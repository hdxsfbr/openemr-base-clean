"""PHI-free telemetry (ADR-0007): Langfuse's LangGraph callback handler with a
mask that replaces every input and output payload with a digest. Refuses to
start if LangSmith tracing variables are set. Telemetry never blocks care:
every observation degrades to a no-op when the tracer is off or fails, and an
exception raised by the code inside an observation propagates unchanged (a
`ModelError` inside a generation span must still reach the graph's fallback)."""

from __future__ import annotations

import json
import logging
import os
import sys
from contextlib import contextmanager
from typing import Any, Iterator

from .settings import settings
from .turn_outcome import turn_error, verification_outcome

log = logging.getLogger("copilot.telemetry")

FORBIDDEN_ENV = ("LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING", "LANGCHAIN_API_KEY", "LANGSMITH_API_KEY")

# Trace scores (ADR-0007 dashboard minimum: verification pass/fail rate and error rate).
SCORE_VERIFICATION_PASSED = "verification_passed"
SCORE_TURN_ERROR = "turn_error"


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
    """The observation handed out when the tracer is off: every method is a no-op."""

    def update(self, **kwargs: Any) -> None:
        return None

    def update_trace(self, **kwargs: Any) -> None:
        return None

    def score_trace(self, **kwargs: Any) -> None:
        return None


def _close(cm: Any, exc_type: Any, exc: Any, tb: Any) -> None:
    """Exit a Langfuse observation context; its own failures are swallowed."""
    try:
        cm.__exit__(exc_type, exc, tb)
    except Exception:  # noqa: BLE001
        pass


@contextmanager
def _observation(as_type: str, name: str, label: str, correlation_id: str | None, **kwargs: Any) -> Iterator[Any]:
    """Open one Langfuse observation as the current context and yield it, or
    yield a no-op when the tracer is off or fails to open. The body's own
    exception is re-raised unchanged after the observation is closed with it;
    a `try/except` around the `yield` in a generator-based context manager
    would otherwise turn it into `RuntimeError("generator didn't stop after
    throw()")` when the handler yields a second time."""
    cm: Any = None
    obs: Any = _NoGeneration()
    try:
        if _ensure_client():
            from langfuse import get_client

            cm = get_client().start_as_current_observation(as_type=as_type, name=name, **kwargs)
            obs = cm.__enter__()
    except Exception as exc:  # noqa: BLE001 - telemetry never blocks care
        log.warning("%s unavailable: %s", label, exc.__class__.__name__, extra={"component": "telemetry", "correlation_id": correlation_id})
        cm, obs = None, _NoGeneration()
    if cm is None:
        yield obs
        return
    try:
        yield obs
    except BaseException:
        _close(cm, *sys.exc_info())
        raise
    _close(cm, None, None, None)


@contextmanager
def turn_trace(correlation_id: str, conversation_id: str) -> Iterator[Any]:
    """The root span for one turn. Node spans (LangChain callback) and
    generation spans nest under it because it sets the current context."""
    with _observation("span", "copilot.turn", "turn trace", correlation_id) as span:
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


def score_trace(span: Any, name: str, value: float) -> None:
    """Attach one numeric score to the turn's trace (langfuse 4.x
    `LangfuseSpan.score_trace`). No-op when the tracer is off; never raises."""
    try:
        span.score_trace(name=name, value=float(value))
    except Exception:  # noqa: BLE001 - telemetry never blocks care
        pass


def finish_turn_trace(span: Any, state: dict[str, Any]) -> None:
    """Attach the PHI-free totals of a finished turn and the two dashboard
    scores: `verification_passed` (1.0 for `passed`, 0.0 for `partial` or
    `failed_closed`, absent when the verifier did not run) and `turn_error`
    (1.0 for a failed or timed-out turn, else 0.0). `state` is the final graph
    state, or `{"status": "timeout"}` / `{"status": "failed"}` from the API's
    own failure paths."""
    outcome = verification_outcome(state)
    try:
        span.update(metadata={
            "status": state.get("status"),
            "turn_type": state.get("turn_type"),
            "claims": len(state.get("accepted") or []),
            "withheld": len(state.get("rejected") or []),
            "tool_calls": len(state.get("tool_calls") or []),
            "timings_ms": state.get("timings_ms") or {},
            "usage": state.get("usage") or {},
            "verification": outcome,
        })
    except Exception:  # noqa: BLE001
        pass
    if outcome != "not_run":
        score_trace(span, SCORE_VERIFICATION_PASSED, 1.0 if outcome == "passed" else 0.0)
    score_trace(span, SCORE_TURN_ERROR, 1.0 if turn_error(state) else 0.0)


@contextmanager
def generation(name: str, model: str, correlation_id: str | None) -> Iterator[Any]:
    """A Langfuse generation span for one model call, nested under the current
    turn trace. Only usage, model, and PHI-free metadata are ever set on it;
    inputs and outputs are never attached. No-op when the tracer is off."""
    with _observation("generation", name, "generation span", correlation_id, model=model) as gen:
        yield gen


@contextmanager
def tool_observation(name: str, correlation_id: str | None) -> Iterator[Any]:
    """A Langfuse tool-type observation for one gateway call, nested under
    the current turn trace, so tool volume, failures, and latency show on the
    agent dashboards. Only status, reason, and counts are attached; never
    records. No-op when the tracer is off."""
    with _observation("tool", name, "tool observation", correlation_id) as obs:
        yield obs


def record_tool_result(obs: Any, response: Any) -> None:
    """Attach the PHI-free outcome of a tool call to its observation."""
    try:
        status = getattr(getattr(response, "status", None), "value", None) or str(getattr(response, "status", ""))
        reason = getattr(response, "reason", None)
        obs.update(
            level="ERROR" if status == "unavailable" else "DEFAULT",
            status_message=reason if status == "unavailable" else None,
            metadata={
                "status": status,
                "reason": reason,
                "record_count": len(getattr(response, "records", None) or []),
                "truncated": bool(getattr(response, "truncated", False)),
                "gateway_latency_ms": getattr(response, "latency_ms", None),
            },
        )
    except Exception:  # noqa: BLE001
        pass


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
