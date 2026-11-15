import uuid
import secrets
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.config import settings
from app.models import Agent, Subscription
from app.schemas import AgentCreate, AgentResponse
from app.services.embeddings import aembed_text
from app.services.rate_limiter import get_current_usage

router = APIRouter(prefix="/v1/agents", tags=["agents"])
logger = logging.getLogger(__name__)


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(payload: AgentCreate, db: AsyncSession = Depends(get_db)):
    # Check slug uniqueness
    existing = await db.execute(select(Agent).where(Agent.slug == payload.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Agent with slug '{payload.slug}' already exists")

    # Check org_domain uniqueness
    existing_domain = await db.execute(select(Agent).where(Agent.org_domain == payload.org_domain))
    if existing_domain.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Agent with domain '{payload.org_domain}' already exists")

    webhook_secret = secrets.token_hex(32)
    agent = Agent(
        id=uuid.uuid4(),
        name=payload.name,
        slug=payload.slug,
        org_domain=payload.org_domain,
        industry_vertical=payload.industry_vertical,
        webhook_url=payload.webhook_url or f"{settings.PUBLIC_API_URL}/mock-agents/{payload.slug}/webhook",
        webhook_secret=webhook_secret,
        persona_prompt=payload.persona_prompt,
        max_notifications_per_hour=payload.max_notifications_per_hour,
        is_verified=True,
    )
    db.add(agent)
    await db.flush()

    # Compute intent embedding
    embedding = None
    try:
        embedding = await aembed_text(payload.intent_text)
    except Exception as e:
        logger.warning(f"Embedding failed for agent {payload.slug}: {e}")

    hard_filters = payload.hard_filters or {"excluded_orgs": [], "allowed_verticals": [], "regions": []}
    sub = Subscription(
        id=uuid.uuid4(),
        agent_id=agent.id,
        hard_filters=hard_filters,
        intent_text=payload.intent_text,
        intent_embedding=embedding,
        relevance_threshold=0.65,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(agent)

    return _build_agent_response(agent, sub, 0)


@router.get("", response_model=List[AgentResponse])
async def list_agents(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Agent).options(selectinload(Agent.subscriptions)).order_by(Agent.created_at)
    )
    agents = result.scalars().all()

    responses = []
    for agent in agents:
        sub = agent.subscriptions[0] if agent.subscriptions else None
        usage = await get_current_usage(str(agent.id))
        responses.append(_build_agent_response(agent, sub, usage))
    return responses


def _build_agent_response(agent: Agent, sub, usage: int) -> AgentResponse:
    return AgentResponse(
        id=agent.id,
        name=agent.name,
        slug=agent.slug,
        org_domain=agent.org_domain,
        industry_vertical=agent.industry_vertical,
        webhook_url=agent.webhook_url,
        persona_prompt=agent.persona_prompt,
        max_notifications_per_hour=agent.max_notifications_per_hour,
        is_verified=agent.is_verified,
        created_at=agent.created_at,
        intent_text=sub.intent_text if sub else None,
        relevance_threshold=sub.relevance_threshold if sub else None,
        hourly_usage=usage,
    )
