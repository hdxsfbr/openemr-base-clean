"""Strict cross-runtime fixtures for the Slice 1 document boundary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.contracts import LabExtraction, UploadResult


FIXTURES = Path(__file__).parent / "fixtures" / "week2"


def test_valid_lab_fixture_is_a_proposal_with_complete_field_evidence() -> None:
    proposal = LabExtraction.model_validate_json((FIXTURES / "valid_lab_extraction.json").read_text())
    assert proposal.test_name == "Sample analyte"
    assert proposal.fields["value"].source_citation is not None


def test_valid_upload_fixture_exposes_only_immutable_source_metadata() -> None:
    result = UploadResult.model_validate_json((FIXTURES / "valid_upload_result.json").read_text())
    assert result.source is not None
    assert result.source.document_type == "lab_pdf"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["fields"].__setitem__("patient_id", payload["fields"]["value"]),
        lambda payload: payload["fields"]["value"].__setitem__("unexpected", True),
        lambda payload: payload["fields"]["value"].__setitem__("source_citation", None),
    ],
)
def test_lab_contract_rejects_unknown_and_uncited_extracted_fields(mutate) -> None:
    payload = json.loads((FIXTURES / "valid_lab_extraction.json").read_text())
    mutate(payload)
    with pytest.raises(ValidationError):
        LabExtraction.model_validate(payload)


def test_upload_contract_rejects_unknown_fields() -> None:
    payload = json.loads((FIXTURES / "valid_upload_result.json").read_text())
    payload["source"]["pid"] = 7
    with pytest.raises(ValidationError):
        UploadResult.model_validate(payload)
