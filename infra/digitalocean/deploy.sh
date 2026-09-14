#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 || $# -gt 4 ]]; then
    printf 'Usage: %s <droplet-ip> <public-hostname> <tls-email> [openemr-image]\n' "$0" >&2
    exit 2
fi

droplet_ip="$1"
public_hostname="$2"
tls_email="$3"
openemr_image="${4:-openemr/openemr:8.1.1@sha256:796adaa7b3d03c76902e9afd2c1b420afc39f040425a68d4aefdf4ace285fa0b}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ssh_target="deployer@${droplet_ip}"
ssh_options=(-o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new)

if [[ ! "${droplet_ip}" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]]; then
    printf 'Invalid IPv4 address.\n' >&2
    exit 2
fi

printf 'Waiting for cloud-init on %s...\n' "${droplet_ip}"
for attempt in $(seq 1 36); do
    if ssh "${ssh_options[@]}" "${ssh_target}" cloud-init status --wait >/dev/null 2>&1; then
        break
    fi
    if [[ "${attempt}" -eq 36 ]]; then
        printf 'Timed out waiting for the host bootstrap.\n' >&2
        exit 1
    fi
    sleep 5
done

scp "${ssh_options[@]}" -r "${script_dir}/runtime/." "${ssh_target}:/opt/agentforge/"

printf -v remote_command 'cd /opt/agentforge && chmod 700 start.sh openemr-entrypoint.sh && ./start.sh %q %q %q' \
    "${public_hostname}" "${tls_email}" "${openemr_image}"
# Values are escaped with printf %q before intentional client-side expansion.
# shellcheck disable=SC2029
ssh "${ssh_options[@]}" "${ssh_target}" "${remote_command}"
