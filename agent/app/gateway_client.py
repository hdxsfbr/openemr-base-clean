"""HTTP client for the module's tool gateway (ADR-0003 step 4). Every call
carries the turn's delegation token and correlation id; failures become an
`unavailable` envelope, never an empty one (PERF-MED-001)."""

from __future__ import annotations

import time
from typing import Any, Protocol

import httpx
from pydantic import ValidationError

from .contracts import ToolResponse
from .intake_extractor import SourceBytes
from .settings import settings


class GatewayPort(Protocol):
    async def call(self, tool: str, params: dict, token: str, correlation_id: str) -> ToolResponse: ...
    async def call_batch(self, calls: list[tuple[str, dict]], token: str, correlation_id: str, disclosure: dict[str, str] | None = None) -> list[ToolResponse]: ...


def unavailable(tool: str, reason: str, correlation_id: str, latency_ms: float = 0.0) -> ToolResponse:
    return ToolResponse.model_validate(
        {
            "tool": tool,
            "tool_version": "n/a",
            "contract_version": "1.0.0",
            "status": "unavailable",
            "reason": reason,
            "records": [],
            "latency_ms": latency_ms,
            "correlation_id": correlation_id,
        }
    )


class HttpGateway:
    def __init__(self, base_url: str | None = None, timeout: float | None = None) -> None:
        self.base_url = (base_url or settings.gateway_base_url).rstrip("/")
        self.timeout = timeout or settings.gateway_timeout_seconds
        # Shared, pooled client: a fresh AsyncClient per call paid a new TCP/TLS
        # handshake on every one of the ~6 parallel tool calls a turn makes, on
        # both ends of the connection (this process and OpenEMR's Apache).
        self._client = httpx.AsyncClient(timeout=self.timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def read_source(self, source_id: str, token: str, correlation_id: str) -> SourceBytes:
        """Read exactly one delegated PDF from the module's internal boundary.

        This method deliberately returns no exception text and does not log the
        document. The intake worker maps every transport, timeout, integrity,
        and parser failure to a typed preview limitation.
        """
        headers = {"X-Copilot-Token": token, "X-Correlation-Id": correlation_id, "Accept": "application/pdf"}
        try:
            response = await self._client.get(f"{self.base_url}/source.php", params={"source_id": source_id}, headers=headers)
        except httpx.HTTPError:
            return SourceBytes(status=503, source_id=None, source_hash=None, content_type=None, bytes=None)
        return SourceBytes(
            status=response.status_code,
            source_id=response.headers.get("X-Copilot-Source-Id"),
            source_hash=response.headers.get("X-Copilot-Source-Hash"),
            content_type=(response.headers.get("Content-Type") or "").split(";", 1)[0],
            bytes=response.content if response.status_code == 200 else None,
        )

    async def call(self, tool: str, params: dict, token: str, correlation_id: str) -> ToolResponse:
        started = time.perf_counter()
        headers = {"X-Copilot-Token": token, "X-Correlation-Id": correlation_id, "Accept": "application/json"}
        try:
            response = await self._client.post(f"{self.base_url}/tools.php", params={"tool": tool}, json=params, headers=headers)
        except httpx.TimeoutException:
            return unavailable(tool, "timeout", correlation_id, (time.perf_counter() - started) * 1000)
        except httpx.HTTPError:
            return unavailable(tool, "transport_error", correlation_id, (time.perf_counter() - started) * 1000)
        if response.status_code != 200:
            reason = "forbidden" if response.status_code in (401, 403) else f"http_{response.status_code}"
            return unavailable(tool, reason, correlation_id, (time.perf_counter() - started) * 1000)
        try:
            return ToolResponse.model_validate(response.json())
        except (ValueError, ValidationError):
            return unavailable(tool, "contract_violation", correlation_id, (time.perf_counter() - started) * 1000)

    async def call_batch(self, calls: list[tuple[str, dict]], token: str, correlation_id: str, disclosure: dict[str, str] | None = None) -> list[ToolResponse]:
        """One request serving every tool in `calls`: one gateway bootstrap
        (globals.php translations/ACL/layout lookups, PERF-MED-002) instead of
        one per tool. A transport-level failure marks every requested tool
        unavailable with the same reasons `call()` uses; a malformed or
        mismatched single result degrades only that tool, using the name we
        asked for rather than whatever the gateway returned. `disclosure`
        ({provider, model}) declares that these records will go to a model
        provider; the module writes a `copilot-model-disclosure` audit row
        before it returns them, and returns none if it cannot."""
        started = time.perf_counter()
        headers = {"X-Copilot-Token": token, "X-Correlation-Id": correlation_id, "Accept": "application/json"}
        body: dict[str, Any] = {"calls": [{"tool": tool, "params": params} for tool, params in calls]}
        if disclosure:
            body["disclosure"] = disclosure
        try:
            response = await self._client.post(f"{self.base_url}/tools.php", json=body, headers=headers)
        except httpx.TimeoutException:
            elapsed = (time.perf_counter() - started) * 1000
            return [unavailable(tool, "timeout", correlation_id, elapsed) for tool, _ in calls]
        except httpx.HTTPError:
            elapsed = (time.perf_counter() - started) * 1000
            return [unavailable(tool, "transport_error", correlation_id, elapsed) for tool, _ in calls]
        if response.status_code != 200:
            elapsed = (time.perf_counter() - started) * 1000
            reason = "forbidden" if response.status_code in (401, 403) else f"http_{response.status_code}"
            return [unavailable(tool, reason, correlation_id, elapsed) for tool, _ in calls]
        try:
            payload = response.json()
            results = payload["results"]
            if not isinstance(results, list) or len(results) != len(calls):
                raise ValueError("results length mismatch")
        except (ValueError, KeyError, TypeError):
            elapsed = (time.perf_counter() - started) * 1000
            return [unavailable(tool, "contract_violation", correlation_id, elapsed) for tool, _ in calls]
        responses: list[ToolResponse] = []
        for (tool, _params), item in zip(calls, results):
            try:
                responses.append(ToolResponse.model_validate(item))
            except ValidationError:
                responses.append(unavailable(tool, "contract_violation", correlation_id))
        return responses
