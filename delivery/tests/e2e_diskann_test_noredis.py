#!/usr/bin/env python3
"""DiskANN e2e test - no Redis needed."""
import os, sys, uuid
from contextlib import contextmanager

ENV_FILE = os.environ.get("ENV_FILE", "../.env")
def load_env(path):
    if not os.path.exists(path):
        print(f"Warning: {path} not found")
        return
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())
load_env(ENV_FILE)

os.environ.setdefault("SECRET_KEY", "diskann-test-secret-key-32chars!!")
os.environ.setdefault("DB_TYPE", "gaussdb")
os.environ.setdefault("VECTOR_STORE", "gaussdb")
os.environ.setdefault("GAUSSDB_MIN_CONNECTION", "1")
os.environ.setdefault("GAUSSDB_MAX_CONNECTION", "5")
os.environ["GAUSSDB_INDEX_TYPE"] = "diskann"

sys.path.insert(0, "/app/api")
sys.path.insert(0, "/app/api/providers/vdb/vdb-gaussdb/src")

class MockRedis:
    def __init__(self, *a, **kw): self._d = {}
    def set(self, k, v, **kw): self._d[k] = v; return True
    def setnx(self, k, v):
        if k not in self._d: self._d[k] = v; return 1
        return 0
    def get(self, k): return self._d.get(k)
    def delete(self, k): self._d.pop(k, None); return 1
    def expire(self, k, t): return True
    def exists(self, k): return 1 if k in self._d else 0
    def ping(self): return True
    def setex(self, k, t, v): self._d[k] = v; return True
    def lock(self, name, timeout=20, **kw):
        @contextmanager
        def _lock():
            yield
        return _lock()

from extensions.ext_redis import redis_client
redis_client.initialize(MockRedis())
print("redis_client initialized (mock)", flush=True)

from dify_vdb_gaussdb.gaussdb import GaussDB, GaussDBConfig
from core.rag.models.document import Document

print("===1. Construct adapter (diskann)===", flush=True)
cfg = GaussDBConfig(
    host=os.environ["GAUSSDB_HOST"],
    port=int(os.environ["GAUSSDB_PORT"]),
    user=os.environ["GAUSSDB_USER"],
    password=os.environ["GAUSSDB_PASSWORD"],
    database=os.environ["GAUSSDB_DATABASE"],
    min_connection=int(os.environ["GAUSSDB_MIN_CONNECTION"]),
    max_connection=int(os.environ["GAUSSDB_MAX_CONNECTION"]),
    index_type="diskann",
)
vdb = GaussDB(collection_name="e2e_diskann_test", config=cfg)
print(f"adapter ok, table={vdb.table_name}, index_type={vdb.index_type}", flush=True)

print("===2. Create collection + add vectors===", flush=True)
doc_ids = [str(uuid.uuid4()) for _ in range(3)]
docs = [
    Document(page_content="diskann hello", metadata={"id": doc_ids[0]}),
    Document(page_content="diskann foo", metadata={"id": doc_ids[1]}),
    Document(page_content="diskann test", metadata={"id": doc_ids[2]}),
]
embeddings = [
    [0.1, 0.2, 0.3, 0.4],
    [0.5, 0.6, 0.7, 0.8],
    [0.9, 0.8, 0.7, 0.6],
]
vdb.create(texts=docs, embeddings=embeddings)
print(f"created collection, doc_ids={doc_ids}", flush=True)

print("===3. Search by vector===", flush=True)
results = vdb.search_by_vector(query_vector=[0.1, 0.2, 0.3, 0.5], top_k=2)
print(f"search results: {len(results)}", flush=True)
for r in results:
    content = r.page_content[:50] if hasattr(r, "page_content") else str(r)[:50]
    meta = r.metadata if hasattr(r, "metadata") else {}
    print(f"  content={content} metadata={meta}", flush=True)

print("===4. Delete by ids===", flush=True)
vdb.delete_by_ids(ids=doc_ids)
print(f"deleted {len(doc_ids)} ids", flush=True)

print("===5. Delete collection===", flush=True)
vdb.delete()
print("collection deleted", flush=True)

print("ALL DONE", flush=True)
