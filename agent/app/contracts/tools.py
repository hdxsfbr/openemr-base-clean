"""Tool contracts: requests the agent sends to the gateway and the typed,
status-bearing records the gateway returns (AUDIT.md section 7.1)."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import Field

from .common import ClinicalDate, CorrelationId, SourceRef, StrictModel

TOOL_NAMES = ("patient_context", "encounters", "clinical_notes", "problems", "medications", "allergies", "lab_results")
ToolName = Literal["patient_context", "encounters", "clinical_notes", "problems", "medications", "allergies", "lab_results"]


class ToolStatus(StrEnum):
    ok = "ok"
    empty = "empty"
    partial = "partial"
    unavailable = "unavailable"


class AbsenceState(StrEnum):
    documented = "documented"
    reviewed_none = "reviewed_none"
    not_documented = "not_documented"


class Window(StrictModel):
    since: date | None = None
    until: date | None = None


# ---- parameters (no tool accepts a patient identifier; extra="forbid" rejects one) ----


class WindowParams(StrictModel):
    since: date | None = None
    until: date | None = None
    limit: int = Field(default=50, ge=1, le=50)
    cursor: str | None = Field(default=None, max_length=64)


class NotesParams(WindowParams):
    limit: int = Field(default=20, ge=1, le=20)
    term: str | None = Field(default=None, min_length=2, max_length=80, description="Bounded substring search (UC-03)")


class LabsParams(WindowParams):
    analyte: str | None = Field(default=None, min_length=2, max_length=80, description="Same-analyte lookup (UC-02)")


class ToolRequest(StrictModel):
    tool: ToolName
    params: WindowParams | NotesParams | LabsParams = Field(default_factory=WindowParams)
    correlation_id: CorrelationId


# ---- records ----


class Person(StrictModel):
    username: str | None = Field(default=None, max_length=255)
    display: str | None = Field(default=None, max_length=255)
    unknown: bool = False  # DQ-MEDIUM-008: authorship not recorded


class PatientContextRecord(StrictModel):
    source: SourceRef
    age_band: str = Field(max_length=16, description="e.g. 60-69; never the date of birth")
    sex: str | None = Field(default=None, max_length=32)
    counts: dict[str, int] = Field(default_factory=dict, description="Section row counts for the panel header")


class EncounterRecord(StrictModel):
    source: SourceRef
    encounter_id: int
    date: ClinicalDate
    category: str | None = Field(default=None, max_length=64)
    class_code: str | None = Field(default=None, max_length=16)
    reason: str | None = Field(default=None, max_length=200)
    provider: Person = Field(default_factory=Person)
    is_clinical_visit: bool = Field(description="Reference-encounter candidate (UC-01)")
    sensitivity: str | None = Field(default=None, max_length=32)


class NoteRecord(StrictModel):
    source: SourceRef
    encounter_id: int | None = None
    date: ClinicalDate
    note_type: str | None = Field(default=None, max_length=64)
    author: Person = Field(default_factory=Person)
    text: str = Field(max_length=4000)
    truncated: bool = False
    term_matched: bool | None = None


class Code(StrictModel):
    system: str | None = Field(default=None, max_length=32)
    code: str | None = Field(default=None, max_length=64)
    as_written: str = Field(max_length=128, description="Exactly as stored; no translation (DQ-HIGH-005)")


class ProblemRecord(StrictModel):
    source: SourceRef
    title: str = Field(max_length=255)
    codes: list[Code] = Field(default_factory=list)
    status: Literal["active", "inactive", "unknown"]
    begin: ClinicalDate
    end: ClinicalDate
    undated: bool = Field(description="No clinical begin date; cannot be placed in a timeline")
    verification: str | None = Field(default=None, max_length=32)
    author: Person = Field(default_factory=Person)
    linked_encounter_count: int = 0


class MedicationRecord(StrictModel):
    source: SourceRef
    provenance: Literal["lists", "prescriptions"]
    name: str = Field(max_length=255)
    codes: list[Code] = Field(default_factory=list)
    dose_text: str | None = Field(default=None, max_length=255, description="Resolved labels, never option ids (DQ-MEDIUM-010)")
    start: ClinicalDate
    end: ClinicalDate
    status: Literal["active", "inactive", "unknown"]
    status_basis: Literal["enddate", "activity", "both", "none"]
    status_conflict: bool = Field(description="enddate and activity disagree (DQ-HIGH-002)")
    prescriber: Person = Field(default_factory=Person)
    documented_indication: str | None = Field(default=None, max_length=255, description="Only what the row records; never inferred")
    undated: bool


class AllergyRecord(StrictModel):
    source: SourceRef
    substance: str = Field(max_length=255)
    reaction: str | None = Field(default=None, max_length=255)
    severity: str | None = Field(default=None, max_length=64)
    status: Literal["active", "inactive", "unknown"]
    begin: ClinicalDate
    undated: bool


class LabResultRecord(StrictModel):
    source: SourceRef
    order_id: int
    report_id: int
    analyte: str = Field(max_length=255)
    analyte_code: str | None = Field(default=None, max_length=64)
    value_text: str = Field(max_length=255, description="Exactly as stored")
    numeric_value: float | None = Field(default=None, description="Set only when value_text is strictly numeric")
    unit: str | None = Field(default=None, max_length=64)
    range_text: str | None = Field(default=None, max_length=128)
    flag: Literal["abnormal", "normal", "unknown"]
    flag_as_recorded: str | None = Field(default=None, max_length=32)
    date: ClinicalDate
    result_status: str | None = Field(default=None, max_length=32)
    corrected: bool = False
    comparable: bool = Field(description="numeric value with a non-empty unit")


ToolRecord = PatientContextRecord | EncounterRecord | NoteRecord | ProblemRecord | MedicationRecord | AllergyRecord | LabResultRecord


class ToolResponse(StrictModel):
    """The envelope every tool returns. `status` is never inferred from an empty
    list: `empty` means retrieval succeeded and found nothing, `unavailable`
    means it did not succeed (PERF-MED-001)."""

    tool: ToolName
    tool_version: str = Field(max_length=16)
    contract_version: str = Field(max_length=16)
    status: ToolStatus
    reason: str | None = Field(default=None, max_length=64)
    records: list[ToolRecord] = Field(default_factory=list)
    window: Window = Field(default_factory=Window)
    truncated: bool = False
    omitted_count: int = Field(default=0, ge=0)
    counts: dict[str, int] = Field(default_factory=dict)
    absence_state: AbsenceState | None = Field(default=None, description="Allergies: reviewed_none vs not_documented (DQ-MEDIUM-007)")
    latency_ms: float = Field(ge=0)
    correlation_id: CorrelationId
