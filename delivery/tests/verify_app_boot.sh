#!/bin/sh
# 端到端验证：连 GaussDB + 迁移系统（flask db current）
# 用法（api 容器内）：sh verify_app_boot.sh
# 配置从 .env 读（ENV_FILE 指定路径，默认 ../.env）
cd /app/api

ENV_FILE="${ENV_FILE:-../.env}"
if [ -f "$ENV_FILE" ]; then
  DB_HOST=$(grep '^DB_HOST=' "$ENV_FILE" | cut -d= -f2-)
  DB_PORT=$(grep '^DB_PORT=' "$ENV_FILE" | cut -d= -f2-)
  DB_USERNAME=$(grep '^DB_USERNAME=' "$ENV_FILE" | cut -d= -f2-)
  DB_PASSWORD=$(grep '^DB_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)
  DB_DATABASE=$(grep '^DB_DATABASE=' "$ENV_FILE" | cut -d= -f2-)
else
  echo "警告: 未找到 $ENV_FILE，用环境变量"
fi

export DB_TYPE=gaussdb
export DB_HOST DB_PORT DB_USERNAME DB_PASSWORD DB_DATABASE
export SECRET_KEY="${SECRET_KEY:-test-secret-key-for-verification-only-32chars}"
export LOG_LEVEL=INFO
# 用 create_migrations_app（轻量，不需 Redis/向量库）验证连库
echo "===测试 flask db 当前 revision（验证连库 + 迁移系统）==="
echo "目标: ${DB_HOST}:${DB_PORT}/${DB_DATABASE}"
timeout 30 flask db current 2>&1 | tail -10
echo "FLASK_DB_EXIT=$?"
