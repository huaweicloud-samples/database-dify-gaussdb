import logging
from logging.config import fileConfig

from alembic import context
from flask import current_app

# ========== GaussDB distributed compat layer ==========
# Detect distributed mode once at startup.
# Fix 1 (alembic_version) and Fix 2 (SAVEPOINT tolerance) are always enabled
# because they only trigger on error (no-op on centralized mode).
# Fix 3 (strip FK) and Fix 4 (general DDL tolerance) are ONLY enabled on
# distributed mode to avoid impacting centralized 507.

from alembic.runtime.migration import HeadMaintainer
from alembic.ddl import impl as _ddl_impl
from sqlalchemy import text, event as _sa_event
from sqlalchemy.engine import Engine as _Engine
import re as _re


def _is_distributed_gaussdb(connection):
    """Check if the database is GaussDB distributed mode."""
    try:
        from sqlalchemy import text as _text
        result = connection.execute(_text("SELECT count(*) FROM pgxc_node WHERE node_type = 'D'"))
        return result.scalar() > 0
    except Exception:
        return False


_gaussdb_distributed = None  # cached result, set on first connection


# Fix 1: alembic_version UPDATE -> DELETE+INSERT (always on, harmless on centralized)
def _patched_update_version(self, from_, to_):
    self.context.impl._exec(
        text("DELETE FROM " + self.context.version_table + " WHERE version_num = :from_").bindparams(from_=from_)
    )
    self.context.impl._exec(
        text("INSERT INTO " + self.context.version_table + " (version_num) VALUES (:to_)").bindparams(to_=to_)
    )


HeadMaintainer._update_version = _patched_update_version


# Fix 2: UNIQUE/FK constraint and index creation tolerance via SAVEPOINT (always on,
# only triggers on error so centralized mode is unaffected)
def _make_sp_wrapper(orig, keywords, desc):
    def wrapper(self, *args, **kwargs):
        sp = self.connection.begin_nested()
        try:
            result = orig(self, *args, **kwargs)
            sp.commit()
            return result
        except Exception as e:
            sp.rollback()
            if any(kw in str(e) for kw in keywords):
                logging.getLogger("alembic.env").warning("GaussDB compat: skipped " + desc)
            else:
                raise
    return wrapper


_ddl_impl.DefaultImpl.add_constraint = _make_sp_wrapper(
    _ddl_impl.DefaultImpl.add_constraint,
    ["cannot be enforced to remote nodes", "not yet supported", "FOREIGN KEY"],
    "add_constraint")
_ddl_impl.DefaultImpl.drop_constraint = _make_sp_wrapper(
    _ddl_impl.DefaultImpl.drop_constraint,
    ["does not exist"],
    "drop_constraint")
_ddl_impl.DefaultImpl.create_index = _make_sp_wrapper(
    _ddl_impl.DefaultImpl.create_index,
    ["cannot be enforced to remote nodes", "not yet supported"],
    "create_index")


# Fix 3: strip FOREIGN KEY from CREATE TABLE SQL (distributed only)
def _strip_fk(conn, cursor, statement, parameters, context, executemany):
    global _gaussdb_distributed
    if _gaussdb_distributed is False:
        return statement, parameters
    if _gaussdb_distributed is None:
        _gaussdb_distributed = _is_distributed_gaussdb(conn)
    if not _gaussdb_distributed:
        return statement, parameters
    if statement and "FOREIGN KEY" in statement.upper() and "CREATE TABLE" in statement.upper():
        pattern = ",\\s*CONSTRAINT\\s+\\w+\\s+FOREIGN\\s+KEY\\s*\\([^)]+\\)\\s*REFERENCES\\s+\\w+\\s*\\([^)]+\\)"
        cleaned = _re.sub(pattern, "", statement, flags=_re.IGNORECASE)
        if cleaned != statement:
            logging.getLogger("alembic.env").warning("GaussDB compat: stripped FK from CREATE TABLE")
            return cleaned, parameters
    return statement, parameters


# Fix 4: general DDL tolerance via SAVEPOINT (distributed only)
_original_exec = _ddl_impl.DefaultImpl._exec


def _patched_exec(self, construct, params=None):
    global _gaussdb_distributed
    if _gaussdb_distributed is False:
        return _original_exec(self, construct, params)
    if _gaussdb_distributed is None:
        try:
            _gaussdb_distributed = _is_distributed_gaussdb(self.connection)
        except Exception:
            _gaussdb_distributed = False
    if not _gaussdb_distributed:
        return _original_exec(self, construct, params)
    # Distributed mode: wrap in SAVEPOINT for tolerance
    sp = self.connection.begin_nested()
    try:
        result = _original_exec(self, construct, params)
        sp.commit()
        return result
    except Exception as e:
        sp.rollback()
        err_msg = str(e)
        if ("cannot be enforced to remote nodes" in err_msg
            or "not yet supported" in err_msg
            or "does not exist" in err_msg
            or "syntax error" in err_msg
            or "ON DELETE" in err_msg):
            logging.getLogger("alembic.env").warning("GaussDB compat: skipped DDL (" + err_msg[:60] + ")")
        else:
            raise


_ddl_impl.DefaultImpl._exec = _patched_exec

# ========== End compat layer ==========

config = context.config
fileConfig(config.config_file_name)
logger = logging.getLogger("alembic.env")


def get_engine():
    return current_app.extensions["migrate"].db.engine


def get_engine_url():
    try:
        return get_engine().url.render_as_string(hide_password=False).replace("%", "%%")
    except AttributeError:
        return str(get_engine().url).replace("%", "%%")


config.set_main_option("sqlalchemy.url", get_engine_url())

from models.base import TypeBase


def get_metadata():
    return TypeBase.metadata


def include_object(object, name, type_, reflected, compare_to):
    if type_ == "foreign_key_constraint":
        return False
    else:
        return True


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=get_metadata(), literal_binds=True)
    logger.info("Generating offline migration SQL with url: %s", url)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    def process_revision_directives(context, revision, directives):
        if getattr(config.cmd_opts, "autogenerate", False):
            script = directives[0]
            if script.upgrade_ops.is_empty():
                directives[:] = []
                logger.info("No changes in schema detected.")

    connectable = get_engine()
    _sa_event.listens_for(_Engine, "before_cursor_execute", retval=True)(_strip_fk)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=get_metadata(),
            process_revision_directives=process_revision_directives,
            include_object=include_object,
            **current_app.extensions["migrate"].configure_args
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
