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
from app.telemetry import finish_turn_trace, generation, mask, record_exchange, score_trace, tool_observation, turn_trace
from app.turn_outcome import turn_error, verification_outcome


class FakeSpan:
    """Only the methods langfuse 4.x spans really have: a fake `update_trace`
    here is what let a call to that removed method go unnoticed."""

    def __init__(self) -> None:
        self.scores: dict[str, float] = {}
        self.metadata: dict[str, Any] = {}
        self.io: dict[str, Any] = {}
        self.trace_io: dict[str, Any] = {}

    def update(self, **kwargs: Any) -> None:
        self.metadata.update(kwargs.get("metadata") or {})
        self.io.update({k: v for k, v in kwargs.items() if k in ("input", "output")})

    def set_trace_io(self, **kwargs: Any) -> None:
        self.trace_io.update(kwargs)

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

    class Propagated:
        def __enter__(self) -> None:
            return None

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            return False

    def propagate_attributes(**kwargs: Any) -> Propagated:
        PROPAGATED.append(kwargs)
        return Propagated()

    PROPAGATED.clear()
    fake = types.ModuleType("langfuse")
    fake.get_client = lambda: Client()  # type: ignore[attr-defined]
    fake.propagate_attributes = propagate_attributes  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langfuse", fake)
    monkeypatch.setattr(telemetry, "_ensure_client", lambda: True)
    return opened


PROPAGATED: list[dict[str, Any]] = []  # what the fake `langfuse.propagate_attributes` was called with


@pytest.mark.parametrize(
    ("cm", "args", "opened_as"),
    [
        (generation, ("narrate", "model-x", "cid-1"), {"as_type": "generation", "name": "narrate", "model": "model-x"}),
        (tool_observation, ("problems", "cid-1"), {"as_type": "tool", "name": "problems"}),
        (turn_trace, ("cid-1", "conv-1"), {"as_type": "span", "name": "copilot.turn"}),
    ],
    ids=["generation", "tool_observation", "turn_trace"],
)
@pytest.mark.parametrize("trace_content", [True, False], ids=["content", "masked"])
def test_exception_inside_a_real_observation_propagates_unchanged_and_closes_the_span(cm, args, opened_as, trace_content: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    """The production branch of `_observation` (tracer on): the Langfuse
    context manager is entered, the body raises, and the ModelError reaches
    the caller unchanged instead of RuntimeError('generator didn't stop after
    throw()'). With content on, `__exit__` receives the body's own
    `(ModelError, instance, traceback)`. In masked mode it receives nothing
    (OpenTelemetry would export the message) and the span is marked with the
    exception class only."""
    monkeypatch.setattr(telemetry.settings, "trace_content", trace_content)
    opened = _fake_langfuse(monkeypatch)
    with pytest.raises(ModelError) as info:
        with cm(*args) as obs:
            assert obs is opened[0].observation, "the span yielded is the one the Langfuse context manager returned"
            raise ModelError("rate_limited")
    assert info.value.kind == "rate_limited"
    assert len(opened) == 1 and opened[0].entered and opened[0].kwargs == opened_as
    exc_type, exc, tb = opened[0].exit_args
    if trace_content:
        assert exc_type is ModelError and exc is info.value and tb is not None
    else:
        assert (exc_type, exc, tb) == (None, None, None)
        assert opened[0].observation.calls == [("update", {"level": "ERROR", "status_message": "ModelError"})]


def test_a_real_observation_is_closed_cleanly_on_normal_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    opened = _fake_langfuse(monkeypatch)
    with generation("narrate", "model-x", "cid-1") as gen:
        gen.update(metadata={"claims": 1})
    assert opened[0].exit_args == (None, None, None)
    assert opened[0].observation.calls == [("update", {"metadata": {"claims": 1}})]


def test_a_failing_observation_exit_never_masks_the_body_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_close` swallows the tracer's own `__exit__` failure so the body's
    ModelError, not the tracer's RuntimeError, is what propagates."""
    for trace_content, closed_with in ((True, ModelError), (False, None)):
        monkeypatch.setattr(telemetry.settings, "trace_content", trace_content)
        opened = _fake_langfuse(monkeypatch, exit_raises=True)
        with pytest.raises(ModelError) as info:
            with generation("narrate", "model-x", "cid-1"):
                raise ModelError("overloaded")
        assert info.value.kind == "overloaded" and opened[0].exit_args[0] is closed_with


def test_exception_text_never_reaches_the_exporter_in_masked_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Against the real SDK, no network: the SDK's mask covers input, output,
    and metadata only, so an error that quotes record text must not leave
    through the span status, the OpenTelemetry `exception` event, or the
    LangChain handler's `status_message`. Also the contract test for the SDK
    surface this module relies on."""
    from langchain_core.runnables import RunnableLambda
    from langfuse import Langfuse, propagate_attributes  # noqa: F401 - import is part of the contract
    from langfuse._client.span import LangfuseSpan
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    assert all(hasattr(LangfuseSpan, name) for name in ("update", "score_trace", "set_trace_io"))
    needle = "Zebulon Synthetic metformin 500 mg"
    exporter = InMemorySpanExporter()
    client = Langfuse(public_key="pk-lf-test", secret_key="sk-lf-test", host="http://127.0.0.1:9", span_exporter=exporter, mask=mask)
    monkeypatch.setattr(telemetry.settings, "trace_content", False)
    monkeypatch.setattr(telemetry, "_ensure_client", lambda: True)

    def boom(_: Any) -> None:
        raise ValueError(f"contract violation in record: {needle}")

    with pytest.raises(ValueError, match="Zebulon"):
        with turn_trace("cid-leak-1", "conv-leak-1"):
            with tool_observation("lab_results", "cid-leak-1"):
                pass
            with generation("narrate", "model-x", "cid-leak-1"):
                RunnableLambda(boom).invoke({"question": needle}, config={"callbacks": [telemetry._callback_handler()]})
    client.flush()

    spans = exporter.get_finished_spans()
    assert {s.name for s in spans} >= {"copilot.turn", "narrate", "lab_results"}
    exported = json.dumps([{"attributes": dict(s.attributes or {}), "status": s.status.description, "events": [{"name": e.name, "attributes": dict(e.attributes or {})} for e in s.events]} for s in spans], default=str)
    assert "Zebulon" not in exported and "metformin" not in exported
    assert "ValueError" in exported, "the exception class is what an operator still sees"


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


def test_turn_trace_sets_the_trace_attributes_through_propagate_attributes(monkeypatch: pytest.MonkeyPatch) -> None:
    """langfuse 4.x has no `span.update_trace`; name, session, tags, and ids go
    through the module-level `propagate_attributes`."""
    _fake_langfuse(monkeypatch)
    with turn_trace("cid-1", "conv-1"):
        pass
    assert PROPAGATED == [{"trace_name": "copilot.turn", "session_id": "conv-1", "tags": ["copilot"], "metadata": {"correlation_id": "cid-1", "conversation_id": "conv-1"}}]


def test_mask_keeps_allowlisted_metadata_readable_and_digests_everything_else() -> None:
    totals = {"status": "partial", "turn_type": "followup", "claims": 3, "withheld": 1, "timings_ms": {"narrate": 3578.2}, "usage": {"input_tokens": 182}, "verification": "partial", "summary_replaced": "ungrounded_number", "prompt_version": "a1b2c3d4e5f6"}
    assert mask(totals) == totals
    assert mask({"reason": None, "record_count": 4, "status": "ok", "truncated": False, "gateway_latency_ms": 12.5})["record_count"] == 4
    for payload in (
        {"status": "complete", "question": "What changed?"},  # unknown key
        {"status": "Metformin 500 mg was stopped"},  # free text under a known key
        {"usage": {"note": "Metformin"}},  # nested non-number
        {"claims": [{"text": "Metformin"}]},  # list value
        {"reason": "Metformin"}, {"status": "Smith"}, {"reason": "Müller"}, {"reason": "1985-03-14"},  # single-token chart content
        {"reason": "555-12-3456"}, {"status": "MRN:00123456"}, {"reason": "metformin\n"},
        {"usage": {"Jane Doe, DOB 1985-03-14": 1}},  # chart content as a nested key
        {"prompt_version": "not-a-hash"},
        "What changed since the last visit?",
        ["a", "b"],
        {},
    ):
        assert mask(payload).get("digest") is True, payload
    assert mask(None) is None, "the SDK masks absent fields too; a digest of None would overwrite real attributes"
    assert mask({"effort": "n/a", "stop_reason": "end_turn", "attempt": 0, "prompt_version": "0a1b2c3d4e5f"})["effort"] == "n/a"


def test_mask_keeps_bounded_document_preview_telemetry_and_rejects_source_content() -> None:
    metadata = {
        "status": "complete", "handoff_id": "a" * 32, "contract_version": "2.0.0",
        "model_version": "deterministic_parser_v1", "timings_ms": {"extract": 12.5},
        "usage": {"input_tokens": 0, "output_tokens": 0, "model_calls": 0, "cost_microusd": 0},
        "record_count": 6, "extraction_confidence": "high", "retrieval_hit_count": 0,
        "verification": "passed", "eval_outcome": "not_run",
    }
    assert mask(metadata) == metadata
    assert mask({**metadata, "source_id": "document:0123456789abcdef0123456789abcdef"})["digest"] is True
    assert mask({**metadata, "status": "Sample analyte 7.2"})["digest"] is True


def test_finish_turn_trace_reports_why_the_summary_was_replaced_without_chart_content() -> None:
    span = FakeSpan()
    finish_turn_trace(span, {"status": "complete", "raw_claims": [{}], "rejected": [], "summary_basis": "deterministic", "summary_reason": "ungrounded_number:40"})
    assert span.metadata["summary_replaced"] == "ungrounded_number" and span.scores["summary_model_kept"] == 0.0
    assert mask(span.metadata) == span.metadata, "the turn totals must survive the mask"
    span = FakeSpan()
    finish_turn_trace(span, {"status": "complete", "raw_claims": [{}], "rejected": [], "summary_basis": "deterministic", "summary_reason": "lexicon:judgment"})
    assert span.metadata["summary_replaced"] == "lexicon:judgment"
    span = FakeSpan()
    finish_turn_trace(span, {"status": "complete", "raw_claims": [{}], "rejected": [], "summary_basis": "model", "summary_reason": "ok"})
    assert span.metadata["summary_replaced"] is None and span.scores["summary_model_kept"] == 1.0


def test_exchange_content_is_attached_only_when_trace_content_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"status": "complete", "raw_claims": [{}], "rejected": [], "question": "What changed?", "summary": "Lisinopril started.", "summary_basis": "model", "summary_reason": "ok", "accepted": [{"id": "c1"}]}
    messages = [{"role": "user", "content": "EVIDENCE PACK: ..."}]

    monkeypatch.setattr(telemetry.settings, "trace_content", False)
    span, gen = FakeSpan(), FakeSpan()
    finish_turn_trace(span, state)
    record_exchange(gen, "SYSTEM", messages, '{"claims": []}')
    assert span.io == {} and span.trace_io == {} and gen.io == {}

    monkeypatch.setattr(telemetry.settings, "trace_content", True)
    span, gen = FakeSpan(), FakeSpan()
    finish_turn_trace(span, state)
    record_exchange(gen, "SYSTEM", messages, '{"claims": []}')
    assert span.io["input"]["question"] == "What changed?" and span.io["output"]["summary"] == "Lisinopril started."
    assert span.trace_io == span.io, "trace-level I/O is what the Sessions view renders"
    assert gen.io == {"input": {"system": "SYSTEM", "messages": messages}, "output": '{"claims": []}'}


@pytest.mark.parametrize(("trace_content", "installs_mask"), [(False, True), (True, False)])
def test_the_mask_is_installed_unless_trace_content_is_on(trace_content: bool, installs_mask: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[dict[str, Any]] = []
    fake = types.ModuleType("langfuse")
    fake.Langfuse = lambda **kwargs: built.append(kwargs)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langfuse", fake)
    monkeypatch.setattr(telemetry, "_client_ready", False)
    monkeypatch.setattr(telemetry.settings, "trace_content", trace_content)
    monkeypatch.setattr(type(telemetry.settings), "secret", lambda self, path: "key")
    assert telemetry._ensure_client() is True
    assert (built[0]["mask"] is mask) is installs_mask and (built[0]["mask"] is None) is not installs_mask


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
