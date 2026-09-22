"""Bounded, local-only worker seam for UC-06 guideline evidence.

This is intentionally not a route, API endpoint, resolver, or supervisor.
The authenticated application/supervisor added in a later slice must validate
its own authorization before constructing an :class:`EvidenceQuery`; this
worker can only run that already-bounded contract against immutable local
artifacts.  It has no gateway, database, filesystem-write, or network client.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from .contracts.guidelines import (
    ACTIVE_CORPUS_VERSION,
    EvidenceQuery,
    EvidenceWorkerResult,
    EvidenceWorkerStatus,
    EvidenceWorkerTimings,
    GuidelineExcerpt,
    GuidelineRetrievalLimitation,
    GuidelineRetrievalLimitationCode,
)
from .guideline_retriever import RERANKER_REVISION, RetrievalNoEvidence, RetrievalUnavailable
from .metrics import Metrics, metrics
from .telemetry import evidence_worker_observation


log = logging.getLogger("copilot.evidence_retriever")
WORKER_REVISION = "evidence-retriever-local-v1"
MAX_RETRIES_PER_HANDOFF = 0
_CORRELATION = re.compile(r"^[A-Za-z0-9\-._]{8,64}$")
_HANDOFF = re.compile(r"^[a-f0-9]{32}$")


class RetrievalEngine(Protocol):
    """The deliberately small seam supplied by Slice 3B's local engine."""

    artifact: dict[str, Any]
    manifest: dict[str, Any]
    artifact_dir: Path
    chunks: dict[str, dict[str, Any]]

    def retrieve(self, query: EvidenceQuery) -> Any: ...


class EvidenceRetrieverWorker:
    """Execute exactly one validated handoff and commit one terminal outcome.

    Cancellation/staleness updates are checked before dispatch and again while
    atomically committing.  A retrieval that finishes after either signal is
    therefore converted to a typed limitation rather than leaking late
    evidence.  The worker deliberately makes no retry: retry policy belongs to
    the later supervisor and ADR-0010 forbids in-turn retrieval retry.
    """

    def __init__(self, engine: RetrievalEngine, *, metric_sink: Metrics = metrics, monotonic: Any = time.monotonic) -> None:
        self.engine = engine
        self.metric_sink = metric_sink
        self.monotonic = monotonic
        self._lock = threading.Lock()
        self._state: dict[str, str] = {}
        self._artifact_sha = self._artifact_manifest_sha256()
        dense = engine.manifest.get("dense_model", {})
        revision = dense.get("revision")
        if not isinstance(revision, str) or not re.fullmatch(r"[a-f0-9]{40}", revision):
            raise ValueError("local retrieval engine has no pinned embedding revision")
        self._embedding_revision = revision

    def invoke(self, payload: object) -> EvidenceWorkerResult:
        """Validate an untrusted transport payload before the retrieval call.

        The generic rejection contains no rejected field value.  It preserves
        only independently syntax-checked correlation/handoff values so an
        authenticated caller can reconcile its own failed dispatch.
        """
        try:
            query = EvidenceQuery.model_validate(payload)
        except ValidationError:
            correlation_id, handoff_id = self._safe_ids(payload)
            return self._terminal(
                correlation_id, handoff_id, EvidenceWorkerStatus.limited,
                GuidelineRetrievalLimitationCode.query_rejected,
                "The guideline request was not permitted.", 0, 0, self._zero_timings(), "unknown",
            )
        return self.run(query)

    def run(self, query: EvidenceQuery) -> EvidenceWorkerResult:
        """Run one already-validated contract; never accepts free-text input."""
        if not isinstance(query, EvidenceQuery):
            # The public `invoke` path turns malformed transport input into a
            # typed limitation.  Direct callers must not bypass that boundary.
            raise TypeError("evidence retriever requires validated EvidenceQuery")
        with self._lock:
            prior = self._state.get(query.handoff_id)
            duplicate = prior not in {None, "canceled", "stale"}
            if prior is None:
                self._state[query.handoff_id] = "active"
        if duplicate:
            return self._terminal(
                query.correlation_id, query.handoff_id, EvidenceWorkerStatus.limited,
                GuidelineRetrievalLimitationCode.duplicate_handoff,
                "This guideline handoff was already terminal.", 0, 0, self._zero_timings(), self._topic(query), commit_state=False,
            )
        started = self.monotonic()
        return self._execute(query, started)

    def cancel(self, correlation_id: str, handoff_id: str) -> None:
        """Cooperatively prevent a current or future handoff from succeeding."""
        self._set_control(correlation_id, handoff_id, "canceled")

    def mark_stale(self, correlation_id: str, handoff_id: str) -> None:
        """Mark a handoff stale when its authenticated parent is no longer live."""
        self._set_control(correlation_id, handoff_id, "stale")

    def _execute(self, query: EvidenceQuery, started: float) -> EvidenceWorkerResult:
        preempted = self._preempted(query)
        if preempted is not None:
            return self._terminal(query.correlation_id, query.handoff_id, *preempted, 0, 0, self._zero_timings(), self._topic(query))
        with evidence_worker_observation(query.correlation_id) as span:
            try:
                raw = self.engine.retrieve(query)
                raw_total = getattr(getattr(raw, "measurement", None), "total_ms", None)
                if not isinstance(raw_total, (int, float)) or raw_total < 0:
                    raise ValueError("engine timing is malformed")
                if raw_total > query.deadline_ms:
                    return self._commit(query, EvidenceWorkerStatus.limited, GuidelineRetrievalLimitationCode.deadline_exceeded, "Guideline retrieval reached its deadline.", 0, 0, self._elapsed_timings(started))
                timings = self._timings(raw)
                elapsed = (self.monotonic() - started) * 1000
                if elapsed > query.deadline_ms or timings.total_ms > query.deadline_ms:
                    return self._commit(query, EvidenceWorkerStatus.limited, GuidelineRetrievalLimitationCode.deadline_exceeded, "Guideline retrieval reached its deadline.", 0, 0, timings)
                excerpts = self._validated_excerpts(raw, query)
                if not excerpts:
                    return self._commit(query, EvidenceWorkerStatus.limited, GuidelineRetrievalLimitationCode.no_evidence, "No approved guideline evidence was found.", 0, 0, timings)
                candidates = self._candidate_count(raw)
                return self._commit(query, EvidenceWorkerStatus.completed, None, None, candidates, len(excerpts), timings, excerpts)
            except RetrievalNoEvidence:
                return self._commit(query, EvidenceWorkerStatus.limited, GuidelineRetrievalLimitationCode.no_evidence, "No approved guideline evidence was found.", 0, 0, self._elapsed_timings(started))
            except RetrievalUnavailable:
                code = GuidelineRetrievalLimitationCode.deadline_exceeded if self._elapsed_ms(started) > query.deadline_ms else GuidelineRetrievalLimitationCode.corpus_unavailable
                detail = "Guideline retrieval reached its deadline." if code is GuidelineRetrievalLimitationCode.deadline_exceeded else "Guideline retrieval is temporarily unavailable."
                return self._commit(query, EvidenceWorkerStatus.limited, code, detail, 0, 0, self._elapsed_timings(started))
            except Exception:
                # This includes malformed engine return objects.  No exception
                # text, model output, artifact path, or excerpt reaches a user.
                return self._commit(query, EvidenceWorkerStatus.limited, GuidelineRetrievalLimitationCode.malformed_output, "Guideline retrieval returned an invalid result.", 0, 0, self._elapsed_timings(started))

    def _commit(self, query: EvidenceQuery, status: EvidenceWorkerStatus, code: GuidelineRetrievalLimitationCode | None, detail: str | None, candidates: int, hits: int, timings: EvidenceWorkerTimings, excerpts: list[GuidelineExcerpt] | None = None) -> EvidenceWorkerResult:
        preempted = self._preempted(query)
        if preempted is not None:
            status, code, detail = preempted
            candidates, hits, excerpts = 0, 0, None
        assert (code is None) == (status is EvidenceWorkerStatus.completed)
        return self._terminal(query.correlation_id, query.handoff_id, status, code, detail, candidates, hits, timings, self._topic(query), excerpts)

    def _terminal(self, correlation_id: str, handoff_id: str, status: EvidenceWorkerStatus, code: GuidelineRetrievalLimitationCode | None, detail: str | None, candidates: int, hits: int, timings: EvidenceWorkerTimings, topic: str, excerpts: list[GuidelineExcerpt] | None = None, commit_state: bool = True) -> EvidenceWorkerResult:
        limitation = None if code is None else GuidelineRetrievalLimitation(code=code, detail=detail or "Guideline retrieval is unavailable.")
        result = EvidenceWorkerResult(
            worker_revision=WORKER_REVISION, correlation_id=correlation_id, handoff_id=handoff_id,
            status=status, artifact_manifest_sha256=self._artifact_sha, embedding_model_revision=self._embedding_revision,
            reranker_model_revision=RERANKER_REVISION, candidate_count=candidates, hit_count=hits, timings=timings,
            excerpts=excerpts or [], limitation=limitation,
        )
        if commit_state:
            with self._lock:
                self._state[handoff_id] = "terminal"
        limitation_code = limitation.code.value if limitation else "none"
        self.metric_sink.evidence_retrieval("guideline_evidence", topic, result.status.value, limitation_code, result.timings.total_ms)
        metadata = {
            "status": result.status.value, "correlation_id": result.correlation_id, "handoff_id": result.handoff_id, "contract_version": result.contract_version,
            "model_version": result.worker_revision, "worker": "evidence_retriever", "intent": "guideline_evidence",
            "topic": topic, "limitation": limitation_code, "candidate_count": result.candidate_count,
            "hit_count": result.hit_count, "retrieval_hit_count": result.hit_count, "artifact_revision": result.artifact_manifest_sha256,
            "timings_ms": result.timings.model_dump(), "eval_outcome": "not_run",
        }
        with evidence_worker_observation(result.correlation_id) as span:
            try:
                span.update(metadata=metadata)
            except Exception:  # telemetry cannot change the worker outcome
                pass
        log.info("evidence retriever terminal", extra={"component": "evidence_retriever", "correlation_id": result.correlation_id, "handoff_id": result.handoff_id, "worker": "evidence_retriever", "intent": "guideline_evidence", "topic": topic, "status": result.status.value, "limitation": limitation_code, "candidate_count": result.candidate_count, "hit_count": result.hit_count, "artifact_revision": result.artifact_manifest_sha256, "model_revision": result.worker_revision, "duration_ms": result.timings.total_ms})
        return result

    def _preempted(self, query: EvidenceQuery) -> tuple[EvidenceWorkerStatus, GuidelineRetrievalLimitationCode, str] | None:
        with self._lock:
            state = self._state.get(query.handoff_id)
        if state == "canceled":
            return (EvidenceWorkerStatus.canceled, GuidelineRetrievalLimitationCode.canceled, "Guideline retrieval was canceled.")
        if state == "stale":
            return (EvidenceWorkerStatus.limited, GuidelineRetrievalLimitationCode.stale_handoff, "The guideline handoff is no longer current.")
        return None

    def _set_control(self, correlation_id: str, handoff_id: str, state: str) -> None:
        if not _CORRELATION.fullmatch(correlation_id) or not _HANDOFF.fullmatch(handoff_id):
            return
        with self._lock:
            if self._state.get(handoff_id) != "terminal":
                self._state[handoff_id] = state

    def _validated_excerpts(self, raw: Any, query: EvidenceQuery) -> list[GuidelineExcerpt]:
        source = getattr(raw, "excerpts", None)
        if not isinstance(source, (tuple, list)) or not source or len(source) > query.requested_top_k:
            raise ValueError("engine excerpts are malformed")
        excerpts = [GuidelineExcerpt.model_validate(item) for item in source]
        if len({item.chunk_id for item in excerpts}) != len(excerpts):
            raise ValueError("engine repeated an excerpt")
        for excerpt in excerpts:
            row = self.engine.chunks.get(excerpt.chunk_id)
            if row is None or excerpt.corpus_version != ACTIVE_CORPUS_VERSION or excerpt.topic.value not in {topic.value for topic in query.concepts}:
                raise ValueError("engine excerpt is outside the immutable request scope")
            for field in ("exact_text", "chunk_sha256", "source_sha256", "document_id", "chunk_ordinal", "section_path", "publisher", "title", "jurisdiction", "publication_date"):
                if getattr(excerpt, field) != row[field]:
                    raise ValueError("engine excerpt does not match active corpus")
        return excerpts

    def _timings(self, raw: Any) -> EvidenceWorkerTimings:
        measurement = getattr(raw, "measurement", None)
        return EvidenceWorkerTimings.model_validate({name: getattr(measurement, name) for name in EvidenceWorkerTimings.model_fields})

    def _candidate_count(self, raw: Any) -> int:
        candidates = getattr(raw, "candidates", None)
        if not isinstance(candidates, (tuple, list)) or len(candidates) > 40:
            raise ValueError("engine candidates are malformed")
        return len(candidates)

    def _elapsed_ms(self, started: float) -> float:
        return max(0.0, (self.monotonic() - started) * 1000)

    def _elapsed_timings(self, started: float) -> EvidenceWorkerTimings:
        return EvidenceWorkerTimings(sparse_ms=0, dense_ms=0, fusion_ms=0, rerank_ms=0, total_ms=min(2000, self._elapsed_ms(started)))

    @staticmethod
    def _zero_timings() -> EvidenceWorkerTimings:
        return EvidenceWorkerTimings(sparse_ms=0, dense_ms=0, fusion_ms=0, rerank_ms=0, total_ms=0)

    def _artifact_manifest_sha256(self) -> str:
        # The engine has already validated the pointer/hash before this worker
        # starts.  Read the immutable manifest only to report its revision.
        import hashlib

        return hashlib.sha256((self.engine.artifact_dir / "artifact-manifest.json").read_bytes()).hexdigest()

    @staticmethod
    def _topic(query: EvidenceQuery) -> str:
        return query.topic_filter.value if query.topic_filter else (query.concepts[0].value if len(query.concepts) == 1 else "multiple")

    @staticmethod
    def _safe_ids(payload: object) -> tuple[str, str]:
        data = payload if isinstance(payload, dict) else {}
        correlation = data.get("correlation_id")
        handoff = data.get("handoff_id")
        return (
            correlation if isinstance(correlation, str) and _CORRELATION.fullmatch(correlation) else "invalid-request",
            handoff if isinstance(handoff, str) and _HANDOFF.fullmatch(handoff) else "0" * 32,
        )
