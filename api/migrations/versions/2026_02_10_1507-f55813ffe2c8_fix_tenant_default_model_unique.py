"""add unique constraint to tenant_default_models

Revision ID: fix_tenant_default_model_unique
Revises: 9d77545f524e
Create Date: 2026-01-19 15:07:00.000000

"""
from alembic import op
import sqlalchemy as sa


def _is_pg(conn):
    return conn.dialect.name == "postgresql"


# revision identifiers, used by Alembic.
revision = 'f55813ffe2c8'
down_revision = 'c3df22613c99'
branch_labels = None
depends_on = None


def upgrade():
    # First, remove duplicate records keeping only the most recent one per (tenant_id, model_type)
    # This is necessary before adding the unique constraint
    conn = op.get_bind()
    
    # Delete duplicates: keep the record with the latest updated_at for each (tenant_id, model_type)
    # If updated_at is the same, keep the one with the largest id as tiebreaker
    if _is_pg(conn):
        # PostgreSQL: Use DISTINCT ON for efficient deduplication
        conn.execute(sa.text("""
            DELETE FROM tenant_default_models
            WHERE id NOT IN (
                SELECT DISTINCT ON (tenant_id, model_type) id
                FROM tenant_default_models
                ORDER BY tenant_id, model_type, updated_at DESC, id DESC
            )
        """))
    else:
        # MySQL/GaussDB: Use subquery to find and delete duplicates
        # Keep one record per (tenant_id, model_type). id is UUID; GaussDB lacks
        # max(uuid) aggregate, so cast to text for comparison.
        conn.execute(sa.text("""
            DELETE FROM tenant_default_models
            WHERE id::text NOT IN (
                SELECT max_id FROM (
                    SELECT MAX(id::text) AS max_id
                    FROM tenant_default_models
                    GROUP BY tenant_id, model_type
                ) t
            )
        """))
    
    # Now add the unique constraint
    with op.batch_alter_table('tenant_default_models', schema=None) as batch_op:
        batch_op.create_unique_constraint('unique_tenant_default_model_type', ['tenant_id', 'model_type'])


def downgrade():
    with op.batch_alter_table('tenant_default_models', schema=None) as batch_op:
        batch_op.drop_constraint('unique_tenant_default_model_type', type_='unique')
