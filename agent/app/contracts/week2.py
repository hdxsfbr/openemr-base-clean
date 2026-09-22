"""Strict Week 2 contracts shared by extraction, review, and evidence flows.

The models in this module are the source for exported JSON Schema.  They carry
no persistence or workflow behavior; those boundaries consume these types.
"""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import Field, RootModel, StringConstraints, model_validator

from .common import CorrelationId, SourceRef, StrictModel
from .turns import ClaimFacts

Uuid = Annotated[
    str,
    StringConstraints(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    ),
]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
DateTime = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")]
FieldId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")]
T = TypeVar("T")


class ExtractionState(StrEnum):
    schema_valid = "schema_valid"
    review_required = "review_required"
    rejected = "rejected"
    unavailable = "unavailable"


class ValidationCode(StrEnum):
    valid = "valid"
    low_confidence = "low_confidence"
    missing = "missing"
    ambiguous = "ambiguous"
    conflicting = "conflicting"
    invalid_type = "invalid_type"
    invalid_format = "invalid_format"
    quote_mismatch = "quote_mismatch"
    out_of_bounds = "out_of_bounds"


class SourceDocumentRef(StrictModel):
    source_document_id: Uuid
    openemr_document_id: str = Field(min_length=1, max_length=128)
    upload_intent_id: Uuid
    document_type: Literal["lab_report", "intake_form"]
    content_sha256: Sha256
    byte_count: int = Field(gt=0)
    mime_type: Literal["application/pdf", "image/png", "image/jpeg"]
    page_count: int = Field(gt=0)

    @model_validator(mode="after")
    def enforce_document_limits(self) -> "SourceDocumentRef":
        if self.document_type == "lab_report":
            if self.mime_type != "application/pdf" or self.byte_count > 20_971_520 or self.page_count > 20:
                raise ValueError("lab reports require a PDF within the 20 MiB and 20-page limits")
        else:
            if self.byte_count > 10_485_760 or self.page_count > 10:
                raise ValueError("intake forms exceed their size or page limit")
            if self.mime_type != "application/pdf" and self.page_count != 1:
                raise ValueError("intake images must contain exactly one page")
        return self


class NormalizedBox(StrictModel):
    x: Decimal = Field(ge=0, le=1)
    y: Decimal = Field(ge=0, le=1)
    width: Decimal = Field(ge=0, le=1)
    height: Decimal = Field(ge=0, le=1)

    @model_validator(mode="after")
    def fits_page(self) -> "NormalizedBox":
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("normalized box must fit within the page")
        return self


class FieldEvidence(StrictModel):
    evidence_id: Uuid
    page_number: int = Field(ge=1)
    box: NormalizedBox
    printed_quote: str = Field(min_length=1, max_length=500)
    ocr_span_start: int = Field(ge=0)
    ocr_span_end: int = Field(ge=1)
    ocr_text_sha256: Sha256
    rendered_page_sha256: Sha256
    confidence: Decimal = Field(ge=0, le=1)
    validation: list[ValidationCode] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_span_and_codes(self) -> "FieldEvidence":
        if self.ocr_span_end <= self.ocr_span_start:
            raise ValueError("OCR span end must be greater than its start")
        if len(set(self.validation)) != len(self.validation):
            raise ValueError("validation codes must be distinct")
        return self


class ProposedField(StrictModel, Generic[T]):
    field_id: FieldId
    value: T | None
    state: ExtractionState
    evidence: list[FieldEvidence] = Field(max_length=3)

    @model_validator(mode="after")
    def enforce_value_and_evidence(self) -> "ProposedField[T]":
        if self.value is None:
            if self.state not in (ExtractionState.review_required, ExtractionState.unavailable):
                raise ValueError("only review-required or unavailable fields may have a null value")
            if self.evidence:
                raise ValueError("a null field cannot carry evidence")
        elif not self.evidence:
            raise ValueError("a proposed value requires field evidence")
        return self


class OcrToken(StrictModel):
    token_index: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=500)
    span_start: int = Field(ge=0)
    span_end: int = Field(ge=1)
    box: NormalizedBox
    confidence: Decimal = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_span(self) -> "OcrToken":
        if self.span_end <= self.span_start:
            raise ValueError("OCR token span end must be greater than its start")
        return self


class OcrPage(StrictModel):
    page_number: int = Field(ge=1)
    text: str = Field(max_length=100_000)
    text_sha256: Sha256
    rendered_page_sha256: Sha256
    renderer_version: str = Field(min_length=1, max_length=64)
    preprocessing_version: str = Field(min_length=1, max_length=64)
    tokens: list[OcrToken] = Field(default_factory=list, max_length=50_000)

    @model_validator(mode="after")
    def validate_text_and_tokens(self) -> "OcrPage":
        if hashlib.sha256(self.text.encode()).hexdigest() != self.text_sha256:
            raise ValueError("OCR text hash does not match")
        for index, token in enumerate(self.tokens):
            if token.token_index != index:
                raise ValueError("OCR token indexes must be contiguous from zero")
            if token.span_end > len(self.text) or self.text[token.span_start : token.span_end] != token.text:
                raise ValueError("OCR token must match its page text span")
            if index and self.tokens[index - 1].span_end > token.span_start:
                raise ValueError("OCR token spans must not overlap")
        return self


class CodedValue(StrictModel):
    system: str = Field(min_length=1, max_length=500)
    code: str = Field(min_length=1, max_length=100)
    display: str | None = Field(default=None, min_length=1, max_length=200)


class QuantityValue(StrictModel):
    kind: Literal["quantity"]
    value: Decimal


class TextValue(StrictModel):
    kind: Literal["text"]
    value: str = Field(min_length=1, max_length=500)


MeasurementValue = Annotated[QuantityValue | TextValue, Field(discriminator="kind")]


class ReferenceRange(StrictModel):
    low: Decimal | None = None
    high: Decimal | None = None
    text: str | None = Field(default=None, min_length=1, max_length=200)
    unit: str | None = Field(default=None, min_length=1, max_length=80)

    @model_validator(mode="after")
    def has_a_bound_or_text(self) -> "ReferenceRange":
        if self.low is None and self.high is None and self.text is None:
            raise ValueError("reference range requires a low, high, or text value")
        return self


AbnormalFlag = Literal["low", "high", "abnormal", "normal", "unknown"]


class ProposedAnalyte(StrictModel):
    analyte_id: Uuid
    test_name: ProposedField[Annotated[str, Field(min_length=1, max_length=200)]]
    code: ProposedField[CodedValue] | None = None
    value: ProposedField[MeasurementValue]
    unit: ProposedField[Annotated[str, Field(min_length=1, max_length=80)]] | None = None
    reference_range: ProposedField[ReferenceRange] | None = None
    abnormal_flag: ProposedField[AbnormalFlag] | None = None


class LabExtractionPayload(StrictModel):
    collection_date: ProposedField[date]
    analytes: list[ProposedAnalyte] = Field(min_length=1, max_length=200)


class LabExtractionEnvelope(StrictModel):
    extraction_id: Uuid
    extraction_version: int = Field(ge=1)
    schema_name: Literal["lab-report"]
    schema_version: Literal["1.0.0"]
    source: SourceDocumentRef
    state: ExtractionState
    created_at: DateTime
    ocr_pages: list[OcrPage] = Field(min_length=1, max_length=20)
    payload: LabExtractionPayload

    @model_validator(mode="after")
    def validate_source_and_pages(self) -> "LabExtractionEnvelope":
        if self.source.document_type != "lab_report":
            raise ValueError("lab extraction requires a lab-report source")
        if len(self.ocr_pages) != self.source.page_count:
            raise ValueError("OCR page count must match the source")
        if [page.page_number for page in self.ocr_pages] != list(range(1, self.source.page_count + 1)):
            raise ValueError("OCR pages must be contiguous from one")
        pages = {page.page_number: page for page in self.ocr_pages}
        fields = [self.payload.collection_date]
        for analyte in self.payload.analytes:
            fields.extend(
                field
                for field in (
                    analyte.test_name,
                    analyte.code,
                    analyte.value,
                    analyte.unit,
                    analyte.reference_range,
                    analyte.abnormal_flag,
                )
                if field is not None
            )
        for proposed in fields:
            for evidence in proposed.evidence:
                page = pages.get(evidence.page_number)
                if page is None or evidence.ocr_span_end > len(page.text):
                    raise ValueError("field evidence points outside retained OCR")
                if evidence.ocr_text_sha256 != page.text_sha256 or evidence.rendered_page_sha256 != page.rendered_page_sha256:
                    raise ValueError("field evidence hashes do not match the retained page")
        return self


ShortAnswer = Annotated[str, Field(min_length=1, max_length=100)]


class ProposedDemographics(StrictModel):
    given_name: ProposedField[ShortAnswer] | None = None
    family_name: ProposedField[ShortAnswer] | None = None
    date_of_birth: ProposedField[date] | None = None
    administrative_sex: ProposedField[Literal["female", "male", "other", "unknown"]] | None = None
    gender_identity: ProposedField[ShortAnswer] | None = None
    pronouns: ProposedField[ShortAnswer] | None = None
    address: ProposedField[Annotated[str, Field(min_length=1, max_length=500)]] | None = None
    phone: ProposedField[Annotated[str, Field(min_length=1, max_length=50)]] | None = None


class ProposedMedication(StrictModel):
    entry_id: Uuid
    name: ProposedField[Annotated[str, Field(min_length=1, max_length=200)]]
    strength: ProposedField[ShortAnswer] | None = None
    dose: ProposedField[ShortAnswer] | None = None
    route: ProposedField[ShortAnswer] | None = None
    frequency: ProposedField[ShortAnswer] | None = None
    status: ProposedField[Literal["active", "inactive", "stopped", "unknown"]] | None = None


class ProposedAllergy(StrictModel):
    entry_id: Uuid
    substance: ProposedField[Annotated[str, Field(min_length=1, max_length=200)]]
    reaction: ProposedField[Annotated[str, Field(min_length=1, max_length=500)]] | None = None
    severity: ProposedField[Literal["mild", "moderate", "severe", "unknown"]] | None = None
    status: ProposedField[Literal["active", "inactive", "resolved", "unknown"]] | None = None


class ProposedFamilyHistory(StrictModel):
    entry_id: Uuid
    relationship: ProposedField[Annotated[str, Field(min_length=1, max_length=200)]]
    condition: ProposedField[Annotated[str, Field(min_length=1, max_length=200)]]
    onset_age_years: ProposedField[Annotated[int, Field(ge=0, le=130)]] | None = None


class IntakeExtractionPayload(StrictModel):
    demographics: ProposedDemographics
    chief_concern: ProposedField[Annotated[str, Field(min_length=1, max_length=2_000)]] | None = None
    medications: list[ProposedMedication] = Field(max_length=50)
    allergies: list[ProposedAllergy] = Field(max_length=50)
    family_history: list[ProposedFamilyHistory] = Field(max_length=50)


def _proposed_fields(value: object) -> list[ProposedField[object]]:
    found: list[ProposedField[object]] = []
    if isinstance(value, ProposedField):
        found.append(value)
    elif isinstance(value, StrictModel):
        for field_name in type(value).model_fields:
            found.extend(_proposed_fields(getattr(value, field_name)))
    elif isinstance(value, list):
        for item in value:
            found.extend(_proposed_fields(item))
    return found


class IntakeExtractionEnvelope(StrictModel):
    extraction_id: Uuid
    extraction_version: int = Field(ge=1)
    schema_name: Literal["intake-form"]
    schema_version: Literal["1.0.0"]
    source: SourceDocumentRef
    state: ExtractionState
    created_at: DateTime
    ocr_pages: list[OcrPage] = Field(min_length=1, max_length=10)
    payload: IntakeExtractionPayload

    @model_validator(mode="after")
    def validate_source_and_pages(self) -> "IntakeExtractionEnvelope":
        if self.source.document_type != "intake_form":
            raise ValueError("intake extraction requires an intake-form source")
        if len(self.ocr_pages) != self.source.page_count:
            raise ValueError("OCR page count must match the source")
        if [page.page_number for page in self.ocr_pages] != list(range(1, self.source.page_count + 1)):
            raise ValueError("OCR pages must be contiguous from one")
        pages = {page.page_number: page for page in self.ocr_pages}
        for proposed in _proposed_fields(self.payload):
            for evidence in proposed.evidence:
                page = pages.get(evidence.page_number)
                if page is None or evidence.ocr_span_end > len(page.text):
                    raise ValueError("field evidence points outside retained OCR")
                if evidence.ocr_text_sha256 != page.text_sha256 or evidence.rendered_page_sha256 != page.rendered_page_sha256:
                    raise ValueError("field evidence hashes do not match the retained page")
        return self


class StringCorrectedValue(StrictModel):
    kind: Literal["string"]
    value: str = Field(min_length=1, max_length=2_000)


class DateCorrectedValue(StrictModel):
    kind: Literal["date"]
    value: date


class IntegerCorrectedValue(StrictModel):
    kind: Literal["integer"]
    value: int = Field(ge=0, le=130)


ChoiceValue = Literal[
    "female", "male", "other", "unknown", "active", "inactive", "stopped", "resolved",
    "mild", "moderate", "severe", "low", "high", "abnormal", "normal",
]


class ChoiceCorrectedValue(StrictModel):
    kind: Literal["choice"]
    value: ChoiceValue


class CodedCorrectedValue(StrictModel):
    kind: Literal["coded"]
    value: CodedValue


class MeasurementCorrectedValue(StrictModel):
    kind: Literal["measurement"]
    value: MeasurementValue


class RangeCorrectedValue(StrictModel):
    kind: Literal["reference_range"]
    value: ReferenceRange


CorrectedValue = Annotated[
    StringCorrectedValue
    | DateCorrectedValue
    | IntegerCorrectedValue
    | ChoiceCorrectedValue
    | CodedCorrectedValue
    | MeasurementCorrectedValue
    | RangeCorrectedValue,
    Field(discriminator="kind"),
]


class ReviewFactCommand(StrictModel):
    idempotency_key: Uuid
    extraction_id: Uuid
    expected_extraction_version: int = Field(ge=1)
    field_id: FieldId
    action: Literal["approve", "correct", "reject"]
    corrected_value: CorrectedValue | None = None
    reason: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def match_action_fields(self) -> "ReviewFactCommand":
        if self.action == "approve":
            if self.corrected_value is not None or self.reason is not None:
                raise ValueError("approval accepts neither a correction nor a reason")
        elif self.action == "correct":
            if self.corrected_value is None or self.reason is None:
                raise ValueError("correction requires a typed value and reason")
        elif self.corrected_value is not None or self.reason is None:
            raise ValueError("rejection requires a reason and no corrected value")
        return self


class PromoteReviewedDocumentCommand(StrictModel):
    idempotency_key: Uuid
    extraction_id: Uuid
    expected_extraction_version: int = Field(ge=1)
    source_content_sha256: Sha256
    target_type: Literal["lab_report", "intake_response"]
    review_ids: list[Uuid] = Field(min_length=1, max_length=1_201)

    @model_validator(mode="after")
    def unique_review_ids(self) -> "PromoteReviewedDocumentCommand":
        if len(set(self.review_ids)) != len(self.review_ids):
            raise ValueError("review IDs must be unique")
        return self


class ReviewedField(StrictModel, Generic[T]):
    value: T
    source_field_id: FieldId
    review_id: Uuid
    evidence_ids: list[Uuid] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def unique_evidence_ids(self) -> "ReviewedField[T]":
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("evidence IDs must be unique")
        return self


class ReviewedAnalyte(StrictModel):
    analyte_id: Uuid
    test_name: ReviewedField[Annotated[str, Field(min_length=1, max_length=200)]]
    value: ReviewedField[MeasurementValue]
    code: ReviewedField[CodedValue] | None = None
    unit: ReviewedField[Annotated[str, Field(min_length=1, max_length=80)]] | None = None
    reference_range: ReviewedField[ReferenceRange] | None = None
    abnormal_flag: ReviewedField[AbnormalFlag] | None = None


class RecordProvenance(StrictModel):
    action_id: Uuid
    action: Literal["promote", "amend", "withdraw"]
    action_idempotency_key: Uuid
    review_set_sha256: Sha256
    source_content_sha256: Sha256
    extraction_id: Uuid
    extraction_version: int = Field(ge=1)
    acted_by: str = Field(min_length=1, max_length=128)
    acted_at: DateTime
    correlation_id: CorrelationId


class ReviewedLabReport(StrictModel):
    record_id: Uuid
    record_version: int = Field(ge=1)
    status: Literal["active", "amended", "withdrawn"]
    supersedes_record_id: Uuid | None = None
    source: SourceDocumentRef
    extraction_id: Uuid
    extraction_version: int = Field(ge=1)
    schema_version: Literal["1.0.0"]
    collection_date: ReviewedField[date]
    analytes: list[ReviewedAnalyte] = Field(min_length=1, max_length=200)
    review_ids: list[Uuid] = Field(min_length=1, max_length=1_201)
    reviewed_by: str = Field(min_length=1, max_length=128)
    reviewed_at: DateTime
    lifecycle_reason: str | None = Field(default=None, min_length=1, max_length=500)
    provenance: RecordProvenance

    @model_validator(mode="after")
    def validate_lifecycle_and_reviews(self) -> "ReviewedLabReport":
        if self.source.document_type != "lab_report":
            raise ValueError("reviewed lab record requires a lab-report source")
        if self.record_version == 1:
            if self.status != "active" or self.supersedes_record_id is not None or self.lifecycle_reason is not None:
                raise ValueError("version one must be active and cannot supersede another record")
        elif self.supersedes_record_id is None or self.lifecycle_reason is None or self.status == "active":
            raise ValueError("later record versions require supersession, lifecycle reason, and a terminal status")
        if self.extraction_id != self.provenance.extraction_id or self.extraction_version != self.provenance.extraction_version:
            raise ValueError("record extraction identity must match provenance")
        if self.source.content_sha256 != self.provenance.source_content_sha256:
            raise ValueError("record source hash must match provenance")
        nested = {self.collection_date.review_id}
        for analyte in self.analytes:
            for field_value in (
                analyte.test_name,
                analyte.value,
                analyte.code,
                analyte.unit,
                analyte.reference_range,
                analyte.abnormal_flag,
            ):
                if field_value is not None:
                    nested.add(field_value.review_id)
        if len(set(self.review_ids)) != len(self.review_ids) or set(self.review_ids) != nested:
            raise ValueError("review IDs must exactly equal the nested reviewed-field review IDs")
        return self


DocumentFieldValue = str | date | int | CodedValue | QuantityValue | TextValue | ReferenceRange


class FactReview(StrictModel):
    review_id: Uuid
    idempotency_key: Uuid
    extraction_id: Uuid
    extraction_version: int = Field(ge=1)
    field_id: FieldId
    proposed_value: DocumentFieldValue | None
    final_value: DocumentFieldValue | None = None
    evidence_ids: list[Uuid] = Field(max_length=3)
    decision: Literal["approved", "corrected", "rejected"]
    reason: str | None = Field(default=None, min_length=1, max_length=500)
    reviewed_by: str = Field(min_length=1, max_length=128)
    reviewed_at: DateTime
    supersedes_review_id: Uuid | None = None
    idempotency_outcome: Literal["created", "replayed"]

    @model_validator(mode="after")
    def validate_decision(self) -> "FactReview":
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("evidence IDs must be unique")
        if self.decision == "approved":
            if self.proposed_value is None or self.final_value is None or self.reason is not None:
                raise ValueError("approval requires proposed and final values and no reason")
        elif self.decision == "corrected":
            if self.final_value is None or self.reason is None:
                raise ValueError("correction requires a final value and reason")
        elif self.final_value is not None or self.reason is None:
            raise ValueError("rejection requires a reason and no final value")
        if not self.evidence_ids and not (self.decision == "rejected" and self.proposed_value is None):
            raise ValueError("only rejection of a missing proposal may omit evidence")
        return self


class PromoteReviewedDocumentResponse(StrictModel):
    promotion_id: Uuid
    target_type: Literal["lab_report", "intake_response"]
    target_record_id: Uuid
    record_version: int = Field(ge=1)
    review_set_sha256: Sha256
    outcome: Literal["created", "replayed"]


class ReviseReviewedRecordCommand(StrictModel):
    idempotency_key: Uuid
    record_id: Uuid
    expected_record_version: int = Field(ge=1)
    action: Literal["amend", "withdraw"]
    review_ids: list[Uuid] | None = Field(default=None, min_length=1, max_length=1_201)
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_revision(self) -> "ReviseReviewedRecordCommand":
        if self.action == "amend":
            if not self.review_ids or len(set(self.review_ids)) != len(self.review_ids):
                raise ValueError("amendment requires a unique complete review set")
        elif self.review_ids is not None:
            raise ValueError("withdrawal must not provide review IDs")
        return self


class ReviseReviewedRecordResponse(StrictModel):
    action_id: Uuid
    record_id: Uuid
    record_version: int = Field(ge=2)
    status: Literal["amended", "withdrawn", "stopped"]
    review_set_sha256: Sha256
    outcome: Literal["created", "replayed"]


class StringAnswer(StrictModel):
    kind: Literal["string"]
    value: str = Field(min_length=1, max_length=2_000)


class DateAnswer(StrictModel):
    kind: Literal["date"]
    value: date


class IntegerAnswer(StrictModel):
    kind: Literal["integer"]
    value: int = Field(ge=0, le=130)


class ChoiceAnswer(StrictModel):
    kind: Literal["choice"]
    value: ChoiceValue


ReviewedAnswer = Annotated[StringAnswer | DateAnswer | IntegerAnswer | ChoiceAnswer, Field(discriminator="kind")]


class ReviewedQuestionnaireItem(StrictModel):
    item_id: Uuid
    link_id: FieldId
    repeat_key: Uuid | None = None
    source_field_id: FieldId
    review_id: Uuid
    evidence_ids: list[Uuid] = Field(min_length=1, max_length=3)
    answer: ReviewedAnswer

    @model_validator(mode="after")
    def validate_repeat_and_evidence(self) -> "ReviewedQuestionnaireItem":
        repeated = self.link_id.startswith(("medication-", "allergy-", "family-history-"))
        if repeated != (self.repeat_key is not None):
            raise ValueError("repeat key presence must match the repeated questionnaire section")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("evidence IDs must be unique")
        return self


class ReviewedIntakeResponse(StrictModel):
    record_id: Uuid
    record_version: int = Field(ge=1)
    resource_type: Literal["QuestionnaireResponse"]
    questionnaire: Literal["urn:agentforge:questionnaire:intake:v1"]
    status: Literal["completed", "amended", "stopped"]
    supersedes_record_id: Uuid | None = None
    source: SourceDocumentRef
    extraction_id: Uuid
    extraction_version: int = Field(ge=1)
    schema_version: Literal["1.0.0"]
    subject: Annotated[str, StringConstraints(pattern=r"^Patient/[A-Za-z0-9.-]{1,64}$")]
    authored: DateTime
    reviewed_by: str = Field(min_length=1, max_length=128)
    review_ids: list[Uuid] = Field(min_length=1, max_length=659)
    items: list[ReviewedQuestionnaireItem] = Field(min_length=1, max_length=659)
    lifecycle_reason: str | None = Field(default=None, min_length=1, max_length=500)
    provenance: RecordProvenance

    @model_validator(mode="after")
    def validate_lifecycle_and_reviews(self) -> "ReviewedIntakeResponse":
        if self.source.document_type != "intake_form":
            raise ValueError("reviewed intake record requires an intake-form source")
        if self.record_version == 1:
            if self.status != "completed" or self.supersedes_record_id is not None or self.lifecycle_reason is not None:
                raise ValueError("version one must be completed and cannot supersede another record")
        elif self.supersedes_record_id is None or self.lifecycle_reason is None or self.status == "completed":
            raise ValueError("later intake versions require supersession, lifecycle reason, and terminal status")
        nested = {item.review_id for item in self.items}
        if len(set(self.review_ids)) != len(self.review_ids) or set(self.review_ids) != nested:
            raise ValueError("review IDs must exactly equal questionnaire item review IDs")
        if self.extraction_id != self.provenance.extraction_id or self.extraction_version != self.provenance.extraction_version:
            raise ValueError("record extraction identity must match provenance")
        if self.source.content_sha256 != self.provenance.source_content_sha256:
            raise ValueError("record source hash must match provenance")
        return self


class VersionedReference(StrictModel):
    kind: Literal["source_document", "extraction", "evidence_query", "corpus", "reviewed_record"]
    id: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    integrity_sha256: Sha256 | None = None


class WorkerHandoffRequest(StrictModel):
    handoff_id: Uuid
    correlation_id: CorrelationId
    conversation_id: str | None = Field(default=None, min_length=1, max_length=128)
    turn_id: str | None = Field(default=None, min_length=1, max_length=128)
    event_kind: Literal["document_uploaded", "reprocess_requested", "chat_turn"]
    worker: Literal["intake_extractor", "evidence_retriever"]
    reason_code: Literal[
        "authorized_document_uploaded",
        "authorized_reprocess_requested",
        "explicit_guideline_request",
    ]
    attempt: int = Field(ge=1, le=2)
    deadline_at: DateTime
    input_refs: list[VersionedReference] = Field(min_length=1, max_length=8)
    contract_versions: dict[str, str] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def route_matches_worker(self) -> "WorkerHandoffRequest":
        if self.event_kind in ("document_uploaded", "reprocess_requested"):
            if self.worker != "intake_extractor":
                raise ValueError("document events may dispatch only the intake extractor")
        elif self.worker != "evidence_retriever":
            raise ValueError("chat worker handoffs may dispatch only evidence retrieval")
        return self


class StageTiming(StrictModel):
    stage: str = Field(min_length=1, max_length=64)
    duration_ms: int = Field(ge=0)
    outcome: Literal["completed", "limited", "failed", "canceled"]


class WorkerHandoffResult(StrictModel):
    handoff_id: Uuid
    correlation_id: CorrelationId
    conversation_id: str | None = Field(default=None, min_length=1, max_length=128)
    turn_id: str | None = Field(default=None, min_length=1, max_length=128)
    event_kind: Literal["document_uploaded", "reprocess_requested", "chat_turn"]
    worker: Literal["intake_extractor", "evidence_retriever"]
    attempt: int = Field(ge=1, le=2)
    status: Literal["completed", "partial", "unavailable", "failed", "canceled"]
    output_refs: list[VersionedReference] = Field(max_length=8)
    limitation_codes: list[Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]] = Field(max_length=8)
    retryable: bool
    stage_timings: list[StageTiming] = Field(max_length=16)
    contract_versions: dict[str, str] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_result(self) -> "WorkerHandoffResult":
        if len(set(self.limitation_codes)) != len(self.limitation_codes):
            raise ValueError("limitation codes must be unique")
        if self.status == "completed" and (not self.output_refs or self.limitation_codes):
            raise ValueError("completed handoff requires output and no limitation")
        if self.status in ("unavailable", "failed", "canceled") and not self.limitation_codes:
            raise ValueError("terminal non-success handoff requires a limitation")
        return self


ClaimId = Annotated[str, StringConstraints(pattern=r"^c[0-9]{1,3}$")]
CitationId = Annotated[str, StringConstraints(pattern=r"^ct[0-9]{1,3}$")]
RegistrySlug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]
GuidelineSourceId = Annotated[
    str,
    StringConstraints(
        pattern=r"^guideline:[a-z0-9][a-z0-9._-]{0,63}:[a-z0-9][a-z0-9._-]{0,63}:[a-z0-9][a-z0-9._-]{0,63}$",
        max_length=240,
    ),
]
AbsoluteHttpsUrl = Annotated[
    str,
    StringConstraints(pattern=r"^https://[^\s#]+(?:#[^\s]+)?$", min_length=1, max_length=1_000),
]
RelativeHref = Annotated[str, StringConstraints(pattern=r"^/[^#\x00-\x1f]{0,999}$", max_length=1_000)]
OpenEmrSourceId = Annotated[
    str,
    StringConstraints(pattern=r"^openemr:[A-Za-z0-9_-]{1,64}:[0-9]+(?::[0-9a-f-]{36})?$", max_length=240),
]
DocumentSourceId = Annotated[
    str,
    StringConstraints(
        pattern=r"^document:[0-9a-f-]{36}:record:[0-9a-f-]{36}:v:[1-9][0-9]*:field:[a-z][a-z0-9_.-]{0,127}$",
        max_length=240,
    ),
]


class GuidelineSection(StrictModel):
    kind: Literal["guideline_section"]
    section_path: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(min_length=1, max_length=8)
    chunk_ordinal: int = Field(ge=0)


class ExactQuote(StrictModel):
    kind: Literal["exact_quote"]
    quote: str = Field(min_length=1, max_length=500)


class GuidelineCitation(StrictModel):
    citation_id: CitationId
    claim_id: ClaimId
    source_id: GuidelineSourceId
    source_type: Literal["guideline"]
    title: str = Field(min_length=1, max_length=470)
    page_or_section: GuidelineSection
    field_or_chunk_id: RegistrySlug
    quote_or_value: ExactQuote
    publisher: str = Field(min_length=1, max_length=160)
    jurisdiction: str = Field(min_length=1, max_length=80)
    canonical_url: AbsoluteHttpsUrl
    publication_date: date | None = None
    topic: str = Field(min_length=1, max_length=160)
    corpus_version: RegistrySlug
    source_sha256: Sha256
    chunk_sha256: Sha256
    href: AbsoluteHttpsUrl
    retrieved_at: DateTime


class GuidelineExcerptFacts(StrictModel):
    quote: str = Field(min_length=1, max_length=500)
    publisher: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=300)
    topic: str = Field(min_length=1, max_length=160)
    section_path: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(min_length=1, max_length=8)


class GuidelineEvidenceClaim(StrictModel):
    id: ClaimId
    claim_class: Literal["guideline_evidence"]
    type: Literal["guideline_excerpt"]
    text: str = Field(min_length=1, max_length=700)
    facts: GuidelineExcerptFacts
    source_ids: list[GuidelineSourceId] = Field(min_length=1, max_length=1)
    section: Literal["guideline_evidence"]
    citations: list[GuidelineCitation] = Field(min_length=1, max_length=1)

    @model_validator(mode="after")
    def claim_matches_trusted_citation(self) -> "GuidelineEvidenceClaim":
        citation = self.citations[0]
        source_id = self.source_ids[0]
        _, corpus_version, _, chunk_id = source_id.split(":", 3)
        if citation.claim_id != self.id or citation.source_id != source_id:
            raise ValueError("guideline citation identity must match its claim")
        if citation.quote_or_value.quote != self.facts.quote:
            raise ValueError("guideline citation quote must match the claim quote")
        if (
            citation.publisher != self.facts.publisher
            or citation.topic != self.facts.topic
            or citation.page_or_section.section_path != self.facts.section_path
            or citation.corpus_version != corpus_version
            or citation.field_or_chunk_id != chunk_id
        ):
            raise ValueError("guideline citation metadata must match claim facts and source identity")
        expected = f"{self.facts.publisher} — {self.facts.title}: {self.facts.quote}"
        if self.text != expected:
            raise ValueError("guideline claim text must use the deterministic attribution template")
        return self


class TurnBinding(StrictModel):
    site_id: str = Field(min_length=1, max_length=128)
    user_id: str = Field(min_length=1, max_length=128)
    patient_id: str = Field(min_length=1, max_length=128)
    conversation_id: str = Field(min_length=1, max_length=128)
    turn_id: str = Field(min_length=1, max_length=128)
    correlation_id: CorrelationId
    authorized_at: DateTime


class OpenEmrRecordSource(StrictModel):
    source_type: Literal["openemr_record"]
    source_id: OpenEmrSourceId
    source_ref: SourceRef
    chart_section: str = Field(min_length=1, max_length=64)
    record_label: str = Field(min_length=1, max_length=160)
    source_version: str = Field(min_length=1, max_length=64)
    retrieved_at: DateTime
    fields: dict[str, str | int | float | bool | None]
    href: RelativeHref

    @model_validator(mode="after")
    def source_matches_ref(self) -> "OpenEmrRecordSource":
        if self.source_id != self.source_ref.source_id:
            raise ValueError("OpenEMR source ID must match its source reference")
        return self


class ReviewedDocumentFieldSource(StrictModel):
    source_type: Literal["reviewed_document"]
    source_id: DocumentSourceId
    source_document_id: Uuid
    source_content_sha256: Sha256
    record_id: Uuid
    record_version: int = Field(ge=1, le=2_147_483_647)
    record_status: Literal["active", "amended"]
    record_type: Literal["lab_report", "intake_response"]
    field_id: FieldId
    review_id: Uuid
    review_decision: Literal["approved", "corrected"]
    reviewed_value: DocumentFieldValue
    evidence: list[FieldEvidence] = Field(min_length=1, max_length=3)
    schema_version: str = Field(min_length=1, max_length=64)
    retrieved_at: DateTime
    href: RelativeHref

    @model_validator(mode="after")
    def source_identity_matches_fields(self) -> "ReviewedDocumentFieldSource":
        expected = f"document:{self.source_document_id}:record:{self.record_id}:v:{self.record_version}:field:{self.field_id}"
        if self.source_id != expected:
            raise ValueError("document source ID does not match its typed identity")
        return self


class GuidelineChunkSource(StrictModel):
    source_type: Literal["guideline"]
    source_id: GuidelineSourceId
    corpus_version: RegistrySlug
    document_id: RegistrySlug
    chunk_id: RegistrySlug
    publisher: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=300)
    jurisdiction: str = Field(min_length=1, max_length=80)
    canonical_url: AbsoluteHttpsUrl
    publication_date: date | None = None
    topic: str = Field(min_length=1, max_length=160)
    section_path: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(min_length=1, max_length=8)
    chunk_ordinal: int = Field(ge=0)
    exact_text: str = Field(min_length=1, max_length=4_000)
    source_sha256: Sha256
    chunk_sha256: Sha256
    retrieved_at: DateTime
    corpus_retrieved_at: DateTime
    approved_at: DateTime
    href: AbsoluteHttpsUrl

    @model_validator(mode="after")
    def validate_identity_and_hash(self) -> "GuidelineChunkSource":
        if self.source_id != f"guideline:{self.corpus_version}:{self.document_id}:{self.chunk_id}":
            raise ValueError("guideline source ID does not match its typed identity")
        if hashlib.sha256(self.exact_text.encode()).hexdigest() != self.chunk_sha256:
            raise ValueError("guideline chunk hash does not match exact text")
        return self


ResolvedSourceValue = Annotated[
    OpenEmrRecordSource | ReviewedDocumentFieldSource | GuidelineChunkSource,
    Field(discriminator="source_type"),
]


class ResolvedSource(RootModel[ResolvedSourceValue]):
    pass


class ChartSection(StrictModel):
    kind: Literal["chart_section"]
    section: str = Field(min_length=1, max_length=64)


class RecordValue(StrictModel):
    kind: Literal["record_value"]
    value: str = Field(min_length=1, max_length=500)


class OpenEmrRecordCitation(StrictModel):
    citation_id: CitationId
    claim_id: ClaimId
    source_id: OpenEmrSourceId
    source_type: Literal["openemr_record"]
    title: str = Field(min_length=1, max_length=160)
    page_or_section: ChartSection
    field_or_chunk_id: str = Field(min_length=1, max_length=64)
    quote_or_value: RecordValue
    source_version: str = Field(min_length=1, max_length=64)
    href: RelativeHref
    retrieved_at: DateTime


class DocumentRegion(StrictModel):
    kind: Literal["document_region"]
    page_number: int = Field(ge=1)
    box: NormalizedBox


class ReviewedDocumentValue(StrictModel):
    kind: Literal["reviewed_document_value"]
    reviewed_value: DocumentFieldValue
    printed_quote: str = Field(min_length=1, max_length=500)
    review_decision: Literal["approved", "corrected"]


class ReviewedDocumentCitation(StrictModel):
    citation_id: CitationId
    claim_id: ClaimId
    source_id: DocumentSourceId
    source_type: Literal["reviewed_document"]
    title: str = Field(min_length=1, max_length=160)
    page_or_section: DocumentRegion
    field_or_chunk_id: FieldId
    quote_or_value: ReviewedDocumentValue
    source_content_sha256: Sha256
    rendered_page_sha256: Sha256
    ocr_text_sha256: Sha256
    record_id: Uuid
    record_version: int = Field(ge=1)
    review_id: Uuid
    evidence_id: Uuid
    href: RelativeHref
    retrieved_at: DateTime


CitationValue = Annotated[
    OpenEmrRecordCitation | ReviewedDocumentCitation | GuidelineCitation,
    Field(discriminator="source_type"),
]


class Citation(RootModel[CitationValue]):
    pass


class IntakeAnswerFacts(StrictModel):
    link_id: FieldId
    repeat_key: Uuid | None = None
    answer: ReviewedAnswer


PatientClaimType = Literal[
    "change_event",
    "medication_status",
    "problem_status",
    "lab_result",
    "lab_comparison",
    "documented_reference",
    "absence",
    "conflict",
    "undated",
    "intake_answer",
]
PatientSourceId = OpenEmrSourceId | DocumentSourceId
PatientCitation = OpenEmrRecordCitation | ReviewedDocumentCitation


class PatientRecordClaim(StrictModel):
    id: ClaimId
    claim_class: Literal["patient_record"]
    type: PatientClaimType
    text: str = Field(min_length=1, max_length=400)
    facts: ClaimFacts | IntakeAnswerFacts
    source_ids: list[PatientSourceId] = Field(max_length=8)
    section: str = Field(min_length=1, max_length=32)
    citations: list[PatientCitation] = Field(max_length=24)

    @model_validator(mode="after")
    def validate_patient_claim(self) -> "PatientRecordClaim":
        if (self.type == "intake_answer") != isinstance(self.facts, IntakeAnswerFacts):
            raise ValueError("intake-answer claims require intake-answer facts")
        if self.type != "absence" and (not self.source_ids or not self.citations):
            raise ValueError("non-absence patient claims require sources and citations")
        if any(citation.claim_id != self.id or citation.source_id not in self.source_ids for citation in self.citations):
            raise ValueError("patient citations must resolve sources from the same claim")
        return self


FinalClaimValue = Annotated[PatientRecordClaim | GuidelineEvidenceClaim, Field(discriminator="claim_class")]


class FinalClaim(RootModel[FinalClaimValue]):
    pass


class Week2Limitation(StrictModel):
    kind: Literal[
        "not_documented",
        "reviewed_none",
        "unavailable",
        "truncated",
        "conflict",
        "undated",
        "withheld",
        "out_of_scope",
        "narrative_unavailable",
        "model_budget_exhausted",
        "guideline_no_evidence",
        "guideline_stale",
        "guideline_retrieval_unavailable",
    ]
    section: str | None = Field(default=None, min_length=1, max_length=32)
    detail: str = Field(min_length=1, max_length=300)
    source_ids: list[OpenEmrSourceId | DocumentSourceId | GuidelineSourceId] = Field(max_length=8)

    @model_validator(mode="after")
    def validate_guideline_limitation(self) -> "Week2Limitation":
        if self.kind.startswith("guideline_") and self.section != "guideline_evidence":
            raise ValueError("guideline limitations belong to the guideline evidence lane")
        return self


class ReleaseIdentity(StrictModel):
    manifest_sha256: Sha256
    fixtures_sha256: Sha256
    schema_version: str = Field(min_length=1, max_length=64)
    rubric_version: str = Field(min_length=1, max_length=64)
    guideline_corpus_sha256: Sha256
    resolver_sha256: Sha256
    runtime_image: str = Field(min_length=1, max_length=300)
    model: str = Field(min_length=1, max_length=160)
    prompt_sha256: Sha256
    attempt_policy: str = Field(min_length=1, max_length=160)


class ReleaseManifestEntry(StrictModel):
    id: str = Field(min_length=1, max_length=128)
    tier: Literal["golden", "coverage"]
    primary_category: str = Field(min_length=1, max_length=128)
    capability_tags: list[str] = Field(min_length=1, max_length=16)
    rubrics: list[str] = Field(min_length=1, max_length=16)
    threshold: Decimal = Field(ge=0, le=1)
    zero_tolerance: bool


class ReleaseAttempt(StrictModel):
    rubrics: dict[str, bool] = Field(min_length=1, max_length=32)


class ReleaseCaseResult(StrictModel):
    id: str = Field(min_length=1, max_length=128)
    attempts: list[ReleaseAttempt] = Field(min_length=1, max_length=10)


class ReleaseReport(StrictModel):
    identity: ReleaseIdentity
    manifest: list[ReleaseManifestEntry] = Field(min_length=1)
    cases: list[ReleaseCaseResult] = Field(min_length=1)
