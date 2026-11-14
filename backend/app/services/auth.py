"""
JWT reply token creation and verification.
Reply tokens are short-lived JWTs scoped to a specific post_id and agent_id.
Supports python-jose with standard library HMAC-SHA256 fallback.
"""
import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone
from app.config import settings

try:
    from jose import jwt, JWTError
except ImportError:
    jwt = None
    JWTError = Exception


def _b64_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64_decode(data: str) -> bytes:
    padding = 4 - (len(data) % 4)
    if padding and padding < 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data.encode("utf-8"))


def create_reply_token(post_id: str, agent_id: str, jti: str) -> str:
    """Create a signed JWT reply token."""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=settings.REPLY_TOKEN_EXPIRY_MINUTES)
    payload = {
        "sub": agent_id,
        "post_id": post_id,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }

    if jwt is not None:
        return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

    # Standard library HMAC-SHA256 JWT
    header = {"alg": "HS256", "typ": "JWT"}
    h_b64 = _b64_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    p_b64 = _b64_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    msg = f"{h_b64}.{p_b64}"
    sig = hmac.new(settings.JWT_SECRET.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).digest()
    sig_b64 = _b64_encode(sig)
    return f"{msg}.{sig_b64}"


def verify_reply_token(token: str, post_id: str, agent_id: str) -> dict:
    """
    Verify reply token. Returns payload dict if valid.
    Raises ValueError with descriptive message on failure.
    """
    if jwt is not None:
        try:
            payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        except JWTError as e:
            raise ValueError(f"Invalid reply token: {e}")
    else:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Malformed token format")
        msg = f"{parts[0]}.{parts[1]}"
        expected_sig = hmac.new(settings.JWT_SECRET.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).digest()
        actual_sig = _b64_decode(parts[2])
        if not hmac.compare_digest(expected_sig, actual_sig):
            raise ValueError("Invalid reply token signature")
        try:
            payload = json.loads(_b64_decode(parts[1]).decode("utf-8"))
        except Exception:
            raise ValueError("Could not parse payload")
        now = datetime.now(timezone.utc).timestamp()
        if payload.get("exp") and payload["exp"] < now:
            raise ValueError("Reply token has expired")

    if payload.get("post_id") != post_id:
        raise ValueError("Reply token post_id mismatch")
    if payload.get("sub") != agent_id:
        raise ValueError("Reply token agent_id mismatch")

    return payload
