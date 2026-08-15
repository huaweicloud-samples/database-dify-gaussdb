#!/bin/sh
# 验证镜像内依赖完整性（import）+ 连 GaussDB
# 用法（api 容器内）：sh verify_final.sh
# 配置从 .env 读（ENV_FILE 指定路径，默认 ../.env）
echo "===用户==="
whoami
echo "===import 验证==="
/app/api/.venv/bin/python -c "
import flask, psycopg2, sqlalchemy, opengauss_sqlalchemy, gmpy2, tiktoken, celery
from dify_vdb_gaussdb.gaussdb import GaussDB
print('flask', flask.__version__)
print('sqlalchemy', sqlalchemy.__version__)
print('gmpy2', gmpy2.version())
print('ALL IMPORTS OK')
"
echo "===连 GaussDB 验证==="
sh /app/api/$(dirname "$0")/verify_url.sh 2>/dev/null || \
/app/api/.venv/bin/python -c "
import os
ENV_FILE = os.environ.get('ENV_FILE', '../.env')
if os.path.exists(ENV_FILE):
    for line in open(ENV_FILE):
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1); os.environ.setdefault(k.strip(), v.strip())
import sqlalchemy
from urllib.parse import quote_plus
url = f\"opengauss+psycopg2://{os.environ.get('DB_USERNAME','postgres')}:{quote_plus(os.environ.get('DB_PASSWORD',''))}@{os.environ.get('DB_HOST','localhost')}:{os.environ.get('DB_PORT','5432')}/{os.environ.get('DB_DATABASE','dify')}\"
e = sqlalchemy.create_engine(url)
with e.connect() as c:
    r = c.execute(sqlalchemy.text('select 1')).scalar()
    print('GaussDB connect ok, select 1 =', r)
print('DONE')
"
