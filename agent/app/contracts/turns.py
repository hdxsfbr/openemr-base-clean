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


class ClaimFacts(StrictModel):
    """Typed facts the verifier checks field by field. Flat so structured
    output can emit it reliably; each claim type uses its own subset."""

    section: str | None = Field(default=None, max_length=32, description="change_event, absence, undated")
    kind: str | None = Field(default=None, max_length=32, description="change_event: added|ended|started|stopped|resulted|noted; conflict: status_conflict|note_vs_list|duplicate_sources")
    date: str | None = Field(default=None, max_length=10, description="YYYY-MM-DD for change_event and lab_result")
    name: str | None = Field(default=None, max_length=255, description="medication_status: medication name")
    status: str | None = Field(default=None, max_length=32, description="medication_status: active|inactive|unknown")
    analyte: str | None = Field(default=None, max_length=255, description="lab_result, lab_comparison")
    value_text: str | None = Field(default=None, max_length=255, description="lab_result: exactly as in the pack")
    unit: str | None = Field(default=None, max_length=64, description="lab_result: exactly as in the pack, null if missing")
    flag: str | None = Field(default=None, max_length=16, description="lab_result: abnormal|normal|unknown")
    earlier_source_id: str | None = Field(default=None, max_length=240, description="lab_comparison")
    later_source_id: str | None = Field(default=None, max_length=240, description="lab_comparison")
    direction: str | None = Field(default=None, max_length=8, description="lab_comparison: up|down|same")
    medication_name: str | None = Field(default=None, max_length=255, description="documented_reference")
    mention: str | None = Field(default=None, max_length=300, description="documented_reference: short quote from the cited note")
    state: str | None = Field(default=None, max_length=32, description="absence: not_documented|reviewed_none|no_records_in_window")
    reading: str | None = Field(default=None, max_length=300, description="interpretation: your reading of an ambiguous reference")

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default) if getattr(self, key, None) is not None else default


class Claim(StrictModel):
    id: str = Field(pattern=r"^c[0-9]{1,3}$")
    type: ClaimType
    text: str = Field(min_length=1, max_length=400)
    facts: ClaimFacts = Field(default_factory=ClaimFacts)
    source_ids: list[SourceId] = Field(default_factory=list, max_length=8)
    section: str | None = Field(default=None, max_length=32)


class TurnClaims(StrictModel):
    """The model's structured output. Nothing here is displayed until verified."""

    claims: list[Claim] = Field(default_factory=list, max_length=40)
    summary: str = Field(default="", max_length=600, description="One to three sentences that answer the question by restating the claims; shown only when every claim verified")


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
    summary: str = Field(default="", max_length=600, description="Paragraph shown above the claims")
    summary_basis: str = Field(default="none", pattern=r"^(model|deterministic|none)$", description="model: the model's summary, accepted because every claim verified; deterministic: built from verified claims")
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
