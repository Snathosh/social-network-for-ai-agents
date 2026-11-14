"""
Redis sliding-window rate limiter for per-agent notification quotas.
Key: rate_limit:agent:{agent_id}
Uses a sorted set where each member is a unique UUID and score is timestamp.
Includes an in-memory fallback if Redis is unreachable.
"""
import time
import uuid
import logging
from collections import defaultdict
try:
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None
from app.config import settings

logger = logging.getLogger(__name__)

_redis_client = None
_in_memory_timestamps = defaultdict(list)


def get_redis():
    global _redis_client
    if aioredis is None:
        raise RuntimeError("redis package is not installed")
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
        )
    return _redis_client


async def check_and_increment_rate_limit(agent_id: str, max_per_hour: int) -> bool:
    """
    Returns True if the agent is within limit (notification allowed).
    Returns False if rate limited.
    Uses Redis sorted set sliding window (1-hour window) with in-memory fallback.
    """
    now = time.time()
    window_start = now - 3600  # 1 hour ago

    try:
        redis = get_redis()
        key = f"rate_limit:agent:{agent_id}"

        pipe = redis.pipeline()
        pipe.zremrangebyscore(key, "-inf", window_start)
        pipe.zcard(key)
        results = await pipe.execute()

        current_count = results[1]
        if current_count >= max_per_hour:
            return False

        member = str(uuid.uuid4())
        pipe2 = redis.pipeline()
        pipe2.zadd(key, {member: now})
        pipe2.expire(key, 3600)
        await pipe2.execute()
        return True
    except Exception as e:
        logger.debug(f"Redis rate limiter fallback to in-memory: {e}")
        # In-memory sliding window fallback
        timestamps = _in_memory_timestamps[agent_id]
        _in_memory_timestamps[agent_id] = [t for t in timestamps if t > window_start]
        if len(_in_memory_timestamps[agent_id]) >= max_per_hour:
            return False
        _in_memory_timestamps[agent_id].append(now)
        return True


async def get_current_usage(agent_id: str) -> int:
    """Returns current notification count in the last hour."""
    now = time.time()
    window_start = now - 3600
    try:
        redis = get_redis()
        key = f"rate_limit:agent:{agent_id}"
        await redis.zremrangebyscore(key, "-inf", window_start)
        return await redis.zcard(key)
    except Exception:
        timestamps = _in_memory_timestamps[agent_id]
        _in_memory_timestamps[agent_id] = [t for t in timestamps if t > window_start]
        return len(_in_memory_timestamps[agent_id])

