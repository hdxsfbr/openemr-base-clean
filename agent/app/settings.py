"""Runtime configuration. Values come from the environment; secrets from files."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="COPILOT_", extra="ignore")

    # Internal URL of the module's gateway ping endpoint (never through the edge).
    gateway_ping_url: str = (
        "http://openemr:80/interface/modules/custom_modules/oe-module-copilot/public/gateway/ping.php"
    )
    gateway_timeout_seconds: float = 2.0

    # Secrets are mounted as files; the service reports "not_configured" when absent.
    anthropic_api_key_file: Path = Path("/run/secrets/anthropic_api_key")
    delegation_secret_file: Path = Path("/run/secrets/copilot_delegation_secret")

    # Tracer configuration presence (keys themselves are read by the tracer client later).
    langfuse_public_key_file: Path = Path("/run/secrets/langfuse_public_key")

    # Writable directory for the checkpointer (ADR-0005).
    state_dir: Path = Path("/var/lib/copilot")

    # Readiness results are cached to keep /ready cheap under polling.
    ready_cache_seconds: float = 30.0


settings = Settings()
