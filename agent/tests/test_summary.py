"""The summary gate and its fallback (ADR-0006 decision 7). `verify_summary`
decides whether the model's prose may be shown; `deterministic_summary` writes
what is shown when it may not. The gate grounds dates as dates and numbers in
canonical form, so a format difference is not a rejection and a wrong month is."""

from __future__ import annotations

import pytest

from app.contracts import Claim, ClaimType
from app.verifier import MAX_SUMMARY_CHARS, deterministic_summary, verify_summary


def claim(n: int, type_: ClaimType, text: str, **facts: str) -> Claim:
    return Claim(id=f"c{n}", type=type_, text=text, facts=facts, source_ids=[])


A1C = claim(1, ClaimType.lab_result, "Hemoglobin A1c 8.4 % on 2026-08-20, flagged abnormal.", analyte="Hemoglobin A1c", value_text="8.4", unit="%", date="2026-08-20", flag="abnormal")
LISINOPRIL = claim(2, ClaimType.change_event, "Lisinopril 10 mg tablet started 2026-09-03.", section="medications", kind="started", date="2026-09-03")
CLAIMS = [A1C, LISINOPRIL]


@pytest.mark.parametrize(
    "summary",
    [
        "Lisinopril 10 mg was started on 2026-09-03 and the A1c was 8.4 % on 2026-08-20.",
        "Lisinopril was started on September 3, 2026.",
        "Lisinopril was started on Sept 3.",
        "Lisinopril was started on 3 September 2026.",
        "Lisinopril was started on the 3rd of September.",
        "Lisinopril was started on 9/3/2026.",
        "Lisinopril was started in September 2026 and the A1c was resulted in August 2026.",
        "The A1c was 8.40 % in 2026.",  # a trailing zero and a bare year are the same facts
        "There are 2 verified statements since the visit on 2026-06-17.",  # a count of claims and the window date
    ],
)
def test_a_summary_that_restates_the_claims_is_shown_however_it_writes_dates_and_numbers(summary: str) -> None:
    assert verify_summary(summary, CLAIMS, [], known_values=["2026-06-17"]) == (True, "ok")


@pytest.mark.parametrize(
    ("summary", "reason"),
    [
        ("Lisinopril was started on October 3, 2026.", "ungrounded_date:October 3, 2026"),  # right digits, wrong month
        ("Lisinopril was started on 2026-09-04.", "ungrounded_date:2026-09-04"),
        ("Lisinopril was started in July 2026.", "ungrounded_date:July 2026"),
        ("Lisinopril was started on September 3, 2025.", "ungrounded_date:September 3, 2025"),
        ("The A1c rose from 7.9 to 8.4 %.", "ungrounded_number:7.9"),
        ("Lisinopril 20 mg was started.", "ungrounded_number:20"),
        # The digits of a claim's date are not loose numbers: "09" and "03" do not make 9 or 3 a fact.
        ("There are 9 new results.", "ungrounded_number:9"),
        ("There are 3 new results.", "ungrounded_number:3"),
    ],
)
def test_a_date_or_number_no_claim_carries_replaces_the_summary(summary: str, reason: str) -> None:
    assert verify_summary(summary, CLAIMS, [], known_values=["2026-06-17"]) == (False, reason)


def test_number_forms_are_compared_canonically() -> None:
    platelets = claim(1, ClaimType.lab_result, "Platelet count 1200 on 2026-08-20.", analyte="Platelet count", value_text="1200", date="2026-08-20")
    assert verify_summary("The platelet count was 1,200.", [platelets], [])[0] is True
    potassium = claim(1, ClaimType.lab_result, "Potassium 05.10 mmol/L on 2026-08-20.", analyte="Potassium", value_text="05.10", date="2026-08-20")
    assert verify_summary("Potassium was 5.1 mmol/L.", [potassium], [])[0] is True
    assert verify_summary("Potassium was 5.2 mmol/L.", [potassium], []) == (False, "ungrounded_number:5.2")


def test_the_verb_may_is_not_a_month_and_source_ids_do_not_ground_numbers() -> None:
    comparison = claim(1, ClaimType.lab_comparison, "Hemoglobin A1c went down between the two results.", analyte="Hemoglobin A1c", earlier_source_id="openemr:procedure_result:9000004:a2c1165c", later_source_id="openemr:procedure_result:9000007:a2c1165c", direction="down")
    # "may 1" is not a date, and the 1 is a count no larger than the number of claims.
    assert verify_summary("The chart may 1 day carry an earlier result.", [comparison], [])[0] is True
    assert verify_summary("The A1c fell by 9000004 points.", [comparison], []) == (False, "ungrounded_number:9000004")


def test_the_other_gates_are_unchanged() -> None:
    assert verify_summary("", CLAIMS, []) == (False, "empty")
    assert verify_summary("x" * (MAX_SUMMARY_CHARS + 1), CLAIMS, []) == (False, "too_long")
    assert verify_summary("Lisinopril was started.", CLAIMS, [{"claim_id": "c3", "rule": "type_facts", "detail": ""}]) == (False, "claims_withheld")
    assert verify_summary("Lisinopril was started.", [], []) == (False, "no_verified_claims")
    assert verify_summary("The A1c is improving.", CLAIMS, []) == (False, "lexicon:judgment")
    assert verify_summary("Lisinopril was started because of the A1c.", CLAIMS, []) == (False, "lexicon:causal")


def test_the_fallback_summary_restates_the_first_verified_claims_word_for_word() -> None:
    amlodipine = claim(3, ClaimType.conflict, "Amlodipine is active on the medication list and stopped in prescriptions", kind="status_conflict")
    note = claim(4, ClaimType.change_event, "Progress note documented on 2026-09-03.", section="notes", kind="noted", date="2026-09-03")
    text = deterministic_summary([A1C, LISINOPRIL, amlodipine, note], 0, "2026-06-17", None)
    assert text == (
        "Since the visit on 2026-06-17: Hemoglobin A1c 8.4 % on 2026-08-20, flagged abnormal. Lisinopril 10 mg tablet started 2026-09-03. "
        "Amlodipine is active on the medication list and stopped in prescriptions. 1 more verified statement follows."
    )
    assert deterministic_summary([A1C], 2, None, None) == "Hemoglobin A1c 8.4 % on 2026-08-20, flagged abnormal. 2 statement(s) were withheld because they could not be verified."
    assert deterministic_summary([A1C], 0, None, "timeout").startswith("The narrative service was unavailable, so this answer lists verified chart records only. Hemoglobin A1c")


def test_the_fallback_summary_never_quotes_wording_the_summary_lexicon_refuses() -> None:
    """A claim may quote a note ('stable angina'); the summary lexicon bans the
    word, so that claim is counted, not quoted. With nothing quotable the count
    sentence is what is left."""
    quoted = claim(1, ClaimType.documented_reference, "Note mentions stable angina.", medication_name="nitroglycerin", mention="stable angina")
    text = deterministic_summary([quoted, LISINOPRIL], 0, None, None)
    assert "stable" not in text and text == "Lisinopril 10 mg tablet started 2026-09-03. 1 more verified statement follows."
    assert deterministic_summary([quoted], 0, None, None) == "The chart shows 1 documented reference across the chart."


def test_the_fallback_summary_fits_the_response_contract() -> None:
    long_claims = [claim(n, ClaimType.change_event, ("Progress note documented. " * 16).strip()[:400], section="notes", kind="noted", date="2026-09-03") for n in range(1, 5)]
    for narrate_error, withheld in ((None, 0), ("timeout", 0), (None, 7)):
        text = deterministic_summary(long_claims, withheld, "2026-06-17", narrate_error)
        assert 0 < len(text) <= MAX_SUMMARY_CHARS, len(text)


def test_the_fallback_summary_says_so_when_there_is_nothing_to_restate() -> None:
    assert deterministic_summary([], 0, None, None) == "No statement about this question could be made from the chart sections that were retrievable."
    assert deterministic_summary([], 2, None, None) == "No statement about this question could be verified against the chart. 2 statement(s) were withheld."
    assert deterministic_summary([], 0, None, "timeout") == "The narrative service was unavailable, so no answer could be written for this question."
