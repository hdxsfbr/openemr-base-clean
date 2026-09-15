# AgentForge Clinical Co-Pilot — Execution Plan

## Mission

Build a production-minded Clinical Co-Pilot embedded in OpenEMR that helps a
primary-care physician understand what changed for the current patient before a
visit. The product must favor verified, attributable, access-controlled answers
over breadth or apparent intelligence.

The project is successful when an evaluator can see both a useful clinical
workflow and evidence that it behaves predictably when data is missing, access
is denied, a dependency fails, or the model produces unsupported output.

## Product Thesis

### Target user

A primary-care physician seeing approximately 20 patients per day, with roughly
90 seconds to prepare between visits.

### Core workflow

The physician opens an existing patient chart and asks:

1. "What changed since the last visit?"
2. "Which abnormal labs still appear unresolved?"
3. A grounded follow-up such as "What does the chart say about why this
   medication was prescribed?"

The co-pilot responds with concise claims, inline links to source records, and
explicit uncertainty when the chart does not support an answer.

### Initial scope

- Patient context inherited from the active OpenEMR chart.
- Multi-turn conversations scoped to one user and one patient.
- Read-only tools for demographics, encounters/notes, active medications,
  allergies, problems, and laboratory observations.
- A verification stage between model generation and UI rendering.
- Authorization checks for every data retrieval.
- Graceful partial responses when tools or dependencies fail.
- End-to-end correlation IDs, traces, metrics, token usage, and cost.

### Explicit non-goals for the one-week sprint

- Diagnosing conditions or recommending treatment.
- Medication dosing advice.
- Autonomous writes to the medical record.
- A general-purpose medical chatbot.
- Broad specialty coverage.
- Multi-agent orchestration without a demonstrated user need.
- A vector database before structured retrieval proves insufficient.

## Engineering Principles

1. **Authorization before retrieval:** unauthorized data must never enter model
   context.
2. **Evidence before prose:** every patient-specific factual claim must cite a
   source record.
3. **Deterministic safety boundary:** the model cannot approve its own answer.
4. **Minimum necessary data:** tools return only fields required for the current
   use case.
5. **No silent failure:** partial, unavailable, and uncertain states are visible
   to the clinician.
6. **Observability from the first request:** correlation, timing, retries,
   verification, tokens, and cost are designed in rather than added later.
7. **Measure before optimizing:** latency, throughput, correctness, and cost
   changes must have comparable baselines.

## Proposed System Shape

The user interface will be an OpenEMR custom module attached to the patient
dashboard through existing module events. It will rely on the logged-in
OpenEMR session and active patient context.

An OpenEMR-side clinical-data gateway will validate the session, patient scope,
and ACL for every tool request. A separate agent service may orchestrate tools
and the LLM, but it will not receive database credentials or query OpenEMR
tables directly. Requests crossing that boundary will carry a short-lived,
patient-scoped delegation and a correlation ID.

Tool inputs and outputs will be defined as strict schemas. The model will emit a
structured response made of claims and source identifiers. A deterministic
verifier will ensure cited records exist, enforce supported clinical rules, and
withhold claims that cannot be validated.

This was the pre-audit hypothesis. The audit is complete (2026-09-14, pending
owner review), and `AUDIT.md` §8 records where it changed this shape:
- an explicit gateway patient-scope policy, because OpenEMR has no
  patient-level authorization;
- server-bound conversations;
- in-process, projected, deduplicated tools;
- PHI-free telemetry;
- the co-pilot module in our own image, behind a deny-by-default edge; OpenEMR
  issues documented, not fixed (`AUDIT.md` §7.3).

`ARCHITECTURE.md` reflects those decisions; ADR-0004..0007 (LangGraph
runtime and model, state and delegation, verification, observability) were
accepted on 2026-09-15. AI implementation may begin.

## Schedule

All deadlines are Central Time. This schedule assumes the challenge week runs
September 14–20, 2026.

### Friday–Sunday, September 11–13: prepare

- [x] Run the base OpenEMR stack locally.
- [x] Verify the application, database, login, and supporting services.
- [x] Load or design realistic demo patient data (bundled demo dataset, plus
      synthetic cohort `af-cohort-v1` in `evals/fixtures/cohort/`).
- [x] Establish the public deployment path without deploying the development
      compose stack as-is.
- [x] Inventory relevant OpenEMR modules, services, ACLs, APIs, and audit logs
      (`AUDIT.md`, `docs/audit/`).

### Monday, September 14: understand before building

- [x] Complete the security, performance, architecture, data-quality, and
      compliance audit.
- [x] Finish the approximately 500-word executive summary in `AUDIT.md`.
- [x] Define the target user, workflow moment, and use cases in `USERS.md`
      (owner-approved 2026-09-15; clinician-proxy validation still open).
- [x] Select measurable product outcomes and thresholds in `KEY_METRICS.md`.
- [x] Record the audit-driven architecture decisions in `ARCHITECTURE.md`
      and ADR-0004..0007 (accepted 2026-09-15).
- [ ] Deploy a hardened OpenEMR baseline with demo-only data (edge allowlist,
      project image, demo-seed job; moved to Tuesday with the stub deploy).

**Gate:** no AI-layer implementation until the audit is complete.

**Status (2026-09-14):** the audit covers all five areas. It includes
live access tests, a public cloud-window probe, and synthetic-cohort
measurements, and passed owner review on 2026-09-14. The patient-scope authorization
policy (parity with the chart, ADR-0002) and the integration point
(in-process module gateway, SMART deferred, ADR-0003) are decided in
`docs/adr/`. `USERS.md` was revised against the Stage 4 text (workflow
moment, agent-versus-dashboard defense per use case, schedule sweep deferred
as UC-04, capability table) and `KEY_METRICS.md` thresholds are defined;
`ARCHITECTURE.md` is revised against §8 and the ADRs; ADR-0004..0007 were
accepted on 2026-09-15 (Stage 5 gate passed). The clinician-proxy validation
remains.

The reproducible DigitalOcean/Compose path under `infra/digitalocean` was
externally verified on 2026-09-14: provisioned, public TLS smoke test passed,
demo data loaded (3 patients / 3 encounters / 11 appointments, schema upgraded
to current), and torn down again afterward to control cost. Re-provisioning is
a single `tf.sh apply` + `deploy.sh` cycle (~4 minutes) before each demo,
interview, or submission checkpoint. See `docs/deployment/digitalocean.md` for
the runbook and known gotchas found during this run. A second 8-minute window
the same evening re-provisioned from reviewed saved plans for the audit's
public probe (`docs/audit/evidence/security/cloud-probe-2026-09-14.txt`).

### Tuesday, September 15: complete one vertical slice

- [x] Deploy the skeleton before features (`v0.1.0-skeleton`, 2026-09-15):
      module panel, agent `/health` and `/ready`, deny-by-default edge,
      project image, demo seed, CI skeleton.
- [x] Embed the co-pilot shell in the patient dashboard.
- [x] Implement authenticated, typed patient-data tools (seven, behind the
      parity gateway; contracts exported from Pydantic).
- [x] Scaffold the LangGraph turn graph with the checkpointer before the
      first model call.
- [x] Propagate a correlation ID through the UI, gateway, tools, verifier,
      and logs (model and tracer spans join once the keys exist).
- [x] Implement one end-to-end question with citations and verification
      (`v0.2.0-slice`, 2026-09-15): the UC-01 turn runs live on the
      deployment through panel, ticket, agent, gateway, verifier; without the
      model key it renders the deterministic source-cited brief.
- [ ] Wire traces and the operational dashboard (blocked on the Langfuse
      keys; `/metrics` and JSON logs exist).
- [x] Deploy and smoke-test the vertical slice (Bruno collection 20/20
      against the deployment).
- [ ] First live model turn (blocked on the Anthropic key file).

### Wednesday, September 16: early submission

- Add multi-turn follow-up behavior.
- Add authorization, missing-data, malformed-output, and tool-failure evals.
- Confirm tokens, cost, latency, tool order, retries, and verification outcomes
  are visible.
- Export a runnable API collection.
- Record the early demo with several hours of submission buffer.
- Submit the live URL, repository, eval results, observability evidence, and
  video by 11:59 PM CT.

### Thursday–Friday, September 17–18: deepen reliability

- Prepare for and complete the technical interview.
- Apply feedback without destabilizing the early-submission path.
- Add the abnormal-lab follow-up workflow.
- Strengthen note-level citations, prompt-injection resistance, context
  isolation, and degradation behavior.
- Finish meaningful `/health` and `/ready` checks and alert definitions.

### Saturday, September 19: production evidence

- Run realistic 10- and 50-concurrent-user tests.
- Record CPU, memory, throughput, p50, p95, p99, and error-rate baselines.
- Complete actual and projected cost analysis.
- Test deployment from a clean environment, backup/restore, and rollback.
- Finalize documentation and evaluator-facing evidence.

### Sunday, September 20: final submission

- Run the final smoke, security, eval, and deployment checks.
- Record the final 3–5 minute demo.
- Complete the social post and AI interview requirements.
- Target submission by 10:00 AM CT, ahead of the noon deadline.

## Compounding Into Weeks 2 and 3

The Weeks 1–3 syllabus (`../Gauntlet AI - Remote Phase Syllabus (Weeks 1–3).pdf`,
read 2026-09-14) makes Week 2 a multimodal evidence agent (lab PDF and
intake-form ingestion, hybrid RAG for guideline evidence, a supervisor with
two workers, a 50-case golden set, a PR-blocking eval CI gate) and Week 3 an
adversarial platform that attacks this co-pilot unattended, with a
compressed Friday deadline. Week 1 builds none of that, and these choices
were made so those weeks extend rather than replace:

- LangGraph turn graph from the start (ADR-0004), so the supervisor and
  workers are a parent graph and subgraphs, not a port.
- LangGraph checkpointer as the conversation store (ADR-0005), with raw
  records kept out of state.
- `SourceId` as a URI scheme and an open claim-type enum, so document pages
  and guideline chunks become sources without changing the verifier's shape.
- A reserved, empty write-endpoint class in the gateway with idempotency and
  provenance, because round-tripping derived records will need a write ADR.
- Eval case format usable as the golden set; GitLab CI skeleton in Week 1.
- Headless drive path (agent API, ticket script, eval client), fault
  injection switch, token budgets, and a daily spend halt, which are the
  Week 3 attack surface and cost defenses.
- `KEY_METRICS.md` states how each metric could be gamed and what stops it.
- Tag a clean, deployable release on 2026-09-20; Week 2's PRD arrives the
  next morning alongside panel interviews.

## Priorities

### P0 — cannot submit without it

- Required markdown deliverables with concise summaries.
- Public deployment using demo data.
- Embedded multi-turn agent with at least one meaningful tool chain.
- Source attribution and deterministic verification.
- Request-level authorization and patient isolation.
- Eval suite covering boundaries, invariants, and regressions.
- Correlation IDs and live observability.
- Runnable API collection, health/readiness, alerts, baselines, and load tests.
- Demo video and cost analysis.

### P1 — high-value differentiators

- Click-through citations that open the original chart location.
- Visible verification and partial-answer states.
- Deterministic fallback when the LLM is unavailable.
- A trace-to-UI link using the correlation ID.
- Reproducible adversarial test patients with conflicting and incomplete data.

### P2 — only after P0/P1 are stable

- Additional clinical workflows.
- Streaming and speculative prefetching.
- Note chunking or retrieval beyond the initial bounded context.
- More sophisticated clinical terminology mapping.

## Demonstration Story

The final demo should show one coherent workflow:

1. A physician opens a patient chart and receives a concise, sourced brief.
2. A follow-up question triggers more than one typed tool.
3. Clicking a citation opens the underlying OpenEMR record.
4. A missing-data question produces an explicit "not documented" response.
5. An unauthorized or cross-patient request is rejected before an LLM call.
6. A simulated tool failure yields a useful, clearly marked partial result.
7. The request's correlation ID opens a trace showing order, latency, tokens,
   cost, and verification outcome.
8. Eval and load-test results support the product claims.

## Working Cadence and Learning Goals

- Keep changes small and runnable; deploy at least once per day.
- Record consequential choices as architecture decision records under
  `docs/adr/`.
- For every important component, be able to explain the request path, trust
  boundary, failure behavior, and rejected alternatives without consulting an
  AI transcript.
- Add a regression eval whenever a bug or surprising model behavior is found.
- Maintain a short daily list of assumptions disproved and decisions changed.
- Rehearse the interview questions against actual evidence, not aspirational
  architecture.

## Definition of Done

The project is done when a fresh evaluator can access the deployed application,
follow the primary workflow, inspect every factual source, observe a safe
failure, run the documented API collection and eval suite, inspect real
operational metrics, reproduce the deployment, and understand the system's
limitations from the repository alone.
