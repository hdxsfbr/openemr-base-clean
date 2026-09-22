"""Public contract tests for the Week 2 document and evidence boundary."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.contracts.export import EXPORTS
from app.contracts.week2 import (
    FieldEvidence,
    GuidelineEvidenceClaim,
    IntakeExtractionEnvelope,
    LabExtractionEnvelope,
    PromoteReviewedDocumentCommand,
    ReviewedLabReport,
    ReviewFactCommand,
    SourceDocumentRef,
    WorkerHandoffRequest,
)


def _source_payload(document_type: str = "lab_report") -> dict[str, object]:
    return {
        "source_document_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "openemr_document_id": "1234",
        "upload_intent_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "document_type": document_type,
        "content_sha256": "c" * 64,
        "byte_count": 4096,
        "mime_type": "application/pdf",
        "page_count": 1,
    }


def test_field_evidence_accepts_a_source_region_and_rejects_out_of_bounds_boxes() -> None:
    payload = {
        "evidence_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "page_number": 1,
        "box": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.1},
        "printed_quote": "Potassium 4.2 mmol/L",
        "ocr_span_start": 10,
        "ocr_span_end": 32,
        "ocr_text_sha256": "a" * 64,
        "rendered_page_sha256": "b" * 64,
        "confidence": 0.94,
        "validation": ["valid"],
    }

    evidence = FieldEvidence.model_validate(payload)
    assert evidence.page_number == 1
    assert evidence.printed_quote == "Potassium 4.2 mmol/L"

    payload["box"] = {"x": 0.8, "y": 0.2, "width": 0.3, "height": 0.1}
    with pytest.raises(ValidationError):
        FieldEvidence.model_validate(payload)


def test_source_document_ref_enforces_type_specific_file_limits() -> None:
    payload = _source_payload()
    source = SourceDocumentRef.model_validate(payload)
    assert source.document_type == "lab_report"

    payload["mime_type"] = "image/png"
    with pytest.raises(ValidationError):
        SourceDocumentRef.model_validate(payload)


def test_lab_extraction_round_trips_strict_proposed_facts() -> None:
    text = "Potassium 4.2 mmol/L"
    text_hash = hashlib.sha256(text.encode()).hexdigest()
    evidence = {
        "evidence_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        "page_number": 1,
        "box": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.1},
        "printed_quote": text,
        "ocr_span_start": 0,
        "ocr_span_end": len(text),
        "ocr_text_sha256": text_hash,
        "rendered_page_sha256": "d" * 64,
        "confidence": 0.94,
        "validation": ["valid"],
    }
    field = {"field_id": "analyte.potassium.value", "state": "schema_valid", "evidence": [evidence]}
    payload = {
        "extraction_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        "extraction_version": 1,
        "schema_name": "lab-report",
        "schema_version": "1.0.0",
        "source": _source_payload(),
        "state": "schema_valid",
        "created_at": "2026-09-21T12:00:00Z",
        "ocr_pages": [{
            "page_number": 1,
            "text": text,
            "text_sha256": text_hash,
            "rendered_page_sha256": "d" * 64,
            "renderer_version": "poppler-25.1",
            "preprocessing_version": "agentforge-1",
            "tokens": [],
        }],
        "payload": {
            "collection_date": {
                "field_id": "collection_date",
                "value": "2026-09-20",
                "state": "schema_valid",
                "evidence": [evidence],
            },
            "analytes": [{
                "analyte_id": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
                "test_name": {**field, "field_id": "analyte.potassium.test_name", "value": "Potassium"},
                "value": {**field, "value": {"kind": "quantity", "value": 4.2}},
                "unit": {**field, "field_id": "analyte.potassium.unit", "value": "mmol/L"},
            }],
        },
    }

    extraction = LabExtractionEnvelope.model_validate(payload)
    assert extraction.payload.analytes[0].value.value.value == Decimal("4.2")

    payload["unexpected"] = True
    with pytest.raises(ValidationError):
        LabExtractionEnvelope.model_validate(payload)


def test_intake_extraction_keeps_answers_as_proposals_not_chart_facts() -> None:
    text = "Chief concern: annual visit"
    text_hash = hashlib.sha256(text.encode()).hexdigest()
    evidence = {
        "evidence_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        "page_number": 1,
        "box": {"x": 0.1, "y": 0.2, "width": 0.5, "height": 0.1},
        "printed_quote": text,
        "ocr_span_start": 0,
        "ocr_span_end": len(text),
        "ocr_text_sha256": text_hash,
        "rendered_page_sha256": "d" * 64,
        "confidence": 0.9,
        "validation": ["valid"],
    }
    payload = {
        "extraction_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        "extraction_version": 1,
        "schema_name": "intake-form",
        "schema_version": "1.0.0",
        "source": _source_payload("intake_form"),
        "state": "schema_valid",
        "created_at": "2026-09-21T12:00:00Z",
        "ocr_pages": [{
            "page_number": 1,
            "text": text,
            "text_sha256": text_hash,
            "rendered_page_sha256": "d" * 64,
            "renderer_version": "poppler-25.1",
            "preprocessing_version": "agentforge-1",
            "tokens": [],
        }],
        "payload": {
            "demographics": {},
            "chief_concern": {
                "field_id": "chief_concern",
                "value": "annual visit",
                "state": "schema_valid",
                "evidence": [evidence],
            },
            "medications": [],
            "allergies": [],
            "family_history": [],
        },
    }

    extraction = IntakeExtractionEnvelope.model_validate(payload)
    assert extraction.payload.chief_concern.value == "annual visit"
    assert not hasattr(extraction.payload.chief_concern, "review_decision")


def test_review_and_promotion_commands_require_explicit_complete_human_input() -> None:
    correction = ReviewFactCommand.model_validate({
        "idempotency_key": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "extraction_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        "expected_extraction_version": 1,
        "field_id": "analyte.potassium.value",
        "action": "correct",
        "corrected_value": {"kind": "measurement", "value": {"kind": "quantity", "value": 4.2}},
        "reason": "Verified against the printed source",
    })
    assert correction.action == "correct"

    with pytest.raises(ValidationError):
        ReviewFactCommand.model_validate({
            "idempotency_key": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "extraction_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
            "expected_extraction_version": 1,
            "field_id": "analyte.potassium.value",
            "action": "approve",
            "corrected_value": {"kind": "measurement", "value": {"kind": "quantity", "value": 4.2}},
        })

    with pytest.raises(ValidationError):
        PromoteReviewedDocumentCommand.model_validate({
            "idempotency_key": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "extraction_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
            "expected_extraction_version": 1,
            "source_content_sha256": "c" * 64,
            "target_type": "lab_report",
            "review_ids": [
                "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
                "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
            ],
        })


def test_worker_handoff_is_reference_only_and_rejects_raw_content() -> None:
    payload = {
        "handoff_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "correlation_id": "conversation.turn-01",
        "event_kind": "document_uploaded",
        "worker": "intake_extractor",
        "reason_code": "authorized_document_uploaded",
        "attempt": 1,
        "deadline_at": "2026-09-21T12:01:35Z",
        "input_refs": [{
            "kind": "source_document",
            "id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "version": "1",
        }],
        "contract_versions": {"document": "1.0.0", "handoff": "1.0.0"},
    }
    request = WorkerHandoffRequest.model_validate(payload)
    assert request.worker == "intake_extractor"

    payload["raw_document"] = "synthetic patient content"
    with pytest.raises(ValidationError):
        WorkerHandoffRequest.model_validate(payload)


def test_guideline_claim_requires_one_matching_guideline_citation() -> None:
    payload = {
        "id": "c1",
        "claim_class": "guideline_evidence",
        "type": "guideline_excerpt",
        "text": "USPSTF — Hypertension Screening: Screen adults 18 years or older.",
        "facts": {
            "quote": "Screen adults 18 years or older.",
            "publisher": "USPSTF",
            "title": "Hypertension Screening",
            "topic": "adult-hypertension",
            "section_path": ["Recommendation"],
        },
        "source_ids": ["guideline:uspstf-2026q3:hypertension:recommendation-1"],
        "section": "guideline_evidence",
        "citations": [{
            "citation_id": "ct1",
            "claim_id": "c1",
            "source_id": "guideline:uspstf-2026q3:hypertension:recommendation-1",
            "source_type": "guideline",
            "title": "USPSTF — Hypertension Screening",
            "page_or_section": {
                "kind": "guideline_section",
                "section_path": ["Recommendation"],
                "chunk_ordinal": 1,
            },
            "field_or_chunk_id": "recommendation-1",
            "quote_or_value": {"kind": "exact_quote", "quote": "Screen adults 18 years or older."},
            "publisher": "USPSTF",
            "jurisdiction": "US",
            "canonical_url": "https://www.uspreventiveservicestaskforce.org/example",
            "publication_date": "2024-06-01",
            "topic": "adult-hypertension",
            "corpus_version": "uspstf-2026q3",
            "source_sha256": "a" * 64,
            "chunk_sha256": "b" * 64,
            "href": "https://www.uspreventiveservicestaskforce.org/example#recommendation",
            "retrieved_at": "2026-09-21T12:00:00Z",
        }],
    }
    claim = GuidelineEvidenceClaim.model_validate(payload)
    assert claim.citations[0].quote_or_value.quote == claim.facts.quote

    payload["source_ids"] = ["document:aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa:record:bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb:v:1:field:value"]
    with pytest.raises(ValidationError):
        GuidelineEvidenceClaim.model_validate(payload)


def test_reviewed_lab_record_contains_only_human_reviewed_values_and_exact_provenance() -> None:
    collection_review = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
    value_review = "ffffffff-ffff-4fff-8fff-ffffffffffff"
    reviewed = ReviewedLabReport.model_validate({
        "record_id": "11111111-1111-4111-8111-111111111111",
        "record_version": 1,
        "status": "active",
        "source": _source_payload(),
        "extraction_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        "extraction_version": 1,
        "schema_version": "1.0.0",
        "collection_date": {
            "value": "2026-09-20",
            "source_field_id": "collection_date",
            "review_id": collection_review,
            "evidence_ids": ["cccccccc-cccc-4ccc-8ccc-cccccccccccc"],
        },
        "analytes": [{
            "analyte_id": "22222222-2222-4222-8222-222222222222",
            "test_name": {
                "value": "Potassium",
                "source_field_id": "analyte.potassium.test_name",
                "review_id": collection_review,
                "evidence_ids": ["cccccccc-cccc-4ccc-8ccc-cccccccccccc"],
            },
            "value": {
                "value": {"kind": "quantity", "value": 4.2},
                "source_field_id": "analyte.potassium.value",
                "review_id": value_review,
                "evidence_ids": ["cccccccc-cccc-4ccc-8ccc-cccccccccccc"],
            },
        }],
        "review_ids": [collection_review, value_review],
        "reviewed_by": "physician-1",
        "reviewed_at": "2026-09-21T12:00:00Z",
        "provenance": {
            "action_id": "33333333-3333-4333-8333-333333333333",
            "action": "promote",
            "action_idempotency_key": "44444444-4444-4444-8444-444444444444",
            "review_set_sha256": "a" * 64,
            "source_content_sha256": "c" * 64,
            "extraction_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
            "extraction_version": 1,
            "acted_by": "physician-1",
            "acted_at": "2026-09-21T12:00:00Z",
            "correlation_id": "conversation.turn-01",
        },
    })
    assert reviewed.analytes[0].value.value.value == Decimal("4.2")

    invalid = reviewed.model_dump(mode="json")
    invalid["review_ids"] = [collection_review]
    with pytest.raises(ValidationError):
        ReviewedLabReport.model_validate(invalid)


def test_every_week2_boundary_has_an_exported_schema() -> None:
    expected = {
        "lab_extraction.schema.json",
        "intake_extraction.schema.json",
        "review_fact_command.schema.json",
        "fact_review.schema.json",
        "promote_reviewed_document_command.schema.json",
        "promote_reviewed_document_response.schema.json",
        "revise_reviewed_record_command.schema.json",
        "revise_reviewed_record_response.schema.json",
        "reviewed_lab_report.schema.json",
        "reviewed_intake_response.schema.json",
        "worker_handoff_request.schema.json",
        "worker_handoff_result.schema.json",
        "resolved_source.schema.json",
        "citation.schema.json",
        "final_claim.schema.json",
        "week2_limitation.schema.json",
        "release_report.schema.json",
    }
    assert expected <= EXPORTS.keys()


def test_shared_review_fixture_validates_and_unknown_fields_fail_closed() -> None:
    fixture_dir = Path(__file__).parents[2] / "contracts" / "fixtures" / "week2"
    valid = json.loads((fixture_dir / "review_fact_command.valid.json").read_text())
    invalid = json.loads((fixture_dir / "review_fact_command.invalid-extra.json").read_text())

    assert ReviewFactCommand.model_validate(valid).action == "correct"
    with pytest.raises(ValidationError):
        ReviewFactCommand.model_validate(invalid)
