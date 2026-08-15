#!/bin/bash
# 端到端 CRUD 测试：init→setup→login→创建app→查询验证→清理
# 测试完删除测试数据（app + admin 账号）
# 用法：在部署机执行（api 服务需在跑），从 .env 读 INIT_PASSWORD 和访问地址
#   bash e2e_crud_test.sh [DIFY_HOST]
#   DIFY_HOST 默认 localhost（走 nginx 端口80），可传实际 IP
set +e

# --- 从 .env 读配置（部署目录的 .env）---
ENV_FILE="${ENV_FILE:-../.env}"
if [ -f "$ENV_FILE" ]; then
  INIT_PWD=$(grep '^INIT_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)
  DIFY_HOST_FROM_ENV=$(grep '^CONSOLE_API_URL=' "$ENV_FILE" | sed 's|.*//||; s|[:/].*||' | head -1)
else
  echo "警告: 未找到 $ENV_FILE，请用 ENV_FILE=路径 指定，或手动设置 INIT_PWD"
  INIT_PWD="${INIT_PWD:-}"
fi

DIFY_HOST="${1:-${DIFY_HOST_FROM_ENV:-localhost}}"
BASE="http://${DIFY_HOST}/console/api"
ADMIN_EMAIL=e2e-test-admin@example.com
ADMIN_NAME=E2EAdmin
ADMIN_PWD=E2eTestPwd2026!@#
# dify 前端 password 是 base64 编码（FieldEncryption.decrypt_field = base64decode）
ADMIN_PWD_B64=$(echo -n "$ADMIN_PWD" | base64)
COOKIE=/tmp/e2e_cookie.txt
APP_ID=""

echo "目标: $BASE | INIT_PWD=${INIT_PWD:+已设置} | admin=$ADMIN_EMAIL"
echo "=========================================="
echo "=== 1. 查 init/setup 状态 ==="
echo "=========================================="
echo "--- init status ---"
curl -s "$BASE/init" | python3 -m json.tool 2>&1 | head -5
echo "--- setup status ---"
curl -s "$BASE/setup" | python3 -m json.tool 2>&1 | head -5

echo "=========================================="
echo "=== 2. init（验证密码）==="
echo "=========================================="
curl -s -X POST "$BASE/init" -H "Content-Type: application/json" \
  -d "{\"password\":\"$INIT_PWD\"}" -c "$COOKIE" | python3 -m json.tool 2>&1 | head -5

echo "=========================================="
echo "=== 3. setup（创建 admin + tenant）==="
echo "=========================================="
# setup 无 decrypt 装饰器，传明文密码（直接 hash 存储）；login 有 decrypt，传 base64
SETUP_RESP=$(curl -s -X POST "$BASE/setup" -H "Content-Type: application/json" \
  -d "{\"email\":\"$ADMIN_EMAIL\",\"name\":\"$ADMIN_NAME\",\"password\":\"$ADMIN_PWD\"}" -b "$COOKIE" -c "$COOKIE")
echo "$SETUP_RESP" | python3 -m json.tool 2>&1 | head -5

echo "=========================================="
echo "=== 4. login（获取 token cookie）==="
echo "=========================================="
LOGIN_RESP=$(curl -s -X POST "$BASE/login" -H "Content-Type: application/json" \
  -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PWD_B64\"}" -b "$COOKIE" -c "$COOKIE")
echo "$LOGIN_RESP" | python3 -m json.tool 2>&1 | head -5

# 提取 csrf_token（从 cookie jar）
CSRF=$(python3 -c "
import re
with open('$COOKIE') as f:
    for line in f:
        if 'csrf_token' in line and not line.startswith('#'):
            print(line.strip().split('\t')[-1]); break
" 2>/dev/null)
echo "CSRF_TOKEN=${CSRF:0:30}..."

echo "=========================================="
echo "=== 5. 查询 apps 列表（验证读）==="
echo "=========================================="
curl -s "$BASE/apps" -H "X-CSRF-Token: $CSRF" -b "$COOKIE" | python3 -m json.tool 2>&1 | head -10

echo "=========================================="
echo "=== 6. 创建 app（验证写）==="
echo "=========================================="
CREATE_RESP=$(curl -s -X POST "$BASE/apps" -H "Content-Type: application/json" -H "X-CSRF-Token: $CSRF" \
  -d '{"name":"E2E-Test-App","mode":"chat","description":"e2e test app"}' -b "$COOKIE" -c "$COOKIE")
echo "$CREATE_RESP" | python3 -m json.tool 2>&1 | head -15
APP_ID=$(echo "$CREATE_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
echo "APP_ID=$APP_ID"

echo "=========================================="
echo "=== 7. 查询创建的 app（验证读+一致性）==="
echo "=========================================="
if [ -n "$APP_ID" ]; then
  curl -s "$BASE/apps/$APP_ID" -H "X-CSRF-Token: $CSRF" -b "$COOKIE" | python3 -m json.tool 2>&1 | head -15
fi

echo "=========================================="
echo "=== 8. 删除测试 app（验证删+清理）==="
echo "=========================================="
if [ -n "$APP_ID" ]; then
  curl -s -X DELETE "$BASE/apps/$APP_ID" -H "X-CSRF-Token: $CSRF" -b "$COOKIE" | python3 -m json.tool 2>&1 | head -5
fi

echo "=========================================="
echo "=== 9. 验证 app 已删除 ==="
echo "=========================================="
curl -s "$BASE/apps/$APP_ID" -b "$COOKIE" | python3 -m json.tool 2>&1 | head -5

echo "=========================================="
echo "=== 测试完成 ==="
echo "=== 注意：admin 账号需手动清理（见后续）==="
echo "=========================================="
echo "DONE"
