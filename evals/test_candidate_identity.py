"""Candidate deployment identity must match the pipeline commit and image."""

from __future__ import annotations

import json

import candidate_identity


class _Response:
    def __init__(self, payload: dict[str, str]) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode()


def test_candidate_identity_accepts_only_the_exact_commit_and_image(monkeypatch) -> None:
    image = "registry.example/copilot@sha256:" + "a" * 64
    monkeypatch.setattr(
        candidate_identity.request,
        "urlopen",
        lambda *_args, **_kwargs: _Response(
            {"candidate_commit": "abc123", "runtime_image": image}
        ),
    )

    assert candidate_identity.verify("https://candidate.example", "abc123", image) == []
    assert candidate_identity.verify("https://candidate.example", "stale", image) == [
        "deployed candidate_commit abc123 != expected stale"
    ]
