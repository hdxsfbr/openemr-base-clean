"""Strict cross-runtime fixtures for the Slice 1 document boundary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.contracts import DocumentType, IntakeExtraction, LabExtraction, UploadResult


FIXTURES = Path(__file__).parent / "fixtures" / "week2"


def test_valid_lab_fixture_is_a_proposal_with_complete_field_evidence() -> None:
    proposal = LabExtraction.model_validate_json((FIXTURES / "valid_lab_extraction.json").read_text())
    assert proposal.analytes[0].test_name.value == "Sample analyte"
    assert proposal.analytes[0].value.evidence.source_citation is not None


def test_valid_upload_fixture_exposes_only_immutable_source_metadata() -> None:
    result = UploadResult.model_validate_json((FIXTURES / "valid_upload_result.json").read_text())
    assert result.source is not None
    assert result.source.document_type == "lab_pdf"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.__setitem__("patient_id", 7),
        lambda payload: payload["analytes"][0].__setitem__("unexpected", True),
        lambda payload: payload["analytes"][0]["value"]["evidence"].__setitem__("source_citation", None),
    ],
)
def test_lab_contract_rejects_unknown_and_uncited_extracted_fields(mutate) -> None:
    payload = json.loads((FIXTURES / "valid_lab_extraction.json").read_text())
    mutate(payload)
    with pytest.raises(ValidationError):
        LabExtraction.model_validate(payload)


def test_lab_contract_supports_a_report_with_multiple_analytes() -> None:
    payload = json.loads((FIXTURES / "valid_lab_extraction.json").read_text())
    second = json.loads(json.dumps(payload["analytes"][0]))
    second["entry_id"] = "1" * 32
    second["test_name"]["value"] = "Second analyte"
    payload["analytes"].append(second)

    proposal = LabExtraction.model_validate(payload)

    assert [analyte.test_name.value for analyte in proposal.analytes] == ["Sample analyte", "Second analyte"]
    assert proposal.analytes[0].entry_id != proposal.analytes[1].entry_id


def test_lab_contract_omits_unit_and_range_when_not_printed_rather_than_inventing_them() -> None:
    payload = json.loads((FIXTURES / "valid_lab_extraction.json").read_text())
    del payload["analytes"][0]["unit"]
    del payload["analytes"][0]["reference_range"]
    del payload["analytes"][0]["abnormal_flag"]

    proposal = LabExtraction.model_validate(payload)

    assert proposal.analytes[0].unit is None
    assert proposal.analytes[0].reference_range is None
    assert proposal.analytes[0].abnormal_flag is None


def test_upload_contract_rejects_unknown_fields() -> None:
    payload = json.loads((FIXTURES / "valid_upload_result.json").read_text())
    payload["source"]["pid"] = 7
    with pytest.raises(ValidationError):
        UploadResult.model_validate(payload)


def test_intake_fixture_preserves_proposal_states_and_per_field_citations() -> None:
    proposal = IntakeExtraction.model_validate_json((FIXTURES / "valid_intake_extraction.json").read_text())

    assert proposal.chief_concern is not None
    assert proposal.chief_concern.evidence.source_citation is not None
    assert proposal.allergies[0].reaction is not None
    assert proposal.allergies[0].reaction.evidence.state.value == "missing"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.__setitem__("unexpected", True),
        lambda payload: payload["chief_concern"]["evidence"].__setitem__("source_citation", None),
        lambda payload: payload["demographics"]["date_of_birth"]["evidence"].__setitem__("source_citation", None),
        lambda payload: payload["demographics"].__setitem__("patient_id", 7),
    ],
)
def test_intake_contract_rejects_unknown_or_uncited_proposals(mutate) -> None:
    payload = json.loads((FIXTURES / "valid_intake_extraction.json").read_text())
    mutate(payload)
    with pytest.raises(ValidationError):
        IntakeExtraction.model_validate(payload)


def test_upload_contract_enforces_intake_specific_limits() -> None:
    payload = json.loads((FIXTURES / "valid_upload_result.json").read_text())
    payload["source"].update({"document_type": DocumentType.intake_form.value, "byte_size": 10 * 1024 * 1024 + 1})
    with pytest.raises(ValidationError):
        UploadResult.model_validate(payload)
