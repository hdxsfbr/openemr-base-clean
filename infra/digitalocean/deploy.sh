#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 || $# -gt 4 ]]; then
    printf 'Usage: %s <droplet-ip> <public-hostname> <tls-email> [openemr-base-image]\n' "$0" >&2
    exit 2
fi

droplet_ip="$1"
public_hostname="$2"
tls_email="$3"
openemr_image="${4:-openemr/openemr:8.1.1@sha256:796adaa7b3d03c76902e9afd2c1b420afc39f040425a68d4aefdf4ace285fa0b}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
ssh_target="deployer@${droplet_ip}"
ssh_options=(-o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new)

if [[ ! "${droplet_ip}" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]]; then
    printf 'Invalid IPv4 address.\n' >&2
    exit 2
fi

printf 'Waiting for cloud-init on %s...\n' "${droplet_ip}"
for attempt in $(seq 1 36); do
    # "done" is the normal end state. "error" means a runcmd step failed; the
    # bootstrap is still usable if Docker is present, so report and continue.
    status="$(ssh "${ssh_options[@]}" "${ssh_target}" 'cloud-init status 2>/dev/null | head -1' 2>/dev/null || true)"
    case "${status}" in
        *done*)
            break
            ;;
        *error*)
            if ssh "${ssh_options[@]}" "${ssh_target}" 'docker info >/dev/null 2>&1 && test -d /opt/agentforge'; then
                printf 'cloud-init finished with an error (see /var/log/cloud-init-output.log on the host); Docker is present, continuing.\n' >&2
                break
            fi
            ;;
    esac
    if [[ "${attempt}" -eq 36 ]]; then
        printf 'Timed out waiting for the host bootstrap (last status: %s).\n' "${status:-unreachable}" >&2
        exit 1
    fi
    sleep 5
done

# Runtime files, then the build contexts and the demo cohort. The cohort is a
# read-only bind mount for the one-shot demo-seed job and is never in an image.
ssh "${ssh_options[@]}" "${ssh_target}" 'mkdir -p /opt/agentforge/build/openemr /opt/agentforge/build/agent /opt/agentforge/demo && rm -rf /opt/agentforge/build/openemr/oe-module-copilot /opt/agentforge/build/agent/* /opt/agentforge/demo/cohort'
scp "${ssh_options[@]}" -r "${script_dir}/runtime/." "${ssh_target}:/opt/agentforge/"
scp "${ssh_options[@]}" "${repo_root}/infra/image/openemr.Dockerfile" "${ssh_target}:/opt/agentforge/build/openemr/Dockerfile"
# Source trees stream as tar so local environments, caches, build output, and tests never travel.
tar -C "${repo_root}/interface/modules/custom_modules" -cf - --exclude='__pycache__' oe-module-copilot \
    | ssh "${ssh_options[@]}" "${ssh_target}" 'tar -C /opt/agentforge/build/openemr -xf -'
tar -C "${repo_root}/agent" -cf - --exclude='.venv' --exclude='__pycache__' --exclude='.pytest_cache' --exclude='*.egg-info' --exclude='build' --exclude='tests' . \
    | ssh "${ssh_options[@]}" "${ssh_target}" 'tar -C /opt/agentforge/build/agent -xf -'
tar -C "${repo_root}/evals/fixtures" -cf - cohort \
    | ssh "${ssh_options[@]}" "${ssh_target}" 'tar -C /opt/agentforge/demo -xf -'

# Operator secrets from ~/.config/agentforge/ (skipped when absent), before start.sh.
"${script_dir}/push-secrets.sh" "${droplet_ip}" 2>/dev/null | grep '^pushed' || true

printf -v remote_command 'cd /opt/agentforge && chmod 700 start.sh openemr-entrypoint.sh && ./start.sh %q %q %q' \
    "${public_hostname}" "${tls_email}" "${openemr_image}"
# Values are escaped with printf %q before intentional client-side expansion.
# shellcheck disable=SC2029
ssh "${ssh_options[@]}" "${ssh_target}" "${remote_command}"
