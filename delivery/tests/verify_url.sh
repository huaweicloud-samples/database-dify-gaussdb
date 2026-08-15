#!/bin/sh
# 验证 opengauss+psycopg2 dialect 连 GaussDB（create_engine + select 1）
# 用法（api 容器内）：sh verify_url.sh
# 配置从 .env 读（ENV_FILE 指定路径，默认 ../.env）
cd /app/api

ENV_FILE="${ENV_FILE:-../.env}"
.venv/bin/python -c "
import os
ENV_FILE = os.environ.get('ENV_FILE', '../.env')
if os.path.exists(ENV_FILE):
    for line in open(ENV_FILE):
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1); os.environ.setdefault(k.strip(), v.strip())

import sqlalchemy
from urllib.parse import quote_plus
user = os.environ.get('DB_USERNAME','postgres')
pwd = quote_plus(os.environ.get('DB_PASSWORD',''))
host = os.environ.get('DB_HOST','localhost')
port = os.environ.get('DB_PORT','5432')
db = os.environ.get('DB_DATABASE','dify')
url = f'opengauss+psycopg2://{user}:{pwd}@{host}:{port}/{db}'
print(f'连接: {host}:{port}/{db}')
try:
    e = sqlalchemy.create_engine(url)
    print('create_engine ok, dialect:', e.dialect.name)
    with e.connect() as c:
        r = c.execute(sqlalchemy.text('select 1')).scalar()
        print('connect ok, select 1 =', r)
except Exception as ex:
    print('FAIL:', type(ex).__name__, ex)
print('DONE')
"
