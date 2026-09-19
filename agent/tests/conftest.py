from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.contracts import Claim, ToolResponse, TurnClaims
from app.gateway_client import unavailable
from app.model import NarrateResult, PlanResult, Usage

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tool_responses"
TEST_SECRET = "0123456789abcdef0123456789abcdef0123456789abcdef"


class FakeGateway:
    """Serves the recorded AF-DQ-A2 responses; can be told to fail a tool."""

    def __init__(self, failing: set[str] | None = None) -> None:
        self.failing = failing or set()
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, tool: str, params: dict, token: str, correlation_id: str) -> ToolResponse:
        self.calls.append((tool, params))
        if tool in self.failing:
            return unavailable(tool, "service_error", correlation_id)
        path = FIXTURE_DIR / f"af-dq-a2.{tool}.json"
        payload = json.loads(path.read_text())
        payload["correlation_id"] = correlation_id
        return ToolResponse.model_validate(payload)

    async def call_batch(self, calls: list[tuple[str, dict]], token: str, correlation_id: str) -> list[ToolResponse]:
        return [await self.call(tool, params, token, correlation_id) for tool, params in calls]


class FakeModel:
    """Scripted model: returns the claims it is given; records calls."""

    def __init__(self, claims: list[dict[str, Any]] | None = None, plan_calls: list[tuple[str, dict]] | None = None, repair_claims: list[dict[str, Any]] | None = None, summary: str = "", repair_summary: str | None = None, suggestions: list[str] | None = None) -> None:
        self.suggestions = suggestions or []
        self.claims = claims or []
        self.repair_claims = repair_claims
        self.summary = summary
        self.repair_summary = repair_summary
        self.plan_calls = plan_calls or []
        self.narrate_calls = 0
        self.plan_rounds = 0

    async def narrate(self, question: str, pack_text: str, effort: str, rejections=None, correlation_id: str | None = None) -> NarrateResult:
        self.narrate_calls += 1
        repairing = bool(rejections) and self.repair_claims is not None
        claims = self.repair_claims if repairing else self.claims
        summary = self.repair_summary if (repairing and self.repair_summary is not None) else self.summary
        return NarrateResult(TurnClaims(claims=[Claim.model_validate(c) for c in claims], summary=summary, suggestions=self.suggestions), Usage(input_tokens=1200, output_tokens=200, model_calls=1))

    async def plan(self, question: str, pack_text: str, prior_calls, correlation_id: str | None = None) -> PlanResult:
        self.plan_rounds += 1
        calls = self.plan_calls if self.plan_rounds == 1 else []
        return PlanResult(calls, Usage(input_tokens=800, output_tokens=50, model_calls=1))


@pytest.fixture()
def secret_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "delegation_secret"
    path.write_text(TEST_SECRET)
    from app import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "delegation_secret_file", path)
    monkeypatch.setattr(settings_module.settings, "state_dir", tmp_path / "state")
    return path
