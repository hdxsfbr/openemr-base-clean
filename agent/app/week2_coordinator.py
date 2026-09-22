"""Parent Week 2 coordination seam.

Routing, branch execution, and deterministic verification stay separate: the
supervisor selects a closed route, read-only branches may run concurrently,
and only their joined current-turn evidence reaches the verifier.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Literal, Sequence

from .contracts.common import StrictModel
from .contracts.week2 import DateTime, TurnBinding
from .parallel_join import LaneTerminal, join_chat_branches
from .supervisor import DeterministicSupervisor, SupervisorDecision, SupervisorEvent
from .week2_verifier import (
    CurrentTurnSourceRegistry,
    RegisteredSource,
    Week2VerificationResult,
    verify_week2_claims,
)

CoordinatorStatus = Literal["complete", "partial", "refused", "canceled", "unavailable", "failed"]


@dataclass(frozen=True)
class BranchEvidence:
    """Protected in-process branch output; never serialized by the coordinator."""

    candidates: Sequence[object] = ()
    sources: Sequence[RegisteredSource] = ()


class CoordinatorResult(StrictModel):
    status: CoordinatorStatus
    decision: SupervisorDecision
    lane_status: dict[Literal["patient_record", "guideline_evidence"], str]
    verification: Week2VerificationResult
    limitation_codes: list[str]


class Week2Coordinator:
    def __init__(self, supervisor: DeterministicSupervisor | None = None) -> None:
        self._supervisor = supervisor or DeterministicSupervisor()

    async def coordinate_chat(
        self,
        event: SupervisorEvent,
        *,
        now: DateTime,
        binding: TurnBinding,
        verified_at: DateTime,
        patient: Callable[[], Awaitable[BranchEvidence]],
        guideline: Callable[[], Awaitable[BranchEvidence]] | None = None,
        active_corpus_version: str | None = None,
    ) -> CoordinatorResult:
        decision = self._supervisor.route(event, now=now)
        if event.event_kind != "chat_turn" or decision.status != "dispatched":
            return CoordinatorResult(
                status=decision.status,
                decision=decision,
                lane_status={},
                verification=Week2VerificationResult(),
                limitation_codes=decision.limitation_codes,
            )

        guideline_selected = "evidence_retriever" in decision.routes

        async def missing_guideline() -> BranchEvidence:
            raise RuntimeError("guideline branch is unavailable")

        joined = await join_chat_branches(
            patient=patient,
            guideline=(guideline or missing_guideline) if guideline_selected else None,
        )
        terminals: list[LaneTerminal[BranchEvidence]] = [joined.patient]
        if joined.guideline is not None:
            terminals.append(joined.guideline)

        candidates: list[object] = []
        sources: list[RegisteredSource] = []
        for terminal in terminals:
            if terminal.status == "completed" and terminal.value is not None:
                candidates.extend(terminal.value.candidates)
                sources.extend(terminal.value.sources)

        limitation_codes = list(decision.limitation_codes)
        for terminal in terminals:
            if terminal.limitation_code and terminal.limitation_code not in limitation_codes:
                limitation_codes.append(terminal.limitation_code)

        try:
            registry = CurrentTurnSourceRegistry(
                binding=binding,
                sources=sources,
                verified_at=verified_at,
                active_corpus_version=active_corpus_version,
            )
            verification = verify_week2_claims(candidates, registry)
        except Exception:  # noqa: BLE001 - fail closed before any branch output is returned
            verification = Week2VerificationResult()
            if "source_registry_invalid" not in limitation_codes:
                limitation_codes.append("source_registry_invalid")
            joined_status: CoordinatorStatus = "failed"
        else:
            joined_status = joined.status

        lane_status = {"patient_record": joined.patient.status}
        if joined.guideline is not None:
            lane_status["guideline_evidence"] = joined.guideline.status
        return CoordinatorResult(
            status=joined_status,
            decision=decision,
            lane_status=lane_status,
            verification=verification,
            limitation_codes=limitation_codes,
        )
