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
from dataclasses import dataclass
from typing import Protocol

from .contracts import (
    DocumentLimitation,
    ExtractionConfidence,
    ExtractionState,
    ExtractionStatus,
    LabExtraction,
    LabExtractionResult,
    LabFieldEvidence,
    SourceCitation,
)

FIELD_NAMES = ("test_name", "value", "unit", "reference_range", "collection_date", "abnormal_flag")


@dataclass(frozen=True)
class SourceBytes:
    status: int
    source_id: str | None
    source_hash: str | None
    content_type: str | None
    bytes: bytes | None


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
    strings = re.findall(rb"\(([^()\\]{1,2000})\)\s*Tj\b", pdf)
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


class IntakeExtractor:
    """The PRD-named, read-only `intake_extractor` worker for Slice 1 lab PDFs."""

    def __init__(self, source_reader: SourceReaderPort) -> None:
        self.source_reader = source_reader

    async def extract(self, source_id: str, token: str, correlation_id: str, fault: str | None = None) -> LabExtractionResult:
        handoff_id = secrets.token_hex(16)
        if fault in {"model", "extraction", "budget"}:
            return self._unavailable(source_id, handoff_id)
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
