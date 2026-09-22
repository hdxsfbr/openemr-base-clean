from __future__ import annotations

from run_slice1_starter import ALL_RUBRICS, CASES, REQUIRED_CASE_IDS


def test_starter_manifest_is_exactly_eight_cases_with_all_required_rubrics() -> None:
    assert len(CASES) == 8
    assert len(REQUIRED_CASE_IDS) == 8
    assert ALL_RUBRICS == {"schema_valid", "citation_present", "factually_consistent", "safe_refusal", "no_phi_in_logs"}
    assert all(case.rubrics for case in CASES)
