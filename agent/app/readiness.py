"""Dependency checks behind /ready (PRD: readiness must validate real dependencies,
including the observability backend, so a check that only reads key files is
not enough; ADR-0007 decision 6)."""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import httpx

from .settings import Settings
from .week2_operations import DailySpendLedger
from .guideline_retriever import (
    BGE_FILE,
    BGE_REPO,
    BGE_REVISION,
    BGE_SHA256,
    MAX_CORPUS_AGE,
    RERANKER_FILE,
    RERANKER_REPO,
    RERANKER_REVISION,
    RERANKER_SHA256,
    _require_file_hash,
    load_frozen_corpus,
)

GUIDELINE_CORPUS_SHA256 = "b4d8dcbf3151c871ec46c43f25cc73a014ed3e3a20bd89a63ab6713c006c3e03"
GUIDELINE_MANIFEST_SHA256 = "cd1916a7d34c877403cd53d533f17e685d296d7746676999694c911aec49da7c"

# The tracer probe is a bounded HTTP round trip so /ready stays fast under a 30 s
# healthcheck; the Langfuse project listing is the cheapest authenticated call.
TRACER_TIMEOUT_SECONDS = 5.0
TRACER_PROBE_PATH = "/api/public/projects"


@dataclass
class DependencyStatus:
    name: str
    ok: bool
    detail: str


@dataclass
class CapabilityStatus:
    name: str
    ok: bool
    detail: str


@dataclass
class ReadinessReport:
    ok: bool
    checked_at: float
    dependencies: list[DependencyStatus] = field(default_factory=list)
    capabilities: list[CapabilityStatus] = field(default_factory=list)

    def as_dict(self) -> dict:
        capabilities = {capability.name: {"ok": capability.ok, "detail": capability.detail} for capability in self.capabilities}
        core = capabilities.get("core_ready")
        if not self.ok or (core is not None and not core["ok"]):
            status = "not_ready"
        elif any(not capability["ok"] for capability in capabilities.values()):
            status = "degraded"
        else:
            status = "ready"
        return {
            "status": status,
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.checked_at)),
            "dependencies": [d.__dict__ for d in self.dependencies],
            "capabilities": capabilities,
        }


def _secret_present(path: Path) -> bool:
    """Readable and non-empty. Existence alone is not enough: a mount the
    service user cannot read must show as not configured."""
    try:
        return bool(path.read_text().strip())
    except OSError:
        return False


async def check_gateway(settings: Settings) -> DependencyStatus:
    try:
        async with httpx.AsyncClient(timeout=settings.gateway_timeout_seconds) as client:
            response = await client.get(settings.gateway_ping_url)
        if response.status_code == 200:
            return DependencyStatus("openemr_gateway", True, "ok")
        return DependencyStatus("openemr_gateway", False, f"http_{response.status_code}")
    except httpx.HTTPError as exc:
        return DependencyStatus("openemr_gateway", False, exc.__class__.__name__)


async def check_llm(settings: Settings) -> DependencyStatus:
    """Key present and the configured model reachable (models.retrieve)."""
    if not _secret_present(settings.anthropic_api_key_file):
        return DependencyStatus("llm_provider", False, "not_configured")
    try:
        import anthropic

        client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key_file.read_text().strip(), max_retries=0, timeout=5.0, default_headers=settings.anthropic_headers()
        )
        model = await client.models.retrieve(settings.model_id)
        return DependencyStatus("llm_provider", True, f"reachable:{model.id}")
    except Exception as exc:  # noqa: BLE001 - class only, never the message (may carry request details)
        return DependencyStatus("llm_provider", False, exc.__class__.__name__)


async def check_tracer(settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> DependencyStatus:
    """Both keys present and the Langfuse host answering to them: `GET
    {langfuse_host}/api/public/projects` with the public key as the basic-auth
    user and the secret key as the password. `not_configured` when a key is
    absent, `reachable` on 200, `http_<code>` on any other status, and the
    httpx error class (never its message) when the request fails. `transport`
    is a test seam so the status branches run without network access."""
    public = settings.secret(settings.langfuse_public_key_file)
    secret = settings.secret(settings.langfuse_secret_key_file)
    if not public or not secret:
        return DependencyStatus("tracer", False, "not_configured")
    url = settings.langfuse_host.rstrip("/") + TRACER_PROBE_PATH
    try:
        async with httpx.AsyncClient(timeout=TRACER_TIMEOUT_SECONDS, auth=httpx.BasicAuth(public, secret), transport=transport) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        return DependencyStatus("tracer", False, exc.__class__.__name__)
    if response.status_code == 200:
        return DependencyStatus("tracer", True, "reachable")
    return DependencyStatus("tracer", False, f"http_{response.status_code}")


def check_delegation_secret(settings: Settings) -> DependencyStatus:
    if _secret_present(settings.delegation_secret_file):
        return DependencyStatus("delegation_secret", True, "configured")
    return DependencyStatus("delegation_secret", False, "not_configured")


def check_state_dir(settings: Settings) -> DependencyStatus:
    try:
        settings.state_dir.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".ready-", dir=settings.state_dir)
        os.close(fd)
        os.unlink(name)
        return DependencyStatus("state_store", True, "writable")
    except OSError as exc:
        return DependencyStatus("state_store", False, exc.__class__.__name__)


def check_spend_ledger(settings: Settings) -> DependencyStatus:
    try:
        availability = DailySpendLedger(settings.spend_ledger_path).availability(
            maximum_usd=settings.model_call_reservation_usd,
            now=datetime.now(timezone.utc),
        )
    except Exception as exc:  # noqa: BLE001 - bounded error class only
        return DependencyStatus("spend_ledger", False, exc.__class__.__name__)
    if not availability.available:
        return DependencyStatus("spend_ledger", False, "daily_limit")
    return DependencyStatus("spend_ledger", True, "warning" if availability.warning else "available")


def check_guideline(
    settings: Settings,
    *,
    now: datetime | None = None,
    model_artifact_check: Callable[[], bool] | None = None,
) -> DependencyStatus:
    if not settings.guideline_enabled:
        return DependencyStatus("guideline", False, "disabled")
    try:
        corpus = load_frozen_corpus(
            corpus_path=settings.guideline_corpus_path,
            manifest_path=settings.guideline_manifest_path,
            expected_corpus_sha256=GUIDELINE_CORPUS_SHA256,
            expected_manifest_sha256=GUIDELINE_MANIFEST_SHA256,
        )
    except ValueError:
        return DependencyStatus("guideline", False, "integrity_failure")
    except OSError:
        return DependencyStatus("guideline", False, "unavailable")
    observed_now = now or datetime.now(timezone.utc)
    approved = datetime.fromisoformat(corpus.approved_at.replace("Z", "+00:00"))
    if observed_now - approved > MAX_CORPUS_AGE:
        return DependencyStatus("guideline", False, "stale")
    try:
        models_ready = (model_artifact_check or _pinned_guideline_models_available)()
    except Exception:  # noqa: BLE001 - readiness exposes a bounded reason only
        models_ready = False
    return DependencyStatus("guideline", models_ready, "ready" if models_ready else "model_unavailable")


def _pinned_guideline_models_available() -> bool:
    from huggingface_hub import hf_hub_download

    for repo, revision, filename, expected in (
        (BGE_REPO, BGE_REVISION, BGE_FILE, BGE_SHA256),
        (RERANKER_REPO, RERANKER_REVISION, RERANKER_FILE, RERANKER_SHA256),
    ):
        common = {"repo_id": repo, "revision": revision, "local_files_only": True}
        hf_hub_download(filename="tokenizer.json", **common)
        model_path = Path(hf_hub_download(filename=filename, **common))
        _require_file_hash(model_path, expected, "guideline model")
    return True


async def evaluate(settings: Settings) -> ReadinessReport:
    """The three network checks run concurrently so /ready costs one round trip
    (the slowest of the three), not their sum; the local checks follow."""
    gateway, llm, tracer = await asyncio.gather(check_gateway(settings), check_llm(settings), check_tracer(settings))
    delegation = check_delegation_secret(settings)
    state_store = check_state_dir(settings)
    spend_ledger = check_spend_ledger(settings)
    guideline = check_guideline(settings)
    deps = [gateway, llm, tracer, delegation, state_store, spend_ledger, guideline]
    core_ok = all(dependency.ok for dependency in (gateway, delegation, state_store))
    capabilities = [
        CapabilityStatus("core_ready", core_ok, "ready" if core_ok else "dependency_unavailable"),
        CapabilityStatus(
            "chat_model_ready",
            llm.ok and spend_ledger.ok,
            "ready" if llm.ok and spend_ledger.ok else "dependency_unavailable",
        ),
        CapabilityStatus("document_ready", False, "not_configured"),
        CapabilityStatus("guideline_ready", guideline.ok, guideline.detail),
        CapabilityStatus("telemetry_ready", tracer.ok, "ready" if tracer.ok else "dependency_unavailable"),
    ]
    return ReadinessReport(ok=core_ok, checked_at=time.time(), dependencies=deps, capabilities=capabilities)
