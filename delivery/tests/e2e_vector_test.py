#!/usr/bin/env python3
"""向量数据库端到端测试（IVFFLAT）：直接调 GaussDB adapter，测 create/add/search/delete 全链路。
用法（api 容器内）：python e2e_vector_test.py
配置从 .env 读（ENV_FILE 环境变量指定路径，默认 ../.env）；容器内 redis 需在跑。
"""
import os, time, sys

# --- 从 .env 读配置 ---
ENV_FILE = os.environ.get('ENV_FILE', '../.env')
def load_env(path):
    if not os.path.exists(path):
        print(f'警告: {path} 不存在，用环境变量或默认值')
        return
    for line in open(path):
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())
load_env(ENV_FILE)

# 设 dify 必需的默认值（测试用）
os.environ.setdefault('SECRET_KEY', 'vec-test-secret-key-32chars!!')
os.environ.setdefault('DB_TYPE', 'gaussdb')
os.environ.setdefault('VECTOR_STORE', 'gaussdb')
os.environ.setdefault('GAUSSDB_MIN_CONNECTION', '1')
os.environ.setdefault('GAUSSDB_MAX_CONNECTION', '5')
os.environ.setdefault('GAUSSDB_INDEX_TYPE', 'ivfflat')

sys.path.insert(0, '/app/api')
sys.path.insert(0, '/app/api/providers/vdb/vdb-gaussdb/src')

# 初始化 redis_client（adapter 用它加锁防并发建表；容器内 redis 服务名 redis）
import redis
from extensions.ext_redis import redis_client
REDIS_HOST = os.environ.get('REDIS_HOST', 'redis')
REDIS_PORT = int(os.environ.get('REDIS_PORT', '6379'))
REDIS_PWD = os.environ.get('REDIS_PASSWORD', 'difyai123456')
redis_client.initialize(redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PWD))
print(f'redis_client initialized ({REDIS_HOST}:{REDIS_PORT})')

from dify_vdb_gaussdb.gaussdb import GaussDB, GaussDBConfig
from core.rag.models.document import Document

print('===1. 构造 adapter===')
cfg = GaussDBConfig(
    host=os.environ['GAUSSDB_HOST'], port=int(os.environ['GAUSSDB_PORT']),
    user=os.environ['GAUSSDB_USER'], password=os.environ['GAUSSDB_PASSWORD'],
    database=os.environ['GAUSSDB_DATABASE'],
    min_connection=int(os.environ['GAUSSDB_MIN_CONNECTION']),
    max_connection=int(os.environ['GAUSSDB_MAX_CONNECTION']),
    index_type=os.environ['GAUSSDB_INDEX_TYPE'],
)
vdb = GaussDB(collection_name='e2e_vec_test', config=cfg)
print(f'adapter ok (table={vdb.table_name}, index={vdb.index_type})')

print('===2. create（建表+索引+插入）===')
texts = [
    Document(page_content='GaussDB is a distributed database', metadata={'id':'doc1'}),
    Document(page_content='Dify is an AI application platform', metadata={'id':'doc2'}),
    Document(page_content='Vector search enables semantic retrieval', metadata={'id':'doc3'}),
]
emb = [[0.1,0.2,0.3,0.4],[0.2,0.3,0.4,0.5],[0.3,0.4,0.5,0.6]]
t0=time.time(); vdb.create(texts=texts, embeddings=emb); print(f'create ok {time.time()-t0:.1f}s')

print('===3. add_texts===')
vdb.add_texts(documents=[Document(page_content='OpenGauss vector extension', metadata={'id':'doc4'})], embeddings=[[0.4,0.5,0.6,0.7]])
print('add ok')

print('===4. search_by_vector===')
res = vdb.search_by_vector([0.15,0.25,0.35,0.45], top_k=3)
print(f'search ok {len(res)} results:')
for r in res: print(f'  {r}')

print('===5. delete_by_metadata_field（按 metadata.id 删 doc4）===')
vdb.delete_by_metadata_field('id', 'doc4'); print('delete_by_metadata ok')

print('===5b. delete_by_ids（用真实 UUID）===')
with vdb._get_cursor() as cur:
    cur.execute(f"SELECT id FROM {vdb.table_name} LIMIT 1")
    row = cur.fetchone()
    if row:
        real_uuid = str(row[0])
        vdb.delete_by_ids([real_uuid])
        print(f'delete_by_ids ok (uuid={real_uuid[:8]}...)')
    else:
        print('无数据，跳过 delete_by_ids')

print('===6. delete collection===')
vdb.delete(); print('delete ok')
print('VEC_E2E_DONE')
