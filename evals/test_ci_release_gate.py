"""GitLab release jobs are automatic and fail closed."""

from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]


def test_gitlab_corpus_and_candidate_gates_are_automatic_and_blocking() -> None:
    config = yaml.safe_load((ROOT / ".gitlab-ci.yml").read_text())

    corpus = config["test:evals-corpus"]
    candidate = config["test:evals-candidate"]
    for job in (corpus, candidate):
        assert job.get("when") != "manual"
        assert job.get("allow_failure", False) is False

    assert any("eval-local-gate.sh" in line for line in corpus["script"])
    assert any("run-candidate-release-gate.sh" in line for line in candidate["script"])


def test_candidate_gate_requires_pipeline_matched_identity() -> None:
    script = (ROOT / "scripts" / "run-candidate-release-gate.sh").read_text()

    assert "CANDIDATE_COMMIT_SHA" in script
    assert "CI_COMMIT_SHA" in script
    assert "CANDIDATE_RUNTIME_IMAGE" in script
    assert "candidate_identity.py" in script
    assert "APPROVED_BASELINE_PATH" in script
