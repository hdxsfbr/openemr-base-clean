"""Tests for controls the design documents already cite (ADR-0004 breaker,
ADR-0005 checkpoint content, ADR-0007 LangSmith guard). Each one turns a
sentence in ARCHITECTURE.md from stated intent into an automated check."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import types
from pathlib import Path
from typing import Any

import anthropic
import httpx
import pytest
from langgraph.checkpoint.base import CheckpointMetadata
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app import budget
from app import model as model_module
from app.contracts import Claim, ClaimFacts, Limitation, SourceSummary, TurnResponse, Verification
from app.contracts.tools import AllergyRecord, Code, EncounterRecord, LabResultRecord, MedicationRecord, NoteRecord, PatientContextRecord, Person, ProblemRecord
from app.graph.build import build_graph
from app.graph.nodes import Runtime
from app.graph.state import PER_TURN_DEFAULTS, TurnState
from app.model import AnthropicModel, CircuitBreaker, ModelError
from app.state_store import drop_token, put_token
from app.telemetry import guard_environment
from conftest import FIXTURE_DIR, FakeGateway, FakeModel

TODAY = dt.date(2026, 9, 15)
CID = "57b815a321edb1bbab13699dec3adb20"
CFG = {"configurable": {"thread_id": CID}}
HYPERLIPIDEMIA = "openemr:lists:9000003:a2bfa267-d103-4be7-a4c2-a3699fdea462"
# A value that could only reach the checkpoint through graph state.
TOKEN = "tok-" + "f" * 40 + ".sig-" + "e" * 20

RECORD_MODELS = (PatientContextRecord, EncounterRecord, NoteRecord, ProblemRecord, MedicationRecord, AllergyRecord, LabResultRecord, Person, Code)
# Keys graph state carries by design (claims and their facts, sources, limitations, history,
# evidence summaries). A record-model field outside this set can only come from a raw record.
STATE_KEYS = (
    set(TurnState.__annotations__)
    | set(Claim.model_fields) | set(ClaimFacts.model_fields) | set(SourceSummary.model_fields)
    | set(Limitation.model_fields) | set(Verification.model_fields) | set(TurnResponse.model_fields)
    | {"tool", "status", "record_count", "truncated", "absence_state"}  # EvidencePack.evidence_summary
    | {"source_id", "table", "id", "label", "encounter_id", "order_id"}  # nodes.source_summary
    | {"claim_id", "rule", "detail"}  # verifier rejections
    | set(CheckpointMetadata.__annotations__)  # the checkpointer's own metadata column ({"source": "loop", "step": ...})
)


def _turn_input(question: str, turn_id: str) -> dict[str, Any]:
    state = dict(PER_TURN_DEFAULTS)
    state.update({"conversation_id": CID, "turn_id": turn_id, "correlation_id": "ctrl-turn-0001", "question": question, "fault": None})
    return state


def _checkpoint_bytes(path: str) -> bytes:
    """Every cell of every row of every table, so no channel, write, or metadata column is skipped."""
    con = sqlite3.connect(path)
    out = bytearray()
    for (table,) in con.execute("select name from sqlite_master where type = 'table'"):
        for row in con.execute(f"select * from {table}"):  # noqa: S608 - table names come from sqlite_master
            for cell in row:
                if isinstance(cell, bytes):
                    out += cell
                elif isinstance(cell, str):
                    out += cell.encode()
    con.close()
    return bytes(out)


def _key_encodings(key: str) -> list[bytes]:
    """How a dict key appears in the serialized checkpoint: msgpack fixstr (the
    checkpointer's default serializer) or a JSON-quoted string."""
    raw = key.encode()
    forms = [b'"' + raw + b'"']
    if len(raw) < 32:
        forms.append(bytes([0xA0 | len(raw)]) + raw)
    return forms


@pytest.mark.anyio
async def test_checkpoint_holds_no_note_body_record_shape_or_token(tmp_path: Path) -> None:
    """ADR-0005: raw tool records live in the per-turn cache and the delegation
    token in its own; the SQLite checkpoint must hold neither after a UC-01
    turn and a follow-up that retrieved notes. Lab values and doses are not
    asserted absent: verified claims carry them by design."""
    budget.daily.reset()
    path = str(tmp_path / "checkpoints.sqlite")
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        claim = {"id": "c1", "type": "change_event", "text": "Hyperlipidemia added to the problem list on 2026-08-31.", "facts": {"section": "problems", "kind": "added", "date": "2026-08-31"}, "source_ids": [HYPERLIPIDEMIA]}
        put_token("c0ffee00c0ffee01", TOKEN)
        g = build_graph(Runtime(gateway=FakeGateway(), model=FakeModel(claims=[claim]), today=lambda: TODAY), checkpointer=saver)
        first = await g.ainvoke(_turn_input("What changed since the last visit?", "c0ffee00c0ffee01"), CFG)
        drop_token("c0ffee00c0ffee01")
        assert first["turn_type"] == "uc01_first" and [c["id"] for c in first["accepted"]] == ["c1"]
        assert "clinical_notes" in {e["tool"] for e in first["evidence"]}
        put_token("c0ffee00c0ffee02", TOKEN)
        gateway = FakeGateway()
        model = FakeModel(claims=[], plan_calls=[("clinical_notes", {"term": "amlodipine"})])
        g2 = build_graph(Runtime(gateway=gateway, model=model, today=lambda: TODAY), checkpointer=saver)
        second = await g2.ainvoke(_turn_input("Was the amlodipine stop documented in a note?", "c0ffee00c0ffee02"), CFG)
        drop_token("c0ffee00c0ffee02")
        assert second["turn_type"] == "followup" and gateway.calls[0][0] == "clinical_notes" and len(second["history"]) == 2

    blobs = _checkpoint_bytes(path)
    # Positive controls: the scan reads real content in both encodings it checks.
    assert b"Hyperlipidemia added to the problem list" in blobs
    assert any(form in blobs for form in _key_encodings("history"))

    assert TOKEN.encode() not in blobs, "delegation token found in the checkpoint"

    notes = json.loads((FIXTURE_DIR / "af-dq-a2.clinical_notes.json").read_text())["records"]
    assert notes
    for note in notes:
        body = note["text"]
        assert body[:48].encode() not in blobs and body[-48:].encode() not in blobs, "verbatim note body found in the checkpoint"

    record_only = {name for m in RECORD_MODELS for name in m.model_fields} - STATE_KEYS
    assert {"numeric_value", "note_type", "dose_text", "prescriber", "status_basis", "term_matched", "age_band"} <= record_only
    found = sorted(key for key in record_only if len(key) >= 4 and any(form in blobs for form in _key_encodings(key)))
    assert found == [], f"raw record key shape in the checkpoint (ADR-0005 breach): {found}"


def _clock(monkeypatch: pytest.MonkeyPatch, start: float = 1_000.0) -> dict[str, float]:
    clock = {"now": start}
    monkeypatch.setattr(model_module, "time", types.SimpleNamespace(time=lambda: clock["now"]))
    return clock


def test_circuit_breaker_opens_after_three_failures_and_closes_after_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _clock(monkeypatch)
    breaker = CircuitBreaker(threshold=3, cooldown=60.0)
    breaker.record(False)
    breaker.record(False)
    assert not breaker.is_open() and breaker.failures == 2
    breaker.record(False)
    assert breaker.is_open() and breaker.opened_at == clock["now"]
    clock["now"] += 59.0
    assert breaker.is_open()
    clock["now"] += 2.0
    assert not breaker.is_open() and breaker.failures == 0 and breaker.opened_at is None
    # A success before the threshold resets the count.
    breaker.record(False)
    breaker.record(False)
    breaker.record(True)
    breaker.record(False)
    assert not breaker.is_open() and breaker.failures == 1


@pytest.mark.anyio
async def test_provider_connection_failures_trip_the_breaker_and_short_circuit_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Three connection failures open the breaker; the fourth call raises
    `circuit_open` without touching the SDK; after the cooldown the call goes
    through again."""
    clock = _clock(monkeypatch)
    monkeypatch.setattr(model_module, "breaker", CircuitBreaker(threshold=3, cooldown=60.0))
    model = AnthropicModel.__new__(AnthropicModel)
    model._anthropic = anthropic
    attempts = 0

    async def failing():
        nonlocal attempts
        attempts += 1
        raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.invalid/v1/messages"))

    for _ in range(3):
        with pytest.raises(ModelError) as info:
            await model._guarded(failing)
        assert info.value.kind == "timeout"
    assert model_module.breaker.is_open() and attempts == 3
    with pytest.raises(ModelError) as info:
        await model._guarded(failing)
    assert info.value.kind == "circuit_open" and attempts == 3

    clock["now"] += 61.0

    async def ok():
        return types.SimpleNamespace(content=[], stop_reason="end_turn", usage=None)

    assert (await model._guarded(ok)).stop_reason == "end_turn"
    assert not model_module.breaker.is_open() and model_module.breaker.failures == 0


def test_guard_environment_raises_on_langsmith_tracing(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING", "LANGCHAIN_API_KEY", "LANGSMITH_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    guard_environment()
    monkeypatch.setenv("LANGSMITH_TRACING", "1")
    with pytest.raises(RuntimeError, match="LANGSMITH_TRACING"):
        guard_environment()
