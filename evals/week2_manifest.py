"""Validate the additive Week 2 release-corpus plan from ADR-0015."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REQUIRED_RUBRICS = {
    "schema_valid",
    "citation_present",
    "factually_consistent",
    "safe_refusal",
    "no_phi_in_logs",
}
ALLOCATION_MINIMUMS = {
    "lab_pdf": 8,
    "intake_form": 8,
    "guideline_retrieval": 5,
    "source_verification": 5,
    "supervisor_handoff": 4,
    "authorization_degradation": 3,
    "telemetry": 2,
}
NON_HAPPY_VARIANTS = {"negative", "adversarial", "degraded", "boundary"}


@dataclass(frozen=True)
class ManifestValidation:
    retained_cases: int
    new_golden_cases: int
    golden_cases: int
    total_cases: int
    errors: list[str]


def _existing_cases(cases_dir: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    cases: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for case_path in sorted(cases_dir.glob("*.yaml")):
        payload = yaml.safe_load(case_path.read_text())
        case_id = payload.get("id") if isinstance(payload, dict) else None
        if not isinstance(case_id, str):
            errors.append(f"{case_path.name}: missing case ID")
        elif case_id in cases:
            errors.append(f"duplicate existing case ID {case_id}")
        else:
            cases[case_id] = payload
    return cases, errors


def validate_manifest_file(path: Path) -> ManifestValidation:
    payload = yaml.safe_load(path.read_text())
    errors: list[str] = []
    existing, existing_errors = _existing_cases(path.parent / "cases")
    errors.extend(existing_errors)
    retained = payload.get("retained_case_ids") if isinstance(payload, dict) else None
    planned = payload.get("planned_cases") if isinstance(payload, dict) else None
    if not isinstance(retained, list):
        retained = []
        errors.append("retained_case_ids must be an array")
    if set(retained) != set(existing):
        missing = sorted(set(existing) - set(retained))
        unexpected = sorted(set(retained) - set(existing))
        if missing:
            errors.append("retained cases missing: " + ", ".join(missing))
        if unexpected:
            errors.append("unknown retained cases: " + ", ".join(unexpected))
    if len(retained) != len(set(retained)):
        errors.append("retained case IDs must be unique")
    if not isinstance(planned, list):
        planned = []
        errors.append("planned_cases must be an array")

    planned_ids: set[str] = set()
    allocation = Counter()
    new_golden = 0
    non_happy = 0
    holdout_areas: set[str] = set()
    for index, case in enumerate(planned, start=1):
        if not isinstance(case, dict):
            errors.append(f"planned case {index} must be an object")
            continue
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id:
            errors.append(f"planned case {index} has no ID")
            continue
        if case_id in planned_ids or case_id in existing:
            errors.append(f"duplicate planned case ID {case_id}")
        planned_ids.add(case_id)
        area = case.get("primary_area")
        if area not in ALLOCATION_MINIMUMS:
            errors.append(f"{case_id}: unknown primary area {area}")
        if case.get("tier") == "golden":
            new_golden += 1
            allocation[area] += 1
        elif case.get("tier") != "coverage":
            errors.append(f"{case_id}: tier must be golden or coverage")
        if case.get("variant") in NON_HAPPY_VARIANTS:
            non_happy += 1
        rubrics = case.get("rubrics")
        if not isinstance(rubrics, list) or not rubrics:
            errors.append(f"{case_id}: applicable rubrics are missing")
        elif not set(rubrics).issubset(REQUIRED_RUBRICS):
            errors.append(f"{case_id}: unknown required rubric")
        tags = case.get("capability_tags")
        if not isinstance(tags, list) or not tags:
            errors.append(f"{case_id}: capability tags are missing")
        if case.get("holdout") is True:
            if case.get("tier") != "coverage":
                errors.append(f"{case_id}: a holdout cannot be golden")
            holdout_areas.add(area)

    for area, minimum in ALLOCATION_MINIMUMS.items():
        if allocation[area] < minimum:
            errors.append(f"{area}: planned golden allocation {allocation[area]} is below {minimum}")
    if planned and non_happy * 2 < len(planned):
        errors.append("at least half of planned cases must be negative, adversarial, degraded, or boundary")
    if not {"lab_pdf", "guideline_retrieval"}.issubset(holdout_areas):
        errors.append("planned holdouts must include document and retrieval cases")

    existing_golden = sum(case.get("tier") == "golden" for case in existing.values())
    total = len(existing) + len(planned_ids)
    golden = existing_golden + new_golden
    if new_golden < 35:
        errors.append("fewer than 35 new golden cases are planned")
    if golden < 50:
        errors.append("golden set is below the 50-case floor")
    if total < 83:
        errors.append("release corpus is below the 83-case floor")
    return ManifestValidation(len(existing), new_golden, golden, total, errors)

