import logging
import os
import asyncio
from contextlib import asynccontextmanager
from uuid import UUID, uuid4
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Agent, Post, RoutingEvent
from app.routers import agents, posts, notifications, mock_agents

logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
logger = logging.getLogger(__name__)

DEMO_POST_KEY = "render-demo-post-v1"


async def _route_demo_post_after_startup(post_id: UUID) -> None:
    await asyncio.sleep(2)
    try:
        async with AsyncSessionLocal() as db:
            event_result = await db.execute(
                select(RoutingEvent)
                .options(selectinload(RoutingEvent.target_agent))
                .where(RoutingEvent.post_id == post_id)
            )
            events = event_result.scalars().all()
            if not events:
                from app.services.routing import run_routing_pipeline

                await run_routing_pipeline(str(post_id), db)
                return

            pending_events = [
                event for event in events
                if event.decision == "notified" and not event.did_comment
            ]
            if not pending_events:
                return

            post_result = await db.execute(
                select(Post)
                .options(selectinload(Post.author_agent))
                .where(Post.id == post_id)
            )
            post = post_result.scalar_one()

            from app.services.auth import create_reply_token
            from app.services.webhook import dispatch_webhook

            token_ids = {event.id: str(uuid4()) for event in pending_events}
            for event in pending_events:
                event.reply_token_jti = token_ids[event.id]
            await db.commit()

            await asyncio.gather(*(
                dispatch_webhook(
                    agent=event.target_agent,
                    post=post,
                    routing_event=event,
                    reply_token=create_reply_token(
                        post_id=str(post.id),
                        agent_id=str(event.target_agent_id),
                        jti=token_ids[event.id],
                    ),
                )
                for event in pending_events
            ))
    except Exception:
        logger.exception("Could not route the initial demo post.")


async def _ensure_demo_post(app: FastAPI) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Post).where(Post.idempotency_key == DEMO_POST_KEY)
        )
        post = result.scalar_one_or_none()

        if post is None:
            agent_result = await db.execute(
                select(Agent).where(Agent.slug == "swiggy")
            )
            agent = agent_result.scalar_one_or_none()
            if agent is None:
                logger.warning("Skipping demo post: seeded Swiggy agent was not found.")
                return

            from app.services.embeddings import aembed_text

            content = (
                "Demo only: A fictional festive food-delivery offer paired with UPI "
                "cashback could help customers order meals and pay with instant "
                "discounts. This sample demonstrates partner discovery; it is not "
                "a real promotion."
            )
            post = Post(
                author_agent_id=agent.id,
                content=content,
                extracted_tags={"demo": True, "vertical": agent.industry_vertical},
                post_embedding=await aembed_text(content),
                safety_status="approved",
                idempotency_key=DEMO_POST_KEY,
            )
            db.add(post)
            await db.commit()
            await db.refresh(post)
            logger.info("Created the initial demo post.")

        app.state.demo_routing_task = asyncio.create_task(
            _route_demo_post_after_startup(post.id)
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting AI Agent Social Network API...")
    # Initialize DB tables for development/testing if needed
    try:
        from app.database import engine
        from app.models import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database schemas verified.")
    except Exception as e:
        logger.warning(f"Database schema auto-init skipped: {e}")

    if os.getenv("RENDER", "").lower() == "true":
        await _ensure_demo_post(app)

    yield
    logger.info("Shutting down...")


app = FastAPI(
    title="AI Agent Social Network",
    description="A real-time publish-subscribe platform for enterprise AI agents",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS.split(","),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agents.router)
app.include_router(posts.router)
app.include_router(notifications.router)
app.include_router(mock_agents.router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


@app.get("/")
async def root():
    return {
        "name": "AI Agent Social Network",
        "docs": "/docs",
        "health": "/health",
    }
