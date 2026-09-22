"""Validate the file-backed Week 2 release corpus from ADR-0015."""

from __future__ import annotations

import argparse
import ast
import json
from collections import Counter
from dataclasses import asdict, dataclass
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
EXECUTABLE_MODES = {"offline", "live"}
REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ManifestValidation:
    retained_cases: int
    new_golden_cases: int
    golden_cases: int
    total_cases: int
    executable_cases: int
    pending_cases: int
    errors: list[str]


def _existing_cases(cases_dir: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    cases: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for case_path in sorted(cases_dir.glob("*.yaml")):
        payload = yaml.safe_load(case_path.read_text())
        case_id = payload.get("id") if isinstance(payload, dict) else None
        if not isinstance(case_id, str):
            errors.append(f"{case_path.name}: missing case ID")
        elif case_id != case_path.stem:
            errors.append(f"{case_path.name}: filename must match case ID {case_id}")
        elif case_id in cases:
            errors.append(f"duplicate case ID {case_id}")
        else:
            cases[case_id] = payload
    return cases, errors


def _declared_ids(payload: dict[str, Any], key: str, errors: list[str]) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        errors.append(f"{key} must be an array of case IDs")
        return []
    if len(value) != len(set(value)):
        errors.append(f"{key} must contain unique IDs")
    return value


def _validate_public_pytest_node(case_id: str, rubric: str, node_id: str) -> list[str]:
    errors: list[str] = []
    parts = node_id.split("::")
    if len(parts) != 2 or not parts[0].startswith("tests/") or not parts[1].startswith("test_"):
        return [
            f"{case_id}: rubric {rubric} evidence must be a public pytest node ID "
            f"(tests/...::test_...), got {node_id}"
        ]
    test_path = REPO_ROOT / "agent" / parts[0]
    if not test_path.is_file():
        return [f"{case_id}: rubric {rubric} pytest file does not exist: {parts[0]}"]
    try:
        module = ast.parse(test_path.read_text())
    except (OSError, SyntaxError) as exc:
        return [f"{case_id}: rubric {rubric} pytest file cannot be inspected: {exc}"]
    public_tests = {
        node.name
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    }
    if parts[1] not in public_tests:
        errors.append(f"{case_id}: rubric {rubric} pytest node does not exist: {node_id}")
    return errors


def validate_manifest_file(path: Path) -> ManifestValidation:
    raw = yaml.safe_load(path.read_text())
    payload = raw if isinstance(raw, dict) else {}
    errors: list[str] = []
    cases, case_errors = _existing_cases(path.parent / "cases")
    errors.extend(case_errors)

    retained = _declared_ids(payload, "retained_case_ids", errors)
    week2_ids = _declared_ids(payload, "week2_case_ids", errors)
    retained_set = set(retained)
    week2_set = set(week2_ids)
    actual_ids = set(cases)

    overlap = sorted(retained_set & week2_set)
    if overlap:
        errors.append("retained and Week 2 IDs overlap: " + ", ".join(overlap))
    undeclared = sorted(actual_ids - retained_set - week2_set)
    missing_files = sorted((retained_set | week2_set) - actual_ids)
    undeclared_week2 = sorted((actual_ids - retained_set) - week2_set)
    if undeclared:
        errors.append("case files not declared by the manifest: " + ", ".join(undeclared))
    if undeclared_week2:
        errors.append("Week 2 case files not declared: " + ", ".join(undeclared_week2))
    if missing_files:
        errors.append("declared cases missing files: " + ", ".join(missing_files))

    allocation: Counter[str] = Counter()
    non_happy = 0
    executable = 0
    pending = 0
    holdout_areas: set[str] = set()
    new_golden = 0

    for case_id in week2_ids:
        case = cases.get(case_id)
        if case is None:
            continue
        area = case.get("primary_area")
        if area not in ALLOCATION_MINIMUMS:
            errors.append(f"{case_id}: unknown primary area {area}")
        tier = case.get("tier")
        if tier == "golden":
            new_golden += 1
            allocation[area] += 1
        elif tier != "coverage":
            errors.append(f"{case_id}: tier must be golden or coverage")
        variant = case.get("variant")
        if variant not in NON_HAPPY_VARIANTS | {"positive"}:
            errors.append(f"{case_id}: unknown variant {variant}")
        if variant in NON_HAPPY_VARIANTS:
            non_happy += 1

        rubrics = case.get("rubrics")
        if not isinstance(rubrics, list) or not rubrics:
            errors.append(f"{case_id}: applicable rubrics are missing")
        elif len(rubrics) != len(set(rubrics)):
            errors.append(f"{case_id}: applicable rubrics must be unique")
        elif not set(rubrics).issubset(REQUIRED_RUBRICS):
            errors.append(f"{case_id}: unknown required rubric")

        tags = case.get("capability_tags")
        if not isinstance(tags, list) or not tags:
            errors.append(f"{case_id}: capability tags are missing")

        mode = case.get("mode")
        if mode in EXECUTABLE_MODES:
            executable += 1
            if mode == "offline":
                pytest_by_rubric = case.get("pytest_by_rubric")
                if not isinstance(pytest_by_rubric, dict):
                    errors.append(f"{case_id}: offline case has no per-rubric pytest evidence map")
                    pytest_by_rubric = {}
                rubric_names = rubrics if isinstance(rubrics, list) else []
                extra_rubrics = sorted(
                    str(name) for name in pytest_by_rubric if name not in rubric_names
                )
                if extra_rubrics:
                    errors.append(
                        f"{case_id}: pytest evidence maps non-applicable rubrics: "
                        + ", ".join(extra_rubrics)
                    )
                for rubric in rubric_names:
                    node_ids = pytest_by_rubric.get(rubric)
                    if not isinstance(node_ids, list) or not node_ids:
                        errors.append(f"{case_id}: pytest evidence is missing for rubric {rubric}")
                        continue
                    valid_node_ids = [
                        node_id
                        for node_id in node_ids
                        if isinstance(node_id, str) and node_id
                    ]
                    if len(valid_node_ids) != len(set(valid_node_ids)):
                        errors.append(f"{case_id}: rubric {rubric} pytest node IDs must be unique")
                    for node_id in node_ids:
                        if not isinstance(node_id, str) or not node_id:
                            errors.append(f"{case_id}: rubric {rubric} has an invalid pytest node ID")
                            continue
                        errors.extend(_validate_public_pytest_node(case_id, rubric, node_id))
            elif not isinstance(case.get("steps"), list) or not case["steps"]:
                errors.append(f"{case_id}: live case has no steps")
        elif mode == "pending":
            pending += 1
            if not isinstance(case.get("pending_seam"), str) or not case["pending_seam"].strip():
                errors.append(f"{case_id}: pending case must name its unavailable seam")
        else:
            errors.append(f"{case_id}: mode must be offline, live, or pending")

        if case.get("holdout") is True:
            if tier != "coverage":
                errors.append(f"{case_id}: a holdout cannot be golden")
            holdout_areas.add(area)

    for area, minimum in ALLOCATION_MINIMUMS.items():
        if allocation[area] < minimum:
            errors.append(f"{area}: golden allocation {allocation[area]} is below {minimum}")
    if week2_ids and non_happy * 2 < len(week2_ids):
        errors.append("at least half of Week 2 cases must be negative, adversarial, degraded, or boundary")
    if not {"lab_pdf", "guideline_retrieval"}.issubset(holdout_areas):
        errors.append("Week 2 holdouts must include document and retrieval cases")

    existing_golden = sum(
        cases[case_id].get("tier") == "golden"
        for case_id in retained
        if case_id in cases
    )
    total = len(cases)
    golden = existing_golden + new_golden
    if len(retained) != 48:
        errors.append(f"retained Week 1 case count {len(retained)} is not 48")
    if new_golden < 35:
        errors.append("fewer than 35 new golden cases exist")
    if golden < 50:
        errors.append("golden set is below the 50-case floor")
    if total < 83:
        errors.append("release corpus is below the 83-case floor")
    return ManifestValidation(
        retained_cases=len(retained_set & actual_ids),
        new_golden_cases=new_golden,
        golden_cases=golden,
        total_cases=total,
        executable_cases=executable,
        pending_cases=pending,
        errors=errors,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).with_name("week2_manifest.yaml"),
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = validate_manifest_file(args.manifest)
    if args.json:
        print(json.dumps(asdict(result), indent=2))
    else:
        print(
            f"cases={result.total_cases} golden={result.golden_cases} "
            f"retained={result.retained_cases} executable={result.executable_cases} "
            f"pending={result.pending_cases}"
        )
        for error in result.errors:
            print(f"ERROR: {error}")
    return 1 if result.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
