#!/usr/bin/env python3
"""Compare two eval result files (evals/results/*.json): pass/fail changes, scorecard
deltas, and per-case latency deltas. For A/B experiments (model, effort, planning rounds).

    python evals/compare.py evals/results/<baseline>.json evals/results/<candidate>.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _first_attempts(run: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in run["results"]:
        out.setdefault(r["id"], r)
    return out


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)


def main(argv: list[str]) -> int:
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
        lines.append(f"| {g['gate']} | {'PASS' if base.get('passed') else 'FAIL'} ({_fmt(base.get('value'))}) | {'PASS' if g['passed'] else 'FAIL'} ({_fmt(g['value'])}) |")
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
