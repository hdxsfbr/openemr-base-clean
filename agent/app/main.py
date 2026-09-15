"""Co-pilot agent HTTP API (skeleton): /health, /ready, correlation IDs, JSON logs."""

from __future__ import annotations

import logging
import secrets
import time

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from . import __version__
from .logging_setup import configure_logging
from .readiness import ReadinessReport, evaluate
from .settings import settings

configure_logging()
log = logging.getLogger("copilot.api")

app = FastAPI(title="AgentForge Clinical Co-Pilot Agent", version=__version__, docs_url=None, redoc_url=None)
_started_at = time.time()
_ready_cache: ReadinessReport | None = None

CORRELATION_HEADER = "X-Correlation-Id"


def _valid_correlation_id(value: str | None) -> str:
    # Accept caller ids of a bounded, printable shape; otherwise mint one.
    if value and 8 <= len(value) <= 64 and all(c.isalnum() or c in "-._" for c in value):
        return value
    return secrets.token_hex(8)


@app.middleware("http")
async def correlation_and_access_log(request: Request, call_next):
    correlation_id = _valid_correlation_id(request.headers.get(CORRELATION_HEADER))
    request.state.correlation_id = correlation_id
    started = time.perf_counter()
    try:
        response: Response = await call_next(request)
    except Exception:  # noqa: BLE001 - logged with class only, then re-raised as 500
        log.exception(
            "unhandled",
            extra={"correlation_id": correlation_id, "path": request.url.path, "method": request.method},
        )
        response = JSONResponse(
            status_code=500,
            content={"code": "internal_error", "message": "Request failed.", "correlation_id": correlation_id},
        )
    response.headers[CORRELATION_HEADER] = correlation_id
    log.info(
        "request",
        extra={
            "correlation_id": correlation_id,
            "path": request.url.path,
            "method": request.method,
            "status": response.status_code,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        },
    )
    return response


@app.get("/health")
async def health() -> dict:
    """Liveness: the process is up. No dependency checks here."""
    return {"status": "ok", "version": __version__, "uptime_seconds": round(time.time() - _started_at, 1)}


@app.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """Readiness: real dependency checks, cached briefly. 503 when any fails."""
    global _ready_cache
    now = time.time()
    if _ready_cache is None or now - _ready_cache.checked_at > settings.ready_cache_seconds:
        _ready_cache = await evaluate(settings)
    body = _ready_cache.as_dict()
    body["version"] = __version__
    body["correlation_id"] = request.state.correlation_id
    return JSONResponse(status_code=200 if _ready_cache.ok else 503, content=body)
