"""Dependency checks behind /ready (PRD: readiness must validate real dependencies,
including the observability backend, so a check that only reads key files is
not enough; ADR-0007 decision 6)."""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from .settings import Settings

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
class ReadinessReport:
    ok: bool
    checked_at: float
    dependencies: list[DependencyStatus] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "status": "ready" if self.ok else "not_ready",
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.checked_at)),
            "dependencies": [d.__dict__ for d in self.dependencies],
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


async def evaluate(settings: Settings) -> ReadinessReport:
    """The three network checks run concurrently so /ready costs one round trip
    (the slowest of the three), not their sum; the local checks follow."""
    gateway, llm, tracer = await asyncio.gather(check_gateway(settings), check_llm(settings), check_tracer(settings))
    deps = [gateway, llm, tracer, check_delegation_secret(settings), check_state_dir(settings)]
    return ReadinessReport(ok=all(d.ok for d in deps), checked_at=time.time(), dependencies=deps)
