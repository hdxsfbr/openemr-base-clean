"""Agent-side verification of the per-turn delegation token (ADR-0005).
Same HMAC as the module; carries only the conversation id, turn id, and times."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass

from .settings import settings


class DelegationError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Delegation:
    conversation_id: str
    turn_id: str
    issued_at: int
    expires_at: int
    raw: str


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def verify(token: str, secret: str | None = None, now: int | None = None) -> Delegation:
    secret = secret if secret is not None else settings.secret(settings.delegation_secret_file)
    if not secret or len(secret) < 32:
        raise DelegationError("secret_not_configured")
    parts = token.split(".")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise DelegationError("bad_token")
    expected = _b64encode(hmac.new(secret.encode(), parts[0].encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, parts[1]):
        raise DelegationError("bad_token")
    try:
        payload = json.loads(_b64decode(parts[0]))
    except (ValueError, json.JSONDecodeError) as exc:
        raise DelegationError("bad_token") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("v") != 1
        or not re.fullmatch(r"[a-f0-9]{32}", str(payload.get("cid", "")))
        or not re.fullmatch(r"[a-f0-9]{16}", str(payload.get("jti", "")))
        or not isinstance(payload.get("iat"), int)
        or not isinstance(payload.get("exp"), int)
    ):
        raise DelegationError("bad_token")
    now = now if now is not None else int(time.time())
    if payload["exp"] < now or payload["iat"] > now + 30:
        raise DelegationError("token_expired")
    return Delegation(payload["cid"], payload["jti"], payload["iat"], payload["exp"], token)


def mint_for_tests(conversation_id: str, turn_id: str, secret: str, ttl: int = 90) -> str:
    """Test helper mirroring the module's DelegationToken::encode."""
    now = int(time.time())
    body = _b64encode(json.dumps({"cid": conversation_id, "jti": turn_id, "iat": now, "exp": now + ttl, "v": 1}).encode())
    return body + "." + _b64encode(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
