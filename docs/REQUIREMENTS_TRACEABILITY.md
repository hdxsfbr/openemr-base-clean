# Requirements Traceability

This matrix maps the AgentForge PRD to planned implementation and evaluator
evidence. Update the status and evidence links as work lands. A requirement is
not complete merely because code exists; its proof must also be accessible.

Status values: `Not started`, `In progress`, `Verified`, or `Blocked`.

| Requirement | Planned implementation or artifact | Verification evidence | Status |
| --- | --- | --- | --- |
| OpenEMR runs locally with realistic sample data | Development compose stack plus documented clinical demo cohort | `SETUP.md`; repeatable seed command; screenshots or smoke test | Verified locally 2026-09-14 — bundled demo dataset plus deterministic synthetic cohort `af-cohort-v1` (`evals/fixtures/cohort/`: 26 patients, 50 encounters, 134 lab results, 67 notes; identical checksums across reloads; post-load checks pass). Not yet loaded on the deployment (requires a project-built image) |
| Publicly accessible deployment | Single-Droplet Terraform, restricted Compose networks, and Caddy TLS ingress | `docs/deployment/digitalocean.md`; external smoke test | Verified 2026-09-14 — provisioned, public TLS smoke test passed, demo data loaded, then destroyed to control cost between uses; re-provisioned the same evening for the audit's public probe and destroyed again. Re-provision (`tf.sh apply` + `deploy.sh`, ~4 min) before each demo/interview/submission checkpoint |
| Full audit with approximately 500-word summary | Security, performance, architecture, data-quality, and compliance passes | `AUDIT.md` (500-word summary; one section per PRD area with every finding; remediation; plan changes; residual risk); detail and evidence in `docs/audit/` | Draft complete, pending owner review — all five areas audited on 2026-09-14 with live ACL tests, lead spot-checks, an 8-minute public cloud-window probe, and synthetic-cohort measurements. Authenticated Droplet latency and load tests remain later deliverables |
| Narrow target user and concrete workflow | Primary-care physician pre-visit workflow | `USERS.md`; user/use-case review | In progress |
| Every use case explains why an agent is appropriate | Explicit rationale and rejected UI alternatives per use case | `USERS.md` use-case sections | In progress |
| Architecture plan with approximately 500-word summary | Audit-informed context, components, trust boundaries, and tradeoffs | `ARCHITECTURE.md`; ADRs | Not started |
| Key metrics with rationale | Safety, utility, latency, reliability, and cost metrics | `KEY_METRICS.md`; dashboard/eval links | In progress |
| Embedded agentic chatbot | OpenEMR patient-dashboard module | Multi-turn live demo and UI tests | Not started |
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
| Boundary/invariant/regression evals | Versioned clinical fixtures and machine-readable eval cases | `evals/`; CI result artifact | In progress — synthetic fixture cohort `af-cohort-v1` built and verified (`evals/fixtures/cohort/`); cases, runner, and results not started |
| Runnable API collection | Core workflows, health/readiness, and failure examples | Bruno/Postman collection run in CI | Not started |
| Separate health and readiness | Liveness plus meaningful OpenEMR, LLM, and observability dependency checks | Endpoint contract/integration tests | Not started — audit found OpenEMR `readyz` returns HTTP 200 `setup_required` on a working install, locally and publicly (SEC-MED-007); the agent `/ready` must not proxy it |
| Baseline infrastructure profile | CPU, memory, latency, throughput under named scenario | Versioned load-test report | In progress — local, public, and synthetic-cohort single-request baselines recorded (`docs/audit/performance.md`); load-scenario profile not started |
| Load tests at 10 and 50 concurrent users | Realistic authenticated conversation scenario | p50/p95/p99 and error-rate results | Not started |
| AI cost analysis | Actual development spend plus 100/1K/10K/100K-user projections | `AI_COST_ANALYSIS.md`; measured token mix | Not started |
| Repository setup and architecture guide | Evaluator-oriented README additions | Clean-checkout rehearsal | Not started |
| Early and final 3–5 minute demos | Scripted physician workflow plus engineering evidence | Video links and scripts | Not started |
| Technical and AI interviews | Evidence-backed architecture and failure-mode explanations | Interview preparation notes | Not started |
| Final social post | Concise product story and demo media | Post link in submission checklist | Not started |

## Known PRD Naming Ambiguity

The hard-gate section names `USERS.md`, while the submission table names
`USER.md`. `USERS.md` is the canonical document in this repository, and
`USER.md` points evaluators and automated checks to it.
