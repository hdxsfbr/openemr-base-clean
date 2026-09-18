"""Runtime configuration. Values come from the environment; secrets from files."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="COPILOT_", extra="ignore")

    # Module gateway on the internal network (never through the edge).
    gateway_base_url: str = "http://openemr:80/interface/modules/custom_modules/oe-module-copilot/public/gateway"
    gateway_ping_url: str = (
        "http://openemr:80/interface/modules/custom_modules/oe-module-copilot/public/gateway/ping.php"
    )
    gateway_timeout_seconds: float = 2.0
    tool_concurrency: int = 6

    # Secrets are mounted as files; the service reports "not_configured" when absent.
    anthropic_api_key_file: Path = Path("/run/secrets/anthropic_api_key")
    # Optional: required by the API when the key is organization-level rather than workspace-scoped.
    anthropic_workspace_id_file: Path = Path("/run/secrets/anthropic_workspace_id")
    delegation_secret_file: Path = Path("/run/secrets/copilot_delegation_secret")
    langfuse_public_key_file: Path = Path("/run/secrets/langfuse_public_key")
    langfuse_secret_key_file: Path = Path("/run/secrets/langfuse_secret_key")
    langfuse_host: str = "https://us.cloud.langfuse.com"

    # Model (ADR-0004).
    model_id: str = "claude-sonnet-5"  # owner decision 2026-09-15 on measured latency (ADR-0004)
    # Optional override for the `plan` call only (tool selection -- a bounded, structured
    # decision, unlike narrate/repair's open-ended clinical synthesis). None falls back to
    # model_id, so leaving this unset is a no-op (2026-09-18 experiment, not yet adopted).
    plan_model_id: str | None = None
    # output_config.effort is a Claude 5-family parameter (400s on e.g. Haiku 4.5,
    # confirmed 2026-09-18). Set false alongside a plan_model_id override to a
    # model outside that family.
    plan_model_supports_effort: bool = True
    effort_first_turn: str = "low"
    effort_followup: str = "medium"
    model_timeout_seconds: float = 30.0
    max_output_tokens: int = 1800

    # Bounds (ADR-0004 decision 5).
    max_plan_rounds: int = 3
    max_tool_calls_per_turn: int = 8
    turn_wall_clock_seconds: float = 45.0  # measured first-turn narration on Opus 5 exceeds the 12 s design budget; see KEY_METRICS.md
    tokens_per_turn: int = 20_000
    tokens_per_conversation: int = 60_000
    daily_token_halt: int = 2_000_000
    turns_per_minute: int = 10

    # Evidence pack cap (characters; about 12K tokens at 4 chars per token).
    evidence_pack_max_chars: int = 48_000
    conversation_idle_minutes: int = 30

    # Writable directory for the checkpointer (ADR-0005).
    state_dir: Path = Path("/var/lib/copilot")
    ready_cache_seconds: float = 30.0

    # Demo/CI only: honors X-Copilot-Fault (model, tool:<name>, tracer, budget).
    fault_injection: bool = False

    def anthropic_headers(self) -> dict[str, str]:
        workspace = self.secret(self.anthropic_workspace_id_file)
        return {"anthropic-workspace-id": workspace} if workspace else {}

    def secret(self, path: Path) -> str | None:
        try:
            value = path.read_text().strip()
        except OSError:
            return None
        return value or None


settings = Settings()
