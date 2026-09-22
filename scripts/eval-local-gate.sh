#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "${repo_root}"

python_bin="${EVAL_PYTHON:-${repo_root}/agent/.venv/bin/python}"
if [[ ! -x "${python_bin}" ]]; then
    python_bin="$(command -v python3)"
fi

baseline="${repo_root}/evals/baselines/week2-local-offline-v1.json"
test -f "${baseline}" || {
    printf 'Missing committed local feedback baseline: %s\n' "${baseline}" >&2
    exit 1
}

"${python_bin}" evals/week2_manifest.py
"${python_bin}" -m pytest -q \
    evals/test_week2_manifest.py \
    evals/test_compare.py \
    evals/test_release_reporting.py \
    evals/test_local_gate.py \
    evals/test_hook_install.py \
    evals/test_candidate_identity.py \
    evals/test_ci_release_gate.py

gate_tmp="$(mktemp -d)"
trap 'rm -rf -- "${gate_tmp}"' EXIT
set +e
COPILOT_RUNTIME_IMAGE=local-offline \
    "${python_bin}" evals/run.py \
    --offline-only \
    --model deterministic-offline \
    --label local-pre-push \
    --out-dir "${gate_tmp}"
suite_status=$?
set -e

candidate="$(find "${gate_tmp}" -maxdepth 1 -type f -name '*.json' -print -quit)"
test -n "${candidate}" || {
    printf 'Offline eval did not produce a JSON report.\n' >&2
    exit 1
}
set +e
"${python_bin}" evals/local_gate.py "${baseline}" "${candidate}"
compare_status=$?
set -e
if [[ ${suite_status} -ne 0 || ${compare_status} -ne 0 ]]; then
    exit 1
fi
