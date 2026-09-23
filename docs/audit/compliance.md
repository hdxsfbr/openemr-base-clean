# Compliance and Regulatory Audit (HIPAA)

| Field | Value |
| --- | --- |
| Audit date | 2026-09-14 |
| Scope | OpenEMR fork baseline (local `docker/development-easy` stack + `infra/digitalocean` definitions) and the *planned* Clinical Co-Pilot (read-only, multi-turn, LLM provider + observability backend) |
| Data classification | Demo/synthetic data only |
| Evidence | `docs/audit/evidence/compliance/01-audit-globals-local-db.txt`, `02-log-tables-schema-counts.txt`, `03-code-references.txt` |
| Method | Source review; read-only `SELECT`s on `globals`, `log`, `log_comment_encrypt`, `api_log`, `extended_log`, schema, and grants (counts/settings only, no patient values) |

## Important disclaimers

- **This is not a HIPAA certification, attestation, or legal opinion.** HHS does
  not certify software as "HIPAA compliant". HIPAA duties fall on covered
  entities and business associates, not on a codebase. This section maps
  technical observations to Security, Privacy, and Breach Notification Rule
  provisions so the architecture can be designed sensibly.
- Per the PRD, we **assume** a Business Associate Agreement (BAA) exists with
  the LLM provider and that the provider does not train on submitted data. That
  is an assumption, not something verified. No BAA was reviewed.
- Labels: **OBSERVED** means seen in a file (path:line) or command output.
  **INFERRED** means reasoning that was not directly tested. **REQ** marks a
  legal requirement. **GP** marks good practice that is not strictly mandated.
- Local values are from the development stack. Deployed values were checked
  read-only during the 2026-09-14 cloud window
  (`evidence/security/cloud-runtime-2026-09-14.md`): `enable_auditlog=1`,
  `audit_events_query=1` (unlike local), `api_log_option=2`, REST/FHIR APIs
  disabled, and the `openemr` DB account holds `ALL PRIVILEGES ON openemr.*`.
  Later statements saying deployed values were not verified are superseded by
  that record.

## 1. OpenEMR audit logging

### 1.1 How it works

- OBSERVED: `EventAuditLogger` writes through a separate DBAL connection to
  `LogTablesSink`. An ATNA (RFC 5425 syslog) sink is added only if
  `enable_atna_audit` is on (`src/Common/Logging/EventAuditLogger.php:36-66`).
  Locally, `enable_atna_audit` is empty (off), so all audit data stays in the
  same MariaDB schema as the clinical data (evidence 01).
- OBSERVED: There are two entry paths:
  - `auditSQLEvent()` is gated by `enable_auditlog` and per-category flags. It
    logs the full SQL statement plus bound values in `comments`
    (`EventAuditLogger.php:405-525`, binds at `:446-452`).
  - `newEvent()` → `recordLogItem()` has **no** `enable_auditlog` check, so
    login, logout, view, api, and access-denied events are always written
    (`EventAuditLogger.php:187-219, 642-695`).
- OBSERVED current local values (evidence 01): `enable_auditlog=1`,
  `audit_events_patient-record=1`, `audit_events_http-request=1`,
  `gbl_force_log_breakglass=1`, `api_log_option=2` (Full).
  - **`audit_events_query` is empty (off)**, though the code default is `1`
    (`library/globals.inc.php:2832-2837`).
  - `gbl_print_log_option=0` (the code default is 2).
  - `audit_events_lab-order` is read at `EventAuditLogger.php:77`, but no global
    by that name exists in `library/globals.inc.php`. It therefore evaluates to
    false, so `procedure_order` and `procedure_order_code` writes are not
    SQL-audited unless the user is a break-glass user.

### 1.2 Is a patient READ (chart view) logged?

- **Yes, coarsely.** OBSERVED: `PatientSessionUtil.php:80` writes a `view`
  event with user and `pid` whenever a patient is set into the session (opening
  a chart). The local DB has 12 `view` rows across 2 patient ids (evidence 02).
- **Page-level, yes.** OBSERVED: `logHttpRequest()`
  (`EventAuditLogger.php:700-734`, called from `interface/globals.php:849`)
  records the script name, query string, and session `pid` for every
  authenticated page. The local DB has 9,758 `http-request-*` rows, and 7,274
  of them carry a non-zero patient id.
- **Record-level reads, no (as configured).** OBSERVED: with
  `audit_events_query` off, SELECTs are skipped (`:440-444`). There are 0
  `patient-record-select` rows. Even with it on, only SELECTs against mapped
  tables are logged (`:501-505`).
- INFERRED: the HTTP log shows *which page* a user opened. It does not show
  *which data elements* were returned. REST and FHIR reads are covered only by
  `api_log` (1.4).
- INFERRED: requests made through OpenEMR's internal "local API" are **not**
  recorded in `api_log` (`ApiResponseLoggerListener.php:52-53`). If the
  co-pilot gateway calls services in-process or through the local API, its
  reads will not be audited unless new events are added (Section 5).

### 1.3 Tamper evidence and admin control over logs

- OBSERVED: each row gets an **unkeyed** SHA3-512 checksum over its
  concatenated fields, stored in `log_comment_encrypt.checksum`. API rows also
  get `checksum_api` (`LogTablesSink.php:63, 83-94`).
- OBSERVED: verification runs only on demand, in
  `interface/reports/audit_log_tamper_report.php:241-265` (ACL `admin/super`,
  `:30`). No scheduled verification or alerting was found.
- OBSERVED: the application DB account has `ALL PRIVILEGES ON openemr.*`
  (evidence 02). There are no triggers, no append-only storage, and no external
  log shipping (ATNA off).
- INFERRED: anyone with the app's DB credentials, or with SQL access through
  the admin phpMyAdmin that the dev stack exposes, can alter a row *and* its
  checksum. The checksum therefore detects accidental corruption, not
  deliberate tampering.
- OBSERVED: a super-admin can remove all online audit rows through the UI.
  The "EventLog Backup" action in `interface/main/backup.php:1000-1027,
  1103-1107` renames `log`, `log_comment_encrypt`, and `api_log`, dumps them
  to `backup_log_dir`, then **drops** them. The default and current directory
  is `/tmp`, and the code creates it `0777` (`:1005-1006`).
- OBSERVED: `extended_log` disclosure entries can be edited and hard-deleted
  (`EventAuditLogger.php:596-626`).
- OBSERVED: log viewing needs only `admin/users` (`interface/logview/logview.php:29`).
  The logs contain PHI (SQL binds, API bodies).

### 1.4 REST/FHIR access logging and PHI in `api_log`

- OBSERVED: `ApiResponseLoggerListener` writes one `api` event plus an
  `api_log` row per external API request (`:39-105`).
- OBSERVED: with `api_log_option=2` (current value and code default), the full
  JSON or FHIR+JSON **response body is stored twice**, in both `request_body`
  and `response` (`:84-85`). The row is also summed into `checksum_api`.
  Option 1 blanks the bodies.
- INFERRED: every FHIR read of a patient's Observations, Conditions, and
  similar resources copies PHI into a log table with no retention limit. That
  multiplies the PHI footprint and breach scope, and it goes beyond what an
  audit trail needs (45 CFR 164.502(b) minimum necessary; 164.312(b) calls for
  recording activity, not copying content).

### 1.5 Regulatory mapping

| Requirement | Source | Baseline status |
| --- | --- | --- |
| Audit controls: record and examine activity in systems containing ePHI | REQ 45 CFR 164.312(b) | Partially met. Events exist, but record-level reads and local-API reads are not captured. INFERRED |
| Information system activity review: regularly review audit logs and access reports | REQ 164.308(a)(1)(ii)(D) | No review procedure or tooling beyond manual reports. OBSERVED (no scheduler found) |
| Integrity: protect ePHI from improper alteration or destruction | REQ 164.312(c)(1) (addressable mechanism 164.312(c)(2)) | Unkeyed checksums, same-DB storage, app account can delete. OBSERVED |
| Log-in monitoring | Addressable 164.308(a)(5)(ii)(C) | Login/logout/auth failure events present. OBSERVED (`login` 26, `logout` 26) |
| Accounting of disclosures | REQ 164.528 | `extended_log` manual disclosure entry exists but is mutable. OBSERVED |

## 2. Retention and deletion

- **Legal baseline:** HIPAA does **not** set a retention period for medical
  records or audit logs. 45 CFR 164.316(b)(2)(i) requires Security Rule
  *documentation* (policies, procedures, required activity/assessment records)
  to be kept for 6 years from creation or last effective date. Many
  organizations apply 6 years to audit logs as GP. Medical-record retention is
  set by state law (REQ, state-specific), and accounting of disclosures covers
  6 years (164.528).
- OBSERVED: no time-based retention or purge job exists for `log`, `api_log`,
  or `extended_log`. The only mechanism is the manual or cron "EventLog Backup"
  rotation above (`Documentation/README-Log-Backup.txt:4-11`), which exports
  and then drops the tables. Retention of the exported file is undefined.
- OBSERVED: `log` has rows dated back to 2014 from the bundled demo dump
  (evidence 02), so logs are kept indefinitely by default.
- OBSERVED: no patient-level deletion or purge workflow was identified for the
  co-pilot scope. Deleting clinical data would not cascade to logs.
  (`api_log` bodies and `log.comments` SQL binds keep copies. INFERRED.)
- OBSERVED (DigitalOcean): `backups = false` (`infra/digitalocean/main.tf:22`).
  The runbook states "There is intentionally no backup"
  (`docs/deployment/digitalocean.md:41-45, 167-168`), and backup/restore is a
  TODO (`:206`). Data lives in Droplet-local named volumes
  (`runtime/compose.yaml:104-110`).
- Contingency plan (data backup, disaster recovery) is REQ 164.308(a)(7).
  Having no backups is acceptable only because the data is disposable demo
  data.

## 3. Encryption

HIPAA treats encryption as *addressable* (164.312(a)(2)(iv) at rest,
164.312(e)(2)(ii) in transit). Encryption consistent with HHS guidance is also
the "safe harbor" that makes lost data "secured" and therefore not a
notifiable breach (164.402, HHS Guidance to Render Unsecured PHI Unusable).

### At rest

- OBSERVED: `database_encryption=1` and `drive_encryption=1` (evidence 01).
  Database keys are stored base64 in the `keys` table (4 rows) in the **same
  schema** (`CryptoGen.php:401-433`). Drive keys live under
  `sites/<site>/documents/logs_and_misc/methods/` (3 files) and are themselves
  encrypted with the database key (`CryptoGen.php:448-462`).
- INFERRED: a database dump alone yields the database keys. A database dump
  plus the `openemr_sites` volume yields every key. Application-level
  encryption therefore does not protect against a full-host or backup
  compromise.
- INFERRED (not exhaustively verified): `database_encryption` covers selected
  secrets and fields such as tokens and credentials. Core clinical tables
  (`patient_data`, `lists`, `procedure_result`, `form_*`) and all log tables are
  plaintext. OBSERVED: `log_comment_encrypt.encrypt='No'` on all 9,930 rows;
  the log-encryption path was removed (`EventAuditLogger.php:660-661`).
- OBSERVED: MariaDB `innodb_encrypt_tables=OFF` and `innodb_encrypt_log=OFF`
  (evidence 02). No volume or disk encryption is configured in
  `infra/digitalocean`. INFERRED: DigitalOcean encrypts storage at the provider
  layer, but that was not verified and is outside our control.
- OBSERVED: the OAuth signing private key sits in
  `sites/default/documents/certificates/oaprivate.key` on the same
  `openemr_sites` volume.

### In transit

- OBSERVED: public edge TLS is Caddy with automatic ACME, HSTS, nosniff, and
  Referrer-Policy (`infra/digitalocean/runtime/Caddyfile:6-17`).
- OBSERVED: Caddy → OpenEMR is plain `http://openemr:80` on the Docker
  `frontend` bridge (`Caddyfile:16`). INFERRED: this stays on one host, which
  is acceptable for a single-Droplet demo. A multi-host deployment would need
  internal TLS or mTLS.
- OBSERVED: the server reports `have_ssl=YES` with
  `require_secure_transport=OFF`, and the `openemr` user has no `REQUIRE SSL`.
  App DB TLS is enabled only when `documents/certificates/mysql-ca` exists
  (`src/BC/DatabaseConnectionOptions.php:136-160`), and that file is absent
  locally. INFERRED: application DB traffic is unencrypted. The DO backend
  network is `internal: true` (`compose.yaml:112-115`), which limits exposure.
- INFERRED (planned): agent service → LLM provider and → observability backend
  cross the public internet and **must** use TLS 1.2+ (REQ-level expectation
  under 164.312(e)(1); GP to pin to provider endpoints).

## 4. PHI data-flow inventory for the planned co-pilot

Assumptions: patient context comes from the OpenEMR session, and a gateway
enforces ACL before retrieval (`docs/PROJECT_PLAN.md:56-66`). "BAA?" asks
whether a third party creates, receives, maintains, or transmits PHI on our
behalf (164.502(e), 164.504(e), 164.308(b)).

| # | Data element / store | PHI present? | Minimum-necessary rule (164.502(b)) | Retention (proposed) | Access control | BAA needed? |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Clinician question text | Possibly (free text may name patients or conditions) | Do not add identifiers; patient bound by session, not typed name | Conversation lifetime only | Session user + patient lock | Yes, if sent to LLM |
| 2 | Tool outputs (typed chart data) | **Yes** | Per-tool field allowlist; no SSN, address, phone, insurance; date-bounded windows; internal source IDs instead of MRN | Request/conversation lifetime; never persisted outside OpenEMR | Gateway ACL per call (`AclMain`), patient-scoped delegation | N/A inside OpenEMR; yes once sent to LLM |
| 3 | LLM prompt (system + context + tools) | **Yes** | Same allowlist as #2; strip names and DOB where not needed (use "the patient", age band); no cross-patient context | Provider: zero-retention / no-training mode (assumed under BAA); local: not stored | API key in secret store; agent service only | **Yes** (LLM provider is a business associate) |
| 4 | Model response / verified claims | **Yes** | Only claims with verified source IDs rendered | Same as conversation; no long-term copy unless it becomes a chart note (out of scope) | Same session user | Yes (produced by BA) |
| 5 | Conversation state store | **Yes** | Store source IDs + claims, not raw tool payloads, where feasible | Short TTL (e.g. ≤24 h demo; policy-defined in real use); explicit delete | Bound to user + site + patient + conversation id; encrypted at rest | Only if hosted by third party |
| 6 | Application logs (PSR-3, container stdout) | Must be **No** | Correlation id, tool name, status, latency, counts; never prompts, outputs, names, notes (AGENTS.md:52-53) | Operational (e.g. 30 days) | Host/ops only | If shipped to third-party log SaaS and PHI leaks → yes; design to avoid |
| 7 | Observability traces (Langfuse/LangSmith) | **Yes by default** (these tools capture inputs/outputs) | Disable input/output capture or redact; send ids, token counts, cost, latency, verification outcome | Short (e.g. 14–30 days demo) | Project-scoped SSO accounts | **Yes**, unless self-hosted in our boundary *or* verifiably PHI-free. Self-hosted Langfuse avoids a new BA |
| 8 | OpenEMR audit log (`log`) co-pilot events | Identifiers only (user, pid, resource types) | No clinical values, no prompt text | ≥6 years as GP for real use (164.316 docs retention analogue); demo: environment lifetime | Admin ACL; append-only target | No |
| 9 | `api_log` (if gateway uses REST/FHIR) | **Yes** with `api_log_option=2` | Set to 1 (minimal) for co-pilot traffic, or use audit events instead | As #8 | admin/users | No |
| 10 | Caches (tool-result / prompt cache) | **Yes** | Key by user+patient+resource+version; no cross-user sharing | Minutes; invalidate on write | Server-side only | Provider-side prompt caching falls under LLM BAA |
| 11 | Browser storage (localStorage/sessionStorage/IndexedDB) | Would be **Yes** | Do not persist conversation; in-memory only; clear on patient switch/logout | None | Same-origin | No |
| 12 | Eval fixtures / golden sets | Synthetic only (must be **No** real PHI) | Deterministic synthetic patients | Repo lifetime | Public repo → must be synthetic | No |
| 13 | Demo videos, screenshots, social posts | Synthetic data visible | Use demo cohort only; blur tokens/session ids | Permanent (public) | Public | No, if synthetic |
| 14 | Backups / DB dumps / log backups (`/tmp` default) | **Yes** | Encrypt; exclude from repo | Policy-defined; demo: none | Ops only | Yes, if third-party storage |
| 15 | Error/exception reports | Risk of **Yes** (exception messages, SQL) | Scrub; generic user messages (CLAUDE.md error rules) | Operational | Ops | Yes, if SaaS and not scrubbed |

*Status 2026-09-16 (what exists against this inventory):* #2 tools return projected, windowed, capped records with source ids; `patient_context` carries an age band and sex only (commit `83f33a6`). #3 the prompt receives the evidence pack, not raw payloads; the model key is a file secret in the agent container only. #5 the LangGraph SQLite checkpointer holds claims, limitations, and source ids; raw records live in a 120 s per-turn memory cache (`agent/app/state_store.py`, ADR-0005); no TTL purge of closed checkpoints yet. #6 agent logs are JSON with correlation ids and no payloads. #7 hosted Langfuse with a client-side mask that replaces every input and output with a digest, plus a LangSmith environment guard (`agent/app/telemetry.py`, ADR-0007); read-back on the deployment found no fixture PHI (commit `ab694d8`). #8 implemented as `copilot-session-start`, `copilot-tool-read`, `copilot-denied`, `copilot-session-end` (Section 5 status). #9 not used: the gateway is in-process and REST/FHIR stay disabled. #10 per-turn record cache only, keyed by turn id. #11 the browser keeps one opaque conversation id in `sessionStorage` to re-fetch the transcript behind a fresh ticket (`copilot.js`); no claim or record text is stored client-side. #12 synthetic cohort only.

**BAA implications of sending PHI to an LLM (assumed BAA):**

- A BAA (164.504(e)) must limit use and disclosure to our purposes, require
  safeguards, require breach reporting to us, flow down to subcontractors
  (164.502(e)(1)(ii)), and require return or destruction at termination.
- "No training" and the retention window should be contract terms, not
  dashboard settings.
- Even under a BAA, minimum necessary still applies. A BAA permits disclosure;
  it does not make whole-chart dumps appropriate.
- Every endpoint must be covered. That includes the model API, prompt caching,
  batch APIs, file stores, and the observability vendor. A BAA with the LLM
  provider does **not** cover LangSmith or hosted Langfuse.
- INFERRED: consumer or non-enterprise API tiers are typically outside BAA
  coverage. Real use would require confirming the exact product, region, and
  zero-data-retention configuration in writing.

## 5. Proposed agent-specific audit events

**Where to write:**

1. **OpenEMR audit log via `EventAuditLogger::newEvent()`** for all
   *access-to-PHI* and *security* events, emitted by the OpenEMR-side gateway.
   This keeps one authoritative accounting trail next to existing
   `view`/`login` events and makes it reviewable in the existing log viewer.
   It is required because the co-pilot likely uses in-process or local API
   calls, which `api_log` skips. Use `newEvent`, not `auditSQLEvent`, so events
   are written regardless of the `audit_events_query` setting.
2. **The observability backend** gets operational spans (latency, tokens,
   cost, retries) keyed by the same correlation id, with **no** PHI.
3. **Real use (GP):** also stream audit events to an external append-only or
   WORM store (ATNA sink or log shipping) to address the integrity gap in 1.3.

Keep `comments` short, structured JSON with no clinical values, and put the
patient id in the `patient_id` column.

| Event (`event` / `category`) | Emitted by | Fields (no PHI values) | success |
| --- | --- | --- | --- |
| `copilot-session-start` / `copilot` | Gateway | user, pid, conversation_id, correlation_id, module version | 1 |
| `copilot-tool-read` / `copilot` | Gateway, per tool call | user, pid, tool name, resource types, record count, date window, correlation_id, ACL decision | 1/0 |
| `copilot-access-denied` / `security-access-denied` | Gateway (reuse `AccessDeniedHelper::logDenial`) | user, requested pid, tool, reason code, correlation_id; confirms no LLM call made | 0 |
| `copilot-patient-context-mismatch` / `security` | Gateway/agent | user, session pid, requested pid, correlation_id | 0 |
| `copilot-model-disclosure` / `copilot` | Gateway, per retrieval batch whose records the agent declares will go to the model provider; written before the records are returned | user, pid, provider, model id, tool names, record count, conversation_id, turn_id, correlation_id; **no record, prompt, or response** | 1 |
| `copilot-llm-call` / `copilot` | Agent service → gateway audit endpoint | correlation_id, model id, provider, input/output token counts, resource types in context, duration, outcome; **no prompt/response text** | 1/0 |
| `copilot-verification-result` / `copilot` | Verifier | correlation_id, claims total / verified / withheld, rule ids failed | 1 if no rejections |
| `copilot-response-rendered` / `copilot` | Module | correlation_id, cited source ids count, partial flag | 1 |
| `copilot-dependency-failure` / `copilot` | Gateway/agent | correlation_id, dependency (tool/LLM/trace), error class | 0 |
| `copilot-session-end` / `copilot` | Module / TTL expiry | conversation_id, turns, reason (logout, patient switch, TTL) | 1 |
| `copilot-conversation-deleted` / `copilot` | Agent state store | conversation_id, actor, reason | 1 |
| `copilot-config-change` / `security-administration` | Admin UI | setting name, old/new enabled flag (like `auditSQLAuditTamper`) | 1 |

*Status 2026-09-16:* implemented through `EventAuditLogger::newEvent()` in
`oe-module-copilot/src/Gateway/Audit.php`, `public/api/conversation.php`,
`public/api/ticket.php`, and `public/gateway/tools.php`:
`copilot-session-start`; `copilot-tool-read` (written before data; the tool
answers `unavailable` if the insert fails); `copilot-denied` with reason
`forbidden`, `squad`, `breakglass`, `user_inactive`, or
`patient_context_changed` (this single event covers the proposed
`copilot-access-denied` and `copilot-patient-context-mismatch` rows);
`copilot-session-end` on panel close. Verified in the deployment's `log`
table on 2026-09-15 (commit `2dc51a0`). Not implemented in the OpenEMR log:
`copilot-llm-call`, `copilot-verification-result`,
`copilot-response-rendered`, `copilot-dependency-failure`,
`copilot-conversation-deleted`, `copilot-config-change`; model calls,
verifier outcomes, and dependency failures are recorded in the PHI-masked
Langfuse trace and the agent's `/metrics` instead. The idle close (30 min)
is not audited as a session-end event.

*Status 2026-09-19:* `copilot-model-disclosure` is implemented
(`Audit::modelDisclosure`, `public/gateway/tools.php`). The agent declares
`{provider, model}` on a retrieval batch when that turn's records will go to
the model (`_disclosure` in `agent/app/graph/nodes.py`: not when no model is
configured, the model fault is injected, a budget limit applies, or an
earlier model call of the turn failed), and the module writes the row before
it returns the records; if the row cannot be written every tool of the batch
answers `unavailable, reason=audit_unavailable`, the rule `copilot-tool-read`
already follows. It is the who, which patient, which provider, which
sections of the planned `copilot-llm-call`, moved to before the data leaves;
the token counts, duration, and outcome of the call stay on the Langfuse
trace and join on `correlation_id`. A UC-01 first turn retrieves in two
batches and writes two rows. The row records a declared intent: a model
call that then fails after retrieval still has its row, which is the
conservative side for an accounting of disclosures (the request may have
been sent). The agent side is covered by
`test_a_retrieval_whose_records_go_to_the_model_declares_the_disclosure`;
the PHP was linted by CI, and the rows were read back from the deployment's
`log` table the same day after two drawer turns on a synthetic patient: one
row for the follow-up, two for the UC-01 first turn, provider, model, tool
names and record counts matching the drawer and the Langfuse traces, a tool
that answered `empty` not listed, and no chart content
(`docs/audit/evidence/compliance/04-model-disclosure-rows-2026-09-19.md`).
The fail-closed branch has not been exercised in the deployment.

*Amended 2026-09-19 (brief on chart open, module 0.5.0):* these rows, and the
`copilot-tool-read` rows beside them, are now also written for a chart the
physician opened without asking anything, because the panel starts the UC-01
brief as the chart loads (`BriefPolicy`, ADR-0003 amendment). Nothing about
the rows changes — same user, same open chart, same sections, written before
the data leaves — but their trigger does: an opened chart, not a typed
question. Two consequences for this section. For the minimum-necessary
argument (§4), the read is still the one chart on screen and still the
sections UC-01 needs, but it is now made for every chart opened rather than
only those asked about; mode `visit_today` (`COPILOT_BRIEF_ON_OPEN`) narrows
it to patients with a visit on today's schedule, and mode `off` restores the
question-triggered behaviour exactly. For the access-log review (§6.1), a
`copilot-model-disclosure` row with no drawer interaction behind it is
expected and is not evidence of an unattended read; the physician opened that
chart, which OpenEMR audits on its own.

*Amended 2026-09-23 (GitLab #55): extended to the document-extraction
worker's source read.* `copilot-model-disclosure` had only ever been wired
into the chat path's `tools.php`; the lab/intake extraction worker's own
read of a document's source bytes (`public/gateway/source.php`, called
once per upload regardless of document type) never declared a disclosure,
even though #53/#54 had already wired that read's bytes to leave for
OpenRouter. `source.php` now accepts the same `{provider, model}`
declaration as a query param (the agent's `read_source` always sends
`{"provider": "openrouter", "model": <the pinned model id>}`, since this
worker's only use of a read is handing it to that provider) and writes the
row before returning bytes, fail-closed the same way as `tools.php`: if the
row cannot be written, the read fails instead of returning undisclosed
bytes. One row per document read, not one per model call -- the lab branch
makes one OpenRouter call per read; the intake branch, since the same
change, makes two (a primary and a secondary call over the same in-memory
bytes, GitLab #55's schema fix), and still writes exactly one row,
consistent with the existing rule that the row records a declared intent
over the bytes, not a count of the model calls that intent enables.
Separately, `Audit::modelDisclosure`'s own `$idShaped` sanitizer rejected
any model id containing `/` (written for the chat path's Anthropic ids,
which never do), so every row from this path recorded `model:
"unspecified"` until the regex was widened -- confirmed both the bug and
the fix directly against the `log` table on an integrated local stack,
`google/gemini-2.5-flash` now recorded correctly
(`docs/adr/0009-bounded-document-extraction-and-review.md` status note).

## 6. Procedures: demo project vs. real deployment

### 6.1 Access-log review

- **Demo:**
  - Before each checkpoint, run a scripted query counting `copilot-*` events by
    user and pid.
  - Confirm every `copilot-tool-read` has a matching session and correlation
    id, and every `access-denied` has no matching `llm-call`. These checks can
    also run as eval assertions.
  - Run the tamper report once.
- **Real (REQ 164.308(a)(1)(ii)(D)):**
  - Documented periodic review, e.g. weekly automated anomaly reports: volume
    spikes, off-hours access, patients with no care relationship, VIP flags.
  - Named reviewer, with reviews themselves documented and kept 6 years
    (164.316).
  - Sanctions policy (164.308(a)(1)(ii)(C)).

### 6.2 Breach response

- **Legal:**
  - Unsecured PHI breach → notify individuals without unreasonable delay and no
    later than **60 calendar days** after discovery (164.404).
  - Notify HHS: at the same time for ≥500 people, or through the annual log
    within 60 days of year end for <500 (164.408).
  - Notify media for >500 residents of a state or jurisdiction (164.406).
  - A business associate must notify the covered entity without unreasonable
    delay, ≤60 days (164.410), and contracts often shorten this.
  - A four-factor risk assessment (164.402(2)) decides whether "low probability
    of compromise" applies.
  - Law enforcement delay is allowed (164.412). The burden of proof sits with
    the entity (164.414).
  - State breach laws may be stricter.
- **Demo:** the data is synthetic, so there are no notification obligations.
  Still rehearse the playbook:
  - Detect (e.g. PHI-like strings in traces, a leaked key).
  - Contain: rotate LLM and observability keys, `destroy.sh`, purge traces.
  - Record a timeline in an incident note, then write a post-incident
    regression eval.
- **Real:**
  - Incident response plan (164.308(a)(6)).
  - BAA breach-reporting clauses with the LLM and observability vendors.
  - Ability to scope affected patients from `copilot-tool-read` and
    `llm-call` events. This is the main reason those events must carry pid and
    resource types.
  - Encryption per HHS guidance to qualify for safe harbor.

### 6.3 Deletion

- **Demo:** `destroy.sh` removes the Droplet and volumes.
  - Conversation TTL purge.
  - Delete the observability project and traces at the end of the challenge.
  - Revoke the LLM API keys.
  - Confirm that no browser storage persists.
- **Real:**
  - Medical records and audit logs are *not* deleted on patient request. HIPAA
    has no right to erasure; amendment runs through 164.526.
  - Retention follows state law and org policy.
  - Co-pilot ephemeral stores (conversation state, caches, traces) get
    documented short TTLs.
  - Vendor return or destruction at BAA termination (164.504(e)(2)(ii)(J)).
  - Media disposal and re-use controls (164.310(d)(2)(i)-(ii)).

### 6.4 Demo project vs. real deployment

| Area | Demo project (this sprint) | Real clinical deployment would require |
| --- | --- | --- |
| Data | Synthetic cohort only; no real PHI anywhere | Real PHI; risk analysis and risk management (REQ 164.308(a)(1)(ii)(A)-(B)) |
| BAA | Assumed with LLM provider (PRD); observability either self-hosted or PHI-free | Executed BAAs with LLM, observability, hosting (DigitalOcean), backup, email/SMS vendors; subcontractor flow-down |
| LLM data handling | Assumed no training; minimum-necessary tool allowlists | Contractual zero-retention/no-training, region, product-tier confirmation |
| Audit events | `copilot-*` events via `EventAuditLogger`; checked in evals | Same plus external append-only store, keyed-HMAC or hash-chained integrity, scheduled tamper checks |
| Audit settings | Document local values; consider `api_log_option=1` for co-pilot traffic | Formal config baseline; alert on `auditSQLAuditTamper` disable events |
| Log review | Scripted spot check per checkpoint | Documented periodic review, named owner, sanctions |
| Retention | Environment lifetime; traces ≤30 days; conversation TTL short | Written retention schedule (state law for records; ≥6 yr for HIPAA documentation) |
| Backups | Disabled (runbook) | Encrypted, tested backup/restore and DR (REQ 164.308(a)(7)) |
| Encryption at rest | App-level encryption on, keys co-located; no disk/InnoDB encryption | Volume/InnoDB encryption, KMS-managed keys separated from data host |
| Encryption in transit | Public TLS at Caddy; internal plaintext on single host | TLS for DB connections, internal service TLS if multi-host |
| Access control | Demo accounts; admin password over SSH | Unique user IDs, MFA, least-privilege DB accounts (separate audit writer without DELETE), workforce training |
| Breach response | Playbook rehearsal, key rotation | IR plan, 60-day notification machinery, BA reporting chain |
| Deletion | `destroy.sh`; trace purge | Retention-driven disposal, vendor return/destroy, media sanitization |
| Claims | "Demo; not for clinical use; not HIPAA certified" | Compliance program owned by a covered entity; still no "certification" |

## Findings

### COMP-HIGH-001: Audit log integrity is not protected against privileged or DB-level alteration

- **Status:** Open (baseline).
- **Severity:** High for real use; Medium for demo.
- **Observed evidence:**
  - Unkeyed SHA3-512 checksums sit in the same DB (`LogTablesSink.php:63-94`).
  - The app account has `ALL PRIVILEGES ON openemr.*` (evidence 02).
  - Checks run only on demand (`audit_log_tamper_report.php:241-265`).
  - The admin UI path drops the log tables after exporting to `/tmp`
    (`backup.php:1000-1027, 1103-1107`).
  - ATNA is off.
- **Affected assets/users:** `log`, `log_comment_encrypt`, `api_log`,
  `extended_log`; admins; anyone holding DB credentials.
- **Failure scenario:** A compromised admin or app credential views records via
  the co-pilot, then deletes or rewrites the `copilot-tool-read` rows and
  recomputes the checksums. Alternatively, "EventLog Backup" leaves the only
  copy in world-writable `/tmp` inside the container, where it is lost on
  redeploy.
- **Impact:** Cannot reliably establish who accessed which patient. That
  undermines 164.312(b) and (c)(1) and breach scoping under 164.402-404.
- **Likelihood/assumptions:** Requires privileged access. Demo exposure is low,
  but the gap is structural.
- **Recommendation:**
  - Use a dedicated audit-writer DB account with INSERT-only rights on log
    tables for co-pilot events (GP).
  - Ship audit events to an external append-only store, or enable the ATNA
    sink.
  - Use a keyed HMAC or hash chain with the key outside the DB.
  - Schedule tamper checks and alert on `security-administration` audit
    disable events.
- **Verification:**
  - Attempt `DELETE FROM log` as the audit-writer account; it must fail.
  - Tamper with a row in a test DB; the scheduled check must alert.
- **Architecture consequence:** Co-pilot audit events go through the
  gateway's `EventAuditLogger` **and** are mirrored (by correlation id) to a
  store outside OpenEMR's DB before real use. Do not treat OpenEMR's tamper
  report as sufficient.

### COMP-HIGH-002: Full API logging copies PHI response bodies into `api_log` indefinitely

- **Status:** Open.
- **Severity:** High (real); Low (demo, synthetic).
- **Observed evidence:**
  - `api_log_option=2` (evidence 01).
  - The response body is stored in both `request_body` and `response`
    (`ApiResponseLoggerListener.php:62-85`).
  - There is no retention job (Section 2).
- **Affected assets/users:** Every FHIR/REST consumer; `api_log` readers
  (`admin/users` ACL, `logview.php:29`).
- **Failure scenario:** The co-pilot gateway uses FHIR to fetch labs and notes
  for 20 patients a day. Each response duplicates the chart content into an
  unencrypted log table viewable by user-admins, then flows into log backups.
- **Impact:** PHI footprint multiplied, broader breach scope, and a conflict
  with minimum necessary (164.502(b), 164.514(d)).
- **Likelihood/assumptions:** High if the gateway uses external REST/FHIR
  calls. None if it uses local API or in-process services, which have the
  opposite problem (COMP-MED-003).
- **Recommendation:**
  - Set `api_log_option=1` in the deployed environment, or scope full logging
    to debugging windows.
  - Define `api_log` retention.
  - Rely on structured `copilot-tool-read` events for accountability.
- **Verification:**
  - Make one FHIR call and confirm the `api_log` row has empty
    `request_body`/`response` and the `log` row still exists.
- **Architecture consequence:** The gateway does not depend on `api_log` for
  auditing. It emits its own PHI-free events, and deployment config pins
  `api_log_option=1`.
- **Co-pilot response status (2026-09-16):** The gateway is in-process and
  produces no `api_log` rows; REST/FHIR stay disabled and unrouted at Caddy.
  `api_log_option=1` is **not** pinned anywhere in `infra/` (the deployed value
  was 2 on 2026-09-14 and was not re-dumped after the redeploy); the finding
  is moot on the current data path, not fixed.

### COMP-MED-003: Record-level PHI reads by the co-pilot would not be audited by default

- **Status:** Open.
- **Severity:** Medium.
- **Observed evidence:**
  - `audit_events_query` is empty (off) locally (evidence 01), and there are 0
    `patient-record-select` rows.
  - SELECT logging only covers mapped tables (`EventAuditLogger.php:440-505`).
  - Local API calls are excluded from `api_log`
    (`ApiResponseLoggerListener.php:52-53`).
  - `audit_events_lab-order` has no global definition (`:77`).
  - Only `view` on chart open (`PatientSessionUtil.php:80`) and HTTP page
    requests are logged.
- **Affected assets/users:** Co-pilot tool calls; compliance reviewers.
- **Failure scenario:** The agent fetches notes and labs for a patient through
  service classes during a conversation. The log shows only that the physician
  opened the chart and hit a module URL, not which resources were sent to a
  third-party LLM.
- **Impact:** Cannot perform access review or scope a vendor-side breach
  (164.312(b), 164.404).
- **Likelihood/assumptions:** High given the planned in-process gateway design.
- **Recommendation:** Emit `copilot-tool-read` and `copilot-llm-call` events
  (Section 5) through `newEvent`, independent of `audit_events_query`.
  Enabling `audit_events_query` globally is noisy and stores SQL binds (PHI)
  in comments, so it is not recommended.
- **Verification:** An eval asserts that each tool call produces exactly one
  `copilot-tool-read` row with the matching correlation id and pid, and no
  clinical values in `comments`.
- **Architecture consequence:** Audit emission is part of each tool's contract
  and is tested like authorization.
- **Co-pilot response status (2026-09-16):** Implemented: every tool call
  writes `copilot-tool-read` before returning data and fails to `unavailable`
  if it cannot (`public/gateway/tools.php`); denials write `copilot-denied`.
  Verified by hand in the deployment's `log` table (commit `2dc51a0`). The
  eval that would assert exactly one row per tool call with the matching
  correlation id is not automated (`evals/run.py` does not query `log`); the
  suite asserts correlation-id propagation and tool statuses only.
  `copilot-llm-call` is not written to the OpenEMR log (Section 5 status).
  Since 2026-09-19 the disclosure itself is: `copilot-model-disclosure`
  (provider, model, tools, record count) is written before a batch's records
  are returned for a model-backed turn (Section 5 status, 2026-09-19).

### COMP-HIGH-004: Observability traces will capture PHI and create an uncovered business associate unless designed otherwise

- **Status:** Open (planned component).
- **Severity:** High.
- **Observed evidence:**
  - The plan requires traces with tokens, cost, and tool order
    (`docs/PROJECT_PLAN.md:42, 207-210`; line numbers as of `fc95374`, the
    plan has since been revised).
  - Project rules forbid raw PHI in traces (`AGENTS.md:11, 52-53`;
    `ARCHITECTURE.md:57-60`).
  - INFERRED: Langfuse and LangSmith SDK integrations capture LLM
    inputs/outputs by default.
- **Affected assets/users:** Observability vendor, and everyone with project
  access to it.
- **Failure scenario:** Default instrumentation ships full prompts, including
  tool outputs with labs and notes, to a SaaS tracing vendor that has no BAA.
- **Impact:** Impermissible disclosure (164.502(e)), a presumed breach unless
  the risk assessment shows low probability (164.402), and a policy violation
  even with synthetic data.
- **Likelihood/assumptions:** High without explicit configuration.
- **Recommendation:**
  - Self-host Langfuse inside the deployment boundary, or disable
    input/output capture and send only ids, counts, latency, and verification
    outcome.
  - Add a redaction layer with a CI eval that fails if trace payloads contain
    fixture patient names or values.
- **Verification:**
  - Run the synthetic conversation, export traces, and grep for
    fixture-specific strings (names, lab values); expect 0 hits.
- **Architecture consequence:** The trace schema is allowlist-based, with a
  separate PHI-free telemetry contract. Vendor choice is constrained by BAA
  availability or self-hosting.
- **Co-pilot response status (2026-09-16):** Implemented as PHI-free hosted
  tracing, not self-hosting: Langfuse's LangGraph callback handler with a
  `mask` that replaces every input and output payload with a type/size digest,
  and a startup guard that refuses to run if any LangSmith tracing variable is
  set (`agent/app/telemetry.py`, ADR-0007). Read-back of one deployed trace on
  2026-09-15 found no fixture PHI (commit `ab694d8`;
  `docs/operations/langfuse-dashboard.md`). Not done: the CI eval that greps
  exported traces for fixture strings (none in `evals/`), and self-hosting.
  The hosted tracer therefore remains a third party for any real deployment.

### COMP-MED-005: No retention, backup, or deletion policy for logs, conversation state, or deployment data

- **Status:** Open.
- **Severity:** Medium (Low for demo).
- **Observed evidence:**
  - No purge mechanism; logs date back to 2014 (evidence 02).
  - `backups=false` (`main.tf:22`), plus the runbook statements
    (`digitalocean.md:167-168, 206`).
  - Conversation-state retention is a TODO (`ARCHITECTURE.md:104` as of
    `fc95374`; the document was rewritten on 2026-09-15 and the state design
    now lives in ADR-0005).
  - `backup_log_dir=/tmp`.
- **Affected assets/users:** All PHI stores in Section 4.
- **Failure scenario:** Conversation transcripts and traces pile up with no
  deletion path. Alternatively, a Droplet failure loses the audit trail with no
  recovery.
- **Impact:** Contingency-plan gap (164.308(a)(7)), unbounded PHI
  accumulation, and inability to meet 6-year documentation retention (164.316)
  in real use.
- **Likelihood/assumptions:** Certain over time in any non-disposable
  environment; irrelevant for the ephemeral demo Droplet, which is destroyed
  after each window. Assumes the conversation store is introduced by the
  co-pilot.
- **Recommendation:**
  - Write a retention schedule: conversation TTL, trace TTL, log retention,
    backup encryption and retention.
  - Implement TTL purge plus a `copilot-conversation-deleted` event.
  - Add tested encrypted backups before any non-disposable environment.
- **Verification:**
  - Create a conversation, advance the clock past its TTL, and confirm it is
    purged and the deletion is audited.
  - Complete a restore drill.
- **Architecture consequence:** The conversation store stores claims and source
  IDs rather than raw tool payloads, has a TTL, and is bound to user and
  patient.
- **Co-pilot response status (2026-09-16):** Partly implemented. Claims and
  source ids, not raw payloads, are checkpointed (ADR-0005); a conversation
  idle for 30 minutes is closed (`ConversationRepository::IDLE_MINUTES`,
  commit `983657c`) and panel close is audited as `copilot-session-end`. Not
  implemented: a purge of closed checkpoints from the agent's SQLite store,
  the `copilot-conversation-deleted` event, a trace TTL setting, and backups
  (still `backups = false`).

### COMP-MED-006: Encryption keys co-located with data; DB and internal transport unencrypted

- **Status:** Open.
- **Severity:** Medium.
- **Observed evidence:**
  - DB keys in the `keys` table; drive keys wrapped by the DB key
    (`CryptoGen.php:401-462`).
  - `innodb_encrypt_tables=OFF`, `require_secure_transport=OFF`, and no
    `mysql-ca` (evidence 02).
  - Caddy → `openemr:80` over HTTP (`Caddyfile:16`).
  - `oaprivate.key` on the sites volume.
- **Affected assets/users:** MariaDB data volume, `sites/` volume (keys and
  documents), Droplet block storage and any snapshot or dump taken from them;
  the future conversation store.
- **Failure scenario:** A leaked volume snapshot or DB dump exposes plaintext
  clinical tables and all application keys.
- **Impact:** Data would count as "unsecured PHI", so no safe harbor
  (164.402), and a weak implementation of addressable 164.312(a)(2)(iv).
- **Likelihood/assumptions:** Low on an ephemeral single host with an internal
  network. Rises with backups and multi-host.
- **Recommendation:** For real use, encrypt volumes and InnoDB with keys held
  in a KMS off-host, enable DB TLS (`mysql-ca`) and `REQUIRE SSL`, and use
  internal TLS once components leave the single host. Any agent service
  conversation store encrypts at rest.
- **Verification:** `SHOW STATUS LIKE 'Ssl_cipher'` from the app connection is
  non-empty; InnoDB encryption variables are ON; key material is absent from
  DB dumps.
- **Architecture consequence:** The agent service must not introduce a new
  plaintext PHI store. Its secrets (LLM and trace keys) go in a secret store,
  not `sites/`.
- **Co-pilot response status (2026-09-16):** Secrets are Compose file secrets
  mounted only into the agent (`runtime/compose.yaml`), not under `sites/`.
  The agent's SQLite checkpoint store (`agent_state` volume) holds verified
  claims and limitations for synthetic patients with no application-level
  encryption found in `agent/app/state_store.py`; it is a new store of
  derived PHI for any real deployment. DB TLS and internal TLS are unchanged.

### COMP-LOW-007: Existing logs themselves contain PHI and are readable with `admin/users`

- **Status:** Open.
- **Severity:** Low (demo) / Medium (real).
- **Observed evidence:**
  - SQL binds are stored in `comments` (`EventAuditLogger.php:446-452`).
  - `logHttpRequest` stores query strings (`:720-723`).
  - The log viewer ACL is `admin/users` (`logview.php:29`).
- **Affected assets/users:** The `log` and `log_comment_encrypt` tables; every
  patient whose data has been queried; user administrators as the population
  with access.
- **Failure scenario:** A user-administrator without clinical need reads
  demographics from SQL audit comments or search terms in query strings.
- **Impact:** Minimum-necessary and workforce access concern (164.308(a)(4),
  164.502(b)).
- **Likelihood/assumptions:** Standard OpenEMR behavior, so certain wherever
  `admin/users` is held by non-clinical staff. Low consequence on the demo,
  where all data is synthetic.
- **Recommendation:** Restrict log viewing to a compliance role. Co-pilot
  module URLs must not carry PHI in query strings (use POST bodies and
  correlation ids).
- **Verification:** Review module routes; confirm `http-request` rows for
  co-pilot endpoints contain only ids.
- **Architecture consequence:** The co-pilot API uses POST with JSON bodies. No
  question text or patient names in URLs.
- **Co-pilot response status (2026-09-16):** Implemented: `session.php`,
  `conversation.php`, `ticket.php`, and the tool gateway take POST JSON bodies;
  the agent's turn endpoint is `POST /v1/conversations/{id}/turns` with the
  question in the body. The `http-request` rows for these paths were not
  reviewed on the deployment.

### COMP-INFO-008: Local audit configuration deviates from code defaults

- **Status:** Observed.
- **Severity:** Informational.
- **Observed evidence:** `audit_events_query` is off (default 1),
  `gbl_print_log_option=0` (default 2), and there is no
  `audit_events_lab-order` global (evidence 01).
- **Affected assets/users:** The audit trail of every environment we
  provision; compliance reviewers relying on it.
- **Failure scenario:** A deployment is provisioned with query-event logging
  off, so co-pilot-adjacent reads leave no trail, and nobody notices because
  the setting is not in version control.
- **Impact:** Audit behavior depends on per-install settings that are not
  captured in version control. The deployed DigitalOcean values are unknown.
- **Likelihood/assumptions:** Moderate: the local stack already drifted from
  defaults without anyone changing it deliberately.
- **Recommendation:** Codify the required audit globals in deployment
  provisioning and verify them in the smoke test with a read-only query.
- **Verification:** `smoke.sh` asserts the expected globals.
- **Architecture consequence:** The deployment baseline includes an audit
  configuration check.
- **Co-pilot response status (2026-09-16):** Not done. `infra/digitalocean/smoke.sh`
  does not assert any globals, and no audit global is codified in
  provisioning. The deployed values in `evidence/security/cloud-runtime-2026-09-14.md`
  (`audit_events_query=1`, `api_log_option=2`) were read once from the
  upstream-image deployment and not re-dumped after the project-image redeploy.

## Known limitations of this audit

- Deployed (DigitalOcean) runtime globals, DB grants, and log contents were not
  inspected, because the environment was destroyed. Local dev values may
  differ.
- The co-pilot does not exist yet. Section 4-5 are design requirements, not
  observed behavior. *Status 2026-09-16: the co-pilot now exists; the status
  notes under Sections 4 and 5 and under each finding record what is
  implemented and what is still a requirement.*
- No BAA, provider data-retention terms, or observability vendor terms were
  reviewed. The LLM BAA is assumed per the PRD.
- The coverage of `database_encryption` over specific columns was not
  exhaustively enumerated. The claim that clinical tables are plaintext is
  inferred.
- The FHIR path's `pid` population in `api_log` for OAuth clients was not
  exercised (no load generation or API calls were made).
- DigitalOcean's provider-level at-rest encryption was not verified.
- State-law retention and breach rules and non-HIPAA regimes (42 CFR Part 2,
  FTC Health Breach Notification Rule, state AI or health-privacy laws) are out
  of scope.
- This document makes **no claim of HIPAA compliance or certification**.

## Top findings for executive summary

1. **Co-pilot PHI reads would be invisible in OpenEMR's audit trail as
   configured** (COMP-MED-003). SELECT auditing is off, local-API calls skip
   `api_log`, and only chart-open `view` and page-hit events exist. The gateway
   must emit its own `copilot-tool-read` and `copilot-llm-call` events.
2. **Audit logs are not tamper-resistant** (COMP-HIGH-001). Unkeyed checksums
   sit in the same DB, the app account has ALL privileges, the admin
   "EventLog Backup" drops the log tables to `/tmp`, and verification is
   on-demand only.
3. **Full API logging duplicates PHI response bodies** into `api_log` with no
   retention (COMP-HIGH-002). Pin `api_log_option=1`.
4. **Observability is the most likely unauthorized PHI disclosure path**
   (COMP-HIGH-004). A BAA with the LLM provider does not cover Langfuse or
   LangSmith SaaS. Self-host the tracer or send PHI-free traces only.
5. **No retention, backup, or deletion design** for logs, conversation state,
   or traces (COMP-MED-005). Encryption keys are co-located with data, and DB
   and internal traffic are plaintext (COMP-MED-006). Acceptable for a
   disposable synthetic demo, not for real PHI.

## Architecture consequences

- **Gateway-owned audit events:** Each read-only tool emits a structured
  `copilot-tool-read` event (user, pid, resource types, counts, correlation
  id) through `EventAuditLogger::newEvent()` before returning data. Denials
  emit `security-access-denied` and provably precede any LLM call. This is
  tested in evals.
- **PHI-free telemetry contract:** Traces, metrics, and app logs use an
  allowlisted schema (ids, counts, tokens, cost, latency, verification
  outcome). Prompt and response capture is disabled or redacted, and a CI eval
  greps exported traces for fixture PHI. Prefer a self-hosted Langfuse inside
  the deployment boundary.
- **Minimum-necessary tool schemas:** Field allowlists per tool, no direct
  identifiers in LLM context unless required, and a patient bound by session
  rather than by name.
- **Ephemeral, bound conversation state:** Stored per user+site+patient+
  conversation with a short TTL, encrypted at rest, holding claims and source
  IDs rather than raw payloads. No browser persistence. Deletion is audited.
- **Deployment config pins audit settings:** `enable_auditlog=1`,
  `api_log_option=1`, verified by the smoke test. The co-pilot uses POST
  endpoints so no PHI lands in `http-request` query-string logs.
- **Documented path to real use:** Executed BAAs (LLM, tracing, hosting), an
  external append-only audit sink with a least-privilege writer, KMS-backed
  at-rest encryption, DB TLS, tested encrypted backups, a retention schedule,
  a periodic access-review procedure, and a 164.404/410-aligned incident
  response plan. Until then, the system is labeled demo-only and not for
  clinical use.
