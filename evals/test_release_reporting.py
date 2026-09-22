"""Machine-readable Boolean verdicts at the public eval-runner seam."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import run
from run import run_offline, write_report


def test_offline_case_runs_and_records_each_rubric_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = {
        "id": "INDEPENDENT-RUBRICS-001",
        "name": "One passing node cannot mask a failing rubric",
        "category": "regression",
        "tier": "golden",
        "rubrics": ["schema_valid", "safe_refusal"],
        "pytest_by_rubric": {
            "schema_valid": ["tests/test_contracts.py::test_exported_schema_is_current"],
            "safe_refusal": [
                "tests/test_graph.py::test_closed_conversation_is_denied_before_any_tool_call"
            ],
        },
    }
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> SimpleNamespace:
        commands.append(command)
        failed = command[-1].endswith(
            "test_closed_conversation_is_denied_before_any_tool_call"
        )
        return SimpleNamespace(
            returncode=1 if failed else 0,
            stdout="1 failed" if failed else "1 passed",
            stderr="",
        )

    monkeypatch.setattr(run.subprocess, "run", fake_run)

    result = run_offline(case)

    assert result.passed is False
    assert result.rubrics == {"schema_valid": True, "safe_refusal": False}
    assert result.rubric_evidence == {
        "schema_valid": {
            "kind": "pytest",
            "node_ids": ["tests/test_contracts.py::test_exported_schema_is_current"],
            "exit_code": 0,
        },
        "safe_refusal": {
            "kind": "pytest",
            "node_ids": [
                "tests/test_graph.py::test_closed_conversation_is_denied_before_any_tool_call"
            ],
            "exit_code": 1,
        },
    }
    assert len(commands) == 2


def test_offline_case_blocks_when_an_applicable_rubric_has_no_pytest_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = {
        "id": "MISSING-RUBRIC-EVIDENCE-001",
        "name": "Missing evidence blocks",
        "category": "regression",
        "tier": "golden",
        "rubrics": ["schema_valid", "safe_refusal"],
        "pytest_by_rubric": {
            "schema_valid": ["tests/test_contracts.py::test_exported_schema_is_current"],
        },
    }
    commands: list[list[str]] = []

    def passing_run(command: list[str], **_: object) -> SimpleNamespace:
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="1 passed", stderr="")

    monkeypatch.setattr(
        run.subprocess,
        "run",
        passing_run,
    )

    result = run_offline(case)

    assert result.passed is False
    assert result.rubrics == {"schema_valid": True, "safe_refusal": "unmeasured"}
    assert result.rubric_evidence["safe_refusal"] == {
        "kind": "unmeasured",
        "detail": "no pytest node IDs mapped to applicable rubric safe_refusal",
    }
    assert "safe_refusal" in result.failures[0]
    assert len(commands) == 1


def test_offline_case_reports_boolean_rubrics_with_pytest_evidence() -> None:
    case = yaml.safe_load(
        (Path(__file__).parent / "cases" / "RET-NO-RESULT-001.yaml").read_text()
    )

    result = run_offline(case)

    assert result.passed is True
    assert result.rubrics == {"safe_refusal": True}
    assert result.rubric_evidence["safe_refusal"]["kind"] == "pytest"
    assert result.rubric_evidence["safe_refusal"]["exit_code"] == 0


def test_json_report_groups_attempts_and_carries_comparable_identity(tmp_path: Path) -> None:
    case = yaml.safe_load(
        (Path(__file__).parent / "cases" / "RET-NO-RESULT-001.yaml").read_text()
    )
    result = run_offline(case)
    meta = {
        "full_run": False,
        "commit": "candidate123",
        "environment": "local",
        "model": "deterministic-offline",
        "timestamp": "2026-09-21T00:00:00+00:00",
        "dataset_version": "af-cohort-v1",
        "runner": "evals/run.py",
        "repeat": 1,
        "label": "test",
        "include_holdout": False,
    }

    json_path, _ = write_report([result], meta, tmp_path)
    report = json.loads(json_path.read_text())

    assert report["case_count"] == 1
    assert report["cases"] == [
        {
            "id": "RET-NO-RESULT-001",
            "attempts": [
                {
                    "attempt": 1,
                    "passed": True,
                    "rubrics": {"safe_refusal": True},
                    "rubric_evidence": result.rubric_evidence,
                }
            ],
        }
    ]
    assert report["identity"]["manifest_sha256"]
    assert report["identity"]["fixtures_sha256"]
    assert report["identity"]["candidate_commit"] == "candidate123"
    assert report["identity"]["extraction_identity"].startswith("source-sha256:")
    assert report["identity"]["embedding_identity"].startswith("source-sha256:")
    assert report["identity"]["reranker_identity"].startswith("source-sha256:")
    manifest_entry = next(
        entry for entry in report["manifest"] if entry["id"] == result.id
    )
    assert manifest_entry["rubrics"] == ["safe_refusal"]
