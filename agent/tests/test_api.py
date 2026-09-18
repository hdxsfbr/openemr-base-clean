from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from app import main as main_module
from app.delegation import mint_for_tests
from app.graph.build import build_graph
from app.graph.nodes import Runtime
from conftest import TEST_SECRET, FakeGateway, FakeModel

CID = "57b815a321edb1bbab13699dec3adb20"


@pytest.fixture()
def client(secret_file: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = main_module.app
    # Bypass the lifespan: inject a graph with the fake runtime and an in-memory checkpointer.
    app.state.graph = build_graph(Runtime(gateway=FakeGateway(), model=FakeModel(claims=[]), today=lambda: __import__("datetime").date(2026, 9, 15)), checkpointer=InMemorySaver())
    return TestClient(app)


def test_turn_requires_token_and_matching_conversation(client: TestClient) -> None:
    r = client.post(f"/v1/conversations/{CID}/turns", json={"message": "hi"})
    assert r.status_code == 401 and r.json()["code"] == "unauthorized"
    other = mint_for_tests("0" * 32, "f" * 16, TEST_SECRET)
    r = client.post(f"/v1/conversations/{CID}/turns", json={"message": "hi"}, headers={"X-Copilot-Token": other})
    assert r.status_code == 403
    bad = other[:-4] + "AAAA"
    r = client.post(f"/v1/conversations/{CID}/turns", json={"message": "hi"}, headers={"X-Copilot-Token": bad})
    assert r.status_code == 403


def test_turn_returns_contract_shaped_response_with_correlation_id(client: TestClient) -> None:
    token = mint_for_tests(CID, "abcdefabcdefabcd", TEST_SECRET)
    r = client.post(f"/v1/conversations/{CID}/turns", json={"message": "What changed since the last visit?", "correlation_id": "conv1234abcd.1"}, headers={"X-Copilot-Token": token})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["turn_type"] == "uc01_first" and body["correlation_id"] == "conv1234abcd.1"
    assert r.headers["X-Correlation-Id"] == "conv1234abcd.1"
    assert body["verification"]["outcome"] in ("passed", "partial")
    assert {e["tool"] for e in body["evidence"]} >= {"encounters", "lab_results"}
    assert body["contract_version"] == "1.2.0"
    assert body["summary"] and body["summary_basis"] in ("model", "deterministic")
    assert body["answered_at"] and body["answered_at"].endswith("Z")
    assert isinstance(body["suggestions"], list) and body["suggestions"] and all(s.endswith("?") for s in body["suggestions"])
    got = client.get(f"/v1/conversations/{CID}", headers={"X-Copilot-Token": token})
    assert got.status_code == 200 and len(got.json()["turns"]) == 1


def test_turn_streams_evidence_then_claims(client: TestClient) -> None:
    token = mint_for_tests(CID, "abcdefabcdefabce", TEST_SECRET)
    with client.stream("POST", f"/v1/conversations/{CID}/turns", json={"message": "What changed since the last visit?", "stream": True}, headers={"X-Copilot-Token": token}) as r:
        assert r.status_code == 200
        text = "".join(r.iter_text())
    verify_progress = text.index('"node": "verify"')
    assert text.index("event: evidence") < verify_progress < text.index("event: claims") < text.index("event: done")
    # No claim text leaves before the claims event: progress events carry node names only.
    progress_lines = [line for line in text.splitlines() if line.startswith("data:") and '"node"' in line]
    assert progress_lines and all("text" not in line for line in progress_lines)


def test_invalid_body_is_400_and_metrics_exposed(client: TestClient) -> None:
    token = mint_for_tests(CID, "abcdefabcdefabcf", TEST_SECRET)
    r = client.post(f"/v1/conversations/{CID}/turns", json={"message": "", "pid": 1}, headers={"X-Copilot-Token": token})
    assert r.status_code == 400
    m = client.get("/metrics")
    assert m.status_code == 200 and "copilot_turns_total" in m.text


# Operational controls at the API: the queue-depth gauge (A2), the verification counter and the
# tool-call reason label (A3, A5), the per-conversation rate limit (A7b), and the failure paths.

from app.metrics import metrics  # noqa: E402

CID_FLIGHT = "67b815a321edb1bbab13699dec3adb21"
CID_RATE = "77b815a321edb1bbab13699dec3adb22"
CID_FAIL = "87b815a321edb1bbab13699dec3adb23"


class _ObservedGraph:
    """Wraps the compiled graph and records `copilot_turns_in_flight` while a turn is running."""

    def __init__(self, graph) -> None:
        self.graph = graph
        self.seen: list[int] = []

    async def ainvoke(self, *args, **kwargs):
        self.seen.append(metrics.turns_in_flight)
        return await self.graph.ainvoke(*args, **kwargs)

    async def astream(self, *args, **kwargs):
        self.seen.append(metrics.turns_in_flight)
        async for update in self.graph.astream(*args, **kwargs):
            yield update

    def __getattr__(self, name: str):
        return getattr(self.graph, name)


class _BrokenGraph:
    async def ainvoke(self, *args, **kwargs):
        raise RuntimeError("graph exploded")

    async def astream(self, *args, **kwargs):
        raise RuntimeError("graph exploded")
        yield  # pragma: no cover - makes this an async generator


def test_health_leaves_turns_in_flight_at_zero(client: TestClient) -> None:
    for _ in range(3):
        assert client.get("/health").status_code == 200
    assert metrics.turns_in_flight == 0
    text = client.get("/metrics").text
    assert "\ncopilot_turns_in_flight 0\n" in text
    assert "\ncopilot_in_flight 1\n" in text  # the scrape itself is an HTTP request in flight; turns are not


def test_turn_increments_turns_in_flight_then_returns_to_zero(client: TestClient) -> None:
    observed = _ObservedGraph(main_module.app.state.graph)
    main_module.app.state.graph = observed
    token = mint_for_tests(CID_FLIGHT, "b" * 16, TEST_SECRET)
    r = client.post(f"/v1/conversations/{CID_FLIGHT}/turns", json={"message": "What changed since the last visit?"}, headers={"X-Copilot-Token": token})
    assert r.status_code == 200, r.text
    assert observed.seen == [1] and metrics.turns_in_flight == 0
    token = mint_for_tests(CID_FLIGHT, "c" * 16, TEST_SECRET)
    with client.stream("POST", f"/v1/conversations/{CID_FLIGHT}/turns", json={"message": "Which notes mention amlodipine?", "stream": True}, headers={"X-Copilot-Token": token}) as r:
        assert r.status_code == 200
        text = "".join(r.iter_text())
    assert "event: done" in text
    assert observed.seen == [1, 1] and metrics.turns_in_flight == 0
    assert "\ncopilot_turns_in_flight 0\n" in client.get("/metrics").text


def test_turn_counts_verification_outcome_and_tool_reasons(client: TestClient) -> None:
    before = metrics.verification["passed"]
    token = mint_for_tests(CID_FLIGHT, "d" * 16, TEST_SECRET)
    r = client.post(f"/v1/conversations/{CID_FLIGHT}/turns", json={"message": "What changed since the last visit?"}, headers={"X-Copilot-Token": token})
    assert r.status_code == 200 and r.json()["verification"]["outcome"] == "passed"
    assert metrics.verification["passed"] == before + 1
    text = client.get("/metrics").text
    assert 'copilot_verification_total{outcome="passed"}' in text
    assert 'copilot_tool_calls_total{tool="encounters",status="ok",reason="none"}' in text
    assert "copilot_verification_total{outcome=\"other\"}" not in text


def test_third_turn_in_a_minute_is_429_rate_limited(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import api as api_module

    monkeypatch.setattr(api_module.settings, "turns_per_minute", 2)
    api_module._turn_times.pop(CID_RATE, None)
    before = metrics.denials["rate_limited"]
    statuses = []
    for turn_id in ("e" * 16, "f" * 16, "a" * 15 + "0"):
        token = mint_for_tests(CID_RATE, turn_id, TEST_SECRET)
        r = client.post(f"/v1/conversations/{CID_RATE}/turns", json={"message": "What changed since the last visit?"}, headers={"X-Copilot-Token": token})
        statuses.append(r.status_code)
    assert statuses == [200, 200, 429]
    assert r.json()["code"] == "rate_limited" and r.headers["X-Correlation-Id"]
    assert metrics.denials["rate_limited"] == before + 1
    assert 'copilot_denials_total{reason="rate_limited"}' in client.get("/metrics").text
    assert metrics.turns_in_flight == 0


def test_turn_failure_is_generic_500_and_leaves_no_turn_in_flight(client: TestClient) -> None:
    main_module.app.state.graph = _BrokenGraph()
    before = metrics.turns["failed"]
    token = mint_for_tests(CID_FAIL, "a" * 15 + "1", TEST_SECRET)
    r = client.post(f"/v1/conversations/{CID_FAIL}/turns", json={"message": "hi there"}, headers={"X-Copilot-Token": token})
    assert r.status_code == 500 and r.json()["code"] == "internal_error" and "exploded" not in r.text
    token = mint_for_tests(CID_FAIL, "a" * 15 + "2", TEST_SECRET)
    with client.stream("POST", f"/v1/conversations/{CID_FAIL}/turns", json={"message": "hi there", "stream": True}, headers={"X-Copilot-Token": token}) as r:
        text = "".join(r.iter_text())
    assert "event: error" in text and '"error_class": "RuntimeError"' in text and "exploded" not in text
    assert metrics.turns["failed"] == before + 2
    assert metrics.turns_in_flight == 0
