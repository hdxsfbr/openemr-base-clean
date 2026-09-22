"""In-process operational metrics (PRD dashboard minimum) exposed as
Prometheus text at /metrics on the internal network. No PHI, no unbounded
labels: every label value is drawn from a closed set defined here or in the
contracts (`TOOL_REASONS`, `VERIFICATION_OUTCOMES`)."""

from __future__ import annotations

import re
import threading
import time
from collections import Counter, deque
from typing import Any

from .contracts.tools import TOOL_REASONS
from .turn_outcome import VERIFICATION_OUTCOMES

_HTTP_REASON_RE = re.compile(r"^http_(\d)\d\d$")
REASON_NONE = "none"
# The funnel that says whether precomputing the UC-01 brief is seen: chart opened with the panel, brief
# started for it (BriefPolicy said so, module 0.5.0), drawer opened, and what kind of question opened the
# conversation. `brief_started` against `drawer_open` is the precompute's waste rate: a brief prepared for
# a chart whose drawer is never opened is spend nobody read. Closed label sets, no ids.
PANEL_EVENTS = ("chart_open", "brief_started", "drawer_open")
FIRST_TURN_TYPES = ("uc01_first", "followup")
REASON_OTHER = "other"


def bounded_reason(reason: str | None) -> str:
    """Map a tool envelope's free-text `reason` onto the bounded label set: a
    missing reason is `none`, an `http_<code>` collapses to its class
    (`http_5xx`), anything outside `TOOL_REASONS` is `other`."""
    if reason is None or reason == "":
        return REASON_NONE
    if reason in TOOL_REASONS:
        return reason
    match = _HTTP_REASON_RE.match(reason)
    if match:
        return f"http_{match.group(1)}xx"
    return REASON_OTHER


class Metrics:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.requests = Counter()
        self.turns = Counter()
        self.denials = Counter()
        self.tool_status = Counter()
        self.rejections = Counter()
        self.tokens = Counter()
        self.verification = Counter()
        self.extractions = Counter()
        self.panel_events = Counter()
        self.first_turns = Counter()
        self.latencies: deque[tuple[float, float]] = deque(maxlen=5000)
        # Every HTTP request, healthchecks and scrapes included (copilot_in_flight).
        self.in_flight = 0
        # Turns inside the graph or the SSE generator only: the queue depth the PRD asks for.
        self.turns_in_flight = 0
        self.started = time.time()

    def request(self, path_class: str, status: int) -> None:
        with self.lock:
            self.requests[(path_class, str(status // 100) + "xx")] += 1

    def denial(self, reason: str) -> None:
        with self.lock:
            self.denials[reason[:40]] += 1

    def panel_event(self, event: str) -> bool:
        """A chart opened with the panel on it, a brief started for it, or the
        drawer was opened. False for anything else."""
        if event not in PANEL_EVENTS:
            return False
        with self.lock:
            self.panel_events[event] += 1
        return True

    def conversation_first_turn(self, turn_type: str | None) -> None:
        """What kind of question opened a conversation: the UC-01 brief or something else."""
        with self.lock:
            self.first_turns[turn_type if turn_type in FIRST_TURN_TYPES else REASON_OTHER] += 1

    def turn_started(self) -> None:
        with self.lock:
            self.turns_in_flight += 1

    def turn_finished(self) -> None:
        with self.lock:
            self.turns_in_flight -= 1

    def tool_call(self, tool: str, status: str, reason: str | None) -> None:
        """One gateway call, counted where it happens (the graph's `_call`) so
        follow-up plan rounds and repeated tools count each time."""
        with self.lock:
            self.tool_status[(tool[:40], status[:16], bounded_reason(reason))] += 1

    def turn(self, status: str, latency_ms: float, usage: dict[str, Any], rejected: list[dict[str, str]] | None = None, verification: str | None = None) -> None:
        with self.lock:
            self.turns[status] += 1
            self.latencies.append((time.time(), latency_ms))
            for k in ("input_tokens", "output_tokens", "cache_read_tokens", "model_calls"):
                self.tokens[k] += int(usage.get(k, 0) or 0)
            for r in rejected or []:
                self.rejections[str(r.get("rule", "?"))[:40]] += 1
            if verification is not None:
                self.verification[verification if verification in VERIFICATION_OUTCOMES else REASON_OTHER] += 1

    def extraction(self, status: str, latency_ms: float, confidence: str) -> None:
        """Record only the bounded outcome of a document-preview job.

        Field values, source identifiers, and handoff identifiers deliberately
        stay out of metrics.  The confidence summary is the lowest confidence
        bucket visible in the preview, or ``unknown`` for an unavailable job.
        """
        with self.lock:
            bounded_status = status if status in {"complete", "partial", "unavailable", "failed"} else REASON_OTHER
            bounded_confidence = confidence if confidence in {"high", "medium", "low", "unknown"} else REASON_OTHER
            self.extractions[(bounded_status, bounded_confidence)] += 1
            self.latencies.append((time.time(), latency_ms))

    def window(self, seconds: float = 300.0) -> dict[str, float]:
        now = time.time()
        with self.lock:
            vals = sorted(v for t, v in self.latencies if now - t <= seconds)
        if not vals:
            return {"count": 0, "p50": 0.0, "p95": 0.0, "p99": 0.0}
        pick = lambda q: vals[min(len(vals) - 1, int(q * len(vals)))]  # noqa: E731
        return {"count": len(vals), "p50": pick(0.5), "p95": pick(0.95), "p99": pick(0.99)}

    def prometheus(self) -> str:
        lines = ["# TYPE copilot_requests_total counter"]
        with self.lock:
            for (path_class, status), n in self.requests.items():
                lines.append(f'copilot_requests_total{{path="{path_class}",status="{status}"}} {n}')
            lines.append("# TYPE copilot_turns_total counter")
            for status, n in self.turns.items():
                lines.append(f'copilot_turns_total{{status="{status}"}} {n}')
            lines.append("# TYPE copilot_denials_total counter")
            for reason, n in self.denials.items():
                lines.append(f'copilot_denials_total{{reason="{reason}"}} {n}')
            lines.append("# TYPE copilot_tool_calls_total counter")
            for (tool, status, reason), n in self.tool_status.items():
                lines.append(f'copilot_tool_calls_total{{tool="{tool}",status="{status}",reason="{reason}"}} {n}')
            lines.append("# TYPE copilot_verifier_rejections_total counter")
            for rule, n in self.rejections.items():
                lines.append(f'copilot_verifier_rejections_total{{rule="{rule}"}} {n}')
            lines.append("# TYPE copilot_verification_total counter")
            for outcome, n in self.verification.items():
                lines.append(f'copilot_verification_total{{outcome="{outcome}"}} {n}')
            lines.append("# TYPE copilot_document_extractions_total counter")
            for (status, confidence), n in self.extractions.items():
                lines.append(f'copilot_document_extractions_total{{status="{status}",confidence="{confidence}"}} {n}')
            lines.append("# TYPE copilot_panel_events_total counter")
            for event, n in self.panel_events.items():
                lines.append(f'copilot_panel_events_total{{event="{event}"}} {n}')
            lines.append("# TYPE copilot_conversation_first_turn_total counter")
            for turn_type, n in self.first_turns.items():
                lines.append(f'copilot_conversation_first_turn_total{{turn_type="{turn_type}"}} {n}')
            lines.append("# TYPE copilot_tokens_total counter")
            for k, n in self.tokens.items():
                lines.append(f'copilot_tokens_total{{kind="{k}"}} {n}')
            lines.append(f"copilot_in_flight {self.in_flight}")
            lines.append("# TYPE copilot_turns_in_flight gauge")
            lines.append(f"copilot_turns_in_flight {self.turns_in_flight}")
        w = self.window()
        lines.append("# TYPE copilot_turn_latency_ms gauge")
        for q in ("p50", "p95", "p99"):
            lines.append(f'copilot_turn_latency_ms{{quantile="{q}",window="5m"}} {w[q]:.1f}')
        lines.append(f"copilot_turn_latency_count_5m {w['count']}")
        return "\n".join(lines) + "\n"


metrics = Metrics()
