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
for secret_name in mysql_root_password mysql_password openemr_admin_password copilot_delegation_secret; do
    if [[ ! -s "secrets/${secret_name}" ]]; then
        openssl rand -hex 24 > "secrets/${secret_name}"
    fi
done

# Operator-supplied secrets. Empty placeholders keep Compose happy; the agent's
# /ready reports "not_configured" until the operator writes the real values.
for secret_name in anthropic_api_key langfuse_public_key langfuse_secret_key; do
    if [[ ! -e "secrets/${secret_name}" ]]; then
        : > "secrets/${secret_name}"
    fi
done

printf 'PUBLIC_HOSTNAME=%s\nTLS_EMAIL=%s\nOPENEMR_IMAGE=%s\nDEMO_ANCHOR=%s\n' \
    "${public_hostname}" "${tls_email}" "${openemr_image}" "$(date +%F)" > .env
chmod 600 .env secrets/*

if [[ ! -d build/openemr/oe-module-copilot || ! -d build/agent ]]; then
    printf 'Build contexts missing under build/. Run deploy.sh from the repository, which copies them.\n' >&2
    exit 1
fi

docker compose pull database caddy
docker compose build --pull openemr agent
docker compose up --detach --wait --wait-timeout 600

# Register and enable the co-pilot module (idempotent).
docker compose --profile setup run --rm copilot-setup | tee "logs/copilot-setup-$(date +%F).log"

printf '\nDeployment started at https://%s\n' "${public_hostname}"
printf 'Agent health: https://%s/copilot-api/health\n' "${public_hostname}"
printf 'OpenEMR username: challenge-admin\n'
printf 'Read the generated password over SSH with:\n'
printf '  ssh deployer@<droplet-ip> cat /opt/agentforge/secrets/openemr_admin_password\n'
printf 'Seed the synthetic cohort (demo data only) with:\n'
printf '  cd /opt/agentforge && docker compose --profile demo run --rm demo-seed | tee logs/demo-seed-$(date +%%F).json\n'
