"""Telemetry (ADR-0007): Langfuse's LangGraph callback handler. By default a
mask replaces every input and output payload with a digest, and only
allowlisted PHI-free metadata stays readable. With `COPILOT_TRACE_CONTENT` on
(tracer inside the compliance boundary) the mask is not installed and each
model call carries its full exchange. Refuses to start if LangSmith tracing
variables are set. Telemetry never blocks care: every observation degrades to
a no-op when the tracer is off or fails, and an exception raised by the code
inside an observation propagates unchanged (a `ModelError` inside a generation
span must still reach the graph's fallback)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from contextlib import contextmanager
from typing import Any, Iterator

from .settings import settings
from .turn_outcome import turn_error, verification_outcome

log = logging.getLogger("copilot.telemetry")

FORBIDDEN_ENV = ("LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING", "LANGCHAIN_API_KEY", "LANGSMITH_API_KEY")

# Trace scores (ADR-0007 dashboard minimum: verification pass/fail rate and error rate).
SCORE_VERIFICATION_PASSED = "verification_passed"
SCORE_TURN_ERROR = "turn_error"
# 1.0 when the model's narrative was shown, 0.0 when the deterministic summary replaced it.
SCORE_SUMMARY_MODEL_KEPT = "summary_model_kept"


def guard_environment() -> None:
    present = [k for k in FORBIDDEN_ENV if os.environ.get(k)]
    if present:
        raise RuntimeError(f"LangSmith tracing variables must not be set (PHI): {present}")


# The SDK passes metadata through the same mask as inputs and outputs, as one dict.
# These are the keys this module itself writes; their values are counts, enums, and ids.
METADATA_KEYS = frozenset({
    "status", "turn_type", "claims", "withheld", "tool_calls", "timings_ms", "usage", "verification",
    "summary_basis", "summary_replaced", "prompt_version",
    "effort", "attempt", "stop_reason",
    "reason", "record_count", "truncated", "gateway_latency_ms",
    "handoff_id", "contract_version", "model_version", "document_type", "retrieval_hit_count", "extraction_confidence", "eval_outcome",
    "worker", "intent", "topic", "limitation", "candidate_count", "hit_count", "artifact_revision", "correlation_id",
})
# Enum-shaped: lowercase-led snake/colon tokens ("partial", "lexicon:judgment", "http_503", "n/a").
# Rejects names, dates, MRN/SSN/phone shapes, non-ASCII, and anything with whitespace.
_ENUM_SHAPED = re.compile(r"[a-z][a-z0-9_:/]{0,63}")
_PROMPT_VERSION = re.compile(r"[0-9a-f]{12}")
_CONTRACT_VERSION = re.compile(r"\d+\.\d+\.\d+")
_HANDOFF_ID = re.compile(r"[a-f0-9]{32}")
_ARTIFACT_REVISION = re.compile(r"[a-f0-9]{64}")
_CORRELATION_ID = re.compile(r"[A-Za-z0-9\-._]{8,64}")


def _phi_free_scalar(key: str, value: Any) -> bool:
    if value is None or isinstance(value, (bool, int, float)):
        return True
    if not isinstance(value, str):
        return False
    pattern = _PROMPT_VERSION if key == "prompt_version" else _CONTRACT_VERSION if key == "contract_version" else _HANDOFF_ID if key == "handoff_id" else _ARTIFACT_REVISION if key == "artifact_revision" else _CORRELATION_ID if key == "correlation_id" else _ENUM_SHAPED
    return bool(pattern.fullmatch(value))


def _phi_free_metadata(data: Any) -> bool:
    """Whether `data` is one of this module's own metadata dicts: known keys
    only, each value a number, bool, None, an enum-shaped string, or a flat
    dict of enum-shaped keys to numbers (`timings_ms`, `usage`). The SDK runs
    node inputs and outputs through the same mask, so the shape check, not the
    caller, is what keeps chart content out."""
    if not isinstance(data, dict) or not data or not set(data) <= METADATA_KEYS:
        return False
    for key, value in data.items():
        if isinstance(value, dict):
            if not all(isinstance(k, str) and _ENUM_SHAPED.fullmatch(k) and isinstance(v, (bool, int, float)) for k, v in value.items()):
                return False
        elif not _phi_free_scalar(key, value):
            return False
    return True


def mask(data: Any) -> Any:
    """Replace any payload with a PHI-free digest: type, size, and counts only.
    Allowlisted metadata (counts, enums, ids) passes through unchanged."""
    try:
        # The SDK masks absent fields too; a digest of None would overwrite real attributes.
        if data is None:
            return None
        if _phi_free_metadata(data):
            return data
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
_trace_io_warned = False  # the SDK-surface warning in `_record_turn_io` fires once per process


def _ensure_client() -> bool:
    """Initialize the Langfuse client once; False when not configured. The PHI
    mask is installed unless `trace_content` is on."""
    global _client_ready
    if _client_ready:
        return True
    public = settings.secret(settings.langfuse_public_key_file)
    secret = settings.secret(settings.langfuse_secret_key_file)
    if not public or not secret:
        return False
    from langfuse import Langfuse

    Langfuse(public_key=public, secret_key=secret, host=settings.langfuse_host, mask=None if settings.trace_content else mask)
    _client_ready = True
    log.info("tracer ready: content %s", "on" if settings.trace_content else "masked", extra={"component": "telemetry"})
    return True


def prompt_version(*parts: str) -> str:
    """A short stable id for the prompt text a model call was made with, so
    traces and eval reports can be compared across prompt changes."""
    return hashlib.sha256("\x1e".join(parts).encode()).hexdigest()[:12]


def _callback_handler() -> Any:
    """The Langfuse LangChain handler. The SDK's mask covers input, output, and
    metadata only; an error's text goes out as the span's `status_message`, and
    a gateway or contract error can quote record text. In masked mode the
    message is therefore reduced to the exception class. The override is of a
    private SDK method: if it moves, the base class still masks payloads and
    the contract test in `test_telemetry.py` fails."""
    from langfuse.langchain import CallbackHandler

    if settings.trace_content:
        return CallbackHandler()

    class _ClassNameOnErrors(CallbackHandler):  # type: ignore[misc, valid-type]
        def _get_error_level_and_status_message(self, error: BaseException) -> tuple[Any, str]:
            level, _ = super()._get_error_level_and_status_message(error)
            return level, type(error).__name__

    return _ClassNameOnErrors()


def trace_config(correlation_id: str, conversation_id: str, turn_type: str) -> dict[str, Any]:
    """LangChain run config additions that attach the Langfuse handler and the
    PHI-free trace attributes. Empty when the tracer is not configured or fails."""
    try:
        if not _ensure_client():
            return {}
        return {
            "callbacks": [_callback_handler()],
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

    def set_trace_io(self, **kwargs: Any) -> None:
        return None

    def score_trace(self, **kwargs: Any) -> None:
        return None


def _close(cm: Any, exc_type: Any, exc: Any, tb: Any) -> None:
    """Exit a Langfuse observation context; its own failures are swallowed."""
    try:
        cm.__exit__(exc_type, exc, tb)
    except Exception:  # noqa: BLE001
        pass


def _close_on_error(cm: Any, obs: Any, exc: BaseException) -> None:
    """Close an observation whose body raised. With content on, the span is
    closed with the exception so the trace shows it in full. In masked mode it
    is closed clean and marked with the exception class only: OpenTelemetry
    would otherwise export the message and stack (status description and the
    `exception` event), which the SDK's mask never sees and which can quote
    record text."""
    if settings.trace_content:
        _close(cm, type(exc), exc, exc.__traceback__)
        return
    if obs is not None and isinstance(exc, Exception):  # cancellation and generator exit are not errors
        try:
            obs.update(level="ERROR", status_message=exc.__class__.__name__)
        except Exception:  # noqa: BLE001 - telemetry never blocks care
            pass
    _close(cm, None, None, None)


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
    except BaseException as exc:
        _close_on_error(cm, obs, exc)
        raise
    _close(cm, None, None, None)


@contextmanager
def _trace_attributes(correlation_id: str, conversation_id: str) -> Iterator[None]:
    """Set the trace-level attributes (name, session, tags, ids) on the current
    span and every span opened inside. langfuse 4.x replaced `span.update_trace`
    with the module-level `propagate_attributes`. Same exception discipline as
    `_observation`: tracer failures are swallowed, the body's own are not."""
    cm: Any = None
    try:
        if _ensure_client():
            from langfuse import propagate_attributes

            cm = propagate_attributes(
                trace_name="copilot.turn",
                session_id=conversation_id,
                tags=["copilot"],
                metadata={"correlation_id": correlation_id, "conversation_id": conversation_id},
            )
            cm.__enter__()
    except Exception as exc:  # noqa: BLE001 - telemetry never blocks care
        log.warning("trace attributes unavailable: %s", exc.__class__.__name__, extra={"component": "telemetry", "correlation_id": correlation_id})
        cm = None
    if cm is None:
        yield
        return
    try:
        yield
    except BaseException as exc:
        _close_on_error(cm, None, exc)
        raise
    _close(cm, None, None, None)


@contextmanager
def turn_trace(correlation_id: str, conversation_id: str) -> Iterator[Any]:
    """The root span for one turn. Node spans (LangChain callback) and
    generation spans nest under it because it sets the current context."""
    with _observation("span", "copilot.turn", "turn trace", correlation_id) as span:
        with _trace_attributes(correlation_id, conversation_id):
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
    own failure paths. With `trace_content` on, the question and the rendered
    answer are also set as the span's and the trace's input and output."""
    outcome = verification_outcome(state)
    basis = state.get("summary_basis")
    reason = str(state.get("summary_reason") or "")
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
            "summary_basis": basis,
            # Rule name only: the ungrounded token after the colon is chart content.
            "summary_replaced": (reason.split(":")[0] if reason.startswith("ungrounded") else reason) if basis == "deterministic" else None,
        })
    except Exception:  # noqa: BLE001
        pass
    if settings.trace_content:
        _record_turn_io(span, state, reason)
    if basis in ("model", "deterministic"):
        score_trace(span, SCORE_SUMMARY_MODEL_KEPT, 1.0 if basis == "model" else 0.0)
    if outcome != "not_run":
        score_trace(span, SCORE_VERIFICATION_PASSED, 1.0 if outcome == "passed" else 0.0)
    score_trace(span, SCORE_TURN_ERROR, 1.0 if turn_error(state) else 0.0)


def _record_turn_io(span: Any, state: dict[str, Any], summary_reason: str) -> None:
    """The turn as the physician saw it, plus what the verifier did to it."""
    turn_input = {"question": state.get("question"), "turn_type": state.get("turn_type"), "window_since": state.get("window_since")}
    turn_output = {
        "status": state.get("status"),
        "summary": state.get("summary"),
        "summary_basis": state.get("summary_basis"),
        "summary_reason": summary_reason,
        "raw_summary": state.get("raw_summary"),
        "claims": state.get("accepted") or [],
        "rejected": state.get("rejected") or [],
        "limitations": state.get("limitations") or [],
        "suggestions": state.get("suggestions") or [],
        "repair_attempted": bool(state.get("repair_attempted")),
    }
    try:
        span.update(input=turn_input, output=turn_output)
    except Exception:  # noqa: BLE001 - telemetry never blocks care
        pass
    try:
        # Trace-level I/O is what the Langfuse Sessions view renders as the conversation.
        # Deprecated in langfuse 4.x with no replacement yet; pyproject caps the major version.
        span.set_trace_io(input=turn_input, output=turn_output)
    except Exception as exc:  # noqa: BLE001 - telemetry never blocks care
        global _trace_io_warned
        if not _trace_io_warned:
            _trace_io_warned = True
            log.warning("trace io unavailable: %s", exc.__class__.__name__, extra={"component": "telemetry", "correlation_id": state.get("correlation_id")})


@contextmanager
def generation(name: str, model: str, correlation_id: str | None) -> Iterator[Any]:
    """A Langfuse generation span for one model call, nested under the current
    turn trace. Usage, model, and PHI-free metadata are always set on it; the
    exchange itself only through `record_exchange`. No-op when the tracer is off."""
    with _observation("generation", name, "generation span", correlation_id, model=model) as gen:
        yield gen


def record_exchange(gen: Any, system: str, messages: list[dict[str, Any]], output: Any) -> None:
    """Attach one model call's full exchange (system prompt, messages, raw
    output) to its generation span. Does nothing unless `trace_content` is on."""
    if not settings.trace_content:
        return
    try:
        gen.update(input={"system": system, "messages": messages}, output=output)
    except Exception:  # noqa: BLE001 - telemetry never blocks care
        pass


@contextmanager
def tool_observation(name: str, correlation_id: str | None) -> Iterator[Any]:
    """A Langfuse tool-type observation for one gateway call, nested under
    the current turn trace, so tool volume, failures, and latency show on the
    agent dashboards. Only status, reason, and counts are attached; never
    records. No-op when the tracer is off."""
    with _observation("tool", name, "tool observation", correlation_id) as obs:
        yield obs


@contextmanager
def evidence_worker_observation(correlation_id: str) -> Iterator[Any]:
    """A PHI-free worker span.  Exact queries, excerpts, and source IDs never
    enter this span, even when trace content is enabled for the synthetic demo."""
    with _observation("tool", "evidence_retriever", "evidence worker span", correlation_id) as obs:
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
