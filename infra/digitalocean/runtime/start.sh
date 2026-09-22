#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
    printf 'Usage: %s <public-hostname> <tls-email> [openemr-base-image]\n' "$0" >&2
    exit 2
fi

public_hostname="$1"
tls_email="$2"
openemr_image="${3:-openemr/openemr:8.1.1@sha256:796adaa7b3d03c76902e9afd2c1b420afc39f040425a68d4aefdf4ace285fa0b}"

if [[ ! "${public_hostname}" =~ ^[A-Za-z0-9.-]+$ ]]; then
    printf 'Invalid public hostname.\n' >&2
    exit 2
fi

if [[ ! "${tls_email}" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]]; then
    printf 'Invalid TLS email address.\n' >&2
    exit 2
fi

if [[ ! "${openemr_image}" =~ ^[A-Za-z0-9._/:@-]+$ ]]; then
    printf 'Invalid OpenEMR image reference.\n' >&2
    exit 2
fi

cd "$(dirname "$0")"
umask 077
mkdir -p secrets logs

# Generated on the host; never in cloud-init, Terraform state, or the repository.
for secret_name in mysql_root_password mysql_password openemr_admin_password copilot_delegation_secret demo_user_password; do
    if [[ ! -s "secrets/${secret_name}" ]]; then
        openssl rand -hex 24 > "secrets/${secret_name}"
    fi
done

# Operator-supplied secrets. Empty placeholders keep Compose happy; the agent's
# /ready reports "not_configured" until the operator writes the real values.
for secret_name in anthropic_api_key anthropic_workspace_id langfuse_public_key langfuse_secret_key slack_alert_webhook; do
    if [[ ! -e "secrets/${secret_name}" ]]; then
        : > "secrets/${secret_name}"
    fi
done

today="$(date +%F)"
printf 'PUBLIC_HOSTNAME=%s\nTLS_EMAIL=%s\nOPENEMR_IMAGE=%s\nDEMO_ANCHOR=%s\n' \
    "${public_hostname}" "${tls_email}" "${openemr_image}" "${today}" > .env
chmod 600 .env secrets/*
# Compose file secrets are bind mounts that keep the host mode (the `mode`
# attribute applies to swarm only). The agent runs as uid 10001 and must read
# these four; the directory itself is 0700, so only this user and root see them.
chmod 644 secrets/anthropic_api_key secrets/anthropic_workspace_id secrets/copilot_delegation_secret secrets/langfuse_public_key secrets/langfuse_secret_key secrets/slack_alert_webhook
chmod 700 secrets

if [[ ! -d build/openemr/oe-module-copilot || ! -d build/agent ]]; then
    printf 'Build contexts missing under build/. Run deploy.sh from the repository, which copies them.\n' >&2
    exit 1
fi
build_commit="$(tr -d '\r\n' < build/agent/BUILD_COMMIT 2>/dev/null || true)"
if [[ ! "${build_commit}" =~ ^[a-f0-9]{40}$ ]]; then
    printf 'Missing or invalid candidate BUILD_COMMIT; deploy.sh must copy a committed runtime tree.\n' >&2
    exit 1
fi

docker compose pull database caddy
docker compose build --pull openemr agent
# This setup-only command downloads no unpinned artifact: the provisioner
# atomically verifies every full SHA-256. Its named volume is read-only in the
# running agent service, so deployment never ships local model binaries.
docker compose --profile guideline-models run --rm guideline-model-provision
docker compose up --detach --wait --wait-timeout 600

# Evidence only: image IDs are immutable local content identities; no patient,
# request, secret, or model content is recorded here.
agent_image_id="$(docker image inspect --format '{{.Id}}' agentforge/copilot-agent:local)"
openemr_image_id="$(docker image inspect --format '{{.Id}}' agentforge/openemr:local)"
printf '{"candidate_commit":"%s","agent_image_id":"%s","openemr_image_id":"%s"}\n' \
    "${build_commit}" "${agent_image_id}" "${openemr_image_id}" | tee "logs/deployment-identity-${build_commit}.json"

# Caddy can stay in Created when its depends_on on openemr resolves after the
# --wait window has returned (seen 2026-09-15 on a redeploy that rebuilt from
# scratch); an explicit second up starts it. Harmless when it is already up.
docker compose up --detach --wait --wait-timeout 120 caddy

# Fail loudly if any long-running service is not running. The one-shot jobs
# (copilot-setup, demo-seed) are behind profiles and are not expected here.
required_services=(database openemr agent caddy alerts)
running_services="$(docker compose ps --services --status running)"
missing_services=()
for service_name in "${required_services[@]}"; do
    if ! grep -qx "${service_name}" <<< "${running_services}"; then
        missing_services+=("${service_name}")
    fi
done
if [[ "${#missing_services[@]}" -gt 0 ]]; then
    printf 'Not running after start: %s\n' "${missing_services[*]}" >&2
    docker compose ps >&2
    exit 1
fi

# The public edge must answer before this script reports success. Six attempts
# ten seconds apart cover a Caddy restart; a first certificate issuance on a
# brand-new hostname can take longer, in which case rerun deploy.sh (idempotent).
# This gate needs curl on the host: cloud-init.yaml.tftpl installs it alongside Docker.
livez_url="https://${public_hostname}/meta/health/livez"
for attempt in $(seq 1 6); do
    if curl --fail --silent --show-error --location --max-time 20 "${livez_url}" >/dev/null; then
        break
    fi
    if [[ "${attempt}" -eq 6 ]]; then
        printf 'Public liveness probe failed after %s attempts: %s\n' "${attempt}" "${livez_url}" >&2
        docker compose ps >&2
        docker compose logs --tail 20 caddy >&2
        exit 1
    fi
    sleep 10
done

# Register and enable the co-pilot module (idempotent).
docker compose --profile setup run --rm copilot-setup | tee "logs/copilot-setup-${today}.log"

printf '\nDeployment started at https://%s\n' "${public_hostname}"
printf 'Agent health: https://%s/copilot-api/health\n' "${public_hostname}"
printf 'Alert evaluator (one heartbeat or alert line per 300 s): docker compose logs --tail 5 alerts\n'
printf 'OpenEMR username: challenge-admin\n'
printf 'Read the generated password over SSH with:\n'
printf '  ssh deployer@<droplet-ip> cat /opt/agentforge/secrets/openemr_admin_password\n'
printf 'Seed the demo users and synthetic cohort (demo data only) with:\n'
# A literal command for the operator; the $(date) is meant to expand on their shell.
# shellcheck disable=SC2016
printf '  cd /opt/agentforge && docker compose --profile demo run --rm demo-seed | tee logs/demo-seed-$(date +%%F).json\n'
printf 'Demo clinician password (physician, audit-physician, audit-nurse, audit-frontdesk):\n'
printf '  ssh deployer@<droplet-ip> cat /opt/agentforge/secrets/demo_user_password\n'
