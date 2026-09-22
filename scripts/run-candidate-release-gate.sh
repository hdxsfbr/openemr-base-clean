#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "${repo_root}"
python_bin="${EVAL_PYTHON:-$(command -v python3)}"

: "${CI_COMMIT_SHA:?CI_COMMIT_SHA is required}"
: "${CANDIDATE_BASE_URL:?CANDIDATE_BASE_URL is required}"
: "${CANDIDATE_COMMIT_SHA:?CANDIDATE_COMMIT_SHA is required}"
: "${CANDIDATE_RUNTIME_IMAGE:?CANDIDATE_RUNTIME_IMAGE is required}"
: "${APPROVED_BASELINE_PATH:?APPROVED_BASELINE_PATH is required}"
: "${DEMO_PASSWORD:?DEMO_PASSWORD is required}"

[[ "${CANDIDATE_COMMIT_SHA}" == "${CI_COMMIT_SHA}" ]] || {
    printf 'Candidate commit %s does not match pipeline commit %s.\n' \
        "${CANDIDATE_COMMIT_SHA}" "${CI_COMMIT_SHA}" >&2
    exit 1
}
[[ "${CANDIDATE_RUNTIME_IMAGE}" =~ @sha256:[0-9a-f]{64}$ ]] || {
    printf 'CANDIDATE_RUNTIME_IMAGE must be an immutable digest reference.\n' >&2
    exit 1
}
[[ -f "${APPROVED_BASELINE_PATH}" ]] || {
    printf 'Approved baseline not found: %s\n' "${APPROVED_BASELINE_PATH}" >&2
    exit 1
}

"${python_bin}" evals/candidate_identity.py \
    "${CANDIDATE_BASE_URL}" \
    --expected-commit "${CI_COMMIT_SHA}" \
    --expected-image "${CANDIDATE_RUNTIME_IMAGE}"

out_dir="${repo_root}/evals/results/candidate"
mkdir -p "${out_dir}"
set +e
COPILOT_RUNTIME_IMAGE="${CANDIDATE_RUNTIME_IMAGE}" \
    "${python_bin}" evals/run.py \
    --base-url "${CANDIDATE_BASE_URL}" \
    --password-file - \
    --label "candidate ${CI_COMMIT_SHA}" \
    --out-dir "${out_dir}"
suite_status=$?
set -e

candidate_report="$(find "${out_dir}" -maxdepth 1 -type f -name '*.json' -print | sort | tail -1)"
test -n "${candidate_report}" || {
    printf 'Candidate release run did not produce a JSON report.\n' >&2
    exit 1
}

set +e
"${python_bin}" evals/compare.py --release \
    "${APPROVED_BASELINE_PATH}" "${candidate_report}"
compare_status=$?
set -e

if [[ ${suite_status} -ne 0 || ${compare_status} -ne 0 ]]; then
    exit 1
fi
