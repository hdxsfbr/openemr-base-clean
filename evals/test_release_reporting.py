"""Machine-readable Boolean verdicts at the public eval-runner seam."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from run import run_offline, write_report


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
