# Requirements Traceability

This matrix maps the AgentForge PRD to planned implementation and evaluator
evidence. Update the status and evidence links as work lands. A requirement is
not complete merely because code exists; its proof must also be accessible.

Status values: `Not started`, `In progress`, `Verified`, or `Blocked`.

| Requirement | Planned implementation or artifact | Verification evidence | Status |
| --- | --- | --- | --- |
| OpenEMR runs locally with realistic sample data | Development compose stack plus documented clinical demo cohort | `SETUP.md`; repeatable seed command; screenshots or smoke test | Verified locally 2026-09-14 — bundled demo dataset plus deterministic synthetic cohort `af-cohort-v1` (`evals/fixtures/cohort/`: 26 patients, 50 encounters, 134 lab results, 67 notes; identical checksums across reloads; post-load checks pass). Not yet loaded on the deployment (requires a project-built image) |
| Publicly accessible deployment | Single-Droplet Terraform, restricted Compose networks, and Caddy TLS ingress | `docs/deployment/digitalocean.md`; external smoke test | Verified 2026-09-15 — `v0.1.0-skeleton` live at `https://openemr-137-184-4-22.sslip.io`: project image with the module, agent service, deny-by-default edge (probe: 20 sensitive paths 404), demo users and 26-patient cohort seeded, panel rendering on cohort charts. Kept up during build days. Owned hostname still pending |
| Full audit with approximately 500-word summary | Security, performance, architecture, data-quality, and compliance passes | `AUDIT.md` (500-word summary; one section per PRD area with every finding; remediation; plan changes; residual risk); detail and evidence in `docs/audit/` | Complete, owner-reviewed 2026-09-14 (Stage 3 gate passed) — all five areas audited on 2026-09-14 with live ACL tests, lead spot-checks, an 8-minute public cloud-window probe, and synthetic-cohort measurements. Authenticated Droplet latency and load tests remain later deliverables |
| Narrow target user and concrete workflow | Primary-care physician pre-visit workflow | `USERS.md`; user/use-case review | Verified (document) 2026-09-15, owner-approved — 90-second workflow moment (T−30 s to T+90 s), refusals, the per-chart-versus-schedule-sweep decision (sweep deferred as UC-04), rejected and scheduled use cases, and the CAP-01..08 capability table `ARCHITECTURE.md` traces to. Clinician-proxy validation (six checkboxes) still open and tracked in `USERS.md` |
| Every use case explains why an agent is appropriate | Explicit rationale and rejected UI alternatives per use case | `USERS.md` use-case sections | Verified 2026-09-15 — each of UC-01..03 carries a widget / sorted list / chart view / agent comparison, an "honest limit" stating where a non-agent would suffice, and a worked synthetic example; owner-approved. The clinician interview may revise wording |
| Architecture plan with approximately 500-word summary | Audit-informed context, components, trust boundaries, and tradeoffs | `ARCHITECTURE.md`; ADRs | Verified 2026-09-15 (Stage 5 gate passed) — revised against `AUDIT.md` §8 and ADR-0002/0003: 594-word summary, request path, per-turn delegation, CAP-01..08 traceability, tool matrix, contracts, LangGraph turn graph, checkpointed state, verifier, failure matrix, observability, API and Bruno collection design, deployment, Weeks 2–3 compounding. ADR-0004..0007 accepted 2026-09-15 |
| Key metrics with rationale | Safety, utility, latency, reliability, and cost metrics | `KEY_METRICS.md`; dashboard/eval links | Verified (definitions) 2026-09-15 — metrics, gaming defenses, decision thresholds (release gates, the three PRD alerts with responses, risk-acceptance rules) owner-approved; latency and cost thresholds provisional until the load baseline (2026-09-19) and clinician interview; dashboard and eval evidence links land with the implementation |
| Embedded agentic chatbot | OpenEMR patient-dashboard module | Multi-turn live demo and UI tests | In progress — module `oe-module-copilot` renders the panel on the patient dashboard locally and on the deployment (2026-09-15); conversation endpoints, gateway tools, and the turn graph not started |
| Multi-turn context | Conversation scoped to authenticated user and active patient | Follow-up evals; context-isolation tests | Not started |
| Tool invocation and chaining | Strict read-only tools for encounters, meds, problems, allergies, labs, and notes | Traces and tool integration tests | Not started |
| Source attribution for every claim | Claim/source structured output and clickable record citations | Citation correctness and unsupported-claim evals | Not started |
| Domain constraint enforcement | Deterministic rule/policy checks after generation | Verifier unit tests and decision metrics | Not started |
| Verification before response delivery | Model output quarantined until verifier passes | Architecture sequence; fail-closed tests | Not started |
| Authorization and access control | OpenEMR session/ACL check on every tool request; patient-scoped delegation | Role and cross-patient adversarial tests; audit events | Not started — the audit confirmed live that OpenEMR has no patient-level authorization (SEC-HIGH-001), so the gateway must add its own patient-scope policy; test fixtures exist (`audit-*` users, `AF-ACL-*` patients) |
| HIPAA-aware PHI handling | Minimum necessary payloads, encryption, secret management, redacted operational logs | Threat model and audit evidence | In progress — compliance audit complete (`docs/audit/compliance.md`: PHI data-flow inventory, BAA implications, retention, breach notification, proposed audit events); implementation not started |
| Transparent failure behavior | Partial response, retry limits, deterministic fallback, visible errors | Dependency-failure evals and demo | Not started |
| Correlation ID across boundaries | One ID propagated through UI, gateway, agent, tools, LLM, verifier, and logs | Searchable end-to-end trace | Not started |
| Canonical strict contracts | Pydantic/JSON Schema source of truth for requests and tool I/O | Generated schemas and contract tests | Not started |
| Request/tool/LLM observability | Structured events and distributed traces | Trace linked from demo | Not started |
| Real-time operational dashboard | Requests, errors, p50/p95, tool calls, retry count, verification outcomes, tokens, cost, and queue/in-flight depth | Dashboard URL/export and screenshot | Not started |
| Alert definitions and response | Latency, error-rate, and tool-failure alerts | Alert rules and runbook procedures | Not started |
| Boundary/invariant/regression evals | Versioned clinical fixtures and machine-readable eval cases | `evals/`; CI result artifact | In progress — synthetic fixture cohort `af-cohort-v1` built and verified (`evals/fixtures/cohort/`) and loaded on the deployment; `.gitlab-ci.yml` runs whitespace, PHP lint, Caddy and Compose validation, and the agent tests; cases, runner, and results not started |
| Runnable API collection | Core workflows, health/readiness, and failure examples | Bruno/Postman collection run in CI | Not started — designed in `ARCHITECTURE.md` ("Agent HTTP API and the Runnable Collection"): login, open chart, session, start, ticket, four use-case turns, seven failure examples, health and readiness; `docs/api-collection/` in Bruno format with local and deployed environments |
| Separate health and readiness | Liveness plus meaningful OpenEMR, LLM, and observability dependency checks | Endpoint contract/integration tests | In progress — agent `/health` and `/ready` deployed 2026-09-15 with per-dependency detail and a 503 when any fails (gateway ping over the internal network, state store, secrets presence); the LLM and tracer checks are presence-only until the model client and tracer exist. OpenEMR `readyz` is unrouted (SEC-MED-007). Four tests |
| Baseline infrastructure profile | CPU, memory, latency, throughput under named scenario | Versioned load-test report | In progress — local, public, and synthetic-cohort single-request baselines recorded (`docs/audit/performance.md`); load-scenario profile not started |
| Load tests at 10 and 50 concurrent users | Realistic authenticated conversation scenario | p50/p95/p99 and error-rate results | Not started |
| AI cost analysis | Actual development spend plus 100/1K/10K/100K-user projections | `AI_COST_ANALYSIS.md`; measured token mix | Not started |
| Repository setup and architecture guide | Evaluator-oriented README additions | Clean-checkout rehearsal | In progress — `SETUP.md` covers the module and demo users locally; `docs/deployment/digitalocean.md` covers the deployment; root `README.md` additions pending |
| Early and final 3–5 minute demos | Scripted physician workflow plus engineering evidence | Video links and scripts | Not started |
| Technical and AI interviews | Evidence-backed architecture and failure-mode explanations | Interview preparation notes | Not started |
| Final social post | Concise product story and demo media | Post link in submission checklist | Not started |

## Known PRD Naming Ambiguity

The hard-gate section names `USERS.md`, while the submission table names
`USER.md`. `USERS.md` is the canonical document in this repository, and
`USER.md` points evaluators and automated checks to it.
