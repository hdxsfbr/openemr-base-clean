#!/usr/bin/env bash
# Copy operator secrets from ~/.config/agentforge/ to the Droplet and restart
# the agent. Never prints a value. Files that do not exist locally are skipped.
#
#   ./push-secrets.sh <droplet-ip>
#
# Local files (one value per file):
#   ~/.config/agentforge/anthropic_api_key
#   ~/.config/agentforge/anthropic_workspace_id   (only for an organization-level key)
#   ~/.config/agentforge/langfuse_public_key
#   ~/.config/agentforge/langfuse_secret_key
set -euo pipefail

if [[ $# -ne 1 ]]; then
    printf 'Usage: %s <droplet-ip>\n' "$0" >&2
    exit 2
fi
droplet_ip="$1"
if [[ ! "${droplet_ip}" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]]; then
    printf 'Invalid IPv4 address.\n' >&2
    exit 2
fi
ssh_target="deployer@${droplet_ip}"
ssh_options=(-o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new)
source_dir="${AGENTFORGE_SECRETS_DIR:-${HOME}/.config/agentforge}"

pushed=0
for name in anthropic_api_key anthropic_workspace_id langfuse_public_key langfuse_secret_key; do
    path="${source_dir}/${name}"
    if [[ ! -s "${path}" ]]; then
        printf 'skip   %s (no local file)\n' "${name}"
        continue
    fi
    # Stream the trimmed value; the agent runs as uid 10001, so the file is 0644
    # inside the 0700 secrets directory (Compose keeps host modes for file secrets).
    tr -d '\r\n' < "${path}" | ssh "${ssh_options[@]}" "${ssh_target}" \
        "umask 022 && cat > /opt/agentforge/secrets/${name}.tmp && mv /opt/agentforge/secrets/${name}.tmp /opt/agentforge/secrets/${name} && chmod 644 /opt/agentforge/secrets/${name}"
    printf 'pushed %s\n' "${name}"
    pushed=$((pushed + 1))
done

if [[ "${pushed}" -gt 0 ]]; then
    ssh "${ssh_options[@]}" "${ssh_target}" 'cd /opt/agentforge && docker compose up -d --force-recreate agent >/dev/null 2>&1 && sleep 8'
    printf 'Agent restarted. Readiness:\n'
    curl -s --max-time 20 "https://$(ssh "${ssh_options[@]}" "${ssh_target}" 'grep PUBLIC_HOSTNAME /opt/agentforge/.env | cut -d= -f2')/copilot-api/ready" \
        | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["status"]); [print("  " + x["name"] + ": " + x["detail"]) for x in d["dependencies"]]' || true
fi
