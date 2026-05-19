"""init schemas

Revision ID: 0001
Revises:
Create Date: 2026-05-18

"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS core")
    op.execute("CREATE SCHEMA IF NOT EXISTS food")
    op.execute("CREATE SCHEMA IF NOT EXISTS content")
    op.execute("CREATE SCHEMA IF NOT EXISTS ai")
    op.execute("CREATE SCHEMA IF NOT EXISTS tracking")
    # Future tiers:
    # op.execute("CREATE SCHEMA IF NOT EXISTS bills")
    # op.execute("CREATE SCHEMA IF NOT EXISTS health")
    # op.execute("CREATE SCHEMA IF NOT EXISTS community")


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS tracking CASCADE")
    op.execute("DROP SCHEMA IF EXISTS ai CASCADE")
    op.execute("DROP SCHEMA IF EXISTS content CASCADE")
    op.execute("DROP SCHEMA IF EXISTS food CASCADE")
    op.execute("DROP SCHEMA IF EXISTS core CASCADE")
