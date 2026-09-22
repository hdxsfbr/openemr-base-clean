#!/usr/bin/env python3
"""Explicit setup-time downloader for the pinned local guideline models.

This script is never imported by the service.  Production/runtime code only
opens already-provisioned local files and fails closed when they are absent or
altered.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.request import urlopen


FILES = (
    ("BAAI/bge-small-en-v1.5", "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a", "onnx/model.onnx", "828e1496d7fabb79cfa4dcd84fa38625c0d3d21da474a00f08db0f559940cf35", "bge"),
    ("BAAI/bge-small-en-v1.5", "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a", "tokenizer.json", "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66", "bge"),
    ("cross-encoder/ms-marco-MiniLM-L6-v2", "233902d25c440f23af6f7d6e94d2946bac0bee0a", "onnx/model_quint8_avx2.onnx", "c80a8b34256ea453093d612e3ac48d3d965a0c0a48c7906709af8b8e28461bf9", "reranker"),
    ("cross-encoder/ms-marco-MiniLM-L6-v2", "233902d25c440f23af6f7d6e94d2946bac0bee0a", "tokenizer.json", "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66", "reranker"),
)


def digest(path: Path) -> str:
    value = sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def provision(destination: Path) -> None:
    for repository, revision, filename, expected, directory in FILES:
        target = destination / directory / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file() and digest(target) == expected:
            continue
        url = f"https://huggingface.co/{repository}/resolve/{revision}/{filename}"
        with urlopen(url, timeout=60) as response, NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
            for block in iter(lambda: response.read(1024 * 1024), b""):
                temporary.write(block)
            candidate = Path(temporary.name)
        if digest(candidate) != expected:
            candidate.unlink(missing_ok=True)
            raise RuntimeError("downloaded model artifact failed its pinned SHA-256 check")
        candidate.replace(target)


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision hash-bound guideline model artifacts during setup only.")
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    provision(args.destination)
    print('{"status":"ok","artifacts":4}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
