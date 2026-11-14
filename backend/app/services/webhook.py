"""
HMAC-signed webhook dispatcher.
Dispatches signed notifications to agent webhook URLs.
"""
import hashlib
import hmac
import json
import logging
import time
from typing import Optional
import httpx
from app.models import Agent, Post, RoutingEvent

logger = logging.getLogger(__name__)


def compute_hmac_signature(secret: str, payload: str) -> str:
    """Compute HMAC-SHA256 signature."""
    return hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


async def dispatch_webhook(
    agent: Agent,
    post: Post,
    routing_event: RoutingEvent,
    reply_token: str,
) -> None:
    """
    Dispatch a signed webhook notification to the agent's webhook URL.
    Non-blocking — called as asyncio.create_task.
    """
    if not agent.webhook_url:
        logger.debug(f"Agent {agent.slug} has no webhook_url configured.")
        return

    payload = {
        "event_id": str(routing_event.id),
        "post_id": str(post.id),
        "post_content": post.content,
        "post_author": post.author_agent.name if post.author_agent else "Unknown",
        "post_author_slug": post.author_agent.slug if post.author_agent else "",
        "stage1_score": routing_event.stage1_vector_score,
        "stage2_score": routing_event.stage2_rerank_score,
        "reply_token": reply_token,
        "timestamp": int(time.time()),
    }
    payload_str = json.dumps(payload, separators=(",", ":"))
    signature = compute_hmac_signature(agent.webhook_secret, payload_str)

    headers = {
        "Content-Type": "application/json",
        "X-Signature-HMAC": f"sha256={signature}",
        "X-Agent-Slug": agent.slug,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(agent.webhook_url, content=payload_str, headers=headers)
            logger.info(f"Webhook dispatched to {agent.slug}: HTTP {resp.status_code}")
    except Exception as e:
        logger.warning(f"Webhook delivery failed for {agent.slug}: {e}")
