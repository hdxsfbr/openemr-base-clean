"""Model-free Week 2 route table and reference-only worker dispatch."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Literal, Protocol
from uuid import uuid4

from pydantic import Field, model_validator

from .contracts.common import CorrelationId, StrictModel
from .contracts.week2 import VersionedReference, WorkerHandoffRequest

Route = Literal["patient_turn_graph", "intake_extractor", "evidence_retriever"]
log = logging.getLogger("copilot.supervisor")


class SupervisorReadiness(StrictModel):
    core_ready: bool
    document_ready: bool
    guideline_ready: bool


class SupervisorEvent(StrictModel):
    event_kind: Literal["document_uploaded", "reprocess_requested", "chat_turn"]
    correlation_id: CorrelationId
    conversation_id: str | None = Field(default=None, min_length=1, max_length=128)
    turn_id: str | None = Field(default=None, min_length=1, max_length=128)
    authorized: bool
    canceled: bool
    guideline_intent: Literal["none", "explicit_permitted", "ambiguous", "prohibited"]
    source_ref: VersionedReference | None = None
    evidence_query_ref: VersionedReference | None = None
    corpus_ref: VersionedReference | None = None
    source_version_budget: bool
    readiness: SupervisorReadiness
    contract_versions: dict[str, str] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_event_shape(self) -> "SupervisorEvent":
        if self.event_kind in ("document_uploaded", "reprocess_requested"):
            if self.source_ref is None or self.source_ref.kind != "source_document":
                raise ValueError("document events require one source-document reference")
            if self.evidence_query_ref is not None or self.corpus_ref is not None or self.guideline_intent != "none":
                raise ValueError("document events cannot carry guideline inputs")
        else:
            if self.source_ref is not None:
                raise ValueError("chat events cannot dispatch a source document")
            if self.guideline_intent == "explicit_permitted":
                if self.evidence_query_ref is None or self.evidence_query_ref.kind != "evidence_query":
                    raise ValueError("explicit guideline events require an evidence-query reference")
                if self.corpus_ref is None or self.corpus_ref.kind != "corpus":
                    raise ValueError("explicit guideline events require a corpus reference")
            elif self.evidence_query_ref is not None or self.corpus_ref is not None:
                raise ValueError("non-explicit chat cannot smuggle guideline references")
        for reference in (self.source_ref, self.evidence_query_ref, self.corpus_ref):
            if reference is not None and reference.integrity_sha256 is None:
                raise ValueError("supervisor input references require integrity hashes")
        return self


class SupervisorDecision(StrictModel):
    status: Literal["dispatched", "refused", "canceled", "unavailable"]
    routes: tuple[Route, ...] = Field(max_length=2)
    handoffs: list[WorkerHandoffRequest] = Field(max_length=1)
    limitation_codes: list[str] = Field(max_length=4)


class SupervisorRouteEvent(StrictModel):
    event: Literal["supervisor.route"] = "supervisor.route"
    correlation_id: CorrelationId
    event_kind: Literal["document_uploaded", "reprocess_requested", "chat_turn"]
    status: Literal["dispatched", "refused", "canceled", "unavailable"]
    routes: tuple[Route, ...] = Field(max_length=2)
    limitation_codes: list[str] = Field(max_length=4)
    handoff_ids: list[str] = Field(max_length=1)


class SupervisorTelemetryPort(Protocol):
    def record(self, event: SupervisorRouteEvent) -> None: ...


class LoggingSupervisorTelemetry:
    def record(self, event: SupervisorRouteEvent) -> None:
        log.info(
            "supervisor.route routes=%s limitations=%s handoffs=%d",
            ",".join(event.routes) or "none",
            ",".join(event.limitation_codes) or "none",
            len(event.handoff_ids),
            extra={
                "component": "supervisor",
                "correlation_id": event.correlation_id,
                "status": event.status,
            },
        )


class DeterministicSupervisor:
    def __init__(
        self,
        *,
        handoff_id: Callable[[], str] = lambda: str(uuid4()),
        telemetry: SupervisorTelemetryPort | None = None,
    ) -> None:
        self._handoff_id = handoff_id
        self._telemetry = telemetry or LoggingSupervisorTelemetry()

    def route(self, event: SupervisorEvent, *, now: str) -> SupervisorDecision:
        decision = self._route(event, now=now)
        self._telemetry.record(SupervisorRouteEvent(
            correlation_id=event.correlation_id,
            event_kind=event.event_kind,
            status=decision.status,
            routes=decision.routes,
            limitation_codes=decision.limitation_codes,
            handoff_ids=[handoff.handoff_id for handoff in decision.handoffs],
        ))
        return decision

    def _route(self, event: SupervisorEvent, *, now: str) -> SupervisorDecision:
        observed_now = _utc(now)
        if not event.authorized:
            return self._decision("refused", limitations=["authorization_denied"])
        if event.canceled:
            return self._decision("canceled", limitations=["canceled"])
        if not event.readiness.core_ready:
            return self._decision("unavailable", limitations=["core_unavailable"])

        if event.event_kind in ("document_uploaded", "reprocess_requested"):
            if not event.readiness.document_ready:
                return self._decision("unavailable", limitations=["document_unavailable"])
            if event.event_kind == "reprocess_requested" and not event.source_version_budget:
                return self._decision("refused", limitations=["extraction_version_limit"])
            assert event.source_ref is not None
            handoff = self._handoff(
                event,
                worker="intake_extractor",
                reason=(
                    "authorized_document_uploaded"
                    if event.event_kind == "document_uploaded"
                    else "authorized_reprocess_requested"
                ),
                deadline=observed_now + timedelta(seconds=95),
                refs=[event.source_ref],
            )
            return self._decision("dispatched", routes=("intake_extractor",), handoffs=[handoff])

        if event.guideline_intent == "prohibited":
            return self._decision("refused", limitations=["guideline_intent_prohibited"])
        if event.guideline_intent == "ambiguous":
            return self._decision(
                "dispatched",
                routes=("patient_turn_graph",),
                limitations=["guideline_intent_ambiguous"],
            )
        if event.guideline_intent == "none":
            return self._decision("dispatched", routes=("patient_turn_graph",))
        if not event.readiness.guideline_ready:
            return self._decision(
                "dispatched",
                routes=("patient_turn_graph",),
                limitations=["guideline_unavailable"],
            )
        assert event.evidence_query_ref is not None and event.corpus_ref is not None
        handoff = self._handoff(
            event,
            worker="evidence_retriever",
            reason="explicit_guideline_request",
            deadline=observed_now + timedelta(seconds=2),
            refs=[event.evidence_query_ref, event.corpus_ref],
        )
        return self._decision(
            "dispatched",
            routes=("patient_turn_graph", "evidence_retriever"),
            handoffs=[handoff],
        )

    def _handoff(
        self,
        event: SupervisorEvent,
        *,
        worker: str,
        reason: str,
        deadline: datetime,
        refs: list[VersionedReference],
    ) -> WorkerHandoffRequest:
        return WorkerHandoffRequest.model_validate({
            "handoff_id": self._handoff_id(),
            "correlation_id": event.correlation_id,
            "conversation_id": event.conversation_id,
            "turn_id": event.turn_id,
            "event_kind": event.event_kind,
            "worker": worker,
            "reason_code": reason,
            "attempt": 1,
            "deadline_at": deadline.isoformat().replace("+00:00", "Z"),
            "input_refs": [reference.model_dump(mode="json") for reference in refs],
            "contract_versions": event.contract_versions,
        })

    @staticmethod
    def _decision(
        status: str,
        *,
        routes: tuple[Route, ...] = (),
        handoffs: list[WorkerHandoffRequest] | None = None,
        limitations: list[str] | None = None,
    ) -> SupervisorDecision:
        return SupervisorDecision.model_validate({
            "status": status,
            "routes": routes,
            "handoffs": [handoff.model_dump(mode="json") for handoff in handoffs or []],
            "limitation_codes": limitations or [],
        })


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("supervisor timestamp must be UTC")
    return parsed.astimezone(timezone.utc)
