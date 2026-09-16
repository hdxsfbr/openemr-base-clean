# Security Audit — Authentication, Authorization, Sessions, API Surface

Track A of the audit. Dependencies/secrets are in `dependencies-secrets.md`.

| Field | Value |
| --- | --- |
| Date | 2026-09-14 |
| Commit | `fc95374` |
| Environment | Local `docker/development-easy` stack (repo bind-mounted; `sites/` is a Docker volume) |
| Method | Code reading, read-only SQL against config/ACL tables, unauthenticated HTTP probes |
| Status | Code-confirmed. Live role-based and cross-patient tests **done locally**; public-deployment checks done in the 2026-09-14 cloud window |

Evidence labels: **OBSERVED** = reproduced from code, SQL, or HTTP output cited here.
**INFERRED** = reasoning from observed facts, not yet exercised live.

## Summary

OpenEMR authorizes by **role and section**, not by **patient**. Any user whose
role grants a patient-data section can load any chart, and the chart's patient
ID is written into the session before any check runs. The browser session
cookie is readable by JavaScript by design, so a single XSS exposes a
PHI-bearing session. The OAuth/REST/FHIR surface is broadly enabled in
the local dev configuration. The fresh deployment has it off, but it would come
back with permissive defaults if re-enabled.
The co-pilot therefore cannot inherit "who may see this patient" from OpenEMR.
It must enforce its own patient-scope policy at the gateway, on every tool call.

---

### `SEC-HIGH-001` No patient-level authorization; access is role/section-based

- **Status:** Open. **Confirmed live**
  (`evidence/security/live-cross-patient-test.md`). Test users with no
  relationship to any patient opened full clinical dashboards: Physicians and
  Clinicians groups got HTTP 200 for pid 1 and pid 2 with all 12 clinical
  sections rendered. Front Office got demographics-level dashboards. The audit
  log recorded a successful `view` per user and patient, and nothing marked the
  access as outside a care relationship.
- **Severity:** High
- **Observed evidence:**
  - `AclMain::aclCheckCore($section, $value, $user, $return_value)` takes no
    patient argument (`src/Common/Acl/AclMain.php:166`). Admin/super
    short-circuits everything (`:174`).
  - Only 4 of 310 classes under `src/Services/` reference `AclMain`
    (`FormService`, `EncounterService`, `PatientPortalService`,
    `FHIR\FhirLocationService`). The services
    that return patients, problems, allergies, medications, and labs trust
    their callers.
  - The only per-patient view hook is `ViewEvent::EVENT_HANDLE`
    (`demographics.php:1054-1061`). Its only listener is the Zend
    `PatientFilter` module (`interface/modules/zend_modules/module/PatientFilter/Module.php:79`),
    which is **not installed**: `modules` lists only Carecoordination, Ccr,
    Documents, Immunization, Syndromicsurveillance.
  - The API path has the same gap. A clinician (`users`) bearer token is checked
    only for role (`BearerTokenAuthorizationStrategy.php:383-385`), scope, and
    per-route section ACL (`RestConfig::request_authorization_check`), with no
    patient filter. The only patient-access hook,
    `checkUserHasAccessToPatient()`, is called at a single site (`:443`), when
    binding a SMART EHR-launch patient to a token, and it returns `true`
    unconditionally (`:479-485`). Verified identical in the deployed
    `openemr:8.1.1` image (offline container, 2026-09-14). REST/FHIR are
    disabled in our deployment, and no token-based request was live-tested.
    The in-session local API sets `skipAuthorization=true`
    (`LocalApiAuthorizationController.php:111`), and `AuthorizationListener`
    returns before any role or scope check (`AuthorizationListener.php:154-157`).
    Cross-checked with `architecture.md` ARCH-HIGH-003; see
    `evidence/architecture/lead-spot-check.md`.
  - `restrict_user_facility` defaults to `0` (`library/globals.inc.php:957`)
    and is empty locally. It only restricts *non-authorized* users to schedule
    facilities; it is not a patient relationship.
  - Default role grants (read-only query of `gacl_*`):

    | Role | Patient-data sections granted |
    | --- | --- |
    | Physicians | write: demo, med, notes, lab, rx, docs, sensitivities/high… |
    | Clinicians (nurse) | addonly: demo, notes, lab, rx, docs; write: med, encounters/notes |
    | Front Office | write: demo, appt; view: alert |
    | Emergency Login | admin/super (everything) |

  - Local accounts: 9 users (6 active, 3 authorized providers). Group membership:
    Administrators 3, Physicians 1, Clinicians 1, Front Office 1, Accounting 1,
    Emergency Login 0.
- **Affected assets and users:** All patient records; every authenticated user.
- **Threat or failure scenario:** A clinician, or a front-desk user holding
  `patients/demo`, opens `demographics.php?set_pid=<any id>` and views any
  patient's chart. A co-pilot that trusts the session patient summarizes
  whichever patient the session points to, for anyone who can reach it.
- **Impact:** The PRD's "physician has access to their own patients" is not
  enforced natively, so minimum-necessary access (45 CFR 164.502(b)/164.514(d))
  depends entirely on role assignment and after-the-fact log review.
- **Likelihood and assumptions:** High in a multi-user clinic. It is standard
  OpenEMR behavior, not a misconfiguration.
- **Recommendation:** Decided in `docs/adr/0002-patient-scope-authorization.md`:
  **parity with the chart.** The gateway binds each conversation to the open
  chart, re-checks the session `pid` every turn, re-runs the chart's section
  ACLs and squad check per tool (the services do none of this), denies
  break-glass sessions (`SEC-INFO-008`), audits every read, and gives the
  model no way to choose a patient. The limitation is stated: isolation
  equals OpenEMR's. A stricter care-relationship policy (schedule, encounter
  provider, care team) was designed and deferred; `users.supervisor_id` is
  not a relationship under either (`SEC-INFO-009`).
- **Verification:** Scripted test with Physician, Clinician, and Front Office
  test users against (a) the chart UI, (b) the co-pilot gateway. Includes a
  negative case per role and a cross-patient case.
- **Architecture consequence:** The patient-scope policy is a first-class
  gateway component, not an inherited property of the OpenEMR session. Tool
  handlers receive a typed `AuthorizedPatientContext` (user, role, pid, allowed
  sections, reason), never a raw pid. The LLM never supplies patient IDs.
- **Co-pilot response status (2026-09-16):** Implemented as parity
  (`oe-module-copilot/src/Gateway/ContextBuilder.php` builds the immutable
  `AuthorizedPatientContext`, policy `parity-1`; per-tool section matrix in
  `ContextBuilder::sectionMatrix()`, printed per user by `bin/acl_matrix.php`).
  The first live role test on 2026-09-15 found `AclMain::aclCheckIssue()`
  returning true for every user in the session-less gateway request; the
  gateway now reads `issue_types.aco_spec` itself and fails closed (commit
  `2dc51a0`). Evals pass live for `audit-physician` and `audit-frontdesk`
  on every `AF-ACL-*` fixture (`AUTH-PARITY-OTHER-001`, `AUTH-UNSCHED-DIRECT-001`,
  `AUTH-SQUAD-001`, `AUTH-FRONTDESK-001`, `AUTH-FORGED-PID-001`; run
  `evals/results/2026-09-16T073141Z-1ddf824.md`). Not done: `audit-nurse`
  through the gateway, and the `ViewEvent` dispatch ADR-0002 describes (no
  reference in the module). OpenEMR itself is unchanged; the finding stays open.

### `SEC-HIGH-002` Session patient context is changed and "view" is logged before authorization

- **Status:** Open. Code-confirmed. Downstream data leak **not reproduced**:
  with session pid set, `audit-frontdesk` (no issue ACLs) requested
  `stats_full.php` for medication, allergy, and medical_problem and got
  **HTTP 403** each time. That page re-checks `aclCheckIssue`
  (`stats_full.php:43,223`). The risk that remains is context confusion and a
  misleading audit trail. Section-ACL bypass via session pid was not observed
  on the page tested; other pages are untested.
- **Severity:** High for the co-pilot's context model; Medium as an
  OpenEMR-native issue.
- **Observed evidence:**
  - `interface/patient_file/summary/demographics.php:84-94` calls
    `setpid($_GET['set_pid'])` and `touchRecentPatientList()` at the top of the
    page.
  - `PatientSessionUtil::setPid()` (`src/Common/Session/PatientSessionUtil.php:44-81`)
    only casts to int, writes `pid` into the session, and emits a `view` audit
    event. It performs no authorization.
  - The page's ACL check comes later (`demographics.php:1056-1061`, plus the
    squad check at `:1069`).
  - 49 of 100 PHP files under `interface/patient_file/` call an `aclCheck*`
    function.
- **Affected assets and users:** The session `pid`, the `log` table's `view`
  events, the recent-patient list, and any embedded component (the co-pilot
  included) that reads session state.
- **Threat or failure scenario:** (INFERRED) A user who is denied the dashboard
  still has `pid` set in the session and an entry in the recent-patient list.
  Subsequent requests that read session `pid` without their own check operate
  on that patient. The audit log records a successful `view` even when the page
  was denied. An embedded co-pilot reading `$_SESSION['pid']` would inherit an
  unauthorized context.
- **Impact:** Context confusion and misleading audit trail.
- **Likelihood and assumptions:** Certain that the ordering exists (code);
  the multi-tab effect is likely in a 20-patient day and remains INFERRED
  until the two-tab test runs. Assumes other `patient_file` pages behave like
  `stats_full.php`, which was not verified.
- **Recommendation:** The co-pilot never treats session `pid` as authorization.
  It treats it as a *request* that must pass `SEC-HIGH-001`'s policy. It binds
  each conversation to (user, pid) at creation and rejects turns whose session
  pid differs.
- **Verification:** Live test: as a restricted user, request `set_pid` for a
  squad-restricted patient. Confirm the session pid, the `log` entry, and what
  one other `patient_file` page returns. Eval case: patient switch mid-conversation.
- **Architecture consequence:** Conversations are patient-bound, and a
  patient switch forces a new conversation. This is a cross-patient-leak guard
  and also defines the cache key.
- **Co-pilot response status (2026-09-16):** Implemented. A conversation is
  bound server-side to (site, user, pid) at start; every per-turn ticket
  re-reads the session pid and, on a mismatch, closes the conversation and
  answers 409 `patient_context_changed`, audited as `copilot-denied`
  (`public/api/ticket.php`). `AUTH-SWITCH-001` (golden) opens a second chart in
  the same session and asserts the 409 and a clean new start; passes live.
  The browser two-tab test itself has not been run.

### `SEC-MED-003` Core session cookie is not HttpOnly and not Secure

> **Cloud window 2026-09-14: confirmed on the public deployment.** Over
> HTTPS through Caddy, `Set-Cookie: OpenEMR=<redacted>; …; SameSite=Strict`
> has no `HttpOnly` and no `Secure` (`evidence/security/cloud-probe-2026-09-14.txt` §3).

- **Status:** Open. Observed.
- **Severity:** Medium
- **Observed evidence:**
  - `SessionConfigurationBuilder::forCore()` sets `setCookieHttpOnly(false)`
    and inherits `cookie_secure => false`
    (`src/Common/Session/SessionConfigurationBuilder.php:26,83-91`).
  - `library/restoreSession.php:44-65` reads and rewrites the session cookie
    from JavaScript (`document.cookie`) to support per-window sessions. The
    flag is a design dependency, not an oversight.
  - The login page response over both HTTP and HTTPS returns
    `Set-Cookie: OpenEMR=<redacted>; Max-Age=28000; path=/; SameSite=Strict`
    with no `HttpOnly` and no `Secure`. By contrast, the OAuth/API sessions set
    `Secure`.
  - Positive controls observed: session ID regenerated at login
    (`interface/main/main_screen.php:403`); `SameSite=Strict`;
    `X-Frame-Options: DENY`; `CSP frame-ancestors 'none'`.
- **Affected assets and users:** The `OpenEMR` session cookie of every
  logged-in user; the co-pilot panel as a new rendering surface inside that
  origin.
- **Threat or failure scenario:** Any stored or reflected XSS, including one
  introduced by rendering model output or note text in a new chat panel, can
  read the session ID and act as the clinician.
- **Impact:** Full account takeover with PHI access.
- **Likelihood and assumptions:** Requires an XSS; OpenEMR has 584 untriaged
  Semgrep results and the co-pilot adds a surface that renders untrusted
  record text and model output. Moderate, and entirely within our control for
  the new surface.
- **Recommendation:** Terminate TLS at Caddy only (`Secure` still absent, but
  no plaintext path is exposed publicly). The co-pilot UI renders model and
  record text as text (no `innerHTML`), with a strict CSP on its assets. Its
  endpoints require the CSRF token plus a short-lived, patient-bound token
  instead of relying on the cookie alone.
- **Verification:** Eval/UI test in which a note contains `<img onerror>` and
  `<script>` payloads. Assert they are rendered inert in the chat panel.
- **Architecture consequence:** Output rendering is part of the trust
  boundary. Clinical text and LLM output are untrusted for both prompt
  injection *and* HTML injection.
- **Co-pilot response status (2026-09-16):** Partly implemented. The panel
  renders every string through `textContent` and DOM APIs, never `innerHTML`
  (`public/assets/js/copilot.js`); endpoints require the CSRF token plus a
  per-turn HMAC delegation token (`DelegationToken.php`). `INJ-NOTE-O-001`
  (golden) passes live: the `AF-DQ-O` payload is quoted, not obeyed, and
  `<script` / `onerror=` do not appear in the response text. Not done: a CSP
  on the module's assets (no CSP header is set by the module) and a
  browser-level test that the payload renders inert. The cookie flags are
  unchanged (allowlist probe 2026-09-15: `OpenEMR` cookie still without
  `HttpOnly`/`Secure`).

### `SEC-MED-004` Weak account-protection defaults for a PHI system

> **Cloud window 2026-09-14:** the deployment has `secure_password=1` (complexity
> on). Lockout thresholds (20/100), `timeout=7200`, and zero MFA registrations
> match local (`evidence/security/cloud-runtime-2026-09-14.md`).

- **Status:** Open. Observed (local config).
- **Severity:** Medium
- **Observed evidence (globals):** `password_max_failed_logins=20`,
  `ip_max_failed_logins=100`, `secure_password` empty (complexity off),
  `gbl_minimum_password_length=9`, `password_expiration_days=0`,
  `timeout=7200` (2 h idle; default in `library/globals.inc.php:2113`), and
  zero rows in `login_mfa_registrations`. Hashing uses PHP
  `PASSWORD_DEFAULT` (bcrypt/argon) (`src/Common/Auth/AuthHash.php:47-80`).
- **Affected assets and users:** Every user account on the public login page;
  unattended sessions on shared workstations.
- **Threat or failure scenario:** Password spraying against a public login
  page gets 20 tries per account before lockout. A 2-hour idle session on a
  shared clinic workstation stays usable.
- **Impact:** Account compromise with full role access; on the demo, exposure
  of the well-known demo credentials to automated login attempts.
- **Likelihood and assumptions:** High for the spraying attempt itself (any
  public OpenEMR login is scanned); success depends on password strength,
  which complexity rules now enforce on the deployment.
- **Recommendation:** For the deployment: lower the lockout thresholds, enable
  password complexity, set idle timeout ≤15–30 minutes, and enable TOTP for
  demo clinical accounts. Document the remaining gaps as "not production".
- **Verification:** Globals dump from the deployed instance; login-lockout
  test.
- **Architecture consequence:** A co-pilot conversation must never outlive or
  extend the OpenEMR session. Every gateway call revalidates the live session.
- **Co-pilot response status (2026-09-16):** Implemented on the co-pilot side:
  each ticket runs under OpenEMR's own `authCheckSession`, re-checks that the
  user is still active, and a conversation idle for 30 minutes is closed
  (`ConversationRepository::IDLE_MINUTES`, commit `983657c`). The deployment's
  lockout, timeout, and MFA settings are unchanged (documented, not fixed).

### `SEC-MED-005` OAuth2/REST/FHIR surface broadly enabled

> **Cloud window 2026-09-14: largely refuted for the deployment.** The fresh
> 8.1.1 install has `rest_api=0`, `rest_fhir_api=0`, `rest_portal_api=0`,
> `rest_system_scopes_api=0`, `oauth_password_grant=0`, and empty
> `site_addr_oath`; OIDC discovery returns 404. FHIR `metadata` and
> `smart-configuration` still answer 200 unauthenticated, and `Patient` returns 401.
> The finding stands for the local dev configuration and as a **guardrail**:
> enabling APIs later (e.g. for SMART launch) reintroduces auto-enable of
> self-registered public clients (`oauth_app_manual_approval=0`) and
> `api_log_option=2`. Deployment severity: Low; dev/config-drift severity: Medium.

- **Status:** Open. Observed.
- **Severity:** Medium
- **Observed evidence:**
  - Globals: `rest_api=1`, `rest_fhir_api=1`, `rest_portal_api=1`,
    `rest_system_scopes_api=1`, `oauth_password_grant=3` (Users + Patients,
    per `src/Console/Command/InstallCommand.php:130`),
    `oauth_app_manual_approval=0`, `oauth_ehr_launch_authorization_flow_skip=1`.
  - Unauthenticated probes: `apis/default/fhir/metadata` 200,
    `.well-known/smart-configuration` 200, OIDC discovery 200. Discovery
    advertises `registration_endpoint` and grant types
    `authorization_code, password, refresh_token`, with 293 scopes.
    `apis/default/api/patient` and `apis/default/fhir/Patient` return 401
    without a token (good).
  - Dynamic client registration enables a client immediately unless its scopes
    require manual approval
    (`src/Common/Auth/OpenIDConnect/Repositories/ClientRepository.php:78-88`).
    With `oauth_app_manual_approval=0`,
    `ScopeRepository::hasScopesThatRequireManualApproval()`
    (`src/Common/Auth/OpenIDConnect/Repositories/ScopeRepository.php:334-363`)
    holds back only two cases: public clients requesting `launch`, and
    confidential clients requesting `user/*` or `system/*` scopes. A
    **public** client requesting `user/*` scopes without `launch` is
    auto-enabled by this logic. That is code-derived; a live registration test
    is pending because it creates a client row.
- **Affected assets and users:** OAuth2 client registry, all user accounts
  (password grant), and every patient resource reachable through REST/FHIR
  once enabled.
- **Threat or failure scenario:** An attacker self-registers a public client
  requesting `user/*` scopes, which is auto-enabled per the logic above. They
  then use the password grant to turn phished or sprayed credentials into
  bearer tokens, bypassing the browser session and its CSRF/SameSite
  protections. `CustomPasswordGrant::validateClient()`
  (`src/Common/Auth/OpenIDConnect/Grant/CustomPasswordGrant.php:112-125`)
  requires only that the client exists and is enabled. It adds no
  confidential-client requirement. Each link in this chain is OBSERVED in
  code. The end-to-end chain is INFERRED until the live test runs; if it
  succeeds, raise severity to High.
- **Impact:** Bearer-token access to all patients with no per-patient filter
  (SEC-HIGH-001), bypassing browser session protections.
- **Likelihood and assumptions:** Low on the deployment (APIs off, verified
  live); moderate on any install that enables the APIs with defaults, because
  each link is standard configuration, not a bug.
- **Recommendation:** The deployment disables the password grant, system
  scopes, and portal API unless needed, and requires manual app approval.
  Consider blocking `/oauth2/*/registration` at Caddy.
- **Verification:** Globals dump plus probes from the deployed host.
- **Architecture consequence:** The co-pilot does **not** use REST/FHIR with
  the password grant or a system-scope service account. A system-scoped token
  would read all patients and discard the user identity. Tools run in-process
  under the user's session, behind the gateway policy.
- **Co-pilot response status (2026-09-16):** Holds. The co-pilot uses the
  in-process module gateway (ADR-0003), not REST/FHIR; the deployment keeps
  the APIs disabled and Caddy leaves `/apis/*` and `/oauth2/*` unrouted
  (allowlist probe 2026-09-15: all 404). Deployed globals were not re-dumped
  after the redeploy to the project image.

### `SEC-MED-006` CSRF verification is per-script and inconsistently applied

- **Status:** Open. Candidates identified; not individually triaged.
- **Severity:** Medium (unconfirmed)
- **Observed evidence:** There is no central CSRF enforcement in
  `interface/globals.php` or `library/auth.inc.php`. 232 files in `interface/`
  call `CsrfUtils::verify*` or `check*`. 65 files read `$_POST` with no such
  call (19 in `modules/`, 16 in `forms/`, 9 in `orders/`). The list is in
  `evidence/security/csrf-candidates.txt`; some may verify via includes.
- **Affected assets and users:** The 65 candidate POST handlers (forms,
  orders, modules) and the records they write; any logged-in clinician as the
  victim.
- **Threat or failure scenario:** A clinician with an active session visits a
  malicious page that submits a form to an unprotected handler, altering a
  record or setting. In older browsers or a same-site context, `SameSite`
  does not apply.
- **Impact:** Unauthorized record changes attributed to the clinician.
- **Likelihood and assumptions:** Low on modern browsers because of
  `SameSite=Strict`; unconfirmed because the candidates were not triaged (out
  of scope: OpenEMR is documented, not fixed).
- **Mitigation observed:** `SameSite=Strict` on the session cookie blocks most
  cross-site POSTs in modern browsers.
- **Recommendation:** Triage the top candidates. Co-pilot endpoints verify the
  CSRF token explicitly and are covered by a negative test.
- **Verification:** A request to any co-pilot endpoint without the CSRF token,
  or with another session's token, returns 403 and writes no audit event
  other than the denial.
- **Architecture consequence:** New module endpoints must not rely on the
  legacy "each script remembers to check" pattern. A single gateway
  middleware enforces session, CSRF, and patient scope.
- **Co-pilot response status (2026-09-16):** The three browser-facing module
  endpoints (`public/api/session.php`, `conversation.php`, `ticket.php`) all
  call `CsrfUtils::verifyCsrfToken` with the `copilot` subject; the tool
  gateway is reachable only from the Docker network with a delegation token
  (Caddy returns 404 for its path). Not done: the negative test (request
  without the CSRF token returns 403 and writes only a denial) is not in the
  eval suite or the Bruno collection, which covers the delegation token
  (`No token`, `Tampered token`) instead. The 65 OpenEMR candidates remain
  untriaged.

### `SEC-MED-007` Readiness probe is semantically wrong and leaks exception messages (confirms PRE-003)

> **Cloud window 2026-09-14: confirmed on the public deployment.** Public
> `/meta/health/readyz` returns HTTP 200 `{"status":"setup_required","checks":{"installed":false,…}}`
> on a working install, and is reachable unauthenticated through Caddy.

- **Status:** Open. Observed with root cause.
- **Severity:** Medium (operations/reliability)
- **Observed evidence** (`evidence/security/readyz-semantics.txt`):
  - An installed system returns HTTP 200
    `{"status":"setup_required","checks":{"installed":false,"database":true,…}}`.
  - Root cause: `meta/health/index.php` loads `sqlconf.php` (`$config = 1`),
    then `interface/globals.php`. That pulls in `library/sql.inc.php:59`, which
    overwrites the global `$config` with a `DatabaseConnectionOptions` object.
    `InstallationCheck` then fails `$config !== 1`
    (`src/Health/Check/InstallationCheck.php:42`).
  - Every result returns HTTP 200, including the exception handler
    (`meta/health/index.php:92`), which echoes `$e->getMessage()` in the body.
- **Affected assets and users:** Compose healthchecks, Caddy `depends_on`,
  any orchestrator or monitor; operators relying on them.
- **Threat or failure scenario:** The database goes away or setup is
  incomplete; the probe still returns 200, Compose reports healthy, Caddy
  routes traffic to a broken app, and the outage is discovered by users. An
  unauthenticated caller reads a stack message from the exception body.
- **Impact:** The probe can never signal "not ready", so orchestrators and
  alerts are blind. Exception text may disclose internals to unauthenticated
  callers.
- **Likelihood and assumptions:** Certain (deterministic bug, confirmed live).
- **Recommendation:** Upstream fix: rename the variable in `sql.inc.php`, or
  have `InstallationCheck` read `sqlconf` state directly. Return 503 when not
  ready and use a generic error body. Add a regression test in
  `tests/Tests/Api/HealthEndpointTest.php`. Do not use `/readyz` as a
  deployment gate until fixed.
- **Verification:** Stop the database container: the agent's `/ready` returns
  503 within its check interval, and nothing in Compose or Caddy depends on
  OpenEMR's `readyz`.
- **Architecture consequence:** The co-pilot's `/ready` performs its own
  dependency checks (OpenEMR gateway round-trip, LLM provider, observability
  backend) with real status codes, as the PRD requires. It does not proxy
  OpenEMR's probe.
- **Co-pilot response status (2026-09-16):** Implemented. `GET /ready`
  (`agent/app/main.py`, `agent/app/readiness.py`) checks the gateway ping,
  the model (`models.retrieve`), the tracer keys, the delegation secret, and
  the state directory; results are cached 30 s and any failure returns 503
  (`agent/tests/test_health.py::test_ready_is_503_when_a_dependency_fails`).
  Caddy exposes only `/meta/health/livez`; `readyz` returned 404 in the
  2026-09-15 probe. Compose health checks use `livez` and the agent's
  `/health`. OpenEMR's probe is unchanged.

### `SEC-INFO-008` Break-glass is detective-only

- **Status:** Observed.
- **Severity:** Informational
- **Observed evidence:** The `Emergency Login` group holds `admin/super`
  (0 members locally). With `gbl_force_log_breakglass=1`, all SQL (including
  SELECTs) by break-glass users is logged even when general audit or
  query-event logging is off (`src/Common/Logging/EventAuditLogger.php:409-444`).
  No reason prompt, time limit, or notification mechanism was found (INFERRED
  from code search; not exhaustively verified).
- **Affected assets and users:** Members of `Emergency Login` (0 locally) and
  every patient record, since the group holds `admin/super`.
- **Threat or failure scenario:** A break-glass account is used routinely
  rather than in emergencies; nothing prompts, limits, or alerts, and only a
  later log review could notice. A co-pilot that auto-summarizes under such
  a session would make bulk browsing faster.
- **Impact:** Undetected over-access; for the co-pilot, amplified disclosure
  under an access mode the PRD does not cover.
- **Likelihood and assumptions:** Low on the demo (no members); a real
  deployment's exposure depends on who holds the group.
- **Recommendation:** None for OpenEMR (documented, not fixed). The gateway
  denies co-pilot use to `Emergency Login` members regardless of relationship
  (ADR-0002 §4) and emits a distinct audit event.
- **Verification:** Add `audit-physician` to `Emergency Login` in a test
  database; the chart opens, the co-pilot denies with `reason=breakglass`,
  and no tool or model call occurs.
- **Architecture consequence:** The co-pilot treats break-glass sessions as
  out of scope for v1: deny with an explicit message and emit a distinct audit
  event. It does not auto-summarize charts under emergency access.
- **Co-pilot response status (2026-09-16):** Denial implemented in code:
  `ContextBuilder::isBreakGlass()` (group `Emergency Login`) is checked at
  conversation start, at every ticket, and when the gateway builds a context;
  each path closes the conversation and audits `copilot-denied` with reason
  `breakglass` (`conversation.php`, `ticket.php`, `ContextBuilder.php`). The
  verification test (adding `audit-physician` to `Emergency Login`) is not
  automated in Week 1 (`evals/README.md`); no recorded run exists in this
  repository.

### `SEC-INFO-009` Resident supervision is recorded for billing, not enforced for access

- **Status:** Observed (code search).
- **Severity:** Informational
- **Observed evidence:** `users.supervisor_id` is set in user admin
  (`interface/usergroup/usergroup_admin.php:381`). `form_encounter.supervisor_id`
  is read by `src/Services/EncounterService.php:199,248`,
  `src/Billing/Claim.php:85-88`, and `library/FeeSheet.class.php:61,129`. No
  reference in `AclMain`, the session utilities, or any authorization path was
  found. Across `src/`, `library/`, and `interface/` there are 25 references
  outside user admin, all in billing, encounter data, or schema typing.
- **Affected assets and users:** Resident and supervising-physician accounts;
  any policy that tried to derive access from `supervisor_id`.
- **Threat or failure scenario:** A gateway policy grants a supervisor every
  patient of every supervised resident (or the reverse) on the strength of a
  billing field that nobody maintains for access purposes, widening scope
  silently.
- **Impact:** The PRD's "a resident may be supervised" has no native access
  semantics. A resident account is just whatever ACL group it is assigned.
- **Likelihood and assumptions:** Certain that the field carries no access
  meaning; the misuse scenario is avoided by not modeling supervision in v1.
- **Recommendation:** None for OpenEMR (documented, not fixed). The gateway
  policy does not consult `users.supervisor_id`; `form_encounter.supervisor_id`
  counts only as an encounter-of-record relationship for that encounter
  (ADR-0002 §2, R2).
- **Verification:** Policy unit test: a user linked to a patient only through
  another user's `users.supervisor_id` is denied.
- **Architecture consequence:** v1 targets the attending primary-care
  physician (`USERS.md`) and explicitly does not model resident supervision.
  The gateway policy denies unsupported roles rather than guessing.
- **Co-pilot response status (2026-09-16):** Holds. The module contains no
  reference to `supervisor_id`; access is decided by the section matrix and
  the chart's squad check only.

---

## Live tests: status (2026-09-14)

Test-user creation path (no CLI exists; `bin/console` only offers `install`):
log in as admin, fetch `interface/usergroup/usergroup_admin_add.php` for its
`csrf_token_form`, then POST to `usergroup_admin.php` with `mode=new_user`,
`rumple` (username), `stiltskin` (new password), `adminPass` (admin
re-authentication, required by `AuthUtils::updatePassword`,
`usergroup_admin.php:406-415`), `fname`, `lname`, `authorized`, and
`access_group[]`. This goes through the application's own validation and ACL
assignment instead of raw SQL.

These ran after the data-quality track profiled the untouched demo data.

| # | Test | Status |
| --- | --- | --- |
| 1 | Create `audit-physician`, `audit-nurse`, `audit-frontdesk` in the matching groups | **Done.** Needed a legacy `groups` row named `Default` (`AuthUtils.php:350-359`) |
| 2a | `set_pid` on unrelated patients per role | **Done.** SEC-HIGH-001 confirmed (`evidence/security/live-cross-patient-test.md`) |
| 2b | `set_pid` on a squad-restricted patient | **Not run** in the chart UI. No demo patient had a squad; fixture `AF-ACL-SQUAD` now exists in the synthetic cohort. *2026-09-16:* the co-pilot gateway path is live-tested by `AUTH-SQUAD-001` (conversation start denied 403/409 for `audit-physician`), passing in run `2026-09-16T073141Z-1ddf824` |
| 2c | Does session pid bypass section ACLs on a follow-up page? | **Done, negative.** `stats_full.php` returned 403 to Front Office |
| 3 | Direct API access as a low-privilege user (bearer token) | **Not run.** APIs are disabled in the deployment; remains residual risk |
| 4 | Prompt-injection and HTML payloads in clinical free text | **Fixture built.** `AF-DQ-O` in `evals/fixtures/cohort/`; rendering test belongs to the co-pilot evals. *2026-09-16:* `INJ-NOTE-O-001` (golden) passes live: the payload is quoted, not obeyed, and no `<script`/`onerror=` reaches the response text. A browser-level render test has not been run |
| 5 | Triage 5 CSRF candidates | **Not run.** SEC-MED-006 remains untriaged |
| — | Public deployment checks (cookie flags, readiness, API surface, deployed globals) | **Done** in the cloud window (`evidence/security/cloud-probe-2026-09-14.txt`, `cloud-runtime-2026-09-14.md`) |
