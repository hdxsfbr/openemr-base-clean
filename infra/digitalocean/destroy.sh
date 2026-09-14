#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${script_dir}"

if [[ "${1:-}" == "--yes" ]]; then
    approval=(-auto-approve)
else
    approval=()
fi

printf 'Destroying the Droplet and attached Terraform-managed resources.\n'
printf 'Powering off is not sufficient to stop DigitalOcean compute billing.\n'
./tf.sh destroy "${approval[@]}"
