"""The local pre-push comparison traverses the same release comparator."""

from __future__ import annotations

import copy

from local_gate import evaluate_local_gate
from test_compare import _report


def test_local_gate_turns_red_for_a_boolean_mutation_and_green_when_restored() -> None:
    baseline = _report()
    for entry in baseline["manifest"]:
        entry["mode"] = "offline"
        entry["holdout"] = False
    baseline["manifest"][0].update(
        primary_category="safe_refusal",
        rubrics=["safe_refusal"],
        threshold=1.0,
        zero_tolerance=True,
    )
    baseline["cases"][0]["attempts"][0]["rubrics"] = {"safe_refusal": True}
    candidate = copy.deepcopy(baseline)
    candidate["cases"][0]["attempts"][0]["rubrics"]["safe_refusal"] = False

    red = evaluate_local_gate(baseline, candidate)
    candidate["cases"][0]["attempts"][0]["rubrics"]["safe_refusal"] = True
    green = evaluate_local_gate(baseline, candidate)

    assert red.passed is False
    assert red.failures[0].failed_case_ids == ("CASE-000",)
    assert green.passed is True


def test_local_gate_rejects_a_missing_deterministic_case() -> None:
    baseline = _report()
    for entry in baseline["manifest"]:
        entry["mode"] = "offline"
        entry["holdout"] = False
    candidate = copy.deepcopy(baseline)
    candidate["cases"].pop()

    comparison = evaluate_local_gate(baseline, candidate)

    assert comparison.passed is False
    assert "candidate missing cases" in comparison.corpus_errors[0]


def test_local_gate_accepts_a_compact_feedback_baseline() -> None:
    candidate = _report()
    for entry in candidate["manifest"]:
        entry["mode"] = "offline"
        entry["holdout"] = False
    compact = {
        "authority": "local-feedback-only",
        "identity": copy.deepcopy(candidate["identity"]),
        "expected_rubrics": {
            case["id"]: copy.deepcopy(case["attempts"][0]["rubrics"])
            for case in candidate["cases"]
        },
    }

    comparison = evaluate_local_gate(compact, candidate)

    assert comparison.passed is True
