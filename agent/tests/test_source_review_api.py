from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import main as main_module
from app.delegation import mint_for_tests
from app.source_review import SourceReviewEnvelope
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
