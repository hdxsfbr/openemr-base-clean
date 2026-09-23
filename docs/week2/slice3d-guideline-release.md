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
The deployed clinician walkthrough independently exercised the visible path:
an explicit Breast-screening request rendered three attributed USPSTF excerpts
in the separate guideline lane and the fixed no-applicability notice. Clicking
**Open exact source** opened the selected exact chunk in the Co-Pilot, and
**Open publisher page** reached the USPSTF Breast Cancer: Screening page.
The cropped synthetic screenshots and procedural details are in GitLab #43
[note 76677](https://labs.gauntletai.com/andrebatista/andrebatista-openemr-base-clean/-/work_items/43#note_76677);
they exclude the browser address bar and session token.

An earlier visible request instead rendered the typed
`guideline_retrieval_timeout` limitation and no guideline claim. A direct
finite-topic worker check reproduced one timeout followed by two completed
three-excerpt responses. The first-request timeout is not fixed; its cause and
safe remediation are tracked by [#44](https://labs.gauntletai.com/andrebatista/andrebatista-openemr-base-clean/-/work_items/44).

The earlier targeted privacy canary was absent from deployed agent, OpenEMR,
and Caddy logs, Prometheus metrics, and agent checkpoints after the run. The
request-log path-redaction remediation is included in this candidate.

Five completed finite-topic requests measured worker p50 1372.1 ms, worker p95
1725.3 ms, and endpoint p95 1753.1 ms. The owner accepted the 2.0-second p95
gate in ADR-0014 while retaining the 2.0-second hard deadline and full hybrid
pipeline. The 500 ms p50 target was missed; it remains a performance follow-up
and is not silently treated as PASS. Under the normative budget table, the
unchanged deadline is the hard release gate for this narrow acceptance. This is
small-sample synthetic evidence (`n=5`), not a capacity,
cold-start, mixed-load, CPU/RSS, or broader quality measurement.

Privacy evidence has a deliberately narrow scope. The deployed agent reported
`COPILOT_TRACE_CONTENT=0` with tracer keys configured. A read-only sample of
five full external traces contained 29 observations: all 12 nonempty inputs
and all 12 nonempty outputs were digest-masked, and neither an `AF-DQ-` nor an
`Alba Synthetic` marker appeared. The sampled metadata key names included
`conversation_id`, `thread_id`, and `correlation_id`; two of five traces had a
nonempty Langfuse `session_id`. Their values were not printed or classified as
auth tokens or PHI, but those opaque session/binding identifiers require #45
review. This is a sample, not a complete correlated canary export, so
external-trace privacy remains **NOT RUN**, not PASS.

Slice 3 has no durable guideline handoff store. The current worker's in-memory
state holds opaque handoff IDs and statuses; the release service holds public
guideline excerpts keyed by opaque conversation/turn IDs. That makes a durable
handoff-store scan N/A for this candidate, but it is not a certification of a
future supervisor store. Candidate CI jobs 88209, 88210, and 88211 received a
read-only targeted artifact scan: no synthetic privacy canary, browser
session-token pattern, or login-password field name was found, and the current
candidate eval report had no tested-patient marker. Job 88209 nevertheless
archived 53 historical eval-result files, some containing synthetic `AF-DQ-*`
identifiers; those are demo identifiers, not evidence of real PHI, but the
archive is broader than the candidate report. The comprehensive CI artifact
scan remains **NOT RUN**. Both remaining privacy investigations are tracked in
[#45](https://labs.gauntletai.com/andrebatista/andrebatista-openemr-base-clean/-/work_items/45);
they are not PASS.

A full live guideline evaluation is also **NOT RUN**. It is release-gate and
final-evidence work for [#32](https://labs.gauntletai.com/andrebatista/andrebatista-openemr-base-clean/-/work_items/32)
and [#33](https://labs.gauntletai.com/andrebatista/andrebatista-openemr-base-clean/-/work_items/33),
not evidence claimed by this slice.
