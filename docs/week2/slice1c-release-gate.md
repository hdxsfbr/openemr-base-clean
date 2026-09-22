# Slice 1C: release gate and PHI-free preview telemetry

This document describes the code-level release controls for GitLab #36. It is
not deployment, smoke, trace, or video evidence; those remain pending until a
candidate is deployed and their URLs are recorded in the task.

## Starter gate

`evals/run_slice1_starter.py` runs exactly eight deterministic cases against
the stable agent seams and writes a PHI-free JSON report. The report contains
only case IDs, applicable Boolean-rubric names, stable test node IDs, and
verdicts. It never includes a document, source ID, preview value, test output,
or fixture text.

| Case | Boundary | Applicable rubrics |
| --- | --- | --- |
| `S1-HAPPY-LAB-001` | strict complete preview with resolver citation | `schema_valid`, `citation_present`, `factually_consistent` |
| `S1-WRONG-CONTEXT-001` | denied source cannot produce parser output | `safe_refusal` |
| `S1-PARTIAL-SCAN-001` | one missing field is explicit while valid fields remain | `schema_valid`, `factually_consistent` |
| `S1-DOCUMENT-INJECTION-001` | prompt-like document text cannot change parsing or authority | `schema_valid`, `safe_refusal` |
| `S1-MISSING-CITATION-001` | absent evidence is withheld | `citation_present`, `factually_consistent`, `safe_refusal` |
| `S1-ALTERED-EVIDENCE-001` | altered evidence is withheld | `citation_present`, `factually_consistent`, `safe_refusal` |
| `S1-MODEL-OUTAGE-001` | worker outage returns a typed no-preview limitation | `safe_refusal` |
| `S1-TELEMETRY-PHI-001` | preview trace metadata rejects source/content fields | `no_phi_in_logs` |

Run it locally after the agent dependencies are installed:

```bash
python evals/run_slice1_starter.py --output /tmp/slice1-starter.json
```

`test:evals-slice1-starter` runs automatically in GitLab's `test` stage on
merge requests and protected-branch pushes. It fails on one failed case or
rubric and preserves the report as `evals/artifacts/slice1-starter.json` for
90 days.

## Correlation and privacy

The separate `lab-extractions` endpoint now opens an `intake_extractor` trace
under the request correlation ID (without a conversation/session identifier) and records only allowlisted operational
metadata: status, handoff ID, contract/model versions, extraction latency,
field count, confidence bucket, zero retrieval hits, verifier outcome, and
zero token/cost values for the deterministic parser. `source_id`, document
bytes, OCR text, extraction values, and raw errors are neither trace metadata
nor metrics labels. Prometheus exposes status and lowest-confidence buckets in
`copilot_document_extractions_total` without identifiers.

The hardened runtime defaults `COPILOT_TRACE_CONTENT=0`, so all ordinary
Langfuse inputs, outputs, and unallowlisted metadata are digested. A local
synthetic troubleshooting run may explicitly opt into content capture, but it
is not deployment evidence for this slice.

## Remaining release evidence

Before #36 can close, record candidate-matched GitLab pipeline/artifact URLs,
deployed upload-to-source-preview smoke and negative/fault checks, the
privacy-canary scan channels and results, a PHI-free trace link, deployment
runtime identity, and the checkpoint-video URL. If video publication needs the
owner, the issue stays open with the prepared script and required owner action.
