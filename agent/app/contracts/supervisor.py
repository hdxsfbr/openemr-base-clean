"""PHI-free, deterministic supervisor contracts (ADR-0013).

This module is deliberately a policy boundary, not a graph node.  Its inputs
contain only authorization attestations, opaque/versioned references and finite
intent signals.  Callers which inspect a question or a document must discard
the protected content before constructing one of these models.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, TypeAdapter, model_validator

from .common import CorrelationId, StrictModel
from .documents import DocumentSourceId, DocumentType
from .guidelines import ACTIVE_CORPUS_VERSION, GuidelineTopic


SUPERVISOR_CONTRACT_VERSION = "4.0.0"

OpaqueId = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{16,64}$", max_length=64)]
HandoffId = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{32}$", max_length=32)]
VersionId = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$", max_length=64)]


class SupervisorEventKind(StrEnum):
    document_uploaded = "document_uploaded"
    reprocess_requested = "reprocess_requested"
    chat_turn = "chat_turn"


class SupervisorWorker(StrEnum):
    intake_extractor = "intake_extractor"
    evidence_retriever = "evidence_retriever"


class RouteReason(StrEnum):
    document_event = "document_event"
    patient_record_only = "patient_record_only"
    explicit_control = "explicit_control"
    explicit_guideline_terms = "explicit_guideline_terms"
    evidence_for_supported_finding = "evidence_for_supported_finding"
    ambiguous = "ambiguous"
    disallowed_advice = "disallowed_advice"


class RouteAction(StrEnum):
    dispatch_intake = "dispatch_intake"
    dispatch_evidence = "dispatch_evidence"
    patient_record_only = "patient_record_only"
    clarify = "clarify"
    refuse = "refuse"


class ChatIntentSignal(StrEnum):
    """Finite, trusted results of an upstream inspection; never raw question text."""

    explicit_guideline_terms = "explicit_guideline_terms"
    evidence_for_supported_finding = "evidence_for_supported_finding"
    ambiguous_evidence = "ambiguous_evidence"
    diagnosis_intent = "diagnosis_intent"
    treatment_intent = "treatment_intent"
    dosing_intent = "dosing_intent"
    patient_applicability_intent = "patient_applicability_intent"


class AuthorizedDocumentEvent(StrictModel):
    event_kind: Literal[SupervisorEventKind.document_uploaded, SupervisorEventKind.reprocess_requested]
    event_id: OpaqueId
    authorization_ref: OpaqueId
    source_id: DocumentSourceId
    source_version: VersionId
    document_type: DocumentType
    authorized: Literal[True] = True


class AuthorizedChatEvent(StrictModel):
    event_kind: Literal[SupervisorEventKind.chat_turn] = SupervisorEventKind.chat_turn
    event_id: OpaqueId
    authorization_ref: OpaqueId
    turn_ref: OpaqueId
    patient_record_authorized: Literal[True] = True
    include_guideline_evidence: bool = False
    intent_signals: list[ChatIntentSignal] = Field(default_factory=list, max_length=4)
    supported_finding_topics: list[GuidelineTopic] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def bounded_signals_are_consistent(self) -> "AuthorizedChatEvent":
        if len(set(self.intent_signals)) != len(self.intent_signals):
            raise ValueError("intent_signals must not repeat")
        if len(set(self.supported_finding_topics)) != len(self.supported_finding_topics):
            raise ValueError("supported_finding_topics must not repeat")
        if (
            ChatIntentSignal.evidence_for_supported_finding in self.intent_signals
            and not self.supported_finding_topics
        ):
            raise ValueError("supported-finding evidence needs an approved topic")
        if self.supported_finding_topics and ChatIntentSignal.evidence_for_supported_finding not in self.intent_signals:
            raise ValueError("topics require the supported-finding signal")
        return self


SupervisorEvent = AuthorizedDocumentEvent | AuthorizedChatEvent


class SupervisorRequestState(StrictModel):
    """Checkpoint-safe request state. It intentionally has no patient or content field."""

    contract_version: Literal["4.0.0"]
    correlation_id: CorrelationId
    event: SupervisorEvent
    deadline_unix_ms: int = Field(ge=1, le=4_102_444_800_000)


class RouteDecision(StrictModel):
    contract_version: Literal["4.0.0"]
    correlation_id: CorrelationId
    event_kind: SupervisorEventKind
    action: RouteAction
    reason: RouteReason
    preserve_patient_record_path: bool
    worker: SupervisorWorker | None = None
    limitation: "SupervisorLimitation | None" = None

    @model_validator(mode="after")
    def route_and_worker_are_exhaustive(self) -> "RouteDecision":
        expected = {
            RouteAction.dispatch_intake: (SupervisorWorker.intake_extractor, False, None),
            RouteAction.dispatch_evidence: (SupervisorWorker.evidence_retriever, True, None),
            RouteAction.patient_record_only: (None, True, None),
            RouteAction.clarify: (None, True, SupervisorLimitationCode.ambiguous_evidence_intent),
            RouteAction.refuse: (None, False, SupervisorLimitationCode.disallowed_advice_intent),
        }[self.action]
        worker, patient_path, limitation = expected
        if self.worker is not worker or self.preserve_patient_record_path is not patient_path:
            raise ValueError("route action has an invalid worker or patient-record path")
        if limitation is None and self.limitation is not None:
            raise ValueError("successful route action cannot carry a limitation")
        if limitation is not None and (self.limitation is None or self.limitation.code is not limitation):
            raise ValueError("terminal route action needs its expected limitation")
        return self


class SupervisorLimitationCode(StrEnum):
    ambiguous_evidence_intent = "ambiguous_evidence_intent"
    disallowed_advice_intent = "disallowed_advice_intent"
    unauthorized_event = "unauthorized_event"
    unsupported_event = "unsupported_event"
    stale_handoff = "stale_handoff"
    duplicate_terminal = "duplicate_terminal"
    wrong_worker = "wrong_worker"
    correlation_mismatch = "correlation_mismatch"
    contract_version_mismatch = "contract_version_mismatch"
    malformed_transition = "malformed_transition"
    deadline_exceeded = "deadline_exceeded"
    worker_unavailable = "worker_unavailable"
    worker_canceled = "worker_canceled"
    no_evidence = "no_evidence"


class SupervisorLimitation(StrictModel):
    code: SupervisorLimitationCode
    retryable: Literal[False] = False


class DocumentInputReference(StrictModel):
    kind: Literal["document_source"] = "document_source"
    source_id: DocumentSourceId
    source_version: VersionId
    document_type: DocumentType
    contract_version: Literal["2.0.0"]


class EvidenceInputReference(StrictModel):
    kind: Literal["evidence_request"] = "evidence_request"
    request_ref: OpaqueId
    corpus_version: Literal["uspstf-recommendations-2026-09-21-v2"] = ACTIVE_CORPUS_VERSION
    contract_version: Literal["3.0.0"]


HandoffInputReference = DocumentInputReference | EvidenceInputReference


class HandoffOutputReference(StrictModel):
    kind: Literal["extraction_result", "evidence_result"]
    result_ref: OpaqueId
    result_version: VersionId
    contract_version: Literal["2.0.0", "3.0.0"]


class HandoffStatus(StrEnum):
    dispatched = "dispatched"
    completed = "completed"
    limited = "limited"
    canceled = "canceled"


class HandoffTimings(StrictModel):
    queued_ms: int = Field(ge=0, le=95_000)
    worker_ms: int = Field(ge=0, le=95_000)
    total_ms: int = Field(ge=0, le=95_000)

    @model_validator(mode="after")
    def total_covers_stages(self) -> "HandoffTimings":
        if self.total_ms < self.queued_ms + self.worker_ms:
            raise ValueError("total_ms must cover queued_ms plus worker_ms")
        return self


class DispatchRecord(StrictModel):
    contract_version: Literal["4.0.0"]
    correlation_id: CorrelationId
    handoff_id: HandoffId
    event_kind: SupervisorEventKind
    worker: SupervisorWorker
    reason: RouteReason
    attempt: Literal[1] = 1
    deadline_unix_ms: int = Field(ge=1, le=4_102_444_800_000)
    input_ref: HandoffInputReference
    status: Literal[HandoffStatus.dispatched] = HandoffStatus.dispatched

    @model_validator(mode="after")
    def worker_may_receive_only_its_authorized_reference(self) -> "DispatchRecord":
        if self.worker is SupervisorWorker.intake_extractor:
            if self.event_kind not in {SupervisorEventKind.document_uploaded, SupervisorEventKind.reprocess_requested} or not isinstance(self.input_ref, DocumentInputReference) or self.reason is not RouteReason.document_event:
                raise ValueError("intake extractor accepts only authorized document events")
        elif self.worker is SupervisorWorker.evidence_retriever:
            if self.event_kind is not SupervisorEventKind.chat_turn or not isinstance(self.input_ref, EvidenceInputReference) or self.reason not in {RouteReason.explicit_control, RouteReason.explicit_guideline_terms, RouteReason.evidence_for_supported_finding}:
                raise ValueError("evidence retriever accepts only permitted chat evidence routes")
        return self


class HandoffCompletion(StrictModel):
    contract_version: Literal["4.0.0"]
    correlation_id: CorrelationId
    handoff_id: HandoffId
    worker: SupervisorWorker
    status: Literal[HandoffStatus.completed, HandoffStatus.limited, HandoffStatus.canceled]
    output_ref: HandoffOutputReference | None = None
    limitation: SupervisorLimitation | None = None
    timings: HandoffTimings

    @model_validator(mode="after")
    def terminal_completion_is_atomic(self) -> "HandoffCompletion":
        if self.status is HandoffStatus.completed and (self.output_ref is None or self.limitation is not None):
            raise ValueError("completed handoff needs only an output reference")
        if self.status is not HandoffStatus.completed and (self.output_ref is not None or self.limitation is None):
            raise ValueError("limited or canceled handoff needs only a limitation")
        if self.status is HandoffStatus.canceled and self.limitation and self.limitation.code is not SupervisorLimitationCode.worker_canceled:
            raise ValueError("canceled handoff needs worker_canceled limitation")
        if self.output_ref is not None:
            expected = ("extraction_result", "2.0.0") if self.worker is SupervisorWorker.intake_extractor else ("evidence_result", "3.0.0")
            if (self.output_ref.kind, self.output_ref.contract_version) != expected:
                raise ValueError("output reference must match its worker contract")
        return self


class BranchState(StrEnum):
    not_requested = "not_requested"
    pending = "pending"
    terminal = "terminal"


class SupervisorBranchState(StrictModel):
    worker: SupervisorWorker
    state: BranchState
    dispatch: DispatchRecord | None = None
    terminal: HandoffCompletion | None = None

    @model_validator(mode="after")
    def branch_has_one_valid_lifecycle_shape(self) -> "SupervisorBranchState":
        if self.state is BranchState.not_requested and (self.dispatch or self.terminal):
            raise ValueError("unrequested branch cannot have a handoff")
        if self.state is BranchState.pending and (self.dispatch is None or self.terminal is not None):
            raise ValueError("pending branch needs exactly one dispatch")
        if self.state is BranchState.terminal and (self.dispatch is None or self.terminal is None):
            raise ValueError("terminal branch needs dispatch and terminal result")
        if self.dispatch and self.dispatch.worker is not self.worker:
            raise ValueError("dispatch worker must match branch")
        if self.terminal and self.terminal.worker is not self.worker:
            raise ValueError("terminal worker must match branch")
        return self


class ClaimVerificationReference(StrictModel):
    claim_ref: OpaqueId
    source_resolution: Literal["passed"]
    deterministic_verification: Literal["accepted", "withheld"]
    displayed: bool

    @model_validator(mode="after")
    def displayed_claims_require_verifier_acceptance(self) -> "ClaimVerificationReference":
        if self.displayed and self.deterministic_verification != "accepted":
            raise ValueError("displayed claims require deterministic acceptance")
        return self


class AnswerReadinessResult(StrictModel):
    contract_version: Literal["4.0.0"]
    correlation_id: CorrelationId
    ready: bool
    requested_branches_terminal: bool
    displayed_claims_verified: bool
    limitation: SupervisorLimitation | None = None


def decide_route(request: SupervisorRequestState) -> RouteDecision:
    """Return the only possible route from content-free trusted signals.

    The precedence is deliberate: advice/applicability intent refuses before
    retrieval even if an explicit evidence control was selected.
    """
    event = request.event
    if isinstance(event, AuthorizedDocumentEvent):
        return RouteDecision(
            contract_version=SUPERVISOR_CONTRACT_VERSION, correlation_id=request.correlation_id, event_kind=event.event_kind,
            action=RouteAction.dispatch_intake, reason=RouteReason.document_event,
            preserve_patient_record_path=False, worker=SupervisorWorker.intake_extractor,
        )
    disallowed = {
        ChatIntentSignal.diagnosis_intent, ChatIntentSignal.treatment_intent,
        ChatIntentSignal.dosing_intent, ChatIntentSignal.patient_applicability_intent,
    }
    signals = set(event.intent_signals)
    if signals & disallowed:
        return _route(request, RouteAction.refuse, RouteReason.disallowed_advice)
    if event.include_guideline_evidence:
        return _route(request, RouteAction.dispatch_evidence, RouteReason.explicit_control)
    if ChatIntentSignal.explicit_guideline_terms in signals:
        return _route(request, RouteAction.dispatch_evidence, RouteReason.explicit_guideline_terms)
    if ChatIntentSignal.evidence_for_supported_finding in signals:
        return _route(request, RouteAction.dispatch_evidence, RouteReason.evidence_for_supported_finding)
    if ChatIntentSignal.ambiguous_evidence in signals:
        return _route(request, RouteAction.clarify, RouteReason.ambiguous)
    return _route(request, RouteAction.patient_record_only, RouteReason.patient_record_only)


def _route(request: SupervisorRequestState, action: RouteAction, reason: RouteReason) -> RouteDecision:
    limitation = None
    if action is RouteAction.clarify:
        limitation = SupervisorLimitation(code=SupervisorLimitationCode.ambiguous_evidence_intent)
    elif action is RouteAction.refuse:
        limitation = SupervisorLimitation(code=SupervisorLimitationCode.disallowed_advice_intent)
    return RouteDecision(
        contract_version=SUPERVISOR_CONTRACT_VERSION, correlation_id=request.correlation_id, event_kind=request.event.event_kind,
        action=action, reason=reason,
        preserve_patient_record_path=action in {RouteAction.dispatch_evidence, RouteAction.patient_record_only, RouteAction.clarify},
        worker=SupervisorWorker.evidence_retriever if action is RouteAction.dispatch_evidence else None,
        limitation=limitation,
    )


def complete_handoff(dispatch: DispatchRecord, completion: HandoffCompletion, *, now_unix_ms: int) -> SupervisorBranchState:
    """Fail closed unless one current dispatched record receives one matching terminal."""
    if dispatch.contract_version != completion.contract_version:
        raise ValueError(SupervisorLimitationCode.contract_version_mismatch.value)
    if dispatch.correlation_id != completion.correlation_id:
        raise ValueError(SupervisorLimitationCode.correlation_mismatch.value)
    if dispatch.handoff_id != completion.handoff_id or dispatch.worker is not completion.worker:
        raise ValueError(SupervisorLimitationCode.wrong_worker.value)
    if now_unix_ms > dispatch.deadline_unix_ms:
        raise ValueError(SupervisorLimitationCode.deadline_exceeded.value)
    if dispatch.worker is SupervisorWorker.intake_extractor:
        if completion.output_ref and completion.output_ref.kind != "extraction_result":
            raise ValueError(SupervisorLimitationCode.malformed_transition.value)
    elif completion.output_ref and completion.output_ref.kind != "evidence_result":
        raise ValueError(SupervisorLimitationCode.malformed_transition.value)
    return SupervisorBranchState(worker=dispatch.worker, state=BranchState.terminal, dispatch=dispatch, terminal=completion)


def apply_handoff_completion(branch: SupervisorBranchState, completion: HandoffCompletion, *, now_unix_ms: int) -> SupervisorBranchState:
    """Apply one terminal result to one pending branch exactly once."""
    if branch.state is BranchState.terminal:
        raise ValueError(SupervisorLimitationCode.duplicate_terminal.value)
    if branch.state is not BranchState.pending or branch.dispatch is None:
        raise ValueError(SupervisorLimitationCode.malformed_transition.value)
    return complete_handoff(branch.dispatch, completion, now_unix_ms=now_unix_ms)


def answer_readiness(
    correlation_id: str,
    branches: list[SupervisorBranchState],
    claims: list[ClaimVerificationReference],
) -> AnswerReadinessResult:
    """Observe verifier outputs; do not certify claims or mutate worker state."""
    try:
        safe_correlation = TypeAdapter(CorrelationId).validate_python(correlation_id)
    except Exception as exc:
        raise ValueError("invalid correlation id") from exc
    requested_terminal = all(branch.state is not BranchState.pending for branch in branches)
    claims_verified = all(not claim.displayed or claim.deterministic_verification == "accepted" for claim in claims)
    ready = requested_terminal and claims_verified
    limitation = None if ready else SupervisorLimitation(code=SupervisorLimitationCode.malformed_transition)
    return AnswerReadinessResult(
        contract_version=SUPERVISOR_CONTRACT_VERSION, correlation_id=safe_correlation, ready=ready,
        requested_branches_terminal=requested_terminal,
        displayed_claims_verified=claims_verified, limitation=limitation,
    )
