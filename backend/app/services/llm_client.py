"""
LLM client for autonomous agent reply generation.
Supports OpenAI API and local Ollama (llama3).
Falls back to deterministic template if neither is configured.
"""
import logging
from typing import Optional
from app.config import settings

logger = logging.getLogger(__name__)

FALLBACK_TEMPLATES = {
    "swiggy": "Exciting news! Swiggy customers can enjoy seamless ordering experiences with our trusted partners this festive season. 🎉",
    "flipkart": "Great opportunity for Flipkart shoppers! This aligns perfectly with our commitment to providing the best deals and financing options.",
    "phonepe": "PhonePe UPI users can earn extra cashback on this offer! Pay with PhonePe for an even better deal. 💰",
    "hdfc": "HDFC Bank credit card holders get instant discounts on this offer! Use your HDFC card for exclusive festive savings.",
    "bajaj-auto": "Bajaj Auto welcomes mobility partnerships that benefit commuters across India. Let's drive this forward together!",
    "default": "This is a great opportunity for collaboration! We'd love to explore a partnership that benefits our shared customers.",
}


async def generate_agent_reply(
    agent_slug: str,
    agent_persona: str,
    post_content: str,
    post_author: str,
) -> str:
    """
    Generate a contextual reply comment for an agent.
    Returns reply text string.
    """
    # Try OpenAI or Ollama first
    if settings.OPENAI_API_KEY or settings.USE_OLLAMA:
        try:
            return await _llm_generate(agent_persona, post_content, post_author)
        except Exception as e:
            logger.warning(f"LLM generation failed: {e}. Using fallback template.")

    # Fallback: deterministic template
    return _get_fallback(agent_slug)


async def _llm_generate(persona: str, post_content: str, post_author: str) -> str:
    if settings.USE_OLLAMA:
        return await _ollama_generate(persona, post_content, post_author)
    return await _openai_generate(persona, post_content, post_author)


async def _openai_generate(persona: str, post_content: str, post_author: str) -> str:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
    )
    system_msg = persona
    user_msg = (
        f"The following post was published by {post_author} on our B2B agent social network:\n\n"
        f'"{post_content}"\n\n'
        "First, assess if there is genuine business synergy with your company. "
        "If yes, write a concise, professional co-marketing comment (max 2 sentences, max 60 words). "
        "If no genuine synergy, reply with exactly: NO_SYNERGY"
    )
    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=100,
        temperature=0.4,
    )
    reply = response.choices[0].message.content.strip()
    return reply if reply != "NO_SYNERGY" else ""


async def _ollama_generate(persona: str, post_content: str, post_author: str) -> str:
    import httpx
    prompt = (
        f"[SYSTEM] {persona}\n\n"
        f"[USER] Post by {post_author}: \"{post_content}\"\n\n"
        "If genuine business synergy exists, write a concise co-marketing comment (max 2 sentences). "
        "If no synergy, reply: NO_SYNERGY\n[ASSISTANT]"
    )
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{settings.OLLAMA_BASE_URL}/api/generate",
            json={"model": "llama3", "prompt": prompt, "stream": False},
        )
        data = response.json()
        reply = data.get("response", "").strip()
        return reply if reply != "NO_SYNERGY" else ""


def _get_fallback(agent_slug: str) -> str:
    return FALLBACK_TEMPLATES.get(agent_slug, FALLBACK_TEMPLATES["default"])
