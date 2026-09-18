"""Telemetry and outcome tests (ADR-0007): observations never block care and
never mask the code's own exceptions; the two dashboard scores and the
verification counter come from one outcome helper; every telemetry log line
carries the correlation id."""

from __future__ import annotations

import json
import logging
import sys
import types
from typing import Any

import anthropic
import pytest

from app import telemetry
from app.metrics import Metrics, bounded_reason
from app.model import AnthropicModel, ModelError
from app.telemetry import finish_turn_trace, generation, score_trace, tool_observation, turn_trace
from app.turn_outcome import turn_error, verification_outcome


class FakeSpan:
    def __init__(self) -> None:
        self.scores: dict[str, float] = {}
        self.metadata: dict[str, Any] = {}

    def update(self, **kwargs: Any) -> None:
        self.metadata.update(kwargs.get("metadata") or {})

    def update_trace(self, **kwargs: Any) -> None:
        return None

    def score_trace(self, *, name: str, value: float, **kwargs: Any) -> None:
        self.scores[name] = value


@pytest.mark.parametrize(
    ("cm", "args"),
    [(generation, ("narrate", "model-x", "cid-1")), (tool_observation, ("problems", "cid-1")), (turn_trace, ("cid-1", "conv-1"))],
    ids=["generation", "tool_observation", "turn_trace"],
)
def test_exception_inside_an_observation_propagates_unchanged(cm, args) -> None:
    """A ModelError raised inside a generation span must reach the graph's
    `except ModelError` fallback, not arrive as RuntimeError('generator didn't
    stop after throw()')."""
    with pytest.raises(ModelError) as info:
        with cm(*args):
            raise ModelError("rate_limited")
    assert info.value.kind == "rate_limited"


class _RecordingObservation:
    """What the fake Langfuse context manager yields: records the PHI-free
    calls the telemetry helpers make on it."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def update(self, **kwargs: Any) -> None:
        self.calls.append(("update", kwargs))

    def update_trace(self, **kwargs: Any) -> None:
        self.calls.append(("update_trace", kwargs))

    def score_trace(self, **kwargs: Any) -> None:
        self.calls.append(("score_trace", kwargs))


class _RecordingContext:
    """Stands in for `get_client().start_as_current_observation(...)`: records
    the `__enter__` call and the `(exc_type, exc, tb)` triple `__exit__` gets."""

    def __init__(self, exit_raises: bool = False, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.exit_raises = exit_raises
        self.entered = False
        self.exit_args: tuple[Any, Any, Any] | None = None
        self.observation = _RecordingObservation()

    def __enter__(self) -> _RecordingObservation:
        self.entered = True
        return self.observation

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        self.exit_args = (exc_type, exc, tb)
        if self.exit_raises:
            raise RuntimeError("langfuse flush failed")
        return False


def _fake_langfuse(monkeypatch: pytest.MonkeyPatch, *, exit_raises: bool = False) -> list[_RecordingContext]:
    """Route `_observation` through its production branch without a network:
    `_ensure_client()` reports a client and a fake `langfuse` module in
    `sys.modules` serves `get_client()`, whose `start_as_current_observation`
    hands out recording context managers. Returns the list they are appended to."""
    opened: list[_RecordingContext] = []

    class Client:
        def start_as_current_observation(self, **kwargs: Any) -> _RecordingContext:
            cm = _RecordingContext(exit_raises=exit_raises, **kwargs)
            opened.append(cm)
            return cm

    fake = types.ModuleType("langfuse")
    fake.get_client = lambda: Client()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langfuse", fake)
    monkeypatch.setattr(telemetry, "_ensure_client", lambda: True)
    return opened


@pytest.mark.parametrize(
    ("cm", "args", "opened_as"),
    [
        (generation, ("narrate", "model-x", "cid-1"), {"as_type": "generation", "name": "narrate", "model": "model-x"}),
        (tool_observation, ("problems", "cid-1"), {"as_type": "tool", "name": "problems"}),
        (turn_trace, ("cid-1", "conv-1"), {"as_type": "span", "name": "copilot.turn"}),
    ],
    ids=["generation", "tool_observation", "turn_trace"],
)
def test_exception_inside_a_real_observation_propagates_unchanged_and_closes_the_span(cm, args, opened_as, monkeypatch: pytest.MonkeyPatch) -> None:
    """The production branch of `_observation` (tracer on): the Langfuse
    context manager is entered, the body raises, `__exit__` receives the
    body's own `(ModelError, instance, traceback)`, and the ModelError reaches
    the caller unchanged instead of RuntimeError('generator didn't stop after
    throw()')."""
    opened = _fake_langfuse(monkeypatch)
    with pytest.raises(ModelError) as info:
        with cm(*args) as obs:
            assert obs is opened[0].observation, "the span yielded is the one the Langfuse context manager returned"
            raise ModelError("rate_limited")
    assert info.value.kind == "rate_limited"
    assert len(opened) == 1 and opened[0].entered and opened[0].kwargs == opened_as
    exc_type, exc, tb = opened[0].exit_args
    assert exc_type is ModelError and exc is info.value and tb is not None


def test_a_real_observation_is_closed_cleanly_on_normal_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    opened = _fake_langfuse(monkeypatch)
    with generation("narrate", "model-x", "cid-1") as gen:
        gen.update(metadata={"claims": 1})
    assert opened[0].exit_args == (None, None, None)
    assert opened[0].observation.calls == [("update", {"metadata": {"claims": 1}})]


def test_a_failing_observation_exit_never_masks_the_body_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_close` swallows the tracer's own `__exit__` failure so the body's
    ModelError, not the tracer's RuntimeError, is what propagates."""
    opened = _fake_langfuse(monkeypatch, exit_raises=True)
    with pytest.raises(ModelError) as info:
        with generation("narrate", "model-x", "cid-1"):
            raise ModelError("overloaded")
    assert info.value.kind == "overloaded" and opened[0].exit_args[0] is ModelError


def test_observation_failure_logs_the_correlation_id(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    def broken_client() -> bool:
        raise RuntimeError("tracer down")

    monkeypatch.setattr(telemetry, "_ensure_client", broken_client)
    with caplog.at_level(logging.WARNING, logger="copilot.telemetry"):
        with generation("narrate", "model-x", "cid-gen-0001") as gen:
            assert isinstance(gen, telemetry._NoGeneration)
        with tool_observation("problems", "cid-tool-0002") as obs:
            assert isinstance(obs, telemetry._NoGeneration)
    records = [(r.getMessage(), r.correlation_id) for r in caplog.records if r.name == "copilot.telemetry"]
    assert records == [("generation span unavailable: RuntimeError", "cid-gen-0001"), ("tool observation unavailable: RuntimeError", "cid-tool-0002")]


@pytest.mark.parametrize(
    ("state", "outcome", "error"),
    [
        ({"status": "complete", "raw_claims": [], "rejected": []}, "passed", False),
        ({"status": "partial", "raw_claims": [{}], "rejected": [{"claim_id": "c1", "rule": "type_facts"}]}, "partial", False),
        ({"status": "fallback", "turn_type": "followup", "narrate_error": "timeout", "raw_claims": None}, "failed_closed", False),
        ({"status": "fallback", "turn_type": "uc01_first", "narrate_error": "timeout", "raw_claims": None}, "passed", False),
        ({"status": "denied", "raw_claims": None}, "not_run", False),
        ({"status": "timeout"}, "not_run", True),
        ({"status": "failed"}, "not_run", True),
        ({}, "not_run", True),
    ],
)
def test_verification_outcome_and_turn_error(state, outcome, error) -> None:
    assert verification_outcome(state) == outcome
    assert turn_error(state) is error


def test_finish_turn_trace_sets_the_two_dashboard_scores() -> None:
    span = FakeSpan()
    finish_turn_trace(span, {"status": "complete", "raw_claims": [], "rejected": [], "accepted": [{"id": "c1"}]})
    assert span.scores == {"verification_passed": 1.0, "turn_error": 0.0} and span.metadata["verification"] == "passed"
    span = FakeSpan()
    finish_turn_trace(span, {"status": "partial", "raw_claims": [{}], "rejected": [{"claim_id": "c1", "rule": "x"}]})
    assert span.scores == {"verification_passed": 0.0, "turn_error": 0.0}
    span = FakeSpan()
    finish_turn_trace(span, {"status": "denied", "raw_claims": None})
    assert span.scores == {"turn_error": 0.0}, "verification_passed is absent when the verifier did not run"
    span = FakeSpan()
    finish_turn_trace(span, {"status": "timeout"})
    assert span.scores == {"turn_error": 1.0}
    span = FakeSpan()
    finish_turn_trace(span, {"status": "failed"})
    assert span.scores == {"turn_error": 1.0}


def test_score_trace_never_raises_and_is_a_noop_when_the_tracer_is_off() -> None:
    class Broken:
        def score_trace(self, **kwargs: Any) -> None:
            raise RuntimeError("langfuse down")

    score_trace(Broken(), "verification_passed", 1.0)
    score_trace(object(), "verification_passed", 1.0)
    with turn_trace("cid-1", "conv-1") as span:
        assert isinstance(span, telemetry._NoGeneration)
        finish_turn_trace(span, {"status": "complete", "raw_claims": []})


@pytest.mark.anyio
async def test_dropped_claims_log_carries_the_correlation_id(caplog: pytest.LogCaptureFixture) -> None:
    """The model port receives the turn's correlation id and puts it on the
    'claims dropped by contract' line (A4); the SDK is replaced by a stub."""
    payload = {"claims": [{"type": "undated", "text": "   ", "source_ids": []}, {"type": "undated", "text": "Metformin has no clinical date.", "source_ids": []}], "summary": "", "suggestions": []}

    class Messages:
        async def create(self, **kwargs: Any):
            assert kwargs["output_config"] == {"effort": "low"}
            return type("Resp", (), {"content": [type("Block", (), {"type": "text", "text": json.dumps(payload)})()], "stop_reason": "end_turn", "usage": None})()

    model = AnthropicModel.__new__(AnthropicModel)
    model._anthropic = anthropic
    model.client = type("Client", (), {"messages": Messages()})()
    with caplog.at_level(logging.INFO, logger="copilot.model"):
        result = await model.narrate("Any undated records?", "== CONTEXT ==", "low", correlation_id="cid-drop-0001")
    assert result.claims is not None and [c.text for c in result.claims.claims] == ["Metformin has no clinical date."]
    record = next(r for r in caplog.records if r.getMessage() == "claims dropped by contract")
    assert record.correlation_id == "cid-drop-0001"


def test_tool_call_reason_label_is_bounded() -> None:
    assert bounded_reason(None) == "none" and bounded_reason("") == "none"
    assert bounded_reason("forbidden") == "forbidden" and bounded_reason("service_error") == "service_error"
    assert bounded_reason("http_503") == "http_5xx" and bounded_reason("http_404") == "http_4xx"
    assert bounded_reason("select * from patient_data") == "other"
    m = Metrics()
    m.tool_call("medications", "unavailable", "totally new reason " * 5)
    m.turn("complete", 1.0, {}, verification="not-an-outcome")
    text = m.prometheus()
    assert 'copilot_tool_calls_total{tool="medications",status="unavailable",reason="other"} 1' in text
    assert 'copilot_verification_total{outcome="other"} 1' in text
