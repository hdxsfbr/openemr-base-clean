"""The model-facing parser (app.model_output): one malformed claim costs that
claim, not the turn. Each shape here is one a model has produced or plausibly
will; before 2026-09-19 any of them failed validation of the whole output, so
the good claims and the summary were discarded and the turn paid for a second
model call or fell back to 'narrative unavailable'."""

from __future__ import annotations

import json

from app.contracts import ClaimType
from app.model import parse_model_json
from app.model_output import model_summary, to_claims

SOURCE = "openemr:procedure_result:9000004:a2bfa267-ed5e-44b1-af3d-379c7f90fcbe"
GOOD = {"type": "lab_result", "text": "LDL cholesterol 162 mg/dL, flagged abnormal, dated 2026-08-31.", "source_ids": [SOURCE], "facts": {"analyte": "LDL cholesterol", "value_text": "162", "unit": "mg/dL", "date": "2026-08-31", "flag": "abnormal"}}


def parse(claims: list, **extra: object):
    output = parse_model_json(json.dumps({"claims": claims, "summary": "One LDL result, 162 mg/dL.", "suggestions": ["Which notes mention LDL?"], **extra}))
    assert output is not None, "the whole output was refused"
    return output


def test_an_interpretation_written_with_reading_beside_facts_keeps_its_text_and_the_turn() -> None:
    """Recorded 2026-09-19 (claude-sonnet-5, 'Are there earlier LDL results to
    compare?'): the second claim had `reading` at claim level and no `text`."""
    reading = "Only one LDL cholesterol result appears in the chart, so no earlier LDL value is available for comparison."
    output = parse([GOOD, {"type": "interpretation", "reading": reading, "source_ids": [SOURCE], "facts": {}}])
    claims, dropped = to_claims(output)
    assert [c.type for c in claims] == [ClaimType.lab_result, ClaimType.interpretation] and dropped == []
    assert claims[1].text == reading and claims[1].facts.reading == reading
    assert model_summary(output) == "One LDL result, 162 mg/dL."


def test_a_claim_the_contract_cannot_use_is_dropped_and_the_rest_survive() -> None:
    output = parse([
        GOOD,
        {"type": "prognosis", "text": "Outlook is good.", "source_ids": [SOURCE]},  # not a claim type
        {"type": "lab_result", "source_ids": [SOURCE], "facts": {}},  # no text
        "not an object",
        {"type": "lab_result", "text": "A1c 6.8 %.", "source_ids": None, "facts": None},  # nulls where containers belong
        {"type": "lab_result", "text": "A1c 6.8 %.", "source_ids": [SOURCE, 7], "facts": {"value_text": 6.8, "unit": "%"}},  # a number where a string belongs
    ])
    claims, dropped = to_claims(output)
    assert [c.text for c in claims] == [GOOD["text"], "A1c 6.8 %.", "A1c 6.8 %."]
    assert claims[2].facts.value_text == "6.8" and claims[2].source_ids == [SOURCE] and claims[1].source_ids == []
    assert [d["detail"] for d in dropped] == ["unknown type", "empty text"]


def test_summary_and_suggestions_of_the_wrong_type_are_ignored_not_fatal() -> None:
    output = parse([GOOD], summary=["a", "list"], suggestions="Which notes mention LDL?")
    assert model_summary(output) == "" and output.suggestions is None and len(to_claims(output)[0]) == 1


def test_an_overlong_summary_is_cut_at_a_sentence_not_mid_word() -> None:
    sentence = "Hemoglobin A1c is 6.8 %, flagged abnormal, on 2026-08-31. "
    output = parse([GOOD], summary=sentence * 15)
    text = model_summary(output)
    assert len(text) <= 600 and text.endswith("2026-08-31.") and text == (sentence * 10).strip()


def test_text_that_is_not_json_is_still_refused() -> None:
    assert parse_model_json("I could not find any records.") is None
    assert parse_model_json('{"claims": [') is None
