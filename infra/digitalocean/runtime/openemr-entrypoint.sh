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

# The base image pins PHP's date.timezone to UTC, and PHP does not read TZ for
# it. That clock is what the calendar books against, what appointment dates are
# written in, and what the co-pilot's "does this chart have a visit today" asks,
# so on a site behind UTC every one of them rolls over to tomorrow in the middle
# of the working afternoon. OpenEMR re-points the MySQL session at PHP's offset
# on each request (interface/globals.php, gbl_time_zone), so setting PHP here
# settles both. Written at startup rather than baked into the image so changing
# it is a restart, not a rebuild.
configure_timezone() {
    local tz="${TZ:-}"
    [[ -n "${tz}" ]] || return 0

    if ! php -r 'exit(in_array($argv[1], DateTimeZone::listIdentifiers(), true) ? 0 : 1);' "${tz}"; then
        printf 'Unknown TZ %s; leaving PHP on the image default\n' "${tz}" >&2
        return 0
    fi

    local scan_dir
    scan_dir="$(php -r 'echo PHP_CONFIG_FILE_SCAN_DIR;')"
    if [[ -d "${scan_dir}" ]]; then
        printf 'date.timezone = "%s"\n' "${tz}" > "${scan_dir}/99-openemr-timezone.ini"
    else
        printf 'No PHP scan dir; cannot set date.timezone to %s\n' "${tz}" >&2
    fi

    # The image ships no tzdata, so the system clock stays UTC and only PHP moves.
    # PHP carries its own timezone database, and PHP's clock is the one OpenEMR reads.
    if [[ -f "/usr/share/zoneinfo/${tz}" ]]; then
        cp "/usr/share/zoneinfo/${tz}" /etc/localtime
        printf '%s\n' "${tz}" > /etc/timezone
    fi
}

configure_timezone

MYSQL_ROOT_PASS="$(read_secret mysql_root_password)"
MYSQL_PASS="$(read_secret mysql_password)"
OE_PASS="$(read_secret openemr_admin_password)"
export MYSQL_ROOT_PASS MYSQL_PASS OE_PASS

exec "$@"
