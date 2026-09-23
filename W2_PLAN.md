# Week 2 Vertical-Slice Plan

**Plan date:** Monday, September 21, 2026

**Deadlines:** early submission Wednesday at 11:59 PM CT; final submission Sunday at noon CT

**Planning branch:** `codex/week2-plan-from-scratch`, created from clean `main`

The Week 2 PRD is the sole source of requirements. GitLab issue #16 is used
only for its approved problem statement, failure modes, five boundary rules,
retrieval approach, and gate rules. No code from `codex/week2-implementation`
is part of this plan. Existing Week 2 design-only documents are not evidence
of implementation and must be revised or superseded when they conflict with
this narrower plan.

## Requirements matrix

| ID | PRD requirement or deliverable | How this plan meets it | Slice |
| --- | --- | --- | --- |
| R01 | Accept a lab PDF and an intake form (`Stage 1`, pp. 3–4) | One patient-bound upload path with a closed `lab_pdf \| intake_form` type and per-type strict schema. | 1, 2 |
| R02 | `attach_and_extract(patient_id, file_path, doc_type)` or equivalent (`Core 1`, p. 4) | An equivalent authenticated module command derives the patient from the open chart, stores the file, and starts extraction; neither the model nor caller supplies patient identity. | 1, 2 |
| R03 | Store the source in OpenEMR and round-trip derived facts as FHIR resources or OpenEMR records (`Core 1`, pp. 3–4) | The upload action stores the source in OpenEMR; a later explicit clinician save persists idempotent Observation-shaped or QuestionnaireResponse-shaped module records and reads them back through OpenEMR. | 1, 5 |
| R04 | Strict lab schema and validation tests (`Core 2`, pp. 4, 6) | Require test name, value, unit, reference range, collection date, abnormal flag, extraction status/confidence, and source citation; reject unknown fields. | 1 |
| R05 | Strict intake schema and validation tests (`Core 2`, pp. 4, 6) | Require demographics, chief concern, current medications, allergies, family history, extraction status/confidence, and source citation; reject unknown fields. | 2 |
| R06 | Unsupported or imperfect scans remain visible (`Scenario/Hard Problems`, pp. 2–3) | Field-level missing/ambiguous/unreadable states and typed partial/failure responses; prompt-like document text is data only. | 1, 2 |
| R07 | Hybrid guideline RAG plus rerank (`Stage 2`, `Core 3`, pp. 3–4) | Approved small corpus; FTS5 and dense top-k, reciprocal-rank fusion, pinned local reranker, exact excerpts only. | 3 |
| R08 | One supervisor and two workers with logged handoffs (`Stage 3`, `Core 4`, pp. 3–4) | Inspectable supervisor coordinates `intake_extractor` and `evidence_retriever`; typed route reasons, completion conditions, and parent/child spans. | 4 |
| R09 | Supervisor decides extraction, retrieval, and answer readiness (`Stage 3`, p. 3) | A deterministic decision table routes upload events to extraction and explicit evidence intent to retrieval; answer readiness requires all requested branches to finish or yield typed limitations, then verification. | 4 |
| R10 | Every clinical claim has the minimum machine-readable citation shape (`Core 5`, p. 4) | Resolvers—not the model—emit `{source_type, source_id, page_or_section, field_or_chunk_id, quote_or_value}`; unresolved citations withhold the claim. | 1, 3, 5 |
| R11 | Keep patient-record and guideline evidence grounded and distinct (`Hard Problems`, p. 2) | Separate claim/source unions and UI lanes; guideline excerpts never imply patient applicability. | 3, 4, 5 |
| R12 | Visual PDF bounding-box overlay (`Core 5`, p. 4) | Document resolver opens the immutable source page and overlays the cited normalized bounding box. | 5 |
| R13 | Click-to-source UI and document preview (`Core Deliverables`, p. 5) | Citations open the OpenEMR record, PDF page/box, or approved guideline chunk in place with current authorization rechecked. | 5 |
| R14 | 50 synthetic/demo golden cases and required Boolean rubrics (`Stage 4`, `Core 6`, pp. 3–4) | One curated 50-case release set; each case declares applicable `schema_valid`, `citation_present`, `factually_consistent`, `safe_refusal`, and `no_phi_in_logs` rubrics. | 1, 6 |
| R15 | PR-blocking gate, thresholds, and injected-regression proof (`Core 6`, pp. 4, 6) | Required GitLab job plus matching local hook; block below threshold, on a drop greater than 5 absolute points, or on any new safety failure; preserve red/green mutation artifacts. | 1, 6 |
| R16 | Tool sequence, step latency, tokens, cost, retrieval hits, confidence, and eval outcome (`Core 7`, p. 4) | One correlation ID across UI, module, supervisor, workers, verifier, and CI; allowlisted PHI-free fields only. | 1–7 |
| R17 | Deployed, observable core flow (`Early checkpoint`, p. 3; `Submission`, p. 6) | Slice 1 deploys the lab flow, traces, starter gate, and checkpoint video by Wednesday; later slices update the same deployment. | 1, 7 |
| R18 | `./W2_ARCHITECTURE.md` (`Submission`, p. 6) | Final document explains ingestion, worker graph, RAG, eval gate, risks, and tradeoffs, separating planned from observed behavior. | 7 |
| R19 | `./KEY_METRICS.md` with rationale (`Key Metrics`, p. 3; `Submission`, p. 6) | Replace design-only Week 2 entries with measured safety, quality, latency, cost, and product signals plus thresholds. | 7 |
| R20 | README/setup/deployed link/environment variables; distinguish Week 1 and Week 2 (`Codebase`, p. 3; `Submission`, p. 6) | A Week 2 quick start names the exact services, variables, demo data, and flow without changing the Week 1 baseline instructions. | 7 |
| R21 | Eval dataset, judge configuration, and results (`Submission`, p. 6) | Commit the 50-case manifest, deterministic rubric configuration, pinned baseline, candidate report, and mutation proof; no model self-grading. | 6 |
| R22 | Cost and latency report (`Submission`, p. 6) | Report actual dev spend, projected production cost, p50/p95 by stage and end to end, sample sizes, and bottlenecks. | 7 |
| R23 | 3–5 minute demo video (`Submission`, p. 6) | A Wednesday checkpoint video covers Slice 1; the final video covers both documents, RAG, citations/overlay, eval failure, and traces. | 1, 7 |
| R24 | Early technical interview; final social post and AI interview (`Schedule/Submission`, pp. 3, 6) | Human-owned checklist items with links/status; they are not represented as automated engineering work. | 7 |
| R25 | Narrower and stronger; handle missing data and follow-ups (`Final Note`, p. 6) | Limit core to two document types, two workers, one corpus, one 50-case gate, typed limitations, and reauthorization/re-resolution on every follow-up. | 1–7 |
| X01 | Critic agent, third document type, trend widget, contextual retrieval enhancements (`Core Deliverables`, p. 5) | Treat as extensions: the PRD explicitly calls a critic extension work and warns against widening beyond two document types; none blocks Week 2 core. | Extensions |

## Parent ticket — Deliver a grounded Week 2 multimodal co-pilot

**Goal.** By Sunday noon CT, extend the deployed Week 1 chart-bound co-pilot
with two-document extraction, bounded guideline retrieval, inspectable
supervision, resolver-authored citations, OpenEMR round-trip persistence, and
a 50-case PR-blocking eval gate.

**Acceptance criteria.** A fresh evaluator can use synthetic data to upload
both document types from the open chart, inspect strict extraction and source
regions, explicitly persist and read back derived facts, request separate
guideline evidence, follow every claim to its source, inspect PHI-free traces,
and reproduce a red-then-green gate. All R01–R25 evidence is linked from the
repository; no planned control is presented as implemented. Before code lands,
a short superseding ADR retires only the conflicting Week 2 design choices
(especially the 83-case gate and non-PRD operations) while preserving accepted
Week 1 boundaries.

**Dependencies.** Clean `main`, working Week 1 deployment/auth/tool/verifier/
observability/eval seams, GitLab runner and protected-branch access, synthetic
documents, model credentials, and a human for submission/interview/social
steps.

**Out of scope.** X01, diagnosis/treatment/dosing, open-web retrieval, model-
selected patients, autonomous record writes, real PHI, and non-PRD operations
such as amendments/withdrawals, audit outbox, per-capability readiness,
spend-ledger thresholds, retention sweepers, version caps, or a multi-service
host redesign.

## Child 1 — Wednesday vertical slice: one deployed lab PDF end to end

**Proposed label:** `ready-for-agent`

**Goal.** By Wednesday 8:00 PM CT, deploy the thinnest trustworthy path from
open-chart lab upload to a strict, source-cited extraction answer, basic traces,
and a blocking starter gate, leaving buffer before the 11:59 PM checkpoint.

**Acceptance criteria.** An authorized synthetic user uploads one fixture PDF;
the server derives the open patient, stores one OpenEMR document, invokes the
`intake_extractor`, validates every required lab field, and renders a clearly
labeled extraction preview whose claims have resolver-authored R10 citations.
One citation opens the source page; the full bounding-box overlay may wait for
Child 5. Wrong-patient/replayed intent, malformed scan, missing field, document
prompt injection, altered value/citation, model outage, and PHI-canary tests
fail safely. Traces show route/tool/model/verifier order, timings, tokens, cost,
confidence summary, and no raw content. An automatic MR job blocks the starter
8-case set; the deployed flow and traces appear in a short checkpoint video.

**PRD:** R01, R02, R03 source storage, R04, R06, R10, R14 starter, R15 starter,
R16, R17, R23 checkpoint. **Dependencies:** parent only. **Out of scope:**
intake schema, guideline RAG, durable derived-fact persistence, full overlay,
and the 50-case corpus.

## Child 2 — Add the intake-form path without a second pipeline

**Proposed label:** `ready-for-agent`

**Goal.** Extend the deployed ingestion slice to the second required document
type by configuration and schema, not a parallel architecture.

**Acceptance criteria.** The same upload/extraction/status/UI path accepts a
synthetic intake PDF or image, validates every R05 field and field citation,
shows missing/ambiguous selections explicitly, and rejects a lab payload
misdeclared as intake or unknown fields. A prompt-like instruction in chief
concern cannot change route, tools, or output contract. Lab regression cases
remain green and the deployment demonstrates both document types.

**PRD:** R01, R02, R05, R06, R10, R16, R25. **Dependencies:** Child 1.
**Out of scope:** new document types, automatic updates to demographics,
medications, allergies, or problems, and persistence before clinician action.

## Child 3 — Add one bounded hybrid guideline-evidence worker

**Proposed label:** `ready-for-agent`

**Goal.** Return inspectable guideline excerpts from a small approved corpus
without widening to web search or mixing them with patient facts.

**Acceptance criteria.** A versioned corpus is indexed once with SQLite FTS5
and a pinned dense model; each leg returns candidates, RRF fuses them, and a
pinned local reranker selects the top grounded excerpts. Tests prove a lexical-
only hit, semantic-only hit, rerank order, exact quote/hash, no result, stale or
wrong corpus, timeout, prompt injection, and no fallback. Results use R10,
include retrieval metadata, and render in a guideline lane labeled as not a
patient-applicability conclusion. Retrieval hit counts and timing are PHI-free.

**PRD:** R07, R10, R11, R16, R25. **Dependencies:** Child 1 contracts and
telemetry; may start after those stabilize. **Out of scope:** open web, hosted
reranking, multi-vector search, guideline applicability, query rewriting, and
corpus-refresh automation.

## Child 4 — Put the two workers behind an inspectable supervisor

**Proposed label:** `ready-for-agent`

**Goal.** Make extraction, evidence retrieval, and answer readiness explicit
supervisor decisions while preserving the Week 1 verifier as final authority.

**Acceptance criteria.** A typed decision table routes an authorized upload/
reprocess event only to `intake_extractor`. It routes a chat turn to
`evidence_retriever` only for an explicit UI request or text that asks for a
guideline/source/standard, or asks what evidence supports a named chart or
extracted finding; ambiguous or advice-seeking requests clarify or refuse.
Each decision logs a bounded reason code. The final answer is ready only when
requested branches completed or returned typed limitations and every claim
passed deterministic source resolution/verification. Tests cover all routes,
one-lane failure, duplicate completion, stale handoff, and follow-up
reauthorization, with parent/child trace spans.

**PRD:** R08, R09, R11, R16, R25. **Dependencies:** Children 2 and 3.
**Out of scope:** model-driven routing, a critic worker, worker-authored final
answers, worker record writes, and autonomous guideline retrieval on every
turn.

## Child 5 — Persist reviewed facts and complete click-to-source

**Proposed label:** `ready-for-agent`

**Goal.** Make extracted facts round-trip through OpenEMR and make all source
types directly inspectable without granting write authority to an agent.

**Acceptance criteria.** The extraction preview offers one explicit clinician
`Save reviewed facts` action that rechecks session, open patient, ACL, source
hash, and schema, then idempotently writes an Observation-shaped lab record or
QuestionnaireResponse-shaped intake record owned by the module. Retry creates
no duplicate. A fresh authorized read returns the same typed facts and may
support a later verified patient-record claim. The model, supervisor, and both
workers have no route to this command. Document citations reopen the immutable
OpenEMR source, page, and accessible normalized bounding-box overlay; guideline
and native-record citations resolve through separate adapters. Wrong patient,
wrong page/box, altered quote/value, stale source, unauthorized click, partial
write, and replay fail closed.

**PRD:** R03, R10–R13, R16. **Dependencies:** Children 2 and 4. **Out of
scope:** amendments, withdrawals, native OpenEMR list mutation, automatic
approval by confidence, and same-run promotion by the extractor.

## Child 6 — Finish the 50-case release gate and prove red then green

**Proposed label:** `ready-for-agent`

**Goal.** Turn the starter gate into the evaluator-facing release control,
capped at 50 high-signal cases rather than inheriting the oversized #16 plan.

**Acceptance criteria.** A manifest contains exactly 50 synthetic/demo golden
cases: 10 Week 1 boundary regressions, 14 extraction cases, 8 citation/source
cases, 8 retrieval/supervisor cases, 5 persistence/round-trip cases, and 5
privacy/degradation cases. Cases may assert multiple behaviors and declare only
applicable Boolean rubrics. All five required rubrics have a 100% release
threshold; missing/unmeasured results block. Candidate and pinned baseline use
the same manifest/config. GitLab and the local hook block below threshold, on
more than a 5-point absolute drop, or any new authorization, factual,
safe-refusal, citation-integrity, or PHI-leak failure. A temporary uncited-claim
or telemetry-canary mutation makes the actual MR gate red, then the unchanged
baseline returns green after removal; both reports name commit, dataset,
schemas, corpus, model/prompt, and runtime.

**PRD:** R14, R15, R21. **Dependencies:** Children 1–5. **Out of scope:** more
than 50 release cases, holdout tuning, non-Boolean scoring, and model judging of
its own output.

## Child 7 — Final evidence, documentation, deployment, and demo

**Proposed label:** `ready-for-human` because submission, video publication,
interviews, and the social post require the owner even though documentation
preparation can be delegated.

**Goal.** Make the completed core reproducible and defensible by Sunday 10:00
AM CT, retaining two hours of submission buffer.

**Acceptance criteria.** The public synthetic deployment passes both document
flows, one guideline request, click-to-source overlay, a missing-data/one-lane
failure, PHI-free trace inspection, and the green 50-case gate. Root
`W2_ARCHITECTURE.md` covers ingestion, graph, RAG, verifier, gate, risks, and
tradeoffs. `KEY_METRICS.md` contains measured Week 2 signals and rationale.
README/setup clearly separate Week 1 from Week 2 and list the exact deployed
link and environment variables. The cost/latency report gives actual dev spend,
projected production cost, p50/p95 and bottlenecks. A 3–5 minute final video
shows the core flow and red/green evidence. Human checklist records the early
technical interview, final social post, and AI interview status/links.

**PRD:** R16–R24. **Dependencies:** Children 1–6. **Out of scope:** feature
work after the evidence freeze; any unmet item is reported as residual risk,
not described as complete.

## Decisions (maximum 10)

1. **Open-chart identity only.** The server derives patient/site/user from the live OpenEMR session because neither a model nor a request body may select a patient.
2. **One explicit human write boundary.** Upload stores the source, but only a separate clinician `Save reviewed facts` action can persist derived records; the model, supervisor, and workers stay read-only.
3. **Preview is not chart truth.** Pre-save extraction may answer what the document appears to contain, but it is labeled as a preview and cannot support a later patient-record claim until round-trip persistence and fresh resolution.
4. **Resolver-authored citations.** Models select bounded source IDs; typed resolvers create the PRD citation fields, integrity checks, links, and PDF boxes.
5. **Separate evidence lanes.** Patient records and exact guideline excerpts use different claim/source types and UI lanes so retrieval never becomes a patient-specific recommendation.
6. **Guideline-needed rule.** Retrieve only for an explicit UI request, explicit guideline/source/standard wording, or an evidence question about a named supported finding; ambiguity clarifies and advice intent refuses, with the reason code logged.
7. **Small inspectable graph.** Keep LangGraph, the Week 1 answer/verifier path, exactly two workers, and a deterministic supervisor decision table; no critic agent in core.
8. **Frozen local retrieval.** Use FTS5 plus pinned dense search, RRF, and a pinned local reranker over one approved versioned corpus to bound provenance, latency, and external disclosure.
9. **Exactly 50 release cases.** Curate one high-signal golden set with multi-rubric cases; safety remains zero-tolerance and any category drop over five absolute points blocks.
10. **One deployment shape.** Extend the existing hardened Week 1 deployment and observability path; do not add services or operational controls unless a PRD line requires them.

## Extensions

- A separate critic agent; the deterministic verifier is the core rejection authority.
- A third document type such as referral fax or medication list.
- A lab trend widget built from persisted Observation-shaped records.
- Contextual retrieval beyond the fixed chunking, hybrid retrieval, RRF, and local reranker.
- Amendment/withdrawal workflows, autonomous corpus refresh, and production use with real PHI.

## Residual risks

- OCR/VLM performance on synthetic fixtures will not establish safety on real scan distributions; every low-quality or ambiguous field must remain visible.
- OpenEMR still lacks patient-level authorization beyond chart/section parity; the co-pilot cannot repair that platform limitation.
- Human review reduces but does not eliminate incorrect persistence, and module-owned FHIR-shaped records may not populate native OpenEMR lists.
- A small approved corpus can be incomplete or stale; the product must show the version and fail closed rather than use model memory.
- Fifty cases can miss regressions and the 5-point comparison is coarse on small rubric denominators; zero-tolerance safety failures are the backstop.
- The Wednesday slice is intentionally thin; intake, RAG, full overlay, durable fact persistence, and the complete gate remain final-submission risks until their slices pass.
- Public demo reliability, external model latency, and access to GitLab branch-protection settings remain schedule risks; preserve typed degradation and record any manual control honestly.
