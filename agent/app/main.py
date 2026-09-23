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
from .intake_extractor import IntakeExtractor
from .evidence_retriever_worker import EvidenceRetrieverWorker
from .guideline_release import GuidelineReleaseService
from .guideline_retriever import GuidelineRetriever
from .graph.build import build_graph
from .graph.nodes import Runtime
from .logging_setup import configure_logging
from .metrics import metrics
from .model import live_model
from .openrouter_client import OpenRouterClient
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


def _request_path_class(path: str) -> str:
    """Return a bounded route label without retaining a conversation identifier."""
    if path in {"/health", "/ready", "/metrics"}:
        return path.removeprefix("/")
    if path.startswith("/v1/conversations/"):
        if path.endswith("/turns"):
            return "turn"
        if path.endswith("/guideline-evidence"):
            return "guideline_evidence"
        if path.endswith("/guideline-source"):
            return "guideline_source"
        if path.endswith("/lab-extractions"):
            return "lab_extraction"
        return "conversation"
    return "other"


@asynccontextmanager
async def lifespan(app: FastAPI):
    guard_environment()
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    gateway = HttpGateway()
    openrouter = OpenRouterClient()
    try:
        async with AsyncSqliteSaver.from_conn_string(checkpoint_path()) as saver:
            # Every checkpoint read/write serializes on the saver's own
            # asyncio.Lock (langgraph.checkpoint.sqlite.aio), including the
            # commit -- WAL + NORMAL synchronous shrinks what that commit
            # costs while the lock is held, instead of a full fsync per step.
            await saver.conn.execute("PRAGMA journal_mode=WAL")
            await saver.conn.execute("PRAGMA synchronous=NORMAL")
            runtime = Runtime(gateway=gateway, model=live_model())
            app.state.runtime = runtime
            app.state.graph = build_graph(runtime, checkpointer=saver)
            # Separate from the chat graph: uploaded documents terminate at a
            # review-only preview and cannot become chat evidence or writes.
            app.state.intake_extractor = IntakeExtractor(gateway, openrouter)
            try:
                app.state.guideline_release = GuidelineReleaseService(
                    EvidenceRetrieverWorker(GuidelineRetriever(
                        embedding_model_dir=settings.guideline_models_dir / "bge",
                        reranker_model_dir=settings.guideline_models_dir / "reranker",
                    )), settings.guideline_corpus_dir,
                )
            except Exception as exc:  # the Week 1 chart path remains available
                app.state.guideline_release = None
                log.warning("guideline capability unavailable", extra={"component": "guideline", "error_class": exc.__class__.__name__})
            log.info("agent ready", extra={"component": "startup"})
            yield
    finally:
        await gateway.aclose()
        await openrouter.aclose()


app = FastAPI(title="AgentForge Clinical Co-Pilot Agent", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan)
app.include_router(v1_router)


@app.middleware("http")
async def correlation_and_access_log(request: Request, call_next):
    correlation_id = _valid_correlation_id(request.headers.get(CORRELATION_HEADER))
    request.state.correlation_id = correlation_id
    path_class = _request_path_class(request.url.path)
    started = time.perf_counter()
    metrics.in_flight += 1
    try:
        response: Response = await call_next(request)
    except Exception:  # noqa: BLE001
        log.exception("unhandled", extra={"correlation_id": correlation_id, "path": path_class, "method": request.method})
        response = JSONResponse(status_code=500, content={"code": "internal_error", "message": "Request failed.", "correlation_id": correlation_id})
    finally:
        metrics.in_flight -= 1
    correlation_id = getattr(request.state, "correlation_id", correlation_id)
    response.headers[CORRELATION_HEADER] = correlation_id
    metrics.request(path_class, response.status_code)
    log.info("request", extra={"correlation_id": correlation_id, "path": path_class, "method": request.method, "status": response.status_code, "duration_ms": round((time.perf_counter() - started) * 1000, 1)})
    return response


@app.get("/health")
async def health(panel: str | None = None) -> dict:
    """Liveness. The chart panel's reachability check says why it is asking
    (`?panel=chart_open` on load, `?panel=brief_started` when it prepares the
    brief for that chart, `?panel=drawer_open` when the drawer opens), which is
    the top of the funnel in `/metrics`; any other value is ignored."""
    if panel and metrics.panel_event(panel):
        log.info("panel event: %s", panel, extra={"component": "funnel"})
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
