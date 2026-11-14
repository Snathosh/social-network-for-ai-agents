import uuid
from datetime import datetime
from sqlalchemy import (
    String, Text, Boolean, Integer, Float, DateTime, ForeignKey,
    func, text, JSON, Uuid
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSONB = JSON().with_variant(postgresql.JSONB(), "postgresql")
UUID_TYPE = Uuid().with_variant(postgresql.UUID(as_uuid=True), "postgresql")

try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    def Vector(dim):
        return JSON
from typing import Optional, List


class Base(DeclarativeBase):
    pass


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    org_domain: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    industry_vertical: Mapped[str] = mapped_column(String(100), nullable=False)
    webhook_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    webhook_secret: Mapped[str] = mapped_column(String(255), nullable=False)
    persona_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    max_notifications_per_hour: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    subscriptions: Mapped[List["Subscription"]] = relationship("Subscription", back_populates="agent", cascade="all, delete")
    posts: Mapped[List["Post"]] = relationship("Post", back_populates="author_agent", cascade="all, delete")
    comments: Mapped[List["Comment"]] = relationship("Comment", back_populates="author_agent", cascade="all, delete")
    routing_events: Mapped[List["RoutingEvent"]] = relationship("RoutingEvent", back_populates="target_agent", cascade="all, delete")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    hard_filters: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, default=lambda: {"excluded_orgs": [], "allowed_verticals": [], "regions": []})
    intent_text: Mapped[str] = mapped_column(Text, nullable=False)
    intent_embedding: Mapped[Optional[list]] = mapped_column(Vector(384), nullable=True)
    relevance_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.65)

    agent: Mapped["Agent"] = relationship("Agent", back_populates="subscriptions")


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    author_agent_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    extracted_tags: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, default=dict)
    post_embedding: Mapped[Optional[list]] = mapped_column(Vector(384), nullable=True)
    safety_status: Mapped[str] = mapped_column(String(20), nullable=False, default="approved")
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    author_agent: Mapped["Agent"] = relationship("Agent", back_populates="posts")
    comments: Mapped[List["Comment"]] = relationship("Comment", back_populates="post", cascade="all, delete")
    routing_events: Mapped[List["RoutingEvent"]] = relationship("RoutingEvent", back_populates="post", cascade="all, delete")


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    post_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    parent_comment_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID_TYPE, nullable=True)
    author_agent_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    post: Mapped["Post"] = relationship("Post", back_populates="comments")
    author_agent: Mapped["Agent"] = relationship("Agent", back_populates="comments")


class RoutingEvent(Base):
    __tablename__ = "routing_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    post_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    target_agent_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    stage1_vector_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stage2_rerank_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    decision_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reply_token_jti: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    did_comment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    explicit_feedback: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    post: Mapped["Post"] = relationship("Post", back_populates="routing_events")
    target_agent: Mapped["Agent"] = relationship("Agent", back_populates="routing_events")
