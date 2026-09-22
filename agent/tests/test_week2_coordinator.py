"""Parent integration for deterministic routing, parallel reads, and verification."""

from __future__ import annotations

import asyncio

from app.contracts.week2 import TurnBinding
from app.supervisor import DeterministicSupervisor, SupervisorEvent
from app.week2_coordinator import BranchEvidence, Week2Coordinator


def _ref(kind: str, identity: str, version: str = "1") -> dict[str, str]:
    return {"kind": kind, "id": identity, "version": version, "integrity_sha256": "a" * 64}


def _event(**overrides: object) -> SupervisorEvent:
    payload: dict[str, object] = {
        "event_kind": "chat_turn",
        "correlation_id": "conversation.turn-01",
        "conversation_id": "conversation-01",
        "turn_id": "turn-01",
        "authorized": True,
        "canceled": False,
        "guideline_intent": "none",
        "source_version_budget": True,
        "readiness": {"core_ready": True, "document_ready": True, "guideline_ready": True},
        "contract_versions": {"handoff": "1.0.0", "evidence_query": "1.0.0"},
    }
    payload.update(overrides)
    return SupervisorEvent.model_validate(payload)


def _binding() -> TurnBinding:
    return TurnBinding.model_validate({
        "site_id": "demo-site",
        "user_id": "demo-user",
        "patient_id": "demo-patient",
        "conversation_id": "conversation-01",
        "turn_id": "turn-01",
        "correlation_id": "conversation.turn-01",
        "authorized_at": "2026-09-22T00:00:00Z",
    })


def test_coordinator_executes_only_the_supervisor_selected_patient_route() -> None:
    guideline_called = False

    async def patient() -> BranchEvidence:
        return BranchEvidence()

    async def guideline() -> BranchEvidence:
        nonlocal guideline_called
        guideline_called = True
        return BranchEvidence()

    result = asyncio.run(Week2Coordinator().coordinate_chat(
        _event(),
        now="2026-09-22T00:00:01Z",
        binding=_binding(),
        verified_at="2026-09-22T00:00:02Z",
        patient=patient,
        guideline=guideline,
    ))

    assert result.status == "complete"
    assert result.lane_status == {"patient_record": "completed"}
    assert result.verification.outcome == "passed"
    assert guideline_called is False


def test_mixed_route_joins_before_verification_and_degrades_one_lane_locally() -> None:
    both_started = asyncio.Event()
    started: set[str] = set()

    async def patient() -> BranchEvidence:
        started.add("patient")
        if len(started) == 2:
            both_started.set()
        await both_started.wait()
        return BranchEvidence()

    async def guideline() -> BranchEvidence:
        started.add("guideline")
        if len(started) == 2:
            both_started.set()
        await both_started.wait()
        raise RuntimeError("synthetic dependency detail")

    event = _event(
        guideline_intent="explicit_permitted",
        evidence_query_ref=_ref("evidence_query", "cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
        corpus_ref=_ref("corpus", "uspstf-2026q3"),
    )
    result = asyncio.run(Week2Coordinator().coordinate_chat(
        event,
        now="2026-09-22T00:00:01Z",
        binding=_binding(),
        verified_at="2026-09-22T00:00:02Z",
        active_corpus_version="uspstf-2026q3",
        patient=patient,
        guideline=guideline,
    ))

    assert started == {"patient", "guideline"}
    assert result.status == "partial"
    assert result.lane_status == {
        "patient_record": "completed",
        "guideline_evidence": "failed",
    }
    assert result.limitation_codes == ["guideline_retrieval_unavailable"]
    assert "synthetic dependency detail" not in result.model_dump_json()


def test_denied_route_runs_no_branch_and_returns_no_unverified_output() -> None:
    called = False

    async def patient() -> BranchEvidence:
        nonlocal called
        called = True
        return BranchEvidence(candidates=({"text": "must not escape"},))

    result = asyncio.run(Week2Coordinator().coordinate_chat(
        _event(authorized=False),
        now="2026-09-22T00:00:01Z",
        binding=_binding(),
        verified_at="2026-09-22T00:00:02Z",
        patient=patient,
    ))

    assert result.status == "refused"
    assert result.lane_status == {}
    assert result.verification.patient_record.accepted == []
    assert result.verification.guideline_evidence.accepted == []
    assert called is False
