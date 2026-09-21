#!/usr/bin/env python3
"""Reproducible synthetic benchmark for the bounded Week 2 retriever."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import sqlite3
import statistics
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import faiss
import joblib
import numpy as np
import onnxruntime as ort
import psutil
import requests
from bs4 import BeautifulSoup
from huggingface_hub import hf_hub_download
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize
from tokenizers import Tokenizer


ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "manifest.json"
QUERY_PATH = ROOT / "queries.jsonl"
CORPUS_PATH = ROOT / "corpus.jsonl"
RESULT_PATH = ROOT / "results.json"
MODEL_REPO = "cross-encoder/ms-marco-MiniLM-L6-v2"
MODEL_REVISION = "233902d25c440f23af6f7d6e94d2946bac0bee0a"
MODEL_FILE = "onnx/model_quint8_avx2.onnx"
EMBEDDING_REPO = "BAAI/bge-small-en-v1.5"
EMBEDDING_REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
EMBEDDING_FILE = "onnx/model.onnx"
EMBEDDING_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
RRF_K = 60
TOP_K = 20
RETURN_K = 5
SVD_SEED = 17
EXPECTED_CORPUS_SHA256 = "b4d8dcbf3151c871ec46c43f25cc73a014ed3e3a20bd89a63ab6713c006c3e03"
EXPECTED_MANIFEST_SHA256 = "cd1916a7d34c877403cd53d533f17e685d296d7746676999694c911aec49da7c"
EXPECTED_QUERIES_SHA256 = "27c33979d46bde6b2b57a6ac2cc95c988bddf7d169e014755092e825d0678e55"
EXPECTED_EMBEDDING_SHA256 = "828e1496d7fabb79cfa4dcd84fa38625c0d3d21da474a00f08db0f559940cf35"
EXPECTED_RERANKER_SHA256 = "c80a8b34256ea453093d612e3ac48d3d965a0c0a48c7906709af8b8e28461bf9"
CITATION_FIELDS = (
    "chunk_id",
    "content_sha256",
    "corpus_version",
    "publisher",
    "jurisdiction",
    "retrieved_at",
    "section_heading_path",
    "source_title",
    "source_url",
    "topic",
    "text",
)


def json_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_json_lines(path: Path, rows: list[dict]) -> None:
    payload = "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rows)
    path.write_text(payload)


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def assert_sha256(path: Path, expected: str, label: str) -> None:
    observed = sha256_path(path)
    if observed != expected:
        raise RuntimeError(f"{label} SHA-256 mismatch: expected {expected}, observed {observed}")


def build_corpus() -> list[dict]:
    manifest = json.loads(MANIFEST_PATH.read_text())
    rows: list[dict] = []
    headers = {"User-Agent": "AgentForge synthetic retrieval benchmark/1.0"}
    for source in manifest["sources"]:
        response = requests.get(source["url"], headers=headers, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        main = soup.find("main") or soup
        for element in main.find_all(["script", "style", "nav", "footer", "header", "noscript"]):
            element.decompose()
        headings: dict[int, str] = {}
        sections: dict[str, list[str]] = {}
        for element in main.find_all(["h1", "h2", "h3", "h4", "p", "li"]):
            value = re.sub(r"\s+", " ", element.get_text(" ", strip=True)).strip()
            if not value:
                continue
            if element.name.startswith("h"):
                level = int(element.name[1])
                headings[level] = value
                headings = {key: item for key, item in headings.items() if key <= level}
                continue
            if element.name == "p" and element.find_parent("li") is not None:
                continue
            heading_path = " > ".join(headings[key] for key in sorted(headings)) or source["title"]
            sections.setdefault(heading_path, []).append(value)

        chunks: list[tuple[str, str]] = []
        target_words = manifest["chunking"]["target_words"]
        minimum_words = manifest["chunking"]["minimum_words"]
        overlap = manifest["chunking"]["sentence_overlap"]
        for heading_path, paragraphs in sections.items():
            sentences = [
                sentence.strip()
                for paragraph in paragraphs
                for sentence in re.split(r"(?<=[.!?])\s+", paragraph)
                if sentence.strip()
            ]
            pending: list[str] = []
            for sentence in sentences:
                if pending and len(" ".join(pending + [sentence]).split()) > target_words:
                    chunk = " ".join(pending)
                    if len(chunk.split()) >= minimum_words:
                        chunks.append((heading_path, chunk))
                    pending = pending[-overlap:] if overlap else []
                pending.append(sentence)
            chunk = " ".join(pending)
            if len(chunk.split()) >= minimum_words:
                chunks.append((heading_path, chunk))
        chunks = chunks[: manifest["chunking"]["maximum_chunks_per_topic"]]
        for ordinal, (heading_path, chunk) in enumerate(chunks):
            rows.append(
                {
                    "chunk_id": f"{source['topic']}-{ordinal:03d}",
                    "content_sha256": hashlib.sha256(chunk.encode()).hexdigest(),
                    "corpus_version": manifest["corpus_version"],
                    "publisher": manifest["publisher"],
                    "section_heading_path": heading_path,
                    "source_title": source["title"],
                    "source_url": source["url"],
                    "text": chunk,
                    "topic": source["topic"],
                }
            )
    write_json_lines(CORPUS_PATH, rows)
    return rows


def percentile(values: list[float], quantile: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=np.float64), quantile))


def query_tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


class OnnxEmbedder:
    def __init__(self, offline: bool):
        started = time.perf_counter()
        common = {"repo_id": EMBEDDING_REPO, "revision": EMBEDDING_REVISION, "local_files_only": offline}
        tokenizer_path = hf_hub_download(filename="tokenizer.json", **common)
        model_path = hf_hub_download(filename=EMBEDDING_FILE, **common)
        self.tokenizer = Tokenizer.from_file(tokenizer_path)
        self.tokenizer.enable_truncation(max_length=384)
        self.tokenizer.enable_padding()
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        options.enable_cpu_mem_arena = False
        options.enable_mem_pattern = False
        self.session = ort.InferenceSession(model_path, sess_options=options, providers=["CPUExecutionProvider"])
        self.model_path = Path(model_path)
        self.load_ms = (time.perf_counter() - started) * 1000

    def encode(self, texts: list[str], *, query: bool = False, batch_size: int = 8) -> np.ndarray:
        if query:
            texts = [EMBEDDING_QUERY_PREFIX + text for text in texts]
        vectors: list[np.ndarray] = []
        for start in range(0, len(texts), batch_size):
            encoded = self.tokenizer.encode_batch(texts[start:start + batch_size])
            feed = {
                "input_ids": np.asarray([item.ids for item in encoded], dtype=np.int64),
                "attention_mask": np.asarray([item.attention_mask for item in encoded], dtype=np.int64),
                "token_type_ids": np.asarray([item.type_ids for item in encoded], dtype=np.int64),
            }
            hidden = self.session.run(None, feed)[0]
            vectors.append(hidden[:, 0, :])
        return normalize(np.vstack(vectors)).astype(np.float32)


class Retriever:
    def __init__(self, corpus: list[dict], artifact_dir: Path, embedder: OnnxEmbedder):
        self.corpus = corpus
        self.by_id = {row["chunk_id"]: row for row in corpus}
        self.ids = [row["chunk_id"] for row in corpus]
        self.sqlite_path = artifact_dir / "sparse.sqlite"
        self.faiss_path = artifact_dir / "dense.faiss"
        self.bge_faiss_path = artifact_dir / "bge-dense.faiss"
        self.vectorizer_path = artifact_dir / "tfidf.joblib"
        self.svd_path = artifact_dir / "svd.joblib"

        self.db = sqlite3.connect(self.sqlite_path, check_same_thread=False)
        self.db.execute("CREATE VIRTUAL TABLE chunks USING fts5(chunk_id UNINDEXED, topic UNINDEXED, text)")
        self.db.executemany(
            "INSERT INTO chunks(chunk_id, topic, text) VALUES (?, ?, ?)",
            [(row["chunk_id"], row["topic"], row["text"]) for row in corpus],
        )
        self.db.commit()
        self.thread_state = threading.local()

        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, dtype=np.float32)
        self.tfidf = self.vectorizer.fit_transform([row["text"] for row in corpus])
        dimensions = min(64, self.tfidf.shape[0] - 1, self.tfidf.shape[1] - 1)
        self.svd = TruncatedSVD(n_components=dimensions, random_state=SVD_SEED)
        dense = normalize(self.svd.fit_transform(self.tfidf)).astype(np.float32)
        self.index = faiss.IndexFlatIP(dimensions)
        self.index.add(dense)
        faiss.write_index(self.index, str(self.faiss_path))
        self.embedder = embedder
        bge_dense = self.embedder.encode([row["text"] for row in corpus])
        self.bge_index = faiss.IndexFlatIP(bge_dense.shape[1])
        self.bge_index.add(bge_dense)
        faiss.write_index(self.bge_index, str(self.bge_faiss_path))
        joblib.dump(self.vectorizer, self.vectorizer_path)
        joblib.dump(self.svd, self.svd_path)

    def sparse(self, query: str, limit: int = TOP_K) -> list[str]:
        terms = query_tokens(query)
        expression = " OR ".join(f'"{term}"' for term in terms)
        if not expression:
            return []
        connection = getattr(self.thread_state, "connection", None)
        if connection is None:
            connection = sqlite3.connect(f"file:{self.sqlite_path}?mode=ro", uri=True)
            self.thread_state.connection = connection
        rows = connection.execute(
            "SELECT chunk_id FROM chunks WHERE chunks MATCH ? ORDER BY bm25(chunks) LIMIT ?",
            (expression, limit),
        ).fetchall()
        return [row[0] for row in rows]

    def dense(self, query: str, limit: int = TOP_K) -> list[str]:
        tfidf = self.vectorizer.transform([query])
        dense = normalize(self.svd.transform(tfidf)).astype(np.float32)
        _, indices = self.index.search(dense, limit)
        return [self.ids[index] for index in indices[0] if index >= 0]

    def dense_bge(self, query: str, limit: int = TOP_K) -> list[str]:
        dense = self.embedder.encode([query], query=True)
        _, indices = self.bge_index.search(dense, limit)
        return [self.ids[index] for index in indices[0] if index >= 0]

    def lexical_scores(self, query: str, candidates: list[str]) -> dict[str, float]:
        query_vector = self.vectorizer.transform([query])
        positions = [self.ids.index(candidate) for candidate in candidates]
        scores = (self.tfidf[positions] @ query_vector.T).toarray().ravel()
        return {candidate: float(score) for candidate, score in zip(candidates, scores, strict=True)}

    def hybrid(self, query: str, limit: int = TOP_K) -> list[str]:
        fused: dict[str, float] = {}
        for ranked in (self.sparse(query, limit), self.dense_bge(query, limit)):
            for rank, chunk_id in enumerate(ranked, start=1):
                fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
        return [item[0] for item in sorted(fused.items(), key=lambda item: (-item[1], item[0]))[:limit]]

    def lexical_rerank(self, query: str, limit: int = TOP_K) -> list[str]:
        candidates = self.hybrid(query, limit)
        scores = self.lexical_scores(query, candidates)
        return sorted(candidates, key=lambda item: (-scores[item], item))

    def artifact_sizes(self) -> dict[str, int]:
        return {
            "sparse_sqlite_bytes": self.sqlite_path.stat().st_size,
            "faiss_index_bytes": self.faiss_path.stat().st_size,
            "bge_faiss_index_bytes": self.bge_faiss_path.stat().st_size,
            "tfidf_vectorizer_bytes": self.vectorizer_path.stat().st_size,
            "svd_transform_bytes": self.svd_path.stat().st_size,
            "dense_matrix_bytes": len(self.corpus) * self.index.d * 4,
            "bge_dense_matrix_bytes": len(self.corpus) * self.bge_index.d * 4,
        }


class OnnxCrossEncoder:
    def __init__(self, offline: bool):
        started = time.perf_counter()
        common = {"repo_id": MODEL_REPO, "revision": MODEL_REVISION, "local_files_only": offline}
        tokenizer_path = hf_hub_download(filename="tokenizer.json", **common)
        model_path = hf_hub_download(filename=MODEL_FILE, **common)
        self.tokenizer = Tokenizer.from_file(tokenizer_path)
        self.tokenizer.enable_truncation(max_length=384)
        self.tokenizer.enable_padding()
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        options.enable_cpu_mem_arena = False
        options.enable_mem_pattern = False
        self.session = ort.InferenceSession(model_path, sess_options=options, providers=["CPUExecutionProvider"])
        self.model_path = Path(model_path)
        self.load_ms = (time.perf_counter() - started) * 1000

    def score(self, query: str, documents: list[str], batch_size: int = 4) -> list[float]:
        scores: list[float] = []
        for start in range(0, len(documents), batch_size):
            encoded = self.tokenizer.encode_batch(
                [(query, document) for document in documents[start:start + batch_size]]
            )
            feed = {
                "input_ids": np.asarray([item.ids for item in encoded], dtype=np.int64),
                "attention_mask": np.asarray([item.attention_mask for item in encoded], dtype=np.int64),
                "token_type_ids": np.asarray([item.type_ids for item in encoded], dtype=np.int64),
            }
            scores.extend(self.session.run(None, feed)[0].reshape(-1).astype(float).tolist())
        return scores


def ranking_metrics(ranked: list[str], topic: str, by_id: dict[str, dict]) -> tuple[float, float, float, float]:
    relevance = [1 if by_id[item]["topic"] == topic else 0 for item in ranked]
    recall = 1.0 if any(relevance[:TOP_K]) else 0.0
    reciprocal_rank = next((1.0 / rank for rank, value in enumerate(relevance, start=1) if value), 0.0)
    dcg = sum(value / math.log2(index + 2) for index, value in enumerate(relevance[:RETURN_K]))
    ideal_count = min(RETURN_K, sum(1 for row in by_id.values() if row["topic"] == topic))
    ideal = sum(1.0 / math.log2(index + 2) for index in range(ideal_count))
    ndcg = dcg / ideal if ideal else 0.0
    top1 = float(bool(relevance and relevance[0]))
    return recall, reciprocal_rank, ndcg, top1


def best_threshold(rows: list[dict]) -> float:
    scores = sorted({row["top_score"] for row in rows})
    candidates = [scores[0] - 1.0] + [(left + right) / 2 for left, right in zip(scores, scores[1:])] + [scores[-1] + 1.0]
    def balanced(threshold: float) -> float:
        positives = [row["top_score"] >= threshold for row in rows if row["topic"] is not None]
        negatives = [row["top_score"] < threshold for row in rows if row["topic"] is None]
        return (statistics.fmean(positives) + statistics.fmean(negatives)) / 2
    return max(candidates, key=lambda threshold: (balanced(threshold), threshold))


def package_versions() -> dict[str, str]:
    names = ["beautifulsoup4", "faiss-cpu", "huggingface-hub", "joblib", "numpy", "onnxruntime", "psutil", "requests", "scikit-learn", "tokenizers"]
    return {name: importlib.metadata.version(name) for name in names}


def cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true", help="Use the frozen corpus and a locally cached pinned reranker")
    parser.add_argument("--refresh-corpus", action="store_true", help="Rebuild corpus.jsonl from the publisher pages")
    parser.add_argument("--iterations", type=int, default=3)
    args = parser.parse_args()
    if args.offline and args.refresh_corpus:
        parser.error("--offline and --refresh-corpus cannot be combined")
    manifest = json.loads(MANIFEST_PATH.read_text())
    if args.refresh_corpus:
        corpus = build_corpus()
    else:
        assert_sha256(MANIFEST_PATH, EXPECTED_MANIFEST_SHA256, "manifest")
        assert_sha256(CORPUS_PATH, EXPECTED_CORPUS_SHA256, "corpus")
        assert_sha256(QUERY_PATH, EXPECTED_QUERIES_SHA256, "queries")
        corpus = json_lines(CORPUS_PATH)
    queries = json_lines(QUERY_PATH)

    process = psutil.Process()
    peak_rss = process.memory_info().rss
    with tempfile.TemporaryDirectory(prefix="week2-retrieval-") as temporary:
        artifact_dir = Path(temporary)
        rss_before_embedding = process.memory_info().rss
        embedder = OnnxEmbedder(args.offline)
        assert_sha256(embedder.model_path, EXPECTED_EMBEDDING_SHA256, "embedding model")
        rss_after_embedding = process.memory_info().rss
        peak_rss = max(peak_rss, rss_after_embedding)
        build_start = time.perf_counter()
        cpu_start = time.process_time()
        retriever = Retriever(corpus, artifact_dir, embedder)
        build_wall_ms = (time.perf_counter() - build_start) * 1000
        build_cpu_ms = (time.process_time() - cpu_start) * 1000
        peak_rss = max(peak_rss, process.memory_info().rss)

        rss_before_model = process.memory_info().rss
        reranker = OnnxCrossEncoder(args.offline)
        assert_sha256(reranker.model_path, EXPECTED_RERANKER_SHA256, "reranker model")
        rss_after_model = process.memory_info().rss
        peak_rss = max(peak_rss, rss_after_model)

        variants = {
            "sparse": retriever.sparse,
            "dense_lsa_faiss_control": retriever.dense,
            "dense_bge_faiss": retriever.dense_bge,
            "hybrid_rrf": retriever.hybrid,
            "hybrid_rrf_lexical_rerank": retriever.lexical_rerank,
        }
        quality: dict[str, dict] = {}
        for name, method in variants.items():
            timings: list[float] = []
            metrics: list[tuple[float, float, float, float]] = []
            cpu_started = time.process_time()
            for _ in range(args.iterations):
                for query in queries:
                    started = time.perf_counter()
                    ranked = method(query["text"])
                    timings.append((time.perf_counter() - started) * 1000)
                    if query["topic"] is not None:
                        metrics.append(ranking_metrics(ranked, query["topic"], retriever.by_id))
            cpu_ms = (time.process_time() - cpu_started) * 1000
            columns = list(zip(*metrics, strict=True))
            quality[name] = {
                "recall_at_20": statistics.fmean(columns[0]),
                "mrr": statistics.fmean(columns[1]),
                "ndcg_at_5": statistics.fmean(columns[2]),
                "top1_topic_accuracy": statistics.fmean(columns[3]),
                "latency_p50_ms": percentile(timings, 50),
                "latency_p95_ms": percentile(timings, 95),
                "cpu_ms_per_query": cpu_ms / len(timings),
            }

        neural_rows: list[dict] = []
        neural_timings: list[float] = []
        neural_cpu_start = time.process_time()
        for query in queries:
            candidates = retriever.hybrid(query["text"])
            documents = [retriever.by_id[item]["text"] for item in candidates]
            started = time.perf_counter()
            scores = reranker.score(query["text"], documents)
            neural_timings.append((time.perf_counter() - started) * 1000)
            ranked = [item for _, item in sorted(zip(scores, candidates, strict=True), key=lambda pair: (-pair[0], pair[1]))]
            row = {"id": query["id"], "split": query["split"], "topic": query["topic"], "top_score": max(scores)}
            if query["topic"] is not None:
                row["metrics"] = ranking_metrics(ranked, query["topic"], retriever.by_id)
            neural_rows.append(row)
            peak_rss = max(peak_rss, process.memory_info().rss)
        neural_cpu_ms = (time.process_time() - neural_cpu_start) * 1000
        dev_rows = [row for row in neural_rows if row["split"] == "dev"]
        holdout_rows = [row for row in neural_rows if row["split"] == "holdout"]
        threshold = best_threshold(dev_rows)
        holdout_abstention = statistics.fmean(
            (row["top_score"] >= threshold) == (row["topic"] is not None) for row in holdout_rows
        )
        positive_metrics = [row["metrics"] for row in neural_rows if row["topic"] is not None]
        neural_columns = list(zip(*positive_metrics, strict=True))
        quality["hybrid_rrf_onnx_cross_encoder"] = {
            "recall_at_20": statistics.fmean(neural_columns[0]),
            "mrr": statistics.fmean(neural_columns[1]),
            "ndcg_at_5": statistics.fmean(neural_columns[2]),
            "top1_topic_accuracy": statistics.fmean(neural_columns[3]),
            "rerank_latency_p50_ms": percentile(neural_timings, 50),
            "rerank_latency_p95_ms": percentile(neural_timings, 95),
            "cpu_ms_per_query": neural_cpu_ms / len(neural_timings),
            "dev_selected_abstention_threshold": threshold,
            "holdout_abstention_accuracy": holdout_abstention,
            "per_query": [
                {
                    "id": row["id"],
                    "split": row["split"],
                    "expected_topic": row["topic"],
                    "top_score": row["top_score"],
                    "passes_threshold": row["top_score"] >= threshold,
                }
                for row in neural_rows
            ],
        }

        def concurrent(method, workers: int, requests_count: int) -> dict[str, float]:
            query_texts = [queries[index % len(queries)]["text"] for index in range(requests_count)]
            def timed(query_text: str) -> float:
                query_started = time.perf_counter()
                method(query_text)
                return (time.perf_counter() - query_started) * 1000
            started = time.perf_counter()
            with ThreadPoolExecutor(max_workers=workers) as executor:
                timings = list(executor.map(timed, query_texts))
            elapsed = (time.perf_counter() - started) * 1000
            return {
                "workers": workers,
                "requests": requests_count,
                "wall_ms": elapsed,
                "throughput_qps": requests_count / (elapsed / 1000),
                "latency_p50_ms": percentile(timings, 50),
                "latency_p95_ms": percentile(timings, 95),
            }

        def citation_payload(chunk_id: str, rank: int, score: float) -> dict:
            source = retriever.by_id[chunk_id]
            return {
                "chunk_id": source["chunk_id"],
                "content_sha256": source["content_sha256"],
                "corpus_version": source["corpus_version"],
                "publisher": source["publisher"],
                "jurisdiction": manifest["jurisdiction"],
                "retrieved_at": manifest["retrieved_at"],
                "section_heading_path": source["section_heading_path"],
                "source_title": source["source_title"],
                "source_url": source["source_url"],
                "topic": source["topic"],
                "text": source["text"],
                "final_rank": rank,
                "reranker_score": score,
            }

        def full_pipeline(query_text: str) -> list[dict]:
            candidates = retriever.hybrid(query_text)
            documents = [retriever.by_id[item]["text"] for item in candidates]
            scores = reranker.score(query_text, documents)
            ranked = sorted(
                zip(scores, candidates, strict=True),
                key=lambda pair: (-pair[0], pair[1]),
            )[:RETURN_K]
            return [
                citation_payload(chunk_id, rank, score)
                for rank, (score, chunk_id) in enumerate(ranked, start=1)
            ]

        citation_failures: list[dict] = []
        citation_outputs_checked = 0
        for query in queries:
            for payload in full_pipeline(query["text"]):
                source = retriever.by_id[payload["chunk_id"]]
                expected = {
                    **{field: source[field] for field in CITATION_FIELDS if field in source},
                    "jurisdiction": manifest["jurisdiction"],
                    "retrieved_at": manifest["retrieved_at"],
                }
                citation_outputs_checked += 1
                mismatched = [field for field in CITATION_FIELDS if payload[field] != expected[field]]
                if mismatched:
                    citation_failures.append(
                        {"query_id": query["id"], "chunk_id": payload["chunk_id"], "fields": mismatched}
                    )

        result = {
            "inputs": {
                "corpus_rows": len(corpus),
                "corpus_sha256": sha256_path(CORPUS_PATH),
                "manifest_sha256": sha256_path(MANIFEST_PATH),
                "queries": len(queries),
                "queries_sha256": sha256_path(QUERY_PATH),
                "synthetic_only": True,
            },
            "configuration": {
                "rrf_k": RRF_K,
                "candidate_k_per_leg": TOP_K,
                "return_k": RETURN_K,
                "svd_seed": SVD_SEED,
                "reranker_repo": MODEL_REPO,
                "reranker_revision": MODEL_REVISION,
                "reranker_file": MODEL_FILE,
                "reranker_sha256": sha256_path(reranker.model_path),
                "onnx_threads": 2,
                "embedding_repo": EMBEDDING_REPO,
                "embedding_revision": EMBEDDING_REVISION,
                "embedding_file": EMBEDDING_FILE,
                "embedding_sha256": sha256_path(embedder.model_path),
                "embedding_query_prefix": EMBEDDING_QUERY_PREFIX,
            },
            "build": {
                "wall_ms": build_wall_ms,
                "cpu_ms": build_cpu_ms,
                "cpu_percent_of_one_core": build_cpu_ms / build_wall_ms * 100,
                "reranker_cold_load_ms": reranker.load_ms,
                "reranker_first_query_ms": neural_timings[0],
                "reranker_rss_delta_bytes": rss_after_model - rss_before_model,
                "embedding_cold_load_ms": embedder.load_ms,
                "embedding_rss_delta_bytes": rss_after_embedding - rss_before_embedding,
                "peak_process_rss_bytes": peak_rss,
                "artifact_sizes": {
                    **retriever.artifact_sizes(),
                    "embedding_model_bytes": embedder.model_path.stat().st_size,
                    "reranker_model_bytes": reranker.model_path.stat().st_size,
                },
            },
            "quality_and_latency": quality,
            "citation_metadata_preservation": {
                "required_fields": list(CITATION_FIELDS),
                "outputs_checked": citation_outputs_checked,
                "outputs_with_exact_metadata": citation_outputs_checked - len(citation_failures),
                "preservation_rate": (
                    (citation_outputs_checked - len(citation_failures)) / citation_outputs_checked
                ),
                "failures": citation_failures,
            },
            "concurrency": {
                "sparse_1_worker": concurrent(retriever.sparse, 1, 64),
                "sparse_10_workers": concurrent(retriever.sparse, 10, 128),
                "dense_bge_1_worker": concurrent(retriever.dense_bge, 1, 64),
                "dense_bge_10_workers": concurrent(retriever.dense_bge, 10, 128),
                "full_pipeline_1_worker": concurrent(full_pipeline, 1, 32),
                "full_pipeline_10_workers": concurrent(full_pipeline, 10, 64),
            },
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "logical_cpus": os.cpu_count(),
                "physical_cpus": psutil.cpu_count(logical=False),
                "cpu_model": cpu_model(),
                "memory_total_bytes": psutil.virtual_memory().total,
                "packages": package_versions(),
            },
        }
    RESULT_PATH.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
