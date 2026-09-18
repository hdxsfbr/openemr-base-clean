#!/usr/bin/env bash
# Restore a backup.sh archive onto a deployed AgentForge OpenEMR host, over SSH
# from the operator's machine. --host is mandatory and never defaults, so the
# live Droplet is never implied.
#
#   ./restore.sh --host <droplet-ip-or-hostname> --archive <file.tar.age|.tar.gpg>
#                [--user deployer] [--skip-env] [--helper-image IMAGE]
#                [--yes] [--dry-run] [--help]
#
# Order, and why:
#   1. Decrypt the archive into a 0700 temp dir on this machine and verify
#      SHA256SUMS. Nothing on the host is touched until the archive is intact.
#   2. Stop openemr, agent and alerts (those that exist in the host's compose file).
#   3. Untar secrets/ and .env into /opt/agentforge. Secrets first: every password
#      of the stack lives there (see backup.sh). --skip-env keeps the host's own
#      .env, for restoring one host's archive onto a host with another hostname.
#   4. Re-initialise the database volume from the restored secrets: remove the
#      database container, delete database_data, `up --wait database`. MariaDB
#      reads MARIADB_*_PASSWORD_FILE only into an empty volume, so a volume
#      initialised under other secrets (a fresh Droplet, or a host whose secrets
#      directory was lost) can never accept the restored credentials; a re-init
#      always can.
#   5. Load openemr.sql.gz through `mariadb` inside the database container
#      (MYSQL_PWD read from the container's own MARIADB_ROOT_PASSWORD_FILE,
#      never printed or passed as an argument).
#   6. Replace the contents of the openemr_sites and agent_state volumes.
#   7. docker compose up --detach --wait, then print docker compose ps.
#
# Step 4 deletes the database volume: run backup.sh first if the host's current
# state has any value. The host must have been deployed once (deploy.sh) so the
# compose project, images and volumes exist. The DEMO_PASSWORD after a restore
# is the one in the archive's secrets, not the one the host had before.
set -euo pipefail

usage() {
    cat <<'USAGE'
Usage: restore.sh --host <droplet-ip-or-hostname> --archive <file> [options]

Restore a backup.sh archive onto a deployed AgentForge OpenEMR host over SSH:
secrets and .env, a re-initialised database loaded from the dump, then the
openemr_sites and agent_state volumes. See the header of this file for the
order and the reasons. Deletes the host's database volume (back it up first).

Options:
  --host HOST           Required. Never defaults; the live Droplet is never implied.
  --archive FILE        Required. A backup.sh archive ending in .age or .gpg.
  --user USER           SSH user on the host (default: deployer).
  --skip-env            Keep the host's own /opt/agentforge/.env (different hostname).
  --helper-image IMAGE  Image used to write the volumes on the host
                        (default: agentforge/copilot-agent:local, already built there).
  --yes                 Skip the confirmation prompt.
  --dry-run             Print the commands, decrypt nothing, contact nothing.
  -h, --help            This text.
USAGE
}

die() {
    printf 'restore.sh: %s\n' "$1" >&2
    exit 2
}

host=""
archive=""
ssh_user="deployer"
skip_env=0
helper_image="agentforge/copilot-agent:local"
assume_yes=0
dry_run=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --host)
            [[ $# -ge 2 ]] || die '--host needs a value'
            host="$2"
            shift 2
            ;;
        --archive)
            [[ $# -ge 2 ]] || die '--archive needs a value'
            archive="$2"
            shift 2
            ;;
        --user)
            [[ $# -ge 2 ]] || die '--user needs a value'
            ssh_user="$2"
            shift 2
            ;;
        --skip-env)
            skip_env=1
            shift
            ;;
        --helper-image)
            [[ $# -ge 2 ]] || die '--helper-image needs a value'
            helper_image="$2"
            shift 2
            ;;
        --yes)
            assume_yes=1
            shift
            ;;
        --dry-run)
            dry_run=1
            shift
            ;;
        -h | --help)
            usage
            exit 0
            ;;
        *)
            usage >&2
            die "unknown argument: $1"
            ;;
    esac
done

[[ -n "${host}" ]] || die 'pass --host explicitly; this script never assumes a host (see --help)'
[[ "${host}" =~ ^[A-Za-z0-9.-]+$ ]] || die 'invalid --host'
[[ -n "${archive}" ]] || die 'pass --archive (see --help)'
[[ -f "${archive}" ]] || die "archive not found: ${archive}"
[[ "${ssh_user}" =~ ^[a-z_][a-z0-9_-]*$ ]] || die 'invalid --user'
[[ "${helper_image}" =~ ^[A-Za-z0-9._/:@-]+$ ]] || die 'invalid --helper-image'

backup_dir="${AGENTFORGE_BACKUP_DIR:-${HOME}/.config/agentforge/backups}"
umask 077
mkdir -p "${backup_dir}"
work="$(mktemp -d "${backup_dir}/restore.XXXXXX")"
trap 'rm -rf "${work}"' EXIT

case "${archive}" in
    *.age)
        command -v age >/dev/null 2>&1 || die 'age is not installed'
        decrypt_cmd=(age --decrypt --output "${work}/bundle.tar" "${archive}")
        ;;
    *.gpg)
        command -v gpg >/dev/null 2>&1 || die 'gpg is not installed'
        decrypt_cmd=(gpg --decrypt --output "${work}/bundle.tar" "${archive}")
        ;;
    *)
        die 'the archive must end in .age or .gpg (written by backup.sh)'
        ;;
esac

ssh_target="${ssh_user}@${host}"
ssh_options=(-o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new)
members=(openemr.sql.gz openemr_sites.tar agent_state.tar config.tar manifest.txt SHA256SUMS)

# Remote snippets. Each runs through `bash -c` on the host; the command
# strings are built with printf %q and expand nowhere else.
remote_resolve="$(cat <<'REMOTE'
set -euo pipefail
cd /opt/agentforge
project="$(sed -n 's/^name:[[:space:]]*\([^[:space:]#]*\).*/\1/p' compose.yaml | head -n 1)"
if [[ -z "${project}" ]]; then
    printf 'compose.yaml has no top-level name:\n' >&2
    exit 1
fi
for volume in database_data openemr_sites agent_state; do
    name="$(docker volume ls --quiet --filter "label=com.docker.compose.project=${project}" --filter "label=com.docker.compose.volume=${volume}")"
    if [[ -z "${name}" ]]; then
        printf 'volume %s not found for project %s (deploy the host once first)\n' "${volume}" "${project}" >&2
        exit 1
    fi
    printf '%s\n' "${name}"
done
REMOTE
)"
remote_stop="$(cat <<'REMOTE'
set -euo pipefail
cd /opt/agentforge
mapfile -t present < <(docker compose config --services | grep -x -e openemr -e agent -e alerts)
docker compose stop "${present[@]}"
REMOTE
)"
if [[ "${skip_env}" -eq 1 ]]; then
    remote_config='cd /opt/agentforge && tar -C /opt/agentforge --exclude=.env -xpf - && chmod 700 secrets'
else
    remote_config='cd /opt/agentforge && tar -C /opt/agentforge -xpf - && chmod 700 secrets && chmod 600 .env'
fi
remote_load="cd /opt/agentforge && docker compose exec -T database sh -c 'export MYSQL_PWD=\"\$(cat \"\${MARIADB_ROOT_PASSWORD_FILE}\")\"; exec mariadb --user=root openemr'"
remote_up='cd /opt/agentforge && docker compose up --detach --wait --wait-timeout 600 && docker compose ps'

# run_step DESCRIPTION REMOTE_COMMAND [INPUT_FILE]; the file, when given, is
# the host command's stdin. A dry run only prints, so it never opens the file.
run_step() {
    local description="$1"
    local remote="$2"
    local input="${3:-/dev/null}"
    printf '\nrestore: %s\n' "${description}" >&2
    if [[ "${dry_run}" -eq 1 ]]; then
        printf 'ssh %s %q bash -c %q < %q\n' "${ssh_options[*]}" "${ssh_target}" "${remote}" "${input}"
        return 0
    fi
    local command
    printf -v command 'bash -c %q' "${remote}"
    # Built with printf %q; nothing expands on the client side.
    # shellcheck disable=SC2029
    ssh "${ssh_options[@]}" "${ssh_target}" "${command}" <"${input}"
}

if [[ "${dry_run}" -eq 1 ]]; then
    printf '# dry run: nothing is executed, decrypted, or contacted\n'
    printf '%s\n' "${decrypt_cmd[*]}"
    printf 'tar -C %q -xf %q/bundle.tar && (cd %q && sha256sum -c SHA256SUMS)\n' "${work}" "${work}" "${work}"
    database_volume='<database_data volume>'
    sites_volume='<openemr_sites volume>'
    state_volume='<agent_state volume>'
    printf '\n# volume names are resolved on the host with:\n%s\n' "${remote_resolve}"
else
    printf 'restore: decrypting %s\n' "${archive}"
    "${decrypt_cmd[@]}"
    tar -C "${work}" -xf "${work}/bundle.tar"
    for member in "${members[@]}"; do
        [[ -f "${work}/${member}" ]] || die "archive is missing ${member}"
    done
    (cd "${work}" && sha256sum --check --quiet SHA256SUMS) || die 'SHA256SUMS check failed; the archive is damaged'
    printf '\n--- manifest ---\n'
    cat "${work}/manifest.txt"
    printf -- '--- end manifest ---\n\n'

    printf -v resolve_command 'bash -c %q' "${remote_resolve}"
    # shellcheck disable=SC2029
    resolved="$(ssh -n "${ssh_options[@]}" "${ssh_target}" "${resolve_command}")"
    mapfile -t volumes <<< "${resolved}"
    [[ "${#volumes[@]}" -eq 3 ]] || die 'could not resolve the three volume names on the host'
    database_volume="${volumes[0]}"
    sites_volume="${volumes[1]}"
    state_volume="${volumes[2]}"
    for volume in "${database_volume}" "${sites_volume}" "${state_volume}"; do
        [[ "${volume}" =~ ^[A-Za-z0-9_.-]+$ ]] || die "unexpected volume name from the host: ${volume}"
    done

    if [[ "${assume_yes}" -ne 1 ]]; then
        printf 'This deletes the database volume %s on %s and replaces secrets, .env,\n' "${database_volume}" "${host}"
        printf 'openemr_sites and agent_state with the archive contents.\n'
        read -r -p "Type the host (${host}) to continue: " answer </dev/tty
        [[ "${answer}" == "${host}" ]] || die 'aborted'
    fi
fi

remote_reinit="cd /opt/agentforge && docker compose rm --stop --force database && docker volume rm ${database_volume} && docker compose up --detach --wait --wait-timeout 300 database"
remote_sites="docker run --rm --interactive --user 0:0 --volume ${sites_volume}:/data ${helper_image} sh -c 'find /data -mindepth 1 -delete && tar -C /data -xpf -'"
remote_state="docker run --rm --interactive --user 0:0 --volume ${state_volume}:/data ${helper_image} sh -c 'find /data -mindepth 1 -delete && tar -C /data -xpf -'"

run_step 'stopping openemr, agent, alerts' "${remote_stop}"
run_step 'restoring secrets and .env' "${remote_config}" "${work}/config.tar"
run_step 're-initialising the database volume from the restored secrets' "${remote_reinit}"
printf '\nrestore: loading the database dump\n' >&2
if [[ "${dry_run}" -eq 1 ]]; then
    printf 'gunzip -c %q/openemr.sql.gz | ssh %s %q bash -c %q\n' "${work}" "${ssh_options[*]}" "${ssh_target}" "${remote_load}"
else
    printf -v load_command 'bash -c %q' "${remote_load}"
    # shellcheck disable=SC2029
    gunzip -c "${work}/openemr.sql.gz" | ssh "${ssh_options[@]}" "${ssh_target}" "${load_command}"
fi
run_step 'restoring the openemr_sites volume' "${remote_sites}" "${work}/openemr_sites.tar"
run_step 'restoring the agent_state volume' "${remote_state}" "${work}/agent_state.tar"
run_step 'starting the stack' "${remote_up}"

printf '\nrestore finished on %s. Verify with:\n' "${host}"
printf '  %s/smoke.sh <public-hostname>\n' "$(dirname "${BASH_SOURCE[0]}")"
printf '  curl -s https://<public-hostname>/copilot-api/ready\n'
printf 'The demo clinician password is now the one in the archive: ssh %s cat /opt/agentforge/secrets/demo_user_password\n' "${ssh_target}"
