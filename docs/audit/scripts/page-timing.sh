#!/usr/bin/env bash
# Baseline page/API latency for the audit (performance track).
# Read-only apart from session state. Run only when no other audit work
# is using the stack. Credentials come from the environment and are never echoed.
#
# Usage: OE_USER=admin OE_PASS=... ./page-timing.sh [base_url] [runs] [pid]
set -euo pipefail

BASE="${1:-http://localhost:8300}"
RUNS="${2:-20}"
PID="${3:-1}"
: "${OE_USER:?set OE_USER}" "${OE_PASS:?set OE_PASS}"

JAR="$(mktemp)"
trap 'rm -f "$JAR"' EXIT
C=(curl -sk -b "$JAR" -c "$JAR" -o /dev/null)

"${C[@]}" "$BASE/interface/login/login.php?site=default"
"${C[@]}" -X POST "$BASE/interface/main/main_screen.php?auth=login&site=default" \
    --data-urlencode "new_login_session_management=1" \
    --data-urlencode "languageChoice=1" \
    --data-urlencode "authUser=$OE_USER" \
    --data-urlencode "clearPass=$OE_PASS"

declare -A PAGES=(
    [login_page]="interface/login/login.php?site=default"
    [patient_dashboard]="interface/patient_file/summary/demographics.php?set_pid=$PID"
    [encounter_history]="interface/patient_file/history/encounters.php"
    [readyz]="meta/health/readyz"
)

printf "%-20s %6s %8s %8s %8s %8s %8s\n" page n p50_ms p95_ms max_ms bytes http
for name in "${!PAGES[@]}"; do
    url="$BASE/${PAGES[$name]}"
    times=()
    for _ in $(seq "$RUNS"); do
        read -r t size code < <("${C[@]}" -w "%{time_total} %{size_download} %{http_code}\n" "$url")
        times+=("$t")
    done
    printf "%s\n" "${times[@]}" | sort -n | awk -v n="$RUNS" -v name="$name" -v size="$size" -v code="$code" '
        { a[NR] = $1 * 1000 }
        END {
            p50 = a[int((n - 1) * 0.50) + 1]; p95 = a[int((n - 1) * 0.95) + 1]
            printf "%-20s %6d %8.1f %8.1f %8.1f %8d %8s\n", name, n, p50, p95, a[n], size, code
        }'
done
