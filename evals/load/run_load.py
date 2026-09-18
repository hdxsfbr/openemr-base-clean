#!/usr/bin/env python3
"""Load driver for the Clinical Co-Pilot deployment: 1, 10 and 50 virtual clinicians.

Why this exists. The PRD asks for load tests at 10 and 50 concurrent users with
p50/p95/p99 and error rates (docs/REQUIREMENTS_TRACEABILITY.md, "Load tests at 10
and 50 concurrent users"). KEY_METRICS.md measures "complete verified response
latency" through traces and load tests and lets only the load baseline revise the
latency and cost thresholds. The audit (docs/audit/performance.md) infers that
chart opens and co-pilot turns compete for the same Apache prefork workers; this
driver turns that inference into a measurement.

Do not run this against the deployment without the owner's approval: every
model-backed turn spends model budget (docs/FINAL_PUSH_PLAN.md, invariant 5).
Building the driver is MILESTONE M2; running it is M4.

    DEMO_PASSWORD="$(ssh deployer@<droplet-ip> cat /opt/agentforge/secrets/demo_user_password)" \\
      agent/.venv/bin/python evals/load/run_load.py --base-url https://<host> --users 1,10,50 \\
      --metrics-url https://<host>/copilot-api/metrics --label baseline
    agent/.venv/bin/python evals/load/run_load.py --base-url https://<host> --users 10 --fault model
    agent/.venv/bin/python evals/load/run_load.py --base-url https://<host> --users 2 --plan   # no network

The password is read from the environment variable named by --password-env
(default DEMO_PASSWORD). There is no --password flag and never will be: a
password on the command line lands in shell history and process listings.

What one virtual user (VU) does: the handshake of the `Session` class in
evals/run.py (class at :63-129 as of commit 66a6711: `__init__` :66 logs in,
open_chart :82 also fetches session.php, start :91, mint :97, turn :102,
history :121), rewritten on asyncio and httpx.AsyncClient so that N VUs run
concurrently in one process. evals/run.py is not imported; the constants it
shares are copied here and cited.

    login            POST /interface/main/main_screen.php?auth=login&site=default (expects 302)
    chart_open       GET  /interface/patient_file/summary/demographics.php?set_pid=<pid> (panel must render)
    session          GET  <module>/api/session.php (CSRF token)
    start            POST <module>/api/conversation.php {"action": "start"}
    ticket           POST <module>/api/ticket.php (delegation token and correlation id)
    turn (first)     POST /copilot-api/v1/conversations/<id>/turns "What changed since the last visit?"
    ticket           POST <module>/api/ticket.php
    turn (followup)  POST /copilot-api/v1/conversations/<id>/turns "Which of those lab results are flagged abnormal?"
    ticket, history  POST <module>/api/ticket.php, GET /copilot-api/v1/conversations/<id>

VUs alternate between the demo clinicians audit-physician and physician and
round-robin over three charts: AF-DQ-A2 (pid 900001, the UC-01 reference chart),
AF-DQ-N (900018, the note-versus-list conflict chart) and AF-HEAVY (900023, the
five-year chart REG-HEAVY-001 keeps in every eval run). Pids come from
evals/cases/cohort.json; the built-in map is the fallback and is checked against
the file. Synthetic cohort af-cohort-v1 only: no PHI is sent, stored or printed.
Results carry the two demo account names and the per-turn correlation ids
(levels[].vu_records, the join key to Langfuse traces and the agent's
correlation-id log lines); never a ticket token, CSRF value or cookie.

Levels. --users takes one or more levels (default 1,10,50). Each level starts its
VUs spread over --ramp-seconds (default 30), waits for all of them, and reads
--metrics-url before and after, so every counter it reports is a delta for that
level alone. At the levels in --stream-levels (default 1,10) the first turn is
sent with Accept: text/event-stream and the time to the `event: evidence` frame
(TTFE: the moment the panel can show sources) is recorded next to the full turn
time, which for a streamed turn ends at `event: done`. Streamed turns are not
subject to the agent's 45 s wall clock (agent/app/api.py applies
turn_wall_clock_seconds to the JSON path only), so their long tail is bounded by
this driver's 90 s client timeout instead.

--fault model sends `X-Copilot-Fault: model` on every turn. The deployment
honors it (COPILOT_FAULT_INJECTION=1 in infra/digitalocean/runtime/compose.yaml),
so the model call is replaced by the deterministic fallback and the run measures
OpenEMR, the gateway and the agent's own capacity without provider rate limits
or spend. Expect every turn to report status `fallback` in that mode.

Results. Two files in --out-dir (default evals/load/results/): <UTC>-<sha>.json
and <UTC>-<sha>.md, sha from `git rev-parse --short HEAD`.

JSON schema (schema_version 1; every key is always present):

    schema_version    1
    kind              "load"
    commit            short git sha
    timestamp         UTC ISO-8601 of the run start
    label             --label (free text, may be empty)
    base_url          the deployment
    fault             --fault or null
    ramp_seconds      --ramp-seconds
    stream_levels     levels whose first turn was streamed
    users_levels      the levels that ran, in order
    scenarios         {pubpid: pid} as used
    messages          {"first": ..., "followup": ...}
    interrupted       true when Ctrl-C stopped the run; levels[] then holds the completed levels only
    levels[]          one object per level:
      users             VU count
      started_at, finished_at, duration_s
      vus               {"total", "completed", "failed"}
      failed_at         {step: count} for VUs that stopped before the last step
      latency_ms        {step: {n, p50, p95, p99, max}} for login, chart_open, session,
                        start, ticket, turn, turn_first, turn_followup, history, ttfe;
                        every request that received an HTTP response counts, whatever
                        its status; transport failures are errors, not latencies
      by_scenario       {pubpid: {latency_ms: {chart_open, ticket, turn, ttfe}, turns,
                        errors, status_counts, status_share}}
      turns             turn attempts at this level
      errors            {"5xx", "504", "429", "transport", "other", "total", "rate"};
                        5xx excludes 504; rate = total / turns; denials are not errors
      denials           {"turn_http_401_403", "handshake_http_401_403",
                        "metrics_by_reason": copilot_denials_total deltas}
      status_counts     {complete, partial, fallback, failed, denied}; failed also counts
                        every turn without a 200 body (5xx, 504, 429, transport, other)
      status_share      the same as fractions of turns (0.0 when turns == 0)
      server_turns_by_status  copilot_turns_total deltas: the agent's own count
      tool_unavailable  {"calls_total", "total", "by_reason", "by_tool"} from
                        copilot_tool_calls_total deltas. The `reason` label is optional
                        (older builds label only tool and status) and reads as
                        "unlabelled" when absent, so both label sets aggregate
      client_tool_unavailable  evidence entries with status unavailable in turn bodies
      usage             summed input_tokens, output_tokens, cache_read_tokens, model_calls
      step_http         {step: {"<http status>" or "transport": count}}
      metrics           {"before": bool, "after": bool}: whether /metrics was read
      vu_records[]      one entry per VU in start order: {index, user, scenario, completed,
                        failed_at, error, turns: [{type, http_status, error, status, stream,
                        ms, ttfe_ms, correlation_id}]}; error is the step detail (an HTTP
                        status or an exception class name), never a body or a token

Expected failures at 50 users: results to record, not bugs to fix during the
window. The numbers below were checked against the code at commit 66a6711 on
2026-09-17; files WS-AGENT edits in the same milestone (nodes.py, api.py,
model.py) are cited by symbol, the others by line.

  * Capacity arithmetic. The UC-01 first turn fans out six tools through a
    per-turn asyncio.Semaphore(settings.tool_concurrency) with tool_concurrency 6
    (the `sem = asyncio.Semaphore(...)` fan-out in the `retrieve` node of
    agent/app/graph/nodes.py; agent/app/settings.py:19), so 50 first turns in
    flight are up to 300 concurrent gateway requests. Apache in the
    pinned OpenEMR image runs mpm_prefork with MaxRequestWorkers 250
    (docs/audit/architecture.md:265 and :349; the lead spot-check confirms
    prefork, docs/audit/evidence/architecture/lead-spot-check.md:11); infra/
    pins the image and does not change the MPM. Chart opens from the same VUs
    queue on the same workers (docs/audit/performance.md, PERF finding on
    dashboard cost).
  * Likely shape of the failure: `partial` turns, not 5xx. A gateway call that
    waits longer than gateway_timeout_seconds 2.0 (agent/app/settings.py:18,
    used by agent/app/gateway_client.py:39) returns an `unavailable` envelope
    with reason `timeout` (gateway_client.py:48); the turn still renders with a
    limitation and reports status `partial`. Those show up here as
    tool_unavailable.by_reason.timeout and status_counts.partial.
  * 504 is the second shape: the JSON turn path has a 45 s wall clock
    (turn_wall_clock_seconds, agent/app/settings.py:40; the asyncio.wait_for on
    the non-stream path of `post_turn` in agent/app/api.py),
    so queued turns that exceed it return 504 dependency_unavailable and count
    under errors["504"], not errors["5xx"].
  * Provider 429s. The model client retries once on 429/5xx and the
    CircuitBreaker opens for cooldown 60.0 s (agent/app/model.py: the module
    docstring and `class CircuitBreaker`, `cooldown: float = 60.0`).
    While it is open every turn takes the deterministic fallback, so a burst of
    provider limits converts turns to status `fallback` for a minute rather than
    failing them. --fault model measures capacity with that effect removed.
  * The agent's own limiter is per conversation (turns_per_minute 10,
    agent/app/settings.py:44; `_rate_limited` in agent/app/api.py) and this
    scenario sends two turns per conversation, so a 429 counted here did not
    come from that rule.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from collections.abc import AsyncIterator, Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = ROOT / "evals" / "load" / "results"
DEFAULT_COHORT_FILE = ROOT / "evals" / "cases" / "cohort.json"

SCHEMA_VERSION = 1
# Copied from evals/run.py:35-36 (MODULE_PATH, TURN_TIMEOUT); the driver stays standalone.
MODULE_PATH = "/interface/modules/custom_modules/oe-module-copilot/public"
TURN_TIMEOUT = 90.0
METRICS_TIMEOUT = 10.0
LOGIN_PATH = "/interface/main/main_screen.php?auth=login&site=default"
CHART_PATH = "/interface/patient_file/summary/demographics.php"
API_PREFIX = "/copilot-api"

USERS: tuple[str, ...] = ("audit-physician", "physician")
# Fallback pubpid -> pid map; evals/cases/cohort.json is the source of truth (checked in load_cohort).
DEFAULT_SCENARIOS: dict[str, int] = {"AF-DQ-A2": 900001, "AF-DQ-N": 900018, "AF-HEAVY": 900023}
# UC-01 starter (evals/run.py STARTER_QUESTIONS) and the follow-up ISO-FOLLOWUP-CHAIN-001 sends second.
FIRST_MESSAGE = "What changed since the last visit?"
FOLLOWUP_MESSAGE = "Which of those lab results are flagged abnormal?"
DEFAULT_LEVELS = "1,10,50"
DEFAULT_STREAM_LEVELS = "1,10"

STEP_NAMES: tuple[str, ...] = ("login", "chart_open", "session", "start", "ticket", "turn", "turn_first", "turn_followup", "history", "ttfe")
SCENARIO_STEPS: tuple[str, ...] = ("chart_open", "ticket", "turn", "ttfe")
ERROR_BUCKETS: tuple[str, ...] = ("5xx", "504", "429", "transport", "other")
TURN_STATUSES: tuple[str, ...] = ("complete", "partial", "fallback", "failed", "denied")
USAGE_KEYS: tuple[str, ...] = ("input_tokens", "output_tokens", "cache_read_tokens", "model_calls")
TOOL_FAILURE_STATUS = "unavailable"
UNLABELLED_REASON = "unlabelled"

_METRIC_LINE_RE = re.compile(r"^(?P<name>[A-Za-z_:][A-Za-z0-9_:]*)(?:\{(?P<labels>[^}]*)\})?\s+(?P<value>[^\s]+)(?:\s+-?\d+)?$")
_LABEL_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)="((?:[^"\\]|\\.)*)"')


# ---------------------------------------------------------------- samples


@dataclass
class StepSample:
    """One timed request of the handshake (everything but the turn itself)."""

    step: str
    scenario: str
    user: str
    ms: float
    http_status: int | None
    error: str | None = None  # exception class name for transport failures


@dataclass
class TurnSample:
    """One turn attempt: timing, HTTP outcome, and the sanitized body facts the report needs."""

    scenario: str
    user: str
    turn_type: str  # "first" or "followup"
    ms: float
    http_status: int | None
    error: str | None = None
    status: str | None = None  # body status: complete, partial, fallback, failed, denied
    stream: bool = False
    ttfe_ms: float | None = None
    evidence_unavailable: int = 0
    usage: dict[str, float] = field(default_factory=dict)
    correlation_id: str | None = None


@dataclass
class VirtualUserResult:
    index: int
    user: str
    scenario: str
    steps: list[StepSample] = field(default_factory=list)
    turns: list[TurnSample] = field(default_factory=list)
    failed_at: str | None = None
    error: str | None = None

    @property
    def completed(self) -> bool:
        return self.failed_at is None


@dataclass(frozen=True)
class RunConfig:
    base_url: str
    scenarios: dict[str, int]
    fault: str | None
    ramp_seconds: float
    stream_levels: frozenset[int]
    metrics_url: str | None
    pause_seconds: float
    first_message: str = FIRST_MESSAGE
    followup_message: str = FOLLOWUP_MESSAGE


class StepFailure(Exception):
    """A handshake step the scenario cannot continue past (login rejected, panel absent, no ticket)."""

    def __init__(self, step: str, detail: str, sample: StepSample | None = None) -> None:
        super().__init__(f"{step}: {detail}")
        self.step = step
        self.detail = detail
        self.sample = sample  # the timing of the failed request, so the report still counts it


# ---------------------------------------------------------------- pure helpers


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank on the sorted sample, the same formula as evals/run.py `_pct`, so the
    load report and the eval report quote comparable numbers."""
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(round(p * (len(ordered) - 1))))], 1)


def distribution(values: list[float]) -> dict[str, Any]:
    return {
        "n": len(values),
        "p50": percentile(values, 0.5),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "max": round(max(values), 1) if values else None,
    }


def classify_turn(http_status: int | None, error: str | None) -> str:
    """Bucket a turn attempt: ok, denied, 429, 504, 5xx, transport or other."""
    if error is not None or http_status is None:
        return "transport"
    if 200 <= http_status < 300:
        return "ok"
    if http_status in (401, 403):
        return "denied"
    if http_status == 429:
        return "429"
    if http_status == 504:
        return "504"
    if http_status >= 500:
        return "5xx"
    return "other"


def turn_status(sample: TurnSample) -> str:
    """The status a turn contributes to status_counts."""
    bucket = classify_turn(sample.http_status, sample.error)
    if bucket == "ok":
        return sample.status if sample.status in TURN_STATUSES else "failed"
    if bucket == "denied":
        return "denied"
    return "failed"


def ramp_offsets(users: int, ramp_seconds: float) -> list[float]:
    """Start times (seconds after the level starts) that spread `users` VUs over the ramp."""
    if users <= 1 or ramp_seconds <= 0:
        return [0.0] * max(users, 0)
    step = ramp_seconds / (users - 1)
    return [round(i * step, 3) for i in range(users)]


def assign(index: int, scenarios: dict[str, int]) -> tuple[str, str]:
    """VU index -> (demo user, pubpid): users alternate, charts round-robin."""
    names = list(scenarios)
    return USERS[index % len(USERS)], names[index % len(names)]


class SSEFramer:
    """Incremental text/event-stream framing: feed lines, get (event, data) at each blank line.
    Shared by the offline parser and the live stream so TTFE is measured on the same framing."""

    def __init__(self) -> None:
        self.event = ""
        self.data: list[str] = []

    def feed(self, raw: str) -> tuple[str, str] | None:
        line = raw.rstrip("\r")
        if line == "":
            return self.flush()
        if line.startswith("event:"):
            self.event = line[6:].strip()
        elif line.startswith("data:"):
            self.data.append(line[5:].lstrip())
        return None

    def flush(self) -> tuple[str, str] | None:
        if not (self.event or self.data):
            return None
        frame = (self.event, "\n".join(self.data))
        self.event, self.data = "", []
        return frame


def parse_sse(lines: Iterable[str]) -> Iterator[tuple[str, str]]:
    """Yield (event, data) pairs from text/event-stream lines; a blank line ends a frame."""
    framer = SSEFramer()
    for line in lines:
        frame = framer.feed(line)
        if frame is not None:
            yield frame
    last = framer.flush()
    if last is not None:
        yield last


def _unescape(value: str) -> str:
    return value.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")


def parse_metrics(text: str) -> dict[str, list[tuple[dict[str, str], float]]]:
    """Prometheus text -> {metric name: [(labels, value)]}. Labels are kept whole, so a label
    the agent adds later (the `reason` on copilot_tool_calls_total) is carried through."""
    series: dict[str, list[tuple[dict[str, str], float]]] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _METRIC_LINE_RE.match(line)
        if not match:
            continue
        try:
            value = float(match.group("value"))
        except ValueError:
            continue
        labels = {k: _unescape(v) for k, v in _LABEL_RE.findall(match.group("labels") or "")}
        series.setdefault(match.group("name"), []).append((labels, value))
    return series


def counter_deltas(before: str | None, after: str | None, name: str) -> list[tuple[dict[str, str], float]]:
    """Per-label-set increase of a counter between two scrapes. A series absent before counts
    from zero; a decrease (process restart) counts the after value, as a fresh counter would."""
    if after is None:
        return []
    earlier = {frozenset(labels.items()): v for labels, v in parse_metrics(before or "").get(name, [])}
    out: list[tuple[dict[str, str], float]] = []
    for labels, value in parse_metrics(after).get(name, []):
        prior = earlier.get(frozenset(labels.items()), 0.0)
        delta = value - prior if value >= prior else value
        if delta:
            out.append((labels, delta))
    return out


def tool_unavailable_deltas(before: str | None, after: str | None) -> dict[str, Any]:
    """`unavailable` tool results by reason and by tool from copilot_tool_calls_total deltas.
    Works with the label set the agent emits today (tool, status) and with the `reason` label
    WS-AGENT is adding: a series without it aggregates under "unlabelled"."""
    by_reason: Counter[str] = Counter()
    by_tool: dict[str, Counter[str]] = {}
    calls_total = 0.0
    for labels, delta in counter_deltas(before, after, "copilot_tool_calls_total"):
        calls_total += delta
        if labels.get("status") != TOOL_FAILURE_STATUS:
            continue
        reason = labels.get("reason") or UNLABELLED_REASON
        tool = labels.get("tool", "?")
        by_reason[reason] += int(delta)
        by_tool.setdefault(tool, Counter())[reason] += int(delta)
    return {
        "calls_total": int(calls_total),
        "total": sum(by_reason.values()),
        "by_reason": dict(sorted(by_reason.items())),
        "by_tool": {tool: dict(sorted(c.items())) for tool, c in sorted(by_tool.items())},
    }


def labelled_counter_by(before: str | None, after: str | None, name: str, label: str) -> dict[str, int]:
    out: Counter[str] = Counter()
    for labels, delta in counter_deltas(before, after, name):
        out[labels.get(label, "?")] += int(delta)
    return dict(sorted(out.items()))


def _latencies(samples: Iterable[StepSample | TurnSample]) -> list[float]:
    return [s.ms for s in samples if s.error is None and s.http_status is not None]


def _error_split(turns: list[TurnSample]) -> dict[str, Any]:
    buckets = Counter(classify_turn(t.http_status, t.error) for t in turns)
    errors = {b: buckets.get(b, 0) for b in ERROR_BUCKETS}
    total = sum(errors.values())
    return {**errors, "total": total, "rate": round(total / len(turns), 4) if turns else 0.0}


def _status_counts(turns: list[TurnSample]) -> dict[str, int]:
    counts = Counter(turn_status(t) for t in turns)
    return {s: counts.get(s, 0) for s in TURN_STATUSES}


def _status_share(counts: dict[str, int], turns: int) -> dict[str, float]:
    return {s: round(n / turns, 4) if turns else 0.0 for s, n in counts.items()}


def _scenario_block(scenario: str, vus: list[VirtualUserResult]) -> dict[str, Any]:
    mine = [v for v in vus if v.scenario == scenario]
    steps = [s for v in mine for s in v.steps]
    turns = [t for v in mine for t in v.turns]
    counts = _status_counts(turns)
    latency = {
        "chart_open": distribution(_latencies(s for s in steps if s.step == "chart_open")),
        "ticket": distribution(_latencies(s for s in steps if s.step == "ticket")),
        "turn": distribution(_latencies(turns)),
        "ttfe": distribution([t.ttfe_ms for t in turns if t.ttfe_ms is not None]),
    }
    return {"vus": len(mine), "latency_ms": latency, "turns": len(turns), "errors": _error_split(turns), "status_counts": counts, "status_share": _status_share(counts, len(turns))}


def _step_http(steps: list[StepSample], turns: list[TurnSample]) -> dict[str, dict[str, int]]:
    out: dict[str, Counter[str]] = {}
    for s in steps:
        out.setdefault(s.step, Counter())["transport" if s.error is not None or s.http_status is None else str(s.http_status)] += 1
    for t in turns:
        out.setdefault("turn", Counter())["transport" if t.error is not None or t.http_status is None else str(t.http_status)] += 1
    return {step: dict(sorted(c.items())) for step, c in sorted(out.items())}


def _vu_record(vu: VirtualUserResult) -> dict[str, Any]:
    """The per-VU line of the report: who, which chart, where it stopped, and per turn the
    outcome plus the correlation id that joins it to its trace and log lines. No body text,
    no token, no cookie."""
    return {
        "index": vu.index,
        "user": vu.user,
        "scenario": vu.scenario,
        "completed": vu.completed,
        "failed_at": vu.failed_at,
        "error": vu.error,
        "turns": [
            {
                "type": t.turn_type,
                "http_status": t.http_status,
                "error": t.error,
                "status": t.status,
                "stream": t.stream,
                "ms": round(t.ms, 1),
                "ttfe_ms": round(t.ttfe_ms, 1) if t.ttfe_ms is not None else None,
                "correlation_id": t.correlation_id,
            }
            for t in vu.turns
        ],
    }


def summarize_level(users: int, vus: list[VirtualUserResult], metrics_before: str | None, metrics_after: str | None, started_at: str, finished_at: str, duration_s: float, scenarios: Iterable[str]) -> dict[str, Any]:
    """Everything the schema promises for one level, computed from the VU records and the two
    /metrics scrapes. Pure: no I/O, so evals/load/test_run_load.py can feed it synthetic samples."""
    steps = [s for v in vus for s in v.steps]
    turns = [t for v in vus for t in v.turns]
    latency: dict[str, Any] = {}
    for name in ("login", "chart_open", "session", "start", "ticket", "history"):
        latency[name] = distribution(_latencies(s for s in steps if s.step == name))
    latency["turn"] = distribution(_latencies(turns))
    latency["turn_first"] = distribution(_latencies(t for t in turns if t.turn_type == "first"))
    latency["turn_followup"] = distribution(_latencies(t for t in turns if t.turn_type == "followup"))
    latency["ttfe"] = distribution([t.ttfe_ms for t in turns if t.ttfe_ms is not None])
    counts = _status_counts(turns)
    usage = {k: round(sum(float(t.usage.get(k, 0) or 0) for t in turns)) for k in USAGE_KEYS}
    return {
        "users": users,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_s": round(duration_s, 1),
        "vus": {"total": len(vus), "completed": sum(1 for v in vus if v.completed), "failed": sum(1 for v in vus if not v.completed)},
        "failed_at": dict(sorted(Counter(v.failed_at for v in vus if v.failed_at).items())),
        "latency_ms": latency,
        "by_scenario": {name: _scenario_block(name, vus) for name in scenarios},
        "turns": len(turns),
        "errors": _error_split(turns),
        "denials": {
            "turn_http_401_403": sum(1 for t in turns if classify_turn(t.http_status, t.error) == "denied"),
            "handshake_http_401_403": sum(1 for s in steps if s.http_status in (401, 403)),
            "metrics_by_reason": labelled_counter_by(metrics_before, metrics_after, "copilot_denials_total", "reason"),
        },
        "status_counts": counts,
        "status_share": _status_share(counts, len(turns)),
        "server_turns_by_status": labelled_counter_by(metrics_before, metrics_after, "copilot_turns_total", "status"),
        "tool_unavailable": tool_unavailable_deltas(metrics_before, metrics_after),
        "client_tool_unavailable": sum(t.evidence_unavailable for t in turns),
        "usage": usage,
        "step_http": _step_http(steps, turns),
        "metrics": {"before": metrics_before is not None, "after": metrics_after is not None},
        "vu_records": [_vu_record(v) for v in sorted(vus, key=lambda v: v.index)],
    }


def build_results(*, commit: str, timestamp: str, label: str, cfg: RunConfig, levels: list[dict[str, Any]], interrupted: bool = False) -> dict[str, Any]:
    """The fixed top-level schema documented in the module docstring."""
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "load",
        "commit": commit,
        "timestamp": timestamp,
        "label": label,
        "base_url": cfg.base_url,
        "fault": cfg.fault,
        "ramp_seconds": cfg.ramp_seconds,
        "stream_levels": sorted(cfg.stream_levels),
        "users_levels": [lv["users"] for lv in levels],
        "scenarios": dict(cfg.scenarios),
        "messages": {"first": cfg.first_message, "followup": cfg.followup_message},
        "interrupted": interrupted,
        "levels": levels,
    }


def _fmt_dist(d: dict[str, Any], keys: tuple[str, ...] = ("p50", "p95", "p99")) -> str:
    if not d.get("n"):
        return "n/a"
    return " / ".join(f"{d[k]:.0f}" for k in keys)


def _fmt_errors(e: dict[str, Any]) -> str:
    return f"{e['total']} ({e['rate']:.1%}): " + " ".join(f"{b}={e[b]}" for b in ERROR_BUCKETS)


def _fmt_share(s: dict[str, float]) -> str:
    return " / ".join(f"{s.get(k, 0.0):.0%}" for k in ("complete", "partial", "fallback", "failed", "denied"))


def render_markdown(results: dict[str, Any]) -> str:
    """Sibling summary of the JSON: one table per level plus the tool-unavailable breakdown."""
    lines = [
        f"# Load run {results['timestamp']} ({results['commit']}){' — ' + results['label'] if results['label'] else ''}",
        "",
        f"Base URL `{results['base_url']}`; fault `{results['fault'] or 'none'}`; ramp {results['ramp_seconds']} s; "
        f"levels {', '.join(str(u) for u in results['users_levels']) or 'none'}; streamed first turn at levels "
        f"{', '.join(str(u) for u in results['stream_levels']) or 'none'}. Synthetic cohort af-cohort-v1; no PHI.",
        "",
        "Latency columns are p50 / p95 / p99 in ms over every request that received an HTTP response; "
        "transport failures count as errors only. Status share is complete / partial / fallback / failed / denied.",
    ]
    if results["interrupted"]:
        lines += ["", "**Interrupted run.** Only the levels that completed before Ctrl-C are recorded below."]
    for lv in results["levels"]:
        lat, errs = lv["latency_ms"], lv["errors"]
        lines += [
            "",
            f"## {lv['users']} users — {lv['vus']['completed']} of {lv['vus']['total']} VUs completed in {lv['duration_s']} s, {lv['turns']} turns",
            "",
            "| Scenario | VUs | Turns | Chart open | Ticket | Turn | TTFE (p50 / p95) | Errors (rate) | Denials | Status share |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            f"| all | {lv['vus']['total']} | {lv['turns']} | {_fmt_dist(lat['chart_open'])} | {_fmt_dist(lat['ticket'])} | {_fmt_dist(lat['turn'])} | "
            f"{_fmt_dist(lat['ttfe'], ('p50', 'p95'))} | {_fmt_errors(errs)} | {lv['denials']['turn_http_401_403']} | {_fmt_share(lv['status_share'])} |",
        ]
        for name, sc in lv["by_scenario"].items():
            sl = sc["latency_ms"]
            lines.append(
                f"| {name} | {sc['vus']} | {sc['turns']} | {_fmt_dist(sl['chart_open'])} | {_fmt_dist(sl['ticket'])} | {_fmt_dist(sl['turn'])} | "
                f"{_fmt_dist(sl['ttfe'], ('p50', 'p95'))} | {_fmt_errors(sc['errors'])} | {sc['status_counts']['denied']} | {_fmt_share(sc['status_share'])} |"
            )
        lines += [
            "",
            f"First turn p50 / p95 / p99: {_fmt_dist(lat['turn_first'])}; follow-up: {_fmt_dist(lat['turn_followup'])}; "
            f"login: {_fmt_dist(lat['login'])}; session.php: {_fmt_dist(lat['session'])}; start: {_fmt_dist(lat['start'])}; history: {_fmt_dist(lat['history'])}.",
        ]
        if lv["failed_at"]:
            lines.append("VUs that stopped early, by step: " + ", ".join(f"{k}={v}" for k, v in lv["failed_at"].items()) + ".")
        tu = lv["tool_unavailable"]
        if lv["metrics"]["before"] and lv["metrics"]["after"]:
            reasons = ", ".join(f"{k}={v}" for k, v in tu["by_reason"].items()) or "none"
            tools = "; ".join(f"{tool}: " + ", ".join(f"{k}={v}" for k, v in c.items()) for tool, c in tu["by_tool"].items()) or "none"
            lines.append(f"Tool calls in this level (from /metrics deltas): {tu['calls_total']}; unavailable {tu['total']} by reason: {reasons}; by tool: {tools}.")
            server = ", ".join(f"{k}={v}" for k, v in lv["server_turns_by_status"].items()) or "none"
            denials = ", ".join(f"{k}={v}" for k, v in lv["denials"]["metrics_by_reason"].items()) or "none"
            lines.append(f"Agent-side turns by status: {server}; denials by reason: {denials}.")
        else:
            lines.append("Tool-unavailable breakdown: not measured (/metrics was not read on both sides of this level).")
        u = lv["usage"]
        lines.append(f"Client-side unavailable evidence entries: {lv['client_tool_unavailable']}. Tokens in / out / cache read: {u['input_tokens']} / {u['output_tokens']} / {u['cache_read_tokens']}; model calls {u['model_calls']}.")
    return "\n".join(lines) + "\n"


def git_sha() -> str:
    """Copy of evals/run.py git_sha: short sha, or the CI variable, or 'unknown'."""
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except OSError:
        sha = ""
    return sha or os.environ.get("CI_COMMIT_SHORT_SHA", "") or "unknown"


def load_cohort(path: Path) -> dict[str, int]:
    """The three load scenarios with pids from cohort.json; the built-in map is only a fallback,
    and a disagreement between the two is an error rather than a silent choice."""
    if not path.exists():
        return dict(DEFAULT_SCENARIOS)
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a pubpid -> pid object")
    scenarios: dict[str, int] = {}
    for pubpid, fallback in DEFAULT_SCENARIOS.items():
        pid = data.get(pubpid)
        if not isinstance(pid, int):
            raise ValueError(f"{path}: {pubpid} is missing or not an integer pid")
        if pid != fallback:
            raise ValueError(f"{path}: {pubpid} is pid {pid}, the driver expected {fallback}; update DEFAULT_SCENARIOS deliberately")
        scenarios[pubpid] = pid
    return scenarios


def parse_levels(text: str) -> list[int]:
    levels: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit() or int(part) < 1:
            raise argparse.ArgumentTypeError(f"level {part!r} is not a positive integer")
        levels.append(int(part))
    if not levels:
        raise argparse.ArgumentTypeError("at least one level is required")
    return levels


# ---------------------------------------------------------------- live driver


class AsyncSession:
    """One OpenEMR login on one httpx.AsyncClient; the handshake of evals/run.py `Session`, async."""

    def __init__(self, client: httpx.AsyncClient, base_url: str, user: str, scenario: str, scenarios: dict[str, int]) -> None:
        self.client = client
        self.base = base_url.rstrip("/")
        self.api = self.base + API_PREFIX
        self.user = user
        self.scenario = scenario
        self.pid = scenarios[scenario]
        self.csrf: str | None = None
        self.conversation_id: str | None = None
        self.ticket: dict[str, Any] | None = None

    async def _request(self, step: str, method: str, url: str, **kwargs: Any) -> tuple[httpx.Response | None, StepSample]:
        t0 = time.perf_counter()
        try:
            resp = await self.client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            return None, StepSample(step, self.scenario, self.user, (time.perf_counter() - t0) * 1000, None, exc.__class__.__name__)
        return resp, StepSample(step, self.scenario, self.user, (time.perf_counter() - t0) * 1000, resp.status_code)

    async def login(self, password: str) -> StepSample:
        # evals/run.py:71-76 (inside Session.__init__): form login, success is the 302 to the main screen.
        form = {"new_login_session_management": "1", "languageChoice": "1", "authUser": self.user, "clearPass": password}
        resp, sample = await self._request("login", "POST", self.base + LOGIN_PATH, data=form)
        if resp is None or resp.status_code != 302:
            raise StepFailure("login", sample.error or f"HTTP {sample.http_status}", sample)
        return sample

    async def open_chart(self) -> StepSample:
        # evals/run.py:82-87: the chart must render the panel, or the rest measures nothing real.
        resp, sample = await self._request("chart_open", "GET", f"{self.base}{CHART_PATH}?set_pid={self.pid}", follow_redirects=True)
        if resp is None or resp.status_code != 200 or "copilot-panel" not in resp.text:
            raise StepFailure("chart_open", sample.error or f"HTTP {sample.http_status}, panel absent", sample)
        return sample

    async def session(self) -> StepSample:
        resp, sample = await self._request("session", "GET", f"{self.base}{MODULE_PATH}/api/session.php")
        if resp is None or resp.status_code != 200:
            raise StepFailure("session", sample.error or f"HTTP {sample.http_status}", sample)
        self.csrf = _json(resp).get("csrf_token")
        if not self.csrf:
            raise StepFailure("session", "no csrf_token", sample)
        return sample

    async def start(self) -> StepSample:
        resp, sample = await self._request("start", "POST", f"{self.base}{MODULE_PATH}/api/conversation.php", json={"action": "start", "csrf_token": self.csrf})
        if resp is None or resp.status_code != 200:
            raise StepFailure("start", sample.error or f"HTTP {sample.http_status}", sample)
        self.conversation_id = _json(resp).get("conversation_id")
        if not self.conversation_id:
            raise StepFailure("start", "no conversation_id", sample)
        return sample

    async def mint(self) -> StepSample:
        resp, sample = await self._request("ticket", "POST", f"{self.base}{MODULE_PATH}/api/ticket.php", json={"csrf_token": self.csrf, "conversation_id": self.conversation_id})
        self.ticket = _json(resp) if resp is not None and resp.status_code == 200 else None
        if not self.ticket or "token" not in self.ticket:
            raise StepFailure("ticket", sample.error or f"HTTP {sample.http_status}", sample)
        return sample

    def _turn_request(self, message: str, fault: str | None, stream: bool) -> tuple[str, dict[str, str], dict[str, Any]]:
        assert self.ticket is not None
        headers = {"X-Copilot-Token": self.ticket["token"], "X-Correlation-Id": self.ticket["correlation_id"]}
        if fault:
            headers["X-Copilot-Fault"] = fault
        if stream:
            headers["Accept"] = "text/event-stream"
        body = {"message": message, "correlation_id": self.ticket["correlation_id"], "stream": stream}
        return f"{self.api}/v1/conversations/{self.conversation_id}/turns", headers, body

    async def turn(self, message: str, turn_type: str, fault: str | None, stream: bool) -> TurnSample:
        url, headers, body = self._turn_request(message, fault, stream)
        sample = TurnSample(self.scenario, self.user, turn_type, 0.0, None, stream=stream, correlation_id=self.ticket["correlation_id"] if self.ticket else None)
        t0 = time.perf_counter()
        try:
            if stream:
                await self._streamed_turn(url, headers, body, sample, t0)
            else:
                resp = await self.client.post(url, json=body, headers=headers)
                sample.http_status = resp.status_code
                _absorb_body(sample, _json(resp) if resp.status_code == 200 else {})
        except httpx.HTTPError as exc:
            sample.error = exc.__class__.__name__
        sample.ms = (time.perf_counter() - t0) * 1000
        return sample

    async def _streamed_turn(self, url: str, headers: dict[str, str], body: dict[str, Any], sample: TurnSample, t0: float) -> None:
        async with self.client.stream("POST", url, json=body, headers=headers) as resp:
            sample.http_status = resp.status_code
            if resp.status_code != 200:
                await resp.aread()
                return
            errored = False
            async for event, data in _aiter_sse(resp):
                if event == "evidence" and sample.ttfe_ms is None:
                    sample.ttfe_ms = (time.perf_counter() - t0) * 1000
                elif event == "claims":
                    _absorb_body(sample, _loads(data))
                elif event == "error":
                    errored = True
            if errored or sample.status is None:
                sample.status = "failed"

    async def history(self) -> StepSample:
        assert self.ticket is not None
        _, sample = await self._request("history", "GET", f"{self.api}/v1/conversations/{self.conversation_id}", headers={"X-Copilot-Token": self.ticket["token"]})
        return sample


async def _aiter_sse(resp: httpx.Response) -> AsyncIterator[tuple[str, str]]:
    """Frame the SSE stream as it arrives, so TTFE is the arrival of the evidence frame, not of the whole body."""
    framer = SSEFramer()
    async for raw in resp.aiter_lines():
        frame = framer.feed(raw)
        if frame is not None:
            yield frame
    last = framer.flush()
    if last is not None:
        yield last


def _json(resp: httpx.Response | None) -> dict[str, Any]:
    if resp is None or not resp.content:
        return {}
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _loads(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _absorb_body(sample: TurnSample, body: dict[str, Any]) -> None:
    """Keep only what the report needs from a turn body: status, evidence health, usage, correlation id."""
    if not body:
        return
    status = body.get("status")
    sample.status = status if isinstance(status, str) else None
    sample.evidence_unavailable = sum(1 for e in body.get("evidence") or [] if isinstance(e, dict) and e.get("status") == TOOL_FAILURE_STATUS)
    usage = body.get("usage") or {}
    sample.usage = {k: float(usage.get(k, 0) or 0) for k in USAGE_KEYS} if isinstance(usage, dict) else {}
    if isinstance(body.get("correlation_id"), str):
        sample.correlation_id = body["correlation_id"]


ClientFactory = Callable[[], httpx.AsyncClient]


def default_client_factory() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TURN_TIMEOUT, follow_redirects=False)


async def run_virtual_user(index: int, level: int, cfg: RunConfig, password: str, start_delay: float, client_factory: ClientFactory = default_client_factory) -> VirtualUserResult:
    """One VU end to end. Never raises: a step that cannot continue is recorded in failed_at."""
    user, scenario = assign(index, cfg.scenarios)
    result = VirtualUserResult(index=index, user=user, scenario=scenario)
    if start_delay > 0:
        await asyncio.sleep(start_delay)
    stream_first = level in cfg.stream_levels
    async with client_factory() as client:
        session = AsyncSession(client, cfg.base_url, user, scenario, cfg.scenarios)
        step = "login"
        try:
            result.steps.append(await session.login(password))
            step = "chart_open"
            result.steps.append(await session.open_chart())
            step = "session"
            result.steps.append(await session.session())
            step = "start"
            result.steps.append(await session.start())
            for turn_type, message in (("first", cfg.first_message), ("followup", cfg.followup_message)):
                step = "ticket"
                result.steps.append(await session.mint())
                step = "turn"
                result.turns.append(await session.turn(message, turn_type, cfg.fault, stream_first and turn_type == "first"))
            step = "ticket"
            result.steps.append(await session.mint())
            step = "history"
            result.steps.append(await session.history())
        except StepFailure as exc:
            if exc.sample is not None:
                result.steps.append(exc.sample)
            result.failed_at, result.error = exc.step, exc.detail
        except httpx.HTTPError as exc:
            result.failed_at, result.error = step, exc.__class__.__name__
    return result


async def fetch_metrics(url: str | None, client_factory: ClientFactory = default_client_factory) -> str | None:
    """Best effort: a missing or failing /metrics never stops a level; the report says it was not read."""
    if not url:
        return None
    try:
        async with client_factory() as client:
            resp = await client.get(url, timeout=METRICS_TIMEOUT)
    except httpx.HTTPError:
        return None
    return resp.text if resp.status_code == 200 else None


async def run_level(users: int, cfg: RunConfig, password: str, client_factory: ClientFactory = default_client_factory) -> dict[str, Any]:
    before = await fetch_metrics(cfg.metrics_url, client_factory)
    started = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    offsets = ramp_offsets(users, cfg.ramp_seconds)
    vus = await asyncio.gather(*(run_virtual_user(i, users, cfg, password, offsets[i], client_factory) for i in range(users)))
    duration = time.perf_counter() - t0
    finished = datetime.now(timezone.utc)
    after = await fetch_metrics(cfg.metrics_url, client_factory)
    return summarize_level(users, list(vus), before, after, started.isoformat(timespec="seconds"), finished.isoformat(timespec="seconds"), duration, cfg.scenarios)


async def run_all(levels: list[int], cfg: RunConfig, password: str, client_factory: ClientFactory = default_client_factory, log: Callable[[str], None] = lambda _: None, sink: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Run every level in order. `sink` receives each level as it completes, so a run stopped by
    Ctrl-C after the 10-user level still writes the 1- and 10-user results."""
    out: list[dict[str, Any]] = sink if sink is not None else []
    for i, users in enumerate(levels):
        if i and cfg.pause_seconds > 0:
            log(f"pausing {cfg.pause_seconds:.0f} s before the {users}-user level")
            await asyncio.sleep(cfg.pause_seconds)
        log(f"level {users}: starting {users} VU(s) over {cfg.ramp_seconds:.0f} s" + (" with X-Copilot-Fault: " + cfg.fault if cfg.fault else ""))
        level = await run_level(users, cfg, password, client_factory)
        e = level["errors"]
        log(f"level {users}: {level['vus']['completed']}/{level['vus']['total']} VUs completed in {level['duration_s']} s; turns {level['turns']}, turn p95 {level['latency_ms']['turn']['p95']} ms, errors {e['total']} ({e['rate']:.1%})")
        out.append(level)
    return out


def write_results(results: dict[str, Any], out_dir: Path, stem: str) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    json_path.write_text(json.dumps(results, indent=2, sort_keys=False) + "\n")
    md_path.write_text(render_markdown(results))
    return json_path, md_path


def plan(levels: list[int], cfg: RunConfig) -> dict[str, Any]:
    """The schedule the run would execute, for a dry look without any network."""
    return {
        "base_url": cfg.base_url,
        "fault": cfg.fault,
        "levels": [
            {
                "users": users,
                "stream_first_turn": users in cfg.stream_levels,
                "vus": [{"index": i, "user": assign(i, cfg.scenarios)[0], "scenario": assign(i, cfg.scenarios)[1], "start_after_s": off} for i, off in enumerate(ramp_offsets(users, cfg.ramp_seconds))],
            }
            for users in levels
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Load driver for the Clinical Co-Pilot deployment (human-gated: every model-backed turn spends model budget).", formatter_class=argparse.RawDescriptionHelpFormatter, epilog="See the module docstring for the results schema and the expected failures at 50 users.")
    ap.add_argument("--base-url", required=True, help="Deployment origin, for example https://openemr-137-184-4-22.sslip.io (required; there is no default so nothing runs by accident)")
    ap.add_argument("--users", type=parse_levels, default=parse_levels(DEFAULT_LEVELS), help=f"Comma-separated VU levels run in order (default {DEFAULT_LEVELS})")
    ap.add_argument("--label", default="", help="Free-text label recorded in the results (for example baseline, fault-model)")
    ap.add_argument("--fault", default=None, help="Value for X-Copilot-Fault on every turn; 'model' measures capacity without provider limits or spend")
    ap.add_argument("--ramp-seconds", type=float, default=30.0, help="Spread each level's VU starts over this many seconds (default 30)")
    ap.add_argument("--password-env", default="DEMO_PASSWORD", help="Environment variable holding the demo clinician password (default DEMO_PASSWORD); never a flag")
    ap.add_argument("--metrics-url", default=None, help="Agent /metrics URL read before and after each level, for example https://<host>/copilot-api/metrics")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Where <UTC>-<sha>.json and .md go (default evals/load/results)")
    ap.add_argument("--cohort", type=Path, default=DEFAULT_COHORT_FILE, help="pubpid -> pid map (default evals/cases/cohort.json)")
    ap.add_argument("--stream-levels", type=parse_levels, default=parse_levels(DEFAULT_STREAM_LEVELS), help=f"Levels whose first turn is streamed to measure TTFE (default {DEFAULT_STREAM_LEVELS})")
    ap.add_argument("--pause-seconds", type=float, default=10.0, help="Idle time between levels so one level's tail does not bleed into the next (default 10)")
    ap.add_argument("--plan", action="store_true", help="Print the schedule as JSON and exit without any network access")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.base_url.startswith(("http://", "https://")):
        print("--base-url must start with http:// or https://", file=sys.stderr)
        return 2
    try:
        scenarios = load_cohort(args.cohort)
    except (OSError, ValueError) as exc:
        print(f"cohort: {exc}", file=sys.stderr)
        return 2
    cfg = RunConfig(args.base_url, scenarios, args.fault or None, args.ramp_seconds, frozenset(args.stream_levels), args.metrics_url, args.pause_seconds)
    if args.plan:
        print(json.dumps(plan(args.users, cfg), indent=2))
        return 0
    password = os.environ.get(args.password_env)
    if not password:
        print(f"set {args.password_env} in the environment (the password is never a command-line flag)", file=sys.stderr)
        return 2
    started = datetime.now(timezone.utc)
    levels: list[dict[str, Any]] = []
    interrupted = False
    try:
        asyncio.run(run_all(args.users, cfg, password, log=_log, sink=levels))
    except KeyboardInterrupt:
        interrupted = True
        _log(f"interrupted after {len(levels)} completed level(s); writing what finished")
    results = build_results(commit=git_sha(), timestamp=started.isoformat(timespec="seconds"), label=args.label, cfg=cfg, levels=levels, interrupted=interrupted)
    json_path, md_path = write_results(results, args.out_dir, f"{started.strftime('%Y-%m-%dT%H%M%SZ')}-{results['commit']}")
    _log(f"wrote {json_path} and {md_path}")
    return 130 if interrupted else 0


def _log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
