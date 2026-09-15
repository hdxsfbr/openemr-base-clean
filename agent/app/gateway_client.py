"""HTTP client for the module's tool gateway (ADR-0003 step 4). Every call
carries the turn's delegation token and correlation id; failures become an
`unavailable` envelope, never an empty one (PERF-MED-001)."""

from __future__ import annotations

import time
from typing import Protocol

import httpx
from pydantic import ValidationError

from .contracts import ToolResponse
from .settings import settings


class GatewayPort(Protocol):
    async def call(self, tool: str, params: dict, token: str, correlation_id: str) -> ToolResponse: ...


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

    async def call(self, tool: str, params: dict, token: str, correlation_id: str) -> ToolResponse:
        started = time.perf_counter()
        headers = {"X-Copilot-Token": token, "X-Correlation-Id": correlation_id, "Accept": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/tools.php", params={"tool": tool}, json=params, headers=headers)
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
