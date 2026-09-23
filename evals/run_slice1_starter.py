#!/usr/bin/env python3
"""Run the deterministic eight-case Slice 1 release starter gate.

This is intentionally a narrow complement to the existing Week 1 harness:
each case names the stable test seam that proves its Boolean rubric(s), and the
report contains only case IDs, rubric names, test node IDs, and pass/fail
status. It never serializes fixture bytes, extraction values, source IDs, or
pytest output into a CI artifact.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class StarterCase:
    case_id: str
    rubrics: tuple[str, ...]
    node_id: str


CASES = (
    StarterCase("S1-HAPPY-LAB-001", ("schema_valid", "citation_present", "factually_consistent"), "tests/test_intake_extractor.py::test_fixture_path_is_complete_and_citations_are_resolver_authored"),
    StarterCase("S1-WRONG-CONTEXT-001", ("safe_refusal",), "tests/test_intake_extractor.py::test_source_denial_is_raised_before_any_parser_output"),
    StarterCase("S1-PARTIAL-SCAN-001", ("schema_valid", "factually_consistent"), "tests/test_intake_extractor.py::test_partial_document_keeps_independent_valid_fields_visible"),
    StarterCase("S1-DOCUMENT-INJECTION-001", ("schema_valid", "safe_refusal"), "tests/test_intake_extractor.py::test_prompt_like_document_text_cannot_smuggle_a_fabricated_value"),
    StarterCase("S1-MISSING-CITATION-001", ("citation_present", "factually_consistent", "safe_refusal"), "tests/test_intake_extractor.py::test_resolver_withholds_a_missing_citation"),
    StarterCase("S1-ALTERED-EVIDENCE-001", ("citation_present", "factually_consistent", "safe_refusal"), "tests/test_intake_extractor.py::test_resolver_withholds_an_altered_citation"),
    StarterCase("S1-MODEL-OUTAGE-001", ("safe_refusal",), "tests/test_intake_extractor.py::test_fault_or_source_integrity_failure_returns_no_unverified_output"),
    StarterCase("S1-TELEMETRY-PHI-001", ("no_phi_in_logs",), "tests/test_telemetry.py::test_mask_keeps_bounded_document_preview_telemetry_and_rejects_source_content"),
)

REQUIRED_CASE_IDS = frozenset(case.case_id for case in CASES)
ALL_RUBRICS = frozenset({rubric for case in CASES for rubric in case.rubrics})


def run(output: Path) -> int:
    agent_dir = Path(__file__).resolve().parents[1] / "agent"
    results = []
    for case in CASES:
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", case.node_id],
            cwd=agent_dir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        results.append({"case_id": case.case_id, "rubrics": list(case.rubrics), "node_id": case.node_id, "passed": completed.returncode == 0})
    report = {
        "schema_version": "slice1-starter-1",
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "cases": results,
        "rubrics": {rubric: all(result["passed"] for result in results if rubric in result["rubrics"]) for rubric in sorted(ALL_RUBRICS)},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    passed = sum(result["passed"] for result in results)
    print(f"Slice 1 starter gate: {passed}/{len(results)} cases passed; report: {output}")
    return 0 if passed == len(results) and all(report["rubrics"].values()) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="PHI-free JSON report path")
    args = parser.parse_args()
    return run(args.output)


if __name__ == "__main__":
    raise SystemExit(main())
