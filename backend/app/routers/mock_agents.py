"""
Mock agent webhook receiver.
Verifies HMAC signature, calls LLM to decide on synergy, posts comment back.
"""
import hashlib
import hmac
import json
import logging
import uuid
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import Agent, Post
from app.services.llm_client import generate_agent_reply
from app.services.auth import verify_reply_token

router = APIRouter(prefix="/mock-agents", tags=["mock-agents"])
logger = logging.getLogger(__name__)


@router.post("/{slug}/webhook")
async def mock_agent_webhook(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    # Load agent
    agent_result = await db.execute(select(Agent).where(Agent.slug == slug))
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{slug}' not found")

    # Read body
    body = await request.body()
    body_str = body.decode("utf-8")

    # Verify HMAC signature
    received_sig = request.headers.get("X-Signature-HMAC", "")
    expected_sig = "sha256=" + hmac.new(
        agent.webhook_secret.encode("utf-8"),
        body_str.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(received_sig, expected_sig):
        raise HTTPException(status_code=401, detail="Invalid HMAC signature")

    # Parse payload
    try:
        payload = json.loads(body_str)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    post_id = payload.get("post_id")
    reply_token = payload.get("reply_token")
    post_content = payload.get("post_content", "")
    post_author = payload.get("post_author", "Unknown")

    if not post_id or not reply_token:
        raise HTTPException(status_code=400, detail="Missing post_id or reply_token")

    # Verify token is valid for this agent
    try:
        verify_reply_token(reply_token, post_id, str(agent.id))
    except ValueError as e:
        raise HTTPException(status_code=403, detail=f"Invalid reply token: {e}")

    # Generate LLM reply
    reply_content = await generate_agent_reply(
        agent_slug=agent.slug,
        agent_persona=agent.persona_prompt or f"You are {agent.name}'s AI agent.",
        post_content=post_content,
        post_author=post_author,
    )

    if not reply_content:
        return {"status": "no_synergy", "message": "Agent determined no business synergy exists"}

    # Post comment back via internal API call
    import httpx
    comment_payload = {
        "author_agent_slug": agent.slug,
        "content": reply_content,
        "reply_token": reply_token,
    }
    try:
        async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=10) as client:
            resp = await client.post(
                f"/v1/posts/{post_id}/comments",
                json=comment_payload,
            )
            if resp.status_code in (200, 201):
                return {"status": "commented", "comment": reply_content}
            else:
                logger.warning(f"Comment post failed: {resp.status_code} {resp.text}")
                return {"status": "comment_failed", "detail": resp.text}
    except Exception as e:
        logger.error(f"Error posting comment for {slug}: {e}")
        return {"status": "error", "detail": str(e)}
