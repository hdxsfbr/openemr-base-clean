"""Fetch only the pinned local guideline artifacts during an image build."""

from __future__ import annotations

from pathlib import Path

from huggingface_hub import hf_hub_download

from .guideline_retriever import (
    BGE_FILE,
    BGE_REPO,
    BGE_REVISION,
    BGE_SHA256,
    RERANKER_FILE,
    RERANKER_REPO,
    RERANKER_REVISION,
    RERANKER_SHA256,
    _require_file_hash,
)


def main() -> None:
    for repo, revision, filename, expected in (
        (BGE_REPO, BGE_REVISION, BGE_FILE, BGE_SHA256),
        (RERANKER_REPO, RERANKER_REVISION, RERANKER_FILE, RERANKER_SHA256),
    ):
        common = {"repo_id": repo, "revision": revision}
        hf_hub_download(filename="tokenizer.json", **common)
        path = Path(hf_hub_download(filename=filename, **common))
        _require_file_hash(path, expected, "guideline model")


if __name__ == "__main__":
    main()
