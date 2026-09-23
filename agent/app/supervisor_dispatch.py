"""Content-free runtime bridge for the deterministic supervisor contracts.

This is deliberately narrower than the chat graph.  It can turn an already
authorized evidence route into one bounded ``EvidenceQuery``, and it retains
only the opaque terminal handoff reference.  It neither renders the returned
excerpts nor decides that they support a claim.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from .contracts.guidelines import (
    ACTIVE_CORPUS_VERSION,
    EvidenceIntent,
    EvidenceQuery,
    EvidenceWorkerResult,
    EvidenceWorkerStatus,
    GuidelineRetrievalLimitationCode,
    GuidelineTopic,
)
from .contracts.supervisor import (BranchState, DispatchRecord, EvidenceInputReference,
    HandoffCompletion, HandoffOutputReference, HandoffStatus, HandoffTimings,
    RouteAction, RouteDecision, SupervisorBranchState, SupervisorLimitation,
    SupervisorLimitationCode, SupervisorWorker, complete_handoff)

log = logging.getLogger("copilot.supervisor")

class EvidenceWorkerPort(Protocol):
    def invoke(self, payload: object) -> Any: ...

    def cancel(self, correlation_id: str, handoff_id: str) -> None: ...

@dataclass(frozen=True)
class WorkerDispatch:
    """Checkpoint-safe terminal state; never retains worker evidence."""
    branch: SupervisorBranchState
    result_status: str

def opaque_ref(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()

def chat_intent_projection(question: str, *, include_guideline_evidence: bool, topics: list[GuidelineTopic]) -> tuple[list[str], list[str]]:
    """Return finite signals only; callers must discard the inspected question.

    This helper is intentionally not a routing authority.  Its output is
    subsequently validated by the sealed supervisor contract, and no question
    text is put in an event, handoff, checkpoint, or log.
    """
    text, signals = question.lower(), []
    if any(term in text for term in ("diagnos", "treat", "dose", "dosing", "should i", "recommend", "applicab")):
        signals.append("treatment_intent")
    elif not include_guideline_evidence and any(term in text for term in ("guideline", "clinical standard", "uspstf", "publisher evidence", "source guideline")):
        signals.append("explicit_guideline_terms")
    elif not include_guideline_evidence and "evidence" in text:
        signals.append("ambiguous_evidence")
    return signals, [topic.value for topic in topics[:3]]

class SupervisorDispatcher:
    """The sole Slice 4B component permitted to call evidence retrieval.

    The caller must perform both checks at this boundary.  They are callbacks
    rather than cached flags so a ticket/session or approved corpus cannot be
    silently reused after it has gone stale.  Each callback returns only a
    boolean: the dispatcher has no reason to receive the user, patient, source
    text, or corpus contents.
    """
    def __init__(self, evidence_worker: EvidenceWorkerPort | None, *, now_ms: Any = None) -> None:
        self.evidence_worker, self.now_ms = evidence_worker, now_ms or (lambda: int(time.time() * 1000))

    async def dispatch_evidence(
        self,
        decision: RouteDecision,
        *,
        conversation_id: str,
        turn_id: str,
        topics: list[GuidelineTopic],
        deadline_unix_ms: int,
        reauthorize: Callable[[], bool],
        corpus_is_current: Callable[[], bool],
    ) -> WorkerDispatch:
        """Dispatch exactly one fresh, authorized evidence handoff.

        A failed preflight creates no handoff at all.  Once a handoff exists it
        always reaches one typed terminal state, including timeout and
        cancellation races.  No retry is attempted: ADR-0010 forbids an
        in-turn retrieval retry.
        """
        started = self.now_ms()
        if not self._is_evidence_route(decision) or not conversation_id or not turn_id or not self._topics_are_valid(topics):
            return self._not_dispatched(SupervisorLimitationCode.malformed_transition)
        if started >= deadline_unix_ms:
            return self._not_dispatched(SupervisorLimitationCode.deadline_exceeded)
        if not self._check(reauthorize):
            return self._not_dispatched(SupervisorLimitationCode.unauthorized_event)
        if not self._check(corpus_is_current):
            return self._not_dispatched(SupervisorLimitationCode.worker_unavailable)
        if self.evidence_worker is None:
            return self._not_dispatched(SupervisorLimitationCode.worker_unavailable)

        handoff_id = secrets.token_hex(16)
        dispatch = DispatchRecord(contract_version="4.0.0", correlation_id=decision.correlation_id, handoff_id=handoff_id,
            event_kind=decision.event_kind, worker=SupervisorWorker.evidence_retriever, reason=decision.reason,
            deadline_unix_ms=deadline_unix_ms, input_ref=EvidenceInputReference(request_ref=opaque_ref(decision.correlation_id, conversation_id, turn_id, "evidence"), contract_version="3.0.0"))
        remaining = deadline_unix_ms - started
        if remaining <= 0:
            return self._limited(decision, deadline_unix_ms, SupervisorLimitationCode.deadline_exceeded, dispatch, started)
        query = EvidenceQuery(intent=EvidenceIntent.guideline_evidence, concepts=topics[:3], topic_filter=topics[0] if len(topics) == 1 else None,
            requested_top_k=5, correlation_id=decision.correlation_id, handoff_id=handoff_id, deadline_ms=min(2000, remaining))
        try:
            result = await asyncio.wait_for(asyncio.to_thread(self.evidence_worker.invoke, query), timeout=remaining / 1000)
        except asyncio.TimeoutError:
            self._cancel(decision.correlation_id, handoff_id)
            return self._limited(decision, deadline_unix_ms, SupervisorLimitationCode.deadline_exceeded, dispatch, started)
        except Exception:
            return self._limited(decision, deadline_unix_ms, SupervisorLimitationCode.worker_unavailable, dispatch, started)
        completed_at = self.now_ms()
        elapsed = max(0, completed_at - started)
        try:
            terminal = EvidenceWorkerResult.model_validate(result)
        except Exception:
            return self._limited(decision, deadline_unix_ms, SupervisorLimitationCode.malformed_transition, dispatch, started)
        if terminal.correlation_id != decision.correlation_id or terminal.handoff_id != handoff_id:
            return self._limited(decision, deadline_unix_ms, SupervisorLimitationCode.correlation_mismatch, dispatch, started)
        if terminal.contract_version != "3.0.0" or terminal.corpus_version != ACTIVE_CORPUS_VERSION:
            return self._limited(decision, deadline_unix_ms, SupervisorLimitationCode.malformed_transition, dispatch, started)
        if completed_at > deadline_unix_ms:
            self._cancel(decision.correlation_id, handoff_id)
            return self._limited(decision, deadline_unix_ms, SupervisorLimitationCode.deadline_exceeded, dispatch, started)
        # The corpus may change while the worker is running.  The resolver will
        # re-resolve again before rendering, but this boundary rejects the
        # stale handoff immediately as well.
        if not self._check(reauthorize):
            self._cancel(decision.correlation_id, handoff_id)
            return self._limited(decision, deadline_unix_ms, SupervisorLimitationCode.unauthorized_event, dispatch, started)
        if not self._check(corpus_is_current):
            self._cancel(decision.correlation_id, handoff_id)
            return self._limited(decision, deadline_unix_ms, SupervisorLimitationCode.worker_unavailable, dispatch, started)
        if terminal.status is EvidenceWorkerStatus.completed:
            completion = HandoffCompletion(contract_version="4.0.0", correlation_id=decision.correlation_id, handoff_id=handoff_id, worker=SupervisorWorker.evidence_retriever, status=HandoffStatus.completed,
                output_ref=HandoffOutputReference(kind="evidence_result", result_ref=opaque_ref(handoff_id, "result"), result_version=opaque_ref(terminal.artifact_manifest_sha256, terminal.embedding_model_revision), contract_version="3.0.0"), timings=HandoffTimings(queued_ms=0, worker_ms=elapsed, total_ms=elapsed))
        else:
            canceled = terminal.status is EvidenceWorkerStatus.canceled
            completion = HandoffCompletion(contract_version="4.0.0", correlation_id=decision.correlation_id, handoff_id=handoff_id, worker=SupervisorWorker.evidence_retriever, status=HandoffStatus.canceled if canceled else HandoffStatus.limited,
                limitation=SupervisorLimitation(code=self._limitation_of(terminal)), timings=HandoffTimings(queued_ms=0, worker_ms=elapsed, total_ms=elapsed))
        branch = complete_handoff(dispatch, completion, now_unix_ms=completed_at)
        self._log(branch, terminal.status.value)
        return WorkerDispatch(branch, terminal.status.value)

    @staticmethod
    def _is_evidence_route(decision: RouteDecision) -> bool:
        return (
            decision.action is RouteAction.dispatch_evidence
            and decision.worker is SupervisorWorker.evidence_retriever
            and decision.event_kind.value == "chat_turn"
        )

    @staticmethod
    def _topics_are_valid(topics: list[GuidelineTopic]) -> bool:
        return 1 <= len(topics) <= 3 and len(set(topics)) == len(topics)

    @staticmethod
    def _check(check: Callable[[], bool]) -> bool:
        try:
            return check() is True
        except Exception:
            return False

    def _cancel(self, correlation_id: str, handoff_id: str) -> None:
        cancel = getattr(self.evidence_worker, "cancel", None)
        if callable(cancel):
            try:
                cancel(correlation_id, handoff_id)
            except Exception:
                # An unavailable cancellation hook must not alter the typed
                # deadline/authorization outcome already selected above.
                pass

    @staticmethod
    def _limitation_of(result: EvidenceWorkerResult) -> SupervisorLimitationCode:
        if result.status is EvidenceWorkerStatus.canceled:
            return SupervisorLimitationCode.worker_canceled
        if result.limitation and result.limitation.code is GuidelineRetrievalLimitationCode.no_evidence:
            return SupervisorLimitationCode.no_evidence
        if result.limitation and result.limitation.code is GuidelineRetrievalLimitationCode.deadline_exceeded:
            return SupervisorLimitationCode.deadline_exceeded
        return SupervisorLimitationCode.worker_unavailable

    @staticmethod
    def _not_dispatched(code: SupervisorLimitationCode) -> WorkerDispatch:
        """Represent a denied preflight without inventing a worker handoff."""
        branch = SupervisorBranchState(worker=SupervisorWorker.evidence_retriever, state=BranchState.not_requested)
        return WorkerDispatch(branch, code.value)

    def _limited(self, decision: RouteDecision, deadline: int, code: SupervisorLimitationCode, dispatch: DispatchRecord, started: int) -> WorkerDispatch:
        elapsed = max(0, self.now_ms() - started) if started is not None else 0
        completion = HandoffCompletion(contract_version="4.0.0", correlation_id=decision.correlation_id, handoff_id=dispatch.handoff_id, worker=SupervisorWorker.evidence_retriever, status=HandoffStatus.canceled if code is SupervisorLimitationCode.worker_canceled else HandoffStatus.limited, limitation=SupervisorLimitation(code=code), timings=HandoffTimings(queued_ms=0, worker_ms=elapsed, total_ms=elapsed))
        branch = SupervisorBranchState(worker=SupervisorWorker.evidence_retriever, state=BranchState.terminal, dispatch=dispatch, terminal=completion)
        self._log(branch, "limited")
        return WorkerDispatch(branch, "limited")

    @staticmethod
    def _log(branch: SupervisorBranchState, status: str) -> None:
        dispatch, terminal = branch.dispatch, branch.terminal
        assert dispatch and terminal
        log.info("worker handoff terminal", extra={"component": "supervisor", "correlation_id": dispatch.correlation_id, "handoff_id": dispatch.handoff_id, "worker": dispatch.worker.value, "reason": dispatch.reason.value, "status": status, "limitation": terminal.limitation.code.value if terminal.limitation else "none", "contract_version": dispatch.contract_version, "duration_ms": terminal.timings.total_ms})
