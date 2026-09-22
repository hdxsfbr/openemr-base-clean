"""Offline integrity tests for the checked-in Slice 3A corpus bundle."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.guideline_corpus.build import (
    CORPUS_ROOT,
    CorpusError,
    build_chunks,
    load_manifest,
    read_jsonl,
    validate_artifacts,
    validate_inputs,
)


ARTIFACTS = CORPUS_ROOT / "artifacts"
SOURCE_INPUT = Path(__file__).parents[2] / "docs" / "research" / "week2-retrieval-benchmark" / "corpus.jsonl"


def test_committed_artifacts_bind_exactly_the_same_sparse_and_dense_chunk_set() -> None:
    manifest = load_manifest()
    artifact = validate_artifacts(ARTIFACTS, manifest)
    chunks = read_jsonl(ARTIFACTS / "chunks.jsonl")
    assert artifact["chunk_count"] == len(chunks) == 160
    assert len({row["chunk_id"] for row in chunks}) == 160
    assert json.loads((ARTIFACTS / "dense.ids.json").read_text()) == [row["chunk_id"] for row in chunks]
    assert all(row["section_path"] for row in chunks)


def test_normalization_and_heading_aware_chunking_are_stable_from_frozen_sources() -> None:
    manifest = load_manifest()
    snapshots = validate_inputs(manifest, read_jsonl(SOURCE_INPUT))
    first = build_chunks(manifest, snapshots)
    second = build_chunks(manifest, snapshots)
    assert first == second
    assert [row["chunk_id"] for row in first] == [row["chunk_id"] for row in read_jsonl(ARTIFACTS / "chunks.jsonl")]
    assert all(row["chunk_sha256"] for row in first)


def test_altered_source_content_and_incomplete_provenance_fail_before_build() -> None:
    manifest = load_manifest()
    rows = read_jsonl(SOURCE_INPUT)
    rows[0]["text"] = "synthetic privacy canary"
    with pytest.raises(CorpusError):
        validate_inputs(manifest, rows)

    manifest["sources"][0].pop("approved_at")
    with pytest.raises(CorpusError):
        validate_inputs(manifest, read_jsonl(SOURCE_INPUT))

    manifest = load_manifest()
    manifest["sources"][0]["approved_at"] = "2026-10-07T00:00:00Z"
    with pytest.raises(CorpusError):
        validate_inputs(manifest, read_jsonl(SOURCE_INPUT))


def test_corrupted_artifact_fails_closed(tmp_path: Path) -> None:
    copied = tmp_path / "artifacts"
    shutil.copytree(ARTIFACTS, copied)
    (copied / "dense.ids.json").write_text("[]\n")
    with pytest.raises(CorpusError):
        validate_artifacts(copied, load_manifest())


def test_checked_in_active_pointer_validates_without_a_model_or_network() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "app.guideline_corpus.build", "validate"],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "\"status\": \"ok\"" in result.stdout
