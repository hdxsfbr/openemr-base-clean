"""Closed, deterministic Week 2 claim verification.

The registry contains only source projections already returned by authorized
tools for the current turn.  This module deliberately has no persistence,
network, tool, or model dependency.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal, Sequence

from pydantic import Field, RootModel, ValidationError

from .contracts.common import StrictModel
from .contracts.turns import ClaimFacts
from .contracts.week2 import (
    DateTime,
    GuidelineChunkSource,
    GuidelineCitation,
    GuidelineEvidenceClaim,
    GuidelineExcerptFacts,
    GuidelineSourceId,
    IntakeAnswerFacts,
    OpenEmrRecordCitation,
    OpenEmrRecordSource,
    PatientClaimType,
    PatientRecordClaim,
    PatientSourceId,
    QuantityValue,
    ReferenceRange,
    ReviewedDocumentCitation,
    ReviewedDocumentFieldSource,
    ResolvedSourceValue,
    TextValue,
    TurnBinding,
    Week2Limitation,
)
from .verifier import FORBIDDEN


ResolutionState = Literal[
    "resolved",
    "stale",
    "withdrawn",
    "unauthorized",
    "not_found",
    "hash_mismatch",
    "version_mismatch",
    "unavailable",
]


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")


class RegisteredSource(StrictModel):
    """A trusted resolver result and the server-held binding that produced it."""

    source: ResolvedSourceValue
    binding: TurnBinding
    state: ResolutionState = "resolved"


class PatientClaimCandidate(StrictModel):
    id: str = Field(pattern=r"^c[0-9]{1,3}$")
    claim_class: Literal["patient_record"]
    type: PatientClaimType
    text: str = Field(min_length=1, max_length=400)
    facts: ClaimFacts | IntakeAnswerFacts
    source_ids: list[PatientSourceId] = Field(max_length=8)
    section: str = Field(min_length=1, max_length=32)


class GuidelineClaimCandidate(StrictModel):
    id: str = Field(pattern=r"^c[0-9]{1,3}$")
    claim_class: Literal["guideline_evidence"]
    type: Literal["guideline_excerpt"]
    facts: GuidelineExcerptFacts
    source_ids: list[GuidelineSourceId] = Field(min_length=1, max_length=1)
    section: Literal["guideline_evidence"]


ClaimCandidateValue = Annotated[
    PatientClaimCandidate | GuidelineClaimCandidate,
    Field(discriminator="claim_class"),
]


class ClaimCandidate(RootModel[ClaimCandidateValue]):
    pass


class ClaimRejection(StrictModel):
    claim_id: str = Field(pattern=r"^c[0-9]{1,3}$")
    lane: Literal["patient_record", "guideline_evidence"]
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    detail: str = Field(min_length=1, max_length=200)
    source_ids: list[str] = Field(default_factory=list, max_length=8)


class PatientLaneResult(StrictModel):
    lane: Literal["patient_record"] = "patient_record"
    accepted: list[PatientRecordClaim] = Field(default_factory=list, max_length=40)
    rejected: list[ClaimRejection] = Field(default_factory=list, max_length=40)
    limitations: list[Week2Limitation] = Field(default_factory=list, max_length=40)


class GuidelineLaneResult(StrictModel):
    lane: Literal["guideline_evidence"] = "guideline_evidence"
    accepted: list[GuidelineEvidenceClaim] = Field(default_factory=list, max_length=40)
    rejected: list[ClaimRejection] = Field(default_factory=list, max_length=40)
    limitations: list[Week2Limitation] = Field(default_factory=list, max_length=40)


class Week2VerificationResult(StrictModel):
    patient_record: PatientLaneResult = Field(default_factory=PatientLaneResult)
    guideline_evidence: GuidelineLaneResult = Field(default_factory=GuidelineLaneResult)

    @property
    def outcome(self) -> Literal["passed", "partial", "rejected"]:
        accepted = len(self.patient_record.accepted) + len(self.guideline_evidence.accepted)
        rejected = len(self.patient_record.rejected) + len(self.guideline_evidence.rejected)
        if accepted and rejected:
            return "partial"
        if rejected:
            return "rejected"
        return "passed"


class CurrentTurnSourceRegistry:
    """Exact current-turn source allowlist; resolution performs no I/O."""

    def __init__(
        self,
        *,
        binding: TurnBinding,
        sources: Sequence[RegisteredSource],
        verified_at: DateTime,
        active_corpus_version: str | None = None,
    ) -> None:
        self.binding = binding
        self.verified_at = verified_at
        self.active_corpus_version = active_corpus_version
        self._sources: dict[str, RegisteredSource] = {}
        for entry in sources:
            if entry.source.source_id in self._sources:
                raise ValueError("duplicate source ID in current-turn registry")
            self._sources[entry.source.source_id] = entry

    def resolve(self, source_id: str) -> tuple[ResolvedSourceValue | None, ResolutionState]:
        entry = self._sources.get(source_id)
        if entry is None:
            return None, "not_found"
        if entry.state != "resolved":
            return None, entry.state
        if isinstance(entry.source, GuidelineChunkSource):
            if (
                entry.binding.turn_id != self.binding.turn_id
                or entry.binding.correlation_id != self.binding.correlation_id
            ):
                return None, "unauthorized"
            if entry.source.corpus_version != self.active_corpus_version:
                return None, "stale"
            latest_approval = max(
                _instant(entry.source.corpus_retrieved_at),
                _instant(entry.source.approved_at),
            )
            if _instant(self.verified_at) - latest_approval > timedelta(days=14):
                return None, "stale"
            if not (
                _instant(self.binding.authorized_at)
                <= _instant(entry.source.retrieved_at)
                <= _instant(self.verified_at)
            ):
                return None, "stale"
            return entry.source, "resolved"
        if entry.binding != self.binding:
            return None, "unauthorized"
        if isinstance(entry.source, (OpenEmrRecordSource, ReviewedDocumentFieldSource)) and not (
            _instant(self.binding.authorized_at)
            <= _instant(entry.source.retrieved_at)
            <= _instant(self.verified_at)
        ):
            return None, "stale"
        return entry.source, "resolved"


_OPENEMR_FACT_FIELDS: dict[str, tuple[str, ...]] = {
    "change_event": ("section", "kind", "date"),
    "medication_status": ("name", "status"),
    "problem_status": ("name", "status"),
    "lab_result": ("analyte", "value_text", "unit", "flag", "date"),
    "documented_reference": ("medication_name", "mention"),
}

_CROSS_LANE_PATTERNS = (
    r"\bguideline\b",
    r"\bappl(?:y|ies|icable|icability)\b",
    r"\beligib(?:le|ility)\b",
    r"\bfor this patient\b",
)


def _patient_text_is_forbidden(text: str) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in _CROSS_LANE_PATTERNS) or any(
        re.search(pattern, text, re.IGNORECASE) for pattern, _rule in FORBIDDEN
    )


def _verify_openemr_candidate(
    candidate: PatientClaimCandidate,
    source: OpenEmrRecordSource,
    citation_start: int,
) -> PatientRecordClaim | ClaimRejection:
    if candidate.section != source.chart_section:
        return ClaimRejection(
            claim_id=candidate.id,
            lane="patient_record",
            code="wrong_section",
            detail="Claim section does not match the resolved chart section.",
            source_ids=candidate.source_ids,
        )
    fact_names = _OPENEMR_FACT_FIELDS.get(candidate.type, ())
    if not fact_names:
        return ClaimRejection(
            claim_id=candidate.id,
            lane="patient_record",
            code="unsupported_claim_type",
            detail="The OpenEMR projection cannot support this claim type.",
            source_ids=candidate.source_ids,
        )
    facts = candidate.facts.model_dump(mode="json", exclude_none=True)
    for name in fact_names:
        if name not in facts or facts[name] != source.fields.get(name):
            return ClaimRejection(
                claim_id=candidate.id,
                lane="patient_record",
                code="value_mismatch",
                detail="Claim facts do not exactly match the current source projection.",
                source_ids=candidate.source_ids,
            )
    citations = [
        OpenEmrRecordCitation(
            citation_id=f"ct{citation_start + index - 1}",
            claim_id=candidate.id,
            source_id=source.source_id,
            source_type="openemr_record",
            title=source.record_label,
            page_or_section={"kind": "chart_section", "section": source.chart_section},
            field_or_chunk_id=name,
            quote_or_value={"kind": "record_value", "value": str(source.fields[name])},
            source_version=source.source_version,
            href=source.href,
            retrieved_at=source.retrieved_at,
        )
        for index, name in enumerate(fact_names, start=1)
    ]
    return PatientRecordClaim(
        **candidate.model_dump(),
        citations=citations,
    )


def _verify_document_candidate(
    candidate: PatientClaimCandidate,
    source: ReviewedDocumentFieldSource,
    citation_start: int,
) -> PatientRecordClaim | ClaimRejection:
    if candidate.type != "intake_answer" or not isinstance(candidate.facts, IntakeAnswerFacts):
        return ClaimRejection(
            claim_id=candidate.id,
            lane="patient_record",
            code="unsupported_claim_type",
            detail="This reviewed document field cannot support the requested claim type.",
            source_ids=candidate.source_ids,
        )
    answer = candidate.facts.answer.value
    if candidate.facts.link_id != source.field_id or answer != source.reviewed_value:
        return ClaimRejection(
            claim_id=candidate.id,
            lane="patient_record",
            code="value_mismatch",
            detail="The intake answer does not exactly match the current reviewed field.",
            source_ids=candidate.source_ids,
        )
    citations = [
        ReviewedDocumentCitation(
            citation_id=f"ct{citation_start + index - 1}",
            claim_id=candidate.id,
            source_id=source.source_id,
            source_type="reviewed_document",
            title=f"Intake response v{source.record_version}",
            page_or_section={
                "kind": "document_region",
                "page_number": evidence.page_number,
                "box": evidence.box,
            },
            field_or_chunk_id=source.field_id,
            quote_or_value={
                "kind": "reviewed_document_value",
                "reviewed_value": source.reviewed_value,
                "printed_quote": evidence.printed_quote,
                "review_decision": source.review_decision,
            },
            source_content_sha256=source.source_content_sha256,
            rendered_page_sha256=evidence.rendered_page_sha256,
            ocr_text_sha256=evidence.ocr_text_sha256,
            record_id=source.record_id,
            record_version=source.record_version,
            review_id=source.review_id,
            evidence_id=evidence.evidence_id,
            href=source.href,
            retrieved_at=source.retrieved_at,
        )
        for index, evidence in enumerate(source.evidence, start=1)
    ]
    return PatientRecordClaim(**candidate.model_dump(), citations=citations)


def _decimal_text(value: Decimal) -> str:
    rendered = format(value, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _document_value_text(value: object) -> str:
    if isinstance(value, QuantityValue):
        return _decimal_text(value.value)
    if isinstance(value, TextValue):
        return value.value
    return str(value)


def _reference_range_text(value: ReferenceRange) -> str:
    if value.text is not None:
        rendered = value.text
    elif value.low is not None and value.high is not None:
        rendered = f"{_decimal_text(value.low)}–{_decimal_text(value.high)}"
    elif value.low is not None:
        rendered = f">={_decimal_text(value.low)}"
    else:
        rendered = f"<={_decimal_text(value.high)}"
    return f"{rendered} {value.unit}" if value.unit else rendered


def _reviewed_document_citations(
    candidate: PatientClaimCandidate,
    sources: Sequence[ReviewedDocumentFieldSource],
    citation_start: int,
    title: str,
) -> list[ReviewedDocumentCitation]:
    citations: list[ReviewedDocumentCitation] = []
    for source in sources:
        for evidence in source.evidence:
            citations.append(
                ReviewedDocumentCitation(
                    citation_id=f"ct{citation_start + len(citations)}",
                    claim_id=candidate.id,
                    source_id=source.source_id,
                    source_type="reviewed_document",
                    title=title,
                    page_or_section={
                        "kind": "document_region",
                        "page_number": evidence.page_number,
                        "box": evidence.box,
                    },
                    field_or_chunk_id=source.field_id,
                    quote_or_value={
                        "kind": "reviewed_document_value",
                        "reviewed_value": source.reviewed_value,
                        "printed_quote": evidence.printed_quote,
                        "review_decision": source.review_decision,
                    },
                    source_content_sha256=source.source_content_sha256,
                    rendered_page_sha256=evidence.rendered_page_sha256,
                    ocr_text_sha256=evidence.ocr_text_sha256,
                    record_id=source.record_id,
                    record_version=source.record_version,
                    review_id=source.review_id,
                    evidence_id=evidence.evidence_id,
                    href=source.href,
                    retrieved_at=source.retrieved_at,
                )
            )
    return citations


def _verify_document_lab_result(
    candidate: PatientClaimCandidate,
    sources: Sequence[ReviewedDocumentFieldSource],
    citation_start: int,
) -> PatientRecordClaim | ClaimRejection:
    def reject(code: str, detail: str) -> ClaimRejection:
        return ClaimRejection(
            claim_id=candidate.id,
            lane="patient_record",
            code=code,
            detail=detail,
            source_ids=candidate.source_ids,
        )

    if candidate.type != "lab_result" or not isinstance(candidate.facts, ClaimFacts):
        return reject("unsupported_claim_type", "Reviewed lab fields cannot support this claim type.")
    if candidate.section != "labs" or not sources:
        return reject("wrong_section", "Reviewed lab claims belong to the labs section.")
    identity = {
        (
            source.source_document_id,
            source.record_id,
            source.record_version,
            source.source_content_sha256,
            source.schema_version,
        )
        for source in sources
    }
    if len(identity) != 1 or any(source.record_type != "lab_report" for source in sources):
        return reject("mixed_document_record", "Reviewed lab fields must come from one immutable record version.")
    by_field = {source.field_id: source for source in sources}
    if len(by_field) != len(sources):
        return reject("duplicate_field", "Reviewed lab fields must be unique.")
    analyte_prefixes = {
        field_id.rsplit(".", 1)[0]
        for field_id in by_field
        if field_id.endswith((".test_name", ".value", ".unit", ".reference_range", ".abnormal_flag"))
    }
    if len(analyte_prefixes) != 1:
        return reject("mixed_analyte", "Reviewed lab fields must describe exactly one analyte.")
    prefix = analyte_prefixes.pop()
    required = {
        "collection_date",
        f"{prefix}.test_name",
        f"{prefix}.value",
    }
    if candidate.facts.unit is not None:
        required.add(f"{prefix}.unit")
    if candidate.facts.flag is not None:
        required.add(f"{prefix}.abnormal_flag")
    range_asserted = "reference range" in candidate.text.lower()
    if range_asserted:
        required.add(f"{prefix}.reference_range")
    if set(by_field) != required:
        return reject("source_set_mismatch", "Reviewed lab sources do not exactly cover the asserted fields.")
    expected_values = {
        "collection_date": candidate.facts.date,
        f"{prefix}.test_name": candidate.facts.analyte,
        f"{prefix}.value": candidate.facts.value_text,
        f"{prefix}.unit": candidate.facts.unit,
        f"{prefix}.abnormal_flag": candidate.facts.flag,
    }
    for field_id, expected in expected_values.items():
        if field_id not in by_field:
            continue
        if _document_value_text(by_field[field_id].reviewed_value) != expected:
            return reject("value_mismatch", "Claim facts do not exactly match the reviewed lab fields.")
    if range_asserted:
        range_value = by_field[f"{prefix}.reference_range"].reviewed_value
        if not isinstance(range_value, ReferenceRange) or _reference_range_text(range_value) not in candidate.text:
            return reject("value_mismatch", "The asserted reference range does not match its reviewed field.")
    record_version = sources[0].record_version
    citations = _reviewed_document_citations(candidate, sources, citation_start, f"Lab report v{record_version}")
    return PatientRecordClaim(**candidate.model_dump(), citations=citations)


def _reviewed_lab_observation(
    sources: Sequence[ReviewedDocumentFieldSource],
) -> tuple[str, datetime, Decimal, str, str] | None:
    if not sources or any(source.record_type != "lab_report" for source in sources):
        return None
    identity = {
        (
            source.source_document_id,
            source.record_id,
            source.record_version,
            source.source_content_sha256,
            source.schema_version,
        )
        for source in sources
    }
    by_field = {source.field_id: source for source in sources}
    prefixes = {
        field_id.rsplit(".", 1)[0]
        for field_id in by_field
        if field_id.endswith((".test_name", ".value", ".unit"))
    }
    if len(identity) != 1 or len(by_field) != len(sources) or len(prefixes) != 1:
        return None
    prefix = prefixes.pop()
    if set(by_field) != {
        "collection_date",
        f"{prefix}.test_name",
        f"{prefix}.value",
        f"{prefix}.unit",
    }:
        return None
    analyte = by_field[f"{prefix}.test_name"].reviewed_value
    measured = by_field[f"{prefix}.value"].reviewed_value
    unit = by_field[f"{prefix}.unit"].reviewed_value
    recorded_date = by_field["collection_date"].reviewed_value
    if not isinstance(analyte, str) or not isinstance(measured, QuantityValue) or not isinstance(unit, str):
        return None
    try:
        day = datetime.strptime(str(recorded_date), "%Y-%m-%d")
    except ValueError:
        return None
    if not unit:
        return None
    return analyte, day, measured.value, unit, by_field[f"{prefix}.value"].source_id


def _native_lab_observation(source: OpenEmrRecordSource) -> tuple[str, datetime, Decimal, str, str] | None:
    fields = source.fields
    analyte = fields.get("analyte")
    value = fields.get("value_text")
    unit = fields.get("unit")
    recorded_date = fields.get("date")
    if not isinstance(analyte, str) or not isinstance(unit, str) or not unit or value is None:
        return None
    try:
        numeric = Decimal(str(value))
        day = datetime.strptime(str(recorded_date), "%Y-%m-%d")
    except (InvalidOperation, ValueError):
        return None
    if not numeric.is_finite():
        return None
    return analyte, day, numeric, unit, source.source_id


def _native_lab_comparison_citations(
    candidate: PatientClaimCandidate,
    source: OpenEmrRecordSource,
    citation_start: int,
) -> list[OpenEmrRecordCitation]:
    citations: list[OpenEmrRecordCitation] = []
    for field_name in ("analyte", "value_text", "unit", "date"):
        citations.append(
            OpenEmrRecordCitation(
                citation_id=f"ct{citation_start + len(citations)}",
                claim_id=candidate.id,
                source_id=source.source_id,
                source_type="openemr_record",
                title=source.record_label,
                page_or_section={"kind": "chart_section", "section": source.chart_section},
                field_or_chunk_id=field_name,
                quote_or_value={"kind": "record_value", "value": str(source.fields[field_name])},
                source_version=source.source_version,
                href=source.href,
                retrieved_at=source.retrieved_at,
            )
        )
    return citations


def _verify_lab_comparison(
    candidate: PatientClaimCandidate,
    sources: Sequence[ResolvedSourceValue],
    citation_start: int,
) -> PatientRecordClaim | ClaimRejection:
    def reject(code: str, detail: str) -> ClaimRejection:
        return ClaimRejection(
            claim_id=candidate.id,
            lane="patient_record",
            code=code,
            detail=detail,
            source_ids=candidate.source_ids,
        )

    if candidate.type != "lab_comparison" or not isinstance(candidate.facts, ClaimFacts):
        return reject("unsupported_claim_type", "The source set cannot support this comparison type.")
    native_sources = [source for source in sources if isinstance(source, OpenEmrRecordSource)]
    document_sources = [source for source in sources if isinstance(source, ReviewedDocumentFieldSource)]
    if len(native_sources) != 1 or len(native_sources) + len(document_sources) != len(sources):
        return reject("source_class_mismatch", "Comparison requires one native and one reviewed lab result.")
    native = _native_lab_observation(native_sources[0])
    reviewed = _reviewed_lab_observation(document_sources)
    if native is None or reviewed is None:
        return reject("lab_rules", "Comparison sources require exact numeric values, dates, analytes, and units.")
    observations = {native[4]: native, reviewed[4]: reviewed}
    earlier_id = candidate.facts.earlier_source_id
    later_id = candidate.facts.later_source_id
    if earlier_id not in observations or later_id not in observations or earlier_id == later_id:
        return reject("source_identity_mismatch", "Comparison identities must name the native and reviewed values.")
    earlier = observations[earlier_id]
    later = observations[later_id]
    if earlier[0] != later[0] or candidate.facts.analyte != earlier[0]:
        return reject("analyte_mismatch", "Comparison analytes must match exactly.")
    if earlier[3] != later[3]:
        return reject("unit_mismatch", "Comparison units must be present and exactly equal.")
    if earlier[1] == later[1]:
        return reject("same_day_superseded", "Same-day results cannot form a comparison.")
    if earlier[1] > later[1]:
        return reject("date_order_mismatch", "Earlier and later source identities do not match their dates.")
    direction = "up" if later[2] > earlier[2] else "down" if later[2] < earlier[2] else "same"
    if candidate.facts.direction != direction:
        return reject("direction_mismatch", "Comparison direction does not match the exact numeric values.")
    native_citations = _native_lab_comparison_citations(candidate, native_sources[0], citation_start)
    document_citations = _reviewed_document_citations(
        candidate,
        document_sources,
        citation_start + len(native_citations),
        f"Lab report v{document_sources[0].record_version}",
    )
    return PatientRecordClaim(
        **candidate.model_dump(),
        citations=[*native_citations, *document_citations],
    )


def _verify_guideline_candidate(
    candidate: GuidelineClaimCandidate,
    source: GuidelineChunkSource,
    citation_id: int,
) -> GuidelineEvidenceClaim | ClaimRejection:
    facts = candidate.facts
    if (
        facts.publisher != source.publisher
        or facts.title != source.title
        or facts.topic != source.topic
        or facts.section_path != source.section_path
    ):
        return ClaimRejection(
            claim_id=candidate.id,
            lane="guideline_evidence",
            code="metadata_mismatch",
            detail="Guideline facts do not exactly match the active corpus source.",
            source_ids=candidate.source_ids,
        )
    quote = facts.quote.replace("\r\n", "\n").replace("\r", "\n")
    exact_text = source.exact_text.replace("\r\n", "\n").replace("\r", "\n")
    if quote not in exact_text:
        return ClaimRejection(
            claim_id=candidate.id,
            lane="guideline_evidence",
            code="quote_mismatch",
            detail="Guideline quote is not an exact contiguous source substring.",
            source_ids=candidate.source_ids,
        )
    citation = GuidelineCitation(
        citation_id=f"ct{citation_id}",
        claim_id=candidate.id,
        source_id=source.source_id,
        source_type="guideline",
        title=f"{source.publisher} — {source.title}",
        page_or_section={
            "kind": "guideline_section",
            "section_path": source.section_path,
            "chunk_ordinal": source.chunk_ordinal,
        },
        field_or_chunk_id=source.chunk_id,
        quote_or_value={"kind": "exact_quote", "quote": quote},
        publisher=source.publisher,
        jurisdiction=source.jurisdiction,
        canonical_url=source.canonical_url,
        publication_date=source.publication_date,
        topic=source.topic,
        corpus_version=source.corpus_version,
        source_sha256=source.source_sha256,
        chunk_sha256=source.chunk_sha256,
        href=source.href,
        retrieved_at=source.retrieved_at,
    )
    return GuidelineEvidenceClaim(
        id=candidate.id,
        claim_class="guideline_evidence",
        type="guideline_excerpt",
        text=f"{source.publisher} — {source.title}: {quote}",
        facts=candidate.facts.model_copy(update={"quote": quote}),
        source_ids=candidate.source_ids,
        section="guideline_evidence",
        citations=[citation],
    )


def verify_week2_claims(
    candidates: Sequence[object],
    registry: CurrentTurnSourceRegistry,
) -> Week2VerificationResult:
    """Verify independent claims against only the supplied current-turn registry."""

    result = Week2VerificationResult()
    next_citation_id = 1
    for raw in candidates:
        requested_lane = (
            "guideline_evidence"
            if isinstance(raw, dict) and raw.get("claim_class") == "guideline_evidence"
            else "patient_record"
        )
        try:
            if isinstance(raw, (PatientClaimCandidate, GuidelineClaimCandidate)):
                candidate = raw
            elif requested_lane == "guideline_evidence":
                candidate = GuidelineClaimCandidate.model_validate(raw)
            else:
                candidate = PatientClaimCandidate.model_validate(raw)
        except ValidationError:
            candidate_id = "c0"
            source_ids: list[str] = []
            section = "patient_record"
            if isinstance(raw, dict):
                if isinstance(raw.get("id"), str) and re.fullmatch(r"c[0-9]{1,3}", raw["id"]):
                    candidate_id = raw["id"]
                if isinstance(raw.get("section"), str) and 0 < len(raw["section"]) <= 32:
                    section = raw["section"]
                raw_source_ids = raw.get("source_ids")
                if isinstance(raw_source_ids, list):
                    source_ids = [value for value in raw_source_ids[:8] if isinstance(value, str) and len(value) <= 240]
            rejection = ClaimRejection(
                claim_id=candidate_id,
                lane=requested_lane,
                code="schema_invalid",
                detail="Claim candidate did not match the strict Week 2 schema.",
                source_ids=source_ids,
            )
            if requested_lane == "guideline_evidence":
                result.guideline_evidence.rejected.append(rejection)
                result.guideline_evidence.limitations.append(
                    Week2Limitation(
                        kind="guideline_retrieval_unavailable",
                        section="guideline_evidence",
                        detail="Guideline evidence was withheld because its structure was invalid.",
                        source_ids=[],
                    )
                )
            else:
                result.patient_record.rejected.append(rejection)
                result.patient_record.limitations.append(Week2Limitation(
                    kind="withheld",
                    section=section,
                    detail="A patient-record claim was withheld because its structure was invalid.",
                    source_ids=[],
                ))
            continue
        if isinstance(candidate, GuidelineClaimCandidate):
            try:
                source, state = registry.resolve(candidate.source_ids[0])
            except Exception:  # noqa: BLE001 - fail closed per claim at the verifier boundary
                source, state = None, "unavailable"
            if not isinstance(source, GuidelineChunkSource):
                result.guideline_evidence.rejected.append(
                    ClaimRejection(
                        claim_id=candidate.id,
                        lane="guideline_evidence",
                        code=state if source is None else "wrong_source_class",
                        detail="The guideline source did not resolve from the active current-turn corpus.",
                        source_ids=candidate.source_ids,
                    )
                )
                result.guideline_evidence.limitations.append(
                    Week2Limitation(
                        kind=(
                            "guideline_stale"
                            if state in ("stale", "hash_mismatch", "version_mismatch")
                            else "guideline_retrieval_unavailable"
                        ),
                        section="guideline_evidence",
                        detail="Guideline evidence could not be verified against the active corpus.",
                        source_ids=candidate.source_ids,
                    )
                )
                continue
            try:
                verified_guideline = _verify_guideline_candidate(candidate, source, next_citation_id)
            except Exception:  # noqa: BLE001 - strict final-contract failure must not escape
                verified_guideline = ClaimRejection(
                    claim_id=candidate.id,
                    lane="guideline_evidence",
                    code="verification_failed_closed",
                    detail="Guideline evidence failed deterministic final-contract validation.",
                    source_ids=candidate.source_ids,
                )
            if isinstance(verified_guideline, ClaimRejection):
                result.guideline_evidence.rejected.append(verified_guideline)
                result.guideline_evidence.limitations.append(
                    Week2Limitation(
                        kind="guideline_retrieval_unavailable",
                        section="guideline_evidence",
                        detail="Guideline evidence was withheld because its exact source checks failed.",
                        source_ids=candidate.source_ids,
                    )
                )
            else:
                result.guideline_evidence.accepted.append(verified_guideline)
                next_citation_id += 1
            continue
        if _patient_text_is_forbidden(candidate.text):
            result.patient_record.rejected.append(
                ClaimRejection(
                    claim_id=candidate.id,
                    lane="patient_record",
                    code="applicability_forbidden",
                    detail="Patient text cannot add advice or combine patient and guideline evidence.",
                    source_ids=candidate.source_ids,
                )
            )
            result.patient_record.limitations.append(
                Week2Limitation(
                    kind="withheld",
                    section=candidate.section,
                    detail="A patient-record claim was withheld because it added unsupported clinical framing.",
                    source_ids=candidate.source_ids,
                )
            )
            continue
        resolved: list[ResolvedSourceValue] = []
        for source_id in candidate.source_ids:
            try:
                source, state = registry.resolve(source_id)
            except Exception:  # noqa: BLE001 - fail closed per claim at the verifier boundary
                source, state = None, "unavailable"
            if source is None:
                result.patient_record.rejected.append(
                    ClaimRejection(
                        claim_id=candidate.id,
                        lane="patient_record",
                        code=state,
                        detail="A required current-turn source could not be resolved.",
                        source_ids=[source_id],
                    )
                )
                result.patient_record.limitations.append(
                    Week2Limitation(
                        kind="withheld",
                        section=candidate.section,
                        detail="A patient-record claim was withheld because its source did not verify.",
                        source_ids=[source_id],
                    )
                )
                break
            resolved.append(source)
        else:
            if candidate.type == "lab_comparison":
                try:
                    verified = _verify_lab_comparison(candidate, resolved, next_citation_id)
                except Exception:  # noqa: BLE001 - strict final-contract failure must not escape
                    verified = ClaimRejection(
                        claim_id=candidate.id,
                        lane="patient_record",
                        code="verification_failed_closed",
                        detail="Patient evidence failed deterministic final-contract validation.",
                        source_ids=candidate.source_ids,
                    )
            elif len(resolved) == 1 and isinstance(resolved[0], OpenEmrRecordSource):
                try:
                    verified = _verify_openemr_candidate(candidate, resolved[0], next_citation_id)
                except Exception:  # noqa: BLE001 - strict final-contract failure must not escape
                    verified = ClaimRejection(
                        claim_id=candidate.id,
                        lane="patient_record",
                        code="verification_failed_closed",
                        detail="Patient evidence failed deterministic final-contract validation.",
                        source_ids=candidate.source_ids,
                    )
            elif candidate.type == "lab_result" and all(
                isinstance(source, ReviewedDocumentFieldSource) for source in resolved
            ):
                try:
                    verified = _verify_document_lab_result(
                        candidate,
                        [source for source in resolved if isinstance(source, ReviewedDocumentFieldSource)],
                        next_citation_id,
                    )
                except Exception:  # noqa: BLE001 - strict final-contract failure must not escape
                    verified = ClaimRejection(
                        claim_id=candidate.id,
                        lane="patient_record",
                        code="verification_failed_closed",
                        detail="Patient evidence failed deterministic final-contract validation.",
                        source_ids=candidate.source_ids,
                    )
            elif len(resolved) == 1 and isinstance(resolved[0], ReviewedDocumentFieldSource):
                try:
                    verified = _verify_document_candidate(candidate, resolved[0], next_citation_id)
                except Exception:  # noqa: BLE001 - strict final-contract failure must not escape
                    verified = ClaimRejection(
                        claim_id=candidate.id,
                        lane="patient_record",
                        code="verification_failed_closed",
                        detail="Patient evidence failed deterministic final-contract validation.",
                        source_ids=candidate.source_ids,
                    )
            else:
                verified = None
            if verified is not None:
                if isinstance(verified, ClaimRejection):
                    result.patient_record.rejected.append(verified)
                    result.patient_record.limitations.append(
                        Week2Limitation(
                            kind="withheld",
                            section=candidate.section,
                            detail="A patient-record claim was withheld because its facts did not verify.",
                            source_ids=candidate.source_ids,
                        )
                    )
                else:
                    result.patient_record.accepted.append(verified)
                    next_citation_id += len(verified.citations)
            else:
                result.patient_record.rejected.append(
                    ClaimRejection(
                        claim_id=candidate.id,
                        lane="patient_record",
                        code="unsupported_source_set",
                        detail="The source set cannot support this patient claim type.",
                        source_ids=candidate.source_ids,
                    )
                )
                result.patient_record.limitations.append(
                    Week2Limitation(
                        kind="withheld",
                        section=candidate.section,
                        detail="A patient-record claim was withheld because its source set was unsupported.",
                        source_ids=candidate.source_ids,
                    )
                )
    return result
