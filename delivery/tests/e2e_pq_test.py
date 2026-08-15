#!/usr/bin/env python3
"""GsDiskANN+PQ 端到端测试：1536 维（>1024，触发 enable_pq=true 路径）。
用法（api 容器内）：python e2e_pq_test.py
配置从 .env 读（ENV_FILE 指定路径，默认 ../.env）；强制 index_type=diskann。
需集中式 GaussDB（>1024维），分布式硬限1024无法测。
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

os.environ.setdefault('SECRET_KEY', 'pq-test-secret-key-32chars!!')
os.environ.setdefault('DB_TYPE', 'gaussdb')
os.environ.setdefault('VECTOR_STORE', 'gaussdb')
os.environ.setdefault('GAUSSDB_MIN_CONNECTION', '1')
os.environ.setdefault('GAUSSDB_MAX_CONNECTION', '5')
os.environ['GAUSSDB_INDEX_TYPE'] = 'diskann'  # >1024维必须 diskann

sys.path.insert(0, '/app/api')
sys.path.insert(0, '/app/api/providers/vdb/vdb-gaussdb/src')

import redis
from extensions.ext_redis import redis_client
REDIS_HOST = os.environ.get('REDIS_HOST', 'redis')
redis_client.initialize(redis.Redis(host=REDIS_HOST, port=int(os.environ.get('REDIS_PORT','6379')),
    password=os.environ.get('REDIS_PASSWORD','difyai123456')))

from dify_vdb_gaussdb.gaussdb import GaussDB, GaussDBConfig
from core.rag.models.document import Document

DIM = 1536  # >1024，触发 PQ
print(f'===1. 构造 adapter（diskann+PQ, dim={DIM}）===')
cfg = GaussDBConfig(host=os.environ['GAUSSDB_HOST'], port=int(os.environ['GAUSSDB_PORT']),
    user=os.environ['GAUSSDB_USER'], password=os.environ['GAUSSDB_PASSWORD'],
    database=os.environ['GAUSSDB_DATABASE'],
    min_connection=int(os.environ['GAUSSDB_MIN_CONNECTION']),
    max_connection=int(os.environ['GAUSSDB_MAX_CONNECTION']), index_type='diskann')
vdb = GaussDB(collection_name='e2e_pq_test', config=cfg)
pq_nseg = vdb._calc_pq_nseg(DIM)
enable_pq = DIM > 1024
print(f'pq_nseg={pq_nseg} enable_pq={enable_pq} subgraph_count={1 if enable_pq else 0} enable_vector_copy={not enable_pq}')

print('===2. create（建表 1536维 + GsDiskANN+PQ 索引 + 插入 20 向量）===')
random.seed(42)
texts = [Document(page_content=f'pq doc {i} topic {i%5}', metadata={'id':f'pq{i}'}) for i in range(20)]
emb = [[round(random.random(),4) for _ in range(DIM)] for _ in range(20)]
t0 = time.time()
try:
    vdb.create(texts=texts, embeddings=emb)
    print(f'create ok {time.time()-t0:.1f}s（1536维 + PQ 索引）')
except Exception as e:
    import traceback; traceback.print_exc()
    print(f'create FAIL: {e}'); sys.exit(1)

print('===3. add_texts（追加 5 向量）===')
extra = [Document(page_content=f'extra pq {i}', metadata={'id':f'pq_extra{i}'}) for i in range(5)]
extra_emb = [[round(random.random(),4) for _ in range(DIM)] for _ in range(5)]
vdb.add_texts(documents=extra, embeddings=extra_emb)
print('add ok')

print('===4. search_by_vector（PQ 检索）===')
q = [round(random.random(),4) for _ in range(DIM)]
res = vdb.search_by_vector(q, top_k=5)
print(f'search ok {len(res)} results:')
for r in res[:3]:
    print(f'  score={r.metadata.get("score","?")} content={r.page_content[:30]}')

print('===5. delete collection===')
vdb.delete()
print('delete ok')
print('PQ_E2E_DONE')
