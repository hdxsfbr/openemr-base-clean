"""Pure Slice 4A supervisor-policy, contract, transition, and privacy tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.contracts import (
    AnswerReadinessResult,
    DispatchRecord,
    HandoffCompletion,
    RouteAction,
    RouteReason,
    SupervisorRequestState,
)
from app.contracts.supervisor import (
    BranchState,
    ChatIntentSignal,
    ClaimVerificationReference,
    SupervisorLimitationCode,
    apply_handoff_completion,
    answer_readiness,
    complete_handoff,
    decide_route,
)


FIXTURE = Path(__file__).parent / "fixtures" / "week2" / "valid_supervisor_contracts.json"
INVALID_FIXTURE = Path(__file__).parent / "fixtures" / "week2" / "invalid_supervisor_contracts.json"
CID = "123e4567-e89b-12d3-a456-426614174000"


def payload() -> dict:
    return json.loads(FIXTURE.read_text())


def invalid_payload() -> dict:
    return json.loads(INVALID_FIXTURE.read_text())


def chat(*, signals: list[str] | None = None, control: bool = False, topics: list[str] | None = None) -> SupervisorRequestState:
    data = payload()["request"]
    data["event"]["intent_signals"] = signals or []
    data["event"]["include_guideline_evidence"] = control
    data["event"]["supported_finding_topics"] = topics or []
    return SupervisorRequestState.model_validate(data)


@pytest.mark.parametrize(
    ("signals", "control", "topics", "action", "reason"),
    [
        ([], False, [], RouteAction.patient_record_only, RouteReason.patient_record_only),
        ([], True, [], RouteAction.dispatch_evidence, RouteReason.explicit_control),
        (["explicit_guideline_terms"], False, [], RouteAction.dispatch_evidence, RouteReason.explicit_guideline_terms),
        (["evidence_for_supported_finding"], False, ["aaa"], RouteAction.dispatch_evidence, RouteReason.evidence_for_supported_finding),
        (["ambiguous_evidence"], False, [], RouteAction.clarify, RouteReason.ambiguous),
        (["treatment_intent"], True, [], RouteAction.refuse, RouteReason.disallowed_advice),
        (["diagnosis_intent"], False, [], RouteAction.refuse, RouteReason.disallowed_advice),
        (["dosing_intent"], False, [], RouteAction.refuse, RouteReason.disallowed_advice),
        (["patient_applicability_intent"], False, [], RouteAction.refuse, RouteReason.disallowed_advice),
    ],
)
def test_chat_decision_table_is_exhaustive_and_advice_precedes_retrieval(signals, control, topics, action, reason) -> None:
    decision = decide_route(chat(signals=signals, control=control, topics=topics))
    assert (decision.action, decision.reason) == (action, reason)
    assert decision.worker is None if action in {RouteAction.patient_record_only, RouteAction.clarify, RouteAction.refuse} else decision.worker.value == "evidence_retriever"


@pytest.mark.parametrize("event_kind", ["document_uploaded", "reprocess_requested"])
def test_authorized_document_events_can_only_dispatch_intake(event_kind: str) -> None:
    request = payload()["request"]
    request["event"] = {
        "event_kind": event_kind,
        "event_id": "1111111111111111",
        "authorization_ref": "2222222222222222",
        "source_id": "document:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "source_version": "c" * 64,
        "document_type": "lab_pdf",
        "authorized": True,
    }
    decision = decide_route(SupervisorRequestState.model_validate(request))
    assert decision.action is RouteAction.dispatch_intake
    assert decision.reason is RouteReason.document_event
    assert decision.worker and decision.worker.value == "intake_extractor"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data.pop("contract_version"),
        lambda data: data.pop("correlation_id"),
        lambda data: data.pop("deadline_unix_ms"),
        lambda data: data.__setitem__("patient_id", "forbidden"),
        lambda data: data["event"].__setitem__("question", "forbidden"),
        lambda data: data["event"].__setitem__("ocr", "forbidden"),
        lambda data: data["event"].__setitem__("authorized", False),
    ],
)
def test_request_rejects_missing_security_fields_and_protected_content(mutate) -> None:
    data = payload()["request"]
    mutate(data)
    with pytest.raises(ValidationError):
        SupervisorRequestState.model_validate(data)


def test_invalid_cross_runtime_fixture_fails_closed_without_protected_content() -> None:
    data = invalid_payload()
    with pytest.raises(ValidationError):
        SupervisorRequestState.model_validate(data["missing_deadline"])
    with pytest.raises(ValidationError):
        SupervisorRequestState.model_validate(data["unknown_event"])
    with pytest.raises(ValidationError):
        DispatchRecord.model_validate(data["wrong_worker_dispatch"])


def test_exported_supervisor_contract_schemas_advertise_their_own_version() -> None:
    schema = json.loads((Path(__file__).parents[2] / "contracts" / "schema" / "supervisor_request_state.schema.json").read_text())
    assert schema["x-contract-version"] == "4.0.0"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data.pop("contract_version"),
        lambda data: data.pop("deadline_unix_ms"),
        lambda data: data.__setitem__("worker", "other_worker"),
        lambda data: data.__setitem__("reason", "ambiguous"),
        lambda data: data["input_ref"].__setitem__("question", "forbidden"),
        lambda data: data["input_ref"].__setitem__("source_text", "forbidden"),
        lambda data: data.__setitem__("attempt", 2),
    ],
)
def test_dispatch_rejects_wrong_worker_raw_content_or_unbounded_attempt(mutate) -> None:
    data = payload()["dispatch"]
    mutate(data)
    with pytest.raises(ValidationError):
        DispatchRecord.model_validate(data)


def test_completion_rejects_unknown_fields_and_worker_output_mismatch() -> None:
    data = payload()["completion"]
    data["answer"] = "forbidden"
    with pytest.raises(ValidationError):
        HandoffCompletion.model_validate(data)
    data = payload()["completion"]
    data["output_ref"]["kind"] = "extraction_result"
    data["output_ref"]["contract_version"] = "2.0.0"
    with pytest.raises(ValidationError):
        HandoffCompletion.model_validate(data)


def test_completion_requires_matching_current_dispatch_and_one_terminal_transition() -> None:
    data = payload()
    dispatch = DispatchRecord.model_validate(data["dispatch"])
    completion = HandoffCompletion.model_validate(data["completion"])
    branch = complete_handoff(dispatch, completion, now_unix_ms=1_700_000_000_000)
    assert branch.state is BranchState.terminal
    assert branch.terminal is completion
    pending = branch.model_copy(update={"state": BranchState.pending, "terminal": None})
    assert apply_handoff_completion(pending, completion, now_unix_ms=1_700_000_000_000).state is BranchState.terminal
    with pytest.raises(ValueError, match=SupervisorLimitationCode.duplicate_terminal.value):
        apply_handoff_completion(branch, completion, now_unix_ms=1_700_000_000_000)

    for updates, expected in (
        ({"correlation_id": "different-correlation"}, SupervisorLimitationCode.correlation_mismatch),
        ({"handoff_id": "b" * 32}, SupervisorLimitationCode.wrong_worker),
        ({"worker": "intake_extractor"}, SupervisorLimitationCode.wrong_worker),
        ({"contract_version": "4.0.1"}, SupervisorLimitationCode.contract_version_mismatch),
    ):
        # The production boundary validates first. model_copy here deliberately
        # simulates a corrupted in-memory record so the transition guard itself
        # proves it also fails closed.
        altered = completion.model_copy(update=updates)
        with pytest.raises(ValueError, match=expected.value):
            complete_handoff(dispatch, altered, now_unix_ms=1_700_000_000_000)
    with pytest.raises(ValueError, match=SupervisorLimitationCode.deadline_exceeded.value):
        complete_handoff(dispatch, completion, now_unix_ms=1_800_000_000_001)


def test_readiness_requires_every_branch_terminal_and_only_observes_verifier_output() -> None:
    data = payload()
    dispatch = DispatchRecord.model_validate(data["dispatch"])
    completed = HandoffCompletion.model_validate(data["completion"])
    terminal = complete_handoff(dispatch, completed, now_unix_ms=1_700_000_000_000)
    claim = ClaimVerificationReference.model_validate(data["claim"])
    ready = answer_readiness(CID, [terminal], [claim])
    assert ready.ready and ready.requested_branches_terminal and ready.displayed_claims_verified
    assert isinstance(ready, AnswerReadinessResult)
    pending = terminal.model_copy(update={"state": BranchState.pending, "terminal": None})
    not_ready = answer_readiness(CID, [pending], [claim])
    assert not not_ready.ready and not_ready.limitation
    with pytest.raises(ValidationError):
        ClaimVerificationReference.model_validate({**data["claim"], "deterministic_verification": "withheld"})


def test_serialized_contracts_and_safe_transition_errors_exclude_privacy_canaries() -> None:
    canaries = ("CedarPrivacy", "document bytes", "OCR value", "guide excerpt", "prompt payload", "answer payload")
    data = payload()
    serialized = json.dumps(data, sort_keys=True)
    assert not any(value in serialized for value in canaries)
    dispatch = DispatchRecord.model_validate(data["dispatch"])
    completion = HandoffCompletion.model_validate({**data["completion"], "correlation_id": "different-correlation"})
    with pytest.raises(ValueError) as error:
        complete_handoff(dispatch, completion, now_unix_ms=1_700_000_000_000)
    assert not any(value in str(error.value) for value in canaries)
