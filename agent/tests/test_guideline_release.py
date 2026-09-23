from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.contracts import EvidenceWorkerResult, GuidelineEvidenceRequest, GuidelineExcerpt
from app.guideline_release import GuidelineReleaseService


ROOT = Path(__file__).parents[1] / "guideline_corpus"
NOW = lambda: datetime(2026, 9, 22, tzinfo=timezone.utc)


class Worker:
    def __init__(self, result): self.result = result
    def invoke(self, query): return self.result


def result_for_first_chunk():
    row = json.loads((ROOT / "artifacts" / "chunks.jsonl").read_text().splitlines()[0])
    payload = {key: value for key, value in row.items() if key != "review_date"}
    excerpt = GuidelineExcerpt.model_validate({**payload, "source_id": f"guideline:{row['corpus_version']}:{row['document_id']}:{row['chunk_id']}"})
    return EvidenceWorkerResult.model_validate({
        "correlation_id": "guideline.0001", "handoff_id": "a" * 32, "status": "completed",
        "artifact_manifest_sha256": "b" * 64, "embedding_model_revision": "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a",
        "reranker_model_revision": "233902d83d1a76f73c2047c6952d4f5dcb1bee0a", "candidate_count": 1, "hit_count": 1,
        "timings": {"sparse_ms": 1, "dense_ms": 1, "fusion_ms": 1, "rerank_ms": 1, "total_ms": 4}, "excerpts": [excerpt],
    })


def test_exact_active_excerpt_is_the_only_displayable_guideline_claim():
    service = GuidelineReleaseService(Worker(result_for_first_chunk()), ROOT, now=NOW)
    response = service.invoke("c" * 32, "d" * 16, "guideline.0001", GuidelineEvidenceRequest(concepts=["aaa"], topic_filter="aaa"))
    assert response.status == "complete" and len(response.claims) == 1
    assert response.claims[0].claim_class == "guideline_evidence"
    assert "applicability was not determined" in response.applicability_notice
    source = service.resolve("c" * 32, "d" * 16, response.claims[0].source_ids[0])
    assert source and source.exact_text.startswith(response.claims[0].facts.quote)


def test_tampered_active_chunk_withholds_and_never_reopens(monkeypatch):
    service = GuidelineReleaseService(Worker(result_for_first_chunk()), ROOT, now=NOW)
    monkeypatch.setattr(service, "_active_rows", lambda: {})
    response = service.invoke("c" * 32, "d" * 16, "guideline.0001", GuidelineEvidenceRequest(concepts=["aaa"], topic_filter="aaa"))
    assert response.claims == [] and response.limitations[0].code == "guideline_retrieval_unavailable"
    assert service.resolve("c" * 32, "d" * 16, "guideline:uspstf-recommendations-2026-09-21-v2:aaa:aaa-000") is None


def test_stale_active_pointer_has_a_typed_no_evidence_state():
    stale = lambda: datetime(2026, 10, 20, tzinfo=timezone.utc)
    service = GuidelineReleaseService(Worker(result_for_first_chunk()), ROOT, now=stale)
    response = service.invoke("c" * 32, "d" * 16, "guideline.0001", GuidelineEvidenceRequest(concepts=["aaa"], topic_filter="aaa"))
    assert response.claims == [] and response.limitations[0].code == "guideline_corpus_stale"


def test_final_guideline_reverification_withholds_a_claim_when_the_active_source_changes(monkeypatch):
    service = GuidelineReleaseService(Worker(result_for_first_chunk()), ROOT, now=NOW)
    response = service.invoke("c" * 32, "d" * 16, "guideline.0001", GuidelineEvidenceRequest(concepts=["aaa"], topic_filter="aaa"))
    assert response.claims
    monkeypatch.setattr(service, "_active_rows", lambda: {})

    final = service.reverify(response, "guideline.0001")

    assert final.status == "limited"
    assert final.claims == []
    assert final.limitations[0].code == "guideline_retrieval_unavailable"


def test_final_guideline_reverification_rejects_a_mismatched_correlation_without_reopening_sources():
    service = GuidelineReleaseService(Worker(result_for_first_chunk()), ROOT, now=NOW)
    response = service.invoke("c" * 32, "d" * 16, "guideline.0001", GuidelineEvidenceRequest(concepts=["aaa"], topic_filter="aaa"))

    final = service.reverify(response, "different-correlation")

    assert final.status == "limited"
    assert final.claims == []
    assert final.limitations[0].code == "guideline_malformed_output"
