#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    printf 'Usage: %s <public-hostname>\n' "$0" >&2
    exit 2
fi

public_hostname="$1"
base_url="https://${public_hostname}"

printf 'Checking valid public TLS and OpenEMR liveness at %s...\n' "${base_url}"
curl --fail --show-error --silent --location --max-time 30 \
    "${base_url}/meta/health/livez" >/dev/null
curl --fail --show-error --silent --location --max-time 30 \
    "${base_url}/" | grep -i 'openemr' >/dev/null

printf 'Smoke test passed: %s\n' "${base_url}"
