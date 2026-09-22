"""Checkpointer factory (ADR-0005) and the per-turn caches that keep raw tool
records and the delegation token out of graph state, so neither is ever
checkpointed. Both are keyed by turn id and expire after RECORD_TTL_SECONDS,
longer than any turn's wall clock and the token's own 90 s life."""

from __future__ import annotations

import threading
import time
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
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


def mark_conversation_closed(path: Path | str, conversation_id: str, *, closed_at: datetime) -> None:
    """Record the first close time without placing it in graph checkpoint state."""

    _require_utc(closed_at)
    if not conversation_id or len(conversation_id) > 128:
        raise ValueError("conversation ID must be bounded")
    with sqlite3.connect(path, timeout=5.0) as connection:
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS closed_conversation_retention (thread_id TEXT PRIMARY KEY, closed_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO closed_conversation_retention(thread_id, closed_at) VALUES (?, ?) ON CONFLICT(thread_id) DO NOTHING",
            (conversation_id, _utc_iso(closed_at)),
        )


def sweep_closed_checkpoints(
    path: Path | str,
    *,
    now: datetime,
    retention: timedelta = timedelta(hours=24),
) -> int:
    """Delete both LangGraph tables only after the post-close retention bound."""

    _require_utc(now)
    if retention <= timedelta(0):
        raise ValueError("checkpoint retention must be positive")
    cutoff = _utc_iso(now - retention)
    with sqlite3.connect(path, timeout=5.0) as connection:
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS closed_conversation_retention (thread_id TEXT PRIMARY KEY, closed_at TEXT NOT NULL)"
        )
        rows = connection.execute(
            "SELECT thread_id FROM closed_conversation_retention WHERE closed_at <= ? ORDER BY thread_id",
            (cutoff,),
        ).fetchall()
        thread_ids = [str(row[0]) for row in rows]
        for thread_id in thread_ids:
            connection.execute("DELETE FROM writes WHERE thread_id = ?", (thread_id,))
            connection.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
            connection.execute("DELETE FROM closed_conversation_retention WHERE thread_id = ?", (thread_id,))
        return len(thread_ids)


def _require_utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None or value.utcoffset().total_seconds() != 0:
        raise ValueError("retention timestamps must be UTC")


def _utc_iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")
