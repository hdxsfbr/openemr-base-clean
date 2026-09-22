"""Build and validate the immutable, local guideline-corpus artifacts.

This module never downloads source or model material.  The command accepts a
previously provisioned pinned model directory and fails before artifact access
when the approved input, model, tokenizer, or active-version pointer drifts.
It intentionally contains no query/ranking implementation.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import re
import shutil
import sqlite3
import tempfile
import time
import unicodedata
from pathlib import Path
from typing import Any

import faiss
import numpy as np
import onnxruntime as ort
import tokenizers
from tokenizers import Tokenizer


# The package is installed at /app/app in the runtime image, with the checked-in
# corpus at /app/guideline_corpus.  Derive that stable agent root first rather
# than assuming a source-checkout parent such as /repository/agent.
AGENT_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = AGENT_ROOT.parent
CORPUS_ROOT = AGENT_ROOT / "guideline_corpus"
MANIFEST_PATH = CORPUS_ROOT / "approved_manifest.json"
ACTIVE_POINTER_PATH = CORPUS_ROOT / "active.json"
SOURCE_INPUT_PATH = REPOSITORY / "docs" / "research" / "week2-retrieval-benchmark" / "corpus.jsonl"
ARTIFACTS = ("chunks.jsonl", "sparse.sqlite", "dense.faiss", "dense.ids.json", "artifact-manifest.json")
SENTENCES = re.compile(r"(?<=[.!?])\s+")


class CorpusError(ValueError):
    """An approved corpus invariant failed; callers must not use artifacts."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError) as exc:
        raise CorpusError("approved input is unreadable") from exc


def normalized_text(value: str) -> str:
    value = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def section_path(value: str) -> list[str]:
    result = [normalized_text(item) for item in value.split(" > ")]
    if not result or any(not item or len(item) > 200 for item in result) or len(result) > 8:
        raise CorpusError("source section path is malformed")
    return result


def chunks_for_block(text: str, *, target_words: int, minimum_words: int, overlap: int) -> list[str]:
    sentences = [normalized_text(item) for item in SENTENCES.split(text) if normalized_text(item)]
    if not sentences:
        raise CorpusError("source block has no text")
    pending: list[str] = []
    output: list[str] = []
    for sentence in sentences:
        if pending and len(" ".join([*pending, sentence]).split()) > target_words:
            chunk = " ".join(pending)
            if len(chunk.split()) < minimum_words:
                raise CorpusError("source block would create an undersized chunk")
            output.append(chunk)
            pending = pending[-overlap:] if overlap else []
        pending.append(sentence)
    chunk = " ".join(pending)
    if len(chunk.split()) < minimum_words:
        raise CorpusError("source block would create an undersized chunk")
    output.append(chunk)
    return output


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise CorpusError("approved corpus manifest is unreadable") from exc
    required = {"corpus_version", "approval", "licensing", "chunking", "dense_model", "sources"}
    if set(manifest) != required or not isinstance(manifest["sources"], list) or len(manifest["sources"]) != 8:
        raise CorpusError("approved corpus manifest shape is invalid")
    if manifest["corpus_version"] != "uspstf-recommendations-2026-09-21-v2":
        raise CorpusError("unapproved corpus version")
    if manifest["approval"].get("automated_refresh") is not False or manifest["approval"].get("runtime_network") is not False:
        raise CorpusError("corpus must be offline-only and manually approved")
    return manifest


def source_snapshot(rows: list[dict[str, Any]], source: dict[str, Any]) -> dict[str, Any]:
    blocks = []
    for row in rows:
        if row.get("topic") != source["document_id"]:
            continue
        text = normalized_text(str(row.get("text", "")))
        if not text:
            raise CorpusError("approved source contains empty text")
        blocks.append({"section_path": section_path(str(row.get("section_heading_path", ""))), "text": text})
    if not blocks:
        raise CorpusError("approved source has no frozen blocks")
    return {
        "document_id": source["document_id"],
        "publisher": source["publisher"],
        "title": source["title"],
        "canonical_url": source["canonical_url"],
        "jurisdiction": source["jurisdiction"],
        "publication_date": source["publication_date"],
        "review_date": source["review_date"],
        "blocks": blocks,
    }


def validate_inputs(manifest: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    known = {source["document_id"] for source in manifest["sources"]}
    if len(rows) != 160 or len(known) != len(manifest["sources"]) or {row.get("topic") for row in rows} != known:
        raise CorpusError("source set does not exactly match the approved manifest")
    if any(
        set(row) != {"chunk_id", "content_sha256", "corpus_version", "publisher", "section_heading_path", "source_title", "source_url", "text", "topic"}
        or row["corpus_version"] != manifest["corpus_version"]
        or sha256_bytes(normalized_text(str(row["text"])).encode()) != row["content_sha256"]
        for row in rows
    ):
        raise CorpusError("frozen source input has malformed or altered content")
    snapshots: list[dict[str, Any]] = []
    for source in manifest["sources"]:
        expected = {
            "document_id", "publisher", "title", "canonical_url", "jurisdiction", "publication_date", "review_date",
            "source_snapshot_sha256", "publisher_snapshot_retrieved_at", "approved_at",
        }
        if set(source) != expected:
            raise CorpusError("source provenance fields are incomplete")
        if not source["title"] or not source["canonical_url"].startswith("https://"):
            raise CorpusError("source provenance is malformed")
        try:
            snapshot_at = datetime.fromisoformat(source["publisher_snapshot_retrieved_at"].replace("Z", "+00:00"))
            approved_at = datetime.fromisoformat(source["approved_at"].replace("Z", "+00:00"))
        except (AttributeError, ValueError) as exc:
            raise CorpusError("source provenance date is malformed") from exc
        if approved_at < snapshot_at or (approved_at - snapshot_at).days > manifest["approval"]["stale_after_days"]:
            raise CorpusError("source snapshot is stale when approved")
        if sum(row["topic"] == source["document_id"] for row in rows) != 20:
            raise CorpusError("approved source chunk count drifted")
        snapshot = source_snapshot(rows, source)
        observed = sha256_bytes(canonical_json(snapshot))
        if observed != source["source_snapshot_sha256"]:
            raise CorpusError("source snapshot hash mismatch")
        snapshots.append(snapshot)
    return snapshots


def build_chunks(manifest: dict[str, Any], snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    policy = manifest["chunking"]
    if set(policy) != {"algorithm_version", "target_words", "minimum_words", "sentence_overlap", "maximum_chunks_per_document"}:
        raise CorpusError("chunking policy is incomplete")
    output: list[dict[str, Any]] = []
    approved = {source["document_id"]: source for source in manifest["sources"]}
    for snapshot in snapshots:
        source = approved[snapshot["document_id"]]
        ordinal = 0
        source_hash = sha256_bytes(canonical_json(snapshot))
        for block in snapshot["blocks"]:
            for text in chunks_for_block(
                block["text"], target_words=policy["target_words"], minimum_words=policy["minimum_words"], overlap=policy["sentence_overlap"],
            ):
                if ordinal >= policy["maximum_chunks_per_document"]:
                    raise CorpusError("approved source exceeds maximum chunk count")
                chunk_id = f"{snapshot['document_id']}-{ordinal:03d}"
                output.append(
                    {
                        "corpus_version": manifest["corpus_version"],
                        "document_id": snapshot["document_id"],
                        "chunk_id": chunk_id,
                        "chunk_ordinal": ordinal,
                        "publisher": snapshot["publisher"],
                        "title": snapshot["title"],
                        "jurisdiction": snapshot["jurisdiction"],
                        "canonical_url": snapshot["canonical_url"],
                        "publication_date": snapshot["publication_date"],
                        "review_date": snapshot["review_date"],
                        "topic": snapshot["document_id"],
                        "section_path": block["section_path"],
                        "exact_text": text,
                        "source_sha256": source_hash,
                        "chunk_sha256": sha256_bytes(text.encode()),
                        "corpus_retrieved_at": source["publisher_snapshot_retrieved_at"],
                        "approved_at": source["approved_at"],
                    }
                )
                ordinal += 1
        if ordinal == 0:
            raise CorpusError("approved source produced no chunks")
    ids = [row["chunk_id"] for row in output]
    if len(ids) != len(set(ids)):
        raise CorpusError("chunk IDs must be unique")
    return output


def _load_embedder(model_dir: Path, configuration: dict[str, Any]):
    model_path = model_dir / configuration["onnx_file"]
    tokenizer_path = model_dir / configuration["tokenizer_file"]
    if not model_path.is_file() or not tokenizer_path.is_file():
        raise CorpusError("pinned model or tokenizer is unavailable locally")
    if ort.__version__ != configuration["onnxruntime_version"] or tokenizers.__version__ != configuration["tokenizers_version"]:
        raise CorpusError("embedding runtime version drifted")
    if sha256_path(model_path) != configuration["onnx_sha256"] or sha256_path(tokenizer_path) != configuration["tokenizer_sha256"]:
        raise CorpusError("pinned model or tokenizer hash mismatch")
    options = ort.SessionOptions()
    options.intra_op_num_threads = configuration["intra_op_threads"]
    options.inter_op_num_threads = configuration["inter_op_threads"]
    options.enable_cpu_mem_arena = False
    options.enable_mem_pattern = False
    try:
        session = ort.InferenceSession(model_path, sess_options=options, providers=["CPUExecutionProvider"])
        tokenizer = Tokenizer.from_file(str(tokenizer_path))
    except Exception as exc:  # no opaque library content reaches callers/logs
        raise CorpusError("pinned embedding artifact is unusable") from exc
    tokenizer.enable_truncation(max_length=configuration["max_tokens"])
    tokenizer.enable_padding()
    return session, tokenizer


def embed_chunks(chunks: list[dict[str, Any]], model_dir: Path, configuration: dict[str, Any]) -> np.ndarray:
    session, tokenizer = _load_embedder(model_dir, configuration)
    outputs: list[np.ndarray] = []
    texts = [row["exact_text"] for row in chunks]
    for start in range(0, len(texts), configuration["batch_size"]):
        encoded = tokenizer.encode_batch(texts[start : start + configuration["batch_size"]])
        feed = {
            "input_ids": np.asarray([item.ids for item in encoded], dtype=np.int64),
            "attention_mask": np.asarray([item.attention_mask for item in encoded], dtype=np.int64),
            "token_type_ids": np.asarray([item.type_ids for item in encoded], dtype=np.int64),
        }
        outputs.append(session.run(None, feed)[0][:, 0, :])
    matrix = np.vstack(outputs).astype(np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    if matrix.shape[1] != configuration["vector_dimensions"] or np.any(norms == 0):
        raise CorpusError("embedding dimensions or normalization are invalid")
    return matrix / norms


def write_artifacts(output: Path, manifest: dict[str, Any], chunks: list[dict[str, Any]], model_dir: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    chunk_path = output / "chunks.jsonl"
    chunk_path.write_bytes(b"".join(canonical_json(row) for row in chunks))

    sqlite_path = output / "sparse.sqlite"
    connection = sqlite3.connect(sqlite_path)
    try:
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA page_size=4096")
        connection.execute("PRAGMA auto_vacuum=NONE")
        connection.execute("CREATE VIRTUAL TABLE chunks USING fts5(chunk_id UNINDEXED, document_id UNINDEXED, exact_text)")
        connection.executemany(
            "INSERT INTO chunks(chunk_id, document_id, exact_text) VALUES (?, ?, ?)",
            [(row["chunk_id"], row["document_id"], row["exact_text"]) for row in chunks],
        )
        connection.commit()
        connection.execute("VACUUM")
    finally:
        connection.close()

    vectors = embed_chunks(chunks, model_dir, manifest["dense_model"])
    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)
    faiss.write_index(index, str(output / "dense.faiss"))
    (output / "dense.ids.json").write_bytes(canonical_json([row["chunk_id"] for row in chunks]))

    artifact_hashes = {name: sha256_path(output / name) for name in ARTIFACTS if name != "artifact-manifest.json"}
    result = {
        "artifact_format_version": 1,
        "corpus_version": manifest["corpus_version"],
        "chunk_count": len(chunks),
        "chunk_set_sha256": sha256_path(chunk_path),
        "source_manifest_sha256": sha256_path(MANIFEST_PATH),
        "sqlite_runtime": sqlite3.sqlite_version,
        "dense_model": manifest["dense_model"],
        "artifacts": {name: {"sha256": digest, "bytes": (output / name).stat().st_size} for name, digest in artifact_hashes.items()},
    }
    (output / "artifact-manifest.json").write_bytes(canonical_json(result))
    return result


def validate_artifacts(output: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    try:
        artifact = json.loads((output / "artifact-manifest.json").read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise CorpusError("artifact manifest is unreadable") from exc
    if artifact.get("corpus_version") != manifest["corpus_version"] or artifact.get("source_manifest_sha256") != sha256_path(MANIFEST_PATH):
        raise CorpusError("artifact corpus version or manifest binding drifted")
    for name, expected in artifact.get("artifacts", {}).items():
        path = output / name
        if not path.is_file() or sha256_path(path) != expected.get("sha256"):
            raise CorpusError("artifact hash mismatch")
    rows = read_jsonl(output / "chunks.jsonl")
    if len(rows) != artifact.get("chunk_count") or any(sha256_bytes(row["exact_text"].encode()) != row["chunk_sha256"] for row in rows):
        raise CorpusError("chunk artifact integrity mismatch")
    ids = json.loads((output / "dense.ids.json").read_text())
    if ids != [row["chunk_id"] for row in rows]:
        raise CorpusError("dense artifact does not use the sparse chunk set")
    index = faiss.read_index(str(output / "dense.faiss"))
    if index.ntotal != len(rows) or index.d != manifest["dense_model"]["vector_dimensions"]:
        raise CorpusError("dense artifact does not match approved chunks")
    try:
        connection = sqlite3.connect(f"file:{output / 'sparse.sqlite'}?mode=ro", uri=True)
        count = connection.execute("SELECT count(*) FROM chunks").fetchone()[0]
    except sqlite3.DatabaseError as exc:
        raise CorpusError("sparse artifact is invalid") from exc
    finally:
        if "connection" in locals():
            connection.close()
    if count != len(rows):
        raise CorpusError("sparse artifact does not match approved chunks")
    return artifact


def validate_active_pointer(output: Path, artifact: dict[str, Any]) -> None:
    """Bind the checked-in active version to one immutable artifact manifest."""
    try:
        pointer = json.loads(ACTIVE_POINTER_PATH.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise CorpusError("active corpus pointer is unreadable") from exc
    expected = {"corpus_version", "artifact_manifest_sha256", "approved_at"}
    if set(pointer) != expected or pointer["corpus_version"] != artifact["corpus_version"]:
        raise CorpusError("active corpus pointer is invalid")
    if pointer["artifact_manifest_sha256"] != sha256_path(output / "artifact-manifest.json"):
        raise CorpusError("active corpus pointer does not bind the artifact")


def build(destination: Path, model_dir: Path) -> dict[str, Any]:
    manifest = load_manifest()
    snapshots = validate_inputs(manifest, read_jsonl(SOURCE_INPUT_PATH))
    chunks = build_chunks(manifest, snapshots)
    return write_artifacts(destination, manifest, chunks, model_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build or validate the approved local guideline corpus without network access.")
    parser.add_argument("command", choices=("build", "validate", "drift"))
    parser.add_argument("--output", type=Path, default=CORPUS_ROOT / "artifacts")
    parser.add_argument("--model-dir", type=Path)
    args = parser.parse_args(argv)
    started = time.monotonic()
    try:
        manifest = load_manifest()
        if args.command == "build":
            if args.model_dir is None:
                raise CorpusError("--model-dir is required for an offline build")
            artifact = build(args.output, args.model_dir)
        else:
            artifact = validate_artifacts(args.output, manifest)
            if args.output.resolve() == (CORPUS_ROOT / "artifacts").resolve():
                validate_active_pointer(args.output, artifact)
            if args.command == "drift":
                with tempfile.TemporaryDirectory(prefix="guideline-corpus-") as temporary:
                    if args.model_dir is None:
                        raise CorpusError("--model-dir is required for a deterministic drift check")
                    rebuilt = Path(temporary) / "artifacts"
                    build(rebuilt, args.model_dir)
                    for name in ARTIFACTS:
                        if sha256_path(args.output / name) != sha256_path(rebuilt / name):
                            raise CorpusError("deterministic artifact drift detected")
        elapsed = round((time.monotonic() - started) * 1000)
        print(json.dumps({"status": "ok", "corpus_version": artifact["corpus_version"], "chunk_count": artifact["chunk_count"], "build_or_check_ms": elapsed, "artifact_bytes": {name: item["bytes"] for name, item in artifact["artifacts"].items()}}, sort_keys=True))
        return 0
    except CorpusError as exc:
        print(json.dumps({"status": "rejected", "code": "guideline_corpus_invalid"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
