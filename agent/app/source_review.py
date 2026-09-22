"""Trusted click-to-source resolver boundary for the module UI.

The browser asks the OpenEMR module to open an opaque citation selector.  The
module reauthorizes that request and then calls the agent route, which only
accepts a citation that was rendered in the exact authenticated turn.  A
resolver must nevertheless reopen its own protected source: checkpointed
citation metadata is not a current source view.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol

from .contracts.common import StrictModel
from .contracts.week2 import Citation, GuidelineCitation
from .guideline_retriever import FrozenCorpus, MAX_CORPUS_AGE, load_frozen_corpus


class SourceReviewEnvelope(StrictModel):
    citation: Citation
    source: dict[str, object]


class SourceReviewResolver(Protocol):
    async def resolve(
        self,
        conversation_id: str,
        turn_id: str,
        citation: dict[str, object],
        correlation_id: str,
    ) -> SourceReviewEnvelope | None: ...


class GuidelineSourceReviewResolver:
    """Reopen only an active, immutable local-corpus guideline citation.

    This module deliberately knows nothing about patient-record or document
    storage.  Those source classes require their own live OpenEMR adapters;
    returning ``None`` for them is the fail-closed behavior, not a fallback to
    checkpointed metadata.  Keeping the interface to one ``resolve`` method
    gives the API one seam while preserving that locality.
    """

    def __init__(
        self,
        corpus_loader: Callable[[], FrozenCorpus],
        *,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._corpus_loader = corpus_loader
        self._now = now

    async def resolve(
        self,
        conversation_id: str,
        turn_id: str,
        citation: dict[str, object],
        correlation_id: str,
    ) -> SourceReviewEnvelope | None:
        # The API has already checked these opaque selectors against the exact
        # delegation and rendered turn.  Do not log them or use them as source
        # selectors here.
        del conversation_id, turn_id, correlation_id
        try:
            trusted = Citation.model_validate(citation).root
        except Exception:  # noqa: BLE001 - the caller returns a content-free 503
            return None
        if not isinstance(trusted, GuidelineCitation):
            return None
        return await asyncio.to_thread(self._reopen, trusted)

    def _reopen(self, citation: GuidelineCitation) -> SourceReviewEnvelope | None:
        try:
            corpus = self._corpus_loader()
            now = self._now()
            if now.tzinfo is None or now.utcoffset() != timedelta(0):
                return None
            retrieved = _utc(corpus.retrieved_at)
            approved = _utc(corpus.approved_at)
            if now - max(retrieved, approved) > MAX_CORPUS_AGE:
                return None
        except Exception:  # noqa: BLE001 - integrity/load errors are unavailable, never a stale view
            return None

        if corpus.version != citation.corpus_version:
            return None
        chunk = next(
            (
                item for item in corpus.chunks
                if item.chunk_id == citation.field_or_chunk_id
                and item.document_id == citation.source_id.split(":", 3)[2]
            ),
            None,
        )
        if chunk is None:
            return None
        if not (
            chunk.corpus_version == citation.corpus_version
            and chunk.publisher == citation.publisher
            and chunk.title == citation.title.removeprefix(chunk.publisher + " — ")
            and chunk.jurisdiction == citation.jurisdiction
            and chunk.canonical_url == citation.canonical_url
            and chunk.topic == citation.topic
            and chunk.section_path == citation.page_or_section.section_path
            and chunk.chunk_ordinal == citation.page_or_section.chunk_ordinal
            and chunk.source_sha256 == citation.source_sha256
            and chunk.chunk_sha256 == citation.chunk_sha256
            and citation.quote_or_value.quote in chunk.exact_text
        ):
            return None
        return SourceReviewEnvelope.model_validate({
            "citation": citation.model_dump(mode="json"),
            "source": {
                "source_type": "guideline",
                "status": "active",
                "source_id": citation.source_id,
                "corpus_version": corpus.version,
                "active_corpus_version": corpus.version,
                "document_id": chunk.document_id,
                "chunk_id": chunk.chunk_id,
                "publisher": chunk.publisher,
                "title": chunk.title,
                "section_path": chunk.section_path,
                "chunk_ordinal": chunk.chunk_ordinal,
                "exact_text": chunk.exact_text,
                "source_sha256": chunk.source_sha256,
                "chunk_sha256": chunk.chunk_sha256,
                "canonical_url": chunk.canonical_url,
            },
        })


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("source review timestamps must be UTC")
    return parsed.astimezone(timezone.utc)


def configured_guideline_source_resolver(settings: object) -> GuidelineSourceReviewResolver | None:
    """Build the optional local-corpus adapter without making startup depend on it.

    Readiness reports corpus/model failures separately.  The resolver is
    intentionally configured whenever the capability is enabled, then each
    click reloads and integrity-checks the immutable files.  A bad deployment
    therefore gives a typed unavailable source instead of a stale cached page.
    """
    if not bool(getattr(settings, "guideline_enabled", False)):
        return None
    # Kept here rather than duplicated as settings constants: the exact hashes
    # are the readiness contract and must be identical at click time.
    from .readiness import GUIDELINE_CORPUS_SHA256, GUIDELINE_MANIFEST_SHA256

    return GuidelineSourceReviewResolver(lambda: load_frozen_corpus(
        corpus_path=getattr(settings, "guideline_corpus_path"),
        manifest_path=getattr(settings, "guideline_manifest_path"),
        expected_corpus_sha256=GUIDELINE_CORPUS_SHA256,
        expected_manifest_sha256=GUIDELINE_MANIFEST_SHA256,
    ))
