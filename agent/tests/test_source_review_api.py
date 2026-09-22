from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import main as main_module
from app.delegation import mint_for_tests
from app.guideline_retriever import FrozenCorpus, GuidelineChunk
from app.source_review import SourceReviewEnvelope
from app.source_review import GuidelineSourceReviewResolver
from conftest import TEST_SECRET

CID = "a" * 32
TURN = "b" * 16


def _citation() -> dict[str, object]:
    return {
        "citation_id": "ct1",
        "claim_id": "c1",
        "source_id": "openemr:lists:1",
        "source_type": "openemr_record",
        "title": "Synthetic problem",
        "page_or_section": {"kind": "chart_section", "section": "problems"},
        "field_or_chunk_id": "title",
        "quote_or_value": {"kind": "record_value", "value": "Synthetic condition"},
        "source_version": "problems-v1",
        "href": "/interface/patient_file/summary/demographics.php",
        "retrieved_at": "2026-09-22T00:00:00Z",
    }


class Graph:
    async def aget_state(self, config):
        return SimpleNamespace(values={"history": [{
            "turn_id": TURN,
            "claims": [{"id": "c1", "citations": [_citation()]}],
        }]})


class Resolver:
    def __init__(self) -> None:
        self.calls = 0
        self.correlation_ids: list[str] = []

    async def resolve(
        self,
        conversation_id: str,
        turn_id: str,
        citation: dict[str, object],
        correlation_id: str,
    ):
        self.calls += 1
        self.correlation_ids.append(correlation_id)
        return SourceReviewEnvelope.model_validate({
            "citation": citation,
            "source": {
                "source_type": "openemr_record",
                "source_id": "openemr:lists:1",
                "chart_section": "problems",
                "record_label": "Synthetic problem",
                "source_version": "problems-v1",
                "field_id": "title",
                "displayed_value": "Synthetic condition",
                "href": "/interface/patient_file/summary/demographics.php",
            },
        })


def _guideline_citation() -> dict[str, object]:
    quote = "Screen adults for high blood pressure."
    return {
        "citation_id": "ct2", "claim_id": "c2",
        "source_id": "guideline:uspstf-2026q3:hypertension:hypertension-001",
        "source_type": "guideline", "title": "Synthetic Clinical Society — Synthetic hypertension guidance",
        "page_or_section": {"kind": "guideline_section", "section_path": ["Screening"], "chunk_ordinal": 1},
        "field_or_chunk_id": "hypertension-001", "quote_or_value": {"kind": "exact_quote", "quote": quote},
        "publisher": "Synthetic Clinical Society", "jurisdiction": "US", "canonical_url": "https://example.test/hypertension",
        "topic": "hypertension", "corpus_version": "uspstf-2026q3", "source_sha256": "a" * 64,
        "chunk_sha256": hashlib.sha256(quote.encode()).hexdigest(), "href": "https://example.test/hypertension",
        "retrieved_at": "2026-09-21T00:00:01Z",
    }


def test_source_route_requires_exact_turn_token_and_resolves_only_a_displayed_citation(secret_file) -> None:
    resolver = Resolver()
    main_module.app.state.graph = Graph()
    main_module.app.state.source_review_resolver = resolver
    client = TestClient(main_module.app)
    token = mint_for_tests(CID, TURN, TEST_SECRET)

    response = client.get(
        f"/v1/conversations/{CID}/turns/{TURN}/sources/ct1",
        headers={"X-Copilot-Token": token, "X-Correlation-Id": "corr-source-review-1"},
    )

    assert response.status_code == 200
    assert response.json()["citation"]["citation_id"] == "ct1"
    assert resolver.calls == 1
    assert resolver.correlation_ids == ["corr-source-review-1"]

    wrong_turn = "c" * 16
    denied = client.get(
        f"/v1/conversations/{CID}/turns/{wrong_turn}/sources/ct1",
        headers={"X-Copilot-Token": token},
    )
    assert denied.status_code == 403
    assert resolver.calls == 1


def test_source_route_fails_closed_for_unknown_or_unconfigured_citation(secret_file) -> None:
    resolver = Resolver()
    main_module.app.state.graph = Graph()
    main_module.app.state.source_review_resolver = resolver
    client = TestClient(main_module.app)
    token = mint_for_tests(CID, TURN, TEST_SECRET)

    missing = client.get(
        f"/v1/conversations/{CID}/turns/{TURN}/sources/ct99",
        headers={"X-Copilot-Token": token},
    )
    assert missing.status_code == 404
    assert resolver.calls == 0

    del main_module.app.state.source_review_resolver
    unavailable = client.get(
        f"/v1/conversations/{CID}/turns/{TURN}/sources/ct1",
        headers={"X-Copilot-Token": token},
    )
    assert unavailable.status_code == 503
    assert "Synthetic condition" not in unavailable.text


def test_source_route_resolves_a_week2_lane_claim_from_the_same_rendered_turn(secret_file) -> None:
    citation = _guideline_citation()
    quote = "Screen adults for high blood pressure."
    chunk = GuidelineChunk.model_validate({
        "chunk_id": "hypertension-001", "document_id": "hypertension", "corpus_version": "uspstf-2026q3",
        "publisher": "Synthetic Clinical Society", "jurisdiction": "US", "title": "Synthetic hypertension guidance",
        "canonical_url": "https://example.test/hypertension", "topic": "hypertension", "section_path": ["Screening"],
        "chunk_ordinal": 1, "exact_text": quote, "source_sha256": "a" * 64,
        "chunk_sha256": citation["chunk_sha256"],
    })
    main_module.app.state.graph = SimpleNamespace(aget_state=lambda config: _state_with_guideline(citation))
    main_module.app.state.source_review_resolver = GuidelineSourceReviewResolver(
        lambda: FrozenCorpus("uspstf-2026q3", "2026-09-21T00:00:00Z", "2026-09-21T00:00:00Z", [chunk]),
        now=lambda: datetime(2026, 9, 22, tzinfo=timezone.utc),
    )
    client = TestClient(main_module.app)
    token = mint_for_tests(CID, TURN, TEST_SECRET)

    response = client.get(
        f"/v1/conversations/{CID}/turns/{TURN}/sources/ct2",
        headers={"X-Copilot-Token": token},
    )

    assert response.status_code == 200
    assert response.json()["source"]["source_type"] == "guideline"


class _GuidelineState:
    def __init__(self, citation: dict[str, object]) -> None:
        self.values = {"history": [{"turn_id": TURN, "claims": [], "guideline_claims": [{"id": "c2", "citations": [citation]}]}]}


async def _state_with_guideline(citation: dict[str, object]) -> _GuidelineState:
    return _GuidelineState(citation)
