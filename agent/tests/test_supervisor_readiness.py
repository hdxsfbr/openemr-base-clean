"""Final-display freshness tests for Slice 4C.

These cover the join after model work rather than worker implementation.  The
test gateway returns a valid chart first, then removes a cited record during
the mandatory final resolution pass.
"""

from __future__ import annotations

import asyncio

from app.contracts import Claim
from app.contracts.supervisor import BranchState, SupervisorLimitationCode, answer_readiness
from app.graph.nodes import Runtime, make_nodes
from app.graph.state import PER_TURN_DEFAULTS
from app.state_store import drop_token, put_token
from conftest import FakeGateway, FakeModel


CID = "readiness.0001"
TURN_ID = "abcdefabcdefabcd"
SOURCE_ID = "openemr:procedure_result:9000003:a2bfa267-ec71-4353-9c11-3657a2f525f8"


class MutatingGateway(FakeGateway):
    """The source is valid for narration but gone at the final display check."""

    async def call(self, tool, params, token, correlation_id):
        result = await super().call(tool, params, token, correlation_id)
        if tool == "lab_results" and len(self.calls) > 7:
            return result.model_copy(update={"records": []})
        return result


def lab_claim() -> dict[str, object]:
    return {
        "id": "c1",
        "type": "lab_result",
        "text": "Hemoglobin A1c was 6.8 % on 2026-08-31.",
        "facts": {
            "analyte": "Hemoglobin A1c",
            "value_text": "6.8",
            "unit": "%",
            "date": "2026-08-31",
            "flag": "abnormal",
        },
        "source_ids": [SOURCE_ID],
    }


def test_final_patient_resolution_reauthorizes_and_withholds_a_source_changed_after_narration() -> None:
    gateway = MutatingGateway()
    nodes = make_nodes(Runtime(gateway=gateway, model=FakeModel(claims=[lab_claim()])))
    state = dict(PER_TURN_DEFAULTS)
    state.update({
        "conversation_id": "c" * 32,
        "turn_id": TURN_ID,
        "correlation_id": CID,
        "question": "What changed since the last visit?",
    })
    put_token(TURN_ID, "test-delegation")
    try:
        async def invoke():
            for name in ("authorize", "classify", "retrieve", "narrate", "verify", "revalidate", "render"):
                state.update(await nodes[name](state))
            return state
        final = asyncio.run(invoke())
    finally:
        drop_token(TURN_ID)

    assert len(gateway.calls) == 14, "the same bounded calls are replayed before display"
    assert final["accepted"] == []
    assert any(item["rule"] == "source_exists" for item in final["rejected"])
    assert final["status"] == "partial"
    assert final["readiness"]["ready"] is True
    assert final["readiness"]["displayed_claims_verified"] is True


def test_readiness_rejects_pending_duplicate_and_corruption_even_if_a_caller_constructs_it_in_memory() -> None:
    from app.contracts import DispatchRecord, HandoffCompletion
    from app.contracts.supervisor import complete_handoff
    from pathlib import Path
    import json

    fixture = json.loads((Path(__file__).parent / "fixtures" / "week2" / "valid_supervisor_contracts.json").read_text())
    dispatch = DispatchRecord.model_validate(fixture["dispatch"])
    completion = HandoffCompletion.model_validate(fixture["completion"])
    terminal = complete_handoff(dispatch, completion, now_unix_ms=1_700_000_000_000)
    pending = terminal.model_copy(update={"state": BranchState.pending, "terminal": None})
    duplicate = answer_readiness(CID, [terminal, terminal], [])
    pending_result = answer_readiness(CID, [pending], [])
    mismatch = terminal.model_copy(update={"terminal": completion.model_copy(update={"correlation_id": "other-correlation"})})
    mismatch_result = answer_readiness(CID, [mismatch], [])

    for result in (duplicate, pending_result, mismatch_result):
        assert not result.ready
        assert result.limitation and result.limitation.code is SupervisorLimitationCode.malformed_transition


def test_advice_or_applicability_intent_is_refused_before_a_patient_or_guideline_retrieval() -> None:
    gateway = FakeGateway()
    nodes = make_nodes(Runtime(gateway=gateway, model=FakeModel()))
    state = dict(PER_TURN_DEFAULTS)
    state.update({
        "conversation_id": "c" * 32,
        "turn_id": TURN_ID,
        "correlation_id": CID,
        "question": "Should this guideline determine patient applicability?",
    })

    authorization = asyncio.run(nodes["authorize"](state))
    state.update(authorization)
    rendered = asyncio.run(nodes["render"](state))

    assert authorization["route"] == "render"
    assert rendered["status"] == "refused"
    assert gateway.calls == []
    assert rendered["accepted"] == []
