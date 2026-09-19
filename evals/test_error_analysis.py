"""Offline tests for the error-analysis sampler's pure parts (no network):
what an entry records, that the review tooling still parses it, and how a
sampled conversation picks its follow-up. Run: agent/.venv/bin/python -m pytest evals/test_error_analysis.py"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import error_analysis as E  # noqa: E402

BODY = {
    "status": "complete", "summary": "LDL cholesterol is 162 mg/dL, flagged abnormal, on 2026-08-31.", "summary_basis": "model", "withheld_count": 0,
    "claims": [{"type": "lab_result", "text": "LDL cholesterol 162 mg/dL, flagged abnormal, dated 2026-08-31."}],
    "limitations": [], "evidence": [{"tool": "lab_results", "status": "ok"}], "usage": {"model_calls": 2},
    "suggestions": ["Are there earlier LDL results to compare?", "Which notes mention LDL?"], "correlation_id": "1aeb3a691801fb45.2",
}


def test_an_entry_records_the_summary_basis_the_turn_kind_and_the_trace_ref(tmp_path: Path) -> None:
    lines = E._entry(3, "AF-DQ-A2", "Any red flags in the labs?", BODY, 8123.4, "follow-up to entry 2 (chip)")
    status = next(l for l in lines if l.startswith("Status:"))
    assert status == "Status: `complete` · latency 8123 ms · model calls 2 · summary: model · follow-up to entry 2 (chip) · ref 1aeb3a691801fb45.2"
    journal = tmp_path / "j.md"
    journal.write_text("# Error-analysis journal\n\n" + "\n".join(lines) + "\n")
    (entry,) = E.parse_journal(journal)
    assert (entry.index, entry.patient, entry.question, entry.first_issue, entry.notes) == (3, "AF-DQ-A2", "Any red flags in the labs?", "", "")
    saved = E.write_entry(journal, 3, first_issue="says 'flagged' twice", reviewer="ab")
    assert saved.first_issue == "says 'flagged' twice" and "ref 1aeb3a691801fb45.2" in journal.read_text()


def test_a_replaced_summary_says_why_as_far_as_the_response_shows() -> None:
    assert E._summary_basis({**BODY, "summary_basis": "deterministic", "withheld_count": 2}) == "deterministic (claims withheld)"
    assert E._summary_basis({**BODY, "summary_basis": "deterministic", "limitations": [{"kind": "narrative_unavailable"}]}) == "deterministic (narrative unavailable)"
    assert E._summary_basis({**BODY, "summary_basis": "deterministic"}) == "deterministic (summary gate; the reason is on the trace)"
    assert E._summary_basis({"_error": "ConnectError"}) == "?"


def test_a_follow_up_is_the_first_chip_not_yet_asked_else_a_bank_question() -> None:
    rng = random.Random(7)
    assert E.follow_up_question(BODY, ["Any red flags in the labs?"], rng) == ("Are there earlier LDL results to compare?", "chip")
    assert E.follow_up_question(BODY, ["Are there earlier LDL results to compare?"], rng) == ("Which notes mention LDL?", "chip")
    question, source = E.follow_up_question({"suggestions": []}, ["Any red flags in the labs?"], rng)
    assert source == "bank" and question in E.QUESTION_BANK and question != "Any red flags in the labs?"
