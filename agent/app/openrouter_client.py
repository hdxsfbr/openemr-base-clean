"""Bounded OpenRouter PDF client (GitLab #51).

A small, injectable client that sends authorized PDF bytes to a pinned,
version-locked OpenRouter model with a requested JSON schema and returns a
typed result: the parsed structured output and usage, or a typed unavailable
result. Not wired into any worker yet -- the lab and intake extraction tasks
(#52-#54) will take this as a constructor dependency. Never logs PDF bytes,
extracted text, or prompts; only enum-shaped status/reason and counts.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from .model import CircuitBreaker
from .settings import settings

log = logging.getLogger("copilot.openrouter")

# 429/5xx get one retry after a short wait, same policy as the chat model
# (ADR-0004 decision 4) and the vision retry (ADR-0009 decision 3). No retry
# on timeout or a client error -- an unbounded retry is a timeout risk, not a
# reliability win.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_RETRY_WAIT_SECONDS = 0.5


@dataclass
class OpenRouterUsage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class OpenRouterResult:
    """`status` is "ok" or "unavailable"; `reason` is set only when it is not
    "ok" and is always one of this module's own enum-shaped tokens, never
    provider response text (which can carry request/document detail)."""

    status: str
    data: dict[str, Any] | None = None
    usage: OpenRouterUsage = field(default_factory=OpenRouterUsage)
    reason: str | None = None


class OpenRouterError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class OpenRouterPort(Protocol):
    async def extract_pdf(self, pdf: bytes, schema: dict[str, Any], prompt: str, correlation_id: str) -> OpenRouterResult: ...


# Separate from the chat model's breaker (app.model.breaker): a different
# provider and failure mode should not trip the chat path, or vice versa.
breaker = CircuitBreaker()


class OpenRouterClient:
    """Live implementation. Constructed unconditionally; `extract_pdf` fails
    safe with `not_configured` when no key file is present."""

    def __init__(self, base_url: str | None = None, timeout: float | None = None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = (base_url or settings.openrouter_base_url).rstrip("/")
        self.timeout = timeout if timeout is not None else settings.openrouter_timeout_seconds
        # `transport` is a test seam (same pattern as `readiness.check_tracer`) so
        # retry/failure branches run without network access.
        self._client = httpx.AsyncClient(timeout=self.timeout, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def extract_pdf(self, pdf: bytes, schema: dict[str, Any], prompt: str, correlation_id: str) -> OpenRouterResult:
        api_key = settings.secret(settings.openrouter_api_key_file)
        if not api_key:
            return OpenRouterResult(status="unavailable", reason="not_configured")
        if breaker.is_open():
            return OpenRouterResult(status="unavailable", reason="circuit_open")
        body = {
            "model": settings.openrouter_model_id,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "file",
                            "file": {
                                "filename": "document.pdf",
                                "file_data": f"data:application/pdf;base64,{base64.b64encode(pdf).decode('ascii')}",
                            },
                        },
                    ],
                }
            ],
            "response_format": {"type": "json_schema", "json_schema": {"name": "extraction", "strict": True, "schema": schema}},
            "plugins": [{"id": "file-parser", "pdf": {"engine": settings.openrouter_pdf_engine}}],
            "max_tokens": settings.openrouter_max_output_tokens,
            "temperature": 0,
        }
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        started = time.perf_counter()
        try:
            response = await self._call(body, headers)
        except OpenRouterError as exc:
            log.info(
                "openrouter call failed",
                extra={"component": "openrouter", "reason": exc.reason, "correlation_id": correlation_id, "duration_ms": (time.perf_counter() - started) * 1000},
            )
            return OpenRouterResult(status="unavailable", reason=exc.reason)
        result = _parse_response(response)
        log.info(
            "openrouter call complete",
            extra={
                "component": "openrouter",
                "status": result.status,
                "reason": result.reason,
                "correlation_id": correlation_id,
                "duration_ms": (time.perf_counter() - started) * 1000,
            },
        )
        return result

    async def _call(self, body: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
        retried = False
        while True:
            try:
                response = await self._client.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
            except httpx.TimeoutException as exc:
                breaker.record(False)
                raise OpenRouterError("timeout") from exc
            except httpx.HTTPError as exc:
                breaker.record(False)
                raise OpenRouterError("transport_error") from exc
            if response.status_code == 200:
                breaker.record(True)
                return response
            if response.status_code in _RETRYABLE_STATUS and not retried:
                retried = True
                await asyncio.sleep(_RETRY_WAIT_SECONDS)
                continue
            breaker.record(response.status_code < 500)
            raise OpenRouterError(f"http_{response.status_code}")


def _parse_response(response: httpx.Response) -> OpenRouterResult:
    """The final deterministic parse of the provider's response. Any shape
    surprise here is `malformed_output`, never a raised provider-text error."""
    try:
        payload = response.json()
        choice = payload["choices"][0]["message"]["content"]
        usage_raw = payload.get("usage") or {}
        usage = OpenRouterUsage(
            input_tokens=int(usage_raw.get("prompt_tokens", 0) or 0),
            output_tokens=int(usage_raw.get("completion_tokens", 0) or 0),
        )
        data = json.loads(choice) if isinstance(choice, str) else choice
        if not isinstance(data, dict):
            raise ValueError("content is not a JSON object")
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        return OpenRouterResult(status="unavailable", reason="malformed_output")
    return OpenRouterResult(status="ok", data=data, usage=usage)
