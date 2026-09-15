"""Evidence pack: deterministic context assembly from tool responses
(AUDIT.md section 8 row 4). Chooses the reference encounter, computes the
window, derives the change set, renders a compact text with source ids
inline, and keeps an index the verifier resolves claims against."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from .contracts import (
    AllergyRecord,
    EncounterRecord,
    LabResultRecord,
    MedicationRecord,
    NoteRecord,
    PatientContextRecord,
    ProblemRecord,
    ToolResponse,
)

SECTION_OF_TOOL = {
    "patient_context": "patient",
    "encounters": "encounters",
    "clinical_notes": "notes",
    "problems": "problems",
    "medications": "medications",
    "allergies": "allergies",
    "lab_results": "labs",
}


def _day(d: Any) -> date | None:
    value = getattr(d, "value", None)
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _daystr(d: Any) -> str:
    day = _day(d)
    return day.isoformat() if day else "undated"


@dataclass
class ChangeEvent:
    section: str
    kind: str  # added | started | stopped | resulted | noted | reviewed
    date: date | None
    source_id: str
    summary: str


@dataclass
class EvidencePack:
    responses: dict[str, ToolResponse] = field(default_factory=dict)
    records: dict[str, Any] = field(default_factory=dict)  # source_id -> record
    reference_encounter: EncounterRecord | None = None
    window_since: date | None = None
    window_until: date | None = None
    changes: list[ChangeEvent] = field(default_factory=list)
    text: str = ""
    truncated: bool = False

    def status_of(self, tool: str) -> str | None:
        r = self.responses.get(tool)
        return r.status.value if r else None

    def evidence_summary(self) -> list[dict[str, Any]]:
        return [
            {
                "tool": name,
                "status": r.status.value,
                "record_count": len(r.records),
                "truncated": r.truncated,
                "absence_state": r.absence_state.value if r.absence_state else None,
            }
            for name, r in self.responses.items()
        ]


def choose_reference_encounter(encounters: list[EncounterRecord], today: date) -> EncounterRecord | None:
    """Latest clinical visit strictly before today; none means no prior visit."""
    candidates = [e for e in encounters if e.is_clinical_visit and (_day(e.date) or today) < today]
    candidates.sort(key=lambda e: _day(e.date) or date.min, reverse=True)
    return candidates[0] if candidates else None


def add_responses(pack: EvidencePack, responses: list[ToolResponse]) -> None:
    for r in responses:
        pack.responses[r.tool] = r
        for rec in r.records:
            pack.records[rec.source.source_id] = rec


def derive_changes(pack: EvidencePack) -> None:
    since, until = pack.window_since, pack.window_until

    def in_window(d: date | None) -> bool:
        if d is None:
            return False
        return (since is None or d >= since) and (until is None or d <= until)

    changes: list[ChangeEvent] = []
    for rec in pack.records.values():
        sid = rec.source.source_id
        if isinstance(rec, ProblemRecord):
            if in_window(_day(rec.begin)):
                changes.append(ChangeEvent("problems", "added", _day(rec.begin), sid, f"problem added: {rec.title}"))
            if in_window(_day(rec.end)):
                changes.append(ChangeEvent("problems", "ended", _day(rec.end), sid, f"problem ended: {rec.title}"))
        elif isinstance(rec, MedicationRecord):
            if in_window(_day(rec.start)):
                changes.append(ChangeEvent("medications", "started", _day(rec.start), sid, f"medication started: {rec.name}"))
            if in_window(_day(rec.end)):
                changes.append(ChangeEvent("medications", "stopped", _day(rec.end), sid, f"medication stopped: {rec.name}"))
        elif isinstance(rec, AllergyRecord):
            if in_window(_day(rec.begin)):
                changes.append(ChangeEvent("allergies", "added", _day(rec.begin), sid, f"allergy added: {rec.substance}"))
        elif isinstance(rec, LabResultRecord):
            if in_window(_day(rec.date)):
                changes.append(ChangeEvent("labs", "resulted", _day(rec.date), sid, f"result: {rec.analyte} {rec.value_text} {rec.unit or ''} [{rec.flag}]"))
        elif isinstance(rec, NoteRecord):
            if in_window(_day(rec.date)):
                changes.append(ChangeEvent("notes", "noted", _day(rec.date), sid, f"note ({rec.note_type or 'note'})"))
    changes.sort(key=lambda c: (c.date or date.min, c.section), reverse=True)
    pack.changes = changes


def render(pack: EvidencePack, max_chars: int) -> None:
    """Deterministic, stable-ordered text. Record text is data: it is fenced."""
    lines: list[str] = []
    since = pack.window_since.isoformat() if pack.window_since else "none"
    ref = pack.reference_encounter
    lines.append("== CONTEXT ==")
    if ref:
        lines.append(f"reference_encounter: {ref.source.source_id} date={_daystr(ref.date)} category={ref.category or '?'}")
    else:
        lines.append("reference_encounter: none (no prior clinical visit documented)")
    lines.append(f"window_since: {since}")
    for tool, r in pack.responses.items():
        lines.append(f"tool {tool}: status={r.status.value} records={len(r.records)} truncated={str(r.truncated).lower()}"
                     + (f" absence_state={r.absence_state.value}" if r.absence_state else "")
                     + (f" reason={r.reason}" if r.reason else ""))
    for tool, r in pack.responses.items():
        section = SECTION_OF_TOOL.get(tool, tool)
        lines.append(f"== {section.upper()} ==")
        if r.status.value == "unavailable":
            lines.append(f"(unavailable: {r.reason})")
            continue
        if not r.records:
            lines.append("(no records in window)" if r.absence_state is None else f"(absence_state={r.absence_state.value})")
        for rec in r.records:
            lines.append(_render_record(rec))
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n(evidence pack truncated at cap)"
        pack.truncated = True
    pack.text = text


def _render_record(rec: Any) -> str:
    sid = rec.source.source_id
    if isinstance(rec, PatientContextRecord):
        return f"- [{sid}] patient age_band={rec.age_band} sex={rec.sex or '?'} counts={dict(rec.counts)}"
    if isinstance(rec, EncounterRecord):
        return f"- [{sid}] encounter {_daystr(rec.date)} category={rec.category or '?'} reason={rec.reason or '?'} clinical_visit={str(rec.is_clinical_visit).lower()} provider={rec.provider.username or 'unknown'}"
    if isinstance(rec, NoteRecord):
        fenced = rec.text.replace("\n", " ").replace("<<<", "").replace(">>>", "")
        return f"- [{sid}] note {_daystr(rec.date)} type={rec.note_type or '?'} author={rec.author.username or 'unknown'}{' truncated' if rec.truncated else ''} text=<<<{fenced}>>>"
    if isinstance(rec, ProblemRecord):
        codes = ",".join(c.as_written for c in rec.codes) or "uncoded"
        return f"- [{sid}] problem \"{rec.title}\" codes={codes} status={rec.status} begin={_daystr(rec.begin)} end={_daystr(rec.end)}{' UNDATED' if rec.undated else ''}"
    if isinstance(rec, MedicationRecord):
        flags = (" STATUS_CONFLICT" if rec.status_conflict else "") + (" UNDATED" if rec.undated else "")
        return f"- [{sid}] medication \"{rec.name}\" source={rec.provenance} dose={rec.dose_text or '?'} status={rec.status}(basis={rec.status_basis}) start={_daystr(rec.start)} end={_daystr(rec.end)} prescriber={rec.prescriber.username or 'unknown'} indication={rec.documented_indication or 'none documented'}{flags}"
    if isinstance(rec, AllergyRecord):
        return f"- [{sid}] allergy \"{rec.substance}\" reaction={rec.reaction or 'not documented'} severity={rec.severity or 'not documented'} status={rec.status} begin={_daystr(rec.begin)}{' UNDATED' if rec.undated else ''}"
    if isinstance(rec, LabResultRecord):
        return f"- [{sid}] lab {_daystr(rec.date)} {rec.analyte} ({rec.analyte_code or 'no code'}) value={rec.value_text} unit={rec.unit or 'MISSING'} range={rec.range_text or 'MISSING'} flag={rec.flag} status={rec.result_status or '?'}{' CORRECTED' if rec.corrected else ''} comparable={str(rec.comparable).lower()}"
    return f"- [{sid}] record"


def build_uc01_window(encounters: ToolResponse, today: date) -> tuple[EncounterRecord | None, date | None]:
    ref = choose_reference_encounter([r for r in encounters.records if isinstance(r, EncounterRecord)], today)
    if ref is None:
        return None, None
    day = _day(ref.date)
    return ref, (day + timedelta(days=0)) if day else None
