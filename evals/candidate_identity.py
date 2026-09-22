#!/usr/bin/env python3
"""Fail unless a candidate environment reports the exact pipeline identity."""

from __future__ import annotations

import argparse
import json
from urllib import error, request


def verify(base_url: str, expected_commit: str, expected_image: str) -> list[str]:
    url = base_url.rstrip("/") + "/copilot-api/health"
    try:
        with request.urlopen(url, timeout=20) as response:  # noqa: S310 - caller supplies the CI candidate URL
            payload = json.loads(response.read())
    except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return [f"candidate identity endpoint unavailable: {exc.__class__.__name__}"]
    if not isinstance(payload, dict):
        return ["candidate identity endpoint returned a non-object"]
    failures: list[str] = []
    if payload.get("candidate_commit") != expected_commit:
        failures.append(
            f"deployed candidate_commit {payload.get('candidate_commit')} != expected {expected_commit}"
        )
    if payload.get("runtime_image") != expected_image:
        failures.append(
            f"deployed runtime_image {payload.get('runtime_image')} != expected {expected_image}"
        )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url")
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-image", required=True)
    args = parser.parse_args(argv)
    failures = verify(args.base_url, args.expected_commit, args.expected_image)
    for failure in failures:
        print(f"IDENTITY ERROR: {failure}")
    if not failures:
        print(
            f"candidate identity matched commit={args.expected_commit} "
            f"image={args.expected_image}"
        )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
