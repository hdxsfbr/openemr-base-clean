"""PHI-free telemetry (ADR-0007): Langfuse's LangGraph callback handler with a
mask that replaces every input and output payload with a digest. Refuses to
start if LangSmith tracing variables are set."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from .settings import settings

log = logging.getLogger("copilot.telemetry")

FORBIDDEN_ENV = ("LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING", "LANGCHAIN_API_KEY", "LANGSMITH_API_KEY")


def guard_environment() -> None:
    present = [k for k in FORBIDDEN_ENV if os.environ.get(k)]
    if present:
        raise RuntimeError(f"LangSmith tracing variables must not be set (PHI): {present}")


def mask(data: Any) -> Any:
    """Replace any payload with a PHI-free digest: type, size, and counts only."""
    try:
        if isinstance(data, dict):
            return {"digest": True, "keys": sorted(str(k) for k in data.keys())[:20], "bytes": len(json.dumps(data, default=str))}
        if isinstance(data, list):
            return {"digest": True, "items": len(data)}
        if isinstance(data, str):
            return {"digest": True, "chars": len(data)}
        return {"digest": True, "type": type(data).__name__}
    except Exception:  # noqa: BLE001
        return {"digest": True}


def callback_handler(trace_name: str, correlation_id: str, conversation_id: str, turn_type: str):
    """Returns a Langfuse CallbackHandler or None when the tracer is not configured."""
    public = settings.secret(settings.langfuse_public_key_file)
    secret = settings.secret(settings.langfuse_secret_key_file)
    if not public or not secret:
        return None
    try:
        from langfuse import Langfuse
        from langfuse.langchain import CallbackHandler

        Langfuse(public_key=public, secret_key=secret, host=settings.langfuse_host, mask=mask)
        return CallbackHandler(
            trace_name=trace_name,
            metadata={"correlation_id": correlation_id, "conversation_id": conversation_id, "turn_type": turn_type},
        )
    except Exception as exc:  # noqa: BLE001 - telemetry never blocks care
        log.warning("tracer unavailable", extra={"component": "telemetry", "correlation_id": correlation_id})
        log.debug("tracer error class %s", exc.__class__.__name__)
        return None


def tracer_configured() -> bool:
    return bool(settings.secret(settings.langfuse_public_key_file) and settings.secret(settings.langfuse_secret_key_file))
