"""Fail-closed release seam for bounded guideline evidence (Slice 3D).

The chart gateway authenticates and rechecks the live chart before it mints a
delegation.  This module intentionally receives only that opaque delegation and
finite retrieval selectors: no patient identity or chart text can cross into
the local retrieval worker.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from threading import Lock

from .contracts import (
    ACTIVE_CORPUS_VERSION,
    EvidenceQuery,
    EvidenceWorkerResult,
    GuidelineCitation,
    GuidelineEvidenceClaim,
    GuidelineEvidenceRequest,
    GuidelineEvidenceResponse,
    GuidelineExcerpt,
    GuidelineExcerptFacts,
    GuidelineRetrievalLimitation,
    GuidelineRetrievalLimitationCode,
    GuidelineSection,
    GuidelineSourceResponse,
)
from .evidence_retriever_worker import EvidenceRetrieverWorker

MAX_CORPUS_AGE_DAYS = 14


class CorpusStale(ValueError):
    """The active pointer is intact but cannot authorize new evidence."""


class GuidelineReleaseService:
    """Builds resolver-authored exact claims and reopens saved evidence safely."""

    def __init__(self, worker: EvidenceRetrieverWorker, corpus_root: Path, *, now=lambda: datetime.now(timezone.utc)) -> None:
        self.worker = worker
        self.corpus_root = corpus_root
        self.now = now
        self._evidence: dict[tuple[str, str], dict[str, GuidelineExcerpt]] = {}
        self._lock = Lock()

    def _active_rows(self) -> dict[str, dict]:
        """Reload immutable approved artifacts; never use a stale in-memory copy."""
        active = json.loads((self.corpus_root / "active.json").read_text())
        manifest = json.loads((self.corpus_root / "approved_manifest.json").read_text())
        if active.get("corpus_version") != ACTIVE_CORPUS_VERSION or manifest.get("corpus_version") != ACTIVE_CORPUS_VERSION:
            raise ValueError("active corpus version mismatch")
        approved = datetime.fromisoformat(str(active["approved_at"]).replace("Z", "+00:00"))
        if approved.tzinfo is None or (self.now() - approved).days > MAX_CORPUS_AGE_DAYS:
            raise CorpusStale("active corpus is stale")
        rows = {}
        for line in (self.corpus_root / "artifacts" / "chunks.jsonl").read_text().splitlines():
            row = json.loads(line)
            sid = f"guideline:{row['corpus_version']}:{row['document_id']}:{row['chunk_id']}"
            if row.get("corpus_version") != ACTIVE_CORPUS_VERSION or sha256(row["exact_text"].encode()).hexdigest() != row.get("chunk_sha256"):
                raise ValueError("active chunk integrity mismatch")
            rows[sid] = row
        if not rows:
            raise ValueError("active corpus has no chunks")
        return rows

    def _citation(self, excerpt: GuidelineExcerpt, claim_id: str, index: int) -> GuidelineCitation:
        # The exact chunk is bounded to 4k; citation quotes are capped by the
        # normative contract.  A prefix is still an exact byte sequence.
        quote = excerpt.exact_text[:500]
        return GuidelineCitation(
            citation_id=f"ct{index}", claim_id=claim_id, source_id=excerpt.source_id,
            title=excerpt.title, page_or_section=GuidelineSection(section_path=excerpt.section_path, chunk_ordinal=excerpt.chunk_ordinal),
            field_or_chunk_id=excerpt.chunk_id, quote_or_value={"kind": "exact_quote", "quote": quote},
            publisher=excerpt.publisher, jurisdiction=excerpt.jurisdiction, canonical_url=excerpt.canonical_url,
            publication_date=excerpt.publication_date, topic=excerpt.topic, corpus_version=excerpt.corpus_version,
            source_sha256=excerpt.source_sha256, chunk_sha256=excerpt.chunk_sha256,
            href=excerpt.canonical_url, retrieved_at=self.now(),
        )

    def _verify_claim(self, claim: GuidelineEvidenceClaim, excerpt: GuidelineExcerpt, rows: dict[str, dict]) -> bool:
        """Deterministic verifier: no model output or rank may authorize display."""
        row = rows.get(claim.source_ids[0])
        citation = claim.citations[0]
        return bool(row and claim.source_ids[0] == excerpt.source_id and citation.source_id == excerpt.source_id
            and citation.field_or_chunk_id == excerpt.chunk_id and citation.page_or_section.section_path == excerpt.section_path
            and citation.page_or_section.chunk_ordinal == excerpt.chunk_ordinal
            and citation.quote_or_value.quote in excerpt.exact_text
            and citation.source_sha256 == excerpt.source_sha256 == row["source_sha256"]
            and citation.chunk_sha256 == excerpt.chunk_sha256 == row["chunk_sha256"]
            and citation.corpus_version == excerpt.corpus_version == ACTIVE_CORPUS_VERSION
            and claim.text == f'{excerpt.publisher}: "{citation.quote_or_value.quote}"')

    def invoke(self, conversation_id: str, turn_id: str, correlation_id: str, request: GuidelineEvidenceRequest) -> GuidelineEvidenceResponse:
        query = EvidenceQuery(
            concepts=request.concepts, topic_filter=request.topic_filter, requested_top_k=request.requested_top_k,
            correlation_id=correlation_id, handoff_id=secrets.token_hex(16), deadline_ms=request.deadline_ms,
        )
        result: EvidenceWorkerResult = self.worker.invoke(query)
        if result.status.value != "completed":
            return GuidelineEvidenceResponse(turn_id=turn_id, correlation_id=correlation_id, status="limited", claims=[],
                limitations=[result.limitation or GuidelineRetrievalLimitation(code=GuidelineRetrievalLimitationCode.corpus_unavailable, detail="Guideline retrieval is temporarily unavailable.")], worker=result)
        try:
            rows = self._active_rows()
        except CorpusStale:
            return GuidelineEvidenceResponse(turn_id=turn_id, correlation_id=correlation_id, status="limited", claims=[],
                limitations=[GuidelineRetrievalLimitation(code=GuidelineRetrievalLimitationCode.corpus_stale, detail="Approved guideline evidence is stale.")], worker=result)
        except Exception:
            return GuidelineEvidenceResponse(turn_id=turn_id, correlation_id=correlation_id, status="limited", claims=[],
                limitations=[GuidelineRetrievalLimitation(code=GuidelineRetrievalLimitationCode.corpus_unavailable, detail="Approved guideline evidence is unavailable.")], worker=result)
        claims: list[GuidelineEvidenceClaim] = []
        valid: dict[str, GuidelineExcerpt] = {}
        for index, excerpt in enumerate(result.excerpts, start=1):
            claim_id = f"c{index}"
            citation = self._citation(excerpt, claim_id, index)
            claim = GuidelineEvidenceClaim(id=claim_id, text=f'{excerpt.publisher}: "{citation.quote_or_value.quote}"',
                facts=GuidelineExcerptFacts(quote=citation.quote_or_value.quote, publisher=excerpt.publisher, title=excerpt.title, topic=excerpt.topic, section_path=excerpt.section_path),
                source_ids=[excerpt.source_id], citations=[citation])
            if self._verify_claim(claim, excerpt, rows):
                claims.append(claim)
                valid[excerpt.source_id] = excerpt
        if valid:
            with self._lock:
                self._evidence[(conversation_id, turn_id)] = valid
        limitation = [] if claims else [GuidelineRetrievalLimitation(code=GuidelineRetrievalLimitationCode.corpus_unavailable, detail="Guideline evidence could not be verified against the active corpus.")]
        return GuidelineEvidenceResponse(turn_id=turn_id, correlation_id=correlation_id, status="complete" if claims else "limited", claims=claims, limitations=limitation, worker=result)

    def reverify(self, response: GuidelineEvidenceResponse, correlation_id: str) -> GuidelineEvidenceResponse:
        """Re-resolve response claims from the current approved corpus.

        A worker result and the service's in-memory click cache are not source
        authority.  The final display boundary calls this after its fresh chart
        authorization check, so an activation, hash, or correlation change
        withholds the affected lane instead of rendering a stale excerpt.
        """
        if response.correlation_id != correlation_id:
            return self._limited_response(response, correlation_id, GuidelineRetrievalLimitationCode.malformed_output)
        try:
            rows = self._active_rows()
        except CorpusStale:
            return self._limited_response(response, correlation_id, GuidelineRetrievalLimitationCode.corpus_stale)
        except Exception:
            return self._limited_response(response, correlation_id, GuidelineRetrievalLimitationCode.corpus_unavailable)
        claims = []
        excerpt_fields = GuidelineExcerpt.model_fields
        for claim in response.claims:
            row = rows.get(claim.source_ids[0])
            if row is None:
                continue
            try:
                excerpt = GuidelineExcerpt.model_validate({
                    key: value for key, value in row.items() if key in excerpt_fields
                } | {"source_id": claim.source_ids[0]})
            except Exception:
                continue
            if self._verify_claim(claim, excerpt, rows):
                claims.append(claim)
        if not claims:
            return self._limited_response(response, correlation_id, GuidelineRetrievalLimitationCode.corpus_unavailable)
        return response.model_copy(update={"claims": claims, "status": "complete", "limitations": []})

    @staticmethod
    def _limited_response(
        response: GuidelineEvidenceResponse,
        correlation_id: str,
        code: GuidelineRetrievalLimitationCode,
    ) -> GuidelineEvidenceResponse:
        details = {
            GuidelineRetrievalLimitationCode.authorization_changed: "Guideline evidence is unavailable for this chart.",
            GuidelineRetrievalLimitationCode.corpus_stale: "Approved guideline evidence is stale.",
        }
        return response.model_copy(update={
            "correlation_id": correlation_id,
            "status": "limited",
            "claims": [],
            "limitations": [GuidelineRetrievalLimitation(
                code=code,
                detail=details.get(code, "Guideline evidence could not be verified against the active corpus."),
            )],
        })

    def resolve(self, conversation_id: str, evidence_turn_id: str, source_id: str) -> GuidelineSourceResponse | None:
        with self._lock:
            excerpt = self._evidence.get((conversation_id, evidence_turn_id), {}).get(source_id)
        if excerpt is None:
            return None
        try:
            row = self._active_rows().get(source_id)
        except Exception:
            return None
        if row is None or row.get("chunk_sha256") != excerpt.chunk_sha256 or row.get("source_sha256") != excerpt.source_sha256:
            return None
        return GuidelineSourceResponse(source_id=excerpt.source_id, title=excerpt.title, publisher=excerpt.publisher,
            section_path=excerpt.section_path, exact_text=excerpt.exact_text, canonical_url=excerpt.canonical_url,
            source_sha256=excerpt.source_sha256, chunk_sha256=excerpt.chunk_sha256)
