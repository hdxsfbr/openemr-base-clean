# OpenEMR and Clinical Co-Pilot Audit

## Executive Summary

> **Hard-gate placeholder:** Replace this block with an approximately 500-word
> summary before implementing the AI layer. It must identify the highest-impact
> findings across security, performance, architecture, data quality, and
> compliance; explain how those findings changed the proposed agent; and name
> the risks that remain. Do not turn this section into an inventory of every
> observation.

## Audit Record

| Field | Value |
| --- | --- |
| Audit dates | TODO |
| Auditor | TODO |
| Commit | TODO |
| Environment | Local easy-development stack; deployed environment TODO |
| Data classification | Demo data only |
| Scope | OpenEMR baseline and proposed Clinical Co-Pilot integration |
| Out of scope | TODO and rationale |

## Methodology and Evidence Standards

For every finding, record reproducible evidence, affected assets, realistic
impact, likelihood, severity, remediation, and the architecture decision it
influenced. Clearly distinguish observed behavior from inference. Never include
credentials, access tokens, session IDs, or patient data in this document.

Evidence may include sanitized command output, code references, database-schema
observations, timing measurements, access-control tests, dependency diagrams,
and links to versioned test cases.

## Initial Findings to Validate

These are observations from local setup, not the completed audit.

| ID | Area | Observation | Validation required |
| --- | --- | --- | --- |
| PRE-001 | Operations | The development stack exposes several administrative and data services and uses default credentials. | Inventory public bindings and confirm the deployment configuration does not inherit them. |
| PRE-002 | Security | Development compose configuration contains token-like credential values. | Determine provenance without using them; remove from deployment and rotate if potentially valid. |
| PRE-003 | Reliability | `/meta/health/readyz` returns HTTP 200 with a body reporting `setup_required` after successful setup; Docker reports the container healthy. | Trace the installation check, document impact, and add a regression test for readiness semantics. |
| PRE-004 | Security/Performance | Easy development mode enables Xdebug and profiling. | Ensure neither is enabled in the deployed environment and measure overhead if relevant. |
| PRE-005 | Transport | The local HTTPS certificate is self-signed and does not match the container host name. | Use valid TLS at public ingress and document internal transport assumptions. |

## Finding Template

Copy this section for each confirmed finding.

### `[AREA-SEVERITY-NNN]` Finding title

- **Status:** Open / Accepted / Mitigated / Verified
- **Severity:** Critical / High / Medium / Low / Informational
- **Observed evidence:** TODO
- **Affected assets and users:** TODO
- **Threat or failure scenario:** TODO
- **Impact:** TODO
- **Likelihood and assumptions:** TODO
- **Recommendation:** TODO
- **Verification:** TODO
- **Architecture consequence:** TODO

## Security Audit

### Authentication and session management

- [ ] Trace login, session creation, expiry, logout, and CSRF protections.
- [ ] Identify how an embedded module proves the requesting user's identity.
- [ ] Verify that no browser-supplied user or patient identifier is trusted
      without server-side session validation.

### Authorization and patient isolation

- [ ] Map OpenEMR ACL roles relevant to physicians, nurses, residents, and
      administrators.
- [ ] Test authorization at the service/data boundary, not only in UI menus.
- [ ] Examine break-glass behavior and its audit trail.
- [ ] Define how every agent tool rechecks user, patient, and scope.

### Data exposure and prompt injection

- [ ] Inventory PHI crossing each process and network boundary.
- [ ] Review logs, traces, errors, caches, exports, and browser storage.
- [ ] Treat clinical-note content as untrusted input to the model.
- [ ] Test attempts to reveal another patient, system prompts, credentials, or
      tool output.

### Secrets and dependencies

- [ ] Inventory embedded credentials and deployment secrets without recording
      their values.
- [ ] Review dependency and container vulnerability reports.
- [ ] Verify least-privilege runtime identities and network exposure.

## Performance Audit

- [ ] Measure baseline OpenEMR page and relevant API/service latency.
- [ ] Measure the queries and payload sizes required for the core workflow.
- [ ] Identify serial operations that can safely run concurrently.
- [ ] Establish CPU, memory, latency, and throughput baselines.
- [ ] Define cache keys, isolation, expiry, and invalidation behavior.
- [ ] Establish a latency budget for gateway, tools, model, and verification.

## Architecture Audit

- [ ] Diagram browser, PHP application, database, OpenEMR services, module
      events, APIs, audit logger, and deployment topology.
- [ ] Trace the active-user and active-patient context through the application.
- [ ] Identify supported module hooks and extension boundaries.
- [ ] Compare internal services, REST/FHIR APIs, and direct data access.
- [ ] Document trust boundaries and failure domains.

## Data Quality Audit

- [ ] Profile completeness and formats for encounters, notes, medications,
      allergies, problems, and laboratory observations.
- [ ] Find duplicates, inactive/stale rows, missing timestamps, missing units,
      incompatible units, and conflicting records.
- [ ] Identify which values are coded versus free text.
- [ ] Design demo patients that preserve each discovered failure mode.
- [ ] Define when the co-pilot must say "not documented" or refuse comparison.

## Compliance and Regulatory Audit

- [ ] Map minimum-necessary PHI handling and retention for prompts, responses,
      logs, traces, caches, backups, and eval artifacts.
- [ ] Review OpenEMR audit events and identify new agent-specific events.
- [ ] Document BAA assumptions for LLM and observability providers.
- [ ] Define access-log review, breach-response, and deletion procedures.
- [ ] Separate demo-project behavior from requirements for real clinical use.
- [ ] Document known limitations; do not claim HIPAA certification.

## Prioritized Remediation Plan

| Priority | Finding | Action | Owner | Target | Verification |
| --- | --- | --- | --- | --- | --- |
| TODO | TODO | TODO | TODO | TODO | TODO |

## How the Audit Changed the Agent Plan

TODO: For the interview, connect at least three concrete findings to decisions
that differ from the pre-audit architecture hypothesis.

## Residual Risk

TODO: State what remains unsafe, incomplete, or unproven at submission time and
what must change before use with real patients.
