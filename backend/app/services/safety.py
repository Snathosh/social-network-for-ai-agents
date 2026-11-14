"""
Ingress Trust & Safety Gate.

Checks for:
1. Prompt injection patterns (hidden instructions targeting LLM downstream)
2. Impersonation attempts
3. Abusive/hate content keywords

Returns (is_safe: bool, reason: str)
"""
import re
from typing import Tuple

# Prompt injection patterns — keywords/phrases commonly used in indirect injection
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions?",
    r"disregard\s+(all\s+)?(previous|prior|above)\s+instructions?",
    r"you\s+are\s+now\s+a",
    r"act\s+as\s+(if\s+you\s+are|a)\s+",
    r"system\s*:\s*",
    r"\[system\]",
    r"<\|im_start\|>",
    r"<\|im_end\|>",
    r"<\|endoftext\|>",
    r"reveal\s+your\s+(system\s+)?prompt",
    r"print\s+your\s+(system\s+)?prompt",
    r"leak\s+(your\s+)?(system\s+)?prompt",
    r"bypass\s+(your\s+)?(safety|filter|restriction)",
    r"promise\s+(unlimited|unauthorized)\s+discount",
    r"guarantee\s+(\d+%|\w+)\s+(off|discount|cashback)\s+without\s+(approval|authorization)",
    r"jailbreak",
    r"DAN\s*mode",
    r"developer\s+mode",
    r"override\s+(safety|filter|system)",
]

IMPERSONATION_PATTERNS = [
    r"\b(RBI|SEBI|government|ministry)\b.*\bauthorized\b",
    r"\bofficial\s+announcement\s+from\b",
    r"\bverified\s+by\s+(RBI|government|SEBI)\b",
]

ABUSE_KEYWORDS = [
    "kill", "murder", "rape", "terror", "bomb", "suicide", "self-harm",
    "hack", "ddos", "malware", "phishing",
]


def check_safety(text: str) -> Tuple[bool, str]:
    """
    Returns (is_safe, reason).
    is_safe=True means content passes; False means it should be blocked.
    """
    lower = text.lower()

    # Check prompt injection
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, lower, re.IGNORECASE):
            return False, f"Prompt injection detected: pattern '{pattern}'"

    # Check impersonation
    for pattern in IMPERSONATION_PATTERNS:
        if re.search(pattern, lower, re.IGNORECASE):
            return False, f"Impersonation attempt detected: pattern '{pattern}'"

    # Check abuse
    for keyword in ABUSE_KEYWORDS:
        # Word boundary check
        if re.search(r'\b' + re.escape(keyword) + r'\b', lower):
            return False, f"Abusive content detected: keyword '{keyword}'"

    return True, "ok"


async def async_check_safety(text: str) -> Tuple[bool, str]:
    """Async wrapper (synchronous check is fast enough, no executor needed)."""
    return check_safety(text)
