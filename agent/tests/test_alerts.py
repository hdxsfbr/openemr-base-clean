"""PRD alert rules (KEY_METRICS.md, Decision Thresholds) over /metrics text."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import httpx
import pytest

from app import alerts as A
from app.alerts_cli import EXIT_FETCH_FAILED, EXIT_OK, EXIT_PAGE, resolve_webhook, run_once
from app.metrics import Metrics


def metrics_text(
    *,
    turns_5m: int = 10,
    p95_ms: float = 12_000.0,
    p99_ms: float = 20_000.0,
    turn_2xx: int = 100,
    turn_5xx: int = 0,
    health_2xx: int = 1000,
    tools: dict[tuple[str, str, str], int] | None = None,
) -> str:
    """A /metrics sample in the agent's own shape; `tools` maps (tool, status, reason) to a count."""
    tools = tools if tools is not None else {("problems", "ok", "none"): 100, ("medications", "ok", "none"): 100}
    lines = [
        "# TYPE copilot_requests_total counter",
        f'copilot_requests_total{{path="health",status="2xx"}} {health_2xx}',
        f'copilot_requests_total{{path="turn",status="2xx"}} {turn_2xx}',
        f'copilot_requests_total{{path="turn",status="5xx"}} {turn_5xx}',
        "# TYPE copilot_tool_calls_total counter",
        *[f'copilot_tool_calls_total{{tool="{tool}",status="{status}",reason="{reason}"}} {n}' for (tool, status, reason), n in tools.items()],
        "# TYPE copilot_turn_latency_ms gauge",
        f'copilot_turn_latency_ms{{quantile="p50",window="5m"}} {p95_ms / 2:.1f}',
        f'copilot_turn_latency_ms{{quantile="p95",window="5m"}} {p95_ms:.1f}',
        f'copilot_turn_latency_ms{{quantile="p99",window="5m"}} {p99_ms:.1f}',
        f"copilot_turn_latency_count_5m {turns_5m}",
    ]
    return "\n".join(lines) + "\n"


def names(alerts: list[A.Alert]) -> list[tuple[str, str]]:
    return [(a.name, a.severity) for a in alerts]


# Parser


def test_parser_handles_labels_comments_and_escapes() -> None:
    text = (
        "# HELP something\n"
        "# TYPE copilot_requests_total counter\n"
        'copilot_requests_total{path="turn",status="2xx"} 4\n'
        'copilot_denials_total{reason="quote \\" and, comma"} 2 1700000000\n'
        "copilot_in_flight 1\n"
        "garbage line without value\n"
        'copilot_turn_latency_ms{quantile="p95",window="5m"} 123.4\n'
    )
    sample = A.parse_metrics(text, fetched_at=42.0)
    assert sample.fetched_at == 42.0
    assert sample.get("copilot_requests_total", path="turn", status="2xx") == 4
    assert sample.labelled("copilot_denials_total") == [({"reason": 'quote " and, comma'}, 2.0)]
    assert sample.get("copilot_in_flight") == 1.0
    assert sample.get("copilot_turn_latency_ms", quantile="p95", window="5m") == 123.4
    assert sample.get("missing_metric") is None
    assert "garbage" not in sample.series


def test_parser_reads_the_agents_real_exposition() -> None:
    m = Metrics()
    m.request("turn", 200)
    m.request("turn", 500)
    m.tool_call("problems", "ok", None)
    m.tool_call("labs", "unavailable", "timeout")
    m.tool_call("labs", "unavailable", "http_502")
    m.turn("complete", 1500.0, {"input_tokens": 10}, verification="passed")
    sample = A.parse_metrics(m.prometheus())
    assert sample.total("copilot_requests_total", path="turn") == 2
    assert sample.get("copilot_tool_calls_total", tool="problems", status="ok", reason="none") == 1
    assert sample.get("copilot_tool_calls_total", tool="labs", status="unavailable", reason="timeout") == 1
    assert sample.get("copilot_tool_calls_total", tool="labs", status="unavailable", reason="http_5xx") == 1
    assert sample.get("copilot_verification_total", outcome="passed") == 1
    assert sample.get("copilot_turns_in_flight") == 0
    assert sample.get("copilot_turn_latency_count_5m") == 1
    assert sample.get("copilot_turn_latency_ms", quantile="p95", window="5m") == 1500.0


def test_sample_round_trips_through_json() -> None:
    sample = A.parse_metrics(metrics_text(), fetched_at=7.0)
    again = A.Sample.from_json(json.loads(json.dumps(sample.to_json())))
    assert again.series == sample.series
    assert again.fetched_at == 7.0


# Alert 1: turn latency


def test_latency_quiet_below_warn() -> None:
    assert A.evaluate_latency(A.parse_metrics(metrics_text(p95_ms=29_999.0, p99_ms=40_000.0))) == []


def test_latency_warns_above_30s() -> None:
    alerts = A.evaluate_latency(A.parse_metrics(metrics_text(p95_ms=31_000.0, p99_ms=40_000.0)))
    assert names(alerts) == [("turn_latency", "warn")]
    assert alerts[0].threshold == 30_000.0 and alerts[0].value == 31_000.0


def test_latency_pages_above_45s() -> None:
    alerts = A.evaluate_latency(A.parse_metrics(metrics_text(p95_ms=46_000.0, p99_ms=50_000.0)))
    assert names(alerts) == [("turn_latency", "page")]
    assert alerts[0].threshold == 45_000.0


def test_latency_pages_when_a_single_turn_exceeds_60s() -> None:
    alerts = A.evaluate_latency(A.parse_metrics(metrics_text(p95_ms=20_000.0, p99_ms=61_000.0)))
    assert names(alerts) == [("turn_latency", "page")]
    assert alerts[0].threshold == 60_000.0


def test_latency_silent_with_no_turns_in_window() -> None:
    assert A.evaluate_latency(A.parse_metrics(metrics_text(turns_5m=0, p95_ms=0.0, p99_ms=0.0))) == []


# Alert 2: error rate


def test_error_rate_quiet_at_or_below_half_percent() -> None:
    assert A.evaluate_error_rate(A.parse_metrics(metrics_text(turn_2xx=995, turn_5xx=5))) == []


def test_error_rate_warns_above_half_percent() -> None:
    alerts = A.evaluate_error_rate(A.parse_metrics(metrics_text(turn_2xx=990, turn_5xx=10)))
    assert names(alerts) == [("error_rate", "warn")]
    assert alerts[0].threshold == 0.005 and alerts[0].value == pytest.approx(0.01)


def test_error_rate_pages_above_two_percent() -> None:
    alerts = A.evaluate_error_rate(A.parse_metrics(metrics_text(turn_2xx=95, turn_5xx=5)))
    assert names(alerts) == [("error_rate", "page")]
    assert alerts[0].threshold == 0.02


def test_error_rate_ignores_probe_traffic_in_the_denominator() -> None:
    # 5 failed turns out of 100 is 5% even with a thousand /health polls.
    alerts = A.evaluate_error_rate(A.parse_metrics(metrics_text(turn_2xx=95, turn_5xx=5, health_2xx=100_000)))
    assert names(alerts) == [("error_rate", "page")]


def test_error_rate_uses_the_delta_between_two_samples() -> None:
    previous = A.parse_metrics(metrics_text(turn_2xx=100, turn_5xx=10), fetched_at=0.0)
    # Cumulatively 10/210 is 4.8%, but nothing failed since the last sample.
    current = A.parse_metrics(metrics_text(turn_2xx=200, turn_5xx=10), fetched_at=300.0)
    assert A.evaluate_error_rate(current) != []
    assert A.evaluate_error_rate(current, previous) == []
    # And the reverse: a clean history does not hide a bad window.
    previous = A.parse_metrics(metrics_text(turn_2xx=10_000, turn_5xx=0))
    current = A.parse_metrics(metrics_text(turn_2xx=10_090, turn_5xx=10))
    assert names(A.evaluate_error_rate(current, previous)) == [("error_rate", "page")]


def test_counter_reset_is_treated_as_a_fresh_process() -> None:
    assert A.counter_delta(5, None) == 5
    assert A.counter_delta(15, 10) == 5
    assert A.counter_delta(3, 10) == 3
    previous = A.parse_metrics(metrics_text(turn_2xx=1000, turn_5xx=0))
    current = A.parse_metrics(metrics_text(turn_2xx=10, turn_5xx=1))  # restarted, 1 of 11 failed
    assert names(A.evaluate_error_rate(current, previous)) == [("error_rate", "page")]


def test_readiness_pages_only_after_two_minutes_of_failure() -> None:
    alert, since = A.evaluate_readiness(False, now=1000.0, failing_since=None)
    assert alert is None and since == 1000.0
    alert, since = A.evaluate_readiness(False, now=1100.0, failing_since=since)
    assert alert is None and since == 1000.0
    alert, since = A.evaluate_readiness(False, now=1120.0, failing_since=since)
    assert alert is not None and alert.severity == "page" and alert.name == "error_rate"
    assert since == 1000.0
    alert, since = A.evaluate_readiness(True, now=1200.0, failing_since=since)
    assert alert is None and since is None


# Alert 3: tool failure rate


def test_tool_failure_quiet_at_or_below_two_percent() -> None:
    tools = {("problems", "ok", "none"): 98, ("problems", "unavailable", "service_error"): 2}
    assert A.evaluate_tool_failure_rate(A.parse_metrics(metrics_text(tools=tools))) == []


def test_tool_failure_warns_above_two_percent() -> None:
    tools = {("problems", "ok", "none"): 97, ("medications", "unavailable", "service_error"): 3}
    alerts = A.evaluate_tool_failure_rate(A.parse_metrics(metrics_text(tools=tools)))
    assert names(alerts) == [("tool_failure_rate", "page"), ("tool_failure_rate", "warn")]
    # medications failed 3 of 3, so the single-tool rule pages; the fleet rate warns.
    assert alerts[0].threshold == 0.5 and alerts[1].threshold == 0.02


def test_tool_failure_fleet_warn_without_single_tool_page() -> None:
    # 5 of 200 is 2.5% (warn); problems alone is 5%, well under the 50% single-tool page.
    tools = {("problems", "ok", "none"): 95, ("problems", "unavailable", "service_error"): 5, ("labs", "ok", "none"): 100}
    alerts = A.evaluate_tool_failure_rate(A.parse_metrics(metrics_text(tools=tools)))
    assert names(alerts) == [("tool_failure_rate", "warn")]
    assert alerts[0].value == pytest.approx(0.025)


def test_tool_failure_pages_above_five_percent() -> None:
    tools = {("problems", "ok", "none"): 94, ("problems", "unavailable", "service_error"): 6}
    alerts = A.evaluate_tool_failure_rate(A.parse_metrics(metrics_text(tools=tools)))
    assert names(alerts) == [("tool_failure_rate", "page")]
    assert alerts[0].threshold == 0.05 and alerts[0].value == pytest.approx(0.06)


def test_tool_failure_pages_when_one_tool_is_over_half_broken() -> None:
    # 3 of 1003 calls is 0.3% overall, but the labs path is 100% broken (PERF-MED-001 shape).
    tools = {("problems", "ok", "none"): 1000, ("lab_results", "unavailable", "service_error"): 3}
    alerts = A.evaluate_tool_failure_rate(A.parse_metrics(metrics_text(tools=tools)))
    assert names(alerts) == [("tool_failure_rate", "page")]
    assert "lab_results" in alerts[0].message and alerts[0].threshold == 0.5


def test_tool_failure_empty_and_partial_are_not_failures() -> None:
    tools = {("allergies", "empty", "none"): 50, ("notes", "partial", "orphan_rows_omitted"): 50}
    assert A.evaluate_tool_failure_rate(A.parse_metrics(metrics_text(tools=tools))) == []


def test_tool_failure_ignores_forbidden_denials() -> None:
    # Six front-desk denials among forty calls (the a4a5856 AUTH-FRONTDESK-001 shape): 15% of
    # results are `unavailable`, none is a tool failure, so nothing fires (KEY_METRICS.md
    # excludes `forbidden` from the rate).
    tools = {("problems", "ok", "none"): 34, ("problems", "unavailable", "forbidden"): 6}
    assert A.evaluate_tool_failure_rate(A.parse_metrics(metrics_text(tools=tools))) == []
    # Every clinical tool denied at once (a Front Office user) is still not a broken service path.
    denied = {(tool, "unavailable", "forbidden"): 5 for tool in ("problems", "medications", "allergies", "lab_results", "clinical_notes")}
    assert A.evaluate_tool_failure_rate(A.parse_metrics(metrics_text(tools=denied))) == []


def test_tool_failure_keeps_forbidden_in_the_denominator() -> None:
    # Two real failures among forty calls, six of them denials: 2/40 is 5.0%, a warn. If the
    # denials left the denominator too it would be 2/34 = 5.9% and page (docs/operations/alerts.md
    # keeps the denominator as all tool calls).
    tools = {("problems", "ok", "none"): 32, ("problems", "unavailable", "forbidden"): 6, ("problems", "unavailable", "service_error"): 2}
    alerts = A.evaluate_tool_failure_rate(A.parse_metrics(metrics_text(tools=tools)))
    assert names(alerts) == [("tool_failure_rate", "warn")]
    assert alerts[0].value == pytest.approx(0.05)


def test_tool_failure_rate_across_two_samples() -> None:
    previous = A.parse_metrics(metrics_text(tools={("problems", "ok", "none"): 100, ("problems", "unavailable", "service_error"): 50}))
    current = A.parse_metrics(metrics_text(tools={("problems", "ok", "none"): 200, ("problems", "unavailable", "service_error"): 50}))
    assert A.evaluate_tool_failure_rate(current) != []
    assert A.evaluate_tool_failure_rate(current, previous) == []


# Combined evaluation and CLI


def test_evaluate_combines_all_three_rules_and_reports_worst_severity() -> None:
    tools = {("problems", "ok", "none"): 90, ("problems", "unavailable", "service_error"): 10}
    sample = A.parse_metrics(metrics_text(p95_ms=31_000.0, turn_2xx=990, turn_5xx=10, tools=tools))
    alerts = A.evaluate(sample)
    assert names(alerts) == [("turn_latency", "warn"), ("error_rate", "warn"), ("tool_failure_rate", "page")]
    assert A.worst_severity(alerts) == "page"
    assert A.worst_severity(alerts[:2]) == "warn"
    assert A.worst_severity([]) is None
    assert set(alerts[0].to_dict()) == {"name", "severity", "value", "threshold", "message"}


def _client(texts: dict[str, str], ready_status: int = 200, posted: list | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            (posted if posted is not None else []).append(json.loads(request.content))
            return httpx.Response(204)
        if request.url.path.endswith("/ready"):
            return httpx.Response(ready_status, json={"status": "ready" if ready_status == 200 else "not_ready"})
        if request.url.path.endswith("/metrics"):
            return httpx.Response(200, text=texts["metrics"])
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _args(tmp_path: Path, **overrides) -> argparse.Namespace:
    base = {
        "url": "http://agent/metrics",
        "state": str(tmp_path / "state.json"),
        "ready_url": None,
        "webhook": None,
        "webhook_file": None,
        "webhook_channel": None,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def test_cli_heartbeat_then_page_with_state_and_webhook(tmp_path: Path) -> None:
    out = io.StringIO()
    code = run_once(_args(tmp_path), _client({"metrics": metrics_text(turn_2xx=100, turn_5xx=0)}), now=0.0, out=out)
    first = json.loads(out.getvalue().strip())
    assert code == EXIT_OK and first["event"] == "heartbeat" and first["rate_window_seconds"] is None
    assert json.loads((tmp_path / "state.json").read_text())["previous"]["fetched_at"] == 0.0

    posted: list = []
    out = io.StringIO()
    text = metrics_text(turn_2xx=110, turn_5xx=5)  # 5 of 15 since last sample
    code = run_once(_args(tmp_path, webhook="http://hooks/x"), _client({"metrics": text}, posted=posted), now=300.0, out=out)
    records = [json.loads(line) for line in out.getvalue().splitlines()]
    assert code == EXIT_PAGE
    assert [(r["event"], r["name"], r["severity"]) for r in records] == [("alert", "error_rate", "page")]
    assert records[0]["rate_window_seconds"] == 300.0 and records[0]["webhook_delivered"] is True
    assert posted and posted[0]["name"] == "error_rate"


def test_cli_ready_rule_pages_after_two_minutes(tmp_path: Path) -> None:
    text = metrics_text()
    args = _args(tmp_path, ready_url="http://agent/ready")
    assert run_once(args, _client({"metrics": text}, ready_status=503), now=0.0, out=io.StringIO()) == EXIT_OK
    assert run_once(args, _client({"metrics": text}, ready_status=503), now=60.0, out=io.StringIO()) == EXIT_OK
    out = io.StringIO()
    assert run_once(args, _client({"metrics": text}, ready_status=503), now=120.0, out=out) == EXIT_PAGE
    assert "/ready" in json.loads(out.getvalue())["message"]
    assert run_once(args, _client({"metrics": text}, ready_status=200), now=180.0, out=io.StringIO()) == EXIT_OK
    assert json.loads((tmp_path / "state.json").read_text())["ready_failing_since"] is None


def test_cli_reports_fetch_failure_without_touching_state(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    out = io.StringIO()
    code = run_once(_args(tmp_path), httpx.Client(transport=httpx.MockTransport(handler)), now=0.0, out=out)
    assert code == EXIT_FETCH_FAILED
    assert json.loads(out.getvalue())["event"] == "fetch_failed"
    assert not (tmp_path / "state.json").exists()


def test_resolve_webhook_prefers_the_file_and_treats_absence_as_off(tmp_path: Path) -> None:
    """The deployment passes --webhook-file so the URL stays out of argv.

    Absent and empty both mean "no webhook" rather than an error: the alerts
    service has to start on a host where the operator never supplied one.
    """
    missing = tmp_path / "nope"
    assert resolve_webhook(_args(tmp_path, webhook_file=str(missing))) is None

    empty = tmp_path / "empty"
    empty.write_text("")
    assert resolve_webhook(_args(tmp_path, webhook_file=str(empty))) is None

    configured = tmp_path / "hook"
    configured.write_text("  https://hooks.example/services/T/B/xyz\n")
    assert resolve_webhook(_args(tmp_path, webhook_file=str(configured))) == "https://hooks.example/services/T/B/xyz"

    # The file wins over an argv value when both are present, and an empty file
    # falls back rather than silently disabling a webhook the operator did pass.
    assert resolve_webhook(_args(tmp_path, webhook="https://argv/x", webhook_file=str(configured))) == "https://hooks.example/services/T/B/xyz"
    assert resolve_webhook(_args(tmp_path, webhook="https://argv/x", webhook_file=str(empty))) == "https://argv/x"


def test_cli_posts_to_the_webhook_named_by_the_file(tmp_path: Path) -> None:
    hook = tmp_path / "hook"
    hook.write_text("http://hooks/from-file\n")
    out = io.StringIO()
    # The shared mock records bodies, not URLs, and the URL is the point here.
    seen: list[str] = []

    def client_for(text: str) -> httpx.Client:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                seen.append(str(request.url))
                return httpx.Response(204)
            return httpx.Response(200, text=text)

        return httpx.Client(transport=httpx.MockTransport(handler))

    # Prime the state file so the second sample has a window to compute a rate over.
    run_once(_args(tmp_path), client_for(metrics_text(turn_2xx=100, turn_5xx=0)), now=0.0, out=io.StringIO())

    code = run_once(
        _args(tmp_path, webhook_file=str(hook)),
        client_for(metrics_text(turn_2xx=110, turn_5xx=5)),
        now=300.0,
        out=out,
    )

    assert code == EXIT_PAGE
    assert seen == ["http://hooks/from-file"]
    record = json.loads(out.getvalue().splitlines()[0])
    assert record["webhook_delivered"] is True


def test_webhook_payload_carries_a_text_summary_for_slack() -> None:
    """Slack rejects a body without `text` or `blocks` as invalid_payload, and
    ignores keys it does not recognise. Found live: the alert fired correctly
    and reported webhook_delivered false because the raw record has no `text`.
    """
    from app.alerts_cli import webhook_payload

    record = {"ts": 1.0, "event": "alert", "name": "tool_failure_rate", "severity": "page",
              "message": "Tool medications returned unavailable on 100.00% of 5 calls; a service path is broken.",
              "value": 1.0, "threshold": 0.5}
    payload = webhook_payload(record)

    assert payload["text"] == "[PAGE] tool_failure_rate: Tool medications returned unavailable on 100.00% of 5 calls; a service path is broken."
    # Every structured field survives for a non-Slack receiver.
    for key, value in record.items():
        assert payload[key] == value


def test_webhook_payload_channel_override_is_opt_in() -> None:
    from app.alerts_cli import webhook_payload

    record = {"event": "alert", "name": "turn_latency", "severity": "warn", "message": "slow"}
    assert "channel" not in webhook_payload(record)
    assert webhook_payload(record, "#andre-batista-alerts")["channel"] == "#andre-batista-alerts"
