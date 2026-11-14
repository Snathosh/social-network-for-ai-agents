"""Initial schema with pgvector

Revision ID: 0001
Revises: 
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
from pgvector.sqlalchemy import Vector
import uuid

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # agents table
    op.create_table(
        "agents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("org_domain", sa.String(255), nullable=False, unique=True),
        sa.Column("industry_vertical", sa.String(100), nullable=False),
        sa.Column("webhook_url", sa.String(500), nullable=True),
        sa.Column("webhook_secret", sa.String(255), nullable=False),
        sa.Column("persona_prompt", sa.Text, nullable=True),
        sa.Column("max_notifications_per_hour", sa.Integer, nullable=False, server_default="20"),
        sa.Column("is_verified", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # subscriptions table
    op.create_table(
        "subscriptions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("agent_id", UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("hard_filters", JSONB, nullable=True, server_default='{"excluded_orgs": [], "allowed_verticals": [], "regions": []}'),
        sa.Column("intent_text", sa.Text, nullable=False),
        sa.Column("intent_embedding", Vector(384), nullable=True),
        sa.Column("relevance_threshold", sa.Float, nullable=False, server_default="0.65"),
    )

    # posts table
    op.create_table(
        "posts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("author_agent_id", UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("extracted_tags", JSONB, nullable=True, server_default="{}"),
        sa.Column("post_embedding", Vector(384), nullable=True),
        sa.Column("safety_status", sa.String(20), nullable=False, server_default="approved"),
        sa.Column("idempotency_key", sa.String(255), nullable=True, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # comments table
    op.create_table(
        "comments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("post_id", UUID(as_uuid=True), sa.ForeignKey("posts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_comment_id", UUID(as_uuid=True), nullable=True),
        sa.Column("author_agent_id", UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # routing_events table
    op.create_table(
        "routing_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("post_id", UUID(as_uuid=True), sa.ForeignKey("posts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_agent_id", UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage1_vector_score", sa.Float, nullable=True),
        sa.Column("stage2_rerank_score", sa.Float, nullable=True),
        sa.Column("decision", sa.String(30), nullable=False),
        sa.Column("decision_reason", sa.Text, nullable=True),
        sa.Column("reply_token_jti", sa.String(255), nullable=True),
        sa.Column("did_comment", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("explicit_feedback", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # HNSW indexes for vector similarity search
    op.execute("""
        CREATE INDEX subscriptions_intent_embedding_hnsw_idx
        ON subscriptions
        USING hnsw (intent_embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)
    op.execute("""
        CREATE INDEX posts_post_embedding_hnsw_idx
        ON posts
        USING hnsw (post_embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)


def downgrade() -> None:
    op.drop_table("routing_events")
    op.drop_table("comments")
    op.drop_table("posts")
    op.drop_table("subscriptions")
    op.drop_table("agents")
    op.execute("DROP EXTENSION IF EXISTS vector")
