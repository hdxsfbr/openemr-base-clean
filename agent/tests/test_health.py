from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.readiness import DependencyStatus
from app.settings import Settings


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(main_module, "_ready_cache", None)
    return TestClient(main_module.app)


def test_health_is_alive_and_echoes_correlation_id(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Correlation-Id": "abc-12345"})
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["X-Correlation-Id"] == "abc-12345"


def test_health_mints_correlation_id_when_absent_or_invalid(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Correlation-Id": "bad id with spaces"})
    minted = response.headers["X-Correlation-Id"]
    assert minted != "bad id with spaces"
    assert len(minted) == 16


def test_ready_is_503_when_a_dependency_fails(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    test_settings = Settings(
        gateway_ping_url="http://127.0.0.1:9/nope",
        state_dir=tmp_path / "state",
        anthropic_api_key_file=tmp_path / "missing",
    )
    monkeypatch.setattr(main_module, "settings", test_settings)
    response = client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    names = {d["name"]: d for d in body["dependencies"]}
    assert names["openemr_gateway"]["ok"] is False
    assert names["llm_provider"]["detail"] == "not_configured"
    assert names["state_store"]["ok"] is True


def test_ready_is_200_when_all_dependencies_pass(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_evaluate(_settings):
        from app.readiness import ReadinessReport
        import time

        deps = [DependencyStatus(n, True, "ok") for n in ("openemr_gateway", "llm_provider", "tracer", "delegation_secret", "state_store")]
        return ReadinessReport(ok=True, checked_at=time.time(), dependencies=deps)

    monkeypatch.setattr(main_module, "evaluate", fake_evaluate)
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
