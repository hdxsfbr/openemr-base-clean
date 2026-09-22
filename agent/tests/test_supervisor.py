"""Closed deterministic supervisor route table (ADR-0013)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.supervisor import DeterministicSupervisor, SupervisorEvent


def _event(**overrides) -> SupervisorEvent:
    payload = {
        "event_kind": "chat_turn",
        "correlation_id": "conversation.turn-01",
        "conversation_id": "conversation-01",
        "turn_id": "turn-01",
        "authorized": True,
        "canceled": False,
        "guideline_intent": "none",
        "source_version_budget": True,
        "readiness": {
            "core_ready": True,
            "document_ready": True,
            "guideline_ready": True,
        },
        "contract_versions": {"handoff": "1.0.0", "evidence_query": "1.0.0"},
    }
    payload.update(overrides)
    return SupervisorEvent.model_validate(payload)


def _ref(kind: str, identity: str, version: str = "1") -> dict[str, str]:
    return {"kind": kind, "id": identity, "version": version, "integrity_sha256": "a" * 64}


def test_supervisor_route_table_is_closed_and_model_free() -> None:
    supervisor = DeterministicSupervisor(
        handoff_id=lambda: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    )
    cases = [
        (_event(authorized=False), "refused", (), ["authorization_denied"]),
        (_event(canceled=True), "canceled", (), ["canceled"]),
        (
            _event(
                event_kind="document_uploaded",
                conversation_id=None,
                turn_id=None,
                source_ref=_ref("source_document", "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
            ),
            "dispatched",
            ("intake_extractor",),
            [],
        ),
        (_event(guideline_intent="none"), "dispatched", ("patient_turn_graph",), []),
        (_event(guideline_intent="ambiguous"), "dispatched", ("patient_turn_graph",), ["guideline_intent_ambiguous"]),
        (_event(guideline_intent="prohibited"), "refused", (), ["guideline_intent_prohibited"]),
        (
            _event(
                guideline_intent="explicit_permitted",
                evidence_query_ref=_ref("evidence_query", "cccccccc-cccc-4ccc-8ccc-cccccccccccc", "1.0.0"),
                corpus_ref=_ref("corpus", "uspstf-2026q3", "uspstf-2026q3"),
            ),
            "dispatched",
            ("patient_turn_graph", "evidence_retriever"),
            [],
        ),
    ]

    for event, status, routes, limitations in cases:
        decision = supervisor.route(event, now="2026-09-22T00:00:00Z")
        assert decision.status == status
        assert decision.routes == routes
        assert decision.limitation_codes == limitations

    extraction = supervisor.route(cases[2][0], now="2026-09-22T00:00:00Z")
    assert extraction.handoffs[0].worker == "intake_extractor"
    assert extraction.handoffs[0].deadline_at == "2026-09-22T00:01:35Z"
    mixed = supervisor.route(cases[-1][0], now="2026-09-22T00:00:00Z")
    assert mixed.handoffs[0].worker == "evidence_retriever"
    assert mixed.handoffs[0].deadline_at == "2026-09-22T00:00:02Z"


def test_supervisor_rejects_untrusted_route_and_raw_content_fields() -> None:
    payload = _event().model_dump(mode="json")
    payload["route"] = "intake_extractor"
    payload["raw_document"] = "synthetic clinical content"

    with pytest.raises(ValidationError):
        SupervisorEvent.model_validate(payload)


def test_non_explicit_chat_cannot_smuggle_guideline_references() -> None:
    with pytest.raises(ValidationError, match="cannot smuggle guideline references"):
        _event(
            guideline_intent="ambiguous",
            evidence_query_ref=_ref("evidence_query", "cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
            corpus_ref=_ref("corpus", "uspstf-2026q3"),
        )


def test_optional_guideline_outage_preserves_patient_route_with_limitation() -> None:
    event = _event(
        guideline_intent="explicit_permitted",
        evidence_query_ref=_ref("evidence_query", "cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
        corpus_ref=_ref("corpus", "uspstf-2026q3"),
        readiness={"core_ready": True, "document_ready": True, "guideline_ready": False},
    )

    decision = DeterministicSupervisor().route(event, now="2026-09-22T00:00:00Z")

    assert decision.status == "dispatched"
    assert decision.routes == ("patient_turn_graph",)
    assert decision.handoffs == []
    assert decision.limitation_codes == ["guideline_unavailable"]


def test_reprocess_limit_and_core_readiness_fail_closed() -> None:
    reprocess = _event(
        event_kind="reprocess_requested",
        conversation_id=None,
        turn_id=None,
        source_ref=_ref("source_document", "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
        source_version_budget=False,
    )
    supervisor = DeterministicSupervisor()

    limited = supervisor.route(reprocess, now="2026-09-22T00:00:00Z")
    unavailable = supervisor.route(
        _event(readiness={"core_ready": False, "document_ready": True, "guideline_ready": True}),
        now="2026-09-22T00:00:00Z",
    )

    assert limited.status == "refused"
    assert limited.limitation_codes == ["extraction_version_limit"]
    assert unavailable.status == "unavailable"
    assert unavailable.limitation_codes == ["core_unavailable"]


def test_handoff_serialization_is_reference_only() -> None:
    event = _event(
        event_kind="document_uploaded",
        conversation_id=None,
        turn_id=None,
        source_ref=_ref("source_document", "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
    )

    decision = DeterministicSupervisor(
        handoff_id=lambda: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    ).route(event, now="2026-09-22T00:00:00Z")
    serialized = json.dumps(decision.model_dump(mode="json"))

    assert "synthetic clinical content" not in serialized
    assert set(decision.handoffs[0].model_dump()) == {
        "handoff_id",
        "correlation_id",
        "conversation_id",
        "turn_id",
        "event_kind",
        "worker",
        "reason_code",
        "attempt",
        "deadline_at",
        "input_refs",
        "contract_versions",
    }
