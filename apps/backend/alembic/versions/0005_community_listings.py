"""community phase 2: communities, members, join_requests, listings, listing_communities

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-24

"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # community.communities
    op.create_table(
        "communities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["core.users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
        schema="community",
    )
    op.create_index("idx_communities_slug", "communities", ["slug"], schema="community")

    # community.community_members
    op.create_table(
        "community_members",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("community_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["community_id"], ["community.communities.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["core.users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("community_id", "user_id", name="uq_community_members_unique"),
        schema="community",
    )
    op.create_index("idx_community_members_user", "community_members", ["user_id"], schema="community")

    # community.community_join_requests
    op.create_table(
        "community_join_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("community_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_user_id", sa.UUID(), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["community_id"], ["community.communities.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["core.users.id"]),
        sa.ForeignKeyConstraint(["decided_by_user_id"], ["core.users.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="community",
    )
    op.create_index(
        "ux_pending_per_user_per_community",
        "community_join_requests",
        ["community_id", "user_id"],
        unique=True,
        schema="community",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "idx_join_requests_community_status",
        "community_join_requests",
        ["community_id", "status"],
        schema="community",
    )

    # community.listings
    op.create_table(
        "listings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=False),
        sa.Column("allowed_exchange_types", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("quantity_available", sa.Integer(), nullable=False),
        sa.Column("share_in_radius", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("share_radius_miles", sa.Integer(), nullable=True),
        sa.Column("availability_status", sa.String(length=16), nullable=False),
        sa.Column("description_override", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["item_id"], ["community.items.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["core.users.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="community",
    )
    op.create_index(
        "ux_one_active_listing_per_item",
        "listings",
        ["item_id"],
        unique=True,
        schema="community",
        postgresql_where=sa.text("deleted_at IS NULL AND availability_status != 'removed'"),
    )
    op.create_index("idx_listings_item", "listings", ["item_id"], schema="community")

    # community.listing_communities
    op.create_table(
        "listing_communities",
        sa.Column("listing_id", sa.UUID(), nullable=False),
        sa.Column("community_id", sa.UUID(), nullable=False),
        sa.Column("added_by_user_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["listing_id"], ["community.listings.id"]),
        sa.ForeignKeyConstraint(["community_id"], ["community.communities.id"]),
        sa.ForeignKeyConstraint(["added_by_user_id"], ["core.users.id"]),
        sa.PrimaryKeyConstraint("listing_id", "community_id"),
        schema="community",
    )
    op.create_index(
        "idx_listing_communities_community",
        "listing_communities",
        ["community_id"],
        schema="community",
    )


def downgrade() -> None:
    op.drop_index("idx_listing_communities_community", table_name="listing_communities", schema="community")
    op.drop_table("listing_communities", schema="community")
    op.drop_index("idx_listings_item", table_name="listings", schema="community")
    op.drop_index("ux_one_active_listing_per_item", table_name="listings", schema="community")
    op.drop_table("listings", schema="community")
    op.drop_index("idx_join_requests_community_status", table_name="community_join_requests", schema="community")
    op.drop_index("ux_pending_per_user_per_community", table_name="community_join_requests", schema="community")
    op.drop_table("community_join_requests", schema="community")
    op.drop_index("idx_community_members_user", table_name="community_members", schema="community")
    op.drop_table("community_members", schema="community")
    op.drop_index("idx_communities_slug", table_name="communities", schema="community")
    op.drop_table("communities", schema="community")
