"""Checkpointer factory (ADR-0005) and the per-turn record cache that keeps raw
tool records out of graph state (never checkpointed)."""

from __future__ import annotations

import threading
import time
from typing import Any

from .settings import settings

_records: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()
RECORD_TTL_SECONDS = 120.0


def put_pack(turn_id: str, pack: Any) -> None:
    with _lock:
        _records[turn_id] = (time.time(), pack)
        expired = [k for k, (t, _) in _records.items() if time.time() - t > RECORD_TTL_SECONDS]
        for k in expired:
            _records.pop(k, None)


def get_pack(turn_id: str) -> Any | None:
    with _lock:
        item = _records.get(turn_id)
    return item[1] if item else None


def drop_pack(turn_id: str) -> None:
    with _lock:
        _records.pop(turn_id, None)


def checkpoint_path() -> str:
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    return str(settings.state_dir / "checkpoints.sqlite")
