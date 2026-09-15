"""Dependency checks behind /ready (PRD: readiness must validate real dependencies)."""

from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from .settings import Settings


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
    try:
        return path.is_file() and path.stat().st_size > 0
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


def check_llm(settings: Settings) -> DependencyStatus:
    # Skeleton: presence of the key file. The models.retrieve probe lands with the graph.
    if _secret_present(settings.anthropic_api_key_file):
        return DependencyStatus("llm_provider", True, "configured")
    return DependencyStatus("llm_provider", False, "not_configured")


def check_tracer(settings: Settings) -> DependencyStatus:
    if _secret_present(settings.langfuse_public_key_file):
        return DependencyStatus("tracer", True, "configured")
    return DependencyStatus("tracer", False, "not_configured")


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
    deps = [
        await check_gateway(settings),
        check_llm(settings),
        check_tracer(settings),
        check_delegation_secret(settings),
        check_state_dir(settings),
    ]
    return ReadinessReport(ok=all(d.ok for d in deps), checked_at=time.time(), dependencies=deps)
