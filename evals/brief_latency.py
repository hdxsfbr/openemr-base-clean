"""Measure what the physician actually waits for, once the brief is prepared at
chart open instead of on a click (ADR-0003 amendment, module 0.5.0).

Precomputation does not make a turn faster. The narration takes what it takes;
what moves is who waits for it. So the number this prints is not turn latency,
which `evals/run.py` already gates, but the wait the physician is left with:

    T_ready  chart open -> the brief is verified and on screen (measured here)
    L        chart open -> the physician opens the drawer (their reading lag)
    W(L)     what they wait for = max(0, T_ready - L)

Against the old flow, where nothing starts until the click and the wait is the
whole turn whatever L is. The crossover is the honest part: at L = 0 the
prepared brief is *slower* by the panel's own setup (session, conversation,
ticket), and it only pays from the moment the physician spends longer than that
looking at the chart -- which the T0 row of USERS.md puts at seconds, not
milliseconds, but which no real session has yet been timed at.

Drives the deployment through the same sequence the panel's `maybeStartBrief()`
fires, timing each step, so the setup cost is measured rather than assumed.

    agent/.venv/bin/python evals/brief_latency.py [--reps 3] [--out <file.md>]

Costs about USD 0.011 per brief (reps x patients turns). Needs the demo
clinician password: --password-file, or DEMO_PASSWORD, default
~/.config/agentforge/demo_user_password.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE = os.environ.get("COPILOT_BASE_URL", "https://openemr-137-184-4-22.sslip.io")
MODULE = "/interface/modules/custom_modules/oe-module-copilot/public"
BRIEF = "What changed since the last visit?"
# The chart mix the live suite uses: the happy path, a conflict chart, and the
# five-year chart that sets p95. Read as pid -> label.
PATIENTS = {900001: "AF-DQ-A2", 900018: "AF-DQ-N", 900023: "AF-HEAVY", 900012: "AF-DQ-I"}
# Reading lags to report W(L) at. Nobody has timed a real one; these bracket it.
LAGS = (0.0, 2.0, 5.0, 10.0, 15.0, 20.0, 30.0)


def pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    vs = sorted(values)
    return round(vs[min(len(vs) - 1, int(round(p * (len(vs) - 1))))], 1)


class Panel:
    """One login, driven exactly as copilot.js drives it."""

    def __init__(self, base: str, user: str, password: str) -> None:
        self.base = base.rstrip("/")
        self.api = self.base + "/copilot-api"
        self.client = httpx.Client(timeout=120, follow_redirects=False)
        r = self.client.post(
            self.base + "/interface/main/main_screen.php?auth=login&site=default",
            data={"new_login_session_management": "1", "languageChoice": "1", "authUser": user, "clearPass": password},
        )
        if r.status_code != 302:
            raise RuntimeError(f"login failed for {user} (HTTP {r.status_code})")

    def open_chart(self, pid: int) -> None:
        """The chart page load. Not timed into T_ready: the browser pays it either
        way, with or without a brief, so it is not part of what the change costs."""
        r = self.client.get(f"{self.base}/interface/patient_file/summary/demographics.php?set_pid={pid}", follow_redirects=True)
        if "copilot-panel" not in r.text:
            raise RuntimeError(f"chart {pid} did not render the panel (HTTP {r.status_code})")

    def brief(self) -> dict:
        """session.php -> resume -> start -> ticket -> turn, timed per step."""
        t0 = time.perf_counter()
        s = self.client.get(f"{self.base}{MODULE}/api/session.php").json()
        t_session = time.perf_counter() - t0
        if not s.get("brief_on_open"):
            return {"skipped": "brief_on_open=false"}
        csrf = s["csrf_token"]

        t = time.perf_counter()
        self.client.post(f"{self.base}{MODULE}/api/conversation.php", json={"action": "resume", "csrf_token": csrf})
        conv = self.client.post(f"{self.base}{MODULE}/api/conversation.php", json={"action": "start", "csrf_token": csrf}).json()["conversation_id"]
        t_conv = time.perf_counter() - t

        t = time.perf_counter()
        ticket = self.client.post(f"{self.base}{MODULE}/api/ticket.php", json={"csrf_token": csrf, "conversation_id": conv}).json()
        t_ticket = time.perf_counter() - t

        t = time.perf_counter()
        r = self.client.post(
            f"{self.api}/v1/conversations/{conv}/turns",
            json={"message": BRIEF, "correlation_id": ticket["correlation_id"], "stream": False},
            headers={"X-Copilot-Token": ticket["token"], "X-Correlation-Id": ticket["correlation_id"]},
        )
        t_turn = time.perf_counter() - t
        d = r.json() if r.status_code == 200 else {}
        usage = d.get("usage") or {}
        return {
            "http": r.status_code,
            "ref": d.get("correlation_id"),
            "setup_s": round(t_session + t_conv + t_ticket, 3),
            "turn_s": round(t_turn, 3),
            "ready_s": round(time.perf_counter() - t0, 3),
            "status": d.get("status"),
            "basis": d.get("summary_basis"),
            "claims": len(d.get("claims") or []),
            "withheld": d.get("withheld_count"),
            "repair": bool((d.get("verification") or {}).get("repair_attempted")),
            "out_tokens": usage.get("output_tokens"),
            "cache_read": usage.get("cache_read_tokens"),
        }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reps", type=int, default=3, help="briefs per patient (default 3)")
    ap.add_argument("--user", default="audit-physician")
    ap.add_argument("--password-file", default=str(Path.home() / ".config" / "agentforge" / "demo_user_password"))
    ap.add_argument("--base-url", default=BASE)
    ap.add_argument("--out", help="write the markdown report here as well as stdout")
    args = ap.parse_args()

    password = os.environ.get("DEMO_PASSWORD") or Path(args.password_file).read_text().strip()
    panel = Panel(args.base_url, args.user, password)

    rows: list[dict] = []
    for rep in range(args.reps):
        for pid, label in PATIENTS.items():
            panel.open_chart(pid)
            row = {"rep": rep + 1, "pid": pid, "patient": label, **panel.brief()}
            rows.append(row)
            print(
                f"  {label:10s} rep{rep + 1}  ready={row.get('ready_s')}s "
                f"(setup {row.get('setup_s')}s + turn {row.get('turn_s')}s)  "
                f"{row.get('status')}/{row.get('basis')} claims={row.get('claims')} repair={row.get('repair')}",
                flush=True,
            )

    done = [r for r in rows if r.get("http") == 200 and r.get("status") in ("complete", "partial")]
    if not done:
        print("no completed briefs; nothing to report", file=sys.stderr)
        return 1
    ready = [r["ready_s"] for r in done]
    setup = [r["setup_s"] for r in done]
    turn = [r["turn_s"] for r in done]

    out: list[str] = []
    w = out.append
    w(f"# Brief-on-open latency ({datetime.now(timezone.utc).strftime('%Y-%m-%dT%H%M%SZ')})")
    w("")
    w(f"`{args.base_url}` as `{args.user}`, {len(done)} completed briefs of {len(rows)} attempted, "
      f"{args.reps} per chart across {', '.join(PATIENTS.values())}.")
    w("")
    w("## What the physician waits for")
    w("")
    w("`T_ready` is chart open to a verified brief on screen. `W(L)` is what is")
    w("left of it once the physician has spent `L` seconds reading the chart")
    w("before opening the drawer: `W(L) = max(0, T_ready - L)`. The old flow")
    w("started nothing until the click, so its wait was the whole turn at every `L`.")
    w("")
    w("| Reading lag L | W(L) p50 | W(L) p95 | Old flow p50 | Old flow p95 |")
    w("| --- | --- | --- | --- | --- |")
    for lag in LAGS:
        waits = [max(0.0, r - lag) for r in ready]
        w(f"| {lag:.0f} s | {pct(waits, 0.5)} s | {pct(waits, 0.95)} s | {pct(turn, 0.5)} s | {pct(turn, 0.95)} s |")
    w("")
    w("## Stages")
    w("")
    w("| | p50 | p95 | max |")
    w("| --- | --- | --- | --- |")
    w(f"| Panel setup (session, conversation, ticket) | {pct(setup, 0.5)} s | {pct(setup, 0.95)} s | {round(max(setup), 3)} s |")
    w(f"| Turn (retrieve, narrate, verify, repair) | {pct(turn, 0.5)} s | {pct(turn, 0.95)} s | {round(max(turn), 1)} s |")
    w(f"| **T_ready** (chart open to brief) | **{pct(ready, 0.5)} s** | **{pct(ready, 0.95)} s** | {round(max(ready), 1)} s |")
    w("")
    w(f"Setup is {round(statistics.mean(setup), 2)} s on average, which is the cost of preparing a brief "
      f"nobody reads, and the lag below which the old click flow was faster.")
    w("")
    w("## Per chart")
    w("")
    w("| Chart | n | T_ready p50 | T_ready p95 | model summary | repairs |")
    w("| --- | --- | --- | --- | --- | --- |")
    for pid, label in PATIENTS.items():
        rs = [r for r in done if r["pid"] == pid]
        if not rs:
            continue
        kept = sum(1 for r in rs if r["basis"] == "model")
        w(f"| {label} | {len(rs)} | {pct([r['ready_s'] for r in rs], 0.5)} s | {pct([r['ready_s'] for r in rs], 0.95)} s "
          f"| {kept}/{len(rs)} | {sum(1 for r in rs if r['repair'])} |")
    w("")
    w("## Rows")
    w("")
    w("| rep | chart | ready s | setup s | turn s | status | basis | claims | withheld | repair | out tok | ref |")
    w("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in rows:
        w(f"| {r['rep']} | {r['patient']} | {r.get('ready_s')} | {r.get('setup_s')} | {r.get('turn_s')} | "
          f"{r.get('status')} | {r.get('basis')} | {r.get('claims')} | {r.get('withheld')} | {r.get('repair')} | "
          f"{r.get('out_tokens')} | `{r.get('ref')}` |")
    w("")
    w("Read as a measurement of one deployment on one afternoon, not a gate: the")
    w("live suite (`evals/run.py`) stays the release gate for turn latency, and")
    w("`L` is a parameter here, not an observation -- no real physician session")
    w("has been timed between chart open and drawer open.")

    report = "\n".join(out)
    print("\n" + report)
    if args.out:
        Path(args.out).write_text(report + "\n")
        Path(args.out).with_suffix(".json").write_text(json.dumps(rows, indent=1) + "\n")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
