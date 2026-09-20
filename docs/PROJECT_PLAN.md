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

This was the pre-audit hypothesis. The audit is complete (2026-09-14,
owner-reviewed the same day), and `AUDIT.md` §8 records where it changed this shape:
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
- [x] Deploy a hardened OpenEMR baseline with demo-only data (edge allowlist,
      project image, demo-seed job; moved to Tuesday and landed with
      `v0.1.0-skeleton` on 2026-09-15: `docs/deployment/digitalocean.md`
      "Before the Evaluator Deployment", probe evidence
      `docs/audit/evidence/security/cloud-probe-2026-09-15-allowlist.txt`).

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
      (reached at tag `v0.2.0-slice`, 2026-09-15; the deployed tag is now
      `week1` at commit `e1dd331`): the UC-01 turn runs on the deployment
      through panel, ticket, agent, gateway, verifier; without the model key
      it renders the deterministic source-cited brief.
- [x] Wire traces (Langfuse, PHI-free, verified 2026-09-15). The dashboard
      panels (`docs/operations/langfuse-dashboard.md`) and the alert job
      (`agent/app/alerts.py`, `docs/operations/alerts.md`) landed 2026-09-16.
- [x] Deploy and smoke-test the vertical slice (Bruno collection 20/20
      against the deployment).
- [x] First live model turns (2026-09-15, Sonnet 5): UC-01, a planned
      follow-up, UC-02, UC-03 on the note-versus-list fixture.

### Wednesday, September 16: early submission

- [x] Add multi-turn follow-up behavior (transcript panel with follow-up
      chips, history restored behind a fresh ticket, 30-minute idle close;
      `ISO-FOLLOWUP-CHAIN-001` chains three turns on the deployment).
- [x] Add authorization, missing-data, malformed-output, and tool-failure
      evals (`evals/cases/`: 47 cases, 9 authorization, 12 missing data, 5
      citation including altered facts and paraphrased advice, 2 tool
      failure, 3 model failure; eleven result reports in `evals/results/`).
- [x] Confirm tokens, cost, latency, tool order, retries, and verification
      outcomes are visible (Langfuse trace per turn with TOOL observations,
      `docs/operations/correlation-id-walkthrough.md`,
      `docs/operations/langfuse-dashboard.md`).
- [x] Export a runnable API collection (`docs/api-collection/`, Bruno, 21
      requests, 41 assertions).
- [x] Record the early demo with several hours of submission buffer
      (recorded and uploaded 2026-09-16: <https://youtu.be/oxm9xqJpiY8>;
      script `docs/DEMO_SCRIPT.md`).
- [ ] Submit the live URL, repository, eval results, observability evidence, and
      video by 11:59 PM CT.

**Status (2026-09-16):** the eval suite is tiered into a 14-case golden set
(`tier: golden`, blocking "Golden set integrity" gate, `--golden-only`),
behavioral coverage by category, and a 4-case holdout set (`holdout: true`,
excluded from filtered runs unless `--include-holdout`); a full run's exit code
follows the release gates, and every report opens with the five-state gate
table (`evals/README.md`). The verifier's advice lexicon was widened after a
manual paraphrase sweep (`CIT-PARAPHRASE-ADVICE-001`). A manual
error-analysis journal (`evals/error_analysis.py`, 20 unscripted turns
across 14 cohort patients) and a local review UI (`evals/review_ui.py`, screenshot `evals/error_analysis/review-ui-2026-09-16.png`)
exist; the journal's review fields are still blank. GitLab CI runs on a
dedicated runner Droplet (`infra/digitalocean/runner/`); the first green
pipeline and a manual `test:evals-live` job against the deployment are
recorded in `docs/SUBMISSION_CHECKLIST.md`. The latest full run recorded in
the tree, `evals/results/2026-09-20T051146Z-0f11642.md`, ran the full 48-case
suite three times against the deployment: 123 of 124 attempts passed, every
blocking gate PASS, golden set 29/29, citations 615/615, model-backed p95
15.8 s, $0.0104 per model-backed turn. Its one miss,
`CONF-DUP-NAMES-C2-001`, is a holdout-tier hedging flip that passed the other
two attempts.

### Thursday–Friday, September 17–18: deepen reliability

- Prepare for and complete the technical interview.
- Apply feedback without destabilizing the early-submission path.
- Add the abnormal-lab follow-up workflow (the UC-02 turn already runs:
  Bruno `2 Use Cases/03 UC-02 Unresolved labs`, `ISO-FOLLOWUP-CHAIN-001`;
  deepening remains).
- Strengthen note-level citations, prompt-injection resistance, context
  isolation, and degradation behavior (baseline cases exist: `INJ-NOTE-O-001`,
  `ISO-*`, `TOOL-OUTAGE-LABS-001`, `MODEL-OUTAGE-001`).
- Finish meaningful `/health` and `/ready` checks and alert definitions
  (alert rules and runbook landed 2026-09-16, `docs/operations/alerts.md`;
  `/ready` dependency checks live; OpenEMR `readyz` stays unrouted).

### Saturday, September 19: production evidence

- [x] Run realistic 10- and 50-concurrent-user tests. *(2026-09-18, a day
      early: `docs/audit/evidence/performance/load-test-2026-09-18.md`. Ten
      users turn p95 45.0 s at 10% errors; fifty users p95 43.8 s at 5.6%,
      with 76% of turns degrading to `partial`. A `--fault model` control run
      making zero model calls reproduced the same shape, placing the ceiling
      in OpenEMR's Apache/PHP and MariaDB rather than the agent.)*
- [x] Record CPU, memory, throughput, p50, p95, p99, and error-rate
      baselines. *(`baseline-2026-09-18.md`: at fifty users `openemr` peaks
      103.2% and `database` 111.0% of a vCPU while `agent` stays under 44%;
      throughput 13.5 turns/min at ten users, 32.2 at fifty; memory never a
      constraint, so ADR-0001's 8 GiB trigger did not fire.)*
- [x] Test deployment from a clean environment, backup/restore, and
      rollback. *(Rehearsed 2026-09-18 on a throwaway Droplet in its own
      Terraform workspace: clean deploy 2m36s, rollback to `week1` 2m36s,
      roll forward 1m13s, restore 3m19s, destroy 25s. The restore was proven
      not to be a no-op. Timings in `docs/deployment/digitalocean.md`.)*
- [x] Complete actual and projected cost analysis. *(`AI_COST_ANALYSIS.md`:
      Part B measured per turn with the per-tier "what breaks first" table
      grounded in the load data; Part A recounted at the final commit.)*
- [x] Finalize documentation and evaluator-facing evidence. *(2026-09-19/20:
      `AUDIT.md` summary cut to the gate, "Known gaps at submission" in
      `docs/INTERVIEW_NOTES.md`, the demo script pointed at evidence that
      exists, and the checklist re-verified against the tree rather than its
      own prose.)*

One unplanned item landed here. Setting the clinic timezone on a subset of
containers put two clocks in one `datetime` column and silently broke
conversation resume; the eval suite caught it, the deployment was returned
to UTC, and the incident is written up in
`docs/audit/evidence/performance/brief-on-open-2026-09-20.md` §10. It is the
clearest thing this week produced in favour of keeping a deterministic suite
that runs against the real deployment.

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
- Eval case format usable as the golden set; GitLab CI skeleton in Week 1
  (done 2026-09-16: `tier: golden` cases with a blocking integrity gate,
  `run.py` exit code follows the gates, so Week 2's PR-blocking gate is a
  threshold change in `.gitlab-ci.yml`, not new infrastructure).
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
