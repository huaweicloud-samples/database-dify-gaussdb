#!/usr/bin/env python3
# 实测 GaussDB O模式空串→NULL 行为 + behavior_compat_options
# 用法（api 容器内）：python probe_empty_str.py
# 配置从 .env 读（ENV_FILE 指定路径，默认 ../.env）
import os, psycopg2

ENV_FILE = os.environ.get('ENV_FILE', '../.env')
if os.path.exists(ENV_FILE):
    for line in open(ENV_FILE):
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1); os.environ.setdefault(k.strip(), v.strip())

DB_NAME = os.environ.get('DB_DATABASE', 'dify')
conn = psycopg2.connect(
    host=os.environ.get('DB_HOST','localhost'),
    port=int(os.environ.get('DB_PORT','5432')),
    user=os.environ.get('DB_USERNAME','postgres'),
    password=os.environ.get('DB_PASSWORD',''),
    dbname=DB_NAME)
cur = conn.cursor()

print('===1. DBCOMPATIBILITY===')
cur.execute("SELECT datname, datcompatibility FROM pg_database WHERE datname=%s", (DB_NAME,))
print(cur.fetchall())

print('===2. behavior_compat_options 当前值===')
cur.execute("SHOW behavior_compat_options")
print(cur.fetchone())

print('===3. 空串→NULL 实测===')
cur.execute("CREATE TABLE IF NOT EXISTS _empty_test (id int, v text NOT NULL)")
cur.execute("TRUNCATE _empty_test")
try:
    cur.execute("INSERT INTO _empty_test VALUES (1, '')")
    conn.commit()
    cur.execute("SELECT v IS NULL, v = '' FROM _empty_test WHERE id=1")
    print('插空串成功:', cur.fetchone())
except Exception as e:
    conn.rollback()
    print('插空串失败(预期):', e)

print('===4. 空串查询行为===')
cur.execute("INSERT INTO _empty_test VALUES (2, 'abc')")
conn.commit()
cur.execute("SELECT count(*) FROM _empty_test WHERE v = ''")
print("v = '' 匹配行数(含NULL?):", cur.fetchone())
cur.execute("SELECT count(*) FROM _empty_test WHERE v IS NULL")
print("v IS NULL 行数:", cur.fetchone())

cur.execute("DROP TABLE _empty_test")
conn.commit()
cur.close(); conn.close()
print('DONE')
