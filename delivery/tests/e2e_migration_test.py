#!/usr/bin/env python3
"""L2+: 数据库迁移全量测试 — flask db upgrade 建全表 + 验证 schema。
用法（api 容器内）：python e2e_migration_test.py
"""
import os, sys, subprocess

ENV_FILE = os.environ.get("ENV_FILE", "../.env")
def load_env(path):
    if not os.path.exists(path):
        print(f"Warning: {path} not found"); return
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())
load_env(ENV_FILE)

os.environ.setdefault("SECRET_KEY", "migration-test-secret-key-32chars!!")
os.environ.setdefault("DB_TYPE", "gaussdb")
os.environ.setdefault("MIGRATION_ENABLED", "true")
os.environ.setdefault("VECTOR_STORE", "gaussdb")

sys.path.insert(0, "/app/api")
os.chdir("/app/api")

print("===1. Run flask db upgrade (create all tables)===", flush=True)
r = subprocess.run(
    ["/app/api/.venv/bin/flask", "db", "upgrade"],
    capture_output=True, timeout=300,
    env={**os.environ, "FLASK_APP": "app.py"}
)
print(f"  rc={r.returncode}", flush=True)
stdout = r.stdout.decode("utf-8", errors="replace")
stderr = r.stderr.decode("utf-8", errors="replace")
if stdout: print(f"  stdout: {stdout[:500]}", flush=True)
if stderr: print(f"  stderr: {stderr[:500]}", flush=True)

print("\n===2. Verify core tables exist===", flush=True)
import psycopg2
conn = psycopg2.connect(
    host=os.environ["DB_HOST"], port=int(os.environ["DB_PORT"]),
    user=os.environ["DB_USERNAME"], password=os.environ["DB_PASSWORD"],
    dbname=os.environ["DB_DATABASE"])
cur = conn.cursor()

expected_core = [
    "accounts", "tenants", "tenant_account_joins", "apps", "sites",
    "datasets", "documents", "document_segments",
    "dify_setups", "alembic_version",
    "api_tokens", "api_based_extensions", "end_users",
    "conversations", "messages", "message_feedbacks",
    "workflows", "workflow_runs",
]
cur.execute("""
    SELECT tablename FROM pg_tables 
    WHERE schemaname='public' ORDER BY tablename
""")
actual_tables = {r[0] for r in cur.fetchall()}
print(f"  Total tables: {len(actual_tables)}", flush=True)

missing = [t for t in expected_core if t not in actual_tables]
if missing:
    print(f"  MISSING: {missing}", flush=True)
else:
    print(f"  All {len(expected_core)} core tables present", flush=True)

print("\n===3. Check alembic_version===", flush=True)
try:
    cur.execute("SELECT version_num FROM alembic_version")
    row = cur.fetchone()
    print(f"  Migration version: {row[0] if row else 'empty'}", flush=True)
except Exception as e:
    conn.rollback()
    print(f"  ERROR: {e}", flush=True)

print("\n===4. Check table columns (accounts)===", flush=True)
cur.execute("""
    SELECT column_name, data_type FROM information_schema.columns 
    WHERE table_name='accounts' ORDER BY ordinal_position
""")
cols = cur.fetchall()
print(f"  accounts table: {len(cols)} columns", flush=True)
for name, dtype in cols[:10]:
    print(f"    {name}: {dtype}", flush=True)

print("\n===5. Check JSONB columns (sites)===", flush=True)
cur.execute("""
    SELECT column_name, data_type FROM information_schema.columns 
    WHERE table_name='sites' AND data_type LIKE '%json%'
""")
jsonb_cols = cur.fetchall()
print(f"  JSONB columns: {jsonb_cols}", flush=True)

cur.close(); conn.close()
print("\nMIGRATION_TEST_DONE", flush=True)
