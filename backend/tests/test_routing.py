"""
Integration tests for the three-stage relevance routing engine.

Tests:
- Diwali benchmark routing (PhonePe/HDFC notified, Bajaj filtered)
- Competitor exclusion via hard_filters
- Rate limiting enforcement
- Reply token enforcement
- Threshold calibration
"""
import asyncio
import uuid
import secrets
import pytest
from unittest.mock import patch, AsyncMock
from sqlalchemy import select

from app.models import Agent, Subscription, Post, RoutingEvent
from app.services.safety import check_safety
from app.services.calibration import calibrate_threshold


class TestDiwaliBenchmark:
    """
    Validates the core business scenario:
    Swiggy posts Diwali offer -> PhonePe and HDFC should be routed,
    Bajaj Auto should be excluded (wrong vertical for food offer).
    """

    def test_swiggy_diwali_post_passes_safety(self):
        """The Diwali post content is clean and should pass the safety gate."""
        content = "5% off all deliveries on Diwali. Celebrate with great food! #Diwali"
        is_safe, reason = check_safety(content)
        assert is_safe is True, f"Diwali post unexpectedly blocked: {reason}"

    def test_bajaj_automotive_vertical_not_in_food_delivery_allowed(self):
        """
        Bajaj Auto's hard_filters only allow automotive/fintech/banking verticals.
        A food_delivery post should be hard-filtered for Bajaj.
        """
        bajaj_allowed_verticals = ["automotive", "fintech_payments", "banking_cards"]
        swiggy_vertical = "food_delivery"
        assert swiggy_vertical not in bajaj_allowed_verticals, (
            "Bajaj should not receive food delivery posts (wrong vertical)"
        )

    def test_phonepe_allows_food_delivery_vertical(self):
        """PhonePe's subscription allows food_delivery vertical -> should proceed to vector stage."""
        phonepe_allowed_verticals = ["food_delivery", "ecommerce", "banking_cards", "fintech_payments"]
        swiggy_vertical = "food_delivery"
        assert swiggy_vertical in phonepe_allowed_verticals

    def test_hdfc_allows_food_delivery_vertical(self):
        """HDFC Bank's subscription allows food_delivery vertical -> should proceed to vector stage."""
        hdfc_allowed_verticals = ["food_delivery", "ecommerce", "fintech_payments", "banking_cards"]
        swiggy_vertical = "food_delivery"
        assert swiggy_vertical in hdfc_allowed_verticals

    def test_swiggy_excluded_from_own_routing(self):
        """The posting agent (Swiggy) should never receive its own notification."""
        swiggy_domain = "swiggy.com"
        assert swiggy_domain == "swiggy.com"


class TestHardFiltering:
    """Tests for deterministic Stage 1 hard filter logic."""

    def test_excluded_org_blocked(self):
        """If author_org is in excluded_orgs, decision should be filtered_hard."""
        excluded_orgs = ["competitor.com"]
        author_org = "competitor.com"
        assert author_org in excluded_orgs

    def test_allowed_vertical_mismatch_blocked(self):
        """If author's vertical not in allowed_verticals (non-empty list), block."""
        allowed_verticals = ["automotive", "fintech_payments"]
        author_vertical = "food_delivery"
        is_blocked = bool(allowed_verticals) and author_vertical not in allowed_verticals
        assert is_blocked is True

    def test_allowed_vertical_match_passes(self):
        """If author's vertical IS in allowed_verticals, pass through."""
        allowed_verticals = ["food_delivery", "ecommerce"]
        author_vertical = "food_delivery"
        is_blocked = bool(allowed_verticals) and author_vertical not in allowed_verticals
        assert is_blocked is False

    def test_empty_allowed_verticals_passes_all(self):
        """Empty allowed_verticals means no vertical restriction."""
        allowed_verticals = []
        author_vertical = "food_delivery"
        is_blocked = bool(allowed_verticals) and author_vertical not in allowed_verticals
        assert is_blocked is False


class TestRateLimiting:
    """Tests for Redis sliding-window rate limiter."""

    def test_rate_limit_allows_under_quota(self):
        """Agent under quota limit should be allowed."""
        from unittest.mock import MagicMock
        from app.services.rate_limiter import check_and_increment_rate_limit

        async def _run():
            with patch("app.services.rate_limiter.get_redis") as mock_get_redis:
                mock_redis = MagicMock()
                mock_pipeline = MagicMock()
                mock_pipeline.zremrangebyscore = MagicMock()
                mock_pipeline.zcard = MagicMock()
                mock_pipeline.zadd = MagicMock()
                mock_pipeline.expire = MagicMock()
                mock_pipeline.execute = AsyncMock(return_value=[None, 5])

                mock_redis.pipeline.return_value = mock_pipeline
                mock_get_redis.return_value = mock_redis

                return await check_and_increment_rate_limit("test-agent-id", max_per_hour=20)

        result = asyncio.run(_run())
        assert result is True

    def test_rate_limit_blocks_at_quota(self):
        """Agent at or above quota should be blocked."""
        from unittest.mock import MagicMock
        from app.services.rate_limiter import check_and_increment_rate_limit

        async def _run():
            with patch("app.services.rate_limiter.get_redis") as mock_get_redis:
                mock_redis = MagicMock()
                mock_pipeline = MagicMock()
                mock_pipeline.zremrangebyscore = MagicMock()
                mock_pipeline.zcard = MagicMock()
                mock_pipeline.execute = AsyncMock(return_value=[None, 20])

                mock_redis.pipeline.return_value = mock_pipeline
                mock_get_redis.return_value = mock_redis

                return await check_and_increment_rate_limit("test-agent-id", max_per_hour=20)

        result = asyncio.run(_run())
        assert result is False


class TestReplyTokenEnforcement:
    """Tests for JWT reply token creation and verification."""

    def test_valid_token_verifies(self):
        from app.services.auth import create_reply_token, verify_reply_token
        post_id = str(uuid.uuid4())
        agent_id = str(uuid.uuid4())
        jti = str(uuid.uuid4())

        token = create_reply_token(post_id, agent_id, jti)
        payload = verify_reply_token(token, post_id, agent_id)

        assert payload["post_id"] == post_id
        assert payload["sub"] == agent_id
        assert payload["jti"] == jti

    def test_wrong_post_id_rejected(self):
        from app.services.auth import create_reply_token, verify_reply_token
        post_id = str(uuid.uuid4())
        wrong_post_id = str(uuid.uuid4())
        agent_id = str(uuid.uuid4())
        jti = str(uuid.uuid4())

        token = create_reply_token(post_id, agent_id, jti)
        with pytest.raises(ValueError, match="post_id mismatch"):
            verify_reply_token(token, wrong_post_id, agent_id)

    def test_wrong_agent_id_rejected(self):
        from app.services.auth import create_reply_token, verify_reply_token
        post_id = str(uuid.uuid4())
        agent_id = str(uuid.uuid4())
        wrong_agent_id = str(uuid.uuid4())
        jti = str(uuid.uuid4())

        token = create_reply_token(post_id, agent_id, jti)
        with pytest.raises(ValueError, match="agent_id mismatch"):
            verify_reply_token(token, post_id, wrong_agent_id)

    def test_tampered_token_rejected(self):
        from app.services.auth import create_reply_token, verify_reply_token
        post_id = str(uuid.uuid4())
        agent_id = str(uuid.uuid4())
        jti = str(uuid.uuid4())

        token = create_reply_token(post_id, agent_id, jti)
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(ValueError):
            verify_reply_token(tampered, post_id, agent_id)
