#!/usr/bin/env python3
"""L5+: GaussDB SQL 兼容性测试 — 验证 Dify 使用的 SQL 模式在 GaussDB 上正常工作。
测试: JSONB 操作, 分页, UPSERT, NULL 处理, 字符串函数, 事务回滚。
"""
import os, sys, json, uuid

ENV_FILE = os.environ.get("ENV_FILE", "../.env")
def load_env(path):
    if not os.path.exists(path):
        print(f"Warning: {path} not found"); return
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())
load_env(ENV_FILE)

sys.path.insert(0, "/app/api")
import psycopg2

conn = psycopg2.connect(
    host=os.environ["DB_HOST"], port=int(os.environ["DB_PORT"]),
    user=os.environ["DB_USERNAME"], password=os.environ["DB_PASSWORD"],
    dbname=os.environ["DB_DATABASE"])
cur = conn.cursor()

def cleanup():
    cur.execute("DROP TABLE IF EXISTS _sql_test")
    cur.execute("DROP TABLE IF EXISTS _sql_test_jsonb")
    cur.execute("DROP TABLE IF EXISTS _sql_test_upsert")
    conn.commit()

cleanup()

print("===1. JSONB operations (Dify uses JSONB for config/metadata)===", flush=True)
cur.execute("""
    CREATE TABLE _sql_test_jsonb (
        id UUID PRIMARY KEY,
        name TEXT NOT NULL,
        config JSONB NOT NULL DEFAULT '{}'::jsonb,
        meta JSONB
    )
""")
conn.commit()

test_config = {"model": "gpt-4", "temperature": 0.7, "max_tokens": 1000}
test_meta = {"source": "test", "tags": ["a", "b"]}
uid = str(uuid.uuid4())
cur.execute(
    "INSERT INTO _sql_test_jsonb (id, name, config, meta) VALUES (%s, %s, %s, %s)",
    (uid, "test1", json.dumps(test_config), json.dumps(test_meta))
)
conn.commit()

# Read back
cur.execute("SELECT config->>'model', config->>'temperature', meta->'tags' FROM _sql_test_jsonb WHERE id=%s", (uid,))
row = cur.fetchone()
print(f"  JSONB read: model={row[0]}, temp={row[1]}, tags={row[2]}", flush=True)
assert row[0] == "gpt-4"
assert row[1] == "0.7"

# JSONB update
new_config = '{"model": "gpt-4", "temperature": 0.7, "max_tokens": 2000}'
cur.execute("UPDATE _sql_test_jsonb SET config = %s::jsonb WHERE id=%s", (new_config, uid))
conn.commit()
cur.execute("SELECT config->>'max_tokens' FROM _sql_test_jsonb WHERE id=%s", (uid,))
print(f"  JSONB update: max_tokens={cur.fetchone()[0]}", flush=True)

print("\n===2. Pagination (LIMIT/OFFSET)===", flush=True)
cur.execute("TRUNCATE _sql_test_jsonb")
conn.commit()
for i in range(20):
    cur.execute(
        "INSERT INTO _sql_test_jsonb (id, name, config) VALUES (%s, %s, %s)",
        (str(uuid.uuid4()), f"item_{i}", json.dumps({"index": i}))
    )
conn.commit()

cur.execute("SELECT count(*) FROM _sql_test_jsonb")
total = cur.fetchone()[0]
print(f"  total={total}", flush=True)

cur.execute("SELECT name FROM _sql_test_jsonb ORDER BY name LIMIT 10 OFFSET 5")
page = [r[0] for r in cur.fetchall()]
print(f"  page 2 (offset 5): {page[:3]}...{page[-1]}", flush=True)
assert len(page) == 10

print("\n===3. UPSERT (ON CONFLICT)===", flush=True)
cur.execute("""
    CREATE TABLE _sql_test_upsert (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        counter INT DEFAULT 1
    )
""")
conn.commit()

cur.execute("INSERT INTO _sql_test_upsert (key, value) VALUES ('k1', 'v1')")
conn.commit()

try:
    cur.execute("""
        INSERT INTO _sql_test_upsert (key, value, counter) VALUES ('k1', 'v2', 2)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, counter = _sql_test_upsert.counter + 1
    """)
    conn.commit()
    cur.execute("SELECT value, counter FROM _sql_test_upsert WHERE key='k1'")
    row = cur.fetchone()
    print(f"  UPSERT: value={row[0]}, counter={row[1]}", flush=True)
except Exception as e:
    conn.rollback()
    print(f"  UPSERT failed: {e}", flush=True)

print("\n===4. Empty string vs NULL (GaussDB O-mode)===", flush=True)
cur.execute("DROP TABLE IF EXISTS _sql_test_null")
cur.execute("CREATE TABLE _sql_test_null (id int, v1 TEXT NOT NULL, v2 TEXT)")
conn.commit()

try:
    cur.execute("INSERT INTO _sql_test_null (id, v1, v2) VALUES (1, '', NULL)")
    conn.commit()
    cur.execute("SELECT v1, v1 IS NULL, v1 = '', v2 IS NULL FROM _sql_test_null WHERE id=1")
    row = cur.fetchone()
    print(f"  empty str: v1={repr(row[0])}, v1 IS NULL={row[1]}, v1=''={row[2]}, v2 IS NULL={row[3]}", flush=True)
except Exception as e:
    conn.rollback()
    print(f"  empty str insert failed: {e}", flush=True)

print("\n===5. Transaction rollback===", flush=True)
cur.execute("TRUNCATE _sql_test_upsert")
conn.commit()
cur.execute("INSERT INTO _sql_test_upsert (key, value) VALUES ('before', 'before_val')")
conn.commit()

try:
    cur.execute("INSERT INTO _sql_test_upsert (key, value) VALUES ('rollback', 'rb_val')")
    cur.execute("INSERT INTO _sql_test_upsert (key, value) VALUES ('rollback', 'duplicate')")
    conn.commit()
except Exception as e:
    conn.rollback()
    print(f"  rollback triggered: {type(e).__name__}", flush=True)

cur.execute("SELECT count(*) FROM _sql_test_upsert")
count = cur.fetchone()[0]
print(f"  after rollback: {count} rows (expected 1)", flush=True)
assert count == 1

print("\n===6. Array operations===", flush=True)
cur.execute("DROP TABLE IF EXISTS _sql_test_array")
cur.execute("CREATE TABLE _sql_test_array (id int, tags TEXT[])")
cur.execute("INSERT INTO _sql_test_array VALUES (1, ARRAY['a','b','c']), (2, ARRAY['x','y'])")
conn.commit()

cur.execute("SELECT id, tags FROM _sql_test_array WHERE 'a' = ANY(tags) ORDER BY id")
row = cur.fetchone()
print(f"  ANY() filter: id={row[0]}, tags={row[1]}", flush=True)
assert row[0] == 1

cur.execute("SELECT id, array_length(tags, 1) FROM _sql_test_array ORDER BY id")
rows = cur.fetchall()
print(f"  array_length: {rows}", flush=True)

print("\n===7. String functions (used by Dify search)===", flush=True)
cur.execute("SELECT LENGTH('hello'), CHAR_LENGTH('hello world'), POSITION('lo' IN 'hello'), LOWER('HELLO')")
row = cur.fetchone()
print(f"  LENGTH={row[0]}, CHAR_LENGTH(中文)={row[1]}, POSITION={row[2]}, LOWER={row[3]}", flush=True)

cleanup()
cur.close(); conn.close()
print("\nSQL_COMPAT_TEST_DONE", flush=True)
