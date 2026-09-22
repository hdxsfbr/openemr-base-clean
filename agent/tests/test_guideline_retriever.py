"""Deterministic Slice 3B tests for the offline hybrid retrieval engine."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from app.contracts import EvidenceQuery
from app.guideline_corpus.build import CORPUS_ROOT
from app.guideline_retriever import (
    RERANKER_TOKENIZER_SHA256,
    GuidelineRetriever,
    RetrievalNoEvidence,
    RetrievalUnavailable,
)


class StubEmbedder:
    def encode_query(self, _text: str) -> np.ndarray:
        return np.zeros((1, 384), dtype=np.float32)


class StubReranker:
    def __init__(self, scores: list[float] | Exception) -> None:
        self.scores = scores
        self.calls = 0

    def score(self, _query: str, passages: object) -> list[float]:
        self.calls += 1
        if isinstance(self.scores, Exception):
            raise self.scores
        assert len(self.scores) == len(passages)  # type: ignore[arg-type]
        return self.scores


def query(**changes: object) -> EvidenceQuery:
    payload: dict[str, object] = {
        "concepts": ["aaa"],
        "topic_filter": "aaa",
        "requested_top_k": 5,
        "correlation_id": "123e4567-e89b-12d3-a456-426614174000",
        "handoff_id": "a" * 32,
        "deadline_ms": 2000,
    }
    payload.update(changes)
    return EvidenceQuery.model_validate(payload)


def retriever(*, scores: list[float] | Exception = [1.0, 0.5], **kwargs: object) -> GuidelineRetriever:
    return GuidelineRetriever(embedder=StubEmbedder(), reranker=StubReranker(scores), **kwargs)  # type: ignore[arg-type]


def install_legs(instance: GuidelineRetriever, sparse: list[tuple[str, float]], dense: list[tuple[str, float]]) -> None:
    instance._sparse = lambda _text, _allowed: sparse  # type: ignore[method-assign]
    instance._dense = lambda _text, _allowed: dense  # type: ignore[method-assign]


def test_lexical_only_hit_returns_an_unchanged_active_chunk() -> None:
    instance = retriever(scores=[0.5])
    install_legs(instance, [("aaa-001", 3.0)], [])

    result = instance.retrieve(query(requested_top_k=1))

    assert [item.chunk_id for item in result.excerpts] == ["aaa-001"]
    source = instance.chunks["aaa-001"]
    assert result.excerpts[0].exact_text == source["exact_text"]
    assert result.excerpts[0].chunk_sha256 == source["chunk_sha256"]
    assert result.excerpts[0].section_path == source["section_path"]
    assert str(result.excerpts[0].canonical_url) == source["canonical_url"]
    assert result.excerpts[0].source_sha256 == source["source_sha256"]
    assert result.measurement.dense_candidates == 0


def test_semantic_only_hit_returns_an_unchanged_active_chunk() -> None:
    instance = retriever(scores=[0.5])
    install_legs(instance, [], [("aaa-002", 0.9)])

    result = instance.retrieve(query(requested_top_k=1))

    assert [item.chunk_id for item in result.excerpts] == ["aaa-002"]
    assert result.measurement.sparse_candidates == 0


def test_dedup_rrf_order_and_independent_rerank_order_are_stable() -> None:
    instance = retriever(scores=[0.1, 0.9, 0.2])
    install_legs(
        instance,
        [("aaa-001", 3.0), ("aaa-002", 2.0)],
        [("aaa-002", 0.9), ("aaa-003", 0.8)],
    )

    result = instance.retrieve(query(requested_top_k=3))

    # RRF puts the duplicate candidate first; the separate reranker changes it.
    assert [item.chunk_id for item in result.fused] == ["aaa-002", "aaa-001", "aaa-003"]
    assert [item.chunk_id for item in result.excerpts] == ["aaa-001", "aaa-003", "aaa-002"]
    assert len({item.chunk_id for item in result.fused}) == 3
    assert len(result.candidates) == 4


def test_rrf_and_reranker_ties_break_by_chunk_id_and_top_k_is_bounded() -> None:
    instance = retriever(scores=[0.7, 0.7])
    install_legs(instance, [("aaa-003", 1.0), ("aaa-002", 1.0)], [("aaa-002", 1.0), ("aaa-003", 1.0)])

    result = instance.retrieve(query(requested_top_k=2))

    assert [item.chunk_id for item in result.fused] == ["aaa-002", "aaa-003"]
    assert [item.chunk_id for item in result.excerpts] == ["aaa-002", "aaa-003"]


def test_no_result_and_reranker_outage_fail_closed_without_excerpts() -> None:
    instance = retriever(scores=[])
    install_legs(instance, [], [])
    with pytest.raises(RetrievalNoEvidence):
        instance.retrieve(query())

    unavailable = retriever(scores=RetrievalUnavailable("synthetic"))
    install_legs(unavailable, [("aaa-001", 1.0)], [("aaa-002", 1.0)])
    with pytest.raises(RetrievalUnavailable):
        unavailable.retrieve(query())

    failed_sparse = retriever(scores=[])
    failed_sparse._sparse = lambda _text, _allowed: (_ for _ in ()).throw(RetrievalUnavailable("synthetic"))  # type: ignore[method-assign]
    with pytest.raises(RetrievalUnavailable):
        failed_sparse.retrieve(query())


def test_stale_pointer_corruption_and_deadline_fail_before_evidence(tmp_path: Path) -> None:
    stale = retriever(now=lambda: datetime(2026, 10, 7, tzinfo=UTC))
    with pytest.raises(RetrievalUnavailable):
        stale.retrieve(query())

    copied = tmp_path / "artifacts"
    shutil.copytree(CORPUS_ROOT / "artifacts", copied)
    (copied / "dense.ids.json").write_text("[]\n")
    with pytest.raises(RetrievalUnavailable):
        GuidelineRetriever(artifact_dir=copied, embedder=StubEmbedder(), reranker=StubReranker([]))

    ticks = iter([0.0, 0.0, 0.002, 0.002, 0.002])
    timed = retriever(monotonic=lambda: next(ticks), scores=[])
    install_legs(timed, [("aaa-001", 1.0)], [("aaa-002", 1.0)])
    with pytest.raises(RetrievalUnavailable):
        timed.retrieve(query(deadline_ms=1))


def test_missing_local_models_fail_closed_and_no_query_text_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    with pytest.raises(RetrievalUnavailable):
        GuidelineRetriever()
    assert "synthetic privacy canary" not in caplog.text


def test_wrong_corpus_version_is_rejected_before_any_leg() -> None:
    instance = retriever(scores=[])
    wrong = query().model_copy(update={"active_corpus_version": "wrong-version"})
    with pytest.raises(RetrievalUnavailable):
        instance.retrieve(wrong)


@pytest.mark.skipif(not (CORPUS_ROOT.parent / ".guideline_models").is_dir(), reason="pinned local models are provisioned only for offline benchmark runs")
def test_real_pinned_models_match_hashes_and_return_exact_active_chunks() -> None:
    models = CORPUS_ROOT.parent / ".guideline_models"
    instance = GuidelineRetriever(embedding_model_dir=models / "bge", reranker_model_dir=models / "reranker")
    result = instance.retrieve(query(requested_top_k=1))
    assert result.excerpts
    assert all(item.exact_text == instance.chunks[item.chunk_id]["exact_text"] for item in result.excerpts)
    assert RERANKER_TOKENIZER_SHA256 == "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66"
