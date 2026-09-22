# Week 2 Operational Budgets

Status: normative design accepted 2026-09-21; implementation and deployment
evidence are pending.

This specification defines the operational contract for document ingestion,
extraction, guideline retrieval, worker handoffs, verification, evaluation,
and the single-Droplet deployment. It refines ADR-0007 and ADR-0013 without
weakening their privacy, verification, or worker-authority boundaries.

The terms **must**, **must not**, **required**, and **prohibited** are normative.
Numbers in the Observed baseline section are evidence already collected from
Week 1 or the frozen retrieval benchmark. Every other requirement is planned
until implementation and named verification evidence exist.

## Observed baseline

The following facts inform the budgets but do not prove the Week 2 design:

- The deployed Week 1 tree measured `$0.0104` and `$0.0113` per model-backed
  turn in its two final runs. Cache-creation tokens were not recorded, so both
  figures are lower bounds.
- The current two-million-token daily halt is process-local, excludes planning
  calls and cache-creation tokens, and can permit approximately `$17.50` before
  stopping on the release-run token mix.
- On the shared 2-vCPU / 4-GiB tier, batching made 10 concurrent Week 1 users
  clean, while 15 users produced 37% unavailable tool results. OpenEMR and
  MariaDB CPU, not agent memory, were the constraint.
- A `c-4` rehearsal host completed 60 concurrent Week 1 users with no
  unavailable tool result. This predates document extraction and local
  retrieval and is not a Week 2 capacity result.
- The frozen local retrieval pipeline measured 287.36 ms one-worker p95 and
  1,994.66 ms ten-worker p95 on a 24-core workstation. Its process peaked at
  approximately 484 MiB RSS; model files total approximately 149 MiB and the
  indexes are under 1 MiB. Shared-host performance remains unmeasured.
- The code defaults to PHI-masked traces, but the synthetic demo compose file
  currently defaults content tracing and fault injection on.
- A 24-hour post-close retention target exists for conversations, but no
  checkpoint sweeper is scheduled. Traces use a 30-day target and container
  logs use size rotation.

## Data classes and channels

### OpenEMR audit rows

Patient-bearing access and lifecycle events must use OpenEMR's audit facility.
The patient and actor belong in the audit table's structured fields rather than
an ordinary message. An audit row may contain only:

- bounded event name and result;
- UTC event time;
- correlation ID and, when applicable, handoff ID;
- source-document, extraction, review, promoted-record, or action identifier;
- schema, contract, model, corpus, index, or record version;
- bounded operation, route, reason, limitation, and idempotency outcome;
- counts of pages, fields, records, or results;
- target identifier and reviewer identifier where the accepted review or
  promotion contracts require them.

Audit comments must not contain filenames, OCR, extracted or reviewed values,
quotes, evidence excerpts, document bytes, images, page crops, prompts,
questions, answers, unrestricted exceptions, or free-form model output.

Required Week 2 patient-bearing audit events are document access, extraction
start, extraction terminal result, review, promotion, amendment, withdrawal,
and the existing model-disclosure and gateway-read events. Audit insertion
must fail closed where the underlying clinical operation would disclose or
change patient data.

### Operational events and traces

`supervisor.route` and `worker.handoff` are PHI-free operational events. Every
ordinary log event and span may contain only:

- event/schema version and UTC time;
- correlation, conversation, turn, job, and handoff identifiers that are
  opaque and server-issued;
- worker, stage, route, operation, status, bounded reason/limitation, attempt,
  deadline, retryability, and cancellation state;
- duration, queue time, byte/page/field/result counts, and aggregate confidence
  buckets;
- contract, renderer, OCR, model, prompt, corpus, embedding, reranker, and
  index revisions;
- input, output, cache-read, and cache-creation token counts, model-call count,
  and estimated cost;
- error class only.

Operational events and traces must not contain patient or user identifiers,
filenames, source IDs, raw queries or clinical concepts, document/OCR/value
content, evidence excerpts, prompts, questions, answers, page images/crops, or
exception messages. Versioned identifiers that could be joined to patient data
must be stored as a one-way digest in operational telemetry and remain raw only
inside the protected OpenEMR audit/record boundary.

Content tracing and fault injection are permitted only on an explicitly
synthetic deployment. They must default off in every other environment.

### Metrics

Metrics must use bounded labels. Patient, user, correlation, conversation,
turn, handoff, source, document, filename, corpus hash, query, and free-text
labels are prohibited.

The metric surface must expose at least:

- supervisor routes and worker handoffs by bounded route, worker, status,
  reason, retryability, and cancellation outcome;
- queue depth, oldest-job age, active jobs, retry count, and duplicate terminal
  result count;
- extraction documents, pages, fields, and retries by document type and
  extraction state; confidence histograms; temporary and persistent bytes;
- sparse, dense, fusion, and rerank duration; candidate/returned counts;
  abstentions and unavailable reasons; corpus age and capability readiness;
- verification outcome and rejection rule by patient-record or guideline lane;
- every model call and input, output, cache-read, and cache-creation token;
  estimated dollars by bounded operation and model;
- per-service CPU and RSS, host load and free disk, OpenEMR/MariaDB latency and
  errors, and audit-outbox backlog.

The existing runtime alert semantics remain in force: complete-turn p95 warns
above 30 seconds and pages above 45 seconds; API errors warn above 0.5% and
page above 2% over five minutes; healthy-stack tool unavailability warns above
2% and pages above 5% over five minutes or when one tool exceeds 50%.
Additional Week 2 alerts warn/page at the storage thresholds below, page on a
missed 95-second extraction deadline or duplicate terminal handoff, warn when
guideline p95 exceeds 2.0 seconds, and page when the daily dollar ledger reaches
its `$20` halt. Alert payloads follow the same PHI-free event allowlist.

## Trace and correlation topology

The module mints the correlation ID. Chat keeps the existing
`{conversation-correlation}.{turn-sequence}` form. Upload and reprocess actions
receive a job correlation ID independent of a conversation. Every worker
dispatch receives a unique handoff ID. A retry preserves the handoff ID and
increments its attempt; a new dispatch receives a new handoff ID.

Correlation and handoff IDs must cross the UI/module boundary, supervisor,
worker, protected persistence, verifier, audit rows, logs, traces, and response.
Metrics must never carry them.

The required trace shapes are:

```text
copilot.document_job
  supervisor.route
  worker.handoff intake_extractor
    preflight
    render
    ocr
    schema_extract
    optional_region_retry
    validate
    persist

copilot.turn
  supervisor.route
  patient_record_retrieval
  worker.handoff evidence_retriever
    sparse
    dense
    fusion
    rerank
  deterministic_join
  source_resolution
  verification
  render

copilot.eval_run
  eval.case (synthetic metadata only)
```

An eval-case span may carry only synthetic case ID, category, dataset version,
boolean rubric outcomes, latency, usage, cost, and bounded failure reason. It
must not export fixture content merely because the fixture is synthetic.

Patient retrieval and guideline retrieval may be siblings. Both must reach a
terminal status before the join. Extraction must never join a chat trace.

## Retention and storage

| Content | Required retention |
| --- | --- |
| Original source document, OCR/evidence ledger, proposals, reviews, promoted records, amendments, and withdrawals | Follow the OpenEMR source-record lifecycle; no automatic Week 2 deletion. The demo retains them until teardown. |
| Rendered pages, crops, temporary OCR/model files | Delete after the terminal job result. A crash sweeper must remove remnants within one hour. |
| Per-turn evidence pack and delegation token | Existing maximum of 120 seconds; remove eagerly at turn completion. |
| Conversation binding and LangGraph checkpoint | Delete 24 hours after close; both module and checkpoint sweepers are required. |
| PHI-free operational logs and traces | At most 30 days; size-based container rotation remains an additional bound. |
| OpenEMR audit rows | Site audit-retention policy; no Week 2 purge. |
| CI and eval reports | At most 90 days and synthetic data only. |
| Guideline corpus/index | Active version plus one rollback version; manifests and integrity hashes may be retained indefinitely. |

The deployment reserves at most 10 GiB for Week 2 source and ledger growth.
It warns at 70% host-disk use, pages at 85%, and refuses new uploads at 90%
or when less than 10 GiB remains free, whichever happens first. Existing
records remain readable during an upload refusal.

One extraction may use at most 1 GiB of temporary workspace. A source may
have at most three immutable extraction versions in the Week 2 workflow. A
fourth request returns a typed storage/version-limit limitation and does not
delete or overwrite history.

The operational OCR envelope is deliberately narrower than the schema's
representational maximum:

- at most 2,000,000 UTF-8 bytes of retained OCR page text per extraction;
- at most 10,000 positioned OCR tokens per page and 100,000 per extraction;
- at most 30 MiB for the canonical serialized OCR/evidence payload of one
  extraction version;
- at most 100 MiB of retained extraction derivatives per source across the
  three versions, excluding the canonical original document.

If the source cannot fit the envelope, extraction ends `unavailable` with a
review-visible limitation. The implementation must not silently truncate OCR,
tokens, page geometry, or field evidence because doing so would invalidate
source resolution.

## Latency budgets

Latency is measured from accepted server operation to terminal server result,
with network upload time reported separately. Reports must separate warm/cold,
success/failure, document type, chart size, cache state, and concurrency.

| Operation | Target | Hard gate or degradation |
| --- | ---: | --- |
| Supervisor route | p95 <= 50 ms | Invalid route/contract denies dispatch. |
| Worker-handoff creation | p95 <= 50 ms | Combined supervisor and handoff p95 <= 100 ms. |
| Upload acceptance after bytes arrive | p95 <= 2 s | Fail before permanent storage by 5 s. |
| Upload to review-ready extraction | p50 <= 45 s; p95 <= 90 s | Existing 95 s cap; terminal extraction limitation. |
| Local guideline pipeline | p50 <= 500 ms; p95 <= 2.0 s | Two-second deadline; return `guideline_retrieval_unavailable`; no RRF-only fallback. The 2.0 s p95 gate is a dated owner risk acceptance in ADR-0014; it does not permit an over-deadline request. |
| Deterministic verification | p95 <= 150 ms | Fail closed. |
| First useful patient evidence | p95 target <= 2 s | Release-blocking above 4 s. |
| Complete chart-only or mixed-evidence turn | p95 target <= 30 s | Release-blocking above 45 s. |
| Review, promotion, amendment, or withdrawal command | p95 <= 2 s | Roll back and return a typed limitation by 5 s. |

The eight-second complete-answer experience goal remains tracked separately
from the release gate because no clinician interview has validated it. A
guideline branch runs inside its two-second deadline and in parallel with
patient retrieval; it does not extend the 45-second chat wall clock.

## Cost and usage budgets

All cost figures use the configured provider's versioned price table captured
with the report. Cost accounting must include every chat, planning, narration,
repair, extraction, and vision-retry call and every input, output, cache-read,
and cache-creation token.

| Operation | Target | Hard limit |
| --- | ---: | ---: |
| Model-backed chat turn | <= `$0.0223` | Release-blocking above `$0.0446`; the interval is a warning requiring explicit risk acceptance. |
| Guideline retrieval | `$0` query API cost | No hosted fallback. |
| Completed extraction document | p95 <= `$0.10` | `$0.15` reservation per document, including its one optional region retry. |
| Combined UTC-day model spend | warn at `$14` | Refuse new model spend at `$20`. |

Before each model call, the budget owner must reserve its maximum configured
cost. On completion it settles the reservation to actual provider usage. A
retry may start only when its full reservation remains. The ledger must be
durable across process restarts and shared by chat and extraction; a
process-local token counter is non-conformant. When the hard daily limit has
insufficient room for a reservation, chat uses its deterministic fallback and
extraction returns a typed budget limitation. Guideline retrieval remains
available because it has no per-query API cost.

The report must price source/ledger growth, temporary peak disk, model/index
artifacts, snapshots, tracing, and the host separately from model API spend.

## Capability readiness and degradation

`/ready` must report these independent capabilities:

| Capability | Required checks | Failure behavior |
| --- | --- | --- |
| `core_ready` | Module gateway and audit path, delegation secret, state store, contract versions, verifier | HTTP 503; no patient or document operation runs. |
| `chat_model_ready` | Configured model and credentials reachable; budget reservation available | Core remains ready. UC-01 uses its deterministic fallback; other narration returns an explicit limitation. |
| `document_ready` | Protected persistence, job lease, free-space floor, renderer, OCR, extraction model, temp cleanup | Upload or extraction returns a typed limitation; an already stored source remains intact. |
| `guideline_ready` | Active approved non-stale corpus, matching hashes/revisions, FTS/FAISS/reranker loaded | No guideline claim; patient-record lane may continue. |
| `telemetry_ready` | Tracer export and alert delivery state | Core remains ready; log locally and emit an operational warning. |

Only `core_ready=false` makes the overall endpoint return 503. Capability
details must contain bounded status/reason values and no endpoint URL, secret,
exception message, or content. The supervisor must check the relevant
capability before dispatch and must not substitute an unauthorized degraded
algorithm.

A stale corpus older than 14 days, missing reranker, sparse/dense leg failure,
or version mismatch makes `guideline_ready=false`. Low disk, an expired job
lease, renderer/OCR failure, exhausted three-version limit, or unavailable
budget makes `document_ready=false` for the relevant operation. Telemetry loss
must never fail a patient response.

## Deployment topology

The Week 2 evaluator deployment is one DigitalOcean `c-4` with four dedicated
vCPUs, 8 GiB RAM, and 50 GB disk. Its observed reference price is `$84` per
month and must be refreshed in the cost report before deployment.

The host contains separate services for:

- Caddy;
- OpenEMR;
- MariaDB;
- chat API and deterministic supervisor;
- intake-extractor worker, concurrency one;
- evidence-retriever worker with preloaded models, concurrency two;
- alert evaluator.

The agent services retain no database credentials or backend-network route.
No Redis, extra database, load balancer, or self-hosted tracer is introduced
for Week 2. The single host remains one accepted failure domain. Horizontal
scaling, a distributed queue, and managed persistence require a later decision.

The chosen tier is not approved by the Week 1 capacity result alone. Release
requires a co-located test with OpenEMR, MariaDB, local retrieval, and one
active extraction. Failure disables the affected Week 2 lane or requires a
new owner decision; it does not justify loosening safety behavior.

## Required evidence

The Week 2 cost/latency report must include:

1. Commit, deployment tier, container-image digests, configuration relevant to
   each budget, and model, prompt, contract, renderer, OCR, corpus, embedding,
   reranker, and index versions/hashes.
2. Cold and warm p50/p95/p99 by stage, with sample size, success/failure split,
   document type, cache state, and concurrency.
3. Both document types under normal, rotated, noisy, multipage, retry, timeout,
   cancellation, storage-limit, and cleanup scenarios.
4. The frozen retrieval benchmark on the selected co-located host at one, two,
   and ten workers, plus mixed chat load while one extraction is active.
5. OpenEMR and MariaDB request latency/errors and per-service CPU/RSS, host
   load, queue depth, disk use, and temporary/persistent storage growth before
   and during the Week 2 workloads.
6. Every billing token class, API call, per-operation cost, run total, daily
   projection, actual attributable development spend, projected production
   cost, infrastructure price, tracing price, and storage/snapshot cost.
7. One complete reconstruction by correlation and handoff ID across module
   audit, supervisor, worker, model, verifier, and UI result.
8. Automated synthetic-PHI canary scans over logs, traces, metrics, errors,
   readiness responses, and audit comments.
9. Fault evidence for model, tracer, alert receiver, corpus, sparse/dense leg,
   reranker, renderer, OCR, audit write, budget, disk, cancellation, stale
   version, and expired job lease.
10. Proof that transient artifacts disappear within one hour, conversations
    and checkpoints disappear 24 hours after close, a fourth extraction is
    refused without history loss, and all retained artifacts fit their quotas.
11. Eval outcome by required boolean category, including `no_phi_in_logs`, and
    the versioned 50-case release verdict.

Every claim in the report must be explicitly marked **Observed**, **Inferred**,
or **Planned**. Synthetic results must not be represented as real-clinic
prevalence or capacity.
