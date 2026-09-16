"""Deterministic claim verification (ADR-0006). Runs after generation and
before rendering, over the model's claims and this turn's retrieved records.
Makes no model call; fails closed on any exception."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable

from .contracts import (
    AllergyRecord,
    Claim,
    ClaimType,
    LabResultRecord,
    MedicationRecord,
    NoteRecord,
    ProblemRecord,
    ToolStatus,
)
from .evidence import EvidencePack, SECTION_OF_TOOL, _day

FORBIDDEN = [
    (r"\brecommend", "advice"),
    (r"\bshould\b", "advice"),
    (r"\bconsider(ing)?\b", "advice"),
    (r"\badvis", "advice"),
    (r"\bdiagnos", "diagnosis"),
    (r"\btreat(s|ed|ment|ing)?\b", "indication_inference"),
    (r"\bbecause\b", "causal"),
    (r"\bdue to\b", "causal"),
    (r"\bcaused\b", "causal"),
    (r"\blikely\b", "inference"),
    (r"\bsuggest", "inference"),
    (r"\bconsistent with\b", "inference"),
    (r"\binteract", "advice"),
    (r"\b(un)?resolved\b", "resolution_claim"),
    (r"\bneeds? to\b", "advice"),
    (r"\bmust\b", "advice"),
    (r"\bdos(e|age|ing) (should|adjust|increase|decrease)", "dosing_advice"),
]

TOOL_OF_SECTION = {v: k for k, v in SECTION_OF_TOOL.items()}


@dataclass
class VerifyResult:
    accepted: list[Claim] = field(default_factory=list)
    rejected: list[dict[str, str]] = field(default_factory=list)
    rules_applied: list[str] = field(default_factory=list)

    @property
    def outcome(self) -> str:
        if self.rejected and self.accepted:
            return "partial"
        if self.rejected:
            return "rejected"
        return "passed"


def _reject(result: VerifyResult, claim: Claim, rule: str, detail: str) -> None:
    result.rejected.append({"claim_id": claim.id, "rule": rule, "detail": detail[:200]})


def _same_day(value: Any, expected: date | None) -> bool:
    if expected is None or not isinstance(value, str):
        return False
    return value[:10] == expected.isoformat()


def _in_window(day: date | None, pack: EvidencePack) -> bool:
    if day is None:
        return False
    return (pack.window_since is None or day >= pack.window_since) and (pack.window_until is None or day <= pack.window_until)


def _analyte_matches(claimed: str, rec: LabResultRecord) -> bool:
    """The pack renders 'Analyte (code)'; accept the name, the name with its code, or the code."""
    c = re.sub(r"\s*\([^)]*\)\s*$", "", claimed).strip().lower()
    name = rec.analyte.strip().lower()
    return bool(c) and (c in name or name in c or (rec.analyte_code or "").lower() == c)


def verify(claims: list[Claim], pack: EvidencePack) -> VerifyResult:
    result = VerifyResult(rules_applied=["source_exists", "type_facts", "window", "lexicon", "absence_requires_retrieval"])
    for claim in claims:
        try:
            _verify_one(claim, pack, result)
        except Exception as exc:  # noqa: BLE001 - fail closed per claim, never display
            _reject(result, claim, "verifier_exception", exc.__class__.__name__)
    return result


def _verify_one(claim: Claim, pack: EvidencePack, result: VerifyResult) -> None:
    for pattern, rule in FORBIDDEN:
        if re.search(pattern, claim.text, re.IGNORECASE):
            _reject(result, claim, "lexicon:" + rule, pattern)
            return
    records = []
    for sid in claim.source_ids:
        rec = pack.records.get(sid)
        if rec is None:
            _reject(result, claim, "source_exists", sid)
            return
        records.append(rec)
    if claim.type is not ClaimType.absence and claim.type is not ClaimType.interpretation and not records:
        _reject(result, claim, "source_exists", "no source ids")
        return
    f = claim.facts
    t = claim.type

    if t is ClaimType.change_event:
        rec = records[0]
        kind = f.get("kind")
        day_map = {
            "added": (ProblemRecord, "begin"), "ended": (ProblemRecord, "end"),
            "started": (MedicationRecord, "start"), "stopped": (MedicationRecord, "end"),
            "resulted": (LabResultRecord, "date"), "noted": (NoteRecord, "date"),
        }
        if kind == "added" and isinstance(rec, AllergyRecord):
            day_map["added"] = (AllergyRecord, "begin")
        if kind not in day_map or not isinstance(rec, day_map[kind][0]):
            _reject(result, claim, "type_facts", f"kind {kind} does not match record type")
            return
        rec_day = _day(getattr(rec, day_map[kind][1]))
        if rec_day is None:
            _reject(result, claim, "window", "undated record cannot be a change event")
            return
        if not _same_day(f.get("date"), rec_day) or not _in_window(rec_day, pack):
            _reject(result, claim, "window", f"date {f.get('date')} vs record {rec_day}")
            return
    elif t is ClaimType.medication_status:
        rec = records[0]
        if not isinstance(rec, MedicationRecord):
            _reject(result, claim, "type_facts", "not a medication record")
            return
        if rec.status_conflict:
            _reject(result, claim, "type_facts", "record has a status conflict; use a conflict claim")
            return
        if str(f.get("status", "")).lower() != rec.status or str(f.get("name", "")).lower() not in rec.name.lower():
            _reject(result, claim, "type_facts", "name or status differs from record")
            return
    elif t is ClaimType.problem_status:
        rec = records[0]
        if not isinstance(rec, ProblemRecord):
            _reject(result, claim, "type_facts", "not a problem record")
            return
        name = str(f.get("name", "")).lower().strip()
        codes = {c.as_written.lower() for c in rec.codes}
        if not name or (name not in rec.title.lower() and name not in codes):
            _reject(result, claim, "type_facts", f"name {f.get('name')!r} is not the record's title {rec.title!r} or one of its codes as written")
            return
        if str(f.get("status", "")).lower() != rec.status:
            _reject(result, claim, "type_facts", f"status {f.get('status')!r} differs from the record's {rec.status!r}")
            return
    elif t is ClaimType.lab_result:
        rec = records[0]
        if not isinstance(rec, LabResultRecord):
            _reject(result, claim, "type_facts", "not a lab record")
            return
        claimed_unit = f.get("unit")
        claimed_unit = None if claimed_unit in (None, "", "MISSING", "missing", "null") else str(claimed_unit)
        mismatch = None
        if str(f.get("value_text", "")).strip() != rec.value_text.strip():
            mismatch = f"value_text {f.get('value_text')!r} differs from the record's {rec.value_text!r}"
        elif claimed_unit != rec.unit:
            mismatch = f"unit {f.get('unit')!r} differs from the record's {rec.unit or 'MISSING'!r}; copy the pack's unit, null when MISSING"
        elif not _same_day(f.get("date"), _day(rec.date)):
            mismatch = f"date {f.get('date')!r} differs from the record's {_day(rec.date)}"
        elif str(f.get("flag", "")) != rec.flag:
            mismatch = f"flag {f.get('flag')!r} differs from the record's {rec.flag!r}"
        elif not _analyte_matches(str(f.get("analyte", "")), rec):
            mismatch = f"analyte {f.get('analyte')!r} is not the record's {rec.analyte!r}"
        if mismatch:
            _reject(result, claim, "type_facts", mismatch)
            return
        if rec.corrected and "correct" not in claim.text.lower():
            _reject(result, claim, "type_facts", "corrected result not stated as corrected")
            return
    elif t is ClaimType.lab_comparison:
        earlier = pack.records.get(str(f.get("earlier_source_id", "")))
        later = pack.records.get(str(f.get("later_source_id", "")))
        if not isinstance(earlier, LabResultRecord) or not isinstance(later, LabResultRecord):
            _reject(result, claim, "type_facts", "comparison sources are not lab records")
            return
        same = (earlier.analyte_code and earlier.analyte_code == later.analyte_code) or earlier.analyte.lower() == later.analyte.lower()
        if not same or not earlier.comparable or not later.comparable or earlier.unit != later.unit:
            _reject(result, claim, "lab_rules", "not same analyte, not numeric, or unit mismatch")
            return
        if (_day(earlier.date) or date.min) > (_day(later.date) or date.min):
            _reject(result, claim, "lab_rules", "earlier is not earlier")
            return
        if _day(earlier.date) is not None and _day(earlier.date) == _day(later.date):
            _reject(result, claim, "lab_rules", "same-day results are not a trend; a corrected result supersedes the earlier value for that date")
            return
        direction = "up" if later.numeric_value > earlier.numeric_value else "down" if later.numeric_value < earlier.numeric_value else "same"  # type: ignore[operator]
        if f.get("direction") != direction:
            _reject(result, claim, "lab_rules", f"direction is {direction}")
            return
    elif t is ClaimType.documented_reference:
        name = str(f.get("medication_name", "")).lower()
        if not name:
            _reject(result, claim, "type_facts", "medication_name missing")
            return
        ok = False
        for rec in records:
            if isinstance(rec, NoteRecord) and name in rec.text.lower():
                ok = True
            elif isinstance(rec, MedicationRecord) and name in rec.name.lower() and (rec.documented_indication or rec.codes):
                ok = True
            elif isinstance(rec, ProblemRecord) and name in claim.text.lower():
                ok = False
        if not ok:
            _reject(result, claim, "type_facts", "no cited record mentions the medication")
            return
        if re.search(r"\bfor\b|\bindicat", claim.text, re.IGNORECASE):
            _reject(result, claim, "lexicon:indication_inference", "documented references say 'mentions', never 'for'")
            return
    elif t is ClaimType.absence:
        section = str(f.get("section", ""))
        tool = TOOL_OF_SECTION.get(section, section)
        status = pack.status_of(tool)
        if status not in (ToolStatus.ok.value, ToolStatus.empty.value):
            _reject(result, claim, "absence_requires_retrieval", f"{tool} status {status}")
            return
        resp = pack.responses[tool]
        state = str(f.get("state", ""))
        if resp.absence_state is not None:
            if state != resp.absence_state.value:
                _reject(result, claim, "type_facts", f"absence state is {resp.absence_state.value}")
                return
        elif resp.records:
            _reject(result, claim, "type_facts", f"{section} has {len(resp.records)} record(s) in the pack; an absence claim is not allowed for it")
            return
        elif state != "no_records_in_window":
            _reject(result, claim, "type_facts", f"absence state for {section} must be no_records_in_window, not {state!r}")
            return
    elif t is ClaimType.conflict:
        has_conflict = any(isinstance(r, MedicationRecord) and r.status_conflict for r in records)
        if not has_conflict and len(records) < 2:
            _reject(result, claim, "type_facts", "a conflict cites a conflicting record or two records")
            return
    elif t is ClaimType.undated:
        if not any(getattr(r, "undated", False) for r in records):
            _reject(result, claim, "type_facts", "no cited record is undated")
            return
    elif t is ClaimType.interpretation:
        pass
    result.accepted.append(claim)


# ---------------------------------------------------------------- summary


NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
MAX_SUMMARY_CHARS = 600
# Judgments about a trajectory or control state are not facts a record carries; the
# verifier checks lab direction on typed claims, prose may not editorialize it.
SUMMARY_FORBIDDEN = [
    (r"\bimprov", "judgment"),
    (r"\bworsen", "judgment"),
    (r"\b(better|worse)\b", "judgment"),
    (r"\b(well[- ])?controlled\b", "judgment"),
    (r"\buncontrolled\b", "judgment"),
    (r"\bstable\b", "judgment"),
    (r"\bnormaliz", "judgment"),
    (r"\bconcern", "judgment"),
]


def verify_summary(summary: str, accepted: list[Claim], rejected: list[dict[str, str]], known_values: Iterable[str] = ()) -> tuple[bool, str]:
    """Whether the model's summary may be shown. The summary is prose, so it
    cannot be checked fact by fact; it is admitted only when (a) every claim
    of the final round verified, so nothing withheld can leak through it,
    (b) it is non-empty and within its cap, (c) it passes the lexicon, and
    (d) every number in it appears in an accepted claim's text or facts, in
    `known_values` (turn facts the agent itself established, such as the
    window date), or is a count no larger than the number of claims.
    Returns (ok, reason)."""
    text = " ".join(summary.split())
    if not text:
        return False, "empty"
    if len(text) > MAX_SUMMARY_CHARS:
        return False, "too_long"
    if rejected:
        return False, "claims_withheld"
    if not accepted:
        return False, "no_verified_claims"
    for pattern, rule in FORBIDDEN + SUMMARY_FORBIDDEN:
        if re.search(pattern, text, re.IGNORECASE):
            return False, "lexicon:" + rule
    grounded = " ".join(
        [c.text for c in accepted] + [str(v) for c in accepted for v in c.facts.model_dump(exclude_none=True).values()] + [str(v) for v in known_values if v]
    )
    known = set(NUMBER_RE.findall(grounded)) | {str(n) for n in range(len(accepted) + 1)}
    for token in NUMBER_RE.findall(text):
        if token not in known:
            return False, f"ungrounded_number:{token}"
    return True, "ok"


_TYPE_PHRASES = {
    ClaimType.change_event: ("change", "changes"),
    ClaimType.lab_result: ("lab result", "lab results"),
    ClaimType.lab_comparison: ("lab comparison", "lab comparisons"),
    ClaimType.medication_status: ("medication status", "medication statuses"),
    ClaimType.problem_status: ("problem status", "problem statuses"),
    ClaimType.documented_reference: ("documented reference", "documented references"),
    ClaimType.absence: ("absence", "absences"),
    ClaimType.conflict: ("conflict", "conflicts"),
    ClaimType.undated: ("undated record", "undated records"),
    ClaimType.interpretation: ("reading", "readings"),
}


def deterministic_summary(accepted: list[Claim], withheld: int, window_since: str | None, narrate_error: str | None) -> str:
    """A summary built only from verified claims and turn state, used when the
    model's summary cannot be shown. Counts, never content."""
    if narrate_error:
        lead = "The narrative service was unavailable, so this answer lists verified chart records only."
    elif not accepted:
        if not withheld:
            return "No statement about this question could be made from the chart sections that were retrievable."
        return f"No statement about this question could be verified against the chart. {withheld} statement(s) were withheld."
    else:
        lead = ""
    counts: dict[ClaimType, int] = {}
    for c in accepted:
        counts[c.type] = counts.get(c.type, 0) + 1
    parts = [f"{n} {_TYPE_PHRASES[t][0 if n == 1 else 1]}" for t, n in counts.items()]
    if len(parts) > 1:
        joined = ", ".join(parts[:-1]) + " and " + parts[-1]
    else:
        joined = parts[0] if parts else "no statements"
    scope = f"since the visit on {window_since}" if window_since else "across the chart"
    body = f"The chart shows {joined} {scope}."
    tail = f" {withheld} statement(s) were withheld because they could not be verified." if withheld else ""
    return " ".join(s for s in (lead, body + tail) if s)


# ---------------------------------------------------------------- suggestions

STARTER_QUESTIONS = [
    "What changed since the last visit?",
    "Which recent abnormal labs still have no later result or documented follow-up?",
    "What does the chart say about why each current medication is on the list?",
]
MAX_SUGGESTION_CHARS = 120


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", " ".join(text.lower().split()))


def filter_suggestions(raw: list[str], asked: list[str]) -> list[str]:
    """Follow-up questions the panel may offer. They assert nothing, so the
    gate is shape and lexicon: a question, short, not already asked, not
    advice, not about anything outside the open chart."""
    out: list[str] = []
    seen = {_norm(q) for q in asked}
    for item in raw:
        text = " ".join(item.split())
        if not text.endswith("?") or len(text) > MAX_SUGGESTION_CHARS or len(text) < 8:
            continue
        if any(re.search(p, text, re.IGNORECASE) for p, _ in FORBIDDEN):
            continue
        if any(re.search(p, text, re.IGNORECASE) for p, _ in SUMMARY_FORBIDDEN):
            continue
        # Questions that ask for management, adherence, targets, or anything outside the chart are not answerable here.
        if re.search(r"\b(other patients?|schedule|appointment|guideline|dos(e|es|ing|age)|prescrib|manag|plan|adher|taking|taken|need|address|target|goal|next step|prompted|cause)", text, re.IGNORECASE):
            continue
        key = _norm(text)
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) == 3:
            break
    return out


def default_suggestions(accepted: list[Claim], asked: list[str]) -> list[str]:
    """Deterministic follow-ups from the verified claims, then the starters not yet asked."""
    candidates: list[str] = []
    types = {c.type for c in accepted}
    if ClaimType.lab_result in types or ClaimType.change_event in types:
        candidates.append("Which of these lab results are flagged abnormal?")
    if ClaimType.conflict in types:
        candidates.append("Was the conflicting medication change documented in a note?")
    if ClaimType.change_event in types:
        candidates.append("What does the chart say about the newest problem?")
    candidates.extend(STARTER_QUESTIONS)
    return filter_suggestions(candidates, asked)
