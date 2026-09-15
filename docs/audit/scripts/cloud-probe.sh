#!/usr/bin/env bash
# Public-deployment audit probe. Records status codes, sizes, headers, and
# timings only: never response bodies of sensitive paths, never secrets.
#
# Usage: ./cloud-probe.sh <public_hostname> <droplet_ip> [runs]
set -euo pipefail

HOST="${1:?public hostname}"
IP="${2:?droplet ip}"
RUNS="${3:-20}"
BASE="https://$HOST"

echo "# Cloud probe — $(date -u +%FT%TZ) — host=<sslip hostname> commit=$(git rev-parse --short HEAD 2>/dev/null || echo n/a)"

echo; echo "## 1. File exposure through Caddy (status + bytes only)"
for p in \
    docker/development-easy/docker-compose.yml \
    docker/library/sql-ssl-certs-keys/easy/server-key.pem \
    tests/Tests/data/Unit/Common/Auth/Grant/openemr-rsa384-private.key \
    composer.lock composer.json package.json .env.example \
    sites/default/sqlconf.php sites/default/documents/ \
    admin.php setup.php sql_upgrade.php acl_upgrade.php \
    phpinfo.php interface/main/backup.php; do
    printf "%-72s " "$p"
    curl -sk -o /dev/null --max-time 15 -w "HTTP %{http_code} %{size_download}B\n" "$BASE/$p"
done

echo; echo "## 2. API / OAuth surface"
for p in apis/default/fhir/metadata apis/default/fhir/.well-known/smart-configuration \
         oauth2/default/.well-known/openid-configuration apis/default/api/patient apis/default/fhir/Patient \
         meta/health/livez meta/health/readyz; do
    printf "%-60s " "$p"
    curl -sk -o /dev/null --max-time 15 -w "HTTP %{http_code} %{size_download}B\n" "$BASE/$p"
done
curl -sk --max-time 15 "$BASE/oauth2/default/.well-known/openid-configuration" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print("openid-configuration: not JSON"); sys.exit(0)
print("registration_endpoint advertised:", bool(d.get("registration_endpoint")))
print("grant_types_supported:", d.get("grant_types_supported"))
print("scopes_supported count:", len(d.get("scopes_supported", [])))'
echo "readyz body:"; curl -sk --max-time 15 "$BASE/meta/health/readyz"; echo

echo; echo "## 3. Headers and cookies (values redacted)"
curl -skI --max-time 15 "$BASE/interface/login/login.php?site=default" \
    | grep -iE '^(HTTP/|server|x-powered-by|strict-transport|x-frame|content-security|x-content-type|referrer-policy|set-cookie)' \
    | sed -E 's/(OpenEMR=)[^;]+/\1<REDACTED>/; s/(max-age=)[0-9]+/\1N/I'
echo "HTTP→HTTPS redirect:"; curl -s -o /dev/null --max-time 15 -w "HTTP %{http_code} -> %{redirect_url}\n" "http://$HOST/" | sed -E "s#//[^/]+#//<host>#"

echo; echo "## 4. TLS"
echo | openssl s_client -connect "$IP:443" -servername "$HOST" 2>/dev/null \
    | openssl x509 -noout -issuer -dates 2>/dev/null | sed -E 's/CN ?= ?[^,]*sslip\.io/CN=<host>/'
for v in tls1 tls1_1 tls1_2 tls1_3; do
    printf "%-8s " "$v"
    echo | timeout 10 openssl s_client -"$v" -connect "$IP:443" -servername "$HOST" >/dev/null 2>&1 && echo accepted || echo rejected
done

echo; echo "## 5. Exposed ports from this client (expect 22 restricted, 80/443 open)"
for port in 22 80 443 3306 8080 9300; do
    printf "%-5s " "$port"
    timeout 5 bash -c "</dev/tcp/$IP/$port" 2>/dev/null && echo open || echo closed/filtered
done

echo; echo "## 6. Public-path latency (unauthenticated pages, n=$RUNS, sequential)"
printf "%-24s %8s %8s %8s %8s\n" page p50_ms p95_ms ttfb_p50 http
for spec in "login|interface/login/login.php?site=default" "fhir_metadata|apis/default/fhir/metadata" "readyz|meta/health/readyz"; do
    name="${spec%%|*}"; path="${spec#*|}"
    out=$(for _ in $(seq "$RUNS"); do curl -sk -o /dev/null --max-time 30 -w "%{time_total} %{time_starttransfer} %{http_code}\n" "$BASE/$path"; done)
    pct() { sort -n | awk -v n="$RUNS" -v q="$1" '{ v[NR] = $1 * 1000 } END { printf "%.1f", v[int((n - 1) * q) + 1] }'; }
    p50=$(echo "$out" | awk '{print $1}' | pct 0.50)
    p95=$(echo "$out" | awk '{print $1}' | pct 0.95)
    ttfb=$(echo "$out" | awk '{print $2}' | pct 0.50)
    code=$(echo "$out" | awk '{print $3}' | sort | uniq -c | tr -s ' ' | tr '\n' ';')
    printf "%-24s %8s %8s %8s %8s\n" "$name" "$p50" "$p95" "$ttfb" "$code"
done
