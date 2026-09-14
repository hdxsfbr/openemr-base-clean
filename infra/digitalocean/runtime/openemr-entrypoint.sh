#!/usr/bin/env bash
set -euo pipefail

read_secret() {
    local name="$1"
    local path="/run/secrets/${name}"

    if [[ ! -s "${path}" ]]; then
        printf 'Required secret is missing: %s\n' "${name}" >&2
        exit 1
    fi

    tr -d '\r\n' < "${path}"
}

MYSQL_ROOT_PASS="$(read_secret mysql_root_password)"
MYSQL_PASS="$(read_secret mysql_password)"
OE_PASS="$(read_secret openemr_admin_password)"
export MYSQL_ROOT_PASS MYSQL_PASS OE_PASS

exec "$@"
