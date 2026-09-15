# Glossary

One-line definitions for the acronyms and terms used across `AUDIT.md`,
`ARCHITECTURE.md`, the ADRs, and the interview notes.

## Healthcare systems

- **EHR / EMR** (Electronic Health/Medical Record): the clinic's system of
  record for patients, visits, medications, labs. OpenEMR is one. Used
  interchangeably in practice.
- **PHI** (Protected Health Information): any health data tied to an
  identifiable person. What HIPAA protects.
- **HIPAA**: the US law governing PHI. Citations like "45 CFR 164.312(b)" are
  its rule sections.
- **BAA** (Business Associate Agreement): the HIPAA contract required before a
  vendor (LLM provider, tracing service, host) may handle PHI on your behalf.
- **Break-glass**: emergency access that overrides normal permissions, meant
  to be rare and audited. OpenEMR's version is the `Emergency Login` group.
- **HL7 v2**: the older messaging standard labs and hospitals use to exchange
  results. Real lab feeds arrive this way.
- **Encounter**: a visit.

## Data and API standards

- **FHIR** (Fast Healthcare Interoperability Resources, said "fire"): the
  modern HL7 standard exposing health data as JSON over HTTP. A *resource* is
  one typed record: `Patient`, `Condition`, `MedicationRequest`, `Observation`.
- **SMART on FHIR**: the standard for embedding a third-party app in an EHR,
  using OAuth2 on top of FHIR. **SMART launch** (or EHR launch) is the
  handshake that hands the app the current user and the open patient.
- **OAuth2 / OIDC**: web standards for issuing access tokens without sharing
  passwords; OIDC adds identity. SMART is a healthcare profile of both.
- **Scope**: a permission string on a token, such as `patient/Condition.read`.
- **Bearer token**: the string an API client sends to prove it was authorized.
- **REST API**: OpenEMR's own non-FHIR JSON API. Same auth layer as FHIR,
  different shape.
- **RxNorm, ICD-10, ICD-9, LOINC**: coding systems for drugs, diagnoses, and
  lab tests. "Coded vs free text" means whether a record carries one.
- **C-CDA**: an XML document format for exchanging whole charts. Out of scope.

## OpenEMR internals

- **ACL / phpGACL**: OpenEMR's permission system. Grants a role access to a
  **section** (demographics, medications, notes, labs) at a level (view,
  write, addonly).
- **Section**: a chart area used as the unit of permission, e.g.
  `patients/med`.
- **Squad**: OpenEMR's only per-chart restriction, a label roles can be
  denied.
- **pid**: OpenEMR's internal patient ID. **pubpid** is the human-facing chart
  number. **uuid**: the binary identifier used by FHIR and newer services.
- **Session pid**: the one "currently open patient" stored per login.
- **Local API**: OpenEMR calling its own REST API from a logged-in page,
  skipping token checks.
- **Custom module**: a package under `interface/modules/custom_modules/` that
  hooks OpenEMR events; how the co-pilot panel is embedded.
- **RenderEvent**: the module hook that lets a module inject content into a
  chart page.
- **ViewEvent**: the hook the chart fires when a patient is opened; the place
  a patient filter would listen.
- **`lists` / `prescriptions`**: the two tables medications live in.
- **`log` / `log_comment_encrypt` / `api_log`**: the audit-log tables.

## Our project

- **PRD**: the assignment brief (`PRD.pdf`).
- **UC-01/02/03**: the three use cases in `USERS.md`.
- **CAP-01..08**: the eight required agent capabilities in `ARCHITECTURE.md`
  (chart-bound conversation, tool chaining, reference window, reference
  resolution, per-claim citation, absence/conflict states, deterministic
  verification, deterministic fallback). Metrics map to these: explicit
  uncertainty recall proves CAP-06, safe degradation proves CAP-08.
- **DQ-* / PERF-MED-001**: audit-finding IDs (`docs/audit/data-quality.md`,
  `docs/audit/performance.md`) for specific OpenEMR defects found during the
  audit, e.g. `DQ-CRITICAL-001`, `PERF-MED-001` (broken lab retrieval via
  `ProcedureService::getAll()`).
- **Gateway**: the module code between the agent and OpenEMR's services; it
  does authorization, audit, and data shaping.
- **Agent service**: the separate container that runs orchestration and model
  calls and exposes the co-pilot HTTP API.
- **Delegation token** (turn ticket): the short-lived (90 s) signed credential
  bound to one conversation, minted by the module per turn after re-checking
  the session and open patient, that the browser and agent use to call the
  agent API and the gateway.
- **Evidence pack**: the deterministic text rendering of a turn's tool
  records, with source ids inline, that the model narrates from.
- **Claim**: one typed, cited statement in the model's structured output;
  the unit the verifier accepts or withholds.
- **`AuthorizedPatientContext`**: the immutable object (user, patient,
  allowed sections, reason) the gateway hands to every tool.
- **Parity**: the decision that the co-pilot sees exactly what the user could
  see in the chart (ADR-0002).
- **ADR**: Architecture Decision Record, the one-page "we chose X because"
  documents in `docs/adr/`.
- **Eval**: an automated test of the agent's behavior against fixtures.
- **Cohort / fixtures**: the synthetic `AF-*` patients in
  `evals/fixtures/cohort/`. **`AF-HEAVY`**: the 5-year chronic patient (20
  encounters, ~120 lab results, 39 notes) used as the worst-case fixture for
  latency, token, and cost budgets. **`AF-DQ-*`**: patients seeded with a
  specific data-quality defect (missing date, conflicting record, undated
  entry) for uncertainty and absence-handling evals. **`AF-ACL-*`**: patients
  used for authorization/scope evals.
- **Verifier**: the deterministic step that checks every claim against
  retrieved records before display.
- **Summary**: the one-paragraph answer shown above the claims table. Its
  `summary_basis` is `model` when the model's prose passed the summary gate
  (no claim withheld, lexicon clean, every number grounded in a verified
  claim) or `deterministic` when the agent built a count-only paragraph from
  the verified claims instead.
- **Correlation ID**: the identifier carried through one request end to end.
- **LangGraph**: the graph runtime the agent service uses for state and
  edges; nodes are plain Python functions that call the Anthropic SDK.
- **Turn graph**: the eight-node LangGraph (authorize, classify, plan,
  retrieve, narrate, verify, repair, render) that runs one conversation turn.
- **Checkpointer**: LangGraph's persistence of graph state per conversation;
  SQLite in Week 1, and the co-pilot's only transcript store.

## Tooling and operations

- **Trivy**: container image vulnerability scanner. **Semgrep**: static code
  scanner. **CVE**: a catalogued public vulnerability.
- **Caddy**: the reverse proxy terminating TLS at our edge.
- **Droplet**: a DigitalOcean virtual machine.
- **Compose**: Docker Compose, the multi-container runtime definition.
- **Terraform**: the infrastructure-as-code tool that provisions the Droplet.
- **CSRF, XSS**: web attack classes (forged cross-site requests, injected
  scripts).
- **CSP**: a browser header limiting what a page may load or run.
- **p50 / p95 / p99**: latency percentiles.
- **Prefork**: the Apache process model that gives each request its own
  worker; relevant to the 60 s PHP limit.
