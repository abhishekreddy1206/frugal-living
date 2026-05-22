"""community schema + items table

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-22

"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS community")
    op.create_table(
        "items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("household_id", sa.UUID(), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("tags", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("condition", sa.String(length=16), nullable=True),
        sa.Column("estimated_value_usd", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("location", sa.String(length=120), nullable=True),
        sa.Column("acquired_on", sa.Date(), nullable=True),
        sa.Column("photo_url", sa.String(length=500), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["household_id"], ["core.households.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["core.users.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="community",
    )
    op.create_index(
        "idx_items_household_category",
        "items",
        ["household_id", "category"],
        unique=False,
        schema="community",
    )


def downgrade() -> None:
    op.drop_index(
        "idx_items_household_category", table_name="items", schema="community"
    )
    op.drop_table("items", schema="community")
    op.execute("DROP SCHEMA IF EXISTS community CASCADE")
