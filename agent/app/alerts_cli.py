"""Command line for the PRD alerts: scrape /metrics, evaluate, print one JSON
line per alert (a heartbeat line when none), keep the previous sample in a
state file for rate math.

    python -m app.alerts --url https://HOST/copilot-api/metrics \
        [--state /path/state.json] [--interval 300] [--ready-url URL] \
        [--webhook URL] [--timeout 10]

Exit codes (one-shot mode): 0 no page, 2 a page-severity alert fired, 1 the
metrics endpoint could not be fetched. With --interval the process loops and
only exits on a signal. Output holds metric values and generic messages only;
there is no PHI in /metrics to leak.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from .alerts import Alert, Sample, evaluate, evaluate_readiness, parse_metrics, worst_severity

EXIT_OK = 0
EXIT_FETCH_FAILED = 1
EXIT_PAGE = 2


def fetch_metrics(url: str, client: httpx.Client, now: float | None = None) -> Sample:
    response = client.get(url)
    response.raise_for_status()
    return parse_metrics(response.text, fetched_at=now if now is not None else time.time())


def fetch_ready(url: str, client: httpx.Client) -> bool:
    """True when /ready answers 200. A transport failure counts as not ready."""
    try:
        return client.get(url).status_code == 200
    except httpx.HTTPError:
        return False


def load_state(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def save_state(path: Path | None, state: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(path)


def emit(record: dict[str, Any], out=None) -> None:
    print(json.dumps(record, sort_keys=True), file=out or sys.stdout, flush=True)


def post_webhook(url: str, payload: dict[str, Any], client: httpx.Client) -> bool:
    try:
        client.post(url, json=payload).raise_for_status()
        return True
    except httpx.HTTPError:
        return False


def run_once(args: argparse.Namespace, client: httpx.Client, now: float | None = None, out=None) -> int:
    """One scrape-evaluate-report cycle. Returns the exit code."""
    now = time.time() if now is None else now
    state_path = Path(args.state) if args.state else None
    state = load_state(state_path)
    previous = Sample.from_json(state["previous"]) if state.get("previous") else None

    try:
        sample = fetch_metrics(args.url, client, now)
    except httpx.HTTPError as exc:
        emit({"ts": now, "event": "fetch_failed", "url": args.url, "error": type(exc).__name__}, out)
        return EXIT_FETCH_FAILED

    alerts: list[Alert] = evaluate(sample, previous)
    failing_since = state.get("ready_failing_since")
    if args.ready_url:
        ready_alert, failing_since = evaluate_readiness(fetch_ready(args.ready_url, client), now, failing_since)
        if ready_alert:
            alerts.append(ready_alert)

    save_state(state_path, {"previous": sample.to_json(), "ready_failing_since": failing_since})

    interval = None if previous is None else round(now - previous.fetched_at, 1)
    for alert in alerts:
        record = {"ts": now, "event": "alert", "rate_window_seconds": interval, **alert.to_dict()}
        if args.webhook:
            record["webhook_delivered"] = post_webhook(args.webhook, record, client)
        emit(record, out)
    if not alerts:
        emit({"ts": now, "event": "heartbeat", "rate_window_seconds": interval, "turns_5m": sample.get("copilot_turn_latency_count_5m", 0.0)}, out)

    return EXIT_PAGE if worst_severity(alerts) == "page" else EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.alerts", description="Evaluate the PRD runtime alerts against the agent's /metrics endpoint.")
    parser.add_argument("--url", required=True, help="Metrics URL, for example https://HOST/copilot-api/metrics")
    parser.add_argument("--state", default=None, help="JSON file holding the previous sample; enables rate math across runs")
    parser.add_argument("--interval", type=float, default=0.0, help="Seconds between scrapes; 0 (default) runs once and exits")
    parser.add_argument("--ready-url", default=None, help="Optional /ready URL for the 'not ready for 2 minutes' page rule")
    parser.add_argument("--webhook", default=None, help="Optional URL that receives each alert as a JSON POST (off by default)")
    parser.add_argument("--timeout", type=float, default=10.0, help="HTTP timeout in seconds")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with httpx.Client(timeout=args.timeout, headers={"User-Agent": "copilot-alerts/1"}) as client:
        if args.interval <= 0:
            return run_once(args, client)
        while True:
            run_once(args, client)
            time.sleep(args.interval)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
