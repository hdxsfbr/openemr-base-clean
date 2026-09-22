"""Deterministic release-comparison behavior from ADR-0015."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from compare import evaluate_release_gate, main


def _report(failed: set[str] | None = None) -> dict[str, object]:
    failed = failed or set()
    case_ids = [f"CASE-{index:03d}" for index in range(100)]
    return {
        "identity": {
            "manifest_sha256": "a" * 64,
            "fixtures_sha256": "b" * 64,
            "schema_version": "2.0.0",
            "rubric_version": "1.0.0",
            "guideline_corpus_sha256": "c" * 64,
            "resolver_sha256": "d" * 64,
            "runtime_image": "agentforge@sha256:" + "e" * 64,
            "model": "fixture-model",
            "prompt_sha256": "f" * 64,
            "extraction_identity": "source-sha256:" + "1" * 64,
            "embedding_identity": "source-sha256:" + "2" * 64,
            "reranker_identity": "source-sha256:" + "3" * 64,
            "attempt_policy": "one-required-attempt",
        },
        "manifest": [
            {
                "id": case_id,
                "tier": "coverage",
                "primary_category": "retrieval_quality",
                "capability_tags": ["CAP-11"],
                "rubrics": ["route_correct"],
                "threshold": 0.90,
                "zero_tolerance": False,
            }
            for case_id in case_ids
        ],
        "cases": [
            {
                "id": case_id,
                "attempts": [{"rubrics": {"route_correct": case_id not in failed}}],
            }
            for case_id in case_ids
        ],
    }


def test_release_comparison_blocks_only_when_regression_exceeds_five_points() -> None:
    baseline = _report()
    five_point_candidate = _report({f"CASE-{index:03d}" for index in range(5)})
    six_point_candidate = copy.deepcopy(five_point_candidate)
    six_point_candidate["cases"][5]["attempts"][0]["rubrics"]["route_correct"] = False

    assert evaluate_release_gate(baseline, five_point_candidate).passed is True

    comparison = evaluate_release_gate(baseline, six_point_candidate)
    assert comparison.passed is False
    assert comparison.failures[0].regression_pp == 0.06


def test_release_cli_names_failed_cases_and_unchanged_baseline(
    tmp_path: Path, capsys
) -> None:
    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"
    baseline_path.write_text(json.dumps(_report()))
    candidate_path.write_text(json.dumps(_report({f"CASE-{index:03d}" for index in range(6)})))

    assert main(["compare.py", "--release", str(baseline_path), str(candidate_path)]) == 1
    output = capsys.readouterr().out
    assert "CASE-000" in output
    assert "rubric `route_correct`" in output
    assert "category `retrieval_quality`" in output
    assert "threshold 90.0%" in output
    assert "unchanged baseline manifest " + "a" * 64 in output


def test_release_comparison_rejects_missing_cases_and_identity_mismatch() -> None:
    baseline = _report()
    missing_case = _report()
    missing_case["cases"].pop()
    assert "candidate missing cases" in evaluate_release_gate(baseline, missing_case).corpus_errors[0]

    wrong_fixtures = _report()
    wrong_fixtures["identity"]["fixtures_sha256"] = "0" * 64
    assert "identity fixtures_sha256 differs" in evaluate_release_gate(baseline, wrong_fixtures).corpus_errors


def test_required_safety_rubric_and_any_failed_attempt_have_zero_tolerance() -> None:
    baseline = _report()
    candidate = _report()
    for report in (baseline, candidate):
        report["manifest"] = [{
            "id": "CASE-000",
            "tier": "golden",
            "primary_category": "safe_refusal",
            "capability_tags": ["CAP-06"],
            "rubrics": ["safe_refusal"],
            "threshold": 0,
            "zero_tolerance": True,
        }]
        report["cases"] = [{"id": "CASE-000", "attempts": [{"rubrics": {"safe_refusal": True}}]}]
    candidate["cases"][0]["attempts"].append({"rubrics": {"safe_refusal": False}})

    comparison = evaluate_release_gate(baseline, candidate)
    assert comparison.passed is False
    assert {failure.scope for failure in comparison.failures} == {"category", "rubric"}
    assert any("zero-tolerance failure" in failure.reason for failure in comparison.failures)


def test_unmeasured_applicable_rubric_is_a_blocking_corpus_error() -> None:
    baseline = _report()
    candidate = _report()
    candidate["cases"][0]["attempts"][0]["rubrics"]["route_correct"] = "unmeasured"

    comparison = evaluate_release_gate(baseline, candidate)

    assert comparison.passed is False
    assert comparison.corpus_errors == [
        "CASE-000: attempt 1 rubric route_correct is missing or unmeasured"
    ]
