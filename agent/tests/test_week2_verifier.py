"""Closed-registry verification tests for Week 2 clinical claims."""

from __future__ import annotations

import hashlib
import pytest

from app.contracts.week2 import (
    GuidelineChunkSource,
    OpenEmrRecordSource,
    ReviewedDocumentFieldSource,
    TurnBinding,
)
from app.week2_verifier import CurrentTurnSourceRegistry, RegisteredSource, verify_week2_claims


def _binding(**overrides: str) -> TurnBinding:
    values = {
        "site_id": "demo-site",
        "user_id": "demo-physician",
        "patient_id": "demo-patient",
        "conversation_id": "conversation-1",
        "turn_id": "turn-1",
        "correlation_id": "conversation-1.turn-1",
        "authorized_at": "2026-09-21T12:00:00Z",
    }
    values.update(overrides)
    return TurnBinding.model_validate(values)


def _openemr_source() -> OpenEmrRecordSource:
    source_id = "openemr:prescriptions:42"
    return OpenEmrRecordSource.model_validate(
        {
            "source_type": "openemr_record",
            "source_id": source_id,
            "source_ref": {"source_id": source_id, "table": "prescriptions", "id": 42},
            "chart_section": "medications",
            "record_label": "Metformin 500 mg tablet",
            "source_version": "medications-v1",
            "retrieved_at": "2026-09-21T12:00:01Z",
            "fields": {"name": "Metformin 500 mg tablet", "status": "active"},
            "href": "/interface/patient_file/summary/demographics.php",
        }
    )


def _openemr_lab_source() -> OpenEmrRecordSource:
    source_id = "openemr:procedure_result:84"
    return OpenEmrRecordSource.model_validate(
        {
            "source_type": "openemr_record",
            "source_id": source_id,
            "source_ref": {"source_id": source_id, "table": "procedure_result", "id": 84},
            "chart_section": "labs",
            "record_label": "Potassium result",
            "source_version": "labs-v1",
            "retrieved_at": "2026-09-21T12:00:01Z",
            "fields": {
                "analyte": "Potassium",
                "value_text": "4.2",
                "unit": "mmol/L",
                "flag": "normal",
                "date": "2026-09-20",
            },
            "href": "/interface/patient_file/summary/labs.php",
        }
    )


def _document_source(
    *,
    decision: str = "approved",
    reviewed_value: str = "annual visit",
) -> ReviewedDocumentFieldSource:
    source_document_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    record_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    field_id = "chief_concern"
    return ReviewedDocumentFieldSource.model_validate(
        {
            "source_type": "reviewed_document",
            "source_id": f"document:{source_document_id}:record:{record_id}:v:1:field:{field_id}",
            "source_document_id": source_document_id,
            "source_content_sha256": "a" * 64,
            "record_id": record_id,
            "record_version": 1,
            "record_status": "active",
            "record_type": "intake_response",
            "field_id": field_id,
            "review_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            "review_decision": decision,
            "reviewed_value": reviewed_value,
            "evidence": [
                {
                    "evidence_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
                    "page_number": 1,
                    "box": {"x": 0.1, "y": 0.2, "width": 0.5, "height": 0.1},
                    "printed_quote": "annual visit",
                    "ocr_span_start": 0,
                    "ocr_span_end": 12,
                    "ocr_text_sha256": "b" * 64,
                    "rendered_page_sha256": "c" * 64,
                    "confidence": 0.99,
                    "validation": ["valid"],
                }
            ],
            "schema_version": "1.0.0",
            "retrieved_at": "2026-09-21T12:00:01Z",
            "href": "/interface/modules/custom_modules/oe-module-copilot/public/document.php?id=demo",
        }
    )


def _guideline_source() -> GuidelineChunkSource:
    exact_text = "For adults 18 years or older, screening is recommended with office blood pressure measurement."
    return GuidelineChunkSource.model_validate(
        {
            "source_type": "guideline",
            "source_id": "guideline:demo-2026q3:hypertension:screening-1",
            "corpus_version": "demo-2026q3",
            "document_id": "hypertension",
            "chunk_id": "screening-1",
            "publisher": "Demo Preventive Services Group",
            "title": "Screening for Hypertension",
            "jurisdiction": "US",
            "canonical_url": "https://guidelines.example.test/hypertension",
            "publication_date": "2024-06-01",
            "topic": "adult-hypertension-screening",
            "section_path": ["Recommendation", "Adults"],
            "chunk_ordinal": 1,
            "exact_text": exact_text,
            "source_sha256": "d" * 64,
            "chunk_sha256": hashlib.sha256(exact_text.encode()).hexdigest(),
            "retrieved_at": "2026-09-21T12:00:01Z",
            "corpus_retrieved_at": "2026-09-15T12:00:00Z",
            "approved_at": "2026-09-15T13:00:00Z",
            "href": "https://guidelines.example.test/hypertension#screening",
        }
    )


def test_exact_openemr_facts_receive_registry_authored_citations() -> None:
    binding = _binding()
    registry = CurrentTurnSourceRegistry(
        binding=binding,
        sources=[RegisteredSource(source=_openemr_source(), binding=binding)],
        verified_at="2026-09-21T12:00:02Z",
    )

    result = verify_week2_claims(
        [
            {
                "id": "c1",
                "claim_class": "patient_record",
                "type": "medication_status",
                "text": "Metformin 500 mg tablet is active.",
                "facts": {"name": "Metformin 500 mg tablet", "status": "active"},
                "source_ids": ["openemr:prescriptions:42"],
                "section": "medications",
            }
        ],
        registry,
    )

    assert result.outcome == "passed"
    assert result.patient_record.rejected == []
    claim = result.patient_record.accepted[0]
    assert [citation.field_or_chunk_id for citation in claim.citations] == ["name", "status"]
    assert [citation.quote_or_value.value for citation in claim.citations] == [
        "Metformin 500 mg tablet",
        "active",
    ]


@pytest.mark.parametrize(
    ("registry_source", "source_id", "expected_code"),
    [
        (None, "openemr:prescriptions:99", "not_found"),
        ("wrong_turn", "openemr:prescriptions:42", "unauthorized"),
        ("stale", "openemr:prescriptions:42", "stale"),
    ],
)
def test_registry_rejects_unknown_wrong_turn_and_stale_patient_sources(
    registry_source: str | None,
    source_id: str,
    expected_code: str,
) -> None:
    binding = _binding()
    entries = []
    if registry_source is not None:
        entries = [
            RegisteredSource(
                source=_openemr_source(),
                binding=_binding(turn_id="other-turn") if registry_source == "wrong_turn" else binding,
                state="stale" if registry_source == "stale" else "resolved",
            )
        ]
    registry = CurrentTurnSourceRegistry(
        binding=binding,
        sources=entries,
        verified_at="2026-09-21T12:00:02Z",
    )

    result = verify_week2_claims(
        [
            {
                "id": "c1",
                "claim_class": "patient_record",
                "type": "medication_status",
                "text": "Metformin 500 mg tablet is active.",
                "facts": {"name": "Metformin 500 mg tablet", "status": "active"},
                "source_ids": [source_id],
                "section": "medications",
            }
        ],
        registry,
    )

    assert result.outcome == "rejected"
    assert result.patient_record.rejected[0].code == expected_code
    assert result.patient_record.limitations[0].kind == "withheld"
    assert result.patient_record.accepted == []


def test_openemr_projection_retrieved_before_current_authorization_is_stale() -> None:
    binding = _binding(authorized_at="2026-09-21T12:00:05Z")
    registry = CurrentTurnSourceRegistry(
        binding=binding,
        sources=[RegisteredSource(source=_openemr_source(), binding=binding)],
        verified_at="2026-09-21T12:00:06Z",
    )

    result = verify_week2_claims(
        [
            {
                "id": "c1",
                "claim_class": "patient_record",
                "type": "medication_status",
                "text": "Metformin 500 mg tablet is active.",
                "facts": {"name": "Metformin 500 mg tablet", "status": "active"},
                "source_ids": ["openemr:prescriptions:42"],
                "section": "medications",
            }
        ],
        registry,
    )

    assert result.patient_record.rejected[0].code == "stale"


@pytest.mark.parametrize(
    ("decision", "reviewed_value"),
    [("approved", "annual visit"), ("corrected", "annual wellness visit")],
)
def test_reviewed_intake_answer_preserves_value_evidence_hashes_and_review_decision(
    decision: str,
    reviewed_value: str,
) -> None:
    binding = _binding()
    source = _document_source(decision=decision, reviewed_value=reviewed_value)
    registry = CurrentTurnSourceRegistry(
        binding=binding,
        sources=[RegisteredSource(source=source, binding=binding)],
        verified_at="2026-09-21T12:00:02Z",
    )

    result = verify_week2_claims(
        [
            {
                "id": "c1",
                "claim_class": "patient_record",
                "type": "intake_answer",
                "text": f"Chief concern: {reviewed_value}.",
                "facts": {
                    "link_id": "chief_concern",
                    "answer": {"kind": "string", "value": reviewed_value},
                },
                "source_ids": [source.source_id],
                "section": "intake",
            }
        ],
        registry,
    )

    claim = result.patient_record.accepted[0]
    citation = claim.citations[0]
    assert citation.quote_or_value.reviewed_value == reviewed_value
    assert citation.quote_or_value.printed_quote == "annual visit"
    assert citation.quote_or_value.review_decision == decision
    assert citation.record_version == 1
    assert citation.review_id == source.review_id
    assert citation.source_content_sha256 == "a" * 64
    assert citation.ocr_text_sha256 == "b" * 64
    assert citation.rendered_page_sha256 == "c" * 64
    assert citation.page_or_section.page_number == 1


def test_model_authored_citation_metadata_is_rejected_without_erasing_an_independent_claim() -> None:
    binding = _binding()
    registry = CurrentTurnSourceRegistry(
        binding=binding,
        sources=[RegisteredSource(source=_openemr_source(), binding=binding)],
        verified_at="2026-09-21T12:00:02Z",
    )
    base = {
        "claim_class": "patient_record",
        "type": "medication_status",
        "text": "Metformin 500 mg tablet is active.",
        "facts": {"name": "Metformin 500 mg tablet", "status": "active"},
        "source_ids": ["openemr:prescriptions:42"],
        "section": "medications",
    }

    result = verify_week2_claims(
        [
            {
                **base,
                "id": "c1",
                "citations": [{"source_version": "model-selected", "source_sha256": "0" * 64}],
            },
            {**base, "id": "c2"},
        ],
        registry,
    )

    assert result.outcome == "partial"
    assert [claim.id for claim in result.patient_record.accepted] == ["c2"]
    assert result.patient_record.rejected[0].model_dump() == {
        "claim_id": "c1",
        "lane": "patient_record",
        "code": "schema_invalid",
        "detail": "Claim candidate did not match the strict Week 2 schema.",
        "source_ids": ["openemr:prescriptions:42"],
    }


def test_exact_guideline_excerpt_uses_active_fresh_corpus_and_registry_metadata() -> None:
    binding = _binding()
    source = _guideline_source()
    registry = CurrentTurnSourceRegistry(
        binding=binding,
        sources=[RegisteredSource(source=source, binding=_binding(patient_id="another-demo-patient"))],
        active_corpus_version="demo-2026q3",
        verified_at="2026-09-21T12:00:02Z",
    )
    quote = "screening is recommended with office blood pressure measurement"

    result = verify_week2_claims(
        [
            {
                "id": "c1",
                "claim_class": "guideline_evidence",
                "type": "guideline_excerpt",
                "facts": {
                    "quote": quote,
                    "publisher": source.publisher,
                    "title": source.title,
                    "topic": source.topic,
                    "section_path": source.section_path,
                },
                "source_ids": [source.source_id],
                "section": "guideline_evidence",
            }
        ],
        registry,
    )

    assert result.outcome == "passed"
    claim = result.guideline_evidence.accepted[0]
    assert claim.text == f"{source.publisher} — {source.title}: {quote}"
    assert claim.citations[0].quote_or_value.quote == quote
    assert claim.citations[0].source_sha256 == source.source_sha256
    assert claim.citations[0].chunk_sha256 == source.chunk_sha256
    assert result.patient_record.accepted == []


def test_patient_claim_cannot_smuggle_guideline_applicability_or_advice() -> None:
    binding = _binding()
    registry = CurrentTurnSourceRegistry(
        binding=binding,
        sources=[RegisteredSource(source=_openemr_source(), binding=binding)],
        verified_at="2026-09-21T12:00:02Z",
    )

    result = verify_week2_claims(
        [
            {
                "id": "c1",
                "claim_class": "patient_record",
                "type": "medication_status",
                "text": "The guideline recommends this treatment for this patient; Metformin 500 mg tablet is active.",
                "facts": {"name": "Metformin 500 mg tablet", "status": "active"},
                "source_ids": ["openemr:prescriptions:42"],
                "section": "medications",
            }
        ],
        registry,
    )

    assert result.patient_record.accepted == []
    assert result.patient_record.rejected[0].code == "applicability_forbidden"


def test_openemr_lab_claim_checks_and_cites_every_exact_asserted_value() -> None:
    binding = _binding()
    registry = CurrentTurnSourceRegistry(
        binding=binding,
        sources=[RegisteredSource(source=_openemr_lab_source(), binding=binding)],
        verified_at="2026-09-21T12:00:02Z",
    )

    result = verify_week2_claims(
        [
            {
                "id": "c1",
                "claim_class": "patient_record",
                "type": "lab_result",
                "text": "Potassium was 4.2 mmol/L on 2026-09-20, flagged normal.",
                "facts": {
                    "analyte": "Potassium",
                    "value_text": "4.2",
                    "unit": "mmol/L",
                    "flag": "normal",
                    "date": "2026-09-20",
                },
                "source_ids": ["openemr:procedure_result:84"],
                "section": "labs",
            }
        ],
        registry,
    )

    claim = result.patient_record.accepted[0]
    assert [citation.field_or_chunk_id for citation in claim.citations] == [
        "analyte",
        "value_text",
        "unit",
        "flag",
        "date",
    ]


def test_altered_openemr_value_is_withheld_with_a_patient_lane_limitation() -> None:
    binding = _binding()
    registry = CurrentTurnSourceRegistry(
        binding=binding,
        sources=[RegisteredSource(source=_openemr_lab_source(), binding=binding)],
        verified_at="2026-09-21T12:00:02Z",
    )

    result = verify_week2_claims(
        [
            {
                "id": "c1",
                "claim_class": "patient_record",
                "type": "lab_result",
                "text": "Potassium was 9.9 mmol/L on 2026-09-20, flagged normal.",
                "facts": {
                    "analyte": "Potassium",
                    "value_text": "9.9",
                    "unit": "mmol/L",
                    "flag": "normal",
                    "date": "2026-09-20",
                },
                "source_ids": ["openemr:procedure_result:84"],
                "section": "labs",
            }
        ],
        registry,
    )

    assert result.patient_record.rejected[0].code == "value_mismatch"
    assert result.patient_record.limitations[0].kind == "withheld"


def _guideline_candidate(source: GuidelineChunkSource, **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "id": "c1",
        "claim_class": "guideline_evidence",
        "type": "guideline_excerpt",
        "facts": {
            "quote": "screening is recommended with office blood pressure measurement",
            "publisher": source.publisher,
            "title": source.title,
            "topic": source.topic,
            "section_path": source.section_path,
        },
        "source_ids": [source.source_id],
        "section": "guideline_evidence",
    }
    values.update(overrides)
    return values


def test_guideline_paraphrase_and_model_authored_framing_are_lane_local_rejections() -> None:
    binding = _binding()
    source = _guideline_source()
    registry = CurrentTurnSourceRegistry(
        binding=binding,
        sources=[RegisteredSource(source=source, binding=binding)],
        active_corpus_version=source.corpus_version,
        verified_at="2026-09-21T12:00:02Z",
    )
    paraphrased_facts = _guideline_candidate(source)["facts"].copy()  # type: ignore[union-attr]
    paraphrased_facts["quote"] = "Adults should have their blood pressure checked."

    result = verify_week2_claims(
        [
            _guideline_candidate(source, facts=paraphrased_facts),
            _guideline_candidate(source, id="c2", text="This applies to the patient."),
        ],
        registry,
    )

    assert [rejection.code for rejection in result.guideline_evidence.rejected] == [
        "quote_mismatch",
        "schema_invalid",
    ]
    assert len(result.guideline_evidence.limitations) == 2
    assert result.guideline_evidence.accepted == []


@pytest.mark.parametrize(
    ("active_version", "verified_at", "state", "expected_code"),
    [
        ("demo-next", "2026-09-21T12:00:02Z", "resolved", "stale"),
        ("demo-2026q3", "2026-10-10T12:00:02Z", "resolved", "stale"),
        ("demo-2026q3", "2026-09-21T12:00:02Z", "hash_mismatch", "hash_mismatch"),
    ],
)
def test_guideline_requires_active_fresh_hash_verified_corpus(
    active_version: str,
    verified_at: str,
    state: str,
    expected_code: str,
) -> None:
    binding = _binding()
    source = _guideline_source()
    registry = CurrentTurnSourceRegistry(
        binding=binding,
        sources=[RegisteredSource(source=source, binding=binding, state=state)],
        active_corpus_version=active_version,
        verified_at=verified_at,
    )

    result = verify_week2_claims([_guideline_candidate(source)], registry)

    assert result.guideline_evidence.rejected[0].code == expected_code
    assert result.guideline_evidence.limitations[0].kind == "guideline_stale"


def test_source_classes_cannot_cross_evidence_lanes() -> None:
    binding = _binding()
    guideline = _guideline_source()
    registry = CurrentTurnSourceRegistry(
        binding=binding,
        sources=[
            RegisteredSource(source=_openemr_source(), binding=binding),
            RegisteredSource(source=guideline, binding=binding),
        ],
        active_corpus_version=guideline.corpus_version,
        verified_at="2026-09-21T12:00:02Z",
    )

    result = verify_week2_claims(
        [
            {
                "id": "c1",
                "claim_class": "patient_record",
                "type": "medication_status",
                "text": "Metformin 500 mg tablet is active.",
                "facts": {"name": "Metformin 500 mg tablet", "status": "active"},
                "source_ids": [guideline.source_id],
                "section": "medications",
            },
            _guideline_candidate(guideline, id="c2", source_ids=["openemr:prescriptions:42"]),
        ],
        registry,
    )

    assert result.patient_record.rejected[0].code == "schema_invalid"
    assert result.guideline_evidence.rejected[0].code == "schema_invalid"
    assert result.patient_record.accepted == result.guideline_evidence.accepted == []


def test_guideline_failure_does_not_erase_independently_verified_patient_lane() -> None:
    binding = _binding()
    guideline = _guideline_source()
    registry = CurrentTurnSourceRegistry(
        binding=binding,
        sources=[
            RegisteredSource(source=_openemr_source(), binding=binding),
            RegisteredSource(source=guideline, binding=binding, state="stale"),
        ],
        active_corpus_version=guideline.corpus_version,
        verified_at="2026-09-21T12:00:02Z",
    )

    result = verify_week2_claims(
        [
            {
                "id": "c1",
                "claim_class": "patient_record",
                "type": "medication_status",
                "text": "Metformin 500 mg tablet is active.",
                "facts": {"name": "Metformin 500 mg tablet", "status": "active"},
                "source_ids": ["openemr:prescriptions:42"],
                "section": "medications",
            },
            _guideline_candidate(guideline, id="c2"),
        ],
        registry,
    )

    assert result.outcome == "partial"
    assert [claim.id for claim in result.patient_record.accepted] == ["c1"]
    assert result.guideline_evidence.rejected[0].code == "stale"
    assert result.guideline_evidence.limitations[0].kind == "guideline_stale"


def test_registry_authored_citation_ids_are_unique_across_independent_claims() -> None:
    binding = _binding()
    registry = CurrentTurnSourceRegistry(
        binding=binding,
        sources=[RegisteredSource(source=_openemr_source(), binding=binding)],
        verified_at="2026-09-21T12:00:02Z",
    )
    base = {
        "claim_class": "patient_record",
        "type": "medication_status",
        "text": "Metformin 500 mg tablet is active.",
        "facts": {"name": "Metformin 500 mg tablet", "status": "active"},
        "source_ids": ["openemr:prescriptions:42"],
        "section": "medications",
    }

    result = verify_week2_claims([{**base, "id": "c1"}, {**base, "id": "c2"}], registry)

    citation_ids = [
        citation.citation_id
        for claim in result.patient_record.accepted
        for citation in claim.citations
    ]
    assert citation_ids == ["ct1", "ct2", "ct3", "ct4"]


@pytest.mark.parametrize(
    ("entry_binding", "state", "expected_code"),
    [
        ("current", "hash_mismatch", "hash_mismatch"),
        ("current", "version_mismatch", "version_mismatch"),
        ("other_patient", "resolved", "unauthorized"),
    ],
)
def test_document_source_requires_current_hash_version_and_patient_binding(
    entry_binding: str,
    state: str,
    expected_code: str,
) -> None:
    binding = _binding()
    source = _document_source()
    registry = CurrentTurnSourceRegistry(
        binding=binding,
        sources=[
            RegisteredSource(
                source=source,
                binding=_binding(patient_id="other-demo-patient") if entry_binding == "other_patient" else binding,
                state=state,
            )
        ],
        verified_at="2026-09-21T12:00:02Z",
    )

    result = verify_week2_claims(
        [
            {
                "id": "c1",
                "claim_class": "patient_record",
                "type": "intake_answer",
                "text": "Chief concern: annual visit.",
                "facts": {
                    "link_id": "chief_concern",
                    "answer": {"kind": "string", "value": "annual visit"},
                },
                "source_ids": [source.source_id],
                "section": "intake",
            }
        ],
        registry,
    )

    assert result.patient_record.rejected[0].code == expected_code
    assert result.patient_record.limitations[0].kind == "withheld"


def test_final_contract_error_fails_closed_without_erasing_the_other_lane() -> None:
    binding = _binding()
    source_payload = _guideline_source().model_dump(mode="json")
    source_payload.update(
        {
            "publisher": "P" * 160,
            "title": "T" * 300,
            "exact_text": "Q" * 500,
            "chunk_sha256": hashlib.sha256(("Q" * 500).encode()).hexdigest(),
        }
    )
    oversized = GuidelineChunkSource.model_validate(source_payload)
    registry = CurrentTurnSourceRegistry(
        binding=binding,
        sources=[
            RegisteredSource(source=_openemr_source(), binding=binding),
            RegisteredSource(source=oversized, binding=binding),
        ],
        active_corpus_version=oversized.corpus_version,
        verified_at="2026-09-21T12:00:02Z",
    )
    guideline_candidate = _guideline_candidate(oversized)
    guideline_candidate["facts"] = {
        "quote": "Q" * 500,
        "publisher": oversized.publisher,
        "title": oversized.title,
        "topic": oversized.topic,
        "section_path": oversized.section_path,
    }

    result = verify_week2_claims(
        [
            guideline_candidate,
            {
                "id": "c2",
                "claim_class": "patient_record",
                "type": "medication_status",
                "text": "Metformin 500 mg tablet is active.",
                "facts": {"name": "Metformin 500 mg tablet", "status": "active"},
                "source_ids": ["openemr:prescriptions:42"],
                "section": "medications",
            },
        ],
        registry,
    )

    assert [claim.id for claim in result.patient_record.accepted] == ["c2"]
    assert result.guideline_evidence.rejected[0].code == "verification_failed_closed"
