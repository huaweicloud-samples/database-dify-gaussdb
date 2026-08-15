#!/usr/bin/env python3
"""GsDiskANN 端到端测试：create/add/search/delete 全链路，验证 diskann 索引 + maintenance_work_mem。
用法（api 容器内）：python e2e_diskann_test.py
配置从 .env 读（ENV_FILE 指定路径，默认 ../.env）；强制 index_type=diskann。
"""
import os, time, sys, random

ENV_FILE = os.environ.get('ENV_FILE', '../.env')
def load_env(path):
    if not os.path.exists(path):
        print(f'警告: {path} 不存在，用环境变量或默认值'); return
    for line in open(path):
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line: continue
        k, v = line.split('=', 1); os.environ.setdefault(k.strip(), v.strip())
load_env(ENV_FILE)

os.environ.setdefault('SECRET_KEY', 'diskann-test-secret-key-32chars!!')
os.environ.setdefault('DB_TYPE', 'gaussdb')
os.environ.setdefault('VECTOR_STORE', 'gaussdb')
os.environ.setdefault('GAUSSDB_MIN_CONNECTION', '1')
os.environ.setdefault('GAUSSDB_MAX_CONNECTION', '5')
os.environ['GAUSSDB_INDEX_TYPE'] = 'diskann'  # 强制 diskann

sys.path.insert(0, '/app/api')
sys.path.insert(0, '/app/api/providers/vdb/vdb-gaussdb/src')

import redis
from extensions.ext_redis import redis_client
REDIS_HOST = os.environ.get('REDIS_HOST', 'redis')
redis_client.initialize(redis.Redis(host=REDIS_HOST, port=int(os.environ.get('REDIS_PORT','6379')),
    password=os.environ.get('REDIS_PASSWORD','difyai123456')))
print('redis ok')

from dify_vdb_gaussdb.gaussdb import GaussDB, GaussDBConfig
from core.rag.models.document import Document

print('===1. 构造 adapter（diskann）===')
cfg = GaussDBConfig(host=os.environ['GAUSSDB_HOST'], port=int(os.environ['GAUSSDB_PORT']),
    user=os.environ['GAUSSDB_USER'], password=os.environ['GAUSSDB_PASSWORD'],
    database=os.environ['GAUSSDB_DATABASE'],
    min_connection=int(os.environ['GAUSSDB_MIN_CONNECTION']),
    max_connection=int(os.environ['GAUSSDB_MAX_CONNECTION']), index_type='diskann')
vdb = GaussDB(collection_name='e2e_diskann_test', config=cfg)
print(f'adapter ok, table={vdb.table_name}, index_type={vdb.index_type}')

print('===2. create（建表 + GsDiskANN 索引 + 插入 20 向量）===')
texts = [Document(page_content=f'document content number {i} about topic {i%5}', metadata={'id':f'doc{i}','topic':str(i%5)}) for i in range(20)]
emb = [[round(random.random(),4) for _ in range(4)] for _ in range(20)]
t0 = time.time()
vdb.create(texts=texts, embeddings=emb)
print(f'create ok {time.time()-t0:.1f}s（含 GsDiskANN 建索引 + SET maintenance_work_mem）')

print('===3. add_texts（追加 5 向量）===')
extra = [Document(page_content=f'extra doc {i}', metadata={'id':f'extra{i}'}) for i in range(5)]
extra_emb = [[round(random.random(),4) for _ in range(4)] for _ in range(5)]
vdb.add_texts(documents=extra, embeddings=extra_emb)
print('add ok')

print('===4. search_by_vector（diskann 检索）===')
res = vdb.search_by_vector([0.5,0.5,0.5,0.5], top_k=5)
print(f'search ok {len(res)} results:')
for r in res[:3]:
    score = r.metadata.get('score','?')
    print(f'  score={score} content={r.page_content[:40]}')

print('===5. delete_by_metadata_field===')
vdb.delete_by_metadata_field('id', 'extra0')
print('delete_by_metadata ok')

print('===6. delete collection（清理）===')
vdb.delete()
print('delete ok')
print('DISKANN_E2E_DONE')
