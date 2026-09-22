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
