#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "${repo_root}"

test -f .githooks/pre-push || {
    printf 'Missing versioned hook: .githooks/pre-push\n' >&2
    exit 1
}
chmod +x .githooks/pre-push scripts/eval-local-gate.sh
git config core.hooksPath .githooks
printf 'Configured core.hooksPath=.githooks; pre-push runs the deterministic eval gate.\n'
