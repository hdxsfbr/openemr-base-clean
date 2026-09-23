from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app import openrouter_client as client_module
from app.openrouter_client import OpenRouterClient, breaker
from app.settings import Settings

SCHEMA = {"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]}


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    key_file = tmp_path / "openrouter_api_key"
    key_file.write_text("sk-or-test\n")
    values: dict[str, object] = {"openrouter_api_key_file": key_file}
    values.update(overrides)
    return Settings(**values)


@pytest.fixture(autouse=True)
def _reset_breaker() -> None:
    breaker.failures = 0
    breaker.opened_at = None


@pytest.mark.anyio
async def test_extract_pdf_returns_parsed_data_and_usage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "settings", _settings(tmp_path))
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = {
            "choices": [{"message": {"content": json.dumps({"value": "42"})}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 12},
        }
        return httpx.Response(200, json=body)

    client = OpenRouterClient(transport=httpx.MockTransport(handler))
    result = await client.extract_pdf(b"%PDF-1.4 fixture", SCHEMA, "extract the value", "ctest-0000000000000001")

    assert result.status == "ok"
    assert result.data == {"value": "42"}
    assert (result.usage.input_tokens, result.usage.output_tokens) == (100, 12)
    request_body = json.loads(seen[0].content)
    assert request_body["model"] == "google/gemini-2.5-flash"
    assert request_body["response_format"]["json_schema"]["schema"] == SCHEMA
    assert seen[0].headers["Authorization"] == "Bearer sk-or-test"


@pytest.mark.anyio
async def test_extract_pdf_is_unavailable_without_a_configured_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "settings", _settings(tmp_path, openrouter_api_key_file=tmp_path / "absent"))
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    client = OpenRouterClient(transport=httpx.MockTransport(handler))
    result = await client.extract_pdf(b"%PDF-1.4 fixture", SCHEMA, "extract the value", "ctest-0000000000000002")

    assert (result.status, result.reason) == ("unavailable", "not_configured")
    assert calls == 0  # no network call is made without a key


@pytest.mark.anyio
async def test_extract_pdf_retries_once_on_5xx_then_fails_safe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "settings", _settings(tmp_path))
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    client = OpenRouterClient(transport=httpx.MockTransport(handler))
    result = await client.extract_pdf(b"%PDF-1.4 fixture", SCHEMA, "extract the value", "ctest-0000000000000003")

    assert (result.status, result.reason) == ("unavailable", "http_503")
    assert calls == 2  # exactly one retry, never an unbounded loop


@pytest.mark.anyio
async def test_extract_pdf_does_not_retry_on_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "settings", _settings(tmp_path))
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("boom")

    client = OpenRouterClient(transport=httpx.MockTransport(handler))
    result = await client.extract_pdf(b"%PDF-1.4 fixture", SCHEMA, "extract the value", "ctest-0000000000000004")

    assert (result.status, result.reason) == ("unavailable", "timeout")
    assert calls == 1


@pytest.mark.anyio
async def test_extract_pdf_fails_safe_on_malformed_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "settings", _settings(tmp_path))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})

    client = OpenRouterClient(transport=httpx.MockTransport(handler))
    result = await client.extract_pdf(b"%PDF-1.4 fixture", SCHEMA, "extract the value", "ctest-0000000000000005")

    assert (result.status, result.reason) == ("unavailable", "malformed_output")


@pytest.mark.anyio
async def test_circuit_breaker_short_circuits_after_repeated_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "settings", _settings(tmp_path))
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("down")

    client = OpenRouterClient(transport=httpx.MockTransport(handler))
    for _ in range(3):
        await client.extract_pdf(b"%PDF-1.4 fixture", SCHEMA, "extract the value", "ctest-0000000000000006")
    calls_before = calls

    result = await client.extract_pdf(b"%PDF-1.4 fixture", SCHEMA, "extract the value", "ctest-0000000000000006")

    assert (result.status, result.reason) == ("unavailable", "circuit_open")
    assert calls == calls_before  # the open breaker short-circuits before any request
