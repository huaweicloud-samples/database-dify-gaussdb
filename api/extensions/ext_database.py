import logging

import gevent
from sqlalchemy import event
from sqlalchemy.pool import Pool

from dify_app import DifyApp
from models.engine import db

logger = logging.getLogger(__name__)

# Global flag to avoid duplicate registration of event listener
_gevent_compatibility_setup: bool = False


def _safe_rollback(connection):
    """Safely rollback database connection.

    Args:
        connection: Database connection object
    """
    try:
        connection.rollback()
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("Failed to rollback connection")


def _setup_gevent_compatibility():
    global _gevent_compatibility_setup  # pylint: disable=global-statement

    # Avoid duplicate registration
    if _gevent_compatibility_setup:
        return

    @event.listens_for(Pool, "reset")
    def _safe_reset(dbapi_connection, connection_record, reset_state):
        if reset_state.terminate_only:
            return

        # Safe rollback for connection
        try:
            hub = gevent.get_hub()
            if hasattr(hub, "loop") and getattr(hub.loop, "in_callback", False):
                gevent.spawn_later(0, lambda: _safe_rollback(dbapi_connection))
            else:
                _safe_rollback(dbapi_connection)
        except (AttributeError, ImportError):
            _safe_rollback(dbapi_connection)

    _gevent_compatibility_setup = True


def _patch_opengauss_inspector():
    """opengauss-sqlalchemy 方言未自定义 get_columns，继承 PG base 的原生 pg_catalog
    查询在 GaussDB 报 'invalid reference to FROM-clause entry for table pg_type'。
    用 information_schema.columns 替代（跨库通用，GaussDB 可用）。
    dify 迁移只用 col['name']，type 用 String 占位（reflection 层要求 TypeEngine）。
    """
    try:
        from opengauss_sqlalchemy.psycopg2 import OpenGaussDialect_psycopg2
    except ImportError:
        return  # 非 gaussdb 环境，无需 patch

    if getattr(OpenGaussDialect_psycopg2, "_gaussdb_inspector_patched", False):
        return

    from sqlalchemy import text, String

    def get_columns(self, connection, table_name, schema=None, **kw):
        schema = schema or self.default_schema_name
        rows = connection.execute(
            text(
                "SELECT column_name, is_nullable, column_default "
                "FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = :table "
                "ORDER BY ordinal_position"
            ),
            {"schema": schema, "table": table_name},
        ).fetchall()
        return [
            {
                "name": name,
                "type": String(),
                "nullable": is_nullable == "YES",
                "default": column_default,
                "autoincrement": False,
            }
            for name, is_nullable, column_default in rows
        ]

    OpenGaussDialect_psycopg2.get_columns = get_columns
    OpenGaussDialect_psycopg2._gaussdb_inspector_patched = True


def _patch_opengauss_empty_string():
    """GaussDB O模式（DBCOMPATIBILITY='A'）把空字符串 '' 当作 NULL。
    dify 大量 Model 用 default="" + nullable=False，运行时 INSERT 传 '' 会被 O模式转 NULL，
    违反 NOT NULL 约束报 NotNullViolation（L25：创建 app 时 sites.custom_disclaimer 即此问题）。

    在 ORM flush 前拦截：把所有字符串列的空串 '' 转成空格 ' '（与迁移 d07474999927 的变通方案一致：
    该迁移用 ' ' 空格回填 NOT NULL 列）。空格在业务上与空串等价，且 O模式不把空格转 NULL。
    只对 opengauss 方言生效（PG 不受影响）。
    """
    try:
        from opengauss_sqlalchemy.psycopg2 import OpenGaussDialect_psycopg2
    except ImportError:
        return  # 非 gaussdb 环境，无需 patch

    if getattr(OpenGaussDialect_psycopg2, "_gaussdb_empty_string_patched", False):
        return

    from sqlalchemy.engine import Engine

    # 拦截 INSERT/UPDATE 的 SQL 参数：空串 '' 转空格 ' '
    # 用 before_cursor_execute（SQL 参数已含 default 值，此时拦截最可靠；
    # before_flush 看不到 default="" 未显式设置的属性）
    @event.listens_for(Engine, "before_cursor_execute")
    def _convert_empty_string_params(
        conn, cursor, statement, parameters, context, executemany
    ):
        if not parameters:
            return
        # parameters 可能是 dict（单行）或 list（executemany）
        if isinstance(parameters, dict):
            params_list = [parameters]
        else:
            params_list = parameters
        for params in params_list:
            if not isinstance(params, dict):
                continue
            for k, v in list(params.items()):
                if v == "":
                    params[k] = " "

    OpenGaussDialect_psycopg2._gaussdb_empty_string_patched = True


def init_app(app: DifyApp):
    _patch_opengauss_inspector()
    _patch_opengauss_empty_string()
    db.init_app(app)
    _setup_gevent_compatibility()

    # Eagerly build the engine so pool_size/max_overflow/etc. come from config
    try:
        with app.app_context():
            _ = db.engine  # triggers engine creation with the configured options
    except Exception:
        logger.exception("Failed to initialize SQLAlchemy engine during app startup")
