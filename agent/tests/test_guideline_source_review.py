from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone

from app.guideline_retriever import FrozenCorpus, GuidelineChunk
from app.source_review import GuidelineSourceReviewResolver, configured_guideline_source_resolver


def _corpus(*, version: str = "uspstf-2026q3", text: str = "Screen adults for high blood pressure.") -> FrozenCorpus:
    chunk = GuidelineChunk.model_validate({
        "chunk_id": "hypertension-001",
        "document_id": "hypertension",
        "corpus_version": version,
        "publisher": "Synthetic Clinical Society",
        "jurisdiction": "US",
        "title": "Synthetic hypertension guidance",
        "canonical_url": "https://example.test/hypertension",
        "topic": "hypertension",
        "section_path": ["Screening"],
        "chunk_ordinal": 1,
        "exact_text": text,
        "source_sha256": "a" * 64,
        "chunk_sha256": hashlib.sha256(text.encode()).hexdigest(),
    })
    return FrozenCorpus(version=version, retrieved_at="2026-09-21T00:00:00Z", approved_at="2026-09-21T00:00:00Z", chunks=[chunk])


def _citation(*, version: str = "uspstf-2026q3", quote: str = "Screen adults for high blood pressure.") -> dict[str, object]:
    return {
        "citation_id": "ct1",
        "claim_id": "c1",
        "source_id": f"guideline:{version}:hypertension:hypertension-001",
        "source_type": "guideline",
        "title": "Synthetic Clinical Society — Synthetic hypertension guidance",
        "page_or_section": {"kind": "guideline_section", "section_path": ["Screening"], "chunk_ordinal": 1},
        "field_or_chunk_id": "hypertension-001",
        "quote_or_value": {"kind": "exact_quote", "quote": quote},
        "publisher": "Synthetic Clinical Society",
        "jurisdiction": "US",
        "canonical_url": "https://example.test/hypertension",
        "topic": "hypertension",
        "corpus_version": version,
        "source_sha256": "a" * 64,
        "chunk_sha256": hashlib.sha256("Screen adults for high blood pressure.".encode()).hexdigest(),
        "href": "https://example.test/hypertension",
        "retrieved_at": "2026-09-21T00:00:01Z",
    }


def test_guideline_source_review_reopens_the_active_exact_corpus_chunk() -> None:
    resolver = GuidelineSourceReviewResolver(
        lambda: _corpus(),
        now=lambda: datetime(2026, 9, 22, tzinfo=timezone.utc),
    )

    resolved = asyncio.run(resolver.resolve("conversation", "turn", _citation(), "corr-source"))

    assert resolved is not None
    assert resolved.source["source_type"] == "guideline"
    assert resolved.source["exact_text"] == "Screen adults for high blood pressure."
    assert resolved.citation.root.source_type == "guideline"


def test_guideline_source_review_fails_closed_when_the_checkpointed_quote_or_corpus_is_stale() -> None:
    resolver = GuidelineSourceReviewResolver(
        lambda: _corpus(),
        now=lambda: datetime(2026, 9, 22, tzinfo=timezone.utc),
    )

    changed_quote = asyncio.run(resolver.resolve("conversation", "turn", _citation(quote="Changed text"), "corr-source"))
    changed_corpus = asyncio.run(resolver.resolve("conversation", "turn", _citation(version="retired-corpus"), "corr-source"))

    assert changed_quote is None
    assert changed_corpus is None


def test_guideline_source_review_is_not_configured_when_the_capability_is_disabled() -> None:
    class Settings:
        guideline_enabled = False

    assert configured_guideline_source_resolver(Settings()) is None
