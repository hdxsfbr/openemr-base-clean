"""The three PRD runtime alerts (KEY_METRICS.md, "Decision Thresholds"),
evaluated as pure functions over a parsed /metrics text sample.

Rules and thresholds, copied from KEY_METRICS.md and not to be loosened
here (loosening needs a risk acceptance in the eval report):

    PRD alert 1, turn latency: warn at p95 above 30 s over 5 minutes; page at
        p95 above 45 s or any request over 60 s.
    PRD alert 2, error rate (5xx from the agent API): warn above 0.5% over
        5 minutes; page above 2% over 5 minutes, or any error in /ready for
        2 minutes.
    PRD alert 3, tool failure rate (`unavailable` from any clinical tool):
        warn above 2% over 5 minutes; page above 5%, or one tool above 50%.

Counters are cumulative, so a rate needs two samples; `counter_delta` handles
a process restart (the counter went backwards) by treating the current value
as the whole delta. The metrics carry no PHI and no unbounded labels, and the
alert messages are generic by construction.

Known gap: `copilot_tool_calls_total` carries `status` but not `reason`, so a
`forbidden` denial (reason under status `unavailable`) counts toward the tool
failure rate. KEY_METRICS.md excludes it; the metric cannot yet. See
docs/operations/alerts.md.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

# Thresholds (KEY_METRICS.md, Decision Thresholds table). Units are the
# metric's own units: milliseconds for latency, fractions for rates.
LATENCY_WARN_P95_MS = 30_000.0
LATENCY_PAGE_P95_MS = 45_000.0
LATENCY_PAGE_ANY_REQUEST_MS = 60_000.0
ERROR_RATE_WARN = 0.005
ERROR_RATE_PAGE = 0.02
READY_FAILING_PAGE_SECONDS = 120.0
TOOL_FAILURE_WARN = 0.02
TOOL_FAILURE_PAGE = 0.05
TOOL_FAILURE_SINGLE_TOOL_PAGE = 0.5

WINDOW = "5m"
# Request path classes that are synthetic probe traffic, not the agent API
# serving a user. They are excluded from the error-rate denominator so that a
# /health poll every few seconds cannot mask turn failures.
PROBE_PATHS = frozenset({"health", "ready", "metrics", "root"})
TOOL_FAILURE_STATUS = "unavailable"

SEVERITY_WARN = "warn"
SEVERITY_PAGE = "page"

Labels = dict[str, str]
Series = list[tuple[Labels, float]]

_SAMPLE_RE = re.compile(r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(?P<labels>.*)\})?\s+(?P<value>\S+)(?:\s+\S+)?\s*$")
_LABEL_RE = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\]|\\.)*)"')


@dataclass(frozen=True)
class Alert:
    name: str
    severity: str
    value: float
    threshold: float
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Sample:
    """A parsed /metrics scrape. `series` maps metric name to its samples."""

    series: dict[str, Series] = field(default_factory=dict)
    fetched_at: float = 0.0

    def values(self, name: str, **match: str) -> list[float]:
        return [v for labels, v in self.series.get(name, []) if all(labels.get(k) == want for k, want in match.items())]

    def get(self, name: str, default: float | None = None, **match: str) -> float | None:
        found = self.values(name, **match)
        return found[0] if found else default

    def total(self, name: str, **match: str) -> float:
        return float(sum(self.values(name, **match)))

    def labelled(self, name: str) -> Series:
        return list(self.series.get(name, []))

    def to_json(self) -> dict[str, Any]:
        return {
            "fetched_at": self.fetched_at,
            "series": {name: [[labels, value] for labels, value in rows] for name, rows in self.series.items()},
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Sample":
        series: dict[str, Series] = {}
        for name, rows in (data.get("series") or {}).items():
            series[name] = [(dict(labels), float(value)) for labels, value in rows]
        return cls(series=series, fetched_at=float(data.get("fetched_at") or 0.0))


def _unescape(value: str) -> str:
    return value.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")


def parse_labels(text: str) -> Labels:
    return {key: _unescape(value) for key, value in _LABEL_RE.findall(text)}


def parse_metrics(text: str, fetched_at: float = 0.0) -> Sample:
    """Parse Prometheus text exposition (the subset the agent emits plus the
    common cases: comments, labels with escaped quotes, optional timestamps,
    NaN/Inf). Unparseable lines are skipped rather than failing the scrape."""
    sample = Sample(fetched_at=fetched_at)
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _SAMPLE_RE.match(line)
        if not match:
            continue
        try:
            value = float(match.group("value"))
        except ValueError:
            continue
        labels = parse_labels(match.group("labels") or "")
        sample.series.setdefault(match.group("name"), []).append((labels, value))
    return sample


def counter_delta(current: float, previous: float | None) -> float:
    """Delta of a cumulative counter across two samples. A counter that went
    backwards means the process restarted; the current value is the delta."""
    if previous is None or current < previous:
        return current
    return current - previous


def _labelled_deltas(current: Sample, previous: Sample | None, name: str) -> list[tuple[Labels, float]]:
    prev_index: dict[tuple[tuple[str, str], ...], float] = {}
    if previous is not None:
        for labels, value in previous.labelled(name):
            prev_index[tuple(sorted(labels.items()))] = value
    out: list[tuple[Labels, float]] = []
    for labels, value in current.labelled(name):
        out.append((labels, counter_delta(value, prev_index.get(tuple(sorted(labels.items()))))))
    return out


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator > 0 else 0.0


def _pct(fraction: float) -> str:
    return f"{fraction * 100:.2f}%"


def evaluate_latency(sample: Sample) -> list[Alert]:
    """PRD alert 1. Uses the agent's own 5-minute p95 and p99 gauges. There is
    no max gauge; p99 stands in for "any request over 60 s" (with fewer than
    100 turns in the window p99 is the slowest turn)."""
    count = sample.get("copilot_turn_latency_count_5m", 0.0) or 0.0
    if count <= 0:
        return []
    p95 = sample.get("copilot_turn_latency_ms", 0.0, quantile="p95", window=WINDOW) or 0.0
    p99 = sample.get("copilot_turn_latency_ms", 0.0, quantile="p99", window=WINDOW) or 0.0
    alerts: list[Alert] = []
    if p99 > LATENCY_PAGE_ANY_REQUEST_MS:
        alerts.append(Alert("turn_latency", SEVERITY_PAGE, p99, LATENCY_PAGE_ANY_REQUEST_MS, f"A turn exceeded 60 s (p99 {p99 / 1000:.1f} s over {WINDOW}, {int(count)} turns)."))
    if p95 > LATENCY_PAGE_P95_MS:
        alerts.append(Alert("turn_latency", SEVERITY_PAGE, p95, LATENCY_PAGE_P95_MS, f"Turn p95 latency {p95 / 1000:.1f} s over {WINDOW} is above the 45 s page threshold ({int(count)} turns)."))
    elif p95 > LATENCY_WARN_P95_MS:
        alerts.append(Alert("turn_latency", SEVERITY_WARN, p95, LATENCY_WARN_P95_MS, f"Turn p95 latency {p95 / 1000:.1f} s over {WINDOW} is above the 30 s warning threshold ({int(count)} turns)."))
    return alerts


def evaluate_error_rate(sample: Sample, previous: Sample | None = None, min_requests: int = 1) -> list[Alert]:
    """PRD alert 2. 5xx responses over all non-probe agent API requests,
    computed on the counter deltas since `previous` (or cumulative when there
    is no previous sample)."""
    errors = 0.0
    total = 0.0
    for labels, delta in _labelled_deltas(sample, previous, "copilot_requests_total"):
        if labels.get("path") in PROBE_PATHS:
            continue
        total += delta
        if labels.get("status") == "5xx":
            errors += delta
    if total < min_requests:
        return []
    rate = _ratio(errors, total)
    detail = f"{int(errors)} of {int(total)} agent API requests returned 5xx ({_pct(rate)})"
    if rate > ERROR_RATE_PAGE:
        return [Alert("error_rate", SEVERITY_PAGE, rate, ERROR_RATE_PAGE, f"{detail}; above the 2% page threshold.")]
    if rate > ERROR_RATE_WARN:
        return [Alert("error_rate", SEVERITY_WARN, rate, ERROR_RATE_WARN, f"{detail}; above the 0.5% warning threshold.")]
    return []


def evaluate_readiness(ready_ok: bool, now: float, failing_since: float | None) -> tuple[Alert | None, float | None]:
    """The second page condition of PRD alert 2: /ready has reported an error
    for 2 minutes. Returns the alert (if any) and the updated `failing_since`
    to persist between runs."""
    if ready_ok:
        return None, None
    started = failing_since if failing_since is not None else now
    elapsed = now - started
    if elapsed >= READY_FAILING_PAGE_SECONDS:
        return Alert("error_rate", SEVERITY_PAGE, elapsed, READY_FAILING_PAGE_SECONDS, f"/ready has reported not_ready for {elapsed:.0f} s; a dependency is down."), started
    return None, started


def evaluate_tool_failure_rate(sample: Sample, previous: Sample | None = None, min_calls: int = 1) -> list[Alert]:
    """PRD alert 3. `unavailable` tool results over all tool calls, on the
    counter deltas since `previous`; plus the single-tool 50% page rule."""
    per_tool_total: dict[str, float] = {}
    per_tool_failed: dict[str, float] = {}
    for labels, delta in _labelled_deltas(sample, previous, "copilot_tool_calls_total"):
        tool = labels.get("tool", "?")
        per_tool_total[tool] = per_tool_total.get(tool, 0.0) + delta
        if labels.get("status") == TOOL_FAILURE_STATUS:
            per_tool_failed[tool] = per_tool_failed.get(tool, 0.0) + delta
    total = sum(per_tool_total.values())
    failed = sum(per_tool_failed.values())
    if total < min_calls:
        return []
    alerts: list[Alert] = []
    for tool in sorted(per_tool_total):
        calls = per_tool_total[tool]
        if calls < min_calls:
            continue
        tool_rate = _ratio(per_tool_failed.get(tool, 0.0), calls)
        if tool_rate > TOOL_FAILURE_SINGLE_TOOL_PAGE:
            alerts.append(Alert("tool_failure_rate", SEVERITY_PAGE, tool_rate, TOOL_FAILURE_SINGLE_TOOL_PAGE, f"Tool {tool} returned unavailable on {_pct(tool_rate)} of {int(calls)} calls; a service path is broken."))
    rate = _ratio(failed, total)
    detail = f"{int(failed)} of {int(total)} clinical tool calls returned unavailable ({_pct(rate)})"
    if rate > TOOL_FAILURE_PAGE:
        alerts.append(Alert("tool_failure_rate", SEVERITY_PAGE, rate, TOOL_FAILURE_PAGE, f"{detail}; above the 5% page threshold."))
    elif rate > TOOL_FAILURE_WARN:
        alerts.append(Alert("tool_failure_rate", SEVERITY_WARN, rate, TOOL_FAILURE_WARN, f"{detail}; above the 2% warning threshold."))
    return alerts


def evaluate(sample: Sample, previous: Sample | None = None) -> list[Alert]:
    """All three PRD alerts for one scrape. `previous` enables rate math on the
    cumulative counters; without it rates are since process start."""
    alerts: list[Alert] = []
    alerts.extend(evaluate_latency(sample))
    alerts.extend(evaluate_error_rate(sample, previous))
    alerts.extend(evaluate_tool_failure_rate(sample, previous))
    return alerts


def worst_severity(alerts: Iterable[Alert]) -> str | None:
    severities = {a.severity for a in alerts}
    if SEVERITY_PAGE in severities:
        return SEVERITY_PAGE
    if SEVERITY_WARN in severities:
        return SEVERITY_WARN
    return None


if __name__ == "__main__":  # pragma: no cover
    from .alerts_cli import main

    raise SystemExit(main())
