"""PHI-free telemetry (ADR-0007): Langfuse's LangGraph callback handler with a
mask that replaces every input and output payload with a digest. Refuses to
start if LangSmith tracing variables are set."""

from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator

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


_client_ready = False


def _ensure_client() -> bool:
    """Initialize the Langfuse client once with the PHI mask; False when not configured."""
    global _client_ready
    if _client_ready:
        return True
    public = settings.secret(settings.langfuse_public_key_file)
    secret = settings.secret(settings.langfuse_secret_key_file)
    if not public or not secret:
        return False
    from langfuse import Langfuse

    Langfuse(public_key=public, secret_key=secret, host=settings.langfuse_host, mask=mask)
    _client_ready = True
    return True


def trace_config(correlation_id: str, conversation_id: str, turn_type: str) -> dict[str, Any]:
    """LangChain run config additions that attach the Langfuse handler and the
    PHI-free trace attributes. Empty when the tracer is not configured or fails."""
    try:
        if not _ensure_client():
            return {}
        from langfuse.langchain import CallbackHandler

        return {
            "callbacks": [CallbackHandler()],
            "run_name": "copilot.turn",
            "metadata": {
                "correlation_id": correlation_id,
                "conversation_id": conversation_id,
                "turn_type": turn_type,
                "langfuse_session_id": conversation_id,
                "langfuse_tags": ["copilot", turn_type],
            },
        }
    except Exception as exc:  # noqa: BLE001 - telemetry never blocks care
        log.warning("tracer unavailable: %s", exc.__class__.__name__, extra={"component": "telemetry", "correlation_id": correlation_id})
        return {}


class _NoGeneration:
    def update(self, **kwargs: Any) -> None:
        return None

    def update_trace(self, **kwargs: Any) -> None:
        return None


@contextmanager
def turn_trace(correlation_id: str, conversation_id: str) -> Iterator[Any]:
    """The root span for one turn. Node spans (LangChain callback) and
    generation spans nest under it because it sets the current context."""
    try:
        if not _ensure_client():
            yield _NoGeneration()
            return
        from langfuse import get_client

        with get_client().start_as_current_observation(as_type="span", name="copilot.turn") as span:
            try:
                span.update_trace(
                    name="copilot.turn",
                    session_id=conversation_id,
                    tags=["copilot"],
                    metadata={"correlation_id": correlation_id, "conversation_id": conversation_id},
                )
            except Exception:  # noqa: BLE001
                pass
            yield span
    except Exception as exc:  # noqa: BLE001 - telemetry never blocks care
        log.warning("turn trace unavailable: %s", exc.__class__.__name__, extra={"component": "telemetry", "correlation_id": correlation_id})
        yield _NoGeneration()


def finish_turn_trace(span: Any, state: dict[str, Any]) -> None:
    try:
        span.update(metadata={
            "status": state.get("status"),
            "turn_type": state.get("turn_type"),
            "claims": len(state.get("accepted") or []),
            "withheld": len(state.get("rejected") or []),
            "tool_calls": len(state.get("tool_calls") or []),
            "timings_ms": state.get("timings_ms") or {},
            "usage": state.get("usage") or {},
        })
    except Exception:  # noqa: BLE001
        pass


@contextmanager
def generation(name: str, model: str) -> Iterator[Any]:
    """A Langfuse generation span for one model call, nested under the current
    turn trace. Only usage, model, and PHI-free metadata are ever set on it;
    inputs and outputs are never attached. No-op when the tracer is off."""
    try:
        if not _ensure_client():
            yield _NoGeneration()
            return
        from langfuse import get_client

        with get_client().start_as_current_observation(as_type="generation", name=name, model=model) as gen:
            yield gen
    except Exception as exc:  # noqa: BLE001 - telemetry never blocks care
        log.warning("generation span unavailable: %s", exc.__class__.__name__, extra={"component": "telemetry"})
        yield _NoGeneration()


def record_usage(gen: Any, usage: Any, **metadata: Any) -> None:
    try:
        gen.update(
            usage_details={"input": usage.input_tokens, "output": usage.output_tokens, "cache_read_input_tokens": usage.cache_read_tokens},
            metadata={k: v for k, v in metadata.items() if v is not None},
        )
    except Exception:  # noqa: BLE001
        pass


def tracer_configured() -> bool:
    return bool(settings.secret(settings.langfuse_public_key_file) and settings.secret(settings.langfuse_secret_key_file))
