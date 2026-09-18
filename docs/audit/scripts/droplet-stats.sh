#!/usr/bin/env bash
# Droplet resource sampler for the load window (docs/FINAL_PUSH_PLAN.md, M2 task L2;
# run during M4 next to evals/load/run_load.py). Read-only over SSH: it runs
# `docker stats`, `docker top`, one SHOW GLOBAL STATUS, `free -m` and two
# /metrics scrapes on the host and changes nothing there. Every 5 s (default) it
# appends one CSV row; /metrics is saved at the start and at the end of the run,
# so a run per load level gives per-level counter deltas.
#
# The MariaDB password never leaves the database container: the SHOW GLOBAL
# STATUS runs inside it with `MYSQL_PWD` read from the file that the container's
# own MARIADB_PASSWORD_FILE names (infra/digitalocean/runtime/compose.yaml), and
# only the awk'd number comes back. Nothing here prints a secret.
#
# Usage:
#   docs/audit/scripts/droplet-stats.sh [--host deployer@137.184.4.22] [--duration SECONDS]
#       [--interval 5] [--label NAME] [--out FILE.csv] [--compose-dir /opt/agentforge]
#   --duration 0 (the default) samples until Ctrl-C. --help never contacts the host.
#
# Output: --out (default evals/load/results/droplet-stats-<UTC>[-<label>].csv) plus
# <out stem>-metrics-start.prom and <out stem>-metrics-end.prom.
#
# CSV columns: ts_utc,label,sample, then for openemr, database, agent and caddy:
# <name>_cpu_pct,<name>_mem_mib,<name>_mem_limit_mib,<name>_mem_pct,<name>_pids;
# then httpd_procs,httpd_cap,threads_connected,host_mem_total_mb,host_mem_used_mb,
# host_mem_available_mb,load1. httpd_cap is the Apache prefork MaxRequestWorkers
# the audit observed in the pinned image (docs/audit/architecture.md:265); no swap
# is configured on the Droplet, so free -m's Mem row is the whole story.
set -euo pipefail

HOST="deployer@137.184.4.22"
DURATION=0
INTERVAL=5
LABEL=""
OUT=""
COMPOSE_DIR="/opt/agentforge"
HTTPD_CAP=250
SERVICES=(openemr database agent caddy)
# Compose project name (infra/digitalocean/runtime/compose.yaml `name:`), for the label fallback below.
PROJECT="agentforge-openemr"

usage() {
    sed -n '2,/^set -euo pipefail$/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --host) HOST="${2:?--host needs a value}"; shift 2 ;;
        --duration) DURATION="${2:?--duration needs a value}"; shift 2 ;;
        --interval) INTERVAL="${2:?--interval needs a value}"; shift 2 ;;
        --label) LABEL="${2:?--label needs a value}"; shift 2 ;;
        --out) OUT="${2:?--out needs a value}"; shift 2 ;;
        --compose-dir) COMPOSE_DIR="${2:?--compose-dir needs a value}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
done

if [[ ! "${DURATION}" =~ ^[0-9]+$ ]]; then
    printf -- '--duration must be a whole number of seconds (0 = until interrupted)\n' >&2
    exit 2
fi
if [[ ! "${INTERVAL}" =~ ^[1-9][0-9]*$ ]]; then
    printf -- '--interval must be a positive whole number of seconds\n' >&2
    exit 2
fi
if [[ ! "${LABEL}" =~ ^[A-Za-z0-9._-]*$ ]]; then
    printf -- '--label may contain only letters, digits, dot, underscore and dash\n' >&2
    exit 2
fi
if [[ ! "${HOST}" =~ ^[A-Za-z0-9._-]+@[A-Za-z0-9.-]+$ ]]; then
    printf -- '--host must look like user@host\n' >&2
    exit 2
fi
if [[ ! "${COMPOSE_DIR}" =~ ^/[A-Za-z0-9._/-]+$ ]]; then
    printf -- '--compose-dir must be an absolute path\n' >&2
    exit 2
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../../.." && pwd)"
started_utc="$(date -u +%Y-%m-%dT%H%M%SZ)"
if [[ -z "${OUT}" ]]; then
    OUT="${repo_root}/evals/load/results/droplet-stats-${started_utc}${LABEL:+-${LABEL}}.csv"
fi
stem="${OUT%.csv}"
mkdir -p "$(dirname "${OUT}")"

# One multiplexed SSH connection for the whole run (deploy.sh uses the same
# ConnectTimeout and host-key policy); the control socket lives in a private
# temp dir and is closed on exit.
control_dir="$(mktemp -d)"
SSH_OPTS=(-o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o BatchMode=yes
    -o ControlMaster=auto -o ControlPath="${control_dir}/%C" -o ControlPersist=120)
REMOTE=(ssh "${SSH_OPTS[@]}" "${HOST}")
stop=0
cleanup() {
    ssh "${SSH_OPTS[@]}" -O exit "${HOST}" >/dev/null 2>&1 || true
    rm -rf "${control_dir}"
}
trap cleanup EXIT
trap 'stop=1' INT TERM

# Container names, resolved once from the compose project (each service has one container).
# The command string is built here on purpose; nothing in it is user input beyond the
# validated --compose-dir, and %q quotes that.
declare -A container=()
printf -v list_command 'cd %q && docker compose ps --format "{{.Service}} {{.Name}}" %s' "${COMPOSE_DIR}" "${SERVICES[*]}"
# Compose older than 2.20 rejects Go templates in `ps --format`; the compose labels on the
# containers carry the same service -> name mapping on any Docker version.
printf -v fallback_command 'docker ps --filter label=com.docker.compose.project=%q --format "{{.Label \"com.docker.compose.service\"}} {{.Names}}"' "${PROJECT}"
list_output="$("${REMOTE[@]}" "${list_command}" 2>/dev/null || "${REMOTE[@]}" "${fallback_command}")"
while read -r service name; do
    [[ -n "${service}" && -n "${name}" ]] && container["${service}"]="${name}"
done <<< "${list_output}"
for service in "${SERVICES[@]}"; do
    if [[ -z "${container[${service}]:-}" ]]; then
        printf 'Could not resolve the %s container in %s on %s\n' "${service}" "${COMPOSE_DIR}" "${HOST}" >&2
        exit 1
    fi
done

# The agent is on the internal frontend network only; scrape it from inside its own container.
snapshot_metrics() {
    local when="$1"
    printf -v scrape_command 'docker exec %q python -c %q' "${container[agent]}" \
        "import sys, urllib.request; sys.stdout.write(urllib.request.urlopen('http://127.0.0.1:8080/metrics', timeout=5).read().decode())"
    if ! "${REMOTE[@]}" "${scrape_command}" > "${stem}-metrics-${when}.prom"; then
        printf 'warning: /metrics snapshot (%s) failed; file left empty\n' "${when}" >&2
    fi
}

# Runs on the Droplet once per sample and prints one CSV fragment. Quoted heredoc:
# nothing expands locally; the container names arrive as positional arguments.
read -r -d '' REMOTE_SAMPLE <<'REMOTE' || true
set -euo pipefail
to_mib() {
    awk -v s="$1" 'BEGIN {
        v = s; sub(/[A-Za-z]+$/, "", v); u = s; sub(/^[0-9.]+/, "", u)
        m = 1
        if (u == "B") m = 1 / 1048576
        else if (u == "KiB" || u == "kB" || u == "KB") m = 1 / 1024
        else if (u == "GiB" || u == "GB") m = 1024
        else if (u == "TiB" || u == "TB") m = 1048576
        printf "%.1f", v * m
    }'
}
declare -A cpu mem lim pct pids
while IFS='|' read -r name cpu_raw mem_raw pct_raw pids_raw; do
    [[ -z "${name}" ]] && continue
    cpu["${name}"]="${cpu_raw%\%}"
    mem["${name}"]="$(to_mib "${mem_raw%% *}")"
    lim["${name}"]="$(to_mib "${mem_raw##* }")"
    pct["${name}"]="${pct_raw%\%}"
    pids["${name}"]="${pids_raw}"
done < <(docker stats --no-stream --format '{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}|{{.PIDs}}' "$@")
row=""
for name in "$@"; do
    row+="${cpu[${name}]:-NA},${mem[${name}]:-NA},${lim[${name}]:-NA},${pct[${name}]:-NA},${pids[${name}]:-NA},"
done
httpd="$(docker top "$1" 2>/dev/null | grep -c 'httpd' || true)"
threads="$(docker exec "$2" sh -c 'MYSQL_PWD="$(cat "${MARIADB_PASSWORD_FILE}")" exec mariadb -u"${MARIADB_USER}" -N -B -e "SHOW GLOBAL STATUS LIKE '"'"'Threads_connected'"'"'"' 2>/dev/null | awk '{print $2}' || true)"
read -r _ mem_total mem_used _ _ _ mem_avail < <(free -m | awk 'NR == 2')
load1="$(cut -d' ' -f1 /proc/loadavg)"
printf '%s%s,%s,%s,%s,%s,%s\n' "${row}" "${httpd:-NA}" "${threads:-NA}" "${mem_total:-NA}" "${mem_used:-NA}" "${mem_avail:-NA}" "${load1:-NA}"
REMOTE

header="ts_utc,label,sample"
for service in "${SERVICES[@]}"; do
    header+=",${service}_cpu_pct,${service}_mem_mib,${service}_mem_limit_mib,${service}_mem_pct,${service}_pids"
done
header+=",httpd_procs,httpd_cap,threads_connected,host_mem_total_mb,host_mem_used_mb,host_mem_available_mb,load1"
if [[ ! -s "${OUT}" ]]; then
    printf '%s\n' "${header}" > "${OUT}"
fi

duration_text=" until interrupted"
if [[ "${DURATION}" -gt 0 ]]; then
    duration_text=" for ${DURATION}s"
fi
printf 'Sampling %s every %ss%s -> %s\n' "${HOST}" "${INTERVAL}" "${duration_text}" "${OUT}" >&2
snapshot_metrics start
start_epoch="$(date +%s)"
# A sample that could not be taken (SSH interrupted, host busy) is a row of NA, never a short row.
na_fragment="$(printf 'NA,%.0s' {1..25})NA"
sample=0
while [[ "${stop}" -eq 0 ]]; do
    sample=$((sample + 1))
    if ! fragment="$("${REMOTE[@]}" bash -s -- "${container[openemr]}" "${container[database]}" "${container[agent]}" "${container[caddy]}" <<< "${REMOTE_SAMPLE}")"; then
        fragment="${na_fragment}"
    fi
    # httpd_cap goes in front of threads_connected: split the fragment after the httpd count.
    containers_part="$(cut -d, -f1-20 <<< "${fragment}")"
    httpd_procs="$(cut -d, -f21 <<< "${fragment}")"
    rest="$(cut -d, -f22- <<< "${fragment}")"
    ts_utc="$(date -u +%FT%TZ)"
    printf '%s,%s,%d,%s,%s,%s,%s\n' "${ts_utc}" "${LABEL}" "${sample}" "${containers_part}" "${httpd_procs:-NA}" "${HTTPD_CAP}" "${rest}" >> "${OUT}"
    now_epoch="$(date +%s)"
    if [[ "${DURATION}" -gt 0 && $((now_epoch - start_epoch)) -ge "${DURATION}" ]]; then
        break
    fi
    sleep "${INTERVAL}" || true
done
snapshot_metrics end
printf 'Wrote %d samples to %s (metrics: %s-metrics-start.prom, %s-metrics-end.prom)\n' "${sample}" "${OUT}" "${stem}" "${stem}" >&2
