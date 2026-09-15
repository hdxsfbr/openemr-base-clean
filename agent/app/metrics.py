"""In-process operational metrics (PRD dashboard minimum) exposed as
Prometheus text at /metrics on the internal network. No PHI, no unbounded
labels."""

from __future__ import annotations

import threading
import time
from collections import Counter, deque
from typing import Any


class Metrics:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.requests = Counter()
        self.turns = Counter()
        self.denials = Counter()
        self.tool_status = Counter()
        self.rejections = Counter()
        self.tokens = Counter()
        self.latencies: deque[tuple[float, float]] = deque(maxlen=5000)
        self.in_flight = 0
        self.started = time.time()

    def request(self, path_class: str, status: int) -> None:
        with self.lock:
            self.requests[(path_class, str(status // 100) + "xx")] += 1

    def denial(self, reason: str) -> None:
        with self.lock:
            self.denials[reason[:40]] += 1

    def turn(self, status: str, latency_ms: float, usage: dict[str, Any], evidence: list[dict[str, Any]] | None = None, rejected: list[dict[str, str]] | None = None) -> None:
        with self.lock:
            self.turns[status] += 1
            self.latencies.append((time.time(), latency_ms))
            for k in ("input_tokens", "output_tokens", "cache_read_tokens", "model_calls"):
                self.tokens[k] += int(usage.get(k, 0) or 0)
            for e in evidence or []:
                self.tool_status[(e.get("tool", "?"), e.get("status", "?"))] += 1
            for r in rejected or []:
                self.rejections[str(r.get("rule", "?"))[:40]] += 1

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
            for (tool, status), n in self.tool_status.items():
                lines.append(f'copilot_tool_calls_total{{tool="{tool}",status="{status}"}} {n}')
            lines.append("# TYPE copilot_verifier_rejections_total counter")
            for rule, n in self.rejections.items():
                lines.append(f'copilot_verifier_rejections_total{{rule="{rule}"}} {n}')
            lines.append("# TYPE copilot_tokens_total counter")
            for k, n in self.tokens.items():
                lines.append(f'copilot_tokens_total{{kind="{k}"}} {n}')
            lines.append(f"copilot_in_flight {self.in_flight}")
        w = self.window()
        lines.append("# TYPE copilot_turn_latency_ms gauge")
        for q in ("p50", "p95", "p99"):
            lines.append(f'copilot_turn_latency_ms{{quantile="{q}",window="5m"}} {w[q]:.1f}')
        lines.append(f"copilot_turn_latency_count_5m {w['count']}")
        return "\n".join(lines) + "\n"


metrics = Metrics()
