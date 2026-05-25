"""admin role on users

Revision ID: 0006_admin_role
Revises: 0005_community_listings
Create Date: 2026-05-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("role", sa.String(length=16), nullable=False, server_default="user"),
        schema="core",
    )
    op.create_check_constraint(
        "users_role_valid",
        "users",
        "role IN ('user', 'moderator', 'admin')",
        schema="core",
    )


def downgrade() -> None:
    op.drop_constraint("users_role_valid", "users", schema="core", type_="check")
    op.drop_column("users", "role", schema="core")
