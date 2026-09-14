#!/usr/bin/env bash
set -euo pipefail

if command -v terraform >/dev/null 2>&1; then
    exec terraform "$@"
fi

if command -v tofu >/dev/null 2>&1; then
    exec tofu "$@"
fi

printf 'Terraform or OpenTofu is required. See docs/deployment/digitalocean.md.\n' >&2
exit 1
