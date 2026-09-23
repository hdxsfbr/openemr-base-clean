"""Slice 4B runtime tests: one bounded, fresh evidence handoff at a time."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from app.contracts import (
    EvidenceWorkerResult,
    EvidenceWorkerStatus,
    GuidelineExcerpt,
    GuidelineRetrievalLimitation,
    GuidelineRetrievalLimitationCode,
    GuidelineTopic,
    SupervisorRequestState,
)
from app.contracts.supervisor import BranchState, SupervisorLimitationCode, decide_route
from app.supervisor_dispatch import SupervisorDispatcher, chat_intent_projection


ROOT = Path(__file__).parents[1] / "guideline_corpus"
CID = "123e4567-e89b-12d3-a456-426614174000"


def decision():
    return decide_route(SupervisorRequestState.model_validate({
        "contract_version": "4.0.0",
        "correlation_id": CID,
        "deadline_unix_ms": 9_999_999_999,
        "event": {
            "event_kind": "chat_turn",
            "event_id": "a" * 16,
            "authorization_ref": "b" * 16,
            "turn_ref": "c" * 16,
            "include_guideline_evidence": True,
        },
    }))


def result(*, status: EvidenceWorkerStatus = EvidenceWorkerStatus.completed, correlation_id: str = CID, handoff_id: str = "a" * 32) -> EvidenceWorkerResult:
    row = json.loads((ROOT / "artifacts" / "chunks.jsonl").read_text().splitlines()[0])
    excerpt = GuidelineExcerpt.model_validate({
        **{key: value for key, value in row.items() if key != "review_date"},
        "source_id": f"guideline:{row['corpus_version']}:{row['document_id']}:{row['chunk_id']}",
    })
    payload: dict[str, object] = {
        "correlation_id": correlation_id,
        "handoff_id": handoff_id,
        "status": status,
        "artifact_manifest_sha256": "b" * 64,
        "embedding_model_revision": "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a",
        "reranker_model_revision": "233902d25b440f23af6f7d6e94d2946bac0bee0a",
        "candidate_count": 1 if status is EvidenceWorkerStatus.completed else 0,
        "hit_count": 1 if status is EvidenceWorkerStatus.completed else 0,
        "timings": {"sparse_ms": 1, "dense_ms": 1, "fusion_ms": 1, "rerank_ms": 1, "total_ms": 4},
        "excerpts": [excerpt] if status is EvidenceWorkerStatus.completed else [],
    }
    if status is not EvidenceWorkerStatus.completed:
        code = GuidelineRetrievalLimitationCode.canceled if status is EvidenceWorkerStatus.canceled else GuidelineRetrievalLimitationCode.no_evidence
        payload["limitation"] = GuidelineRetrievalLimitation(code=code, detail="No approved guideline evidence was found.")
    return EvidenceWorkerResult.model_validate(payload)


class Worker:
    def __init__(self, outcome: EvidenceWorkerResult | object) -> None:
        self.outcome = outcome
        self.queries: list[object] = []
        self.cancellations: list[tuple[str, str]] = []

    def invoke(self, query: object) -> object:
        self.queries.append(query)
        if isinstance(self.outcome, EvidenceWorkerResult):
            return self.outcome.model_copy(update={"handoff_id": query.handoff_id})
        return self.outcome

    def cancel(self, correlation_id: str, handoff_id: str) -> None:
        self.cancellations.append((correlation_id, handoff_id))


def run(worker: Worker, *, auth=lambda: True, fresh=lambda: True, now=lambda: 1_000, deadline: int = 5_000):
    return asyncio.run(SupervisorDispatcher(worker, now_ms=now).dispatch_evidence(
        decision(), conversation_id="d" * 32, turn_id="e" * 16, topics=[GuidelineTopic.aaa],
        deadline_unix_ms=deadline, reauthorize=auth, corpus_is_current=fresh,
    ))


def test_dispatch_rechecks_authorization_and_corpus_before_and_after_one_worker_call() -> None:
    worker = Worker(result())
    outcome = run(worker)

    assert outcome.result_status == "completed"
    assert outcome.branch.state is BranchState.terminal
    assert outcome.branch.terminal and outcome.branch.terminal.status.value == "completed"
    assert len(worker.queries) == 1
    query = worker.queries[0]
    assert query.concepts == [GuidelineTopic.aaa] and query.deadline_ms == 2000
    assert "question" not in query.model_dump() and "patient_id" not in query.model_dump()
    assert outcome.branch.dispatch and outcome.branch.dispatch.input_ref.request_ref != "d" * 32


def test_denied_or_stale_preflight_never_mints_or_runs_a_handoff() -> None:
    for check, expected in (
        (dict(auth=lambda: False), SupervisorLimitationCode.unauthorized_event),
        (dict(fresh=lambda: False), SupervisorLimitationCode.worker_unavailable),
    ):
        worker = Worker(result())
        outcome = run(worker, **check)
        assert outcome.result_status == expected.value
        assert outcome.branch.state is BranchState.not_requested
        assert worker.queries == []


def test_route_and_topic_errors_fail_before_worker_invocation() -> None:
    worker = Worker(result())
    dispatcher = SupervisorDispatcher(worker, now_ms=lambda: 1_000)
    refused = decide_route(SupervisorRequestState.model_validate({
        "contract_version": "4.0.0", "correlation_id": CID, "deadline_unix_ms": 9_999_999_999,
        "event": {"event_kind": "chat_turn", "event_id": "a" * 16, "authorization_ref": "b" * 16, "turn_ref": "c" * 16, "intent_signals": ["treatment_intent"]},
    }))
    outcome = asyncio.run(dispatcher.dispatch_evidence(
        refused, conversation_id="d" * 32, turn_id="e" * 16, topics=[], deadline_unix_ms=5_000,
        reauthorize=lambda: True, corpus_is_current=lambda: True,
    ))
    assert outcome.result_status == SupervisorLimitationCode.malformed_transition.value
    assert outcome.branch.state is BranchState.not_requested and worker.queries == []


def test_worker_result_must_match_the_handoff_and_stay_a_valid_terminal_envelope() -> None:
    for outcome_value, expected in (
        (result(correlation_id="different-correlation"), SupervisorLimitationCode.correlation_mismatch),
        (object(), SupervisorLimitationCode.malformed_transition),
    ):
        worker = Worker(outcome_value)
        outcome = run(worker)
        assert outcome.result_status == "limited"
        assert outcome.branch.terminal and outcome.branch.terminal.limitation.code is expected


def test_no_evidence_and_cancellation_are_distinct_typed_terminal_outcomes() -> None:
    no_evidence = run(Worker(result(status=EvidenceWorkerStatus.limited)))
    canceled = run(Worker(result(status=EvidenceWorkerStatus.canceled)))

    assert no_evidence.branch.terminal and no_evidence.branch.terminal.limitation.code is SupervisorLimitationCode.no_evidence
    assert canceled.branch.terminal and canceled.branch.terminal.status.value == "canceled"
    assert canceled.branch.terminal.limitation.code is SupervisorLimitationCode.worker_canceled


def test_authorization_loss_after_worker_completion_withholds_result_and_cancels_handoff() -> None:
    values = iter([True, False])
    worker = Worker(result())
    outcome = run(worker, auth=lambda: next(values))

    assert outcome.branch.terminal and outcome.branch.terminal.limitation.code is SupervisorLimitationCode.unauthorized_event
    assert len(worker.cancellations) == 1


def test_timeout_cancels_late_work_and_never_converts_it_to_success() -> None:
    class SlowWorker(Worker):
        def invoke(self, query: object) -> object:
            self.queries.append(query)
            time.sleep(0.1)
            return result(handoff_id=query.handoff_id)

    worker = SlowWorker(result())
    now = lambda: int(time.monotonic() * 1000)
    outcome = run(worker, now=now, deadline=now() + 20)

    assert outcome.branch.terminal and outcome.branch.terminal.limitation.code is SupervisorLimitationCode.deadline_exceeded
    assert len(worker.cancellations) == 1


def test_question_projection_is_finite_and_never_retains_the_inspected_text(caplog) -> None:
    question = "CedarPrivacy: should I recommend a treatment dose?"
    signals, topics = chat_intent_projection(question, include_guideline_evidence=True, topics=[GuidelineTopic.breast])

    assert signals == ["treatment_intent"] and topics == ["breast"]
    assert question not in caplog.text
