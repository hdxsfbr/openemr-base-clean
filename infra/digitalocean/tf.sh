#!/usr/bin/env bash
set -euo pipefail

if command -v terraform >/dev/null 2>&1; then
    exec terraform "$@"
fi

if command -v tofu >/dev/null 2>&1; then
    exec tofu "$@"
fi

if command -v docker >/dev/null 2>&1; then
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    host_uid="$(id -u)"
    host_gid="$(id -g)"
    docker_args=(
        run
        --rm
        --user "${host_uid}:${host_gid}"
        --env HOME=/tmp/terraform-home
        --volume "${script_dir}:/workspace"
        --workdir /workspace
    )

    if [[ -t 0 && -t 1 ]]; then
        docker_args+=(--interactive --tty)
    fi
    if [[ -n "${DIGITALOCEAN_TOKEN:-}" ]]; then
        docker_args+=(--env DIGITALOCEAN_TOKEN)
    fi
    if [[ -d "${HOME}/.ssh" ]]; then
        docker_args+=(--volume "${HOME}/.ssh:/tmp/terraform-home/.ssh:ro")
    fi

    exec docker "${docker_args[@]}" \
        hashicorp/terraform:1.13.3@sha256:dfb1889a8ee74ada3ddacc48f89b8a0d69f3e114de3d8a2ce15f6a8d3dbfdbe2 \
        "$@"
fi

printf 'Terraform, OpenTofu, or Docker is required. See docs/deployment/digitalocean.md.\n' >&2
exit 1
