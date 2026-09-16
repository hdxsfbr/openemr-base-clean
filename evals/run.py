#!/usr/bin/env python3
"""Clinical Co-Pilot eval runner.

Drives the deployed co-pilot through the same handshake as the panel and the
Bruno collection (login, open chart, session, start, ticket, turn) and checks
each case's deterministic expectations. Offline cases delegate to pytest node
ids in agent/tests so verifier-level invariants share the same report.

    python evals/run.py --base-url https://host --password-file /path/or - [--only CATEGORY] [--case ID]

Results go to evals/results/<UTC date>-<short sha>.json and .md. Never prints
passwords or tokens; case files and results hold no PHI (synthetic cohort).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
CASES_DIR = ROOT / "evals" / "cases"
RESULTS_DIR = ROOT / "evals" / "results"
MODULE_PATH = "/interface/modules/custom_modules/oe-module-copilot/public"
TURN_TIMEOUT = 90.0


@dataclass
class CaseResult:
    id: str
    name: str
    category: str
    mode: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    latency_ms: list[float] = field(default_factory=list)
    usage: dict[str, float] = field(default_factory=dict)
    correlation_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- live driver


class Session:
    """One OpenEMR login; steps run against it in order."""

    def __init__(self, base_url: str, user: str, password: str, cohort: dict[str, int]) -> None:
        self.base = base_url.rstrip("/")
        self.api = self.base + "/copilot-api"
        self.cohort = cohort
        self.client = httpx.Client(timeout=TURN_TIMEOUT, follow_redirects=False)
        r = self.client.post(
            self.base + "/interface/main/main_screen.php?auth=login&site=default",
            data={"new_login_session_management": "1", "languageChoice": "1", "authUser": user, "clearPass": password},
        )
        if r.status_code != 302:
            raise RuntimeError(f"login failed for {user} (HTTP {r.status_code})")
        self.csrf: str | None = None
        self.conversation_id: str | None = None
        self.ticket: dict[str, Any] | None = None
        self.panel_rendered = False

    def open_chart(self, pubpid: str, tolerate_missing_panel: bool = False) -> None:
        pid = self.cohort[pubpid]
        r = self.client.get(f"{self.base}/interface/patient_file/summary/demographics.php?set_pid={pid}", follow_redirects=True)
        self.panel_rendered = r.status_code == 200 and "copilot-panel" in r.text
        if not self.panel_rendered and not tolerate_missing_panel:
            raise RuntimeError(f"chart {pubpid} did not render the panel (HTTP {r.status_code})")
        s = self.client.get(f"{self.base}{MODULE_PATH}/api/session.php")
        self.csrf = s.json().get("csrf_token") if s.status_code == 200 else None

    def start(self) -> httpx.Response:
        r = self.client.post(f"{self.base}{MODULE_PATH}/api/conversation.php", json={"action": "start", "csrf_token": self.csrf})
        if r.status_code == 200:
            self.conversation_id = r.json()["conversation_id"]
        return r

    def mint(self) -> httpx.Response:
        r = self.client.post(f"{self.base}{MODULE_PATH}/api/ticket.php", json={"csrf_token": self.csrf, "conversation_id": self.conversation_id})
        self.ticket = r.json() if r.status_code == 200 else None
        return r

    def turn(self, message: str, fault: str | None = None, tamper: bool = False, body_extra: dict[str, Any] | None = None, ticket_age_seconds: float = 0.0) -> tuple[httpx.Response, float]:
        r = self.mint()
        if r.status_code != 200:
            return r, 0.0
        assert self.ticket is not None
        if ticket_age_seconds:
            time.sleep(ticket_age_seconds)
        token = self.ticket["token"]
        if tamper:
            token = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
        headers = {"X-Copilot-Token": token, "X-Correlation-Id": self.ticket["correlation_id"]}
        if fault:
            headers["X-Copilot-Fault"] = fault
        body: dict[str, Any] = {"message": message, "correlation_id": self.ticket["correlation_id"], "stream": False}
        body.update(body_extra or {})
        t0 = time.perf_counter()
        resp = self.client.post(f"{self.api}/v1/conversations/{self.conversation_id}/turns", json=body, headers=headers)
        return resp, (time.perf_counter() - t0) * 1000

    def history(self) -> httpx.Response:
        r = self.mint()
        if r.status_code != 200:
            return r
        assert self.ticket is not None
        return self.client.get(f"{self.api}/v1/conversations/{self.conversation_id}", headers={"X-Copilot-Token": self.ticket["token"]})

    def close(self) -> None:
        self.client.close()


# ---------------------------------------------------------------- checks


def _as_list(v: Any) -> list[Any]:
    return v if isinstance(v, list) else [v]


def _texts(body: dict[str, Any]) -> str:
    parts = [c.get("text", "") for c in body.get("claims", [])]
    parts.append(body.get("summary", "") or "")
    parts.extend(body.get("suggestions", []) or [])
    parts.extend(l.get("detail", "") for l in body.get("limitations", []))
    return "\n".join(parts)


def check(expect: dict[str, Any], resp: httpx.Response, latency_ms: float) -> list[str]:
    """Return a list of failure strings (empty when the expectation holds)."""
    f: list[str] = []
    try:
        body = resp.json() if resp.content else {}
    except ValueError:
        body = {}
    if "http_status" in expect and resp.status_code not in _as_list(expect["http_status"]):
        f.append(f"http_status {resp.status_code} not in {expect['http_status']}")
    if "code" in expect and body.get("code") not in _as_list(expect["code"]):
        f.append(f"code {body.get('code')} not in {expect['code']}")
    turns = body.get("turns")
    if "turns_max" in expect and isinstance(turns, list) and len(turns) > expect["turns_max"]:
        f.append(f"history has {len(turns)} turns > {expect['turns_max']}")
    if "turns_min" in expect and (not isinstance(turns, list) or len(turns) < expect["turns_min"]):
        f.append(f"history has {len(turns) if isinstance(turns, list) else 'no'} turns < {expect['turns_min']}")
    if "correlation_id" in expect and body.get("correlation_id") != expect["correlation_id"]:
        f.append("body correlation_id does not match the ticket's")
    if "status" in expect and body.get("status") not in _as_list(expect["status"]):
        f.append(f"status {body.get('status')} not in {expect['status']}")
    if "turn_type" in expect and body.get("turn_type") != expect["turn_type"]:
        f.append(f"turn_type {body.get('turn_type')} != {expect['turn_type']}")
    claims = body.get("claims", []) or []
    if "claims_min" in expect and len(claims) < expect["claims_min"]:
        f.append(f"claims {len(claims)} < {expect['claims_min']}")
    if "claims_max" in expect and len(claims) > expect["claims_max"]:
        f.append(f"claims {len(claims)} > {expect['claims_max']}")
    if expect.get("every_claim_cited"):
        for c in claims:
            if c.get("type") not in ("absence", "interpretation") and not c.get("source_ids"):
                f.append(f"claim {c.get('id')} has no source")
    if expect.get("sources_resolve"):
        known = {s["source_id"] for s in body.get("sources", [])}
        for c in claims:
            for sid in c.get("source_ids", []):
                if sid not in known:
                    f.append(f"claim {c.get('id')} cites {sid} which is not in sources[]")
    types = {c.get("type") for c in claims}
    for t in expect.get("claim_types_include", []):
        if t not in types:
            f.append(f"no claim of type {t}")
    for t in expect.get("claim_types_exclude", []):
        if t in types:
            f.append(f"claim of type {t} present")
    for sec in expect.get("no_claims_in_sections", []):
        for c in claims:
            if (c.get("section") or (c.get("facts") or {}).get("section")) == sec:
                f.append(f"claim {c.get('id')} in forbidden section {sec}")
    tables = {s.get("table") for s in body.get("sources", [])}
    for t in expect.get("source_tables_include", []):
        if t not in tables:
            f.append(f"no cited source from table {t}")
    kinds = {l.get("kind") for l in body.get("limitations", [])}
    for k in expect.get("limitations_include", []):
        if k not in kinds:
            f.append(f"no limitation of kind {k}")
    for k in expect.get("limitations_exclude", []):
        if k in kinds:
            f.append(f"limitation of kind {k} present")
    ev = {e.get("tool"): e for e in body.get("evidence", [])}
    for tool, status in (expect.get("evidence_status") or {}).items():
        got = ev.get(tool, {}).get("status")
        if got not in _as_list(status):
            f.append(f"evidence {tool} status {got} not in {status}")
    if "withheld_max" in expect and body.get("withheld_count", 0) > expect["withheld_max"]:
        f.append(f"withheld {body.get('withheld_count')} > {expect['withheld_max']}")
    if "summary_basis" in expect and body.get("summary_basis") not in _as_list(expect["summary_basis"]):
        f.append(f"summary_basis {body.get('summary_basis')} not in {expect['summary_basis']}")
    if expect.get("summary_nonempty") and not (body.get("summary") or "").strip():
        f.append("summary empty")
    if "suggestions_min" in expect and len(body.get("suggestions", []) or []) < expect["suggestions_min"]:
        f.append("too few suggestions")
    if "verification_outcome" in expect and (body.get("verification") or {}).get("outcome") not in _as_list(expect["verification_outcome"]):
        f.append(f"verification outcome {(body.get('verification') or {}).get('outcome')}")
    text = _texts(body)
    for pat in expect.get("text_must_not_match", []):
        if re.search(pat, text, re.IGNORECASE):
            f.append(f"forbidden text matched /{pat}/")
    for pat in expect.get("text_must_match", []):
        if not re.search(pat, text, re.IGNORECASE):
            f.append(f"required text /{pat}/ not found")
    if "latency_ms_max" in expect and latency_ms > expect["latency_ms_max"]:
        f.append(f"latency {latency_ms:.0f} ms > {expect['latency_ms_max']}")
    if expect.get("correlation_header_echo") and resp.headers.get("x-correlation-id", "") == "":
        f.append("no X-Correlation-Id header")
    return f


# ---------------------------------------------------------------- runners


def run_live(case: dict[str, Any], base_url: str, password: str, cohort: dict[str, int]) -> CaseResult:
    result = CaseResult(case["id"], case["name"], case["category"], "live", True)
    session: Session | None = None
    try:
        session = Session(base_url, case.get("user", "audit-physician"), password, cohort)
        for step in case["steps"]:
            kind, spec = next(iter(step.items())) if isinstance(step, dict) else (step, {})
            spec = spec or {}
            if kind == "open_chart":
                if isinstance(spec, str):
                    session.open_chart(spec)
                else:
                    session.open_chart(spec["patient"], spec.get("tolerate_missing_panel", False))
            elif kind == "start":
                r = session.start()
                result.failures += check(spec.get("expect", {"http_status": 200}), r, 0.0)
            elif kind == "ticket":
                r = session.mint()
                result.failures += check(spec.get("expect", {"http_status": 200}), r, 0.0)
            elif kind == "turn":
                r, ms = session.turn(spec["message"], spec.get("fault"), spec.get("tamper", False), spec.get("body_extra"), spec.get("ticket_age_seconds", 0.0))
                result.latency_ms.append(round(ms, 1))
                if r.headers.get("x-correlation-id"):
                    result.correlation_ids.append(r.headers["x-correlation-id"])
                try:
                    usage = (r.json() or {}).get("usage") or {}
                    for k in ("input_tokens", "output_tokens", "cache_read_tokens", "model_calls"):
                        result.usage[k] = result.usage.get(k, 0) + float(usage.get(k, 0))
                except ValueError:
                    pass
                expect = dict(spec.get("expect", {}))
                if expect.pop("correlation_matches_ticket", False) and session.ticket:
                    expect["correlation_id"] = session.ticket["correlation_id"]
                result.failures += check(expect, r, ms)
            elif kind == "history":
                r = session.history()
                result.failures += check(spec.get("expect", {"http_status": 200}), r, 0.0)
            elif kind == "sleep":
                time.sleep(float(spec))
            else:
                result.failures.append(f"unknown step {kind}")
    except Exception as exc:  # noqa: BLE001 - a case must never take the run down
        result.failures.append(f"{exc.__class__.__name__}: {str(exc)[:160]}")
    finally:
        if session:
            session.close()
    result.passed = not result.failures
    return result


def run_offline(case: dict[str, Any]) -> CaseResult:
    result = CaseResult(case["id"], case["name"], case["category"], "offline", True)
    python = ROOT / "agent" / ".venv" / "bin" / "python"
    if not python.exists():
        python = Path(sys.executable)
    node_ids = _as_list(case["pytest"])
    proc = subprocess.run([str(python), "-m", "pytest", "-q", *node_ids], cwd=ROOT / "agent", capture_output=True, text=True)
    if proc.returncode != 0:
        result.failures.append("pytest failed: " + (proc.stdout.strip().splitlines() or ["?"])[-1][:200])
    result.notes = node_ids
    result.passed = not result.failures
    return result


# ---------------------------------------------------------------- reporting


def load_cases(only: str | None, case_id: str | None) -> list[dict[str, Any]]:
    cases = []
    for path in sorted(CASES_DIR.glob("*.yaml")):
        case = yaml.safe_load(path.read_text())
        case["_file"] = path.name
        if only and case["category"] != only:
            continue
        if case_id and case["id"] != case_id:
            continue
        cases.append(case)
    return cases


def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except OSError:
        return "unknown"


def write_report(results: list[CaseResult], meta: dict[str, Any]) -> tuple[Path, Path]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    stem = f"{stamp}-{meta['commit']}"
    by_cat: dict[str, dict[str, int]] = {}
    for r in results:
        c = by_cat.setdefault(r.category, {"passed": 0, "failed": 0})
        c["passed" if r.passed else "failed"] += 1
    latencies = sorted(ms for r in results for ms in r.latency_ms)

    def pct(p: float) -> float | None:
        if not latencies:
            return None
        return round(latencies[min(len(latencies) - 1, int(round(p * (len(latencies) - 1))))], 1)

    tokens = {k: sum(r.usage.get(k, 0) for r in results) for k in ("input_tokens", "output_tokens", "cache_read_tokens", "model_calls")}
    summary = {
        **meta,
        "cases": len(results),
        "passed": sum(r.passed for r in results),
        "failed": sum(not r.passed for r in results),
        "by_category": by_cat,
        "safety_blocking_failures": [r.id for r in results if not r.passed and r.category in ("authorization", "citation", "isolation", "untrusted", "tool_failure", "model_failure")],
        "latency_ms": {"n": len(latencies), "p50": pct(0.5), "p95": pct(0.95), "p99": pct(0.99), "max": latencies[-1] if latencies else None},
        "tokens": tokens,
        "results": [r.__dict__ for r in results],
    }
    json_path = RESULTS_DIR / f"{stem}.json"
    json_path.write_text(json.dumps(summary, indent=2))
    lines = [
        f"# Eval run {stamp}",
        "",
        f"Commit `{meta['commit']}`, environment `{meta['environment']}`, model `{meta['model']}`, cases {len(results)}, passed {summary['passed']}, failed {summary['failed']}.",
        "",
        "| Category | Passed | Failed |",
        "| --- | --- | --- |",
    ]
    lines += [f"| {cat} | {c['passed']} | {c['failed']} |" for cat, c in sorted(by_cat.items())]
    lines += ["", f"Turn latency ms (n={len(latencies)}): p50 {pct(0.5)}, p95 {pct(0.95)}, p99 {pct(0.99)}.", "", "| Case | Mode | Result | Latency ms | Failures |", "| --- | --- | --- | --- | --- |"]
    for r in results:
        lines.append(f"| {r.id} | {r.mode} | {'pass' if r.passed else 'FAIL'} | {', '.join(str(m) for m in r.latency_ms) or ''} | {'; '.join(r.failures)[:300]} |")
    if summary["safety_blocking_failures"]:
        lines += ["", "**Release-blocking failures:** " + ", ".join(summary["safety_blocking_failures"])]
    md_path = RESULTS_DIR / f"{stem}.md"
    md_path.write_text("\n".join(lines) + "\n")
    return json_path, md_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default=os.environ.get("COPILOT_EVAL_BASE_URL", "https://openemr-137-184-4-22.sslip.io"))
    ap.add_argument("--password-file", help="File holding the demo clinician password, or '-' to read DEMO_PASSWORD from the environment", default="-")
    ap.add_argument("--cohort", default=str(ROOT / "evals" / "cases" / "cohort.json"), help="pubpid -> pid map")
    ap.add_argument("--only", help="run one category")
    ap.add_argument("--case", help="run one case id")
    ap.add_argument("--offline-only", action="store_true")
    ap.add_argument("--model", default=os.environ.get("COPILOT_MODEL_ID", "claude-sonnet-5"))
    args = ap.parse_args()

    cases = load_cases(args.only, args.case)
    if not cases:
        print("no cases matched", file=sys.stderr)
        return 2
    cohort = json.loads(Path(args.cohort).read_text())
    password = ""
    if not args.offline_only and any(c["mode"] == "live" for c in cases):
        password = os.environ.get("DEMO_PASSWORD", "") if args.password_file == "-" else Path(args.password_file).read_text().strip()
        if not password:
            print("a demo password is required for live cases (DEMO_PASSWORD or --password-file)", file=sys.stderr)
            return 2

    results: list[CaseResult] = []
    for case in cases:
        if case["mode"] == "offline":
            r = run_offline(case)
        elif args.offline_only:
            continue
        else:
            r = run_live(case, args.base_url, password, cohort)
        results.append(r)
        print(f"{'PASS' if r.passed else 'FAIL'}  {r.id:<28} {r.category:<14} {' '.join(str(m) + 'ms' for m in r.latency_ms)}  {'; '.join(r.failures)[:160]}")

    meta = {
        "commit": git_sha(),
        "environment": args.base_url,
        "model": args.model,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset_version": "af-cohort-v1",
        "runner": "evals/run.py",
    }
    json_path, md_path = write_report(results, meta)
    print(f"\n{sum(r.passed for r in results)}/{len(results)} passed. Report: {md_path.relative_to(ROOT)}")
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
