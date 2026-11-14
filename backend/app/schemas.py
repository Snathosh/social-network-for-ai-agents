from __future__ import annotations
from datetime import datetime
from typing import Optional, List, Any
from uuid import UUID
from pydantic import BaseModel, Field, field_validator


# --- Agent Schemas ---

class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r'^[a-z0-9\-]+$')
    org_domain: str = Field(..., min_length=3)
    industry_vertical: str
    webhook_url: Optional[str] = None
    persona_prompt: Optional[str] = None
    max_notifications_per_hour: int = Field(default=20, ge=1, le=200)
    intent_text: str = Field(..., min_length=10)
    hard_filters: Optional[dict] = None


class AgentResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    org_domain: str
    industry_vertical: str
    webhook_url: Optional[str]
    persona_prompt: Optional[str]
    max_notifications_per_hour: int
    is_verified: bool
    created_at: datetime
    intent_text: Optional[str] = None
    relevance_threshold: Optional[float] = None
    hourly_usage: Optional[int] = None

    model_config = {"from_attributes": True}


# --- Post Schemas ---

class PostCreate(BaseModel):
    author_agent_slug: str
    content: str = Field(..., min_length=1, max_length=5000)


class CommentResponse(BaseModel):
    id: UUID
    post_id: UUID
    parent_comment_id: Optional[UUID]
    author_agent_id: UUID
    author_agent_name: Optional[str] = None
    author_agent_slug: Optional[str] = None
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class RoutingEventResponse(BaseModel):
    id: UUID
    post_id: UUID
    target_agent_id: UUID
    target_agent_name: Optional[str] = None
    target_agent_slug: Optional[str] = None
    stage1_vector_score: Optional[float]
    stage2_rerank_score: Optional[float]
    decision: str
    decision_reason: Optional[str]
    reply_token_jti: Optional[str]
    did_comment: bool
    explicit_feedback: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class PostResponse(BaseModel):
    id: UUID
    author_agent_id: UUID
    author_agent_name: Optional[str] = None
    author_agent_slug: Optional[str] = None
    content: str
    extracted_tags: Optional[Any]
    safety_status: str
    created_at: datetime
    comments: List[CommentResponse] = []
    routing_events: List[RoutingEventResponse] = []

    model_config = {"from_attributes": True}


# --- Comment Schemas ---

class CommentCreate(BaseModel):
    author_agent_slug: str
    content: str = Field(..., min_length=1, max_length=2000)
    reply_token: str
    parent_comment_id: Optional[UUID] = None


# --- Notification/Feedback Schemas ---

class FeedbackCreate(BaseModel):
    feedback: str = Field(..., pattern=r'^(relevant|irrelevant)$')


class FeedbackResponse(BaseModel):
    event_id: UUID
    feedback: str
    new_threshold: Optional[float] = None
    message: str
