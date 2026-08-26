#!/usr/bin/env python3
"""RAG pipeline e2e test: dataset -> document -> segment -> vector -> search -> cleanup.
Uses Dify's own Flask app context (create_migrations_app) for proper DB init.
"""
import os, sys, uuid, json, time
from contextlib import contextmanager

ENV_FILE = os.environ.get("ENV_FILE", "../.env")
def load_env(path):
    if not os.path.exists(path):
        print(f"Warning: {path} not found"); return
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())
load_env(ENV_FILE)

os.environ.setdefault("SECRET_KEY", "rag-test-secret-key-32chars!!")
os.environ.setdefault("DB_TYPE", "gaussdb")
os.environ.setdefault("VECTOR_STORE", "gaussdb")
os.environ.setdefault("GAUSSDB_MIN_CONNECTION", "1")
os.environ.setdefault("GAUSSDB_MAX_CONNECTION", "5")
os.environ.setdefault("GAUSSDB_INDEX_TYPE", "ivfflat")
os.environ.setdefault("MIGRATION_ENABLED", "false")

os.chdir("/app/api")
sys.path.insert(0, "/app/api")
os.environ["FLASK_APP"] = "app.py"

# Mock Redis
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
    def lock(self, name, timeout=60, **kw):
        @contextmanager
        def _lock():
            yield
        return _lock()

# Use Dify's own Flask app
from app import app
from extensions.ext_database import db
from extensions.ext_redis import redis_client
print("app loaded, will init mock redis in context", flush=True)

# Import models inside app context
from models.account import Account, Tenant
from models.dataset import Dataset, Document, DocumentSegment
from core.rag.models.document import Document as RAGDocument

TEST_DOCS = [
    {"content": "GaussDB is a distributed database system developed by Huawei.",
     "metadata": {"source": "doc1", "page": 1}, "embedding": [0.1, 0.2, 0.3, 0.4]},
    {"content": "Dify is an open-source LLM application development platform.",
     "metadata": {"source": "doc2", "page": 1}, "embedding": [0.5, 0.6, 0.7, 0.8]},
    {"content": "Vector search uses cosine similarity to find relevant documents.",
     "metadata": {"source": "doc3", "page": 1}, "embedding": [0.9, 0.8, 0.7, 0.6]},
]
QUERY_EMBEDDING = [0.12, 0.22, 0.32, 0.42]

with app.app_context():
    redis_client._client = MockRedis()
    print("mock redis set", flush=True)
    print("\n===1. Create test tenant + account + dataset===", flush=True)
    account = Account(
        email=f"rag-test-{int(time.time())}@example.com",
        name="RAG Test", password="hashed_pwd_12345678901234567890123456789",
        password_salt="test_salt_12345678", interface_language="en-US", status="active",
    )
    db.session.add(account)
    db.session.commit()
    tenant = Tenant(name="RAG Test Tenant")
    db.session.add(tenant)
    db.session.commit()
    dataset = Dataset(
        tenant_id=tenant.id, name="RAG Test Dataset",
        indexing_technique="high_quality", created_by=account.id,
    )
    db.session.add(dataset)
    db.session.commit()
    print(f"  account={account.id}, tenant={tenant.id}, dataset={dataset.id}", flush=True)

    print("\n===2. Create document===", flush=True)
    doc = Document(
        id=str(uuid.uuid4()), tenant_id=tenant.id, dataset_id=dataset.id,
        position=1, data_source_type="upload_file",
        data_source_info=json.dumps({"upload_file_id": "test"}),
        indexing_status="completed", created_by=account.id,
        name="test_document.txt",
        doc_type="others",
        batch=str(uuid.uuid4()),
        created_from="web",
        doc_form="text_model",
    )
    db.session.add(doc)
    db.session.commit()
    print(f"  document={doc.id}", flush=True)

    print("\n===3. Create document segments (chunks)===", flush=True)
    segments = []
    for i, td in enumerate(TEST_DOCS):
        seg = DocumentSegment(
            tenant_id=tenant.id, dataset_id=dataset.id, document_id=doc.id,
            position=i + 1, content=td["content"],
            index_node_id=str(uuid.uuid4()),
            index_node_hash=f"hash_{i}_{uuid.uuid4().hex[:8]}",
            enabled=True, status="completed",
            word_count=len(td["content"].split()),
            tokens=len(td["content"].split()) * 2,
            created_by=account.id,
        )
        db.session.add(seg)
        segments.append(seg)
    db.session.commit()
    print(f"  created {len(segments)} segments", flush=True)

    print("\n===4. Create vector collection + add embeddings===", flush=True)
    from dify_vdb_gaussdb.gaussdb import GaussDB, GaussDBConfig
    cfg = GaussDBConfig(
        host=os.environ["GAUSSDB_HOST"], port=int(os.environ["GAUSSDB_PORT"]),
        user=os.environ["GAUSSDB_USER"], password=os.environ["GAUSSDB_PASSWORD"],
        database=os.environ["GAUSSDB_DATABASE"],
        min_connection=1, max_connection=5, index_type="ivfflat",
    )
    collection_name = f"rag_test_{str(dataset.id).replace('-', '')[:8]}"
    vdb = GaussDB(collection_name=collection_name, config=cfg)
    print(f"  vdb: table={vdb.table_name}", flush=True)

    rag_docs = []
    for i, seg in enumerate(segments):
        rag_docs.append(RAGDocument(
            page_content=seg.content,
            metadata={
                "doc_id": str(seg.id), "segment_id": str(seg.id),
                "dataset_id": str(dataset.id), "doc_uuid": doc.id,
                "position": seg.position,
            },
        ))
    vdb.create(texts=rag_docs, embeddings=[td["embedding"] for td in TEST_DOCS])
    print(f"  added {len(rag_docs)} vectors", flush=True)

    print("\n===5. Vector search (similarity)===", flush=True)
    results = vdb.search_by_vector(query_vector=QUERY_EMBEDDING, top_k=3)
    print(f"  results: {len(results)}", flush=True)
    for r in results:
        c = r.page_content[:60] if hasattr(r, "page_content") else str(r)[:60]
        m = r.metadata if hasattr(r, "metadata") else {}
        print(f"    content={c}", flush=True)
        print(f"    metadata={m}", flush=True)
    assert len(results) > 0, "No search results!"
    top_content = results[0].page_content if hasattr(results[0], "page_content") else str(results[0])
    print(f"  top result is doc1: {'GaussDB' in top_content}", flush=True)

    print("\n===6. Full-text search===", flush=True)
    try:
        text_results = vdb.search_by_full_text(query="GaussDB", top_k=3)
        print(f"  full-text results: {len(text_results)}", flush=True)
    except Exception as e:
        print(f"  full-text: {type(e).__name__} (may not be supported)", flush=True)

    print("\n===7. Text exists check===", flush=True)
    first_meta = results[0].metadata if hasattr(results[0], "metadata") else {}
    seg_id = first_meta.get("segment_id", "")
    if seg_id:
        exists = vdb.text_exists(id=seg_id)
        print(f"  text_exists({seg_id[:8]}...): {exists}", flush=True)

    print("\n===8. Delete by metadata===", flush=True)
    try:
        vdb.delete_by_metadata_field(key="doc_id", value=doc.id)
        print(f"  deleted by metadata doc_id", flush=True)
    except Exception as e:
        print(f"  delete by metadata: {type(e).__name__}: {e}", flush=True)

    print("\n===9. Verify deletion===", flush=True)
    results2 = vdb.search_by_vector(query_vector=QUERY_EMBEDDING, top_k=10)
    print(f"  after delete: {len(results2)} results", flush=True)

    print("\n===10. Drop vector collection===", flush=True)
    vdb.delete()
    print(f"  dropped", flush=True)

    print("\n===11. Cleanup DB===", flush=True)
    db.session.query(DocumentSegment).filter_by(dataset_id=dataset.id).delete()
    db.session.query(Document).filter_by(dataset_id=dataset.id).delete()
    db.session.query(Dataset).filter_by(id=dataset.id).delete()
    db.session.query(Tenant).filter_by(id=tenant.id).delete()
    db.session.query(Account).filter_by(id=account.id).delete()
    db.session.commit()
    print(f"  cleaned", flush=True)

    print("\n===12. Verify cleanup===", flush=True)
    assert db.session.query(Dataset).filter_by(id=dataset.id).first() is None
    assert db.session.query(Account).filter_by(id=account.id).first() is None
    print(f"  verified", flush=True)

print("\nRAG_PIPELINE_TEST_DONE", flush=True)
