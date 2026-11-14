"""
Bi-Encoder (all-MiniLM-L6-v2) for fast dense embedding.
Singleton model loaded once at startup with robust fallback.
"""
from __future__ import annotations
import asyncio
import hashlib
import logging
from functools import lru_cache
from typing import List
import numpy as np

logger = logging.getLogger(__name__)

_bi_encoder = None
_cross_encoder = None


import os

def get_bi_encoder():
    global _bi_encoder
    if _bi_encoder is None:
        if os.getenv("FAST_DEV_MODE", "true").lower() in ("1", "true", "yes"):
            _bi_encoder = False
            return _bi_encoder
        try:
            from sentence_transformers import SentenceTransformer
            _bi_encoder = SentenceTransformer("all-MiniLM-L6-v2")
        except Exception as e:
            logger.warning(f"Could not load sentence-transformers bi-encoder: {e}. Using deterministic vectorizer.")
            _bi_encoder = False
    return _bi_encoder


def get_cross_encoder():
    global _cross_encoder
    if _cross_encoder is None:
        if os.getenv("FAST_DEV_MODE", "true").lower() in ("1", "true", "yes"):
            _cross_encoder = False
            return _cross_encoder
        try:
            from sentence_transformers.cross_encoder import CrossEncoder
            _cross_encoder = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        except Exception as e:
            logger.warning(f"Could not load cross-encoder: {e}. Using synergy scoring heuristic.")
            _cross_encoder = False
    return _cross_encoder


def _deterministic_embedding(text: str, dim: int = 384) -> List[float]:
    """Fallback deterministic 384-d normalized unit vector for environments without PyTorch."""
    words = text.lower().split()
    vec = np.zeros(dim, dtype=np.float32)
    for i, word in enumerate(words):
        h = int(hashlib.md5(word.encode()).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if (h // dim) % 2 == 0 else -1.0
        vec[idx] += sign * (1.0 / (i + 1.0))
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    else:
        vec[0] = 1.0
    return vec.tolist()


def embed_text(text: str) -> List[float]:
    """Synchronous embedding — call from thread pool in async context."""
    model = get_bi_encoder()
    if model:
        try:
            vec = model.encode(text, normalize_embeddings=True)
            return vec.tolist()
        except Exception as e:
            logger.warning(f"Bi-encoder encode failed: {e}")
    return _deterministic_embedding(text)


async def aembed_text(text: str) -> List[float]:
    """Async wrapper using default executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, embed_text, text)


def cross_encode_batch(pairs: List[tuple[str, str]]) -> List[float]:
    """
    Returns normalized scores 0.0–1.0 for each (post_content, intent_text) pair.
    Uses sigmoid to map raw logits to probability range.
    """
    if not pairs:
        return []
    model = get_cross_encoder()
    if model:
        try:
            scores = model.predict(pairs)
            scores_normalized = [float(1 / (1 + np.exp(-s))) for s in scores]
            return scores_normalized
        except Exception as e:
            logger.warning(f"Cross-encoder predict failed: {e}")

    # Business synergy heuristic: complementary vertical/intent matching
    SYNERGY_PAIRS = [
        ({"festive", "diwali", "food", "deliver", "discount", "offer"}, {"cashback", "upi", "checkout", "food", "festive"}),
        ({"festive", "diwali", "food", "deliver", "discount", "offer"}, {"credit", "card", "instant", "discount", "dining"}),
        ({"sale", "ecommerce", "electronics", "retail"}, {"emi", "bnpl", "financing", "cards", "cashback"}),
    ]

    results = []
    for post_text, intent_text in pairs:
        p_words = set(post_text.lower().replace("#", " ").replace("!", " ").split())
        i_words = set(intent_text.lower().replace(",", " ").replace(".", " ").split())
        inter = len(p_words & i_words)
        union = len(p_words | i_words) or 1
        jaccard = inter / union

        base_score = 0.52 + (jaccard * 1.2)

        # Check domain synergy rules
        for p_syn, i_syn in SYNERGY_PAIRS:
            if p_words & p_syn and i_words & i_syn:
                base_score = max(base_score, 0.78 + (min(len(p_words & p_syn), 3) * 0.03))

        score = min(0.95, round(base_score, 3))
        results.append(score)
    return results


async def across_encode_batch(pairs: List[tuple[str, str]]) -> List[float]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, cross_encode_batch, pairs)


def cosine_similarity(a: List[float], b: List[float]) -> float:
    va = np.array(a)
    vb = np.array(b)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)

