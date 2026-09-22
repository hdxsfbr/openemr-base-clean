# Slice 3D: guideline evidence release seam

This slice adds the explicit, chart-bound guideline-evidence request. The PHP
module uses its existing CSRF/session conversation ticket and rechecks active
user, site, chart, squad scope, and break-glass state before the browser can
send the opaque delegation to the agent. The request body is finite topic
selectors only; it has no patient ID, chart value, question, note, OCR, source
text, or applicability field.

The agent invokes `EvidenceRetrieverWorker` directly (not through the later
supervisor). `GuidelineReleaseService` reloads the active immutable corpus,
checks corpus age, source/chunk hashes, version, section and exact quote, then
creates resolver-authored `guideline_evidence` claims. A failed verification
withholds that excerpt. A source click obtains a fresh ticket, then can reopen
only a source saved for the original conversation/turn and still matching the
active corpus. It never follows arbitrary URLs or accepts citation metadata
from the browser.

The panel renders guideline material in its own lane and always says: “Patient
applicability was not determined. Physician judgment is required.” It neither
mixes these excerpts with chart claims nor uses them for diagnosis, treatment,
recommendation, or dosing.

## Deployment model setup

`start.sh` runs the setup-only `guideline-model-provision` Compose profile
before the agent starts. The provisioner fetches the four revision-pinned
artifacts and verifies every full SHA-256 atomically. The running agent mounts
the resulting named volume read-only at `/opt/copilot-models`; local ignored
`agent/.guideline_models/` files and model binaries are never committed or
copied by `deploy.sh`.

`deploy.sh` copies the candidate's full commit into `build/agent/BUILD_COMMIT`.
`start.sh` refuses an absent/non-SHA value and writes the commit plus the
rebuilt agent/OpenEMR image IDs to `logs/deployment-identity-<commit>.json`.
Use that sanitized file in the deployed smoke/eval evidence; do not call a
deployment candidate-matched without it.

## Local verification

```bash
cd agent
.venv/bin/pytest -q tests/test_guideline_release.py tests/test_guideline_contracts.py tests/test_evidence_retriever_worker.py
.venv/bin/python -m app.contracts.export --check
node --check ../interface/modules/custom_modules/oe-module-copilot/public/assets/js/copilot.js
```

The first command covers exact active-corpus verification, altered active-row
withholding, and denied re-open. It is not deployment evidence. Deployed
privacy scans, authenticated smoke, latency, quality, and CI identity evidence
are recorded only when actually run; missing channels are **NOT RUN**.

## Observed deployed evidence — 2026-09-22

The candidate-matched synthetic deployment at
`d75c91f83a3823a9320e01003e6a0cd025dc073f` recorded agent image
`sha256:a918571d0709828b163d95a5ab8b053c52b8265dba45c147bd76a2aae1f4d35f`
and OpenEMR image
`sha256:922784f4678952ca7711088eeadaf03603699af8443dc4ce4bc64d6f33f81ed5`.
The hardened deploy job and generic smoke both passed.

A synthetic authenticated request produced one verifier-authorized exact
guideline claim and the fixed applicability notice; fresh-ticket source reopen
returned 200. The same bounded smoke observed unauthenticated request 401,
PHI-bearing extra-field rejection 400, and tampered source identity 403.
The privacy canary was absent from deployed agent, OpenEMR, and Caddy logs,
Prometheus metrics, and agent checkpoints after the run. The request-log path
redaction remediation is included in this candidate.

Five completed finite-topic requests measured worker p50 1372.1 ms, worker p95
1725.3 ms, and endpoint p95 1753.1 ms. The owner accepted the 2.0-second p95
gate in ADR-0014 while retaining the 2.0-second hard deadline and full hybrid
pipeline. This is small-sample synthetic evidence (`n=5`), not a capacity,
cold-start, mixed-load, CPU/RSS, or broader quality measurement.

External traces, worker-handoff store inspection, CI captured-artifact scans,
and a full live eval are **NOT RUN**: this release session did not have a safe
read-only interface for those protected/external channels. They are not PASS.
