"""
Closed-Loop Threshold Calibration.

After each comment or feedback event, nudge the agent's subscription relevance_threshold:
- Up +0.03 (capped 0.90) if >85% of last 10 notifications were ignored (no comment, no positive feedback)
- Down -0.02 (floored 0.45) if >70% of last 10 notifications led to comments
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models import Subscription, RoutingEvent

logger = logging.getLogger(__name__)


async def calibrate_threshold(agent_id: str, db: AsyncSession) -> None:
    """
    Recalculates and updates the subscription relevance_threshold for the given agent.
    """
    # Get last 10 'notified' routing events for this agent
    result = await db.execute(
        select(RoutingEvent)
        .where(
            RoutingEvent.target_agent_id == agent_id,
            RoutingEvent.decision == "notified",
        )
        .order_by(RoutingEvent.created_at.desc())
        .limit(10)
    )
    last_10 = result.scalars().all()

    if len(last_10) < 3:
        # Not enough data to calibrate
        return

    total = len(last_10)
    commented = sum(1 for e in last_10 if e.did_comment)
    ignored = sum(1 for e in last_10 if not e.did_comment and e.explicit_feedback != "relevant")

    comment_rate = commented / total
    ignore_rate = ignored / total

    # Get subscription for this agent
    sub_result = await db.execute(
        select(Subscription).where(Subscription.agent_id == agent_id)
    )
    sub = sub_result.scalar_one_or_none()
    if not sub:
        return

    old_threshold = sub.relevance_threshold
    new_threshold = old_threshold

    if ignore_rate > 0.85:
        new_threshold = min(0.90, old_threshold + 0.03)
        logger.info(f"Agent {agent_id}: ignore_rate={ignore_rate:.2f} > 0.85 → raising threshold {old_threshold:.3f} → {new_threshold:.3f}")
    elif comment_rate > 0.70:
        new_threshold = max(0.45, old_threshold - 0.02)
        logger.info(f"Agent {agent_id}: comment_rate={comment_rate:.2f} > 0.70 → lowering threshold {old_threshold:.3f} → {new_threshold:.3f}")

    if new_threshold != old_threshold:
        sub.relevance_threshold = new_threshold
        await db.commit()
