#!/usr/bin/env bash
# Encrypted backup of a deployed AgentForge OpenEMR host, taken over SSH from
# the operator's machine. Nothing runs unless --host is given: there is no
# default host on purpose, so the live Droplet is never implied.
#
#   ./backup.sh --host <droplet-ip-or-hostname> [--user deployer] [--out DIR]
#               [--encrypt age|gpg] [--helper-image IMAGE] [--dry-run] [--help]
#
# What is captured, as one tar stream produced on the host:
#   openemr.sql.gz     mariadb-dump --single-transaction of the openemr database,
#                      run inside the database container. The root password is
#                      read there, from the container's own
#                      MARIADB_ROOT_PASSWORD_FILE into MYSQL_PWD; it is never
#                      printed and never passed as a command-line argument.
#   openemr_sites.tar  the openemr_sites volume (sites/: sqlconf.php, documents)
#   agent_state.tar    the agent_state volume (LangGraph checkpoints, alerts state)
#   config.tar         /opt/agentforge/secrets and /opt/agentforge/.env
#   manifest.txt       host, time, compose images and container status
#   SHA256SUMS         checked by restore.sh before it touches a host
# The stream is encrypted on this machine with age (passphrase) when installed,
# else with gpg --symmetric (AES256), and written to
# ~/.config/agentforge/backups/<host>-<UTC stamp>.tar.<age|gpg> at mode 600.
# Never under the repository.
#
# WHY THE SECRETS ARE PART OF THE BACKUP. Every password in the stack is
# generated on the host by start.sh the first time it runs (openssl rand): the
# MariaDB root and openemr users, the OpenEMR admin, the delegation secret, and
# the shared demo clinician password (DEMO_PASSWORD, whose hashes sit in the
# database). Losing /opt/agentforge/secrets orphans the database volume (no
# credential can open MariaDB or OpenEMR any more) and the next start.sh
# generates a new DEMO_PASSWORD that matches no seeded user. restore.sh
# therefore restores the secrets first and re-initialises the database volume
# from them.
#
# Not captured: openemr_logs, openemr_ssl, caddy_data, caddy_config (they
# regenerate) and the raw database_data files (the dump replaces them). The
# agent state is copied hot, so a checkpoint mid-write may be inconsistent;
# conversations are ephemeral demo state.
#
# Requires locally: ssh, and age or gpg. The host needs only what deploy.sh
# installed. Volumes are read through a helper container; the default helper
# image is the agent image already built on the host, so nothing is pulled.
set -euo pipefail

usage() {
    cat <<'USAGE'
Usage: backup.sh --host <droplet-ip-or-hostname> [options]

Encrypted backup of a deployed AgentForge OpenEMR host over SSH: database
dump, openemr_sites and agent_state volumes, secrets and .env, in one archive
under ~/.config/agentforge/backups/ (mode 600). See the header of this file.

Options:
  --host HOST           Required. Never defaults; the live Droplet is never implied.
  --user USER           SSH user on the host (default: deployer).
  --out DIR             Archive directory (default: $AGENTFORGE_BACKUP_DIR or
                        ~/.config/agentforge/backups).
  --encrypt age|gpg     Encryption tool (default: age when installed, else gpg).
  --helper-image IMAGE  Image used to read the volumes on the host
                        (default: agentforge/copilot-agent:local, already built there).
  --dry-run             Print the commands, contact nothing, write nothing.
  -h, --help            This text.

Restore with: restore.sh --host HOST --archive <file>
USAGE
}

die() {
    printf 'backup.sh: %s\n' "$1" >&2
    exit 2
}

host=""
ssh_user="deployer"
out_dir="${AGENTFORGE_BACKUP_DIR:-${HOME}/.config/agentforge/backups}"
encrypt=""
helper_image="agentforge/copilot-agent:local"
dry_run=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --host)
            [[ $# -ge 2 ]] || die '--host needs a value'
            host="$2"
            shift 2
            ;;
        --user)
            [[ $# -ge 2 ]] || die '--user needs a value'
            ssh_user="$2"
            shift 2
            ;;
        --out)
            [[ $# -ge 2 ]] || die '--out needs a value'
            out_dir="$2"
            shift 2
            ;;
        --encrypt)
            [[ $# -ge 2 ]] || die '--encrypt needs a value'
            encrypt="$2"
            shift 2
            ;;
        --helper-image)
            [[ $# -ge 2 ]] || die '--helper-image needs a value'
            helper_image="$2"
            shift 2
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
[[ "${ssh_user}" =~ ^[a-z_][a-z0-9_-]*$ ]] || die 'invalid --user'
[[ "${helper_image}" =~ ^[A-Za-z0-9._/:@-]+$ ]] || die 'invalid --helper-image'

if [[ -z "${encrypt}" ]]; then
    if command -v age >/dev/null 2>&1; then
        encrypt="age"
    elif command -v gpg >/dev/null 2>&1; then
        encrypt="gpg"
    else
        die 'neither age nor gpg is installed'
    fi
fi

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
case "${encrypt}" in
    age)
        command -v age >/dev/null 2>&1 || die 'age is not installed'
        out_file="${out_dir}/${host}-${stamp}.tar.age"
        encrypt_cmd=(age --passphrase --output "${out_file}")
        ;;
    gpg)
        command -v gpg >/dev/null 2>&1 || die 'gpg is not installed'
        out_file="${out_dir}/${host}-${stamp}.tar.gpg"
        encrypt_cmd=(gpg --symmetric --cipher-algo AES256 --no-symkey-cache --output "${out_file}")
        ;;
    *)
        die '--encrypt must be age or gpg'
        ;;
esac

ssh_target="${ssh_user}@${host}"
ssh_options=(-o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new)

# Runs on the host through `bash -c`; all progress goes to stderr because
# stdout is the tar stream. The secret value only ever exists inside the
# database container's shell, read from the container's own environment.
remote_script="$(cat <<'REMOTE'
set -euo pipefail
cd /opt/agentforge
project="$(sed -n 's/^name:[[:space:]]*\([^[:space:]#]*\).*/\1/p' compose.yaml | head -n 1)"
if [[ -z "${project}" ]]; then
    printf 'compose.yaml has no top-level name:\n' >&2
    exit 1
fi
resolve_volume() {
    docker volume ls --quiet --filter "label=com.docker.compose.project=${project}" --filter "label=com.docker.compose.volume=$1"
}
sites_volume="$(resolve_volume openemr_sites)"
state_volume="$(resolve_volume agent_state)"
if [[ -z "${sites_volume}" || -z "${state_volume}" ]]; then
    printf 'openemr_sites or agent_state volume not found for project %s\n' "${project}" >&2
    exit 1
fi
work="$(mktemp -d /tmp/agentforge-backup.XXXXXX)"
trap 'rm -rf "${work}"' EXIT
printf 'backup: dumping the openemr database\n' >&2
docker compose exec -T database sh -c 'export MYSQL_PWD="$(cat "${MARIADB_ROOT_PASSWORD_FILE}")"; exec mariadb-dump --single-transaction --quick --routines --hex-blob --user=root openemr' | gzip -6 > "${work}/openemr.sql.gz"
printf 'backup: archiving volume %s\n' "${sites_volume}" >&2
docker run --rm --user 0:0 --volume "${sites_volume}:/data:ro" "${HELPER_IMAGE}" tar -C /data -cf - . > "${work}/openemr_sites.tar"
printf 'backup: archiving volume %s\n' "${state_volume}" >&2
docker run --rm --user 0:0 --volume "${state_volume}:/data:ro" "${HELPER_IMAGE}" tar -C /data -cf - . > "${work}/agent_state.tar"
printf 'backup: archiving secrets and .env\n' >&2
tar -C /opt/agentforge -cf "${work}/config.tar" secrets .env
{
    printf 'host: %s\nutc: %s\nproject: %s\nvolumes: %s %s\n\n' "$(hostname)" "$(date -u +%FT%TZ)" "${project}" "${sites_volume}" "${state_volume}"
    docker compose images
    printf '\n'
    docker compose ps
} > "${work}/manifest.txt"
(cd "${work}" && sha256sum openemr.sql.gz openemr_sites.tar agent_state.tar config.tar manifest.txt > SHA256SUMS)
printf 'backup: streaming %s from the host\n' "$(du -sh "${work}" | cut -f1)" >&2
tar -C "${work}" -cf - .
REMOTE
)"
printf -v remote_command 'HELPER_IMAGE=%q bash -c %q' "${helper_image}" "${remote_script}"

if [[ "${dry_run}" -eq 1 ]]; then
    printf '# dry run: nothing is executed and no host is contacted\n'
    printf 'umask 077 && mkdir -p %q\n' "${out_dir}"
    printf 'ssh -n %s %q %q \\\n    | %s\n' "${ssh_options[*]}" "${ssh_target}" "${remote_command}" "${encrypt_cmd[*]}"
    printf 'chmod 600 %q\n' "${out_file}"
    printf '\n# the script run on the host by bash -c:\n%s\n' "${remote_script}"
    exit 0
fi

umask 077
mkdir -p "${out_dir}"
[[ -e "${out_file}" ]] && die "refusing to overwrite ${out_file}"

printf 'backup: %s -> %s (%s)\n' "${ssh_target}" "${out_file}" "${encrypt}"
# The command string is built with printf %q on purpose and expands nowhere.
# shellcheck disable=SC2029
if ! ssh -n "${ssh_options[@]}" "${ssh_target}" "${remote_command}" | "${encrypt_cmd[@]}"; then
    rm -f "${out_file}"
    die 'backup failed; the partial archive was removed'
fi
chmod 600 "${out_file}"

printf '\nbackup written: %s\n' "${out_file}"
ls -l "${out_file}"
printf 'Keep the passphrase with the archive: without it the backup is unreadable.\n'
printf 'Restore with: %s --host %s --archive %q\n' "$(dirname "${BASH_SOURCE[0]}")/restore.sh" "${host}" "${out_file}"
