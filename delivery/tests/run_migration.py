import os, sys, traceback

ENV_FILE = os.environ.get("ENV_FILE", "../.env")
if os.path.exists(ENV_FILE):
    for line in open(ENV_FILE):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

os.environ["FLASK_APP"] = "app.py"
os.environ.setdefault("SECRET_KEY", "migration-test-secret-key-32chars!!")
os.environ.setdefault("DB_TYPE", "gaussdb")
os.environ.setdefault("VECTOR_STORE", "gaussdb")
os.environ.setdefault("MIGRATION_ENABLED", "true")

os.chdir("/app/api")
sys.path.insert(0, "/app/api")

try:
    from app import app
    with app.app_context():
        from flask_migrate import upgrade
        print("Running flask db upgrade...", flush=True)
        upgrade(directory="/app/api/migrations")
        print("MIGRATION_SUCCESS", flush=True)
except Exception as e:
    print(f"MIGRATION_FAILED: {type(e).__name__}: {e}", flush=True)
    traceback.print_exc()
