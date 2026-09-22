"""Bounded Slice 1 lab-PDF extraction worker.

This worker is intentionally not part of the chat graph.  It receives one
delegated immutable document reference, reads it once through the module's
reauthorizing gateway, and returns a review-only preview.  The committed
synthetic fixture has a simple PDF text layer, so deterministic parsing is a
safer and more reproducible choice than sending document content to a model.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import zlib
from dataclasses import dataclass
from typing import Protocol

from .contracts import (
    DocumentLimitation,
    ExtractionConfidence,
    ExtractionState,
    ExtractionStatus,
    IntakeAllergy,
    IntakeDemographics,
    IntakeDateField,
    IntakeExtraction,
    IntakeExtractionResult,
    IntakeFamilyHistory,
    IntakeFieldEvidence,
    IntakeFieldState,
    IntakeMedication,
    IntakeTextField,
    LabExtraction,
    LabExtractionResult,
    LabFieldEvidence,
    SourceCitation,
)

FIELD_NAMES = ("test_name", "value", "unit", "reference_range", "collection_date", "abnormal_flag")
_INTAKE_COMPLETE_STATES = {IntakeFieldState.present, IntakeFieldState.checked, IntakeFieldState.unchecked}


@dataclass(frozen=True)
class SourceBytes:
    status: int
    source_id: str | None
    source_hash: str | None
    content_type: str | None
    bytes: bytes | None
    document_type: str | None = None


class SourceReaderPort(Protocol):
    async def read_source(self, source_id: str, token: str, correlation_id: str) -> SourceBytes: ...


@dataclass(frozen=True)
class _Candidate:
    value: str | None
    quote: str | None
    state: ExtractionState


def _pdf_text(pdf: bytes) -> str:
    """Read literal `Tj` strings from the tightly bounded synthetic PDF.

    This is deliberately not a general PDF/OCR implementation. Unsupported,
    compressed, encrypted, or malformed PDFs yield no text and therefore
    explicit unreadable fields, rather than best-effort invented values.
    """
    if not pdf.startswith(b"%PDF-"):
        return ""
    streams = [pdf]
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\n?endstream", pdf, flags=re.DOTALL):
        if b"FlateDecode" not in pdf[max(0, match.start() - 200):match.start()]:
            continue
        try:
            streams.append(zlib.decompress(match.group(1)))
        except zlib.error:
            continue
    strings = []
    for stream in streams:
        strings.extend(re.findall(rb"\(([^()\\]{1,2000})\)(?:\s*Tj\b|\s*['\"])" , stream))
    return "\n".join(part.decode("latin-1", "strict") for part in strings)


def _match(text: str, pattern: str, group: int = 1) -> _Candidate:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if match is None:
        return _Candidate(None, None, ExtractionState.missing if text else ExtractionState.unreadable)
    value = match.group(group).strip()
    return _Candidate(value or None, value or None, ExtractionState.extracted if value else ExtractionState.malformed)


def _parse(text: str) -> dict[str, _Candidate]:
    """Parse only fixed field labels; every other document instruction is data."""
    value = _match(text, r"\bValue:\s*([0-9]+(?:\.[0-9]+)?)\s+([A-Za-z][A-Za-z0-9_-]{0,63})")
    unit = _match(text, r"\bValue:\s*[0-9]+(?:\.[0-9]+)?\s+([A-Za-z][A-Za-z0-9_-]{0,63})")
    flag = _match(text, r"\bFlag:\s*(abnormal|normal|unknown)\b")
    return {
        "test_name": _match(text, r"\bTest:\s*([^|\n]{1,160})"),
        "value": value,
        "unit": unit,
        "reference_range": _match(text, r"\bReference range:\s*([^|\n]{1,160})"),
        "collection_date": _match(text, r"\bCollection date:\s*(\d{4}-\d{2}-\d{2})\b"),
        "abnormal_flag": flag,
    }


def resolve_lab_preview(source_id: str, source_hash: str, pdf: bytes) -> LabExtraction:
    """Author citations from the source actually read, never from worker output."""
    text = _pdf_text(pdf)
    parsed = _parse(text)
    fields: dict[str, LabFieldEvidence] = {}
    values: dict[str, str | None] = {}
    for name in FIELD_NAMES:
        candidate = parsed[name]
        values[name] = candidate.value
        if candidate.state is not ExtractionState.extracted or candidate.quote is None or candidate.quote not in text:
            fields[name] = LabFieldEvidence(state=candidate.state, confidence=ExtractionConfidence.unknown)
            values[name] = None
            continue
        citation = SourceCitation(
            source_type="document",
            source_id=f"{source_id}:page:1",
            page_or_section=1,
            field_or_chunk_id=name,
            quote_or_value=candidate.quote,
            source_hash=source_hash,
        )
        fields[name] = LabFieldEvidence(state=ExtractionState.extracted, confidence=ExtractionConfidence.high, source_citation=citation)
    flag = values["abnormal_flag"] if values["abnormal_flag"] in {"abnormal", "normal", "unknown"} else "unknown"
    return LabExtraction(
        test_name=values["test_name"], value=values["value"], unit=values["unit"],
        reference_range=values["reference_range"], collection_date=values["collection_date"],
        abnormal_flag=flag, fields=fields,
    )


def verify_lab_preview(source_id: str, source_hash: str, pdf: bytes, extraction: LabExtraction) -> LabExtraction:
    """Final deterministic display authority for a document preview."""
    text = _pdf_text(pdf)
    for name, evidence in extraction.fields.items():
        if evidence.state is not ExtractionState.extracted:
            continue
        citation = evidence.source_citation
        if (
            citation is None
            or citation.source_id != f"{source_id}:page:1"
            or citation.source_hash != source_hash
            or citation.field_or_chunk_id != name
            or citation.page_or_section != 1
            or citation.quote_or_value not in text
            or citation.quote_or_value != getattr(extraction, name)
        ):
            raise ValueError("citation_integrity")
    return extraction


def _intake_field(
    source_id: str,
    source_hash: str,
    text: str,
    field_id: str,
    value: str | None,
    state: IntakeFieldState,
    quote: str | None = None,
) -> IntakeTextField:
    """Build a proposal and its resolver-authored citation from printed text."""
    citation = None
    printed = quote if quote is not None else value
    if printed is not None:
        if printed not in text:
            raise ValueError("citation_integrity")
        citation = SourceCitation(source_type="document", source_id=f"{source_id}:page:1", page_or_section=1,
                                  field_or_chunk_id=field_id, quote_or_value=printed, source_hash=source_hash)
    return IntakeTextField(value=value, evidence=IntakeFieldEvidence(
        state=state, confidence=ExtractionConfidence.medium if value is not None else ExtractionConfidence.unknown,
        source_citation=citation,
    ))


def _intake_date_field(
    source_id: str,
    source_hash: str,
    text: str,
    field_id: str,
    value: str | None,
    state: IntakeFieldState,
    quote: str | None = None,
) -> IntakeDateField:
    field = _intake_field(source_id, source_hash, text, field_id, value, state, quote)
    return IntakeDateField(value=field.value, evidence=field.evidence)


def _intake_candidate(text: str, pattern: str) -> tuple[str | None, IntakeFieldState, str | None]:
    """Read one bounded printed field without interpreting the value as an instruction."""
    candidate = _match(text, pattern)
    if candidate.state is ExtractionState.extracted and candidate.value is not None:
        return candidate.value, IntakeFieldState.present, candidate.quote
    return None, IntakeFieldState.unreadable if candidate.state is ExtractionState.unreadable else IntakeFieldState.missing, None


def _intake_limitations(extraction: IntakeExtraction) -> list[DocumentLimitation]:
    """Report bounded field metadata only; document content never enters a limitation."""
    fields: list[tuple[str, IntakeTextField | None]] = [
        ("given name", extraction.demographics.given_name),
        ("date of birth", extraction.demographics.date_of_birth),
        ("chief concern", extraction.chief_concern),
    ]
    fields.extend(("current medication", item.name) for item in extraction.medications)
    fields.extend(("allergy", item.substance) for item in extraction.allergies)
    fields.extend(("allergy reaction", item.reaction) for item in extraction.allergies)
    fields.extend(("family relationship", item.relationship) for item in extraction.family_history)
    fields.extend(("family history", item.condition) for item in extraction.family_history)
    return [
        DocumentLimitation(code="malformed_source", detail=f"{name.capitalize()} is {field.evidence.state.value}; review is required.")
        for name, field in fields
        if field is not None and field.evidence.state not in _INTAKE_COMPLETE_STATES
    ]


def resolve_intake_preview(source_id: str, source_hash: str, pdf: bytes) -> IntakeExtraction:
    """Resolve the deliberately bounded synthetic intake labels into proposals.

    Labels are fixed by this parser; arbitrary free text is only a displayed
    document value and cannot select a route, tool, patient, or schema.
    """
    text = _pdf_text(pdf)
    if not text or "AgentForge Synthetic Intake Form" not in text:
        raise ValueError("unsupported_intake_format")
    given, given_state, given_quote = _intake_candidate(text, r"\bGiven name:[ \t]*([^\n]{1,100})")
    concern, concern_state, concern_quote = _intake_candidate(text, r"\bChief concern:[ \t]*([^\n]{1,2000})")
    medication, medication_state, medication_quote = _intake_candidate(text, r"\bCurrent medication:[ \t]*([^\n]{1,200})")
    family, family_state, family_quote = _intake_candidate(text, r"\bFamily history:[ \t]*([^\-\n]{1,100})[ \t]*-")
    condition, condition_state, condition_quote = _intake_candidate(text, r"\bFamily history:[ \t]*[^\-\n]{1,100}[ \t]*-[ \t]*([^\n]{1,200})")
    dob = _match(text, r"\bDate of birth:[ \t]*([^\n]{1,100})")
    if dob.state is ExtractionState.extracted and dob.value is not None:
        # This narrow synthetic form marks the two printed date orders as
        # ambiguous.  Preserve the exact text as evidence, never choose one.
        if "/" in dob.value:
            dob_value, dob_state, dob_quote = None, IntakeFieldState.ambiguous, dob.quote
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", dob.value):
            dob_value, dob_state, dob_quote = dob.value, IntakeFieldState.present, dob.quote
        else:
            dob_value, dob_state, dob_quote = None, IntakeFieldState.unreadable, None
    else:
        dob_value, dob_state, dob_quote = None, IntakeFieldState.unreadable if dob.state is ExtractionState.unreadable else IntakeFieldState.missing, None

    allergy_match = re.search(r"\bAllergies:[ \t]*\[([ xX])\][ \t]*([^;\n]{1,200})", text, flags=re.IGNORECASE)
    if allergy_match is None:
        allergy_value, allergy_state, allergy_quote = None, IntakeFieldState.missing, None
    else:
        allergy_value = allergy_match.group(2).strip()
        allergy_state = IntakeFieldState.checked if allergy_match.group(1).strip() else IntakeFieldState.unchecked
        allergy_quote = allergy_value
    if not text.strip():
        raise ValueError("malformed_intake_format")
    return IntakeExtraction(
        demographics=IntakeDemographics(
            given_name=_intake_field(source_id, source_hash, text, "given_name", given, given_state, given_quote),
            date_of_birth=_intake_date_field(source_id, source_hash, text, "date_of_birth", dob_value, dob_state, dob_quote),
        ),
        chief_concern=_intake_field(source_id, source_hash, text, "chief_concern", concern, concern_state, concern_quote),
        medications=[IntakeMedication(entry_id="1" * 32, name=_intake_field(source_id, source_hash, text, "medication_name", medication, medication_state, medication_quote))],
        allergies=[IntakeAllergy(entry_id="2" * 32,
            substance=_intake_field(source_id, source_hash, text, "allergy_substance", allergy_value, allergy_state, allergy_quote),
            reaction=_intake_field(source_id, source_hash, text, "allergy_reaction", None, IntakeFieldState.missing))],
        family_history=[IntakeFamilyHistory(entry_id="3" * 32,
            relationship=_intake_field(source_id, source_hash, text, "family_relationship", family, family_state, family_quote),
            condition=_intake_field(source_id, source_hash, text, "family_condition", condition, IntakeFieldState.conflicting if condition_state is IntakeFieldState.present and condition and "/" in condition else condition_state, condition_quote))],
    )


def verify_intake_preview(source_id: str, source_hash: str, pdf: bytes, extraction: IntakeExtraction) -> IntakeExtraction:
    """Verify every renderable intake field against its immutable source."""
    text = _pdf_text(pdf)
    def verify(field_id: str, field: IntakeTextField | None) -> None:
        if field is None:
            return
        citation = field.evidence.source_citation
        requires_evidence = field.evidence.state not in {IntakeFieldState.missing, IntakeFieldState.unreadable}
        if not requires_evidence and field.value is None and citation is None:
            return
        if (citation is None or citation.source_id != f"{source_id}:page:1" or citation.source_hash != source_hash
                or citation.page_or_section != 1 or citation.field_or_chunk_id != field_id
                or citation.quote_or_value not in text or (field.value is not None and field.value not in citation.quote_or_value)):
            raise ValueError("citation_integrity")
    verify("given_name", extraction.demographics.given_name)
    verify("date_of_birth", extraction.demographics.date_of_birth)
    verify("chief_concern", extraction.chief_concern)
    for medication in extraction.medications:
        verify("medication_name", medication.name)
    for allergy in extraction.allergies:
        verify("allergy_substance", allergy.substance)
        verify("allergy_reaction", allergy.reaction)
    for history in extraction.family_history:
        verify("family_relationship", history.relationship)
        verify("family_condition", history.condition)
    return extraction


class IntakeExtractor:
    """The PRD-named, read-only `intake_extractor` worker for Slice 1 lab PDFs."""

    def __init__(self, source_reader: SourceReaderPort) -> None:
        self.source_reader = source_reader

    async def extract(self, source_id: str, token: str, correlation_id: str, fault: str | None = None) -> LabExtractionResult | IntakeExtractionResult:
        handoff_id = secrets.token_hex(16)
        source = await self.source_reader.read_source(source_id, token, correlation_id)
        if source.status in {401, 403, 404}:
            # The API converts this to the same generic denial envelope as the
            # rest of the delegation boundary; no source bytes are exposed.
            raise PermissionError("source_denied")
        if (
            source.status != 200 or source.source_id != source_id or source.content_type != "application/pdf"
            or source.bytes is None or source.source_hash is None
            or hashlib.sha3_512(source.bytes).hexdigest() != source.source_hash
        ):
            return self._unavailable(source_id, handoff_id)
        if source.document_type == "intake_form":
            if fault in {"model", "extraction", "budget"}:
                return self._intake_unavailable(source_id, handoff_id)
            try:
                extraction = verify_intake_preview(source_id, source.source_hash, source.bytes, resolve_intake_preview(source_id, source.source_hash, source.bytes))
            except Exception:
                return IntakeExtractionResult(source_id=source_id, handoff_id=handoff_id, status=ExtractionStatus.failed,
                    limitations=[DocumentLimitation(code="verification_failed", detail="The intake preview could not be verified.")])
            limitations = _intake_limitations(extraction)
            status = ExtractionStatus.complete if not limitations else ExtractionStatus.partial
            return IntakeExtractionResult(source_id=source_id, handoff_id=handoff_id, status=status, extraction=extraction, limitations=limitations)
        if source.document_type != "lab_pdf":
            return self._unavailable(source_id, handoff_id)
        if fault in {"model", "extraction", "budget"}:
            return self._unavailable(source_id, handoff_id)
        try:
            extraction = verify_lab_preview(source_id, source.source_hash, source.bytes, resolve_lab_preview(source_id, source.source_hash, source.bytes))
        except Exception:  # no raw parser error or candidate content enters a response/log
            return LabExtractionResult(
                source_id=source_id, handoff_id=handoff_id, status=ExtractionStatus.failed,
                limitations=[DocumentLimitation(code="verification_failed", detail="The document preview could not be verified.")],
            )
        status = ExtractionStatus.complete if all(field.state is ExtractionState.extracted for field in extraction.fields.values()) else ExtractionStatus.partial
        limitations = [
            DocumentLimitation(code="malformed_source", detail=f"{name.replace('_', ' ').capitalize()} is {field.state.value}.")
            for name, field in extraction.fields.items() if field.state is not ExtractionState.extracted
        ]
        return LabExtractionResult(source_id=source_id, handoff_id=handoff_id, status=status, extraction=extraction, limitations=limitations)

    @staticmethod
    def _unavailable(source_id: str, handoff_id: str) -> LabExtractionResult:
        return LabExtractionResult(
            source_id=source_id, handoff_id=handoff_id, status=ExtractionStatus.unavailable,
            limitations=[DocumentLimitation(code="extraction_unavailable", detail="The document preview is temporarily unavailable. No extracted facts were shown.")],
        )

    @staticmethod
    def _intake_unavailable(source_id: str, handoff_id: str) -> IntakeExtractionResult:
        return IntakeExtractionResult(source_id=source_id, handoff_id=handoff_id, status=ExtractionStatus.unavailable,
            limitations=[DocumentLimitation(code="extraction_unavailable", detail="The intake preview is temporarily unavailable. No extracted facts were shown.")])
