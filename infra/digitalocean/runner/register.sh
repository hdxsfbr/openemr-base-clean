#!/usr/bin/env bash
# Register the runner Droplet with GitLab using a token read from a local file.
# The token is copied to the host, used once, and deleted; it is never printed.
#
#   ./runner/register.sh <runner-ip> ~/.config/agentforge/gitlab_runner_token [gitlab-url]
set -euo pipefail

ip="${1:?runner ip}"
token_file="${2:?path to the runner authentication token file}"
gitlab_url="${3:-https://labs.gauntletai.com}"
ssh_opts=(-o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new)
target="root@${ip}"

test -s "${token_file}" || { echo "token file is empty or missing: ${token_file}" >&2; exit 2; }

# Wait for cloud-init so gitlab-runner and docker exist.
for _ in $(seq 1 40); do
    if ssh "${ssh_opts[@]}" "${target}" 'cloud-init status 2>/dev/null | grep -q "status: done" && command -v gitlab-runner >/dev/null && docker info >/dev/null 2>&1'; then
        break
    fi
    sleep 15
done

scp "${ssh_opts[@]}" "${token_file}" "${target}:/root/.runner-token"
ssh "${ssh_opts[@]}" "${target}" bash -s "${gitlab_url}" <<'REMOTE'
set -euo pipefail
url="$1"
chmod 600 /root/.runner-token
gitlab-runner register --non-interactive \
  --url "${url}" \
  --token "$(cat /root/.runner-token)" \
  --executor docker \
  --docker-image alpine:3.20 \
  --docker-privileged=false \
  --docker-pull-policy if-not-present \
  --description "agentforge-ci-runner ($(hostname))" >/dev/null
rm -f /root/.runner-token
# One job at a time on a 1 GB host.
sed -i 's/^concurrent = .*/concurrent = 1/' /etc/gitlab-runner/config.toml
systemctl restart gitlab-runner
gitlab-runner verify 2>&1 | sed -E 's/(token|Token)[^ ]*/\1=<redacted>/g' | tail -3
REMOTE
echo "registered; the runner should show Online under the project's Runners settings"
