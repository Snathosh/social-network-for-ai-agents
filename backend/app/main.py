import logging
import os
import asyncio
from uuid import UUID
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
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
                select(RoutingEvent.id).where(RoutingEvent.post_id == post_id).limit(1)
            )
            if event_result.scalar_one_or_none() is None:
                from app.services.routing import run_routing_pipeline

                await run_routing_pipeline(str(post_id), db)
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

        event_result = await db.execute(
            select(RoutingEvent.id).where(RoutingEvent.post_id == post.id).limit(1)
        )
        if event_result.scalar_one_or_none() is None:
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
