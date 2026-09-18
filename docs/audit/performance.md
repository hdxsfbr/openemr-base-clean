# Performance Audit

Lead track. Date 2026-09-14, commit `fc95374`.

| Scope | Local `development-easy` stack, plus unauthenticated public-path timings from the 2026-09-14 cloud window (2 vCPU/4 GiB Droplet, Caddy + TLS): login p50 159 ms, FHIR `metadata` p50 689 ms / p95 1,023 ms, `readyz` p50 125 ms. Authenticated latency on the Droplet is **not yet measured**. |
| --- | --- |
| Evidence | `evidence/performance/page-timing-local.md`, `evidence/performance/service-timing-and-query-shapes.md`, `evidence/performance/indexes.md`, `evidence/performance/cohort-measurements.md` (synthetic) |
| Caveats | Xdebug loaded, bind-mounted code, workstation host. Demo data (3 patients) plus the planted synthetic cohort `af-cohort-v1`. Numbers are **relative** baselines, not production latency. |

## Summary

The expensive part of OpenEMR is page rendering, not clinical data retrieval.
A single patient dashboard costs ≈360 ms and ≈1,045 SQL statements even for a
near-empty chart, almost all of it translation, layout, ACL, and label
lookups. The clinical services the co-pilot needs return in 1–5 ms each at demo
scale, for ≈14 ms serially. The binding latency constraint for the co-pilot is
therefore the **LLM call and verification**, not OpenEMR, provided tools call
services directly. The synthetic cohort showed this holds at volume: a 5-year
chart keeps services under 37 ms p95 and barely changes dashboard cost. Raw
tool payloads (≈42K tokens for that chart), not latency, become the
constraint (PERF-MED-005). `ProcedureService::getAll()` is broken, but its
sibling `search()` now works on seeded lab rows.

---

### `PERF-MED-001` Lab retrieval via `ProcedureService::getAll()` is broken (SQL syntax error)

- **Status:** Open. Observed. **Alternative path verified on synthetic data
  (2026-09-14):** `ProcedureService::search()` with a `puuid` token returned 20
  orders / 120 results for AF-HEAVY and 3 / 4 for AF-DQ-A2, matching the seed
  (`evidence/performance/cohort-measurements.md` §3).
- **Severity:** Medium. It breaks REST `GET /api/procedure` and any direct
  `getAll()` caller. The FHIR lab paths (`FhirObservationLaboratoryService.php:161`,
  `FhirProcedureOEProcedureService.php:136`) call `ProcedureService::search()`
  instead, so they avoid this defect. `search()` was verified on the synthetic
  cohort (see Status); it has not been exercised with real HL7 lab feeds.
- **Observed evidence:** `src/Services/ProcedureService.php:648` emits a bare
  `LEFT JOIN` immediately before `WHERE porder.activity = 1`. Calling
  `getAll([], true, $puuid)` raises a MariaDB syntax error (evidence §1). REST
  `GET /api/procedure` calls it (`src/RestControllers/ProcedureRestController.php:80`).
  The demo DB has 0 `procedure_result` rows, so no UI path has exercised it.
- **Affected assets and users:** Any tool or API client retrieving lab orders
  and results for a patient.
- **Failure scenario:** The co-pilot's lab tool throws on every call. If the
  error is swallowed, the agent reports "no labs documented", which is a false
  negative with clinical consequences.
- **Impact:** A silent false "not documented" state for labs, the exact
  failure mode the PRD warns about.
- **Likelihood and assumptions:** Certain for that method. The FHIR lab
  Observation path uses `search()`, which works on seeded data.
- **Recommendation:** Do not build the lab tool on `ProcedureService::getAll()`.
  Either fix the SQL (upstream-quality patch with a regression test) or use the
  working FHIR laboratory service path. In both cases the tool distinguishes
  `error` from `empty`, and an eval asserts that a failing lab source produces
  "lab data unavailable", never "no labs".
- **Verification:** Unit/integration test calling the chosen lab path against
  a seeded patient with ≥3 results. Negative eval with the source forced to
  fail.
- **Architecture consequence:** Every tool result carries an explicit
  `status ∈ {ok, empty, partial, unavailable}`, and the verifier forbids
  absence claims unless the status is `ok`/`empty`. This finding is the
  concrete case that justifies the rule.
- **Co-pilot response status (2026-09-16):** Implemented. `LabResultsTool`
  calls `ProcedureService::search()` only; any exception in a tool becomes
  `status: unavailable` with a reason, never an empty list (`AbstractTool`,
  `agent/app/gateway_client.py`); `pack_limitations` emits an `unavailable`
  line and the verifier's `absence_requires_retrieval` rule rejects an
  absence claim for a section not retrieved `ok`/`empty`. `TOOL-OUTAGE-LABS-001`
  (golden, injected fault) passes live and the "Healthy-stack tool failures"
  release gate is PASS in `evals/results/2026-09-16T073141Z-1ddf824.md`.
  OpenEMR's `getAll()` is unchanged.

### `PERF-MED-002` Dashboard rendering issues ≈1,045 SQL statements per load, dominated by uncached lookups

- **Status:** Open. Observed.
- **Severity:** Medium
- **Observed evidence:** The `Questions` delta is 1,047 per load, deterministic
  over 3 runs (886 SELECT, 7 INSERT, 1 UPDATE). The general-log shape analysis
  shows 431 translation lookups, 104 layout-group lookups, 112 phpGACL queries
  (56 ACL checks), and 50 `list_options` label lookups. Dashboard latency is
  p50 359.5 ms / p95 395.8 ms at 155 KB of HTML (n=20, local).
- **Affected assets and users:** Apache prefork workers and MariaDB
  connections on the shared Droplet; every clinician's chart-open time; the
  co-pilot's latency budget.
- **Failure scenario:** (INFERRED) Under 50 concurrent clinicians on a
  2 vCPU/4 GiB Droplet with Apache prefork, dashboard renders dominate CPU and
  DB connections. Co-pilot requests queue behind them, and any agent design
  that re-renders or scrapes chart pages multiplies this cost.
- **Impact:** Chart opens and co-pilot turns compete for the same workers;
  p95 for both degrades together under load.
- **Likelihood and assumptions:** Certain that the cost exists (deterministic
  1,047 statements); the concurrency effect is INFERRED until the 10/50-user
  load test runs.
- **Recommendation:** The co-pilot never renders or scrapes chart pages. Tools
  return typed JSON from services. Resolve list labels in one batched query
  per tool, and compute ACL decisions once per request. Treat OpenEMR's
  dashboard cost as background load in the 10/50-user tests.
- **Verification:** Load test (PRD requirement) with a mixed scenario: chart
  opens plus co-pilot turns, recording p50/p95/p99 and DB connections.
- **Architecture consequence:** The latency budget allocates OpenEMR tool I/O
  ≤300 ms p95 in total (parallel fan-out), leaving the remainder for the model
  and verification. The co-pilot panel loads asynchronously after the
  dashboard so it never adds to chart-open time.
- **Co-pilot response status (2026-09-16):** Tools call service classes and
  never render or fetch pages (`src/Gateway/Tools/*.php`); the panel is inert
  until the physician clicks and starts no retrieval on chart open. The
  mixed load test has not been run (target 2026-09-19). Measured retrieval on
  the deployment is about 1 s per turn including the agent→gateway HTTP hop
  (`KEY_METRICS.md`), above the 300 ms line in the budget below.

### `PERF-MED-003` No realistic-volume baseline is possible with current data

- **Status:** Partially addressed with synthetic data. The `af-cohort-v1` heavy
  patient (5 years, 120 results, 39 notes) was measured: services ≤37 ms p95,
  dashboard +3% p50. Payload size, not latency, is the constraint (PERF-MED-005).
  Real-world volume distribution is still unknown.
- **Severity:** Medium
- **Observed evidence:** 3 patients, 1 encounter each, 0 lab results, 0 notes
  (cross-ref `data-quality.md` DQ-CRITICAL-001). No clinical table has a
  `(patient, changed-at)` index. Note-form tables have no patient index and are
  reached via `forms(pid, encounter)` (`evidence/performance/indexes.md`).
- **Affected assets and users:** The latency budget, `AI_COST_ANALYSIS.md`,
  and every eval threshold derived from measured payloads.
- **Failure scenario:** Latency and payload-size claims made now would not
  hold for a chronic-care patient with years of labs and notes. Token cost and
  context size are unknown.
- **Impact:** Budgets set on unrepresentative data fail in the first real
  clinic; a demo that passes hides it.
- **Likelihood and assumptions:** Certain for the demo dataset; reduced to
  moderate by AF-HEAVY, which is one planted distribution, not a measured one.
- **Recommendation:** Done for latency and bytes on AF-HEAVY. Remaining:
  capture `EXPLAIN` for the "since last visit" queries, measure provider-tokenizer
  counts, and add a heavier patient if real chart-size data suggests one.
- **Verification:** `cohort-measurements.md` §2–§4 on every reload; the
  load test (2026-09-19) reports p50/p95/p99 with AF-HEAVY in the mix;
  tokenizer counts recorded in `AI_COST_ANALYSIS.md`.
- **Architecture consequence:** Tools have hard bounds: a time window, a max
  rows per resource, and note truncation with an explicit `truncated` flag.
  Payload size is a tracked metric, not an afterthought.
- **Co-pilot response status (2026-09-16):** Bounds implemented: default
  window since the reference encounter, 50 rows per tool and 20 notes with
  `truncated`/`omitted_count` (`AbstractTool::DEFAULT_LIMIT`,
  `ClinicalNotesTool::limit()`), note text capped, and an evidence-pack
  character cap that marks the pack truncated (`agent/app/evidence.py`).
  `REG-HEAVY-001` (golden) runs UC-01 on `AF-HEAVY` live inside 45 s on every
  attempt. Not done: the 10/50-user load test; `EXPLAIN` on the window
  queries; a heavier patient. Per-turn token counts are now measured from
  API usage (PERF-MED-005 status) rather than by the bytes÷4 heuristic.

### `PERF-MED-005` Raw service payloads are too large to hand to the model

- **Status:** Open. Observed on synthetic data (`evidence/performance/cohort-measurements.md` §3).
- **Severity:** Medium
- **Observed evidence:** For AF-HEAVY (5-year chronic patient), six candidate
  tools return 168,610 bytes of JSON (≈42K tokens by bytes÷4): labs 54 KB,
  notes 38 KB, conditions 33 KB (with duplicate rows, DQ-MEDIUM-014),
  encounters 23 KB, active issues 18 KB. AF-DQ-A2 (3 visits) totals 26 KB
  (≈6.5K tokens). Retrieval stays fast (≈52 ms serial in-process).
- **Affected assets and users:** Model context per turn, token cost, the
  4 s generation budget; the physician waiting on the answer.
- **Failure scenario:** (INFERRED) A "what changed since the last visit" turn
  that forwards raw payloads costs tens of thousands of input tokens per
  patient, pushes model latency past the 4 s budget, and buries the relevant
  rows. Truncating without telling the model or clinician produces silent
  omission.
- **Impact:** Latency and cost overrun on every chronic-care patient, or
  silent omission if capped naively.
- **Likelihood and assumptions:** Certain for any design that forwards raw
  service output; the ≈42K figure uses a bytes÷4 heuristic pending the
  provider tokenizer.
- **Recommendation:** Each tool returns a projected, typed schema (only fields
  the use case needs, resolved labels, no internal UUID sprawl). Apply a
  default time window (since the last encounter, with an explicit override),
  per-resource row caps, dedupe by record identity, and `truncated: true`
  with counts when capped. Measure real token counts with the provider
  tokenizer on AF-HEAVY and record them in `AI_COST_ANALYSIS.md`.
- **Verification:** Eval asserting AF-HEAVY UC-01 context ≤ an agreed token
  budget with no omitted in-window change; a truncation eval that forces the
  cap and expects a visible "partial" statement.
- **Architecture consequence:** Context construction is a deterministic tool
  layer responsibility, not the model's. Payload bytes and tokens per tool
  are first-class metrics on the dashboard.
- **Co-pilot response status (2026-09-16):** Implemented. Tools return
  projected typed records (`agent/app/contracts/tools.py`), the agent builds
  a capped evidence pack, and the model sees the pack, never raw service
  output. Measured on the deployment: 608 input, 1,170 output, and 5,106
  cache-read tokens per model-backed turn (n=120, `AF-HEAVY` included; run
  `1ddf824`), against the 42K-token raw payload. Per-tool record counts,
  truncation, and gateway latency are Langfuse tool observations (commit
  `74a1bf6`). Not done: an eval that forces the cap and asserts a visible
  "partial" statement (the runner has an `evidence_truncated` key; no case
  uses it).

### `PERF-LOW-004` Readiness probe bootstraps the full framework

- **Status:** Observed.
- **Severity:** Low
- **Observed evidence:** `readyz` p50 85 ms (n=20). `meta/health/index.php`
  loads `interface/globals.php` on every probe (the in-file comment
  acknowledges it). Semantics are broken separately (`security.md` SEC-MED-007).
- **Affected assets and users:** Apache workers and the DB connection pool
  when orchestrators or uptime monitors probe frequently.
- **Failure scenario:** (INFERRED) A load balancer probing every few seconds
  from several checkers spends a measurable share of a small Droplet's PHP
  capacity on bootstraps that return no useful signal.
- **Impact:** Wasted capacity; low.
- **Likelihood and assumptions:** Low at demo scale (one Caddy, no external
  checker).
- **Recommendation:** None for OpenEMR (documented, not fixed). Do not point
  external monitors at `/meta/health/readyz`.
- **Verification:** The deployment's health checks target the agent's own
  `/health` and `/ready`; OpenEMR's probe is not referenced in Compose or
  Caddy configuration.
- **Architecture consequence:** The co-pilot `/health` stays trivial. `/ready`
  caches dependency results for a few seconds so orchestration probes don't
  amplify load on OpenEMR or the LLM provider.
- **Co-pilot response status (2026-09-16):** Implemented. `/health` returns a
  constant; `/ready` caches its dependency report for 30 s
  (`settings.ready_cache_seconds`, `agent/app/main.py`). Compose health
  checks target `livez` and the agent's `/health`; `readyz` is unrouted at
  Caddy (404 in the 2026-09-15 probe).

---

## Baseline numbers (local, relative)

| Measure | Value |
| --- | --- |
| Patient dashboard | p50 359.5 ms · p95 395.8 ms · 155 KB · ≈1,045 SQL statements |
| Encounter history page | p50 127.0 ms · p95 151.1 ms |
| Login page | p50 130.2 ms · p95 138.7 ms |
| `readyz` | p50 85.4 ms · p95 94.0 ms |
| Clinical services (each, warm, in-process) | p50 1.3–4.6 ms |
| Clinical services on synthetic AF-HEAVY (5 years) | p50 1.4–24.5 ms · p95 ≤36.5 ms |
| Raw tool payload, AF-HEAVY / AF-DQ-A2 | 168.6 KB (≈42K tokens) / 26.1 KB (≈6.5K tokens) |
| Dashboard, AF-HEAVY vs demo pid 1 | p50 362.6 vs 351.4 ms · 1,161 vs 1,047 SQL statements |
| Idle containers | OpenEMR 332.6 MiB / 0.24% CPU · MariaDB 229.2 MiB / 0.01% CPU |

## Proposed co-pilot latency budget (to validate in load tests)

| Stage | p95 budget | Basis |
| --- | --- | --- |
| Gateway auth + patient-scope policy + audit write | 50 ms | ACL is ≈2 queries per check (evidence §2) |
| Parallel tool fan-out (demographics, encounters, issues, meds, allergies, labs, notes) | 300 ms | services 1–5 ms today; 50× headroom for realistic volume + HTTP hop |
| LLM generation (structured claims) | 4,000 ms | not yet measured; dominant term |
| Deterministic verification | 150 ms | in-process, no model call |
| **End-to-end first answer** | **≈4.5–5 s p95** | Fits a 90-second pre-visit window |

*Status 2026-09-16:* superseded by measurement, kept as the original design
budget. The LLM stage was not 4 s: narration takes 5–9 s, repair 5–14 s, and
planning 10–12 s on follow-ups with Sonnet 5 (`KEY_METRICS.md`). The owner
accepted a provisional 30 s p95 for the complete verified response on
2026-09-15 (ADR-0004), with the 8 s design goal tracked, not gated. Measured on
the deployment in the latest full run,
`evals/results/2026-09-17T024919Z-a4a5856.md`: p50 12.5 s, p95 24.1 s, p99
30.7 s over 40 model-backed turns; UC-01 first turns p95 16.0 s; follow-ups
p95 29.7 s. The earlier `--repeat 3` run
(`evals/results/2026-09-16T073141Z-1ddf824.md`, 120 model-backed turns) gave
p50 12.1 s, p95 27.6 s, p99 40.8 s, UC-01 first turns p95 19.1 s, follow-ups
p95 31.4 s, and is kept as stability history. Retrieval is about 1 s per turn. Time to first
evidence is not measured (the runner does not use the SSE path).

## Not measured (required later by the PRD)

- Authenticated public-path latency on the Droplet. Unauthenticated pages were
  measured in the 2026-09-14 cloud window
  (`evidence/performance/page-timing-local.md`, public comparison).
- CPU/memory/throughput under 10 and 50 concurrent users. *Still not
  measured as of 2026-09-16 (target 2026-09-19).*
- p99 at realistic data volume. *Only the serial eval suite's p99 (40.8 s at
  `1ddf824`) exists; no concurrent measurement.*
- LLM latency, token counts, and cost per turn. *Measured 2026-09-15/16 on the
  deployment: see the latency status above, `AI_COST_ANALYSIS.md` Part B, and
  the eval scorecard ($0.0127 list price per model-backed turn at `1ddf824`).*
- Authenticated dashboard render latency on the Droplet remains unmeasured;
  the eval runner opens charts but does not time them.
