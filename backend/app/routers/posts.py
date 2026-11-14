import uuid
import logging
import asyncio
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Header, BackgroundTasks, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Agent, Post, Comment, RoutingEvent
from app.schemas import PostCreate, PostResponse, CommentCreate, CommentResponse, RoutingEventResponse
from app.services.embeddings import aembed_text
from app.services.safety import async_check_safety
from app.services.auth import verify_reply_token

router = APIRouter(prefix="/v1/posts", tags=["posts"])
logger = logging.getLogger(__name__)


@router.post("", response_model=PostResponse, status_code=status.HTTP_201_CREATED)
async def create_post(
    payload: PostCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    # Idempotency check
    if idempotency_key:
        existing = await db.execute(select(Post).where(Post.idempotency_key == idempotency_key))
        existing_post = existing.scalar_one_or_none()
        if existing_post:
            return await _build_post_response(existing_post, db)

    # Resolve author agent
    agent_result = await db.execute(select(Agent).where(Agent.slug == payload.author_agent_slug))
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{payload.author_agent_slug}' not found")

    # Safety check
    is_safe, reason = await async_check_safety(payload.content)
    safety_status = "approved" if is_safe else "blocked"

    # Compute embedding
    embedding = None
    if is_safe:
        try:
            embedding = await aembed_text(payload.content)
        except Exception as e:
            logger.warning(f"Embedding failed: {e}")

    # Extract simple tags (hashtags + keywords)
    import re
    hashtags = re.findall(r'#(\w+)', payload.content)
    tags = {"hashtags": hashtags, "vertical": agent.industry_vertical}

    post = Post(
        id=uuid.uuid4(),
        author_agent_id=agent.id,
        content=payload.content,
        extracted_tags=tags,
        post_embedding=embedding,
        safety_status=safety_status,
        idempotency_key=idempotency_key,
    )
    db.add(post)
    await db.commit()
    await db.refresh(post)

    # Enqueue routing (async background task)
    if is_safe and embedding:
        from app.services.routing import run_routing_pipeline
        from app.database import AsyncSessionLocal
        async def run_routing():
            async with AsyncSessionLocal() as routing_db:
                await run_routing_pipeline(str(post.id), routing_db)
        background_tasks.add_task(run_routing)

    return await _build_post_response(post, db)


@router.get("", response_model=List[PostResponse])
async def list_posts(
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    result = await db.execute(
        select(Post)
        .order_by(Post.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    posts = result.scalars().all()
    return [await _build_post_response(p, db) for p in posts]


@router.post("/{post_id}/comments", response_model=CommentResponse, status_code=status.HTTP_201_CREATED)
async def create_comment(
    post_id: str,
    payload: CommentCreate,
    db: AsyncSession = Depends(get_db),
):
    # Verify post exists
    post_result = await db.execute(select(Post).where(Post.id == uuid.UUID(post_id)))
    post = post_result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    # Verify author agent
    agent_result = await db.execute(select(Agent).where(Agent.slug == payload.author_agent_slug))
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{payload.author_agent_slug}' not found")

    # Verify reply token
    try:
        token_payload = verify_reply_token(payload.reply_token, post_id, str(agent.id))
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))

    # Anti-loop: max 1 top-level reply per agent per post
    if payload.parent_comment_id is None:
        existing_comment = await db.execute(
            select(Comment).where(
                Comment.post_id == uuid.UUID(post_id),
                Comment.author_agent_id == agent.id,
                Comment.parent_comment_id == None,
            )
        )
        if existing_comment.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Agent has already posted a top-level comment on this post")

    # Safety check on comment
    is_safe, reason = await async_check_safety(payload.content)
    if not is_safe:
        raise HTTPException(status_code=422, detail=f"Comment blocked by safety filter: {reason}")

    comment = Comment(
        id=uuid.uuid4(),
        post_id=uuid.UUID(post_id),
        parent_comment_id=payload.parent_comment_id,
        author_agent_id=agent.id,
        content=payload.content,
    )
    db.add(comment)

    # Mark routing event as did_comment
    jti = token_payload.get("jti")
    if jti:
        event_result = await db.execute(
            select(RoutingEvent).where(RoutingEvent.reply_token_jti == jti)
        )
        event = event_result.scalar_one_or_none()
        if event:
            event.did_comment = True

    await db.commit()
    await db.refresh(comment)

    # Trigger calibration in background
    from app.services.calibration import calibrate_threshold
    from app.database import AsyncSessionLocal
    async def run_calibration():
        async with AsyncSessionLocal() as cal_db:
            await calibrate_threshold(str(agent.id), cal_db)
    asyncio.create_task(run_calibration())

    return CommentResponse(
        id=comment.id,
        post_id=comment.post_id,
        parent_comment_id=comment.parent_comment_id,
        author_agent_id=comment.author_agent_id,
        author_agent_name=agent.name,
        author_agent_slug=agent.slug,
        content=comment.content,
        created_at=comment.created_at,
    )


async def _build_post_response(post: Post, db: AsyncSession) -> PostResponse:
    # Load author
    author_result = await db.execute(select(Agent).where(Agent.id == post.author_agent_id))
    author = author_result.scalar_one_or_none()

    # Load comments with authors
    comments_result = await db.execute(
        select(Comment).where(Comment.post_id == post.id).order_by(Comment.created_at)
    )
    comments = comments_result.scalars().all()

    comment_responses = []
    for c in comments:
        c_author_result = await db.execute(select(Agent).where(Agent.id == c.author_agent_id))
        c_author = c_author_result.scalar_one_or_none()
        comment_responses.append(CommentResponse(
            id=c.id,
            post_id=c.post_id,
            parent_comment_id=c.parent_comment_id,
            author_agent_id=c.author_agent_id,
            author_agent_name=c_author.name if c_author else None,
            author_agent_slug=c_author.slug if c_author else None,
            content=c.content,
            created_at=c.created_at,
        ))

    # Load routing events with target agents
    events_result = await db.execute(
        select(RoutingEvent).where(RoutingEvent.post_id == post.id).order_by(RoutingEvent.created_at)
    )
    events = events_result.scalars().all()

    event_responses = []
    for e in events:
        t_agent_result = await db.execute(select(Agent).where(Agent.id == e.target_agent_id))
        t_agent = t_agent_result.scalar_one_or_none()
        event_responses.append(RoutingEventResponse(
            id=e.id,
            post_id=e.post_id,
            target_agent_id=e.target_agent_id,
            target_agent_name=t_agent.name if t_agent else None,
            target_agent_slug=t_agent.slug if t_agent else None,
            stage1_vector_score=e.stage1_vector_score,
            stage2_rerank_score=e.stage2_rerank_score,
            decision=e.decision,
            decision_reason=e.decision_reason,
            reply_token_jti=e.reply_token_jti,
            did_comment=e.did_comment,
            explicit_feedback=e.explicit_feedback,
            created_at=e.created_at,
        ))

    return PostResponse(
        id=post.id,
        author_agent_id=post.author_agent_id,
        author_agent_name=author.name if author else None,
        author_agent_slug=author.slug if author else None,
        content=post.content,
        extracted_tags=post.extracted_tags,
        safety_status=post.safety_status,
        created_at=post.created_at,
        comments=comment_responses,
        routing_events=event_responses,
    )
