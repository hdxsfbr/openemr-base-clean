from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.readiness import CapabilityStatus, DependencyStatus, check_guideline, check_spend_ledger
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


def test_health_reports_exact_candidate_commit_and_immutable_runtime_image(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = Settings(
        candidate_commit="a" * 40,
        runtime_image="registry.example/agent@sha256:" + "b" * 64,
    )
    monkeypatch.setattr(main_module, "settings", candidate)

    body = client.get("/health").json()

    assert body["candidate_commit"] == "a" * 40
    assert body["runtime_image"] == "registry.example/agent@sha256:" + "b" * 64


def test_the_panels_health_check_counts_the_top_of_the_funnel(client: TestClient) -> None:
    """The chart panel says why it is checking reachability; only the three
    known events are counted, and a probe or a made-up value counts nothing."""
    from app.metrics import metrics

    before = dict(metrics.panel_events)
    for query in ("?panel=chart_open", "?panel=brief_started", "?panel=drawer_open", "?panel=drawer_open", "?panel=<script>", "?panel=", ""):
        assert client.get("/health" + query).json()["status"] == "ok"
    assert metrics.panel_events["chart_open"] - before.get("chart_open", 0) == 1
    assert metrics.panel_events["brief_started"] - before.get("brief_started", 0) == 1
    assert metrics.panel_events["drawer_open"] - before.get("drawer_open", 0) == 2
    assert set(metrics.panel_events) <= {"chart_open", "brief_started", "drawer_open"}
    text = metrics.prometheus()
    assert 'copilot_panel_events_total{event="drawer_open"}' in text and "script" not in text


def test_health_mints_correlation_id_when_absent_or_invalid(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Correlation-Id": "bad id with spaces"})
    minted = response.headers["X-Correlation-Id"]
    assert minted != "bad id with spaces"
    assert len(minted) == 16


@pytest.mark.anyio
async def test_runtime_transient_sweeper_executes_the_one_hour_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    called = asyncio.Event()

    def fake_sweep(path: Path, *, now):
        assert path == tmp_path
        assert now.tzinfo is not None
        called.set()
        return ["expired-job"]

    monkeypatch.setattr(main_module, "sweep_transient_directories", fake_sweep)
    task = asyncio.create_task(main_module._transient_sweeper(tmp_path))
    await asyncio.wait_for(called.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


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


def test_optional_capability_failure_is_degraded_but_does_not_make_core_unready(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_evaluate(_settings):
        from app.readiness import ReadinessReport
        import time

        return ReadinessReport(
            ok=True,
            checked_at=time.time(),
            dependencies=[DependencyStatus("tracer", False, "unreachable")],
            capabilities=[
                CapabilityStatus("core_ready", True, "ready"),
                CapabilityStatus("telemetry_ready", False, "dependency_unavailable"),
            ],
        )

    monkeypatch.setattr(main_module, "evaluate", fake_evaluate)
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["capabilities"]["telemetry_ready"]["ok"] is False


# /ready probes the tracer (A1): keys present is not enough, the Langfuse host must answer.

import base64  # noqa: E402

import httpx  # noqa: E402

from app.readiness import check_tracer  # noqa: E402


def _tracer_settings(tmp_path: Path, **overrides) -> Settings:
    """Both Langfuse keys present, every network dependency pointed at a closed local port."""
    (tmp_path / "pk").write_text("pk-lf-test")
    (tmp_path / "sk").write_text("sk-lf-test")
    values = dict(
        gateway_ping_url="http://127.0.0.1:9/nope",
        state_dir=tmp_path / "state",
        anthropic_api_key_file=tmp_path / "missing",
        langfuse_public_key_file=tmp_path / "pk",
        langfuse_secret_key_file=tmp_path / "sk",
        langfuse_host="http://127.0.0.1:9",
    )
    values.update(overrides)
    return Settings(**values)


def test_ready_is_503_when_tracer_unreachable(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module, "settings", _tracer_settings(tmp_path))
    response = client.get("/ready")
    assert response.status_code == 503
    names = {d["name"]: d for d in response.json()["dependencies"]}
    assert names["tracer"]["ok"] is False
    assert names["tracer"]["detail"] == "ConnectError"  # the httpx class, never its message
    assert names["state_store"]["ok"] is True


@pytest.mark.anyio
async def test_check_tracer_is_not_configured_without_both_keys(tmp_path: Path) -> None:
    status = await check_tracer(_tracer_settings(tmp_path, langfuse_secret_key_file=tmp_path / "absent"))
    assert (status.ok, status.detail) == (False, "not_configured")


@pytest.mark.anyio
async def test_check_tracer_calls_the_projects_endpoint_with_basic_auth(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": []})

    status = await check_tracer(_tracer_settings(tmp_path), transport=httpx.MockTransport(handler))
    assert (status.ok, status.detail) == (True, "reachable")
    assert str(seen[0].url) == "http://127.0.0.1:9/api/public/projects"
    scheme, credentials = seen[0].headers["Authorization"].split(" ", 1)
    assert scheme == "Basic" and base64.b64decode(credentials).decode() == "pk-lf-test:sk-lf-test"


@pytest.mark.anyio
async def test_check_tracer_reports_a_non_200_as_http_status(tmp_path: Path) -> None:
    status = await check_tracer(_tracer_settings(tmp_path), transport=httpx.MockTransport(lambda request: httpx.Response(401)))
    assert (status.ok, status.detail) == (False, "http_401")


def test_spend_ledger_readiness_reports_daily_limit_without_exposing_path(tmp_path: Path) -> None:
    from datetime import datetime, timezone
    from decimal import Decimal

    from app.week2_operations import DailySpendLedger

    path = tmp_path / "spend.sqlite3"
    settings = Settings(spend_ledger_path=path, model_call_reservation_usd=Decimal("0.15"))
    ledger = DailySpendLedger(path)
    ledger.reserve(
        reservation_id="fill-day",
        operation="chat",
        maximum_usd=Decimal("20"),
        now=datetime.now(timezone.utc),
    )

    status = check_spend_ledger(settings)

    assert (status.ok, status.detail) == (False, "daily_limit")
    assert str(path) not in status.detail


def test_guideline_readiness_requires_exact_fresh_corpus_and_pinned_local_models() -> None:
    from datetime import datetime, timezone

    root = Path(__file__).parents[2] / "docs" / "research" / "week2-retrieval-benchmark"
    settings = Settings(
        guideline_enabled=True,
        guideline_corpus_path=root / "corpus.jsonl",
        guideline_manifest_path=root / "manifest.json",
    )

    status = check_guideline(
        settings,
        now=datetime(2026, 9, 22, tzinfo=timezone.utc),
        model_artifact_check=lambda: True,
    )

    assert (status.ok, status.detail) == (True, "ready")
