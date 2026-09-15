"""Co-pilot agent HTTP API: /health, /ready, /metrics, /v1 (ADR-0003, ADR-0004)."""

from __future__ import annotations

import logging
import secrets
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from . import __version__
from .api import router as v1_router
from .gateway_client import HttpGateway
from .graph.build import build_graph
from .graph.nodes import Runtime
from .logging_setup import configure_logging
from .metrics import metrics
from .model import live_model
from .readiness import ReadinessReport, evaluate
from .settings import settings
from .state_store import checkpoint_path
from .telemetry import guard_environment

configure_logging()
log = logging.getLogger("copilot.api")

CORRELATION_HEADER = "X-Correlation-Id"
_started_at = time.time()
_ready_cache: ReadinessReport | None = None


def _valid_correlation_id(value: str | None) -> str:
    if value and 8 <= len(value) <= 64 and all(c.isalnum() or c in "-._" for c in value):
        return value
    return secrets.token_hex(8)


@asynccontextmanager
async def lifespan(app: FastAPI):
    guard_environment()
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    async with AsyncSqliteSaver.from_conn_string(checkpoint_path()) as saver:
        runtime = Runtime(gateway=HttpGateway(), model=live_model())
        app.state.runtime = runtime
        app.state.graph = build_graph(runtime, checkpointer=saver)
        log.info("agent ready", extra={"component": "startup"})
        yield


app = FastAPI(title="AgentForge Clinical Co-Pilot Agent", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan)
app.include_router(v1_router)


@app.middleware("http")
async def correlation_and_access_log(request: Request, call_next):
    correlation_id = _valid_correlation_id(request.headers.get(CORRELATION_HEADER))
    request.state.correlation_id = correlation_id
    started = time.perf_counter()
    metrics.in_flight += 1
    try:
        response: Response = await call_next(request)
    except Exception:  # noqa: BLE001
        log.exception("unhandled", extra={"correlation_id": correlation_id, "path": request.url.path, "method": request.method})
        response = JSONResponse(status_code=500, content={"code": "internal_error", "message": "Request failed.", "correlation_id": correlation_id})
    finally:
        metrics.in_flight -= 1
    correlation_id = getattr(request.state, "correlation_id", correlation_id)
    response.headers[CORRELATION_HEADER] = correlation_id
    path_class = "turn" if request.url.path.endswith("/turns") else request.url.path.split("/")[1] or "root"
    metrics.request(path_class, response.status_code)
    log.info("request", extra={"correlation_id": correlation_id, "path": request.url.path, "method": request.method, "status": response.status_code, "duration_ms": round((time.perf_counter() - started) * 1000, 1)})
    return response


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": __version__, "uptime_seconds": round(time.time() - _started_at, 1)}


@app.get("/ready")
async def ready(request: Request) -> JSONResponse:
    global _ready_cache
    now = time.time()
    if _ready_cache is None or now - _ready_cache.checked_at > settings.ready_cache_seconds:
        _ready_cache = await evaluate(settings)
    body = _ready_cache.as_dict()
    body["version"] = __version__
    body["correlation_id"] = request.state.correlation_id
    return JSONResponse(status_code=200 if _ready_cache.ok else 503, content=body)


@app.get("/metrics")
async def prometheus_metrics() -> PlainTextResponse:
    return PlainTextResponse(metrics.prometheus(), media_type="text/plain; version=0.0.4")
