"""Offline, fail-closed hybrid retrieval for the approved guideline corpus.

This is deliberately an engine rather than a worker or endpoint.  A later
worker supplies the already-authorized :class:`EvidenceQuery`; this module
never accepts a chart question, makes a network request, or emits telemetry.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import time
from typing import Callable, Protocol, Sequence

import faiss
import numpy as np
import onnxruntime as ort
import tokenizers
from tokenizers import Tokenizer

from .contracts.guidelines import (
    ACTIVE_CORPUS_VERSION,
    CandidateLeg,
    EvidenceQuery,
    GuidelineCandidate,
    GuidelineExcerpt,
)
from .guideline_corpus.build import (
    CORPUS_ROOT,
    CorpusError,
    load_manifest,
    read_jsonl,
    sha256_path,
    validate_active_pointer,
    validate_artifacts,
)


CANDIDATES_PER_LEG = 20
FUSED_CANDIDATES = 20
RETURNED_EXCERPTS = 5
RRF_K = 60
RERANKER_BATCH_SIZE = 4
RERANKER_MAX_TOKENS = 384
RERANKER_REPOSITORY = "cross-encoder/ms-marco-MiniLM-L6-v2"
RERANKER_REVISION = "233902d25c440f23af6f7d6e94d2946bac0bee0a"
RERANKER_ONNX_FILE = "onnx/model_quint8_avx2.onnx"
RERANKER_ONNX_SHA256 = "c80a8b34256ea453093d612e3ac48d3d965a0c0a48c7906709af8b8e28461bf9"
RERANKER_TOKENIZER_FILE = "tokenizer.json"
RERANKER_TOKENIZER_SHA256 = "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66"
# The frozen benchmark's threshold is a suppress-only control.  It never
# authorizes evidence and is bound to this model revision.
RERANKER_THRESHOLD = -2.960404384881258

# `EvidenceQuery` intentionally excludes free text.  These fixed, reviewed
# topic probes are the only strings that can reach FTS, BGE, or the reranker.
TOPIC_PROBES = {
    "aaa": "abdominal aortic aneurysm screening ultrasound",
    "breast": "breast cancer screening mammography",
    "cervical": "cervical cancer screening cytology HPV",
    "colorectal": "colorectal cancer screening colonoscopy stool",
    "lung": "lung cancer screening low dose CT smoking",
    "child_obesity": "children high body mass index interventions",
    "hypertension": "adult hypertension blood pressure screening",
    "tobacco": "tobacco smoking cessation adults pregnancy",
}


class RetrievalError(RuntimeError):
    """A bounded retrieval invariant failed and evidence must be withheld."""


class RetrievalUnavailable(RetrievalError):
    """Models, artifacts, a leg, fusion, or the deadline is unavailable."""


class RetrievalNoEvidence(RetrievalError):
    """Both healthy legs found no qualifying active-corpus evidence."""


class Embedder(Protocol):
    def encode_query(self, text: str) -> np.ndarray: ...


class Reranker(Protocol):
    def score(self, query: str, passages: Sequence[str]) -> list[float]: ...


@dataclass(frozen=True)
class FusedCandidate:
    chunk_id: str
    rrf_score: float
    sparse_rank: int | None
    dense_rank: int | None


@dataclass(frozen=True)
class RetrievalMeasurement:
    sparse_ms: float
    dense_ms: float
    fusion_ms: float
    rerank_ms: float
    total_ms: float
    sparse_candidates: int
    dense_candidates: int
    fused_candidates: int
    returned_excerpts: int


@dataclass(frozen=True)
class RetrievalResult:
    excerpts: tuple[GuidelineExcerpt, ...]
    candidates: tuple[GuidelineCandidate, ...]
    fused: tuple[FusedCandidate, ...]
    reranker_scores: tuple[tuple[str, float], ...]
    measurement: RetrievalMeasurement


class PinnedBgeEmbedder:
    """The hash-bound, locally provisioned BGE query encoder."""

    def __init__(self, model_dir: Path, configuration: dict[str, object]) -> None:
        model_path = model_dir / str(configuration["onnx_file"])
        tokenizer_path = model_dir / str(configuration["tokenizer_file"])
        if not model_path.is_file() or not tokenizer_path.is_file():
            raise RetrievalUnavailable("pinned embedding model is unavailable locally")
        if (
            ort.__version__ != configuration["onnxruntime_version"]
            or tokenizers.__version__ != configuration["tokenizers_version"]
            or sha256_path(model_path) != configuration["onnx_sha256"]
            or sha256_path(tokenizer_path) != configuration["tokenizer_sha256"]
        ):
            raise RetrievalUnavailable("pinned embedding model version or hash mismatch")
        options = ort.SessionOptions()
        options.intra_op_num_threads = int(configuration["intra_op_threads"])
        options.inter_op_num_threads = int(configuration["inter_op_threads"])
        options.enable_cpu_mem_arena = False
        options.enable_mem_pattern = False
        try:
            self.session = ort.InferenceSession(model_path, sess_options=options, providers=["CPUExecutionProvider"])
            self.tokenizer = Tokenizer.from_file(str(tokenizer_path))
        except Exception as exc:
            raise RetrievalUnavailable("pinned embedding model is unusable") from exc
        self.tokenizer.enable_truncation(max_length=int(configuration["max_tokens"]))
        self.tokenizer.enable_padding()
        self.prefix = str(configuration["query_prefix"])
        self.dimensions = int(configuration["vector_dimensions"])

    def encode_query(self, text: str) -> np.ndarray:
        encoded = self.tokenizer.encode_batch([self.prefix + text])
        item = encoded[0]
        try:
            hidden = self.session.run(None, {
                "input_ids": np.asarray([item.ids], dtype=np.int64),
                "attention_mask": np.asarray([item.attention_mask], dtype=np.int64),
                "token_type_ids": np.asarray([item.type_ids], dtype=np.int64),
            })[0][:, 0, :].astype(np.float32)
        except Exception as exc:
            raise RetrievalUnavailable("pinned embedding inference failed") from exc
        norm = np.linalg.norm(hidden, axis=1, keepdims=True)
        if hidden.shape != (1, self.dimensions) or np.any(norm == 0):
            raise RetrievalUnavailable("pinned embedding output is invalid")
        return hidden / norm


class PinnedCrossEncoder:
    """Independent, hash-bound local ONNX cross-encoder reranker."""

    def __init__(self, model_dir: Path) -> None:
        model_path = model_dir / RERANKER_ONNX_FILE
        tokenizer_path = model_dir / RERANKER_TOKENIZER_FILE
        if not model_path.is_file() or not tokenizer_path.is_file():
            raise RetrievalUnavailable("pinned reranker is unavailable locally")
        if ort.__version__ != "1.22.1" or tokenizers.__version__ != "0.22.2":
            raise RetrievalUnavailable("pinned reranker runtime version mismatch")
        if sha256_path(model_path) != RERANKER_ONNX_SHA256 or sha256_path(tokenizer_path) != RERANKER_TOKENIZER_SHA256:
            raise RetrievalUnavailable("pinned reranker model or tokenizer hash mismatch")
        try:
            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            options.inter_op_num_threads = 1
            options.enable_cpu_mem_arena = False
            options.enable_mem_pattern = False
            self.session = ort.InferenceSession(model_path, sess_options=options, providers=["CPUExecutionProvider"])
            self.tokenizer = Tokenizer.from_file(str(tokenizer_path))
        except Exception as exc:
            raise RetrievalUnavailable("pinned reranker is unusable") from exc
        self.tokenizer.enable_truncation(max_length=RERANKER_MAX_TOKENS)
        self.tokenizer.enable_padding()

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        scores: list[float] = []
        try:
            for start in range(0, len(passages), RERANKER_BATCH_SIZE):
                encoded = self.tokenizer.encode_batch([(query, text) for text in passages[start:start + RERANKER_BATCH_SIZE]])
                output = self.session.run(None, {
                    "input_ids": np.asarray([item.ids for item in encoded], dtype=np.int64),
                    "attention_mask": np.asarray([item.attention_mask for item in encoded], dtype=np.int64),
                    "token_type_ids": np.asarray([item.type_ids for item in encoded], dtype=np.int64),
                })[0]
                scores.extend(float(row[0]) for row in output)
        except Exception as exc:
            raise RetrievalUnavailable("pinned reranker inference failed") from exc
        if len(scores) != len(passages) or not np.all(np.isfinite(scores)):
            raise RetrievalUnavailable("pinned reranker output is invalid")
        return scores


class GuidelineRetriever:
    """One immutable corpus version, two mandatory legs, and one reranker."""

    def __init__(
        self,
        *,
        artifact_dir: Path = CORPUS_ROOT / "artifacts",
        embedding_model_dir: Path | None = None,
        reranker_model_dir: Path | None = None,
        embedder: Embedder | None = None,
        reranker: Reranker | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        try:
            manifest = load_manifest()
            artifact = validate_artifacts(artifact_dir, manifest)
            validate_active_pointer(artifact_dir, artifact)
            chunks = read_jsonl(artifact_dir / "chunks.jsonl")
            ids = json.loads((artifact_dir / "dense.ids.json").read_text())
            index = faiss.read_index(str(artifact_dir / "dense.faiss"))
        except (CorpusError, OSError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
            raise RetrievalUnavailable("active corpus artifacts are invalid") from exc
        if artifact["corpus_version"] != ACTIVE_CORPUS_VERSION or len(chunks) != len(ids) or index.ntotal != len(ids):
            raise RetrievalUnavailable("active corpus artifacts are inconsistent")
        self.manifest = manifest
        self.artifact = artifact
        self.artifact_dir = artifact_dir
        self.chunks = {row["chunk_id"]: row for row in chunks}
        if set(self.chunks) != set(ids):
            raise RetrievalUnavailable("dense IDs do not bind active chunks")
        self.ids = ids
        self.index = index
        self.monotonic, self.now = monotonic, now
        self.embedder = embedder or PinnedBgeEmbedder(embedding_model_dir or Path(), manifest["dense_model"])
        self.reranker = reranker or PinnedCrossEncoder(reranker_model_dir or Path())

    def _check_deadline(self, started: float, deadline_ms: int) -> None:
        if (self.monotonic() - started) * 1000 > deadline_ms:
            raise RetrievalUnavailable("retrieval deadline exceeded")

    def _query_text(self, query: EvidenceQuery) -> str:
        return " ".join(TOPIC_PROBES[concept.value] for concept in query.concepts)

    def _allowed_ids(self, query: EvidenceQuery) -> set[str]:
        topics = {query.topic_filter.value} if query.topic_filter else {item.value for item in query.concepts}
        return {chunk_id for chunk_id, row in self.chunks.items() if row["topic"] in topics}

    def _sparse(self, text: str, allowed_ids: set[str]) -> list[tuple[str, float]]:
        terms = [term for term in text.lower().split() if term.isascii() and term.isalnum()]
        if not terms:
            raise RetrievalUnavailable("fixed query probe is invalid")
        expression = " OR ".join(f'"{term}"' for term in terms)
        try:
            connection = sqlite3.connect(f"file:{self.artifact_dir / 'sparse.sqlite'}?mode=ro", uri=True)
            rows = connection.execute(
                "SELECT chunk_id, bm25(chunks) AS score FROM chunks WHERE chunks MATCH ? ORDER BY score, chunk_id LIMIT ?",
                (expression, CANDIDATES_PER_LEG * 8),
            ).fetchall()
            connection.close()
        except sqlite3.Error as exc:
            raise RetrievalUnavailable("sparse retrieval failed") from exc
        return [(chunk_id, float(-score)) for chunk_id, score in rows if chunk_id in allowed_ids][:CANDIDATES_PER_LEG]

    def _dense(self, text: str, allowed_ids: set[str]) -> list[tuple[str, float]]:
        vector = self.embedder.encode_query(text)
        try:
            scores, positions = self.index.search(vector, self.index.ntotal)
        except Exception as exc:
            raise RetrievalUnavailable("dense retrieval failed") from exc
        result = [(self.ids[position], float(score)) for score, position in zip(scores[0], positions[0], strict=True) if position >= 0 and self.ids[position] in allowed_ids]
        return result[:CANDIDATES_PER_LEG]

    @staticmethod
    def fuse(sparse: Sequence[tuple[str, float]], dense: Sequence[tuple[str, float]]) -> tuple[FusedCandidate, ...]:
        if sparse is None or dense is None:
            raise RetrievalUnavailable("a retrieval leg is missing")
        fused: dict[str, list[float | int | None]] = {}
        for rank, (chunk_id, _score) in enumerate(sparse, start=1):
            current = fused.setdefault(chunk_id, [0.0, None, None])
            current[0] = float(current[0]) + 1 / (RRF_K + rank)
            current[1] = rank
        for rank, (chunk_id, _score) in enumerate(dense, start=1):
            current = fused.setdefault(chunk_id, [0.0, None, None])
            current[0] = float(current[0]) + 1 / (RRF_K + rank)
            current[2] = rank
        return tuple(
            FusedCandidate(chunk_id, float(values[0]), values[1] if isinstance(values[1], int) else None, values[2] if isinstance(values[2], int) else None)
            for chunk_id, values in sorted(fused.items(), key=lambda item: (-float(item[1][0]), item[0]))[:FUSED_CANDIDATES]
        )

    def _excerpt(self, chunk_id: str) -> GuidelineExcerpt:
        row = self.chunks[chunk_id]
        return GuidelineExcerpt.model_validate({
            **{key: row[key] for key in (
                "corpus_version", "document_id", "chunk_id", "chunk_ordinal", "publisher", "title",
                "jurisdiction", "canonical_url", "publication_date", "topic", "section_path", "exact_text",
                "source_sha256", "chunk_sha256", "corpus_retrieved_at", "approved_at",
            )},
            "contract_version": "3.0.0",
            "source_id": f"guideline:{row['corpus_version']}:{row['document_id']}:{row['chunk_id']}",
        })

    def retrieve(self, query: EvidenceQuery) -> RetrievalResult:
        if not isinstance(query, EvidenceQuery) or query.active_corpus_version != ACTIVE_CORPUS_VERSION:
            raise RetrievalUnavailable("query corpus version is invalid")
        approved_at = datetime.fromisoformat(self.manifest["approval"]["approved_at"].replace("Z", "+00:00"))
        if (self.now() - approved_at).days > int(self.manifest["approval"]["stale_after_days"]):
            raise RetrievalUnavailable("active corpus is stale")
        started = self.monotonic()
        text, allowed_ids = self._query_text(query), self._allowed_ids(query)
        sparse_started = self.monotonic()
        sparse = self._sparse(text, allowed_ids)
        sparse_ms = (self.monotonic() - sparse_started) * 1000
        self._check_deadline(started, query.deadline_ms)
        dense_started = self.monotonic()
        dense = self._dense(text, allowed_ids)
        dense_ms = (self.monotonic() - dense_started) * 1000
        self._check_deadline(started, query.deadline_ms)
        fusion_started = self.monotonic()
        fused = self.fuse(sparse, dense)
        fusion_ms = (self.monotonic() - fusion_started) * 1000
        self._check_deadline(started, query.deadline_ms)
        if not fused:
            raise RetrievalNoEvidence("no active-corpus candidate")
        rerank_started = self.monotonic()
        scores = self.reranker.score(text, [self.chunks[item.chunk_id]["exact_text"] for item in fused])
        rerank_ms = (self.monotonic() - rerank_started) * 1000
        self._check_deadline(started, query.deadline_ms)
        if len(scores) != len(fused):
            raise RetrievalUnavailable("reranker returned incomplete candidates")
        reranked = sorted(zip(fused, scores, strict=True), key=lambda item: (-item[1], item[0].chunk_id))
        final = [(candidate, score) for candidate, score in reranked if score >= RERANKER_THRESHOLD][:query.requested_top_k]
        if not final:
            raise RetrievalNoEvidence("no candidate met the suppress-only threshold")
        candidates = []
        for leg, values in ((CandidateLeg.sparse, sparse), (CandidateLeg.dense, dense)):
            for rank, (chunk_id, score) in enumerate(values, start=1):
                row = self.chunks[chunk_id]
                candidates.append(GuidelineCandidate.model_validate({
                    "contract_version": "3.0.0", "source_id": f"guideline:{row['corpus_version']}:{row['document_id']}:{chunk_id}",
                    "corpus_version": row["corpus_version"], "document_id": row["document_id"], "chunk_id": chunk_id,
                    "chunk_ordinal": row["chunk_ordinal"], "leg": leg, "leg_rank": rank, "score": score,
                    "chunk_sha256": row["chunk_sha256"],
                }))
        total_ms = (self.monotonic() - started) * 1000
        return RetrievalResult(
            excerpts=tuple(self._excerpt(candidate.chunk_id) for candidate, _score in final),
            candidates=tuple(candidates), fused=fused,
            reranker_scores=tuple((candidate.chunk_id, score) for candidate, score in reranked),
            measurement=RetrievalMeasurement(sparse_ms, dense_ms, fusion_ms, rerank_ms, total_ms, len(sparse), len(dense), len(fused), len(final)),
        )
