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
    assert body["contract_version"] == "1.0.0"
    got = client.get(f"/v1/conversations/{CID}", headers={"X-Copilot-Token": token})
    assert got.status_code == 200 and len(got.json()["turns"]) == 1


def test_turn_streams_evidence_then_claims(client: TestClient) -> None:
    token = mint_for_tests(CID, "abcdefabcdefabce", TEST_SECRET)
    with client.stream("POST", f"/v1/conversations/{CID}/turns", json={"message": "What changed since the last visit?", "stream": True}, headers={"X-Copilot-Token": token}) as r:
        assert r.status_code == 200
        text = "".join(r.iter_text())
    assert text.index("event: evidence") < text.index("event: claims") < text.index("event: done")


def test_invalid_body_is_400_and_metrics_exposed(client: TestClient) -> None:
    token = mint_for_tests(CID, "abcdefabcdefabcf", TEST_SECRET)
    r = client.post(f"/v1/conversations/{CID}/turns", json={"message": "", "pid": 1}, headers={"X-Copilot-Token": token})
    assert r.status_code == 400
    m = client.get("/metrics")
    assert m.status_code == 200 and "copilot_turns_total" in m.text
