#!/usr/bin/env python3
"""Compare two eval result files (evals/results/*.json): pass/fail changes, scorecard
deltas, and per-case latency deltas. For A/B experiments (model, effort, planning rounds).

    python evals/compare.py evals/results/<baseline>.json evals/results/<candidate>.json
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any


REQUIRED_IDENTITY_KEYS = (
    "manifest_sha256",
    "fixtures_sha256",
    "schema_version",
    "rubric_version",
    "guideline_corpus_sha256",
    "resolver_sha256",
    "runtime_image",
    "model",
    "prompt_sha256",
    "extraction_identity",
    "embedding_identity",
    "reranker_identity",
    "attempt_policy",
)
REQUIRED_RUBRICS = {
    "schema_valid",
    "citation_present",
    "factually_consistent",
    "safe_refusal",
    "no_phi_in_logs",
}


@dataclass(frozen=True)
class ReleaseFailure:
    scope: str
    name: str
    candidate_rate: float
    threshold: float
    regression_pp: float
    reason: str
    failed_case_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReleaseComparison:
    passed: bool
    failures: list[ReleaseFailure] = field(default_factory=list)
    corpus_errors: list[str] = field(default_factory=list)


def _manifest_by_id(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    manifest = report.get("manifest")
    if not isinstance(manifest, list):
        raise ValueError("manifest must be an array")
    by_id: dict[str, dict[str, Any]] = {}
    for item in manifest:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("every manifest entry requires an ID")
        if item["id"] in by_id:
            raise ValueError(f"duplicate manifest case {item['id']}")
        by_id[item["id"]] = item
    return by_id


def _case_results(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    cases = report.get("cases")
    if not isinstance(cases, list):
        raise ValueError("cases must be an array")
    by_id: dict[str, dict[str, Any]] = {}
    for item in cases:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("every case result requires an ID")
        if item["id"] in by_id:
            raise ValueError(f"duplicate case result {item['id']}")
        by_id[item["id"]] = item
    return by_id


def _case_rubric_verdicts(
    case_id: str,
    manifest_entry: dict[str, Any],
    result: dict[str, Any],
) -> tuple[dict[str, bool], list[str]]:
    errors: list[str] = []
    required = manifest_entry.get("rubrics")
    attempts = result.get("attempts")
    if not isinstance(required, list) or not required:
        return {}, [f"{case_id}: applicable rubrics are missing"]
    if not isinstance(attempts, list) or not attempts:
        return {}, [f"{case_id}: required attempts are missing"]
    verdicts: dict[str, bool] = {}
    for rubric in required:
        values: list[bool] = []
        for attempt_index, attempt in enumerate(attempts, start=1):
            rubrics = attempt.get("rubrics") if isinstance(attempt, dict) else None
            value = rubrics.get(rubric) if isinstance(rubrics, dict) else None
            if not isinstance(value, bool):
                errors.append(f"{case_id}: attempt {attempt_index} rubric {rubric} is missing or unmeasured")
                continue
            values.append(value)
        verdicts[rubric] = len(values) == len(attempts) and all(values)
    return verdicts, errors


def evaluate_release_gate(baseline: dict[str, Any], candidate: dict[str, Any]) -> ReleaseComparison:
    """Compare candidate and approved baseline using ADR-0015 Boolean rules."""

    corpus_errors: list[str] = []
    baseline_identity = baseline.get("identity") if isinstance(baseline.get("identity"), dict) else {}
    candidate_identity = candidate.get("identity") if isinstance(candidate.get("identity"), dict) else {}
    for key in REQUIRED_IDENTITY_KEYS:
        if key not in baseline_identity or key not in candidate_identity:
            corpus_errors.append(f"identity {key} is missing")
        elif baseline_identity[key] != candidate_identity[key]:
            corpus_errors.append(f"identity {key} differs")

    try:
        baseline_manifest = _manifest_by_id(baseline)
        candidate_manifest = _manifest_by_id(candidate)
        baseline_cases = _case_results(baseline)
        candidate_cases = _case_results(candidate)
    except ValueError as exc:
        return ReleaseComparison(False, corpus_errors=[*corpus_errors, str(exc)])

    if baseline_manifest != candidate_manifest:
        corpus_errors.append("baseline and candidate manifests differ")
    expected_ids = set(baseline_manifest)
    for label, case_ids in (("baseline", set(baseline_cases)), ("candidate", set(candidate_cases))):
        missing = sorted(expected_ids - case_ids)
        unexpected = sorted(case_ids - expected_ids)
        if missing:
            corpus_errors.append(f"{label} missing cases: {', '.join(missing)}")
        if unexpected:
            corpus_errors.append(f"{label} unexpected cases: {', '.join(unexpected)}")
    if corpus_errors:
        return ReleaseComparison(False, corpus_errors=corpus_errors)

    category_members: dict[str, list[str]] = {}
    rubric_members: dict[str, list[str]] = {}
    baseline_verdicts: dict[str, dict[str, bool]] = {}
    candidate_verdicts: dict[str, dict[str, bool]] = {}
    for case_id, entry in baseline_manifest.items():
        category = entry.get("primary_category")
        if not isinstance(category, str) or not category:
            corpus_errors.append(f"{case_id}: primary category is missing")
            continue
        category_members.setdefault(category, []).append(case_id)
        baseline_verdicts[case_id], base_errors = _case_rubric_verdicts(case_id, entry, baseline_cases[case_id])
        candidate_verdicts[case_id], candidate_errors = _case_rubric_verdicts(case_id, entry, candidate_cases[case_id])
        corpus_errors.extend(base_errors)
        corpus_errors.extend(candidate_errors)
        for rubric in entry["rubrics"]:
            rubric_members.setdefault(rubric, []).append(case_id)
    if corpus_errors:
        return ReleaseComparison(False, corpus_errors=corpus_errors)

    failures: list[ReleaseFailure] = []

    def compare(scope: str, name: str, members: list[str], threshold: Fraction, zero_tolerance: bool) -> None:
        base_passes = sum(all(baseline_verdicts[case_id].values()) if scope == "category" else baseline_verdicts[case_id][name] for case_id in members)
        candidate_passes = sum(all(candidate_verdicts[case_id].values()) if scope == "category" else candidate_verdicts[case_id][name] for case_id in members)
        denominator = len(members)
        if denominator == 0:
            corpus_errors.append(f"{scope} {name} has a zero denominator")
            return
        base_rate = Fraction(base_passes, denominator)
        candidate_rate = Fraction(candidate_passes, denominator)
        regression = base_rate - candidate_rate
        reasons = []
        if candidate_rate < threshold:
            reasons.append("below threshold")
        if regression > Fraction(5, 100):
            reasons.append("regression exceeds five percentage points")
        if zero_tolerance and candidate_passes != denominator:
            reasons.append("zero-tolerance failure")
        if reasons:
            failed_case_ids = tuple(
                case_id
                for case_id in members
                if not (
                    all(candidate_verdicts[case_id].values())
                    if scope == "category"
                    else candidate_verdicts[case_id][name]
                )
            )
            failures.append(
                ReleaseFailure(
                    scope=scope,
                    name=name,
                    candidate_rate=float(candidate_rate),
                    threshold=float(threshold),
                    regression_pp=float(regression),
                    reason="; ".join(reasons),
                    failed_case_ids=failed_case_ids,
                )
            )

    for category, members in sorted(category_members.items()):
        entries = [baseline_manifest[case_id] for case_id in members]
        thresholds = {entry.get("threshold", 0.95) for entry in entries}
        if len(thresholds) != 1:
            corpus_errors.append(f"category {category} has inconsistent thresholds")
            continue
        zero_tolerance = any(bool(entry.get("zero_tolerance")) for entry in entries)
        compare("category", category, members, Fraction(str(next(iter(thresholds)))), zero_tolerance)

    for rubric, members in sorted(rubric_members.items()):
        threshold = Fraction(1) if rubric in REQUIRED_RUBRICS else Fraction(95, 100)
        compare("rubric", rubric, members, threshold, rubric in REQUIRED_RUBRICS)

    return ReleaseComparison(not corpus_errors and not failures, failures=failures, corpus_errors=corpus_errors)


def _first_attempts(run: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in run["results"]:
        out.setdefault(r["id"], r)
    return out


def _state(g: dict[str, Any]) -> str:
    """A gate row's state as the report prints it (PASS, PASS (warn), FAIL, NOT RUN, NOT MEASURED,
    NOT CONFIGURED); older reports without a state field fall back to passed/failed."""
    if not g:
        return "-"
    state = g.get("state") or ("PASS" if g.get("passed") else "FAIL")
    return f"{state} (warn)" if g.get("warn") else state


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)


def main(argv: list[str]) -> int:
    if len(argv) == 4 and argv[1] == "--release":
        baseline, candidate = (json.loads(Path(path).read_text()) for path in argv[2:])
        comparison = evaluate_release_gate(baseline, candidate)
        print("# Release gate comparison")
        print()
        if comparison.corpus_errors:
            print("## Corpus errors")
            print()
            for error in comparison.corpus_errors:
                print(f"- {error}")
        if comparison.failures:
            print("## Blocking regressions")
            print()
            for failure in comparison.failures:
                print(
                    f"- {failure.scope} `{failure.name}`: candidate {failure.candidate_rate:.1%}, "
                    f"threshold {failure.threshold:.1%}, regression {failure.regression_pp:.1%}; {failure.reason}"
                    f"; failed cases: {', '.join(failure.failed_case_ids)}"
                )
        baseline_identity = baseline.get("identity") if isinstance(baseline.get("identity"), dict) else {}
        print(
            "unchanged baseline manifest "
            + str(baseline_identity.get("manifest_sha256", "missing"))
        )
        if comparison.passed:
            print("PASS: candidate is comparable and satisfies every release threshold.")
        else:
            print("FAIL: candidate is not releasable.")
        return 0 if comparison.passed else 1
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    a, b = (json.loads(Path(p).read_text()) for p in argv[1:])
    lines = [f"# Eval comparison", "", f"Baseline `{a['commit']}` {a['timestamp']} ({a.get('label') or a['model']}) vs candidate `{b['commit']}` {b['timestamp']} ({b.get('label') or b['model']}).", ""]
    ra, rb = _first_attempts(a), _first_attempts(b)
    changed = [(cid, ra[cid]["passed"], rb[cid]["passed"]) for cid in sorted(set(ra) & set(rb)) if ra[cid]["passed"] != rb[cid]["passed"]]
    lines += ["## Pass/fail changes", ""]
    lines += [f"- {cid}: {'pass' if pa else 'FAIL'} -> {'pass' if pb else 'FAIL'}" for cid, pa, pb in changed] or ["- none"]
    only_a, only_b = sorted(set(ra) - set(rb)), sorted(set(rb) - set(ra))
    if only_a or only_b:
        lines += ["", f"Cases only in baseline: {', '.join(only_a) or 'none'}; only in candidate: {', '.join(only_b) or 'none'}."]
    lines += ["", "## Gates", "", "| Gate | Baseline | Candidate |", "| --- | --- | --- |"]
    ga = {g["gate"]: g for g in a.get("gates", [])}
    for g in b.get("gates", []):
        base = ga.get(g["gate"], {})
        lines.append(f"| {g['gate']} | {_state(base)} ({_fmt(base.get('value'))}) | {_state(g)} ({_fmt(g['value'])}) |")
    sa, sb = a.get("scorecard", {}), b.get("scorecard", {})
    lines += ["", "## Scorecard", "", "| Measure | Baseline | Candidate | Delta |", "| --- | --- | --- | --- |"]
    for key in ("turns", "claims_per_turn", "zero_claim_turns", "near_miss_rate", "withheld_total", "withheld_rate", "repair_rate", "model_summary_share", "suggestions_per_turn", "starter_suggestion_share", "model_calls_per_turn", "cost_usd_per_turn"):
        va, vb = sa.get(key), sb.get(key)
        delta = (vb - va) if isinstance(va, (int, float)) and isinstance(vb, (int, float)) else ""
        lines.append(f"| {key} | {_fmt(va)} | {_fmt(vb)} | {_fmt(delta) if delta != '' else ''} |")
    for tt in sorted(set(sa.get("latency_ms_by_turn_type", {})) | set(sb.get("latency_ms_by_turn_type", {}))):
        da, db = sa.get("latency_ms_by_turn_type", {}).get(tt, {}), sb.get("latency_ms_by_turn_type", {}).get(tt, {})
        for pk in ("p50", "p95"):
            va, vb = da.get(pk), db.get(pk)
            delta = (vb - va) if isinstance(va, (int, float)) and isinstance(vb, (int, float)) else ""
            lines.append(f"| latency {tt} {pk} ms | {va} | {vb} | {_fmt(delta) if delta != '' else ''} |")
    for pk in ("p50", "p95", "p99"):
        va, vb = sa.get("latency_ms", {}).get(pk), sb.get("latency_ms", {}).get(pk)
        delta = (vb - va) if isinstance(va, (int, float)) and isinstance(vb, (int, float)) else ""
        lines.append(f"| latency all {pk} ms | {va} | {vb} | {_fmt(delta) if delta != '' else ''} |")
    lines += ["", "## Per-case latency (first attempt, ms per turn)", "", "| Case | Baseline | Candidate |", "| --- | --- | --- |"]
    for cid in sorted(set(ra) & set(rb)):
        la, lb = ra[cid].get("latency_ms", []), rb[cid].get("latency_ms", [])
        if la or lb:
            lines.append(f"| {cid} | {', '.join(str(round(x)) for x in la)} | {', '.join(str(round(x)) for x in lb)} |")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
