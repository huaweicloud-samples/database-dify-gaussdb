#!/usr/bin/env python3
"""Vector DB e2e test (IVFFLAT) - no Redis needed."""
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

os.environ.setdefault("SECRET_KEY", "vec-test-secret-key-32chars!!")
os.environ.setdefault("DB_TYPE", "gaussdb")
os.environ.setdefault("VECTOR_STORE", "gaussdb")
os.environ.setdefault("GAUSSDB_MIN_CONNECTION", "1")
os.environ.setdefault("GAUSSDB_MAX_CONNECTION", "5")
os.environ.setdefault("GAUSSDB_INDEX_TYPE", "ivfflat")

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

print("===1. Construct adapter===", flush=True)
cfg = GaussDBConfig(
    host=os.environ["GAUSSDB_HOST"],
    port=int(os.environ["GAUSSDB_PORT"]),
    user=os.environ["GAUSSDB_USER"],
    password=os.environ["GAUSSDB_PASSWORD"],
    database=os.environ["GAUSSDB_DATABASE"],
    min_connection=int(os.environ["GAUSSDB_MIN_CONNECTION"]),
    max_connection=int(os.environ["GAUSSDB_MAX_CONNECTION"]),
    index_type=os.environ.get("GAUSSDB_INDEX_TYPE", "ivfflat"),
)
vdb = GaussDB(collection_name="e2e_vec_test", config=cfg)
print(f"adapter ok, table={vdb.table_name}, index_type={vdb.index_type}", flush=True)

print("===2. Create collection + add vectors===", flush=True)
doc_ids = [str(uuid.uuid4()) for _ in range(3)]
docs = [
    Document(page_content="hello world", metadata={"id": doc_ids[0]}),
    Document(page_content="foo bar baz", metadata={"id": doc_ids[1]}),
    Document(page_content="test data here", metadata={"id": doc_ids[2]}),
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
    # Document objects returned by search may have metadata with score
    meta = r.metadata if hasattr(r, "metadata") else {}
    content = r.page_content[:50] if hasattr(r, "page_content") else str(r)[:50]
    print(f"  content={content} metadata={meta}", flush=True)

print("===4. Add more texts===", flush=True)
doc_id4 = str(uuid.uuid4())
docs2 = [Document(page_content="extra vector", metadata={"id": doc_id4})]
embeddings2 = [[0.3, 0.4, 0.5, 0.6]]
vdb.add_texts(documents=docs2, embeddings=embeddings2)
print(f"added 1 more, id={doc_id4}", flush=True)

print("===5. Search again===", flush=True)
results2 = vdb.search_by_vector(query_vector=[0.3, 0.4, 0.5, 0.6], top_k=3)
print(f"search results: {len(results2)}", flush=True)
for r in results2:
    content = r.page_content[:50] if hasattr(r, "page_content") else str(r)[:50]
    print(f"  content={content}", flush=True)

print("===6. Text exists check===", flush=True)
exists = vdb.text_exists(id=doc_ids[0])
print(f"text_exists({doc_ids[0][:8]}...): {exists}", flush=True)

print("===7. Get by ids===", flush=True)
got = vdb.get_by_ids(ids=[doc_ids[0]])
print(f"get_by_ids: {len(got)} results", flush=True)

print("===8. Delete by ids===", flush=True)
all_ids = doc_ids + [doc_id4]
vdb.delete_by_ids(ids=all_ids)
print(f"deleted {len(all_ids)} ids", flush=True)

print("===9. Verify deletion===", flush=True)
results3 = vdb.search_by_vector(query_vector=[0.1, 0.2, 0.3, 0.5], top_k=10)
print(f"search after delete: {len(results3)} results", flush=True)

print("===10. Delete collection===", flush=True)
vdb.delete()
print("collection deleted", flush=True)

print("ALL DONE", flush=True)
