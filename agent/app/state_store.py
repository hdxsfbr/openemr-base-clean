"""Checkpointer factory (ADR-0005) and the per-turn caches that keep raw tool
records and the delegation token out of graph state, so neither is ever
checkpointed. Both are keyed by turn id and expire after RECORD_TTL_SECONDS,
longer than any turn's wall clock and the token's own 90 s life."""

from __future__ import annotations

import threading
import time
from typing import Any

from .settings import settings

_records: dict[str, tuple[float, Any]] = {}
_tokens: dict[str, tuple[float, str]] = {}
_lock = threading.Lock()
RECORD_TTL_SECONDS = 120.0


def _sweep(store: dict[str, tuple[float, Any]]) -> None:
    now = time.time()
    for key in [k for k, (t, _) in store.items() if now - t > RECORD_TTL_SECONDS]:
        store.pop(key, None)


def put_pack(turn_id: str, pack: Any) -> None:
    with _lock:
        _records[turn_id] = (time.time(), pack)
        _sweep(_records)


def get_pack(turn_id: str) -> Any | None:
    with _lock:
        item = _records.get(turn_id)
    return item[1] if item else None


def drop_pack(turn_id: str) -> None:
    with _lock:
        _records.pop(turn_id, None)


def put_token(turn_id: str, token: str) -> None:
    """The turn's delegation token, read by the gateway calls of that turn only."""
    with _lock:
        _tokens[turn_id] = (time.time(), token)
        _sweep(_tokens)


def get_token(turn_id: str) -> str | None:
    with _lock:
        item = _tokens.get(turn_id)
    return item[1] if item else None


def drop_token(turn_id: str) -> None:
    with _lock:
        _tokens.pop(turn_id, None)


def checkpoint_path() -> str:
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    return str(settings.state_dir / "checkpoints.sqlite")
