"""Week 2 document-ingestion contracts.

These models deliberately describe proposed extraction data, not chart facts.
Only the module's authenticated upload boundary can create a source document;
the agent can later receive an authorized source reference but never a patient
identifier or a filesystem path.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, StringConstraints, model_validator
from typing_extensions import Annotated

from .common import SourceId, StrictModel


DocumentSourceId = Annotated[
    str,
    StringConstraints(pattern=r"^document:[a-f0-9]{32}$", max_length=41),
]
DocumentHash = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{128}$")]
IntentId = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{32}$")]
DOCUMENT_CONTRACT_VERSION = "2.0.0"


class DocumentType(StrEnum):
    """Closed for Slice 1A. Intake is introduced by the later contract change."""

    lab_pdf = "lab_pdf"


class UploadStatus(StrEnum):
    pending = "pending"
    stored = "stored"
    rejected = "rejected"
    unavailable = "unavailable"


class LimitationCode(StrEnum):
    unauthorized = "unauthorized"
    invalid_file = "invalid_file"
    duplicate_or_replay = "duplicate_or_replay"
    malformed_source = "malformed_source"
    storage_unavailable = "storage_unavailable"
    extraction_unavailable = "extraction_unavailable"
    verification_failed = "verification_failed"


class DocumentLimitation(StrictModel):
    code: LimitationCode
    detail: str = Field(max_length=160)


class NormalizedBox(StrictModel):
    """Coordinates normalized to the source page, never pixels from a transient render."""

    left: float = Field(ge=0, le=1)
    top: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def stays_on_page(self) -> "NormalizedBox":
        if self.left + self.width > 1 or self.top + self.height > 1:
            raise ValueError("normalized box must remain inside its page")
        return self


class SourceCitation(StrictModel):
    """The PRD's minimum citation plus immutable source-integrity fields."""

    source_type: Literal["document"]
    source_id: SourceId
    page_or_section: int = Field(ge=1, le=20)
    field_or_chunk_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    quote_or_value: str = Field(min_length=1, max_length=300)
    source_hash: DocumentHash
    page_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    normalized_box: NormalizedBox | None = None


class ExtractionState(StrEnum):
    extracted = "extracted"
    missing = "missing"
    ambiguous = "ambiguous"
    unreadable = "unreadable"
    malformed = "malformed"


class ExtractionConfidence(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"
    unknown = "unknown"


class LabFieldEvidence(StrictModel):
    state: ExtractionState
    confidence: ExtractionConfidence
    source_citation: SourceCitation | None = None

    @model_validator(mode="after")
    def evidence_matches_state(self) -> "LabFieldEvidence":
        if self.state is ExtractionState.extracted and self.source_citation is None:
            raise ValueError("an extracted field needs a source citation")
        if self.state is not ExtractionState.extracted and self.source_citation is not None:
            raise ValueError("non-extracted fields cannot claim source evidence")
        return self


class LabExtraction(StrictModel):
    """A future worker proposal. It is explicitly not a clinical record fact."""

    contract_version: Literal["2.0.0"] = DOCUMENT_CONTRACT_VERSION
    test_name: str | None = Field(default=None, max_length=160)
    value: str | None = Field(default=None, max_length=160)
    unit: str | None = Field(default=None, max_length=64)
    reference_range: str | None = Field(default=None, max_length=160)
    collection_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    abnormal_flag: Literal["abnormal", "normal", "unknown"] = "unknown"
    fields: dict[Literal["test_name", "value", "unit", "reference_range", "collection_date", "abnormal_flag"], LabFieldEvidence]

    @model_validator(mode="after")
    def missing_values_are_visible(self) -> "LabExtraction":
        required = {"test_name", "value", "unit", "reference_range", "collection_date", "abnormal_flag"}
        if set(self.fields) != required:
            raise ValueError("every required lab field needs an explicit extraction state")
        for name, evidence in self.fields.items():
            if evidence.state is ExtractionState.extracted and getattr(self, name) in (None, ""):
                raise ValueError(f"{name} is extracted but has no value")
            if name == "abnormal_flag" and evidence.state is not ExtractionState.extracted and self.abnormal_flag == "unknown":
                continue
            if evidence.state is not ExtractionState.extracted and getattr(self, name) not in (None, ""):
                raise ValueError(f"{name} has a value without extracted evidence")
        return self


class ExtractionStatus(StrEnum):
    """Terminal status of the bounded, review-only intake-extractor job."""

    complete = "complete"
    partial = "partial"
    unavailable = "unavailable"
    failed = "failed"


class LabExtractionRequest(StrictModel):
    """The browser may name only the immutable source it just stored.

    A server-generated delegation token supplies patient, user, site, turn,
    correlation, and handoff identity; none is accepted from this request.
    """

    source_id: DocumentSourceId


class LabExtractionResult(StrictModel):
    """Verified preview data, never a persisted clinical record."""

    contract_version: Literal["2.0.0"] = DOCUMENT_CONTRACT_VERSION
    source_id: DocumentSourceId
    handoff_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    status: ExtractionStatus
    extraction: LabExtraction | None = None
    limitations: list[DocumentLimitation] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def only_verified_preview_data_is_renderable(self) -> "LabExtractionResult":
        if self.status in (ExtractionStatus.complete, ExtractionStatus.partial) and self.extraction is None:
            raise ValueError("a completed extraction needs verified extraction data")
        if self.status in (ExtractionStatus.unavailable, ExtractionStatus.failed) and self.extraction is not None:
            raise ValueError("a failed extraction cannot expose unverified data")
        return self


class SourceDocument(StrictModel):
    source_id: DocumentSourceId
    native_document_uuid: str = Field(pattern=r"^[a-f0-9-]{36}$")
    content_hash: DocumentHash
    version: Literal[1] = 1
    document_type: DocumentType
    mime_type: Literal["application/pdf"]
    byte_size: int = Field(gt=0, le=20 * 1024 * 1024)
    page_count: int = Field(ge=1, le=20)


class UploadIntent(StrictModel):
    contract_version: Literal["2.0.0"] = DOCUMENT_CONTRACT_VERSION
    intent_id: IntentId
    document_type: DocumentType
    status: Literal["pending"] = "pending"


class UploadResult(StrictModel):
    contract_version: Literal["2.0.0"] = DOCUMENT_CONTRACT_VERSION
    intent_id: IntentId
    status: UploadStatus
    source: SourceDocument | None = None
    limitation: DocumentLimitation | None = None

    @model_validator(mode="after")
    def terminal_result_is_unambiguous(self) -> "UploadResult":
        if self.status is UploadStatus.stored and self.source is None:
            raise ValueError("stored upload needs an immutable source")
        if self.status is not UploadStatus.stored and self.source is not None:
            raise ValueError("non-stored upload cannot expose a source")
        return self
