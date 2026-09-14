#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    printf 'Usage: %s <tls-email>\n' "$0" >&2
    exit 2
fi

tls_email="$1"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${script_dir}"

cleanup() {
    exit_code=$?
    if [[ "${KEEP_INFRA:-0}" == "1" ]]; then
        printf 'KEEP_INFRA=1; resources remain billable until explicitly destroyed.\n' >&2
    else
        ./destroy.sh --yes || printf 'Automatic destroy failed; run ./destroy.sh --yes immediately.\n' >&2
    fi
    exit "${exit_code}"
}
trap cleanup EXIT

./tf.sh init
./tf.sh apply -auto-approve

droplet_ip="$(./tf.sh output -raw ipv4_address)"
public_hostname="$(./tf.sh output -raw smoke_hostname)"

./deploy.sh "${droplet_ip}" "${public_hostname}" "${tls_email}"
./smoke.sh "${public_hostname}"

printf 'Smoke cycle succeeded; tearing down billable resources now.\n'
