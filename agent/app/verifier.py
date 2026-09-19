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
    # Paraphrases of the patterns above that carry the same advice/inference meaning without the
    # literal keyword (2026-09-16 eval hardening: a model can satisfy "don't say 'should'" by
    # rewording rather than by not giving advice, so the lexicon must catch the meaning, not the word).
    (r"\b(wise|prudent|advisable|worthwhile) to\b", "advice"),
    (r"\b(might|may|could) (want|wish|need) to\b", "advice"),
    (r"\bworth (considering|discussing|raising|reviewing) with\b", "advice"),
    (r"\bwould be (a good idea|beneficial|helpful|wise|prudent)\b", "advice"),
    (r"\bgood idea to\b", "advice"),
    (r"\bmight (help|be helpful)\b", "advice"),
    (r"\bpoints? to(ward)?\b", "inference"),
    (r"\bindicative of\b", "inference"),
    (r"\bappears? to (be|show|indicate)\b", "inference"),
    (r"\bmay (explain|indicate|reflect)\b", "inference"),
]

# The claim lexicon in plain words, for the prompt (`agent/app/model.py`): a model cannot avoid
# a filter it is not told about, and every rejection costs a repair call. The prompt states the
# words on top of its rules, not instead of them. `tests/test_summary.py` holds these lists to
# the patterns in both directions; the summary's own list follows `SUMMARY_FORBIDDEN` below.
FORBIDDEN_PLAIN = (
    "recommend", "should", "consider", "advise", "diagnose", "diagnosis", "treat", "treatment",
    "because", "due to", "caused", "likely", "suggest", "consistent with", "interact",
    "resolved", "unresolved", "need to", "must", "dose increase", "dose decrease", "dose adjust",
    "wise to", "prudent to", "advisable to", "worthwhile to", "may want to", "might need to",
    "worth discussing with", "would be helpful", "good idea to", "might help", "points to",
    "indicative of", "appears to be", "may indicate", "may explain", "may reflect",
)

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

# Dates are grounded as dates, not as loose digits: "September 3, 2026" and "2026-09-03" are
# the same fact, and "October 3, 2026" is not, which a digit-by-digit check cannot tell apart.
_MONTH = r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
_MONTH_NUMBER = {name: i + 1 for i, name in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
# (pattern, group order). Month names are matched case-sensitively so the verb "may" is not a month.
_DATE_FORMS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"), "ymd"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "mdy"),
    (re.compile(rf"\b{_MONTH}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?(?!\d)"), "Mdy"),
    (re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH}\.?(?:,?\s+(\d{{4}}))?(?!\d)"), "dMy"),
    (re.compile(rf"\b{_MONTH}\.?,?\s+(\d{{4}})\b"), "My"),
]
_DatePart = tuple[int | None, int | None, int | None]  # (year, month, day); None where the text gave none


def _split_dates(text: str) -> tuple[list[tuple[str, _DatePart]], str]:
    """The date mentions in `text` as (matched text, (year, month, day)), and the
    text with those mentions blanked so their digits are not read again as numbers.
    A match whose month or day is out of range is not a date and is left in place."""
    found: list[tuple[str, _DatePart]] = []
    for pattern, order in _DATE_FORMS:
        def blank(match: re.Match[str], order: str = order) -> str:
            parts: dict[str, int | None] = {"y": None, "m": None, "d": None}
            for key, group in zip(order, match.groups()):
                if key == "M":
                    parts["m"] = _MONTH_NUMBER[group[:3].lower()]
                elif group is not None:
                    parts[key] = int(group)
            month, day = parts["m"], parts["d"]
            if month is None or not 1 <= month <= 12 or (day is not None and not 1 <= day <= 31):
                return match.group(0)
            found.append((match.group(0), (parts["y"], month, day)))
            return " "

        text = pattern.sub(blank, text)
    return found, text


def _date_grounded(mention: _DatePart, grounded: set[tuple[int, int, int]]) -> bool:
    """A date is grounded when a claim carries that day; one written without its
    year or without its day is grounded by any claim date that agrees on the rest."""
    year, month, day = mention
    return any((year is None or year == y) and month == m and (day is None or day == d) for y, m, d in grounded)


def _norm_number(token: str) -> str:
    """Canonical form, so a format difference is not read as a different number:
    '1,200' is '1200', '03' is '3', '8.40' is '8.4'. A comma is a thousands
    separator only when exactly three digits follow it; otherwise a decimal mark."""
    whole, sep, frac = token.partition(",") if "," in token else token.partition(".")
    if sep == "," and len(frac) == 3:
        whole, frac = whole + frac, ""
    whole = whole.lstrip("0") or "0"
    frac = frac.rstrip("0")
    return f"{whole}.{frac}" if frac else whole


# Source ids are citations, not facts a sentence restates; their digits must not ground a number.
_UNGROUNDING_FACTS = frozenset({"earlier_source_id", "later_source_id"})
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
SUMMARY_FORBIDDEN_PLAIN = ("improve", "worsen", "better", "worse", "controlled", "uncontrolled", "stable", "normalize", "concern")


def verify_summary(summary: str, accepted: list[Claim], rejected: list[dict[str, str]], known_values: Iterable[str] = ()) -> tuple[bool, str]:
    """Whether the model's summary may be shown. The summary is prose, so it
    cannot be checked fact by fact; it is admitted only when (a) every claim
    of the final round verified, so nothing withheld can leak through it,
    (b) it is non-empty and within its cap, (c) it passes the lexicon, and
    (d) every date in it is a date an accepted claim carries (in any written
    form), and every other number appears in an accepted claim's text or
    facts, in `known_values` (turn facts the agent itself established, such as
    the window date), or is a count no larger than the number of claims.
    Numbers are compared in canonical form, so '8.40' matches '8.4'.
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
        [c.text for c in accepted]
        + [str(v) for c in accepted for k, v in c.facts.model_dump(exclude_none=True).items() if k not in _UNGROUNDING_FACTS]
        + [str(v) for v in known_values if v]
    )
    grounded_mentions, grounded_rest = _split_dates(grounded)
    grounded_dates = {(y, m, d) for _, (y, m, d) in grounded_mentions if y is not None and m is not None and d is not None}
    mentions, rest = _split_dates(text)
    for written, mention in mentions:
        if not _date_grounded(mention, grounded_dates):
            return False, f"ungrounded_date:{written}"
    known = (
        {_norm_number(n) for n in NUMBER_RE.findall(grounded_rest)}
        | {str(n) for n in range(len(accepted) + 1)}
        | {str(y) for y, _, _ in grounded_dates}
    )
    for token in NUMBER_RE.findall(rest):
        if _norm_number(token) not in known:
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


FALLBACK_SUMMARY_CLAIMS = 3


def _count_sentence(accepted: list[Claim], window_since: str | None) -> str:
    counts: dict[ClaimType, int] = {}
    for c in accepted:
        counts[c.type] = counts.get(c.type, 0) + 1
    parts = [f"{n} {_TYPE_PHRASES[t][0 if n == 1 else 1]}" for t, n in counts.items()]
    joined = ", ".join(parts[:-1]) + " and " + parts[-1] if len(parts) > 1 else parts[0]
    scope = f"since the visit on {window_since}" if window_since else "across the chart"
    return f"The chart shows {joined} {scope}."


def _as_sentence(text: str) -> str:
    text = " ".join(text.split())
    return text if text.endswith((".", "!", "?")) else text + "."


def deterministic_summary(accepted: list[Claim], withheld: int, window_since: str | None, narrate_error: str | None) -> str:
    """The summary shown when the model's cannot be: the first verified claims,
    word for word. A count of claim types ("1 change and 2 lab results") told
    the physician nothing, and the claim texts are already verified and already
    on screen in the statement list, so restating them adds no unverified
    content. A claim whose wording would not pass the summary lexicon is
    counted, not quoted; if none can be quoted the count sentence is used."""
    if not accepted:
        if narrate_error:
            return "The narrative service was unavailable, so no answer could be written for this question."
        if not withheld:
            return "No statement about this question could be made from the chart sections that were retrievable."
        return f"No statement about this question could be verified against the chart. {withheld} statement(s) were withheld."
    lead = "The narrative service was unavailable, so this answer lists verified chart records only." if narrate_error else ""
    tail = f" {withheld} statement(s) were withheld because they could not be verified." if withheld else ""
    scope = f"Since the visit on {window_since}: " if window_since else ""
    # The response contract caps the summary; a claim may be as long as 400 characters.
    budget = MAX_SUMMARY_CHARS - len(lead) - len(tail) - len(scope) - 48  # 48: the "N more ... follow." sentence and joining spaces
    shown: list[str] = []
    for claim in accepted:
        if len(shown) == FALLBACK_SUMMARY_CLAIMS:
            break
        if any(re.search(p, claim.text, re.IGNORECASE) for p, _ in FORBIDDEN + SUMMARY_FORBIDDEN):
            continue
        sentence = _as_sentence(claim.text)
        if sum(len(s) + 1 for s in shown) + len(sentence) > budget:
            break
        shown.append(sentence)
    if shown:
        body = scope + " ".join(shown)
        more = len(accepted) - len(shown)
        if more:
            body += f" {more} more verified statement{'s follow' if more > 1 else ' follows'}."
    else:
        body = _count_sentence(accepted, window_since)
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
