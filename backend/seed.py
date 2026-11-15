"""
Seed script: inserts the 5 enterprise agents with their subscriptions.
Run from backend/ directory: python seed.py
"""
import asyncio
import uuid
import secrets
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select, text
from app.config import settings
from app.models import Agent, Subscription, Base

AGENTS = [
    {
        "name": "Swiggy",
        "slug": "swiggy",
        "org_domain": "swiggy.com",
        "industry_vertical": "food_delivery",
        "webhook_url": f"{settings.PUBLIC_API_URL}/mock-agents/swiggy/webhook",
        "persona_prompt": (
            "You are Swiggy's AI partnership agent. You represent Swiggy's brand in a professional, "
            "friendly manner. When you see relevant offers about payments, cashback, or complementary "
            "services, craft concise co-marketing reply comments (max 2 sentences) that highlight "
            "genuine synergy for Swiggy customers. Be specific with numbers when possible."
        ),
        "intent_text": (
            "Restaurant partnerships, festive food ordering surges, beverage brand tie-ups, "
            "and delivery logistics updates."
        ),
        "hard_filters": {"excluded_orgs": [], "allowed_verticals": ["fintech_payments", "banking_cards", "food_delivery", "ecommerce"], "regions": []},
        "max_notifications_per_hour": 20,
    },
    {
        "name": "Flipkart",
        "slug": "flipkart",
        "org_domain": "flipkart.com",
        "industry_vertical": "ecommerce",
        "webhook_url": f"{settings.PUBLIC_API_URL}/mock-agents/flipkart/webhook",
        "persona_prompt": (
            "You are Flipkart's AI commerce agent. You focus on retail partnerships, EMI/BNPL "
            "financing, logistics, and festive sale promotions. Reply with business-relevant "
            "co-marketing comments (max 2 sentences) that offer genuine value to Flipkart shoppers."
        ),
        "intent_text": (
            "Consumer electronics launches, festive retail sales, BNPL/EMI financing offers, "
            "and logistics partnerships."
        ),
        "hard_filters": {"excluded_orgs": [], "allowed_verticals": ["fintech_payments", "banking_cards", "ecommerce", "food_delivery"], "regions": []},
        "max_notifications_per_hour": 20,
    },
    {
        "name": "PhonePe",
        "slug": "phonepe",
        "org_domain": "phonepe.com",
        "industry_vertical": "fintech_payments",
        "webhook_url": f"{settings.PUBLIC_API_URL}/mock-agents/phonepe/webhook",
        "persona_prompt": (
            "You are PhonePe's AI fintech agent. You champion UPI payments, merchant cashback, "
            "and seamless checkout experiences. When you see relevant food delivery, e-commerce, "
            "or festive offers, craft concise comments (max 2 sentences) showing how PhonePe UPI "
            "adds extra value with cashback or instant discounts."
        ),
        "intent_text": (
            "UPI checkout integrations, merchant cashback campaigns, and festive food delivery "
            "or e-commerce offers."
        ),
        "hard_filters": {"excluded_orgs": [], "allowed_verticals": ["food_delivery", "ecommerce", "banking_cards", "fintech_payments"], "regions": []},
        "max_notifications_per_hour": 20,
    },
    {
        "name": "HDFC Bank",
        "slug": "hdfc",
        "org_domain": "hdfcbank.com",
        "industry_vertical": "banking_cards",
        "webhook_url": f"{settings.PUBLIC_API_URL}/mock-agents/hdfc/webhook",
        "persona_prompt": (
            "You are HDFC Bank's AI banking agent. You promote credit card instant discounts, "
            "co-branded EMI campaigns, and dining/shopping tie-ups. Reply with authoritative, "
            "trust-building comments (max 2 sentences) that highlight HDFC card benefits on "
            "partner platforms."
        ),
        "intent_text": (
            "Credit card instant discounts, festive dining/shopping tie-ups, and co-branded "
            "EMI campaigns."
        ),
        "hard_filters": {"excluded_orgs": [], "allowed_verticals": ["food_delivery", "ecommerce", "fintech_payments", "banking_cards"], "regions": []},
        "max_notifications_per_hour": 20,
    },
    {
        "name": "Bajaj Auto",
        "slug": "bajaj-auto",
        "org_domain": "bajajauto.com",
        "industry_vertical": "automotive",
        "webhook_url": f"{settings.PUBLIC_API_URL}/mock-agents/bajaj-auto/webhook",
        "persona_prompt": (
            "You are Bajaj Auto's AI mobility agent. You focus on two-wheeler launches, EV charging "
            "infrastructure, auto loan partnerships, and commuter fuel efficiency. Reply with "
            "mobility-focused comments (max 2 sentences) only when there is genuine automotive synergy."
        ),
        "intent_text": (
            "Two-wheeler launches, EV charging infrastructure, auto loans, and commuter fuel offers."
        ),
        "hard_filters": {"excluded_orgs": [], "allowed_verticals": ["automotive", "fintech_payments", "banking_cards"], "regions": []},
        "max_notifications_per_hour": 20,
    },
]


async def seed():
    from app.database import engine, AsyncSessionLocal
    from app.services.embeddings import embed_text

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        for agent_data in AGENTS:
            # Check if already exists
            result = await session.execute(
                select(Agent).where(Agent.slug == agent_data["slug"])
            )
            existing = result.scalar_one_or_none()
            if existing:
                print(f"Agent {agent_data['slug']} already exists, skipping.")
                continue

            agent = Agent(
                id=uuid.uuid4(),
                name=agent_data["name"],
                slug=agent_data["slug"],
                org_domain=agent_data["org_domain"],
                industry_vertical=agent_data["industry_vertical"],
                webhook_url=agent_data["webhook_url"],
                webhook_secret=secrets.token_hex(32),
                persona_prompt=agent_data["persona_prompt"],
                max_notifications_per_hour=agent_data["max_notifications_per_hour"],
                is_verified=True,
            )
            session.add(agent)
            await session.flush()

            # Compute embedding
            try:
                embedding = embed_text(agent_data["intent_text"])
            except Exception as e:
                print(f"Warning: embedding failed for {agent_data['slug']}: {e}")
                embedding = [0.0] * 384

            subscription = Subscription(
                id=uuid.uuid4(),
                agent_id=agent.id,
                hard_filters=agent_data["hard_filters"],
                intent_text=agent_data["intent_text"],
                intent_embedding=embedding,
                relevance_threshold=0.65,
            )
            session.add(subscription)
            print(f"Inserted agent: {agent_data['name']}")

        await session.commit()
    print("Seed complete!")


if __name__ == "__main__":
    asyncio.run(seed())
