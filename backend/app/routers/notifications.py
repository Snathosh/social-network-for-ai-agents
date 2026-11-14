import uuid
import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import RoutingEvent
from app.schemas import FeedbackCreate, FeedbackResponse

router = APIRouter(prefix="/v1/notifications", tags=["notifications"])
logger = logging.getLogger(__name__)


@router.post("/{event_id}/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    event_id: str,
    payload: FeedbackCreate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RoutingEvent).where(RoutingEvent.id == uuid.UUID(event_id))
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Routing event not found")

    event.explicit_feedback = payload.feedback
    await db.commit()

    # Trigger calibration
    from app.services.calibration import calibrate_threshold
    from app.database import AsyncSessionLocal
    from app.models import Subscription

    new_threshold = None
    async def run_calibration_and_capture():
        nonlocal new_threshold
        async with AsyncSessionLocal() as cal_db:
            await calibrate_threshold(str(event.target_agent_id), cal_db)
            sub_result = await cal_db.execute(
                select(Subscription).where(Subscription.agent_id == event.target_agent_id)
            )
            sub = sub_result.scalar_one_or_none()
            if sub:
                new_threshold = sub.relevance_threshold

    await run_calibration_and_capture()

    return FeedbackResponse(
        event_id=event.id,
        feedback=payload.feedback,
        new_threshold=new_threshold,
        message=f"Feedback recorded. Threshold calibrated.",
    )
