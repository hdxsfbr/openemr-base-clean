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


class FakeModel:
    """Scripted model: returns the claims it is given; records calls."""

    def __init__(self, claims: list[dict[str, Any]] | None = None, plan_calls: list[tuple[str, dict]] | None = None, repair_claims: list[dict[str, Any]] | None = None) -> None:
        self.claims = claims or []
        self.repair_claims = repair_claims
        self.plan_calls = plan_calls or []
        self.narrate_calls = 0
        self.plan_rounds = 0

    async def narrate(self, question: str, pack_text: str, effort: str, rejections=None) -> NarrateResult:
        self.narrate_calls += 1
        claims = self.repair_claims if (rejections and self.repair_claims is not None) else self.claims
        return NarrateResult(TurnClaims(claims=[Claim.model_validate(c) for c in claims]), Usage(input_tokens=1200, output_tokens=200, model_calls=1))

    async def plan(self, question: str, pack_text: str, prior_calls) -> PlanResult:
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
