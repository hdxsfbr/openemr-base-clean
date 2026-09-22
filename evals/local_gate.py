#!/usr/bin/env python3
"""Compare the deterministic local subset to its committed feedback baseline.

This is developer feedback only. GitLab's candidate release job remains the
release authority and runs the full corpus, including holdouts.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from compare import ReleaseComparison, evaluate_release_gate


def _offline_ids(report: dict[str, Any]) -> set[str]:
    manifest = report.get("manifest")
    if not isinstance(manifest, list):
        return set()
    return {
        entry["id"]
        for entry in manifest
        if isinstance(entry, dict)
        and isinstance(entry.get("id"), str)
        and entry.get("mode") == "offline"
        and not entry.get("holdout", False)
    }


def _subset(report: dict[str, Any], case_ids: set[str]) -> dict[str, Any]:
    subset = copy.deepcopy(report)
    subset["manifest"] = [
        entry
        for entry in report.get("manifest", [])
        if isinstance(entry, dict) and entry.get("id") in case_ids
    ]
    subset["cases"] = [
        case
        for case in report.get("cases", [])
        if isinstance(case, dict) and case.get("id") in case_ids
    ]
    return subset


def evaluate_local_gate(
    baseline: dict[str, Any], candidate: dict[str, Any]
) -> ReleaseComparison:
    expected_rubrics = baseline.get("expected_rubrics")
    if isinstance(expected_rubrics, dict):
        expected = set(expected_rubrics)
        candidate_offline = _offline_ids(candidate)
        if candidate_offline != expected:
            missing = sorted(expected - candidate_offline)
            unexpected = sorted(candidate_offline - expected)
            details = []
            if missing:
                details.append("missing: " + ", ".join(missing))
            if unexpected:
                details.append("new: " + ", ".join(unexpected))
            return ReleaseComparison(
                False,
                corpus_errors=["local baseline membership differs (" + "; ".join(details) + ")"],
            )
        baseline = {
            "identity": copy.deepcopy(baseline.get("identity", {})),
            "manifest": [
                copy.deepcopy(entry)
                for entry in candidate.get("manifest", [])
                if isinstance(entry, dict) and entry.get("id") in expected
            ],
            "cases": [
                {
                    "id": case_id,
                    "attempts": [{"rubrics": copy.deepcopy(rubrics)}],
                }
                for case_id, rubrics in sorted(expected_rubrics.items())
            ],
        }
    expected = _offline_ids(baseline)
    if not expected:
        return ReleaseComparison(False, corpus_errors=["local baseline has no offline cases"])
    baseline_subset = _subset(baseline, expected)
    candidate_subset = _subset(candidate, expected)
    return evaluate_release_gate(baseline_subset, candidate_subset)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args(argv)
    baseline = json.loads(args.baseline.read_text())
    candidate = json.loads(args.candidate.read_text())
    comparison = evaluate_local_gate(baseline, candidate)

    print("# Local deterministic gate")
    print(
        "Baseline authority: local feedback only; "
        "not protected-branch or deployment evidence."
    )
    if comparison.corpus_errors:
        for error in comparison.corpus_errors:
            print(f"CORPUS ERROR: {error}")
    for failure in comparison.failures:
        print(
            f"FAIL {failure.scope} {failure.name}: "
            f"cases={','.join(failure.failed_case_ids)} "
            f"candidate={failure.candidate_rate:.1%} "
            f"threshold={failure.threshold:.1%} "
            f"regression={failure.regression_pp:.1%} "
            f"reason={failure.reason}"
        )
    print("PASS" if comparison.passed else "FAIL")
    return 0 if comparison.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
