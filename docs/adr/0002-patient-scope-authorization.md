# ADR-0002: Patient-Scope Authorization for Co-Pilot Tool Calls

- **Status:** Accepted 2026-09-14 (owner decision after audit review)
- **Date:** 2026-09-14
- **Owners:** Andre Batista (project owner; gateway module)
- **Related requirements:** PRD "Authorization & Access Control" (who may query
  patient data; a physician has access to their own patients; a resident may
  be supervised); authorization on every retrieval; unauthorized data never
  enters model context. `AUDIT.md` §1.1, §7.1, §8 row 1. Findings
  SEC-HIGH-001, SEC-HIGH-002, ARCH-HIGH-001/002/003, SEC-INFO-008/009.
- **Related use cases:** UC-01, UC-02, UC-03 (`USERS.md`); all run inside an
  open chart for a patient the physician is about to see.
- **Related decisions:** ADR-0003 (integration point: in-process module
  gateway).

## Context

The audit established, live and in code, that OpenEMR authorizes by role and
chart section only. `AclMain::aclCheckCore` takes no patient argument; only 4
of 310 service classes reference it, none clinical; the REST/FHIR layer checks
role, scope, and section but never patient; and the one patient-access hook is
a `return true` stub. In a live test, Physician and Clinician accounts with no
relationship to any patient opened full dashboards of arbitrary patients, each
logged as an ordinary `view` (`AUDIT.md` §1.1). Nothing in OpenEMR records or
enforces a care relationship. This is the system's design, not a defect, and
it will not change upstream for us.

Two responses were considered. The architecture track recommended **parity**:
bind the co-pilot to the open chart and re-run the chart's own checks. The
security track proposed a **stricter care-relationship policy** (schedule,
encounter provider, care team) that OpenEMR itself does not have. The
synthesized plan briefly committed to the stricter policy; on review, the
owner chose parity for this project.

Constraints: the agent service holds no database credentials (`AGENTS.md`);
the services the gateway calls enforce nothing, so every check the chart
performs must be performed again by us; the demo runs on synthetic data; the
timeline is one week; and the PRD asks for a defended decision with
adversarial tests, not a particular policy.

## Decision

**The co-pilot's patient isolation equals OpenEMR's chart, by decision.** The
gateway grants a tool call exactly when the same user could see the same
section of the same open chart in the OpenEMR UI. It adds no care-relationship
rule in v1. It does add the checks OpenEMR's services omit, and it audits.

### 1. Checks on every tool call (all required, in this order)

| Check | Source of truth | Notes |
| --- | --- | --- |
| Live OpenEMR session, user `active = 1` | `$_SESSION['authUserID']`, `users.active` | Re-read on every request; the co-pilot never extends or outlives the session (SEC-MED-004) |
| Conversation bound to `(site_id, authUserID, pid)` | Gateway conversation store, created at panel render | The client sends only the conversation ID and never a `pid` |
| Request patient = conversation patient = session `pid` | `PatientSessionUtil::getPid()` | A mismatch denies **and closes the conversation** ("patient context changed"). Session `pid` is a request, not a grant (SEC-HIGH-002) |
| Section ACL for the tool's resource | `AclMain::aclCheckCore` / `aclCheckIssue`, the same calls the chart pages make | Problems, allergies, meds → issue ACLs; prescriptions → `patients/rx`; notes → `patients/notes`; labs → `patients/lab`; encounters → `encounters` plus `sensitivities` |
| Squad restriction | `patient_data.squad`, checked as `demographics.php:1069` does | OpenEMR's only per-chart restriction |
| Not a break-glass session | Membership of the `Emergency Login` group | Our one addition beyond parity; see §3 |

The result is an immutable `AuthorizedPatientContext` (user id, role, pid,
patient uuid, allowed sections, reason, policy version) built once per request
by a single adapter class. Tools receive it and never read the session, the
ACL, or a raw `pid` themselves. Section-to-scope mapping is kept one-to-one
with FHIR scopes so the adapter can later be fed from a SMART token
(ADR-0003).

### 2. Freshness

- No authorization decision is cached across requests. Each turn rebuilds
  the context.
- Tool results, where cached, are keyed by
  `(site, user id, pid, tool, tool version, parameter hash)`, live at most
  60 s inside one conversation, and are dropped on conversation end or
  patient switch (`AUDIT.md` §2.2). A cache hit still needs a fresh context.
- The gateway dispatches OpenEMR's own `ViewEvent` when it builds a context,
  so any future upstream or site-level patient filter (the `PatientFilter`
  hook) applies to the co-pilot without a code change.

### 3. Denials and special roles

| Case | Behavior | Audit event |
| --- | --- | --- |
| Session or request `pid` differs from the bound conversation | Deny and close the conversation; the panel offers a new conversation for the open chart | `copilot-denied`, `reason=patient_context_changed` |
| Section ACL fails for one tool | That tool returns `status=unavailable, reason=forbidden`; the answer states the section was not available; other tools proceed | `copilot-denied` per tool |
| Squad-restricted chart | Deny the co-pilot, as the chart itself would | `copilot-denied`, `reason=squad` |
| Break-glass (`Emergency Login` member) | Deny the co-pilot entirely; chart access unchanged. Rationale: bulk AI summarization under emergency access is out of the PRD's scope, and OpenEMR's break-glass is detective-only (SEC-INFO-008) | `copilot-denied`, `reason=breakglass` |
| Roles without clinical section ACLs (Front Office, Accounting, pure admins) | Not a special case: every clinical tool fails its section check, so the co-pilot has nothing to say | `copilot-denied` per tool |
| Resident supervision | Not modeled. `users.supervisor_id` carries no access meaning in OpenEMR (SEC-INFO-009); a resident is whatever ACL group it holds | none |
| API or bearer-token callers, portal users | Out of scope; the gateway accepts only in-session requests carrying a valid delegation (ADR-0003) | `copilot-denied`, `reason=unsupported_principal` |

Every allow also writes an audit event **before** any data is returned
(COMP-HIGH-004). Denials are generic to the caller and specific in the log.

### 4. Stated limitation

The co-pilot can summarize any chart its user could open. In OpenEMR that is
any chart in the site for any clinical role. This is written into
`ARCHITECTURE.md`, the README limitations, and the interview notes. The
co-pilot does not widen access: it has no patient search or lookup tool, works
on one patient per conversation, and every read is logged, so it is bounded by
the same "open a chart and be logged" model as the UI.

### 5. Fixture mapping (`af-cohort-v1`, three `audit-*` users)

| Fixture | Expected behavior |
| --- | --- |
| Any `AF-*` chart open, `audit-physician` or `audit-nurse` | Allowed for the sections their role holds; each read audited |
| Any `AF-*` chart open, `audit-frontdesk` | Every clinical tool `unavailable/forbidden`; the co-pilot reports nothing clinical and explains why |
| `AF-ACL-OTHER` (scheduled with `physician`) open as `audit-physician` | **Allowed.** Documents the parity limitation; the eval asserts the access is audited and identical to the chart, and that the response carries the "isolation equals chart" limitation text |
| `AF-ACL-UNSCHED` requested while a different chart is open | **Denied**, `patient_context_changed`; no tool or model call. Opened directly, allowed (parity) |
| `AF-ACL-SQUAD` | Denied for every non-admin role, as in the chart |
| `audit-physician` added to `Emergency Login` | Chart opens; co-pilot denies with `reason=breakglass` |

## Alternatives Considered

### Care-relationship policy (schedule / encounter provider / care team)

The stricter design, worked out in detail during synthesis and kept here as
the deferred path.

- Rules: R1 appointment with the user as `pc_aid` within today ±1 day, not
  cancelled; R2 user is `provider_id` or `supervisor_id` on a
  `form_encounter` within 24 months; R3 user is `patient_data.providerID` or
  listed in `care_team_provider`. Any one suffices, evaluated live each turn.
- Benefits: makes "a physician sees their own patients" true for the co-pilot
  even though the host cannot; blocks cross-patient browsing through the
  assistant; strong interview story.
- Costs and risks: stricter than the host, so false denials for covering
  clinicians, nurses, and off-schedule prep; three data sources that real
  sites keep inaccurately; schema coupling to schedule and care-team tables;
  roughly a week of policy, tests, and fixtures; and it does not remove any
  parity check, it sits on top of them.
- Reason deferred: out of proportion for a one-week educational build whose
  brief asks for a defended boundary, not a new access model. The seam
  (`AuthorizedPatientContext` builder) is where it would plug in.

### Chart-open only, with no re-check

- Benefits: least code.
- Costs and risks: OpenEMR's services enforce nothing (ARCH-HIGH-002), so a
  tool calling `ConditionService` for a Front Office user would return data
  the chart hides. The session `pid` is also written before authorization
  (SEC-HIGH-002).
- Reason rejected: it is weaker than the chart, not equal to it.

### Reuse OpenEMR's SMART `checkUserHasAccessToPatient()` hook

- Reason rejected: it is a `return true` stub, runs only during SMART launch
  binding, and the APIs are disabled on the deployment (`AUDIT.md` §1.1).

## Consequences

### Positive

- One explainable property: "the co-pilot sees exactly what this user could
  see by clicking." Testable with the fixtures above.
- Coupling is to three stable OpenEMR functions that its own API layer
  depends on, contained in one adapter class and pinned by tests.
- Future upstream patient-level filtering is inherited through `ViewEvent`.
- Finishable within the timeline; the stricter policy remains a documented
  option, not a promise.

### Negative and residual risk

- **Isolation is no better than the host's.** Any clinician can summarize any
  chart, faster than by reading it. Mitigated by one patient per
  conversation, no patient lookup tool, and audit per read. Stated as a
  limitation everywhere the product is described.
- **Parity is only as good as our replication.** A missed section check is a
  leak the chart would not have. Mitigated by the per-tool ACL matrix, a
  deny-by-default adapter, and negative tests per role.
- Break-glass denial is our own rule; a site that relies on emergency access
  would need to revisit it.

## Verification

- **Found by the first live role test (2026-09-15):** `AclMain::aclCheckIssue()`
  returns true for every user when `$ISSUE_TYPES` is not loaded at global
  scope, which is the case in the session-less gateway request; Front Office
  was granted problems and allergies through the co-pilot while the chart
  hides them. The gateway now reads `issue_types.aco_spec` itself and fails
  closed on a missing spec (`ContextBuilder::sectionMatrix`). The
  `bin/acl_matrix.php` CLI prints the effective matrix per user, and the
  Bruno collection's Front Office turn asserts every clinical section is
  `unavailable`. This is the "a missed check is a leak the chart would not
  have" risk realized once and closed; it stays a listed negative test.
- Negative tests per role and per tool: `audit-frontdesk` receives
  `unavailable/forbidden` on every clinical tool, with no service call and no
  model call (assert on audit event order and tracer spans).
- Two-tab test: switch patient in tab 2, send a follow-up in tab 1, expect
  `patient_context_changed` and a closed conversation (ARCH-HIGH-001).
- Cross-patient request eval on `AF-ACL-UNSCHED`: denied before any tool call.
- Squad eval on `AF-ACL-SQUAD`; break-glass eval with `audit-physician` in
  `Emergency Login`.
- Parity eval on `AF-ACL-OTHER`: allowed, audited, limitation text present.
- The model never emits a patient identifier that the gateway honors: a tool
  call with any `pid` argument is rejected by schema.

**Status note (2026-09-16).** Recorded evidence for the items above, in
`evals/cases/` and `evals/results/` (nine authorization cases, passing in every
full run through 2026-09-16):

- `audit-frontdesk`: `AUTH-FRONTDESK-001` asserts every clinical section
  `unavailable`; the no-model-call rule is
  `test_model_is_not_called_when_every_clinical_section_is_unavailable`
  (offline). Audit-event order and tracer spans are not asserted by the case.
- Patient switch: `AUTH-SWITCH-001` (chart switched after `start`, ticket
  answers 409 `patient_context_changed`), through the ticket path rather than
  two browser tabs.
- `AF-ACL-UNSCHED`: `AUTH-UNSCHED-DIRECT-001` covers the "opened directly,
  allowed" half; the "requested while a different chart is open" half is
  `AUTH-SWITCH-001`.
- `AF-ACL-SQUAD`: `AUTH-SQUAD-001` (denied at conversation start).
- `AF-ACL-OTHER`: `AUTH-PARITY-OTHER-001` asserts the turn is allowed and
  every claim cited; it does not yet assert the "isolation equals chart"
  limitation text named in §5.
- Patient identifier in tool parameters: `AUTH-FORGED-PID-001` (live) and
  `test_tool_request_rejects_patient_identifier` (offline).
- Break-glass: no eval case; `docs/REQUIREMENTS_TRACEABILITY.md` records a
  manual check only.
- §2 `ViewEvent` dispatch: not present in the module source as of this note
  (`grep ViewEvent interface/modules/custom_modules/oe-module-copilot/src`
  matches nothing); the audit event per call (`Gateway/Audit.php`) is.

## Revisit Triggers

- Feedback from a clinician proxy that cross-patient summarization is
  unacceptable for the demo, or a multi-clinician deployment.
- A real deployment, where the deferred care-relationship policy becomes a
  requirement before any PHI is touched.
- Upstream or a site implements the `PatientFilter` hook or patient-level
  ACLs; prefer the native mechanism if enforced at the service layer.
- Migration to SMART on FHIR (ADR-0003), where the adapter is fed from token
  claims instead of the session.
