"""Turn contracts: what the panel sends, what the model must emit, what the
verifier decides, and what the API returns."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import Field

from .common import CorrelationId, SourceId, StrictModel


class ClaimType(StrEnum):
    change_event = "change_event"
    medication_status = "medication_status"
    lab_result = "lab_result"
    lab_comparison = "lab_comparison"
    documented_reference = "documented_reference"
    absence = "absence"
    conflict = "conflict"
    undated = "undated"
    interpretation = "interpretation"
    # Week 2 (reserved): document_extract, guideline_reference


class LimitationKind(StrEnum):
    not_documented = "not_documented"
    reviewed_none = "reviewed_none"
    unavailable = "unavailable"
    truncated = "truncated"
    conflict = "conflict"
    undated = "undated"
    withheld = "withheld"
    out_of_scope = "out_of_scope"
    narrative_unavailable = "narrative_unavailable"
    model_budget_exhausted = "model_budget_exhausted"


class Claim(StrictModel):
    id: str = Field(pattern=r"^c[0-9]{1,3}$")
    type: ClaimType
    text: str = Field(min_length=1, max_length=400)
    facts: dict[str, Any] = Field(default_factory=dict, description="Typed per claim type; checked field-by-field by the verifier")
    source_ids: list[SourceId] = Field(default_factory=list, max_length=8)
    section: str | None = Field(default=None, max_length=32)


class TurnClaims(StrictModel):
    """The model's structured output. Nothing here is displayed until verified."""

    claims: list[Claim] = Field(default_factory=list, max_length=40)
    limitations_restated: list[str] = Field(default_factory=list, max_length=20)


class Limitation(StrictModel):
    kind: LimitationKind
    section: str | None = Field(default=None, max_length=32)
    detail: str = Field(max_length=300)
    source_ids: list[SourceId] = Field(default_factory=list, max_length=8)


class Verification(StrictModel):
    outcome: str = Field(pattern=r"^(passed|partial|rejected|not_run|failed_closed)$")
    rules_applied: list[str] = Field(default_factory=list)
    rejected: list[dict[str, str]] = Field(default_factory=list, description="{claim_id, rule, detail}")
    repair_attempted: bool = False


class TurnRequest(StrictModel):
    message: str = Field(min_length=1, max_length=1000)
    correlation_id: CorrelationId | None = None
    stream: bool = False


class EvidenceSummary(StrictModel):
    tool: str
    status: str
    record_count: int
    truncated: bool = False
    absence_state: str | None = None


class SourceSummary(StrictModel):
    """A cited record the panel can open in the chart (CAP-05)."""

    source_id: SourceId
    table: str = Field(max_length=64)
    id: int
    label: str = Field(max_length=160)
    encounter_id: int | None = None
    order_id: int | None = None


class TurnResponse(StrictModel):
    turn_id: str
    conversation_id: str
    turn_type: str = Field(pattern=r"^(uc01_first|followup)$")
    status: str = Field(pattern=r"^(complete|partial|fallback|denied|failed)$")
    reference_encounter_source_id: SourceId | None = None
    window_since: date | None = None
    evidence: list[EvidenceSummary] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    sources: list[SourceSummary] = Field(default_factory=list)
    limitations: list[Limitation] = Field(default_factory=list)
    withheld_count: int = 0
    verification: Verification
    usage: dict[str, int | float] = Field(default_factory=dict)
    correlation_id: CorrelationId
    contract_version: str


class ErrorCode(StrEnum):
    unauthorized = "unauthorized"
    conversation_closed = "conversation_closed"
    patient_context_changed = "patient_context_changed"
    rate_limited = "rate_limited"
    dependency_unavailable = "dependency_unavailable"
    invalid_request = "invalid_request"
    internal_error = "internal_error"


class ErrorEnvelope(StrictModel):
    code: ErrorCode
    message: str = Field(max_length=200, description="Generic; specifics go to the audit log")
    correlation_id: CorrelationId
