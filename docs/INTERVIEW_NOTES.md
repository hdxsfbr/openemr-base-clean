# Interview Notes: Pre-Search Checklist Answers

Answers to the PRD's Appendix "Pre-Search Checklist", one section per
heading, as built and measured through 2026-09-16. Each answer names where
the evidence lives. Numbers are from the eval results in `evals/results/`
unless a source is named. Where something is deferred, it says so.

## Phase 1: Define Your Constraints

### 1. Domain selection

- **Use cases.** Three, all for one primary-care physician in the 90 seconds
  before a visit, on one open chart (`USERS.md`): UC-01 what changed since
  the last visit; UC-02 which abnormal results have no later result or
  documented follow-up; UC-03 what the chart says about why a medication is
  listed. Follow-up questions stay inside the same chart and window. Rejected
  or deferred: schedule sweeps, cross-patient questions, documentation
  drafting, anything that writes (`USERS.md` "Rejected and Deferred").
- **Verification requirements.** Every displayed patient-specific fact is a
  typed claim citing a record retrieved this turn, checked field by field by
  a deterministic verifier before anything renders (ADR-0006). Absence,
  conflict, undated, unavailable, and truncated states are stated explicitly,
  never flattened. No diagnosis, treatment, dosing, adherence, interaction,
  or causal statements.
- **Data sources.** OpenEMR's own tables, read through OpenEMR's service
  layer inside a custom module: encounters, problem list, medications (list
  and prescriptions), allergies, lab results, clinical notes, patient
  context. No external sources in Week 1 (`ARCHITECTURE.md` "Tools").

### 2. Scale and performance

- **Query volume.** Sized for 20 patients per physician per day, a few
  turns per patient; single clinic. `AI_COST_ANALYSIS.md` projects 100, 1K,
  10K, and 100K users on the measured token mix.
- **Latency.** Complete verified response p95 under 30 s for the early
  submission, owner-accepted 2026-09-15 with an 8 s design goal
  (`KEY_METRICS.md`). Measured on the deployment across six full eval runs:
  model-backed turns p50 11 to 13 s, p95 21 to 30 s; first turns p95 16 s,
  follow-ups p95 27 to 31 s. Evidence (deterministic retrieval) streams to the
  panel in about 1 s before the narrative.
- **Concurrency.** One 2 vCPU / 4 GB Droplet; tool fan-out is bounded by a
  semaphore, one model call per node. Load tests at 10 and 50 concurrent users
  are a final-submission item.
- **Cost constraints.** 20K tokens per turn, 60K per conversation, and a daily
  token halt that routes to the deterministic fallback (`agent/app/budget.py`,
  ADR-0004). Measured $0.013 to $0.014 per model-backed turn at list price
  with prompt caching (eval scorecards).

### 3. Reliability requirements

- **Cost of a wrong answer.** A fluent unsupported clinical claim is the
  central failure: a physician may act on it. Hence the verifier fails closed,
  and a displayed unsupported claim is treated as a verifier defect, not a
  model one (`KEY_METRICS.md`).
- **Non-negotiable verification.** Source existence, field-level fact match
  per claim type, window membership for changes, lexicon (no advice, no
  causation), absence only after a successful retrieval of that section,
  summary shown only when every claim verified and every number is grounded
  (ADR-0006 §1 to §7).
- **Human in the loop.** The physician is the only actor; the co-pilot is
  read-only, cannot write to the chart, and every claim links to the record
  so the human checks the source in one click. No autonomous actions exist.
- **Audit and compliance.** Every gateway call writes an OpenEMR audit row
  before data leaves, carrying the correlation id; the agent logs are
  PHI-free JSON; traces are masked to digests (ADR-0007). `AUDIT.md` §5 maps
  observations to HIPAA provisions and assumes a BAA with the model provider.

### 4. Team and skill constraints

- **Agent frameworks.** LangGraph was chosen from day one so Weeks 2 and 3
  (supervisor and workers, ingestion, retrieval) extend the graph instead of
  replacing a hand-rolled loop (`docs/PROJECT_PLAN.md`).
- **Domain experience.** Primary-care workflow written down first
  (`USERS.md`) and checked against OpenEMR's real data shapes in a two-day
  audit (`AUDIT.md`) before any agent code; the clinician interview is still
  open (`USERS.md` "Validation Work").
- **Eval and testing.** Comfortable enough to write the suite ourselves: 44
  YAML cases, a runner that drives the real login and chart handshake, pytest
  for the offline invariants. No eval framework (see §9).

## Phase 2: Architecture Discovery

### 5. Agent framework selection

- **Single or multi-agent.** Single agent, one LangGraph turn graph:
  authorize, classify, plan or retrieve, narrate, verify, repair, render
  (`agent/app/graph/`). Multi-agent is deferred to Week 2 when there is a
  second responsibility worth a worker.
- **State.** Per-turn state is reset on every invocation; conversation state
  (history, token totals, closed flag) lives in a LangGraph checkpoint keyed
  by conversation id. Raw records never enter state; the evidence pack is held
  per turn in a store keyed by turn id (ADR-0005).
- **Tool integration.** Seven tools behind one in-process gateway in the
  OpenEMR module, each with a typed contract exported to JSON Schema
  (`contracts/schema/`), a status of ok, empty, partial, or unavailable, and a
  2 s timeout. The agent never touches the database (AGENTS.md hard gate).

### 6. LLM selection

- **Provider.** Claude Sonnet 5 through the Anthropic SDK (ADR-0004), chosen
  on measured latency after Opus 5 was tried first. Provider-neutral swap
  points exist (the model port) but no second provider is wired.
- **Structured output.** JSON-as-text validated by our Pydantic contract,
  with one re-ask on malformed output. The grammar-constrained structured
  output path measured 45 s or more per call and was dropped
  (`agent/app/model.py`).
- **Context window.** Evidence packs are capped in characters and per-tool
  record limits (labs 50, notes 20) with a `truncated` flag; a five-year
  synthetic chart (`AF-HEAVY`) is in every eval run to keep this honest.
- **Cost per query.** About $0.013 measured; acceptable against the
  projection in `AI_COST_ANALYSIS.md`.

### 7. Tool design

- **Tools.** encounters, problems, medications, allergies, lab_results,
  clinical_notes, patient_context (`ARCHITECTURE.md` "Tools"). Each
  normalizes OpenEMR's defects: clinical dates with precision and basis,
  status conflicts flagged, absence states distinguished, text-valued labs
  quoted, orphans omitted.
- **External APIs.** Only the model provider and the tracing backend. No
  third-party clinical APIs.
- **Mock vs real data.** Real OpenEMR, with a deterministic synthetic cohort
  of 26 fictional patients, one per catalogued data defect
  (`evals/fixtures/cohort/`). Recorded tool responses serve as pytest
  fixtures so offline tests share the contract.
- **Error handling per tool.** A failed or denied tool returns `unavailable`
  with a reason; the section is marked unavailable in the answer, no absence
  can be claimed for it, and the rest of the brief still renders (ADR-0006
  §5, `TOOL-OUTAGE-LABS-001`).

### 8. Observability strategy

- **Choice.** Langfuse Cloud (ADR-0007): OpenTelemetry-based SDK, session
  and metadata support, a hobby tier that covers a clinic, and a client-side
  mask so nothing but digests leaves the box.
- **Metrics that matter.** The PRD's request count, latency p50/p95, token
  usage, cost, tool calls and failures, verifier rejections and repair count,
  errors; all on the "Clinical Co-Pilot" dashboard
  (`docs/operations/langfuse-dashboard.md`).
- **Real-time monitoring.** Prometheus-style `/metrics` on the agent, an
  alerts job that evaluates the three PRD alerts against the thresholds in
  `KEY_METRICS.md` (`agent/app/alerts.py`, `docs/operations/alerts.md`).
- **Cost tracking.** Token usage and model cost per generation in every
  trace; per-turn usage in the API response; cost per turn in every eval
  scorecard.

### 9. Eval approach

- **Correctness.** Deterministic assertions on the real system: HTTP status,
  authorization outcome, evidence status per tool, claim types and matchers
  for planted findings, citation resolution, limitations, verifier outcome,
  latency. No model-graded scores in the pass rate (`evals/README.md`).
- **Ground truth.** The synthetic cohort: every defect is planted, so the
  required behavior per patient is known in advance and written into the
  case.
- **Automated vs human.** Automated for everything above; the clinician
  rubric (`USERS.md`) is human-scored and kept in a separate field, never
  aggregated with the deterministic pass rate.
- **CI integration.** The offline subset (verifier and graph invariants via
  pytest) runs on every push in `.gitlab-ci.yml`; the live suite is a
  pre-deploy step because it needs the deployment and the demo password. A
  dedicated runner Droplet was provisioned on 2026-09-16 because the lab
  GitLab had none (`docs/deployment/digitalocean.md` "CI Runner").

### 10. Verification design

- **Claims that must be verified.** All of them. Nine claim types
  (`change_event`, `medication_status`, `problem_status`, `lab_result`,
  `lab_comparison`, `documented_reference`, `absence`, `conflict`,
  `undated`) plus `interpretation`, each with the facts its rule checks
  (`ARCHITECTURE.md` "Verification Design").
- **Fact-checking sources.** The evidence pack retrieved in the same turn,
  through the same authorization as the chart. Nothing outside it counts.
- **Confidence thresholds.** None: verification is binary per claim. A
  rejected claim is withheld and counted; the answer's status becomes
  `partial`; the model's prose summary is replaced by a count-only summary
  when anything was withheld (ADR-0006 §7).
- **Escalation.** A withheld claim triggers one repair round with the
  specific rejection reasons; after that it stays withheld. Model or budget
  failure escalates to the deterministic, cited fallback brief. Operational
  escalation is the alerts runbook.

## Phase 3: Post-Stack Refinement

### 11. Failure mode analysis

- **Tool failure.** Section marked unavailable, no absence claimed, brief
  renders from the other sections; every row of the failure matrix has an
  eval (`ARCHITECTURE.md` "Failure and Degradation Matrix").
- **Ambiguous queries.** The classifier routes anything that is not a
  first-turn UC-01 question to planning with strict tool schemas; out-of-scope
  requests (other patients, schedule, general medicine, dosing) are refused as
  a limitation, not answered. An `interpretation` claim type lets the model
  state a reading the physician can correct.
- **Rate limiting and fallback.** Per-conversation rate limit in the API,
  provider rate-limit and timeout mapped to typed errors, a circuit breaker
  (three failures, 60 s cooldown) in front of the model, token caps and a
  daily halt. All fall back to the deterministic brief.
- **Graceful degradation.** Status is `complete`, `partial`, or `fallback`,
  never a blank panel; the panel shows evidence counts before the narrative
  and a "Records only" badge on fallback.

### 12. Security considerations

- **Prompt injection.** Record text is fenced as data in the pack, the
  system prompt says instructions inside it are not instructions, and the
  verifier means an obeyed instruction still cannot produce a displayed claim
  without a record. Fixture `AF-DQ-O` carries an injection and script payload;
  `INJ-NOTE-O-001` checks it is neither obeyed nor rendered active. The panel
  renders model and record text as text only under a CSP.
- **Data leakage.** Authorization is parity with the chart (ADR-0002): the
  gateway checks the same ACLs OpenEMR does before any tool returns data; a
  patient switch closes the conversation at the ticket stage; forged patient
  ids are rejected by schema. Traces carry digests only; logs are PHI-free.
- **API key management.** Docker secrets on the host, files with mode 600 on
  the workstation, never in the repository, environment dumps, Terraform
  state, or shell history; the runner token follows the same pattern.
- **Audit logging.** One OpenEMR audit row per gateway call with user,
  patient, tool, and correlation id, written before data leaves; denials are
  audited with their reason. Walkthrough in
  `docs/operations/correlation-id-walkthrough.md`.

### 13. Testing strategy

- **Unit tests.** Verifier rules, summary gate, suggestion filter, budget,
  alerts, contracts (58 pytest cases in `agent/tests/`); PHP lint and a
  recorded-response contract test for the tools.
- **Integration.** The turn graph with recorded gateway fixtures and a
  scripted model; the live eval suite drives login, chart open, session,
  ticket, and turn against the deployment as different users; the Bruno
  collection (21 requests, 41 assertions) covers the HTTP contract.
- **Adversarial.** Authorization cases (front office, squad restriction,
  tampered and stale tickets, forged pid, patient switch), injection,
  altered facts, fabricated sources, advice wording, budget exhaustion.
- **Regression.** One case per discovered bug (the `activity=0` with no end
  date conflict, DQ-HIGH-002) and one per cohort defect; results versioned
  per commit in `evals/results/` with a compare script.

### 14. Open source planning

- **Release.** The whole repository: the OpenEMR module, the agent, the
  contracts, the eval suite and cohort, the infrastructure, and the
  documentation.
- **Licensing.** OpenEMR is GPL-3.0; the module and the agent are declared
  GPL-3.0-only (`agent/pyproject.toml`) so nothing in the tree is under a
  conflicting license. No proprietary dependencies; the model provider is a
  service, not a bundled component.
- **Documentation.** `README_AGENT_FORGE.md` for evaluators, `SETUP.md`,
  `ARCHITECTURE.md`, seven ADRs, the audit, the glossary, runbooks under
  `docs/operations/`, and the eval README.
- **Community.** Deferred past Week 1; the social post is a final-submission
  item. The likely first contribution upstream is the cohort seed and the
  data-quality findings, which stand on their own.

### 15. Deployment and operations

- **Hosting.** One DigitalOcean Droplet behind Caddy with automatic TLS,
  Docker Compose, secrets as Docker secrets, Terraform for the host and
  firewall (`docs/deployment/digitalocean.md`, ADR-0001). A second $6 Droplet
  runs CI.
- **CI/CD.** Lints, contract schema check, agent tests, and the offline evals
  on every push; deployment is a scripted step run by the owner after the
  live suite and the Bruno collection pass (`infra/digitalocean/deploy.sh`).
- **Monitoring and alerting.** Langfuse dashboard, `/health` and dependency
  `/ready`, `/metrics`, the alerts job with page and warn thresholds.
- **Rollback.** Images are built from the repository at a commit; rolling
  back is redeploying the previous commit with the same script. The database
  is untouched by the co-pilot (read-only), so rollback has no data migration
  step.

### 16. Iteration planning

- **User feedback.** Clinician interview with the question list in
  `USERS.md`; the follow-up suggestions shown in the panel double as a signal
  of what physicians ask next.
- **Eval-driven cycle.** Baseline run, change, run, compare with
  `evals/compare.py`; the scorecard (withheld rate, repair rate, summary
  basis, cost, latency by turn type) is the quality signal, pass count alone
  is not. Any model, prompt, effort, or planning experiment follows this.
- **Prioritization.** P0 / P1 lists in `docs/PROJECT_PLAN.md`, tied to the
  release gates in `KEY_METRICS.md`; safety gates never trade against
  latency or cost.
- **Long-term maintenance.** Contracts are versioned (1.2.0) and exported
  with a CI drift check; ADRs record every deferred alternative (SMART on
  FHIR, care-relationship authorization, structured output) with the trigger
  that would reopen it.

## Three decisions evaluators will probe

1. **Parity authorization instead of a care-relationship rule** (ADR-0002).
   Defense: the co-pilot can never show more than the chart shows, the rule
   is testable ("could this user open this in the chart?"), and the stricter
   policy is written down with its trigger. Evidence: nine authorization
   cases, audit rows on every denial.
2. **Deterministic verifier before display** (ADR-0006). Defense: the
   safety property does not depend on the model; a weaker model degrades
   quality (withheld rate, count-only summaries) but not safety, which is
   exactly what the scorecard measures.
3. **JSON-as-text over grammar-constrained output** (ADR-0004). Defense:
   measured 45 s or more with constrained decoding versus 5 to 9 s as text,
   with the contract still enforced after parsing and one re-ask on
   malformed output; malformed rate is visible in the traces.
