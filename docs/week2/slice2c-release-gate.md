# Slice 2C: shared two-document release gate

GitLab #39 extends the existing automatic Slice 1 gate with the narrowly
required intake boundaries. It is a deterministic code-level release control;
deployment and public-smoke evidence must be recorded separately after the
candidate is deployed.

`evals/run_slice2_gate.py` executes all eight unchanged Slice 1 lab cases and
nine intake cases. The intake cases cover strict cited output, partial fields,
conflicting state, type mismatch, prompt-like form text, denied source access,
citation tampering, worker outage, and telemetry canaries. Each declares only
the applicable PRD Boolean rubrics. The output records case IDs, rubric names,
test node IDs, and pass/fail verdicts only—never source IDs, PDF bytes, form
text, extracted values, or pytest output.

```bash
python evals/run_slice2_gate.py --output /tmp/slice2-shared-gate.json
```

`test:evals-slice2-shared` runs automatically in GitLab’s `test` stage. It
installs the locked agent dependencies, runs both document types’ cases, and
keeps the PHI-free artifact for 90 days. One failed case or applicable rubric
fails the job.

## Intake observability boundary

The document-preview trace has a bounded `document_type` (`lab_pdf` or
`intake_form`) plus status, opaque handoff ID, contract/model versions,
extract latency, record count, confidence summary, zero retrieval hits,
verifier outcome, eval outcome, and zero token/cost values for the current
deterministic parser. Prometheus adds the same bounded document type to
`copilot_document_extractions_total`. Source identifiers, patient identifiers,
source bytes, OCR text, extracted values, prompts, images, and raw errors are
not trace metadata or metric labels. The runtime compose default remains
`COPILOT_TRACE_CONTENT=0`, so unallowlisted trace payloads are masked.

The following still require candidate-matched deployment evidence before #39
can close: authenticated browser upload/preview for both types, deployed
negative/fault paths, correlation reconstruction, and a privacy scan of the
actual deployment’s logs, traces, metrics, handoffs, checkpoints, and CI
artifact.

## Observed candidate evidence (2026-09-22)

Merge commit `03523d98` was deployed by GitLab pipeline
[25292](https://labs.gauntletai.com/andrebatista/andrebatista-openemr-base-clean/-/pipelines/25292).
All required jobs passed, including
[`test:evals-slice2-shared`](https://labs.gauntletai.com/andrebatista/andrebatista-openemr-base-clean/-/jobs/85652)
and the post-deploy
[`verify:smoke`](https://labs.gauntletai.com/andrebatista/andrebatista-openemr-base-clean/-/jobs/85654).

An authenticated synthetic-only smoke then used the deployed panel handshake
and `audit-physician` session. It stored and previewed the intake fixture
(`partial`, with the fixture's explicit ambiguous/conflicting fields), reopened
its source under current authorization, retried the same upload intent without
changing the immutable source, and completed the lab preview. It also confirmed
a model fault returned `unavailable` without an extraction, lab-as-intake was
rejected (`409`), and a patient-switched upload intent was rejected (`409`).
The public health endpoint reported agent `0.3.0`; `/metrics` contained only
the bounded `lab_pdf` and `intake_form` preview labels. This is deployment
evidence for the implemented paths, not evidence for later supervisor,
retrieval, persistence, overlay, or 50-case work.
