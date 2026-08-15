#!/bin/sh
cd /app/api
.venv/bin/python -c "
# 查 opengauss_sqlalchemy 的 entry_points（SQLAlchemy dialect 注册）
from importlib.metadata import entry_points
eps = entry_points()
for ep in eps.select(group='sqlalchemy.dialects') if hasattr(eps,'select') else eps.get('sqlalchemy.dialects',[]):
    if 'opengauss' in ep.name.lower() or 'gauss' in ep.name.lower():
        print('dialect entry_point:', ep.name, '->', ep.value)
# 试常见 dialect 路径
for path in ['opengauss_sqlalchemy.psycopg2', 'opengauss_sqlalchemy.base', 'opengauss_sqlalchemy.dc_psycopg2']:
    try:
        m = __import__(path, fromlist=['*'])
        print(path, 'ok, attrs:', [a for a in dir(m) if 'ialect' in a.lower() or 'OpenGauss' in a][:5])
    except Exception as e:
        print(path, 'FAIL:', e)
# SQLAlchemy 按 scheme opengauss+psycopg2 找 dialect
import sqlalchemy
try:
    d = sqlalchemy.dialects.registry.load('opengauss+psycopg2')
    print('registry opengauss+psycopg2 ok:', d)
except Exception as e:
    print('registry opengauss+psycopg2 FAIL:', e)
print('DONE')
"
