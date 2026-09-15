"""Contract tests: recorded gateway responses (synthetic cohort) must validate
against the Pydantic source of truth, and the exported JSON Schema must be in
sync with the models (ADR-0004)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.contracts import ToolRequest, ToolResponse, ToolStatus

FIXTURES = sorted((Path(__file__).parent / "fixtures" / "tool_responses").glob("*.json"))


@pytest.mark.parametrize("path", FIXTURES, ids=[p.name for p in FIXTURES])
def test_recorded_gateway_response_matches_contract(path: Path) -> None:
    payload = json.loads(path.read_text())
    response = ToolResponse.model_validate(payload)
    assert response.tool in path.name
    assert response.status in ToolStatus
    for record in response.records:
        assert record.source.source_id.startswith("openemr:")


def test_tool_request_rejects_patient_identifier() -> None:
    with pytest.raises(ValidationError):
        ToolRequest.model_validate({"tool": "encounters", "params": {"pid": 900001}, "correlation_id": "abcd1234"})


def test_status_empty_is_distinct_from_unavailable() -> None:
    base = json.loads(FIXTURES[0].read_text())
    base.update({"records": [], "status": "unavailable", "reason": "service_error"})
    assert ToolResponse.model_validate(base).status is ToolStatus.unavailable


def test_exported_schema_is_current() -> None:
    result = subprocess.run([sys.executable, "-m", "app.contracts.export", "--check"], capture_output=True, text=True, cwd=Path(__file__).parents[1])
    assert result.returncode == 0, result.stderr
