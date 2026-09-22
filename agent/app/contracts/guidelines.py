"""Strict, local-only contracts for the approved guideline corpus.

These are deliberately transport-neutral.  Slice 3A defines inputs and
immutable evidence shapes; it does not add a worker, ranking, source resolver,
or UI route.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Literal

from pydantic import Field, HttpUrl, model_validator
from typing_extensions import Annotated

from .common import CorrelationId, SourceId, StrictModel


GUIDELINE_CONTRACT_VERSION = "3.0.0"
ACTIVE_CORPUS_VERSION = "uspstf-recommendations-2026-09-21-v2"

RegistrySlug = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$", max_length=64)]
Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
GuidelineSourceId = Annotated[
    str,
    Field(
        pattern=(
            r"^guideline:uspstf-recommendations-2026-09-21-v2:"
            r"[a-z0-9][a-z0-9._-]{0,63}:[a-z0-9][a-z0-9._-]{0,63}$"
        ),
        max_length=240,
    ),
]


class EvidenceIntent(StrEnum):
    """The corpus supplies publisher evidence only, never care advice."""

    guideline_evidence = "guideline_evidence"


class GuidelineTopic(StrEnum):
    aaa = "aaa"
    breast = "breast"
    cervical = "cervical"
    colorectal = "colorectal"
    lung = "lung"
    child_obesity = "child_obesity"
    hypertension = "hypertension"
    tobacco = "tobacco"


class EvidenceQuery(StrictModel):
    """A bounded retrieval request, intentionally with no free-text question.

    A later supervisor may map a physician request to these finite concepts at
    a server-held boundary.  Raw questions, chart text, OCR, and identifiers
    therefore cannot reach a corpus artifact through this contract.
    """

    contract_version: Literal["3.0.0"] = GUIDELINE_CONTRACT_VERSION
    intent: Literal[EvidenceIntent.guideline_evidence] = EvidenceIntent.guideline_evidence
    concepts: list[GuidelineTopic] = Field(min_length=1, max_length=3)
    topic_filter: GuidelineTopic | None = None
    requested_top_k: int = Field(default=5, ge=1, le=5)
    active_corpus_version: Literal["uspstf-recommendations-2026-09-21-v2"] = ACTIVE_CORPUS_VERSION
    correlation_id: CorrelationId
    handoff_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    deadline_ms: int = Field(ge=1, le=2000)

    @model_validator(mode="after")
    def topic_filter_is_also_a_bounded_concept(self) -> "EvidenceQuery":
        if self.topic_filter is not None and self.topic_filter not in self.concepts:
            raise ValueError("topic_filter must be one of the approved concepts")
        if len(set(self.concepts)) != len(self.concepts):
            raise ValueError("concepts must not repeat")
        return self


class CandidateLeg(StrEnum):
    sparse = "sparse"
    dense = "dense"


class GuidelineCandidate(StrictModel):
    """An internal candidate from a bounded retrieval leg.

    The text is immutable corpus content and must not be copied into ordinary
    telemetry.  Ranking is intentionally not implemented in Slice 3A.
    """

    contract_version: Literal["3.0.0"] = GUIDELINE_CONTRACT_VERSION
    source_id: GuidelineSourceId
    corpus_version: Literal["uspstf-recommendations-2026-09-21-v2"] = ACTIVE_CORPUS_VERSION
    document_id: RegistrySlug
    chunk_id: RegistrySlug
    chunk_ordinal: int = Field(ge=0)
    leg: CandidateLeg
    leg_rank: int = Field(ge=1, le=20)
    score: float | None = None
    chunk_sha256: Sha256

    @model_validator(mode="after")
    def immutable_source_id_matches_fields(self) -> "GuidelineCandidate":
        expected = f"guideline:{self.corpus_version}:{self.document_id}:{self.chunk_id}"
        if self.source_id != expected:
            raise ValueError("source_id must bind corpus, document, and chunk")
        return self


class GuidelineExcerpt(StrictModel):
    """Exact publisher text and metadata returned only inside a trusted lane."""

    contract_version: Literal["3.0.0"] = GUIDELINE_CONTRACT_VERSION
    source_id: GuidelineSourceId
    corpus_version: Literal["uspstf-recommendations-2026-09-21-v2"] = ACTIVE_CORPUS_VERSION
    document_id: RegistrySlug
    chunk_id: RegistrySlug
    chunk_ordinal: int = Field(ge=0)
    publisher: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=300)
    jurisdiction: str = Field(min_length=1, max_length=80)
    canonical_url: HttpUrl
    publication_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    topic: GuidelineTopic
    section_path: list[str] = Field(min_length=1, max_length=8)
    exact_text: str = Field(min_length=1, max_length=4000)
    source_sha256: Sha256
    chunk_sha256: Sha256
    corpus_retrieved_at: datetime
    approved_at: datetime

    @model_validator(mode="after")
    def immutable_fields_match_source_id(self) -> "GuidelineExcerpt":
        expected = f"guideline:{self.corpus_version}:{self.document_id}:{self.chunk_id}"
        if self.source_id != expected:
            raise ValueError("source_id must bind corpus, document, and chunk")
        if any(not path or len(path) > 200 for path in self.section_path):
            raise ValueError("section_path entries must be bounded non-empty strings")
        if sha256(self.exact_text.encode()).hexdigest() != self.chunk_sha256:
            raise ValueError("chunk_sha256 must match exact_text")
        return self


class GuidelineSection(StrictModel):
    kind: Literal["guideline_section"] = "guideline_section"
    section_path: list[str] = Field(min_length=1, max_length=8)
    chunk_ordinal: int = Field(ge=0)


class ExactQuote(StrictModel):
    kind: Literal["exact_quote"] = "exact_quote"
    quote: str = Field(min_length=1, max_length=500)


class GuidelineCitation(StrictModel):
    """Resolver-authored PRD citation for a single exact guideline quote."""

    citation_id: str = Field(pattern=r"^ct[0-9]{1,3}$")
    claim_id: str = Field(pattern=r"^c[0-9]{1,3}$")
    source_type: Literal["guideline"] = "guideline"
    source_id: GuidelineSourceId
    title: str = Field(min_length=1, max_length=470)
    page_or_section: GuidelineSection
    field_or_chunk_id: RegistrySlug
    quote_or_value: ExactQuote
    publisher: str = Field(min_length=1, max_length=160)
    jurisdiction: str = Field(min_length=1, max_length=80)
    canonical_url: HttpUrl
    publication_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    topic: GuidelineTopic
    corpus_version: Literal["uspstf-recommendations-2026-09-21-v2"] = ACTIVE_CORPUS_VERSION
    source_sha256: Sha256
    chunk_sha256: Sha256
    href: HttpUrl
    retrieved_at: datetime


class GuidelineExcerptFacts(StrictModel):
    quote: str = Field(min_length=1, max_length=500)
    publisher: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=300)
    topic: GuidelineTopic
    section_path: list[str] = Field(min_length=1, max_length=8)


class GuidelineEvidenceClaim(StrictModel):
    """A final claim shape whose prose is deterministic, exact attribution."""

    id: str = Field(pattern=r"^c[0-9]{1,3}$")
    claim_class: Literal["guideline_evidence"] = "guideline_evidence"
    type: Literal["guideline_excerpt"] = "guideline_excerpt"
    text: str = Field(min_length=1, max_length=700)
    facts: GuidelineExcerptFacts
    source_ids: list[GuidelineSourceId] = Field(min_length=1, max_length=1)
    section: Literal["guideline_evidence"] = "guideline_evidence"
    citations: list[GuidelineCitation] = Field(min_length=1, max_length=1)

    @model_validator(mode="after")
    def exact_claim_binds_one_resolver_citation(self) -> "GuidelineEvidenceClaim":
        citation = self.citations[0]
        if citation.claim_id != self.id or citation.source_id != self.source_ids[0]:
            raise ValueError("guideline citation must bind this claim and its sole source")
        if citation.field_or_chunk_id != citation.source_id.rsplit(":", 1)[1]:
            raise ValueError("citation chunk must match source_id")
        if citation.quote_or_value.quote != self.facts.quote:
            raise ValueError("citation quote must match claim facts")
        if (
            citation.publisher != self.facts.publisher
            or citation.topic != self.facts.topic
            or citation.page_or_section.section_path != self.facts.section_path
        ):
            raise ValueError("citation metadata must match the exact claim facts")
        expected_text = f'{self.facts.publisher}: "{self.facts.quote}"'
        if self.text != expected_text:
            raise ValueError("guideline claim text must use the deterministic exact-quote template")
        return self


class GuidelineRetrievalLimitationCode(StrEnum):
    corpus_unavailable = "guideline_retrieval_unavailable"
    corpus_stale = "guideline_corpus_stale"
    no_evidence = "guideline_no_evidence"
    query_rejected = "guideline_query_rejected"
    deadline_exceeded = "guideline_retrieval_timeout"
    canceled = "guideline_retrieval_canceled"
    duplicate_handoff = "guideline_duplicate_handoff"
    stale_handoff = "guideline_stale_handoff"
    malformed_output = "guideline_malformed_output"


class GuidelineRetrievalLimitation(StrictModel):
    code: GuidelineRetrievalLimitationCode
    detail: str = Field(max_length=160)


class EvidenceWorkerStatus(StrEnum):
    """The one terminal outcome emitted by the bounded local worker."""

    completed = "completed"
    limited = "limited"
    canceled = "canceled"


class EvidenceWorkerTimings(StrictModel):
    sparse_ms: float = Field(ge=0, le=2000)
    dense_ms: float = Field(ge=0, le=2000)
    fusion_ms: float = Field(ge=0, le=2000)
    rerank_ms: float = Field(ge=0, le=2000)
    total_ms: float = Field(ge=0, le=2000)


class EvidenceWorkerResult(StrictModel):
    """A terminal worker envelope, never a final clinical claim or citation.

    The later authenticated supervisor/resolver owns dispatch, source resolution,
    verification, and rendering.  This envelope contains only exact corpus
    excerpts or one typed limitation.
    """

    contract_version: Literal["3.0.0"] = GUIDELINE_CONTRACT_VERSION
    worker_revision: Literal["evidence-retriever-local-v1"] = "evidence-retriever-local-v1"
    correlation_id: CorrelationId
    handoff_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    status: EvidenceWorkerStatus
    corpus_version: Literal["uspstf-recommendations-2026-09-21-v2"] = ACTIVE_CORPUS_VERSION
    artifact_manifest_sha256: Sha256
    embedding_model_revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    reranker_model_revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    candidate_count: int = Field(ge=0, le=40)
    hit_count: int = Field(ge=0, le=5)
    timings: EvidenceWorkerTimings
    excerpts: list[GuidelineExcerpt] = Field(default_factory=list, max_length=5)
    limitation: GuidelineRetrievalLimitation | None = None

    @model_validator(mode="after")
    def terminal_outcome_is_atomic(self) -> "EvidenceWorkerResult":
        successful = self.status is EvidenceWorkerStatus.completed
        if successful and (not self.excerpts or self.limitation is not None or self.hit_count != len(self.excerpts)):
            raise ValueError("completed worker result requires only exact excerpts")
        if not successful and (self.excerpts or self.limitation is None or self.hit_count != 0):
            raise ValueError("limited or canceled worker result requires one limitation and no excerpts")
        if self.status is EvidenceWorkerStatus.canceled and self.limitation.code is not GuidelineRetrievalLimitationCode.canceled:
            raise ValueError("canceled worker result requires the canceled limitation")
        return self
