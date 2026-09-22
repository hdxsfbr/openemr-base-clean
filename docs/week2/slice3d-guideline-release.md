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
