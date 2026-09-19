"""Offline tests for the load driver's pure functions and its virtual-user flow.

Nothing here opens a socket: the end-to-end tests drive `run_virtual_user` through
httpx.MockTransport, a fake OpenEMR plus agent that answers in-process, so the
handshake, the SSE path and the report schema are checked without the deployment
(FINAL_PUSH_PLAN.md invariant 5: no model budget is spent by a test).

    agent/.venv/bin/python -m pytest -q evals/load/test_run_load.py
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

import run_load as L

# ---------------------------------------------------------------- fixtures (synthetic; no PHI)

OLD_METRICS_BEFORE = """# TYPE copilot_tool_calls_total counter
copilot_tool_calls_total{tool="problems",status="ok"} 100
copilot_tool_calls_total{tool="lab_results",status="ok"} 90
copilot_tool_calls_total{tool="lab_results",status="unavailable"} 5
# TYPE copilot_denials_total counter
copilot_denials_total{reason="rate_limited"} 2
# TYPE copilot_turns_total counter
copilot_turns_total{status="complete"} 40
copilot_in_flight 0
"""

OLD_METRICS_AFTER = """# TYPE copilot_tool_calls_total counter
copilot_tool_calls_total{tool="problems",status="ok"} 150
copilot_tool_calls_total{tool="lab_results",status="ok"} 120
copilot_tool_calls_total{tool="lab_results",status="unavailable"} 12
copilot_tool_calls_total{tool="clinical_notes",status="unavailable"} 3
# TYPE copilot_denials_total counter
copilot_denials_total{reason="rate_limited"} 2
copilot_denials_total{reason="conversation_mismatch"} 1
# TYPE copilot_turns_total counter
copilot_turns_total{status="complete"} 55
copilot_turns_total{status="partial"} 4
copilot_in_flight 3
"""

NEW_METRICS_BEFORE = """# TYPE copilot_tool_calls_total counter
copilot_tool_calls_total{tool="problems",status="ok",reason="none"} 10
copilot_tool_calls_total{tool="lab_results",status="unavailable",reason="timeout"} 1
"""

NEW_METRICS_AFTER = """# TYPE copilot_tool_calls_total counter
copilot_tool_calls_total{tool="problems",status="ok",reason="none"} 30
copilot_tool_calls_total{tool="lab_results",status="unavailable",reason="timeout"} 7
copilot_tool_calls_total{tool="lab_results",status="unavailable",reason="http_5xx"} 2
copilot_tool_calls_total{tool="medications",status="unavailable",reason="forbidden"} 1
copilot_tool_calls_total{tool="medications",status="ok",reason="none"} 4
"""


def turn(scenario: str = "AF-DQ-A2", turn_type: str = "first", ms: float = 1000.0, http: int | None = 200, error: str | None = None, status: str | None = "complete", ttfe: float | None = None, unavailable: int = 0, cid: str | None = None) -> L.TurnSample:
    return L.TurnSample(scenario, "audit-physician", turn_type, ms, http, error, status, stream=ttfe is not None, ttfe_ms=ttfe, evidence_unavailable=unavailable, usage={"input_tokens": 100, "output_tokens": 50, "cache_read_tokens": 20, "model_calls": 2}, correlation_id=cid)


def step(name: str, ms: float, http: int | None = 200, scenario: str = "AF-DQ-A2", error: str | None = None) -> L.StepSample:
    return L.StepSample(name, scenario, "physician", ms, http, error)


# ---------------------------------------------------------------- percentiles and buckets


def test_percentile_matches_the_harness_formula() -> None:
    values = [float(i) for i in range(101)]
    assert L.percentile(values, 0.5) == 50.0
    assert L.percentile(values, 0.95) == 95.0
    assert L.percentile(values, 0.99) == 99.0
    assert L.percentile([7.0], 0.99) == 7.0
    assert L.percentile([], 0.5) is None


def test_distribution_shape() -> None:
    d = L.distribution([3.0, 1.0, 2.0])
    assert d == {"n": 3, "p50": 2.0, "p95": 3.0, "p99": 3.0, "max": 3.0}
    assert L.distribution([]) == {"n": 0, "p50": None, "p95": None, "p99": None, "max": None}


@pytest.mark.parametrize(
    ("http", "error", "bucket"),
    [(200, None, "ok"), (403, None, "denied"), (401, None, "denied"), (429, None, "429"), (504, None, "504"), (500, None, "5xx"), (502, None, "5xx"), (400, None, "other"), (None, "ReadTimeout", "transport"), (200, "RemoteProtocolError", "transport")],
)
def test_classify_turn(http: int | None, error: str | None, bucket: str) -> None:
    assert L.classify_turn(http, error) == bucket


def test_turn_status_folds_non_200_into_failed_and_403_into_denied() -> None:
    assert L.turn_status(turn(status="partial")) == "partial"
    assert L.turn_status(turn(http=504, status=None)) == "failed"
    assert L.turn_status(turn(http=403, status="denied")) == "denied"
    assert L.turn_status(turn(http=200, status="weird")) == "failed"
    assert L.turn_status(turn(http=None, error="ConnectError")) == "failed"


# ---------------------------------------------------------------- scheduling


def test_ramp_offsets_spread_users_over_the_ramp() -> None:
    assert L.ramp_offsets(1, 30.0) == [0.0]
    assert L.ramp_offsets(3, 30.0) == [0.0, 15.0, 30.0]
    assert L.ramp_offsets(4, 0.0) == [0.0, 0.0, 0.0, 0.0]
    assert L.ramp_offsets(0, 30.0) == []


def test_assign_alternates_users_and_round_robins_charts() -> None:
    got = [L.assign(i, L.DEFAULT_SCENARIOS) for i in range(6)]
    assert [u for u, _ in got] == ["audit-physician", "physician"] * 3
    assert [s for _, s in got] == ["AF-DQ-A2", "AF-DQ-N", "AF-HEAVY"] * 2


def test_parse_levels_rejects_junk() -> None:
    assert L.parse_levels("1, 10,50") == [1, 10, 50]
    with pytest.raises(Exception):
        L.parse_levels("0")
    with pytest.raises(Exception):
        L.parse_levels("ten")


def test_cohort_file_is_checked_against_the_builtin_map(tmp_path: Path) -> None:
    good = tmp_path / "cohort.json"
    good.write_text(json.dumps({"AF-DQ-A2": 900001, "AF-DQ-N": 900018, "AF-HEAVY": 900023, "AF-X": 1}))
    assert L.load_cohort(good) == L.DEFAULT_SCENARIOS
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"AF-DQ-A2": 1, "AF-DQ-N": 900018, "AF-HEAVY": 900023}))
    with pytest.raises(ValueError):
        L.load_cohort(bad)
    assert L.load_cohort(tmp_path / "missing.json") == L.DEFAULT_SCENARIOS


def test_repo_cohort_agrees_with_the_driver() -> None:
    assert L.load_cohort(L.DEFAULT_COHORT_FILE) == {"AF-DQ-A2": 900001, "AF-DQ-N": 900018, "AF-HEAVY": 900023}


# ---------------------------------------------------------------- SSE and metrics parsing


def test_sse_framer_is_incremental() -> None:
    f = L.SSEFramer()
    assert f.feed("event: evidence") is None and f.feed('data: {"a": 1}') is None
    assert f.feed("") == ("evidence", '{"a": 1}')
    assert f.feed("") is None  # a second blank line is not a frame
    assert f.feed("data: tail") is None and f.flush() == ("", "tail") and f.flush() is None


def test_parse_sse_frames() -> None:
    lines = ["event: evidence", 'data: {"evidence": []}', "", "event: progress", 'data: {"node": "plan"}', "", "event: claims", "data: {", 'data: "status": "complete"}', "", "event: done", 'data: {"status": "complete"}']
    assert list(L.parse_sse(lines)) == [("evidence", '{"evidence": []}'), ("progress", '{"node": "plan"}'), ("claims", '{\n"status": "complete"}'), ("done", '{"status": "complete"}')]


def test_parse_metrics_keeps_every_label() -> None:
    series = L.parse_metrics(NEW_METRICS_AFTER + 'copilot_x{a="q\\"uote"} 1.5 1700000000\ncopilot_nan{} NaN\nbad line\n')
    assert series["copilot_tool_calls_total"][1] == ({"tool": "lab_results", "status": "unavailable", "reason": "timeout"}, 7.0)
    assert series["copilot_x"] == [({"a": 'q"uote'}, 1.5)]
    assert "bad" not in series


def test_counter_deltas_handle_new_series_and_resets() -> None:
    deltas = dict((frozenset(l.items()), v) for l, v in L.counter_deltas(OLD_METRICS_BEFORE, OLD_METRICS_AFTER, "copilot_tool_calls_total"))
    assert deltas[frozenset({"tool": "problems", "status": "ok"}.items())] == 50.0
    assert deltas[frozenset({"tool": "clinical_notes", "status": "unavailable"}.items())] == 3.0
    reset = L.counter_deltas('c{a="1"} 100\n', 'c{a="1"} 4\n', "c")
    assert reset == [({"a": "1"}, 4.0)]
    assert L.counter_deltas(None, None, "c") == []


def test_tool_unavailable_with_the_old_label_set_aggregates_as_unlabelled() -> None:
    got = L.tool_unavailable_deltas(OLD_METRICS_BEFORE, OLD_METRICS_AFTER)
    assert got == {"calls_total": 90, "total": 10, "by_reason": {"unlabelled": 10}, "by_tool": {"clinical_notes": {"unlabelled": 3}, "lab_results": {"unlabelled": 7}}}


def test_tool_unavailable_with_the_reason_label_splits_by_reason() -> None:
    got = L.tool_unavailable_deltas(NEW_METRICS_BEFORE, NEW_METRICS_AFTER)
    assert got["calls_total"] == 33
    assert got["total"] == 9
    assert got["by_reason"] == {"forbidden": 1, "http_5xx": 2, "timeout": 6}
    assert got["by_tool"] == {"lab_results": {"http_5xx": 2, "timeout": 6}, "medications": {"forbidden": 1}}


def test_labelled_counter_by() -> None:
    assert L.labelled_counter_by(OLD_METRICS_BEFORE, OLD_METRICS_AFTER, "copilot_denials_total", "reason") == {"conversation_mismatch": 1}
    assert L.labelled_counter_by(OLD_METRICS_BEFORE, OLD_METRICS_AFTER, "copilot_turns_total", "status") == {"complete": 15, "partial": 4}
    assert L.labelled_counter_by(None, None, "copilot_turns_total", "status") == {}


# ---------------------------------------------------------------- level summary and schema


def synthetic_vus() -> list[L.VirtualUserResult]:
    a = L.VirtualUserResult(0, "audit-physician", "AF-DQ-A2", steps=[step("login", 300), step("chart_open", 800), step("session", 50), step("start", 60), step("ticket", 40), step("ticket", 45), step("ticket", 42), step("history", 70)], turns=[turn(ms=12000, ttfe=900, cid="corr-a1"), turn(turn_type="followup", ms=20000, status="partial", unavailable=1, cid="corr-a2")])
    b = L.VirtualUserResult(1, "physician", "AF-DQ-N", steps=[step("login", 310, scenario="AF-DQ-N"), step("chart_open", 900, scenario="AF-DQ-N"), step("session", 55, scenario="AF-DQ-N"), step("start", 65, scenario="AF-DQ-N"), step("ticket", 41, scenario="AF-DQ-N"), step("ticket", 43, scenario="AF-DQ-N")], turns=[turn("AF-DQ-N", ms=45000, http=504, status=None), turn("AF-DQ-N", "followup", ms=100, http=None, error="ReadTimeout", status=None)])
    c = L.VirtualUserResult(2, "audit-physician", "AF-HEAVY", steps=[step("login", 305, scenario="AF-HEAVY"), step("chart_open", 1500, http=200, scenario="AF-HEAVY"), step("session", 52, scenario="AF-HEAVY"), step("start", 61, scenario="AF-HEAVY"), step("ticket", 44, scenario="AF-HEAVY")], turns=[turn("AF-HEAVY", ms=500, http=403, status="denied")], failed_at="ticket", error="HTTP 403")
    d = L.VirtualUserResult(3, "physician", "AF-DQ-A2", steps=[step("login", 2000, http=200)], failed_at="login", error="HTTP 200")
    return [a, b, c, d]


def test_summarize_level_error_split_status_share_and_denials() -> None:
    lv = L.summarize_level(4, synthetic_vus(), OLD_METRICS_BEFORE, OLD_METRICS_AFTER, "2026-09-19T00:00:00+00:00", "2026-09-19T00:02:00+00:00", 120.0, L.DEFAULT_SCENARIOS)
    assert lv["users"] == 4
    assert lv["vus"] == {"total": 4, "completed": 2, "failed": 2}  # b kept going after its transport failure
    assert lv["failed_at"] == {"login": 1, "ticket": 1}
    assert lv["turns"] == 5
    assert lv["errors"] == {"5xx": 0, "504": 1, "429": 0, "transport": 1, "other": 0, "total": 2, "rate": 0.4}
    assert lv["denials"]["turn_http_401_403"] == 1
    assert lv["denials"]["metrics_by_reason"] == {"conversation_mismatch": 1}
    assert lv["status_counts"] == {"complete": 1, "partial": 1, "fallback": 0, "failed": 2, "denied": 1}
    assert lv["status_share"] == {"complete": 0.2, "partial": 0.2, "fallback": 0.0, "failed": 0.4, "denied": 0.2}
    assert lv["latency_ms"]["turn"]["n"] == 4  # the transport failure has no latency
    assert lv["latency_ms"]["turn"]["max"] == 45000.0
    assert lv["latency_ms"]["turn_first"]["n"] == 3 and lv["latency_ms"]["turn_followup"]["n"] == 1
    assert lv["latency_ms"]["ttfe"] == {"n": 1, "p50": 900.0, "p95": 900.0, "p99": 900.0, "max": 900.0}
    assert lv["latency_ms"]["chart_open"]["n"] == 3 and lv["latency_ms"]["ticket"]["n"] == 6
    assert lv["by_scenario"]["AF-DQ-N"]["errors"]["total"] == 2
    assert lv["by_scenario"]["AF-HEAVY"]["status_counts"]["denied"] == 1
    assert lv["by_scenario"]["AF-DQ-A2"]["latency_ms"]["turn"]["n"] == 2
    assert lv["tool_unavailable"]["by_reason"] == {"unlabelled": 10}
    assert lv["server_turns_by_status"] == {"complete": 15, "partial": 4}
    assert lv["client_tool_unavailable"] == 1
    assert lv["usage"] == {"input_tokens": 500, "output_tokens": 250, "cache_read_tokens": 100, "model_calls": 10}
    # 20 cache-read of 120 reported prompt tokens on every synthetic turn, whatever its type.
    assert lv["prompt_cache"] == {"read_fraction": 0.167, "first": 0.167, "followup": 0.167}
    assert lv["step_http"]["turn"] == {"200": 2, "403": 1, "504": 1, "transport": 1}
    assert lv["metrics"] == {"before": True, "after": True}
    assert lv["duration_s"] == 120.0


def test_vu_records_carry_correlation_ids_and_nothing_secret() -> None:
    lv = L.summarize_level(4, synthetic_vus(), None, None, "t0", "t1", 2.0, L.DEFAULT_SCENARIOS)
    records = lv["vu_records"]
    assert [r["index"] for r in records] == [0, 1, 2, 3]
    assert records[0]["user"] == "audit-physician" and records[0]["scenario"] == "AF-DQ-A2" and records[0]["completed"] is True
    assert records[0]["turns"][0] == {"type": "first", "http_status": 200, "error": None, "status": "complete", "stream": True, "ms": 12000.0, "ttfe_ms": 900.0, "correlation_id": "corr-a1"}
    assert records[0]["turns"][1]["correlation_id"] == "corr-a2" and records[0]["turns"][1]["ttfe_ms"] is None
    assert records[1]["turns"][1] == {"type": "followup", "http_status": None, "error": "ReadTimeout", "status": None, "stream": False, "ms": 100.0, "ttfe_ms": None, "correlation_id": None}
    assert records[2]["failed_at"] == "ticket" and records[2]["error"] == "HTTP 403" and records[2]["turns"][0]["http_status"] == 403
    assert records[3] == {"index": 3, "user": "physician", "scenario": "AF-DQ-A2", "completed": False, "failed_at": "login", "error": "HTTP 200", "turns": []}
    blob = json.dumps(lv)
    assert "corr-a1" in blob and '"token"' not in blob and "csrf" not in blob and "cookie" not in blob  # usage has *_tokens counts; no token field, no ticket value


def test_summarize_level_without_metrics_or_turns() -> None:
    lv = L.summarize_level(1, [L.VirtualUserResult(0, "physician", "AF-DQ-A2", failed_at="login", error="ConnectError")], None, None, "t0", "t1", 1.0, L.DEFAULT_SCENARIOS)
    assert lv["turns"] == 0
    assert lv["errors"]["rate"] == 0.0
    assert lv["status_share"] == {s: 0.0 for s in L.TURN_STATUSES}
    assert lv["tool_unavailable"] == {"calls_total": 0, "total": 0, "by_reason": {}, "by_tool": {}}
    assert lv["metrics"] == {"before": False, "after": False}


def config(**overrides: Any) -> L.RunConfig:
    base = dict(base_url="https://example.test", scenarios=dict(L.DEFAULT_SCENARIOS), fault=None, ramp_seconds=0.0, stream_levels=frozenset({1, 10}), metrics_url=None, pause_seconds=0.0)
    base.update(overrides)
    return L.RunConfig(**base)


def test_build_results_has_the_documented_top_level_keys_and_serializes() -> None:
    lv = L.summarize_level(4, synthetic_vus(), None, OLD_METRICS_AFTER, "t0", "t1", 2.0, L.DEFAULT_SCENARIOS)
    results = L.build_results(commit="abc1234", timestamp="2026-09-19T00:00:00+00:00", label="baseline", cfg=config(fault="model"), levels=[lv])
    assert list(results) == ["schema_version", "kind", "commit", "timestamp", "label", "base_url", "fault", "ramp_seconds", "stream_levels", "users_levels", "scenarios", "messages", "interrupted", "levels"]
    assert results["interrupted"] is False
    assert results["schema_version"] == L.SCHEMA_VERSION and results["kind"] == "load"
    assert results["users_levels"] == [4] and results["stream_levels"] == [1, 10] and results["fault"] == "model"
    level_keys = ["users", "started_at", "finished_at", "duration_s", "vus", "failed_at", "latency_ms", "by_scenario", "turns", "errors", "denials", "status_counts", "status_share", "server_turns_by_status", "tool_unavailable", "client_tool_unavailable", "usage", "prompt_cache", "step_http", "metrics", "vu_records"]
    assert list(results["levels"][0]) == level_keys
    assert set(results["levels"][0]["latency_ms"]) == set(L.STEP_NAMES)
    assert json.loads(json.dumps(results)) == results


def test_render_markdown_lists_levels_and_scenarios() -> None:
    lv = L.summarize_level(4, synthetic_vus(), OLD_METRICS_BEFORE, OLD_METRICS_AFTER, "t0", "t1", 2.0, L.DEFAULT_SCENARIOS)
    md = L.render_markdown(L.build_results(commit="abc1234", timestamp="2026-09-19T00:00:00+00:00", label="", cfg=config(), levels=[lv]))
    assert "## 4 users" in md
    assert "| AF-HEAVY |" in md and "| AF-DQ-N |" in md and "| all |" in md
    assert "unavailable 10 by reason: unlabelled=10" in md
    assert "504=1" in md and "transport=1" in md
    assert "csrf" not in md.lower() and "x-copilot-token" not in md.lower()
    # Columns: Scenario, VUs, Turns, Chart open, Ticket, Turn, TTFE, Errors, Denials, Status share.
    rows = {cells[0]: cells for cells in ([c.strip() for c in line.split("|")[1:-1]] for line in md.splitlines() if line.startswith("| ")) if cells[0] not in {"Scenario", "---"}}
    assert rows["all"][8] == "1" and rows["AF-HEAVY"][8] == "1" and rows["AF-DQ-A2"][8] == "0" and rows["AF-DQ-N"][8] == "0"
    assert rows["AF-HEAVY"][9] == "0% / 0% / 0% / 0% / 100%"


def test_interrupted_results_are_marked_and_rendered() -> None:
    results = L.build_results(commit="x", timestamp="t", label="", cfg=config(), levels=[], interrupted=True)
    assert results["interrupted"] is True and results["users_levels"] == []
    assert "**Interrupted run.**" in L.render_markdown(results)


def test_run_all_sink_keeps_completed_levels() -> None:
    stack = FakeStack()
    sink: list[dict[str, Any]] = []
    out = asyncio.run(L.run_all([1, 2], config(stream_levels=frozenset()), "pw", factory_for(stack), sink=sink))
    assert out is sink and [lv["users"] for lv in sink] == [1, 2]


def test_write_results_creates_json_and_md(tmp_path: Path) -> None:
    results = L.build_results(commit="abc1234", timestamp="t", label="", cfg=config(), levels=[])
    json_path, md_path = L.write_results(results, tmp_path / "out", "2026-09-19T000000Z-abc1234")
    assert json.loads(json_path.read_text())["commit"] == "abc1234"
    assert md_path.read_text().startswith("# Load run")


def test_plan_has_no_network_and_lists_every_vu() -> None:
    p = L.plan([2, 3], config(ramp_seconds=30.0))
    assert [lv["users"] for lv in p["levels"]] == [2, 3]
    assert p["levels"][0]["stream_first_turn"] is False and [v["start_after_s"] for v in p["levels"][0]["vus"]] == [0.0, 30.0]
    assert p["levels"][1]["vus"][2] == {"index": 2, "user": "audit-physician", "scenario": "AF-HEAVY", "start_after_s": 30.0}


def test_cli_has_no_password_flag_and_documents_the_required_ones() -> None:
    parser = L.build_parser()
    flags = {opt for action in parser._actions for opt in action.option_strings}
    assert "--password" not in flags
    assert {"--base-url", "--users", "--label", "--fault", "--ramp-seconds", "--password-env", "--metrics-url", "--out-dir"} <= flags
    assert L.main(["--base-url", "https://example.test", "--plan"]) == 0
    assert L.main(["--base-url", "ftp://nope", "--plan"]) == 2


def test_main_refuses_to_run_without_the_password_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOAD_TEST_PW", raising=False)
    assert L.main(["--base-url", "https://example.test", "--password-env", "LOAD_TEST_PW", "--users", "1"]) == 2


# ---------------------------------------------------------------- end to end over a fake stack (in-process)


class FakeStack:
    """Answers the handshake the way OpenEMR plus the module plus the agent do (evals/run.py Session
    and agent/app/api.py), with knobs for the failure shapes the report must classify."""

    def __init__(self, *, turn_http: int = 200, turn_status: str = "complete", stream_error: bool = False, drop_panel: bool = False, reject_login: bool = False, omit_correlation_id: bool = False, explode_for: str | None = None) -> None:
        self.turn_http = turn_http
        self.turn_status = turn_status
        self.stream_error = stream_error
        self.drop_panel = drop_panel
        self.reject_login = reject_login
        self.omit_correlation_id = omit_correlation_id  # ticket.php answers with the token only
        self.explode_for = explode_for  # this demo user's login raises a non-httpx exception (a driver bug, in-process)
        self.requests: list[tuple[str, str, dict[str, str]]] = []
        self.metrics_calls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append((request.method, path, dict(request.headers)))
        if path == "/interface/main/main_screen.php":
            assert b"clearPass=" in request.content
            if self.explode_for and parse_qs(request.content.decode()).get("authUser") == [self.explode_for]:
                raise RuntimeError("synthetic driver bug (not an httpx.HTTPError)")
            return httpx.Response(200 if self.reject_login else 302, headers={"set-cookie": "OpenEMR=fake; Path=/"})
        if path == "/interface/patient_file/summary/demographics.php":
            assert request.url.params["set_pid"] in {"900001", "900018", "900023"}
            return httpx.Response(200, text="<html>" + ("" if self.drop_panel else '<div id="copilot-panel">') + "</html>")
        if path.endswith("/api/session.php"):
            return httpx.Response(200, json={"csrf_token": "csrf-fake"})
        if path.endswith("/api/conversation.php"):
            assert json.loads(request.content)["csrf_token"] == "csrf-fake"
            return httpx.Response(200, json={"conversation_id": "conv-1"})
        if path.endswith("/api/ticket.php"):
            return httpx.Response(200, json={"token": "tok-fake"} if self.omit_correlation_id else {"token": "tok-fake", "correlation_id": "corr-1"})
        if path == "/copilot-api/v1/conversations/conv-1/turns":
            return self.turn_response(request)
        if path == "/copilot-api/v1/conversations/conv-1":
            assert request.headers["x-copilot-token"] == "tok-fake"
            return httpx.Response(200, json={"turns": []})
        if path == "/copilot-api/metrics":
            self.metrics_calls += 1
            return httpx.Response(200, text=NEW_METRICS_BEFORE if self.metrics_calls == 1 else NEW_METRICS_AFTER)
        return httpx.Response(404)

    def turn_response(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["x-copilot-token"] == "tok-fake"
        body = json.loads(request.content)
        if self.omit_correlation_id:
            assert "x-correlation-id" not in request.headers and "correlation_id" not in body  # the agent assigns its own
        else:
            assert request.headers["x-correlation-id"] == "corr-1" and body["correlation_id"] == "corr-1"
        if self.turn_http != 200:
            return httpx.Response(self.turn_http, json={"code": "x", "message": "generic", "correlation_id": "corr-1"})
        turn_body = {"status": self.turn_status, "correlation_id": "corr-1", "evidence": [{"tool": "lab_results", "status": "unavailable"}, {"tool": "problems", "status": "ok"}], "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_tokens": 1, "model_calls": 1}}
        if request.headers.get("accept") == "text/event-stream":
            assert body["stream"] is True
            frames = ["event: evidence\ndata: {\"evidence\": []}\n\n", "event: progress\ndata: {\"node\": \"retrieve\"}\n\n"]
            frames.append("event: error\ndata: {\"code\": \"internal_error\"}\n\n" if self.stream_error else f"event: claims\ndata: {json.dumps(turn_body)}\n\nevent: done\ndata: {{\"status\": \"{self.turn_status}\"}}\n\n")
            return httpx.Response(200, content="".join(frames).encode(), headers={"content-type": "text/event-stream"})
        assert body["stream"] is False
        return httpx.Response(200, json=turn_body)


def factory_for(stack: FakeStack) -> L.ClientFactory:
    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(stack.handler), base_url="https://example.test", follow_redirects=False)


def test_virtual_user_json_path_completes_the_handshake() -> None:
    stack = FakeStack(turn_status="partial")
    vu = asyncio.run(L.run_virtual_user(1, 50, config(fault="model"), "pw-not-logged", 0.0, factory_for(stack)))
    assert vu.completed and vu.user == "physician" and vu.scenario == "AF-DQ-N"
    assert [s.step for s in vu.steps] == ["login", "chart_open", "session", "start", "ticket", "ticket", "ticket", "history"]
    assert [t.turn_type for t in vu.turns] == ["first", "followup"]
    assert all(t.status == "partial" and not t.stream and t.ttfe_ms is None and t.evidence_unavailable == 1 for t in vu.turns)
    turn_headers = [h for m, p, h in stack.requests if p.endswith("/turns")]
    assert all(h["x-copilot-fault"] == "model" for h in turn_headers)
    assert all("accept" not in h or h["accept"] != "text/event-stream" for h in turn_headers)


def test_virtual_user_streams_the_first_turn_at_stream_levels() -> None:
    stack = FakeStack()
    vu = asyncio.run(L.run_virtual_user(0, 10, config(), "pw", 0.0, factory_for(stack)))
    assert vu.completed
    first, followup = vu.turns
    assert first.stream and first.ttfe_ms is not None and 0 <= first.ttfe_ms <= first.ms and first.status == "complete"
    assert first.usage["model_calls"] == 1.0 and first.correlation_id == "corr-1"
    assert not followup.stream and followup.ttfe_ms is None


def test_virtual_user_records_a_stream_error_as_failed() -> None:
    vu = asyncio.run(L.run_virtual_user(0, 1, config(), "pw", 0.0, factory_for(FakeStack(stream_error=True))))
    assert vu.completed and vu.turns[0].status == "failed" and vu.turns[0].http_status == 200


def test_virtual_user_stops_when_the_panel_is_missing_or_login_fails() -> None:
    vu = asyncio.run(L.run_virtual_user(0, 1, config(), "pw", 0.0, factory_for(FakeStack(drop_panel=True))))
    assert vu.failed_at == "chart_open" and not vu.turns and [s.step for s in vu.steps] == ["login", "chart_open"]
    vu = asyncio.run(L.run_virtual_user(0, 1, config(), "pw", 0.0, factory_for(FakeStack(reject_login=True))))
    assert vu.failed_at == "login" and vu.error == "HTTP 200"


def test_virtual_user_counts_a_504_turn_and_keeps_going() -> None:
    vu = asyncio.run(L.run_virtual_user(0, 50, config(), "pw", 0.0, factory_for(FakeStack(turn_http=504))))
    assert vu.completed and [L.classify_turn(t.http_status, t.error) for t in vu.turns] == ["504", "504"]


def test_virtual_user_transport_failure_is_recorded_not_raised() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    vu = asyncio.run(L.run_virtual_user(0, 1, config(), "pw", 0.0, lambda: httpx.AsyncClient(transport=httpx.MockTransport(boom), base_url="https://example.test")))
    assert vu.failed_at == "login" and vu.error == "ConnectError" and vu.steps[0].error == "ConnectError"


def test_virtual_user_survives_a_ticket_without_a_correlation_id() -> None:
    stack = FakeStack(omit_correlation_id=True)
    vu = asyncio.run(L.run_virtual_user(0, 1, config(), "pw", 0.0, factory_for(stack)))  # level 1 streams the first turn: both turn paths
    assert vu.completed and [t.turn_type for t in vu.turns] == ["first", "followup"]
    assert [t.correlation_id for t in vu.turns] == ["corr-1", "corr-1"]  # from the turn bodies, not the ticket
    assert all("x-correlation-id" not in h for _m, p, h in stack.requests if p.endswith("/turns"))


def test_virtual_user_records_an_unexpected_exception_instead_of_raising() -> None:
    def bug(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("synthetic driver bug (not an httpx.HTTPError)")

    vu = asyncio.run(L.run_virtual_user(0, 1, config(), "pw", 0.0, lambda: httpx.AsyncClient(transport=httpx.MockTransport(bug), base_url="https://example.test")))
    assert not vu.completed and vu.failed_at == "login" and vu.error == "RuntimeError" and vu.steps == [] and vu.turns == []


def test_run_level_keeps_the_other_vus_when_one_raises_unexpectedly() -> None:
    stack = FakeStack(explode_for="physician")  # VU 1; VU 0 is audit-physician and completes
    lv = asyncio.run(L.run_level(2, config(stream_levels=frozenset()), "pw", factory_for(stack)))
    assert lv["vus"] == {"total": 2, "completed": 1, "failed": 1} and lv["failed_at"] == {"login": 1}
    records = {r["user"]: r for r in lv["vu_records"]}
    assert records["physician"]["completed"] is False and records["physician"]["error"] == "RuntimeError"
    assert records["audit-physician"]["completed"] is True and lv["turns"] == 2


def test_run_all_reads_metrics_around_each_level_and_builds_the_schema() -> None:
    stack = FakeStack()
    cfg = config(metrics_url="https://example.test/copilot-api/metrics", stream_levels=frozenset({1}))
    levels = asyncio.run(L.run_all([1, 3], cfg, "pw", factory_for(stack)))
    assert [lv["users"] for lv in levels] == [1, 3]
    assert stack.metrics_calls == 4
    assert levels[0]["metrics"] == {"before": True, "after": True}
    assert levels[0]["tool_unavailable"]["by_reason"] == {"forbidden": 1, "http_5xx": 2, "timeout": 6}
    assert levels[0]["latency_ms"]["ttfe"]["n"] == 1 and levels[1]["latency_ms"]["ttfe"]["n"] == 0
    assert levels[1]["turns"] == 6 and levels[1]["vus"]["completed"] == 3 and levels[1]["errors"]["total"] == 0
    assert set(levels[1]["by_scenario"]) == {"AF-DQ-A2", "AF-DQ-N", "AF-HEAVY"}
    results = L.build_results(commit="x", timestamp="t", label="", cfg=cfg, levels=levels)
    assert "## 3 users" in L.render_markdown(results)
    assert [t["correlation_id"] for r in levels[1]["vu_records"] for t in r["turns"]] == ["corr-1"] * 6
    blob = json.dumps(results)
    assert "corr-1" in blob and "tok-fake" not in blob and "csrf-fake" not in blob and "clearPass" not in blob


def test_cache_read_fraction_separates_warm_follow_ups_from_cold_first_turns() -> None:
    cold = L.TurnSample("AF-DQ-A2", "physician", "first", 9000.0, 200, None, "complete", usage={"input_tokens": 4000, "output_tokens": 900, "cache_read_tokens": 0, "model_calls": 1})
    warm = L.TurnSample("AF-DQ-A2", "physician", "followup", 5000.0, 200, None, "complete", usage={"input_tokens": 400, "output_tokens": 300, "cache_read_tokens": 3600, "model_calls": 2})
    no_usage = L.TurnSample("AF-DQ-A2", "physician", "followup", 100.0, None, "ReadTimeout", None)
    lv = L.summarize_level(1, [L.VirtualUserResult(0, "physician", "AF-DQ-A2", turns=[cold, warm, no_usage])], None, None, "t0", "t1", 1.0, L.DEFAULT_SCENARIOS)
    assert lv["prompt_cache"] == {"read_fraction": 0.45, "first": 0.0, "followup": 0.9}
    assert L.cache_read_fraction([no_usage]) is None
    md = L.render_markdown(L.build_results(commit="abc1234", timestamp="t", label="", cfg=config(), levels=[lv]))
    assert "Prompt-cache read fraction: all turns 45%, first turns 0%, follow-ups 90%." in md
    lv.pop("prompt_cache")  # a results file recorded before the field existed still renders
    assert "first turns not measured" in L.render_markdown(L.build_results(commit="abc1234", timestamp="t", label="", cfg=config(), levels=[lv]))
