#!/usr/bin/env python3
"""Run the deterministic shared lab-and-intake release gate.

The Slice 1 cases remain in this gate unchanged. Slice 2 adds only the
intake-specific boundaries necessary to prove the same pipeline fails closed.
The artifact contains identifiers, Boolean rubrics, and verdicts only.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from run_slice1_starter import CASES as LAB_CASES
from run_slice1_starter import StarterCase


INTAKE_CASES = (
    StarterCase("S2-HAPPY-INTAKE-001", ("schema_valid", "citation_present", "factually_consistent"), "tests/test_intake_extractor.py::test_intake_fixture_is_strictly_resolved_with_citations_and_preserved_states"),
    StarterCase("S2-PARTIAL-INTAKE-001", ("schema_valid", "factually_consistent", "safe_refusal"), "tests/test_intake_extractor.py::test_intake_partial_result_keeps_valid_fields_and_never_routes_from_document_text"),
    StarterCase("S2-CONFLICTING-STATE-001", ("schema_valid", "factually_consistent"), "tests/test_intake_extractor.py::test_intake_fixture_is_strictly_resolved_with_citations_and_preserved_states"),
    StarterCase("S2-TYPE-MISMATCH-001", ("schema_valid", "safe_refusal"), "tests/test_intake_extractor.py::test_intake_mismatch_or_fault_withholds_every_proposal"),
    StarterCase("S2-DOCUMENT-INJECTION-001", ("schema_valid", "safe_refusal"), "tests/test_intake_extractor.py::test_intake_partial_result_keeps_valid_fields_and_never_routes_from_document_text"),
    StarterCase("S2-WRONG-CONTEXT-001", ("safe_refusal",), "tests/test_intake_extractor.py::test_source_denial_is_raised_before_any_parser_output"),
    StarterCase("S2-CITATION-TAMPER-001", ("citation_present", "factually_consistent", "safe_refusal"), "tests/test_intake_extractor.py::test_intake_resolver_withholds_tampered_citation_components"),
    StarterCase("S2-MODEL-OUTAGE-001", ("safe_refusal",), "tests/test_intake_extractor.py::test_intake_mismatch_or_fault_withholds_every_proposal"),
    StarterCase("S2-TELEMETRY-PHI-001", ("no_phi_in_logs",), "tests/test_telemetry.py::test_mask_keeps_bounded_document_preview_telemetry_and_rejects_source_content"),
)

CASES = LAB_CASES + INTAKE_CASES
ALL_RUBRICS = frozenset(rubric for case in CASES for rubric in case.rubrics)


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
        "schema_version": "slice2-shared-gate-1",
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "cases": results,
        "rubrics": {rubric: all(result["passed"] for result in results if rubric in result["rubrics"]) for rubric in sorted(ALL_RUBRICS)},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    passed = sum(result["passed"] for result in results)
    print(f"Slice 2 shared gate: {passed}/{len(results)} cases passed; report: {output}")
    return 0 if passed == len(results) and all(report["rubrics"].values()) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="PHI-free JSON report path")
    return run(parser.parse_args().output)


if __name__ == "__main__":
    raise SystemExit(main())
