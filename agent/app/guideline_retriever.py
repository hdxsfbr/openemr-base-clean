"""Bounded local guideline retrieval (ADR-0010).

The coordinator owns policy, fusion, integrity, freshness, deadlines, and the
returned contract. Sparse, dense, and reranking engines are narrow adapters so
the production ONNX/FAISS implementations can be tested at their boundary.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import threading
import time
from concurrent.futures import ALL_COMPLETED, Executor, Future, ThreadPoolExecutor, TimeoutError as FutureTimeout, wait
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Protocol

from pydantic import Field, StringConstraints, model_validator
from typing_extensions import Annotated

from .contracts.common import StrictModel
from .contracts.week2 import (
    AbsoluteHttpsUrl,
    DateTime,
    RegistrySlug,
    Sha256,
    StageTiming,
    VersionedReference,
    WorkerHandoffRequest,
    WorkerHandoffResult,
)

RRF_K = 60
CANDIDATES_PER_LEG = 20
RETURN_LIMIT = 5
DEADLINE_SECONDS = 2.0
MAX_CORPUS_AGE = timedelta(days=14)
BGE_REPO = "BAAI/bge-small-en-v1.5"
BGE_REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
BGE_FILE = "onnx/model.onnx"
BGE_SHA256 = "828e1496d7fabb79cfa4dcd84fa38625c0d3d21da474a00f08db0f559940cf35"
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
RERANKER_REPO = "cross-encoder/ms-marco-MiniLM-L6-v2"
RERANKER_REVISION = "233902d25c440f23af6f7d6e94d2946bac0bee0a"
RERANKER_FILE = "onnx/model_quint8_avx2.onnx"
RERANKER_SHA256 = "c80a8b34256ea453093d612e3ac48d3d965a0c0a48c7906709af8b8e28461bf9"
ABSTENTION_THRESHOLD = -2.960404384881258


class EvidenceQuery(StrictModel):
    question: str = Field(min_length=1, max_length=500)
    concepts: list[Annotated[str, StringConstraints(min_length=1, max_length=100)]] = Field(min_length=1, max_length=12)
    intent: Literal["guideline_evidence"]
    active_corpus_version: RegistrySlug
    topic_filters: tuple[RegistrySlug, ...] = Field(default=(), max_length=8)
    population_filters: tuple[Annotated[str, StringConstraints(min_length=1, max_length=100)], ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def reject_prohibited_intent(self) -> "EvidenceQuery":
        content = " ".join([self.question, *self.concepts, *self.population_filters])
        if re.search(
            r"\b(diagnos(?:e|is)|prescrib(?:e|ing|ed)?|"
            r"(?:insulin|drug|medication|antibiotic).{0,40}dos(?:e|ing|age)|"
            r"should (?:i|the patient)|recommend for (?:me|this patient)|"
            r"(?:what|which) (?:medication|drug|antibiotic)|"
            r"how should .{0,120} (?:be )?treated)\b",
            content,
            re.IGNORECASE,
        ):
            raise ValueError("guideline query cannot request diagnosis, treatment, dosing, or applicability")
        if re.search(
            r"\b(?:mrn|medical record (?:number|id)|ssn|social security|date of birth|dob)\s*[:#-]?\s*[a-z0-9/-]+",
            content,
            re.IGNORECASE,
        ):
            raise ValueError("guideline query cannot contain patient identifiers")
        if re.search(r"\b(?:ignore|override|bypass)\b.{0,40}\b(?:instruction|prompt|policy|rule)s?\b", content, re.IGNORECASE):
            raise ValueError("guideline query cannot contain instruction-override text")
        if len(set(self.topic_filters)) != len(self.topic_filters):
            raise ValueError("topic filters must be unique")
        return self


class GuidelineChunk(StrictModel):
    chunk_id: RegistrySlug
    document_id: RegistrySlug
    corpus_version: RegistrySlug
    publisher: str = Field(min_length=1, max_length=160)
    jurisdiction: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=300)
    canonical_url: AbsoluteHttpsUrl
    topic: RegistrySlug
    section_path: list[Annotated[str, StringConstraints(min_length=1, max_length=200)]] = Field(min_length=1, max_length=8)
    chunk_ordinal: int = Field(ge=0)
    exact_text: str = Field(min_length=1, max_length=4_000)
    source_sha256: Sha256
    chunk_sha256: Sha256

    @model_validator(mode="after")
    def verify_chunk_identity(self) -> "GuidelineChunk":
        if hashlib.sha256(self.exact_text.encode()).hexdigest() != self.chunk_sha256:
            raise ValueError("chunk hash does not match exact text")
        return self


class RetrievedGuidelineChunk(GuidelineChunk):
    source_id: str = Field(pattern=r"^guideline:[a-z0-9][a-z0-9._-]{0,63}:[a-z0-9][a-z0-9._-]{0,63}:[a-z0-9][a-z0-9._-]{0,63}$")
    sparse_rank: int | None = Field(default=None, ge=1, le=CANDIDATES_PER_LEG)
    dense_rank: int | None = Field(default=None, ge=1, le=CANDIDATES_PER_LEG)
    rrf_score: float = Field(gt=0)
    final_rank: int = Field(ge=1, le=RETURN_LIMIT)
    reranker_score: float
    embedding_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    reranker_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    index_build_id: RegistrySlug
    retrieved_at: DateTime
    corpus_retrieved_at: DateTime
    approved_at: DateTime


class RetrievalLimitation(StrictModel):
    code: Literal[
        "guideline_no_evidence",
        "guideline_stale",
        "guideline_wrong_corpus",
        "guideline_integrity_failure",
        "guideline_timeout",
        "guideline_retrieval_unavailable",
    ]
    retryable: bool
    detail: str = Field(min_length=1, max_length=200)


class EvidenceResult(StrictModel):
    status: Literal["completed", "limited", "unavailable"]
    corpus_version: RegistrySlug
    chunks: list[RetrievedGuidelineChunk] = Field(max_length=RETURN_LIMIT)
    limitation: RetrievalLimitation | None = None

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> "EvidenceResult":
        if self.status == "completed" and (not self.chunks or self.limitation is not None):
            raise ValueError("completed retrieval requires chunks and no limitation")
        if self.status != "completed" and (self.chunks or self.limitation is None):
            raise ValueError("limited retrieval requires one limitation and no chunks")
        return self


@dataclass(frozen=True)
class FrozenCorpus:
    version: str
    retrieved_at: str
    approved_at: str
    chunks: list[GuidelineChunk]


def load_frozen_corpus(
    *,
    corpus_path: Path,
    manifest_path: Path,
    expected_corpus_sha256: str,
    expected_manifest_sha256: str,
) -> FrozenCorpus:
    """Load only the reviewed immutable corpus identified by exact file hashes."""

    _require_file_hash(corpus_path, expected_corpus_sha256, "corpus")
    _require_file_hash(manifest_path, expected_manifest_sha256, "manifest")
    manifest = json.loads(manifest_path.read_text())
    rows = [json.loads(line) for line in corpus_path.read_text().splitlines() if line.strip()]
    by_topic: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        by_topic.setdefault(str(row["topic"]), []).append(row)
    source_hashes = {
        topic: hashlib.sha256("\n".join(str(row["text"]) for row in topic_rows).encode()).hexdigest()
        for topic, topic_rows in by_topic.items()
    }
    source_titles = {source["topic"]: source["title"] for source in manifest["sources"]}
    source_urls = {source["topic"]: source["url"] for source in manifest["sources"]}
    chunks = [
        GuidelineChunk.model_validate({
            "chunk_id": row["chunk_id"],
            "document_id": row["topic"],
            "corpus_version": row["corpus_version"],
            "publisher": row["publisher"],
            "jurisdiction": manifest["jurisdiction"],
            "title": source_titles[row["topic"]],
            "canonical_url": source_urls[row["topic"]],
            "topic": row["topic"],
            "section_path": [part.strip() for part in row["section_heading_path"].split(" > ")],
            "chunk_ordinal": int(row["chunk_id"].rsplit("-", 1)[1]),
            "exact_text": row["text"],
            "source_sha256": source_hashes[row["topic"]],
            "chunk_sha256": row["content_sha256"],
        })
        for row in rows
    ]
    if len({chunk.chunk_id for chunk in chunks}) != len(chunks):
        raise ValueError("frozen corpus contains duplicate chunk IDs")
    if any(chunk.corpus_version != manifest["corpus_version"] for chunk in chunks):
        raise ValueError("frozen corpus rows do not match the manifest version")
    retrieved_at = f"{manifest['retrieved_at']}T00:00:00Z"
    return FrozenCorpus(
        version=manifest["corpus_version"],
        retrieved_at=retrieved_at,
        approved_at=retrieved_at,
        chunks=chunks,
    )


def _require_file_hash(path: Path, expected: str, label: str) -> None:
    observed = hashlib.sha256(path.read_bytes()).hexdigest()
    if observed != expected:
        raise ValueError(f"{label} integrity mismatch")


class SearchPort(Protocol):
    def search(self, query: str, topics: tuple[str, ...], limit: int) -> list[str]: ...


class RerankerPort(Protocol):
    def score(self, query: str, chunks: list[GuidelineChunk]) -> list[float]: ...


class EvidenceStorePort(Protocol):
    """Protected content store; only references cross the worker handoff."""

    def load_query(self, reference: VersionedReference) -> EvidenceQuery: ...

    def save_result(self, handoff_id: str, result: EvidenceResult) -> VersionedReference: ...


class SQLiteFtsSearch:
    """Local FTS5/BM25 sparse leg over one immutable corpus version."""

    def __init__(self, chunks: list[GuidelineChunk]) -> None:
        self._db = sqlite3.connect(":memory:", check_same_thread=False)
        self._lock = threading.RLock()
        self._db.execute("CREATE VIRTUAL TABLE chunks USING fts5(chunk_id UNINDEXED, topic UNINDEXED, text)")
        self._db.executemany(
            "INSERT INTO chunks(chunk_id, topic, text) VALUES (?, ?, ?)",
            [(chunk.chunk_id, chunk.topic, chunk.exact_text) for chunk in chunks],
        )
        self._db.commit()

    def search(self, query: str, topics: tuple[str, ...], limit: int) -> list[str]:
        terms = re.findall(r"[a-z0-9]+", query.lower())
        if not terms:
            return []
        expression = " OR ".join(f'"{term}"' for term in terms)
        bounded_limit = min(max(limit, 0), CANDIDATES_PER_LEG)
        sql = "SELECT chunk_id FROM chunks WHERE chunks MATCH ?"
        parameters: list[object] = [expression]
        if topics:
            sql += f" AND topic IN ({','.join('?' for _ in topics)})"
            parameters.extend(topics)
        sql += " ORDER BY bm25(chunks), chunk_id LIMIT ?"
        parameters.append(bounded_limit)
        with self._lock:
            rows = self._db.execute(sql, parameters).fetchall()
        return [str(row[0]) for row in rows]


class OnnxBgeFaissSearch:
    """Pinned BGE-small ONNX embeddings over an exact FAISS IndexFlatIP."""

    def __init__(self, chunks: list[GuidelineChunk], *, offline: bool) -> None:
        import faiss
        import numpy as np
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        common = {"repo_id": BGE_REPO, "revision": BGE_REVISION, "local_files_only": offline}
        tokenizer_path = hf_hub_download(filename="tokenizer.json", **common)
        model_path = Path(hf_hub_download(filename=BGE_FILE, **common))
        _require_file_hash(model_path, BGE_SHA256, "embedding model")
        self._tokenizer = Tokenizer.from_file(tokenizer_path)
        self._tokenizer.enable_truncation(max_length=384)
        self._tokenizer.enable_padding()
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        options.enable_cpu_mem_arena = False
        options.enable_mem_pattern = False
        self._session = ort.InferenceSession(str(model_path), sess_options=options, providers=["CPUExecutionProvider"])
        self._np = np
        self._ids = [chunk.chunk_id for chunk in chunks]
        self._topics = {chunk.chunk_id: chunk.topic for chunk in chunks}
        vectors = self._encode([chunk.exact_text for chunk in chunks])
        self._index = faiss.IndexFlatIP(vectors.shape[1])
        self._index.add(vectors)
        self._lock = threading.RLock()

    def _encode(self, texts: list[str], *, query: bool = False) -> object:
        np = self._np
        if query:
            texts = [BGE_QUERY_PREFIX + text for text in texts]
        vectors = []
        for start in range(0, len(texts), 8):
            encoded = self._tokenizer.encode_batch(texts[start : start + 8])
            feed = {
                "input_ids": np.asarray([item.ids for item in encoded], dtype=np.int64),
                "attention_mask": np.asarray([item.attention_mask for item in encoded], dtype=np.int64),
                "token_type_ids": np.asarray([item.type_ids for item in encoded], dtype=np.int64),
            }
            vectors.append(self._session.run(None, feed)[0][:, 0, :])
        matrix = np.vstack(vectors).astype(np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        return matrix / np.clip(norms, 1e-12, None)

    def search(self, query: str, topics: tuple[str, ...], limit: int) -> list[str]:
        vector = self._encode([query], query=True)
        with self._lock:
            _, indexes = self._index.search(vector, len(self._ids))
        ranked = [self._ids[index] for index in indexes[0] if index >= 0]
        if topics:
            ranked = [chunk_id for chunk_id in ranked if self._topics[chunk_id] in topics]
        return ranked[: min(max(limit, 0), CANDIDATES_PER_LEG)]


class OnnxMiniLmReranker:
    """Pinned local MiniLM cross-encoder used only after RRF fusion."""

    def __init__(self, *, offline: bool) -> None:
        import numpy as np
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        common = {"repo_id": RERANKER_REPO, "revision": RERANKER_REVISION, "local_files_only": offline}
        tokenizer_path = hf_hub_download(filename="tokenizer.json", **common)
        model_path = Path(hf_hub_download(filename=RERANKER_FILE, **common))
        _require_file_hash(model_path, RERANKER_SHA256, "reranker model")
        self._tokenizer = Tokenizer.from_file(tokenizer_path)
        self._tokenizer.enable_truncation(max_length=384)
        self._tokenizer.enable_padding()
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        options.enable_cpu_mem_arena = False
        options.enable_mem_pattern = False
        self._session = ort.InferenceSession(str(model_path), sess_options=options, providers=["CPUExecutionProvider"])
        self._np = np
        self._lock = threading.RLock()

    def score(self, query: str, chunks: list[GuidelineChunk]) -> list[float]:
        np = self._np
        scores: list[float] = []
        for start in range(0, len(chunks), 4):
            encoded = self._tokenizer.encode_batch(
                [(query, chunk.exact_text) for chunk in chunks[start : start + 4]]
            )
            feed = {
                "input_ids": np.asarray([item.ids for item in encoded], dtype=np.int64),
                "attention_mask": np.asarray([item.attention_mask for item in encoded], dtype=np.int64),
                "token_type_ids": np.asarray([item.type_ids for item in encoded], dtype=np.int64),
            }
            with self._lock:
                output = self._session.run(None, feed)[0]
            scores.extend(output.reshape(-1).astype(float).tolist())
        return scores


class BoundedGuidelineRetriever:
    def __init__(
        self,
        *,
        chunks: list[GuidelineChunk],
        active_corpus_version: str,
        corpus_retrieved_at: str,
        approved_at: str,
        sparse: SearchPort,
        dense: SearchPort,
        reranker: RerankerPort,
        abstention_threshold: float = ABSTENTION_THRESHOLD,
        monotonic=time.monotonic,
        executor: Executor | None = None,
    ) -> None:
        self._chunks = {chunk.chunk_id: chunk for chunk in chunks}
        if len(self._chunks) != len(chunks):
            raise ValueError("chunk IDs must be unique")
        if any(chunk.corpus_version != active_corpus_version for chunk in chunks):
            raise ValueError("every chunk must belong to the active corpus")
        self._active_corpus_version = active_corpus_version
        self._corpus_retrieved_at = _utc(corpus_retrieved_at)
        self._approved_at = _utc(approved_at)
        self._sparse = sparse
        self._dense = dense
        self._reranker = reranker
        self._abstention_threshold = abstention_threshold
        self._monotonic = monotonic
        self._executor = executor or ThreadPoolExecutor(max_workers=4, thread_name_prefix="guideline-retrieval")

    def retrieve(self, query: EvidenceQuery, *, now: str) -> EvidenceResult:
        if query.active_corpus_version != self._active_corpus_version:
            return self._limited("guideline_wrong_corpus", False, "The requested guideline corpus is not active.")
        observed_now = _utc(now)
        freshness_anchor = max(self._corpus_retrieved_at, self._approved_at)
        if observed_now - freshness_anchor > MAX_CORPUS_AGE:
            return self._limited("guideline_stale", False, "The approved guideline corpus is stale.")

        started = self._monotonic()
        try:
            search_futures = [
                self._executor.submit(search.search, query.question, query.topic_filters, CANDIDATES_PER_LEG)
                for search in (self._sparse, self._dense)
            ]
            done, pending = wait(
                search_futures,
                timeout=self._remaining(started),
                return_when=ALL_COMPLETED,
            )
            if pending:
                for future in pending:
                    future.cancel()
                return self._limited("guideline_timeout", True, "Guideline retrieval exceeded its deadline.")
            sparse_ids, dense_ids = [future.result() for future in search_futures]
            if any(chunk_id not in self._chunks for chunk_id in [*sparse_ids, *dense_ids]):
                return self._limited(
                    "guideline_integrity_failure",
                    False,
                    "A local guideline index returned an unknown chunk identity.",
                )
            fused = _rrf(sparse_ids, dense_ids)
            sparse_ranks = _rank_map(sparse_ids)
            dense_ranks = _rank_map(dense_ids)
            rrf_scores = {
                chunk_id: sum(
                    1.0 / (RRF_K + rank)
                    for rank in (sparse_ranks.get(chunk_id), dense_ranks.get(chunk_id))
                    if rank is not None
                )
                for chunk_id in fused
            }
            candidates = [self._chunks[chunk_id] for chunk_id in fused if chunk_id in self._chunks]
            if query.topic_filters:
                candidates = [chunk for chunk in candidates if chunk.topic in query.topic_filters]
            if not candidates:
                return self._limited("guideline_no_evidence", False, "No approved guideline evidence matched the request.")
            rerank_future: Future[list[float]] = self._executor.submit(self._reranker.score, query.question, candidates)
            try:
                scores = rerank_future.result(timeout=self._remaining(started))
            except FutureTimeout:
                rerank_future.cancel()
                return self._limited("guideline_timeout", True, "Guideline retrieval exceeded its deadline.")
            if len(scores) != len(candidates) or any(not math.isfinite(score) for score in scores):
                return self._limited("guideline_integrity_failure", False, "The local reranker returned an invalid result.")
            if not scores or max(scores) < self._abstention_threshold:
                return self._limited("guideline_no_evidence", False, "No approved guideline evidence matched the request.")
            if self._monotonic() - started >= DEADLINE_SECONDS:
                return self._limited("guideline_timeout", True, "Guideline retrieval exceeded its deadline.")
        except Exception:
            return self._limited("guideline_retrieval_unavailable", True, "Guideline retrieval is unavailable.")

        ranked = sorted(zip(scores, candidates, strict=True), key=lambda pair: (-pair[0], pair[1].chunk_id))[:RETURN_LIMIT]
        output = [
            RetrievedGuidelineChunk.model_validate({
                **chunk.model_dump(mode="json"),
                "source_id": f"guideline:{chunk.corpus_version}:{chunk.document_id}:{chunk.chunk_id}",
                "sparse_rank": sparse_ranks.get(chunk.chunk_id),
                "dense_rank": dense_ranks.get(chunk.chunk_id),
                "rrf_score": rrf_scores[chunk.chunk_id],
                "final_rank": rank,
                "reranker_score": score,
                "embedding_revision": BGE_REVISION,
                "reranker_revision": RERANKER_REVISION,
                "index_build_id": f"faiss-{self._active_corpus_version}-{BGE_SHA256[:12]}",
                "retrieved_at": _utc(now).isoformat().replace("+00:00", "Z"),
                "corpus_retrieved_at": self._corpus_retrieved_at.isoformat().replace("+00:00", "Z"),
                "approved_at": self._approved_at.isoformat().replace("+00:00", "Z"),
            })
            for rank, (score, chunk) in enumerate(ranked, start=1)
        ]
        return EvidenceResult(status="completed", corpus_version=self._active_corpus_version, chunks=output)

    def _remaining(self, started: float) -> float:
        return max(0.0, DEADLINE_SECONDS - (self._monotonic() - started))

    def _limited(self, code: str, retryable: bool, detail: str) -> EvidenceResult:
        return EvidenceResult(
            status="unavailable" if code in ("guideline_timeout", "guideline_retrieval_unavailable") else "limited",
            corpus_version=self._active_corpus_version,
            chunks=[],
            limitation=RetrievalLimitation(code=code, retryable=retryable, detail=detail),
        )


class EvidenceRetrieverWorker:
    """Execute one reference-only, no-retry evidence-retrieval handoff."""

    def __init__(
        self,
        *,
        retriever: BoundedGuidelineRetriever,
        store: EvidenceStorePort,
        monotonic=time.monotonic,
        capacity: threading.BoundedSemaphore | None = None,
    ) -> None:
        self._retriever = retriever
        self._store = store
        self._monotonic = monotonic
        self._capacity = capacity or threading.BoundedSemaphore(2)

    def run(self, handoff: WorkerHandoffRequest, *, now: str) -> WorkerHandoffResult:
        started = self._monotonic()
        query_refs = [reference for reference in handoff.input_refs if reference.kind == "evidence_query"]
        corpus_refs = [reference for reference in handoff.input_refs if reference.kind == "corpus"]
        if handoff.worker != "evidence_retriever" or handoff.attempt != 1:
            return self._terminal(handoff, started, "failed", "guideline_retry_forbidden", False)
        if _utc(handoff.deadline_at) <= _utc(now):
            return self._terminal(handoff, started, "unavailable", "guideline_timeout", True)
        if len(query_refs) != 1 or len(corpus_refs) != 1:
            return self._terminal(handoff, started, "failed", "guideline_handoff_invalid", False)
        if not self._capacity.acquire(blocking=False):
            return self._terminal(handoff, started, "unavailable", "guideline_capacity_exhausted", True)
        try:
            return self._run_with_capacity(handoff, query_refs[0], corpus_refs[0], now, started)
        finally:
            self._capacity.release()

    def _run_with_capacity(
        self,
        handoff: WorkerHandoffRequest,
        query_ref: VersionedReference,
        corpus_ref: VersionedReference,
        now: str,
        started: float,
    ) -> WorkerHandoffResult:
        try:
            query = self._store.load_query(query_ref)
        except Exception:
            return self._terminal(handoff, started, "unavailable", "guideline_query_unavailable", True)
        query_hash = hashlib.sha256(query.model_dump_json().encode()).hexdigest()
        if query_ref.integrity_sha256 != query_hash:
            return self._terminal(handoff, started, "failed", "guideline_integrity_failure", False)
        if corpus_ref.id != query.active_corpus_version or corpus_ref.version != query.active_corpus_version:
            return self._terminal(handoff, started, "failed", "guideline_wrong_corpus", False)

        evidence = self._retriever.retrieve(query, now=now)
        if evidence.status == "completed":
            try:
                output_ref = self._store.save_result(handoff.handoff_id, evidence)
            except Exception:
                return self._terminal(handoff, started, "unavailable", "guideline_result_store_unavailable", True)
            return self._result(handoff, started, "completed", [output_ref], [], False)
        limitation = evidence.limitation
        assert limitation is not None
        status = "unavailable" if evidence.status == "unavailable" else "partial"
        return self._result(handoff, started, status, [], [limitation.code], limitation.retryable)

    def _terminal(
        self,
        handoff: WorkerHandoffRequest,
        started: float,
        status: Literal["unavailable", "failed"],
        code: str,
        retryable: bool,
    ) -> WorkerHandoffResult:
        return self._result(handoff, started, status, [], [code], retryable)

    def _result(
        self,
        handoff: WorkerHandoffRequest,
        started: float,
        status: Literal["completed", "partial", "unavailable", "failed", "canceled"],
        output_refs: list[VersionedReference],
        limitation_codes: list[str],
        retryable: bool,
    ) -> WorkerHandoffResult:
        duration_ms = max(0, round((self._monotonic() - started) * 1000))
        stage_outcome = "completed" if status == "completed" else "limited" if status == "partial" else "failed"
        return WorkerHandoffResult.model_validate({
            "handoff_id": handoff.handoff_id,
            "correlation_id": handoff.correlation_id,
            "conversation_id": handoff.conversation_id,
            "turn_id": handoff.turn_id,
            "event_kind": handoff.event_kind,
            "worker": handoff.worker,
            "attempt": handoff.attempt,
            "status": status,
            "output_refs": [reference.model_dump(mode="json") for reference in output_refs],
            "limitation_codes": limitation_codes,
            "retryable": retryable,
            "stage_timings": [StageTiming(
                stage="guideline_retrieval",
                duration_ms=duration_ms,
                outcome=stage_outcome,
            ).model_dump(mode="json")],
            "contract_versions": handoff.contract_versions,
        })


def _rrf(*ranked_lists: list[str]) -> list[str]:
    fused: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, chunk_id in enumerate(ranked[:CANDIDATES_PER_LEG], start=1):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
    return [chunk_id for chunk_id, _ in sorted(fused.items(), key=lambda item: (-item[1], item[0]))[:CANDIDATES_PER_LEG]]


def _rank_map(ranked: list[str]) -> dict[str, int]:
    return {chunk_id: rank for rank, chunk_id in enumerate(ranked[:CANDIDATES_PER_LEG], start=1)}


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC")
    return parsed.astimezone(timezone.utc)
