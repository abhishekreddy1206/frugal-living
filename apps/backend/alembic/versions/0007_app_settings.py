"""app settings + feature flag overrides

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-24
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_settings_kv",
        sa.Column("key", sa.String(length=120), primary_key=True),
        sa.Column("value", JSONB, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by_user_id", UUID(as_uuid=True),
                  sa.ForeignKey("core.users.id"), nullable=True),
        schema="core",
    )

    op.create_table(
        "household_settings",
        sa.Column("household_id", UUID(as_uuid=True),
                  sa.ForeignKey("core.households.id"), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("value", JSONB, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by_user_id", UUID(as_uuid=True),
                  sa.ForeignKey("core.users.id"), nullable=True),
        sa.PrimaryKeyConstraint("household_id", "key"),
        schema="core",
    )

    op.create_table(
        "user_settings",
        sa.Column("user_id", UUID(as_uuid=True),
                  sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("value", JSONB, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "key"),
        schema="core",
    )

    op.create_table(
        "feature_flag_overrides",
        # PK defaulted on the Python side via the SA model's default=uuid.uuid4,
        # matching every other UUID PK in this codebase. Avoids any implicit
        # dependency on gen_random_uuid() / pgcrypto.
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("flag_key", sa.String(length=120),
                  sa.ForeignKey("core.feature_flags.key", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("household_id", UUID(as_uuid=True),
                  sa.ForeignKey("core.households.id"), nullable=True),
        sa.Column("user_id", UUID(as_uuid=True),
                  sa.ForeignKey("core.users.id"), nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("created_by_user_id", UUID(as_uuid=True),
                  sa.ForeignKey("core.users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "(household_id IS NULL) <> (user_id IS NULL)",
            name="ff_override_xor",
        ),
        schema="core",
    )

    # Partial unique indexes (a flag can have at most one row per scope target)
    op.create_index(
        "ux_flag_override_household",
        "feature_flag_overrides",
        ["flag_key", "household_id"],
        unique=True,
        schema="core",
        postgresql_where=sa.text("user_id IS NULL"),
    )
    op.create_index(
        "ux_flag_override_user",
        "feature_flag_overrides",
        ["flag_key", "user_id"],
        unique=True,
        schema="core",
        postgresql_where=sa.text("household_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_flag_override_user", table_name="feature_flag_overrides", schema="core")
    op.drop_index("ux_flag_override_household", table_name="feature_flag_overrides", schema="core")
    op.drop_table("feature_flag_overrides", schema="core")
    op.drop_table("user_settings", schema="core")
    op.drop_table("household_settings", schema="core")
    op.drop_table("app_settings_kv", schema="core")
