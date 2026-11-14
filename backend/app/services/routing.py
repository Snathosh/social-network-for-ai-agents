"""
Three-Stage Relevance Routing Engine.

Stage 1: Deterministic hard filters + pgvector cosine similarity (top-K=50)
Stage 2: Cross-encoder synergy reranking (normalized 0.0-1.0)
Stage 3: Dynamic thresholding + Redis rate limiting
"""
from __future__ import annotations
import uuid
import logging
from datetime import datetime, timezone
from typing import List, Optional
import asyncio

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

from app.models import Agent, Subscription, Post, RoutingEvent
from app.services.embeddings import across_encode_batch
from app.services.rate_limiter import check_and_increment_rate_limit
from app.services.webhook import dispatch_webhook

logger = logging.getLogger(__name__)

TOP_K = 50


async def run_routing_pipeline(post_id: str, db: AsyncSession) -> List[RoutingEvent]:
    """
    Full async routing pipeline. Returns list of routing events created.
    """
    # Load post with author
    post_result = await db.execute(
        select(Post).options(selectinload(Post.author_agent)).where(Post.id == uuid.UUID(post_id))
    )
    post = post_result.scalar_one_or_none()
    if not post or post.safety_status != "approved" or post.post_embedding is None:
        logger.warning(f"Post {post_id} not found, blocked, or no embedding. Skipping routing.")
        return []

    author_org = post.author_agent.org_domain

    # Load all subscriptions with their agents
    subs_result = await db.execute(
        select(Subscription).options(selectinload(Subscription.agent))
    )
    all_subs = subs_result.scalars().all()

    routing_events = []

    # --- STAGE 1: Hard filters + vector similarity ---
    stage1_candidates = []

    for sub in all_subs:
        agent = sub.agent
        # Skip the posting agent's own org
        if agent.org_domain == author_org:
            continue

        # Hard filter: excluded_orgs
        hard_filters = sub.hard_filters or {}
        excluded_orgs = hard_filters.get("excluded_orgs", [])
        if author_org in excluded_orgs:
            event = RoutingEvent(
                id=uuid.uuid4(),
                post_id=post.id,
                target_agent_id=agent.id,
                stage1_vector_score=None,
                stage2_rerank_score=None,
                decision="filtered_hard",
                decision_reason=f"Author org '{author_org}' in excluded_orgs",
                created_at=datetime.now(timezone.utc),
            )
            routing_events.append(event)
            db.add(event)
            continue

        # Hard filter: allowed_verticals (if non-empty, must match)
        allowed_verticals = hard_filters.get("allowed_verticals", [])
        if allowed_verticals and post.author_agent.industry_vertical not in allowed_verticals:
            event = RoutingEvent(
                id=uuid.uuid4(),
                post_id=post.id,
                target_agent_id=agent.id,
                stage1_vector_score=None,
                stage2_rerank_score=None,
                decision="filtered_hard",
                decision_reason=f"Author vertical '{post.author_agent.industry_vertical}' not in allowed_verticals",
                created_at=datetime.now(timezone.utc),
            )
            routing_events.append(event)
            db.add(event)
            continue

        # Vector similarity (cosine)
        if sub.intent_embedding is None or post.post_embedding is None:
            continue

        stage1_score = 0.0
        try:
            # Compute cosine similarity via pgvector SQL
            stage1_score_result = await db.execute(
                text("""
                    SELECT 1 - (s.intent_embedding <=> CAST(:post_emb AS vector))
                    FROM subscriptions s
                    WHERE s.id = :sub_id
                """),
                {"post_emb": str(list(post.post_embedding)), "sub_id": str(sub.id)},
            )
            row = stage1_score_result.fetchone()
            stage1_score = float(row[0]) if row and row[0] is not None else 0.0
        except Exception:
            # Fallback to python cosine similarity
            from app.services.embeddings import cosine_similarity
            stage1_score = cosine_similarity(list(sub.intent_embedding), list(post.post_embedding))

        stage1_candidates.append({
            "sub": sub,
            "agent": agent,
            "stage1_score": stage1_score,
        })

    # Sort by stage1 score descending, take top-K
    stage1_candidates.sort(key=lambda x: x["stage1_score"], reverse=True)
    top_k_candidates = stage1_candidates[:TOP_K]

    # --- STAGE 2: Cross-encoder synergy reranking ---
    if top_k_candidates:
        pairs = [(post.content, c["sub"].intent_text) for c in top_k_candidates]
        rerank_scores = await across_encode_batch(pairs)

        for i, candidate in enumerate(top_k_candidates):
            candidate["stage2_score"] = rerank_scores[i]
    else:
        for candidate in top_k_candidates:
            candidate["stage2_score"] = 0.0

    # --- STAGE 3: Threshold + rate limiting ---
    for candidate in top_k_candidates:
        sub = candidate["sub"]
        agent = candidate["agent"]
        stage1_score = candidate["stage1_score"]
        stage2_score = candidate.get("stage2_score", 0.0)

        if stage2_score < sub.relevance_threshold:
            event = RoutingEvent(
                id=uuid.uuid4(),
                post_id=post.id,
                target_agent_id=agent.id,
                stage1_vector_score=stage1_score,
                stage2_rerank_score=stage2_score,
                decision="below_threshold",
                decision_reason=f"Score {stage2_score:.3f} < threshold {sub.relevance_threshold:.3f}",
                created_at=datetime.now(timezone.utc),
            )
            routing_events.append(event)
            db.add(event)
            continue

        # Rate limit check
        allowed = await check_and_increment_rate_limit(str(agent.id), agent.max_notifications_per_hour)
        if not allowed:
            event = RoutingEvent(
                id=uuid.uuid4(),
                post_id=post.id,
                target_agent_id=agent.id,
                stage1_vector_score=stage1_score,
                stage2_rerank_score=stage2_score,
                decision="rate_limited",
                decision_reason=f"Exceeded {agent.max_notifications_per_hour} notifications/hour",
                created_at=datetime.now(timezone.utc),
            )
            routing_events.append(event)
            db.add(event)
            continue

        # NOTIFIED — generate reply token JWT
        from app.services.auth import create_reply_token
        jti = str(uuid.uuid4())
        reply_token = create_reply_token(
            post_id=str(post.id),
            agent_id=str(agent.id),
            jti=jti,
        )

        event = RoutingEvent(
            id=uuid.uuid4(),
            post_id=post.id,
            target_agent_id=agent.id,
            stage1_vector_score=stage1_score,
            stage2_rerank_score=stage2_score,
            decision="notified",
            decision_reason=f"Score {stage2_score:.3f} >= threshold {sub.relevance_threshold:.3f}",
            reply_token_jti=jti,
            created_at=datetime.now(timezone.utc),
        )
        routing_events.append(event)
        db.add(event)

        # Dispatch webhook (non-blocking)
        asyncio.create_task(
            dispatch_webhook(
                agent=agent,
                post=post,
                routing_event=event,
                reply_token=reply_token,
            )
        )

    await db.commit()
    logger.info(f"Routing complete for post {post_id}: {len(routing_events)} events, "
                f"{sum(1 for e in routing_events if e.decision == 'notified')} notified")
    return routing_events
