#!/usr/bin/env python3
"""验证 GaussDB 维度上限 + 实例类型（集中式/分布式）。
用法（api 容器内）：python probe_dim_limit.py
配置从 .env 读（ENV_FILE 指定路径，默认 ../.env）。
"""
import os, psycopg2

ENV_FILE = os.environ.get('ENV_FILE', '../.env')
if os.path.exists(ENV_FILE):
    for line in open(ENV_FILE):
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1); os.environ.setdefault(k.strip(), v.strip())

conn = psycopg2.connect(
    host=os.environ.get('DB_HOST','localhost'),
    port=int(os.environ.get('DB_PORT','5432')),
    user=os.environ.get('DB_USERNAME','postgres'),
    password=os.environ.get('DB_PASSWORD',''),
    dbname=os.environ.get('DB_DATABASE','dify'))
cur = conn.cursor()

print('===实例类型===')
try:
    cur.execute("SELECT count(*) FROM pgxc_node WHERE node_type='D'")
    dn = cur.fetchone()[0]
    print(f'datanode 数={dn} → {"分布式" if dn > 0 else "集中式"}')
except Exception:
    conn.rollback()
    try:
        cur.execute("SHOW distrib_kernel_enable")
        print(f'distrib_kernel_enable={cur.fetchone()} → 分布式')
    except Exception as e2:
        conn.rollback(); print(f'无法确定类型: {e2}')

for dim in [1024, 1536, 2048, 4096]:
    tname = f'_dim_test_{dim}'
    try:
        cur.execute(f"DROP TABLE IF EXISTS {tname}")
        cur.execute(f"CREATE TABLE {tname} (id int, v floatvector({dim}))")
        conn.commit(); print(f'{dim} 维建表成功')
    except Exception as e:
        conn.rollback(); print(f'{dim} 维失败: {str(e)[:120]}')
    try:
        cur.execute(f"DROP TABLE IF EXISTS {tname}"); conn.commit()
    except: conn.rollback()
cur.close(); conn.close()
print('DONE')
