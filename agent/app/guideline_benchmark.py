"""Offline repeatable measurements for the Slice 3B retrieval engine.

The runner deliberately uses only finite ``EvidenceQuery`` concepts.  It is a
setup-time/CI utility, never a runtime dependency and never a model downloader.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import resource
import statistics
import time

from .contracts.guidelines import GuidelineTopic
from .guideline_corpus.build import sha256_path
from .guideline_retriever import (
    RERANKER_ONNX_FILE,
    RERANKER_ONNX_SHA256,
    RERANKER_REPOSITORY,
    RERANKER_REVISION,
    RERANKER_TOKENIZER_FILE,
    RERANKER_TOKENIZER_SHA256,
    GuidelineRetriever,
    RetrievalError,
)


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * quantile))]


def peak_rss_bytes() -> int:
    """Linux ``ru_maxrss`` is KiB; use stdlib so the runtime lock need not grow."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024


def query(topic: GuidelineTopic):
    from .contracts.guidelines import EvidenceQuery

    return EvidenceQuery.model_validate({
        "concepts": [topic], "topic_filter": topic, "requested_top_k": 5,
        "correlation_id": "123e4567-e89b-12d3-a456-426614174000",
        "handoff_id": "b" * 32, "deadline_ms": 2000,
    })


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the offline, hash-bound guideline retrieval benchmark.")
    parser.add_argument("--embedding-model-dir", required=True, type=Path)
    parser.add_argument("--reranker-model-dir", required=True, type=Path)
    parser.add_argument("--repeat", type=int, default=2, choices=range(1, 11))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    started = time.perf_counter()
    cpu_started = time.process_time()
    rss_before = peak_rss_bytes()
    try:
        engine = GuidelineRetriever(
            embedding_model_dir=args.embedding_model_dir,
            reranker_model_dir=args.reranker_model_dir,
        )
        load_ms = (time.perf_counter() - started) * 1000
        rows = []
        for _ in range(args.repeat):
            for topic in GuidelineTopic:
                result = engine.retrieve(query(topic))
                rows.append({
                    "topic": topic.value,
                    "top_topic_matches": bool(result.excerpts) and result.excerpts[0].topic == topic,
                    "returned": len(result.excerpts),
                    "sparse_ms": result.measurement.sparse_ms,
                    "dense_ms": result.measurement.dense_ms,
                    "fusion_ms": result.measurement.fusion_ms,
                    "rerank_ms": result.measurement.rerank_ms,
                    "total_ms": result.measurement.total_ms,
                    "exact_hashes_match": all(item.chunk_sha256 == engine.chunks[item.chunk_id]["chunk_sha256"] for item in result.excerpts),
                })
        elapsed_ms = (time.perf_counter() - started) * 1000
        totals = [row["total_ms"] for row in rows]
        result = {
            "status": "ok",
            "synthetic_only": True,
            "configuration": {
                "corpus_version": engine.artifact["corpus_version"],
                "chunk_count": engine.artifact["chunk_count"],
                "rrf_k": 60, "candidate_k_per_leg": 20, "fused_k": 20, "return_k": 5,
                "embedding": {
                    "repository": engine.manifest["dense_model"]["repository"],
                    "revision": engine.manifest["dense_model"]["revision"],
                    "onnx_file": engine.manifest["dense_model"]["onnx_file"],
                    "onnx_sha256": engine.manifest["dense_model"]["onnx_sha256"],
                    "tokenizer_file": engine.manifest["dense_model"]["tokenizer_file"],
                    "tokenizer_sha256": engine.manifest["dense_model"]["tokenizer_sha256"],
                    "provisioned_path": "bge",
                },
                "reranker": {
                    "repository": RERANKER_REPOSITORY, "revision": RERANKER_REVISION,
                    "onnx_file": RERANKER_ONNX_FILE, "onnx_sha256": RERANKER_ONNX_SHA256,
                    "tokenizer_file": RERANKER_TOKENIZER_FILE, "tokenizer_sha256": RERANKER_TOKENIZER_SHA256,
                    "provisioned_path": "reranker",
                },
                "artifacts": engine.artifact["artifacts"],
            },
            "quality": {
                "cases": len(rows),
                "top1_topic_accuracy": statistics.fmean(row["top_topic_matches"] for row in rows),
                "exact_hash_preservation_rate": statistics.fmean(row["exact_hashes_match"] for row in rows),
                "mean_returned_excerpts": statistics.fmean(row["returned"] for row in rows),
            },
            "latency_ms": {
                "load": load_ms, "sparse_p50": percentile([row["sparse_ms"] for row in rows], .5), "sparse_p95": percentile([row["sparse_ms"] for row in rows], .95),
                "dense_p50": percentile([row["dense_ms"] for row in rows], .5), "dense_p95": percentile([row["dense_ms"] for row in rows], .95),
                "fusion_p50": percentile([row["fusion_ms"] for row in rows], .5), "fusion_p95": percentile([row["fusion_ms"] for row in rows], .95),
                "rerank_p50": percentile([row["rerank_ms"] for row in rows], .5), "rerank_p95": percentile([row["rerank_ms"] for row in rows], .95),
                "total_p50": percentile(totals, .5), "total_p95": percentile(totals, .95),
            },
            "resources": {
                "cpu_ms": (time.process_time() - cpu_started) * 1000,
                "peak_rss_bytes": peak_rss_bytes(),
                "rss_delta_bytes": peak_rss_bytes() - rss_before,
                "embedding_model_bytes": (args.embedding_model_dir / engine.manifest["dense_model"]["onnx_file"]).stat().st_size,
                "reranker_model_bytes": (args.reranker_model_dir / RERANKER_ONNX_FILE).stat().st_size,
                "host": platform.platform(), "logical_cpus": os.cpu_count(),
            },
        }
    except (RetrievalError, OSError, ValueError) as exc:
        # Deliberately no free-form exception strings or model paths in output.
        result = {"status": "rejected", "reason": type(exc).__name__}
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": result["status"], "output": str(args.output), "elapsed_ms": round((time.perf_counter() - started) * 1000)}, sort_keys=True))
    return 0 if result["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
