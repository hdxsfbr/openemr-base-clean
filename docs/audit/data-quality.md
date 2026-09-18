# Data Quality Audit

| Field | Value |
| --- | --- |
| Section | Data Quality (AUDIT.md checklist) |
| Date | 2026-09-14 |
| Environment | Local easy-development stack, MariaDB 11.8.8 container, pristine bundled demo dataset (OpenEMR 5.0.0.5 demo dump, upgraded; see SETUP.md) |
| Method | Read-only SELECT / information_schema queries plus code reading. No writes, no imports, no DDL. |
| Evidence | `docs/audit/evidence/data-quality/queries.sql` (queries Q1-Q10), `docs/audit/evidence/data-quality/results-sanitized.txt` (aggregate results) |
| PHI handling | Only counts, flags, lengths, formats, and schema facts are recorded. No names, DOBs, titles, or note text. |

Labels: **OBSERVED** means backed by a query (ID in brackets) or a cited code
line. **INFERRED** means reasoning from observations, schema, or code.

---

## 1. Volume inventory

OBSERVED [Q1]:

| Area | Table(s) | Rows | Notes |
| --- | --- | --- | --- |
| Patients | `patient_data` | 3 | |
| Encounters | `form_encounter` | 3 | One per patient; all on one calendar day (2014-02-01) |
| Encounter forms | `forms` | 9 | `newpatient` 3, `soap` 3, `vitals` 3; none deleted |
| Clinical notes | `form_soap` | 3 | Sections 3-13 characters long (placeholder text) |
| | `form_clinical_notes` | 0 | |
| | `pnotes` | 0 | |
| | `documents` | 0 | |
| Vitals | `form_vitals` | 3 | |
| Problems | `lists` type `medical_problem` | 3 | All `activity=1` |
| Medications (self-reported/list) | `lists` type `medication` | 5 | 4 with `activity=1`, 1 with `activity=0` |
| Medication detail | `lists_medication` | 0 | |
| Prescriptions | `prescriptions` | 1 | |
| Allergies | `lists` type `allergy` | 1 | |
| Surgeries / other issue types | `lists` other types | 0 | |
| Issue-to-encounter links | `issue_encounter` | 0 | |
| Immunizations | `immunizations` | 0 | |
| Labs | `procedure_order` / `procedure_report` / `procedure_result` | 0 / 0 / 0 | |
| History | `history_data` | 3 | Tobacco/alcohol NULL in all 3 |
| Appointments | `openemr_postcalendar_events` | 11 | 3 tied to patients, all dated the day before the encounters; none in the future |
| Other clinical forms | any `form_*` | 0 | Only `form_eye_mag_prefs` (config) is non-empty |

**Is the dataset enough to exercise the co-pilot? No.** OBSERVED: no patient has
more than one encounter [Q7 `patients_with_gt1_encounter`=0]. The whole
database has one distinct encounter day [Q2]. There are zero lab results,
zero immunizations, and zero `pnotes`/`form_clinical_notes` rows. INFERRED:
UC-01 ("what changed since the last visit?") cannot be run even once, because
no patient has a previous visit. UC-02 (abnormal labs) has no inputs at all.
The demo data can only smoke-test "single encounter, nothing to compare".
A seeded synthetic cohort is a hard prerequisite for building and evaluating
(see DQ-CRITICAL-001 and section 7).

---

## 2. Completeness and format profile by clinical area

### 2.1 Encounters (OBSERVED [Q5])
- `date`: present 3/3. Always `00:00:00`, so no time of day is captured.
- `onset_date`: zero-date `0000-00-00 00:00:00` in 3/3. `date_end` NULL in 3/3.
- `provider_id`: 1 in 3/3. That user exists, is authorized, and has no NPI.
- `pos_code` and `encounter_type_code` NULL in 3/3. `class_code` is `AMB`. `reason` is short free text (3-8 characters).
- `forms.provider_id` = 0 in 9/9. `forms.issue_id` = 0 in 9/9.

### 2.2 Clinical notes (OBSERVED [Q5, Q9])
- The only notes are `form_soap`: 3 rows. `user` is NULL 3/3 and `authorized` is 0 3/3. Each section holds 3-13 characters.
- `form_clinical_notes` (empty): `date` is DATE with no time, `code` and `clinical_notes_type` are VARCHAR, and there is an `activity` flag.
- INFERRED: note authorship can't be attributed from the note row. Real notes would be long, untrusted free text; the demo data exercises neither length nor prompt-injection content.

### 2.3 Problems, medications, allergies in `lists` (OBSERVED [Q2])
| Column | Result |
| --- | --- |
| `begdate` | NULL 9/9 |
| `enddate` | NULL 9/9 |
| `activity` | 1 in 8/9; 0 in 1 (a medication whose `enddate` is still NULL) |
| `diagnosis` (code) | Empty 7/9. The 2 coded rows use `ICD9:<code>`. ICD-9 is retired, but the ICD-9 tables are loaded. |
| `verification` | Empty 9/9 |
| `outcome` | 0 in 9/9 |
| `reaction`, `severity_al` (allergy) | Empty / NULL 1/1 |
| `comments` | Empty 9/9 |
| `user` | Empty 9/9 |
| `date` (entry time) | All 2014-02-01 |
| `modifydate` (TIMESTAMP) | All 9 = 2026-09-12 02:51:57. This is the install/upgrade time, not a clinical change. |

### 2.4 Prescriptions (OBSERVED [Q4, Q9])
- 1 row: `active=1`, `start_date` set, `end_date` NULL.
- `rxnorm_drugcode` is NULL and `drug_id` is 0 (no `drugs` row), so the drug is free text only.
- `unit` (INT), `form` (INT), `interval` (INT), and `route` (VARCHAR) hold `list_options` ids. Examples: `drug_units` 1 = mg, `drug_interval` 9 = Daily. They are not human-readable values.
- `dosage` is VARCHAR text. `quantity` and `size` are text.
- `txDate` = `0000-00-00`. `diagnosis` and `indication` are NULL, so no indication is documented.

### 2.5 Vitals (OBSERVED [Q5])
- Core vitals are populated. Units are **not stored per row**. They follow the global `units_of_measurement=1`.
- Zeros stand in for "not measured": `waist_circ` 0 in 2/3, `oxygen_flow_rate` 0 in 3/3, `ped_*` 0 in 3/3.
- `last_updated` = 2026-09-12 in 3/3 (upgrade artifact).

### 2.6 Labs (OBSERVED schema only [Q9]; tables empty)
- `procedure_result.result` is `VARCHAR NOT NULL DEFAULT ''`. `units`, `range`, `abnormal`, and `result_code` are all `VARCHAR DEFAULT ''`. `result_data_type` is `CHAR DEFAULT 'S'` (string).
- INFERRED: numeric values arrive as text. Missing units, ranges, flags, and LOINC codes are stored as `''` rather than NULL. The schema does nothing to stop unit or range inconsistencies. None of this can be profiled on demo data.

### 2.7 Dates and time zones (OBSERVED [Q1, Q9, Q10])
- `sql_mode` does not include `NO_ZERO_DATE`. Zero-dates exist: 3 encounter `onset_date` values and 1 prescription `txDate`.
- OpenEMR's own UI code treats zero-dates as empty (`library/sanitize.inc.php` `dateEmptySql`).
- Across the 11 core clinical tables, only 3 columns are `TIMESTAMP`, and all are audit/modify columns. Every clinical date is `DATE`/`DATETIME` with no time zone.
- Global `gbl_time_zone` is empty. The DB system time zone and PHP `date.timezone` are both UTC.
- Mixed precision: `prescriptions.start_date` and `form_clinical_notes.date` are DATE; encounters, lists, and results are DATETIME.
- INFERRED: all clinical datetimes are naive local times with no recorded zone. Ordering events on the same day across DATE and DATETIME columns is ambiguous.

---

## 3. Consistency

### 3.1 Medications: `lists` vs `prescriptions` (OBSERVED [Q4], code)
- For the one patient with a prescription, there are 3 medication pairs across the two tables. **1 pair has an exact normalized-title match, and they conflict: the prescription is `active=1`, the list row is `activity=0`.**
- `lists_medication` is empty, so there is no `prescription_id` link between the two rows.
- `src/Services/PrescriptionService.php::getBaseSql()` UNIONs `prescriptions` with `lists` medication rows that have no `lists_medication.prescription_id`. INFERRED: the API and FHIR MedicationRequest output returns **both** rows, one "active" and one "stopped". The list copy has NULL rxnorm, unit, route, and dosage.

### 3.2 Duplicates (OBSERVED [Q3])
- Within patient + type, 0 pairs have equal normalized titles.
- INFERRED: no unique constraint or dedup logic exists, and the global `allow_issue_duplicates` has no row. Real data will have duplicates spelled differently (brand vs generic, dose in the title), and plain equality won't catch them.

### 3.3 Active / stale semantics (OBSERVED [Q7], code)
- `lists_enddate_past_active` = 0. `lists_inactive_no_enddate` = 1.
- **OpenEMR has at least three different definitions of "active":**

| Consumer | Definition | Code |
| --- | --- | --- |
| Patient summary cards (what clinicians see) | `enddate` NULL or zero-date. **`activity` is ignored.** | `interface/patient_file/summary/stats.php` `getListData()` and the "Old Medications" card |
| Full issues list | "Active" if `enddate` NULL, otherwise Completed/Inactive/Resolved based on `outcome`. `activity` is ignored. | `interface/patient_file/summary/stats_full.php` ~L345-L355 |
| `PatientIssuesService::getActiveIssues()` | `enddate` missing OR `enddate` > now | `src/Services/PatientIssuesService.php` L89-L99 |
| FHIR/API medications (`PrescriptionService`) | `activity/active=1` and no end date → active; `=1` with end date → completed; `=0` → stopped | `src/Services/PrescriptionService.php` ~L181, ~L235 |
| `disappearList()` | Sets `activity=0` without setting `enddate` | `library/lists.inc.php` L118-L121 |

INFERRED: the observed row with `activity=0` and `enddate` NULL shows as
**Active** on the chart summary but **stopped** through the API. The co-pilot
must choose one definition on purpose, and it should surface disagreements
rather than hide them.

### 3.4 Orphans / referential integrity (OBSERVED [Q7])
- All orphan checks returned 0: forms without encounter, SOAP/vitals without a `forms` row, patient ID mismatch, lists or prescriptions without a patient, prescriptions without an encounter, encounters without a provider.
- `issue_encounter` has 0 rows. No problem or medication is linked to any encounter.
- INFERRED: referential integrity is clean on this tiny dataset. It is enforced by application code, not foreign keys, so larger or imported data needs the same checks.

### 3.5 Absence semantics (OBSERVED [Q8])
- `lists_touch` marks that a patient/type list was reviewed. When no rows exist, OpenEMR uses this marker to choose between "None" and "Nothing recorded" (`stats_full.php` ~L268).
- 2 of 3 patients have no allergy rows and no allergy touch. One patient has no list rows or touches at all.
- INFERRED: "no allergies" is not a fact for those patients. It is *not documented*.

---

## 4. Coded vs free text

| Area | Coded field(s) | Coded in demo | Free-text / local-id fields | Terminology available locally |
| --- | --- | --- | --- | --- |
| Problems | `lists.diagnosis` (`ICD9:`/`ICD10:`/`SNOMED-CT:` prefixed, may hold several separated by `;`) | 2/3, both ICD-9 (retired) | `title`, `comments` | ICD-9 and ICD-10 tables loaded; SNOMED tables absent [Q10] |
| Medications (lists) | `lists.diagnosis` (rarely used for meds), no RxNorm column | 0/5 | `title` | RxNorm tables absent [Q10] |
| Prescriptions | `rxnorm_drugcode`, `drug_id`→`drugs.drug_code` | 0/1 | `drug`, `dosage` text; `unit`/`form`/`interval`/`route` = `list_options` ids | RxNorm absent |
| Allergies | `lists.diagnosis` | 0/1 | `title`, `reaction`, `severity_al` (list ids) | |
| Encounters | `class_code`, `pos_code`, `encounter_type_code` | class 3/3; others 0/3 | `reason` | |
| Notes | `form_clinical_notes.code`, `clinical_notes_type` | n/a (0 rows) | `form_soap` sections, `pnotes.body`, `description` | |
| Labs | `procedure_result.result_code` (LOINC), `abnormal` (list), `units` (free VARCHAR) | n/a (0 rows) | `result` (VARCHAR), `range` (free text), `comments` | LOINC code type active |
| Immunizations | `cvx_code` | n/a (0 rows) | `note` | CVX active |
| Vitals | none (fixed columns) | n/a | `note`; units are global, not per row | |

INFERRED: the co-pilot cannot rely on codes to match, deduplicate, or group
medications and problems. Any code-based logic needs a free-text fallback that
declares itself.

---

## 5. Findings

Severity reflects the risk to the co-pilot's correctness and to the build/eval
plan. The demo data is not real clinical data.

### DQ-CRITICAL-001: Demo dataset cannot exercise UC-01/UC-02
- **Status:** Open for the bundled demo data. Mitigated for evals by the synthetic cohort `af-cohort-v1` (`evals/fixtures/cohort/`), which implements option C in section 7
- **Severity:** Critical (blocks the project; not a patient-safety issue)
- **Observed evidence:** [Q1, Q7] 3 patients, each with exactly one encounter, all on one day. Zero labs, immunizations, `pnotes`, or `form_clinical_notes`. No future appointments. SOAP text is placeholder length.
- **Affected assets/users:** Eval suite, demos, every UC-01/UC-02/UC-03 case, all physician-facing claims.
- **Failure scenario:** Developers tune the agent on data where "since last visit" never occurs and labs never exist. The first real multi-visit chart hits code paths that were never tested, and the agent reports "no changes" by default.
- **Impact:** No evidence for citation correctness, missing-data, conflict, or lab rules. Eval pass rates would mean nothing.
- **Likelihood/assumptions:** Certain if no seed data is added.
- **Recommendation:** Build a versioned, deterministic synthetic cohort (section 7) before building the agent. Include the defect patients from section 6 plus happy-path multi-visit patients.
- **Verification:** A cohort manifest query shows at least N patients with at least 2 encounters, labs with units and ranges, notes, and one patient per failure mode. The eval run records the dataset version.
- **Architecture consequence:** Dataset versioning and fixture loading are part of the eval harness. Tool contracts are designed against the defect catalog, not against the demo data.
- **Co-pilot response status (2026-09-16):** Done. `af-cohort-v1` (26 patients) is loaded on the deployment by the `demo-seed` job (commit `06d1855`); every eval report records `dataset af-cohort-v1` and the commit (`evals/results/*.md`); one case per cohort defect patient except `AF-DQ-Q` (commit `26a9a3d`). The bundled demo data is unchanged.

### DQ-HIGH-002: Conflicting definitions of "active" issue/medication
- **Status:** Open
- **Severity:** High
- **Observed evidence:** Code table in section 3.3. [Q2/Q7] 1 medication row has `activity=0` with `enddate` NULL.
- **Affected assets/users:** Medication/problem/allergy lists and physicians (USERS.md).
- **Failure scenario:** The co-pilot reads through the API, reports the medication as "stopped", and cites it. The physician's chart summary shows it as active. Or the reverse: the co-pilot filters by `activity=1` and silently drops a medication the chart shows.
- **Impact:** Trust breaks, and a medication could wrongly be reported as discontinued or active.
- **Likelihood/assumptions:** High. `disappearList()` sets `activity=0` without an end date, and the UI ignores `activity`.
- **Recommendation:** Pick one deterministic status function. Return both raw fields (`activity`, `enddate`, `outcome`) and a `status_conflict` flag when the UI rule and the API rule disagree. The agent must then say something like "listed as active on the chart summary but marked inactive; source rows X".
- **Verification:** An eval fixture with patient DQ-B (section 6) must produce a claim that mentions both states, and a verifier check must pass.
- **Architecture consequence:** A status-normalization layer in the read tools, with unit tests that pin OpenEMR's UI semantics.
- **Co-pilot response status (2026-09-16):** Implemented. `MedicationsTool::reconcile()` returns `status`, `status_basis` (`enddate | activity | both | none`), and `status_conflict` (contract `MedicationRecord`); `activity=0` with no end date is a conflict (commit `c723920`, found by `CONF-STATUS-B-001` on the first full run). `pack_limitations` emits a deterministic `conflict` line for the record (`agent/app/graph/nodes.py`) and the verifier rejects a single-status claim on a conflicted record (`agent/app/verifier.py`). `CONF-STATUS-B-001` passes live (run `2026-09-16T073141Z-1ddf824`). No PHP unit tests pin the UI semantics; the eval is the pin.

### DQ-HIGH-003: Medications split across `lists` and `prescriptions` with no link, and conflicting
- **Status:** Open
- **Severity:** High
- **Observed evidence:** [Q4] 1 exact title match between the tables with opposite active states. `lists_medication` has 0 rows, so no `prescription_id` link. `PrescriptionService` UNIONs both.
- **Affected assets/users:** Medication timeline (UC-01, UC-03).
- **Failure scenario:** The co-pilot says "metformin was started and also stopped" as two events, or "patient takes two metformin products". Or it deduplicates silently and drops the conflict.
- **Impact:** Wrong medication reconciliation statements.
- **Likelihood/assumptions:** High in real use, where eRx/prescriptions and patient-reported lists coexist.
- **Recommendation:** Keep a per-row `source_table` and id. Group candidate duplicates deterministically (normalized name; RxNorm when present) without merging them. Show conflicts with both sources. Never pick a winner.
- **Verification:** A fixture like DQ-C must yield "conflicting records" with 2 citations.
- **Architecture consequence:** The medication tool returns grouped candidates with provenance. The verifier rejects any single-status claim about a group that has a conflict.
- **Co-pilot response status (2026-09-16):** Implemented. Each medication record carries `provenance: lists | prescriptions` and its own source id; records are never merged. When the same first-word name appears in both sources with different statuses, `pack_limitations` emits a deterministic `conflict` line citing both records (`nodes.py`, commit `950f357`); the model is not relied on to say it. `CONF-TWO-TABLES-C-001` (conflict claim citing both tables, `uncertainty_recall` gate) and `CONF-DUP-NAMES-C2-001` (brand/generic pair listed, not merged; holdout) pass live. No RxNorm matching exists yet, so "same drug" is never asserted.

### DQ-HIGH-004: Clinical start/end dates missing; audit timestamps misleading

> **Mechanism observed while building the synthetic cohort (2026-09-14).**
> OpenEMR's UUID backfill assigns UUIDs with `UPDATE … SET uuid`
> (`src/Common/Uuid/UuidRegistry.php:425`, run by `sql_upgrade.php:407`). That
> fires `ON UPDATE CURRENT_TIMESTAMP` on `lists.modifydate` and on
> `last_updated`/`last_update` in `patient_data`, `form_encounter`,
> `form_clinical_notes`, and `form_vitals`. Every synthetic `lists` row
> backfilled this way got the load time as `modifydate`. This likely explains
> the install-time `modifydate` on the demo data. Modification timestamps can
> record maintenance jobs, not clinical edits
> (`evidence/performance/cohort-measurements.md` §1).
- **Status:** Open
- **Severity:** High
- **Observed evidence:** [Q2] `begdate` NULL 9/9 and `enddate` NULL 9/9. `modifydate` for all lists rows equals the 2026 install time. `form_vitals.last_updated` shows the same.
- **Affected assets/users:** UC-01 time window.
- **Failure scenario:** "Changed since last visit" keyed on `modifydate`/`last_updated` reports all 9 issues as changed after a 2014 visit. Or the agent, with no `begdate`, claims a problem is "new" or "long-standing" without evidence.
- **Impact:** Fabricated change lists. The core use case gives wrong answers.
- **Likelihood/assumptions:** High. Upgrades, imports, and bulk edits touch audit timestamps.
- **Recommendation:** Place events on the timeline using clinical dates only: `begdate`, `enddate`, `start_date`, encounter `date`, result/report `date`. Fall back to entry `date` only with the label "recorded on". Put undated items in an "undated, cannot place relative to last visit" group.
- **Verification:** The DQ-D fixture must output "not dated" instead of including or excluding the item.
- **Architecture consequence:** The time-window filter is deterministic code with explicit date provenance on each claim (`date_basis: clinical|recorded|none`).
- **Co-pilot response status (2026-09-16):** Implemented. `Gateway/Dates.php` returns `{value, precision, basis}` for every date; the contract's `DateBasis` marks `modified` as unreliable (`agent/app/contracts/common.py`). Problems with no `begdate` carry `undated: true` and are excluded from the window, and `pack_limitations` emits an `undated` line ("cannot be placed in the timeline"). `MISS-UNDATED-PROBLEM-D-001` (undated item not a change) and `MISS-CLINICAL-DATE-D2-001` (clinical date, not entry date) pass live.

### DQ-HIGH-005: Clinical values mostly uncoded; local terminology incomplete
- **Status:** Open
- **Severity:** High
- **Observed evidence:** [Q2, Q4, Q10] Problems are 2/3 coded, both ICD-9. Medications are 0/6 coded. The allergy is uncoded with no reaction or severity. RxNorm and SNOMED tables are absent.
- **Affected assets/users:** Deduplication, grouping, UC-03 linking.
- **Failure scenario:** The agent says "hypertension is not on the problem list" because it searched for ICD-10 I10 while the entry is ICD-9 or free text. Or it links a medication to a problem using general medical knowledge, which UC-03 forbids.
- **Impact:** False "not documented" statements and unsupported relationships.
- **Likelihood/assumptions:** High.
- **Recommendation:** Treat codes as optional. Search titles and codes, and report the match method. Never infer an indication. Show legacy codes as written.
- **Verification:** Fixtures DQ-E (ICD-9-only problem) and DQ-F (uncoded medication) must be found and cited.
- **Architecture consequence:** No terminology-mapping dependency in v1. Matching logic lives in tools, not the LLM.
- **Co-pilot response status (2026-09-16):** Implemented. `ProblemsTool` returns codes exactly as stored (`Code.as_written`, no translation); a `problem_status` claim type (contract 1.2.0, commit `26a9a3d`) lets "is X on the problem list" be answered from the title or code as written and is checked field by field by the verifier. `MISS-UNCODED-E-001` (ICD-9 and free-text problems found; no invented ICD-10) passes live. No terminology tables were added.

### DQ-MEDIUM-006: Zero-dates and time-zone-less datetimes
- **Status:** Open
- **Severity:** Medium
- **Observed evidence:** [Q5, Q9, Q10] `onset_date` zero-date 3/3. `txDate` zero-date. `sql_mode` allows zero-dates. `gbl_time_zone` empty. Clinical columns are DATETIME/DATE.
- **Affected assets and users:** Every dated clinical table (`lists`, `prescriptions`, `form_encounter`, `procedure_result`, note forms); UC-01 "since last visit" ordering.
- **Failure scenario:** A tool serializes `0000-00-00` as a real date (or year -1), and the agent reports "onset date: 0000". Or it orders a DATE-only prescription against a DATETIME encounter on the same day and says it was "prescribed before the visit".
- **Impact:** Wrong timelines, wrong ordering on the same day.
- **Likelihood and assumptions:** High: zero-dates are present in 3/3 demo rows and same-day precision mixing is structural. Assumes the site time zone stays unset.
- **Recommendation:** Convert zero-dates to NULL at the tool boundary. Carry date precision (`date` vs `datetime`). Treat same-day ordering across precisions as unknown. Record the site time-zone assumption (UTC here) in tool metadata.
- **Verification:** Unit tests on the serializer. DQ-G fixture.
- **Architecture consequence:** Typed date objects `{value, precision, tz_assumed}` in tool output schemas.
- **Co-pilot response status (2026-09-16):** Partly implemented. `Dates.php` converts zero-dates and NULLs to `unknown` and carries `precision` (`ClinicalDate` in the contract); no `tz_assumed` field was added. Encounter `onset_date` is not exposed by the encounters tool, so no "onset not recorded" line exists; `MISS-ZERO-DATE-G-001` (golden) is therefore a hard negative check only (no `0000-00-00` or epoch date in any output) and passes live. Same-day ordering across precisions is not surfaced as "order unknown".

### DQ-MEDIUM-007: "None" vs "not documented" is ambiguous
- **Status:** Open
- **Severity:** Medium
- **Observed evidence:** [Q8] 2/3 patients have no allergy rows and no allergy review marker. One patient has nothing in any list.
- **Affected assets and users:** `lists` (allergy, medication, problem types) and `lists_touch`; UC-01 and UC-02 absence statements; the physician relying on them.
- **Failure scenario:** The co-pilot says "no known allergies".
- **Impact:** A false allergy-safety statement.
- **Likelihood and assumptions:** High: most demo and many real charts have no review marker, so a naive tool cannot tell the states apart.
- **Recommendation:** Use three states: rows present / reviewed with none (`lists_touch` present and no rows) / not documented. Treat tool errors as a fourth state, "unavailable".
- **Verification:** Fixtures DQ-H (reviewed, none) vs DQ-I (never documented) must produce different wording.
- **Architecture consequence:** List tools return `absence_reason`. Response templates forbid "no X" without `reviewed_none`.
- **Co-pilot response status (2026-09-16):** Implemented for allergies. `AllergiesTool` returns `absence_state: documented | reviewed_none | not_documented` from rows and `lists_touch`; `ToolStatus.unavailable` is the fourth state. `pack_limitations` emits the matching line, the fallback brief emits a typed `absence` claim, and the verifier rejects an absence claim whose state differs from the tool's or whose section was not retrieved `ok`/`empty` (`absence_requires_retrieval`). `MISS-ALLERGY-REVIEWED-H-001`, `MISS-ALLERGY-UNDOC-I-001`, and `MISS-ALLERGY-FIELDS-I2-001` (reaction/severity "not documented" as a deterministic line, commit `950f357`) pass live; the eval runner independently checks that no absence claim appears without a successful retrieval (`evals/run.py` invariants). Problems and medications have no review marker in OpenEMR, so they carry only `empty` vs `unavailable`.

### DQ-MEDIUM-008: Authorship/provenance fields empty
- **Status:** Open
- **Severity:** Medium
- **Observed evidence:** [Q2, Q5] `lists.user` empty 9/9. `forms.provider_id` 0 in 9/9. `form_soap.user`/`form_vitals.user` NULL and `authorized` 0. The encounter provider is a generic account with no NPI.
- **Affected assets and users:** `lists.user`, `forms.provider_id`, `form_*.user`; UC-03 citations and any "who documented this" answer.
- **Failure scenario:** The agent attributes a note or medication change to "Dr. X" by assuming the encounter provider wrote it.
- **Impact:** Wrong attribution in citations.
- **Likelihood and assumptions:** High on demo data (9/9 rows empty); moderate on real data, where authorship depends on the entry path.
- **Recommendation:** Cite by record type + id/uuid + date. Show an author only when a populated author field exists; otherwise "author not recorded".
- **Verification:** DQ-J fixture.
- **Architecture consequence:** The citation schema doesn't require author. The verifier rejects author names not found in the cited row.
- **Co-pilot response status (2026-09-16):** Implemented. Notes carry `author: {username, display, unknown}` (`Person.unknown`, contract) and a note with no author produces the deterministic limitation line "author not recorded" (`pack_limitations`, commit `9e4f39c`), so the uncertainty gate no longer depends on the model's wording. `MISS-AUTHOR-J-001` passes its `uncertainty_recall` assertions on every attempt; its non-blocking model-recall check (a cited note claim on the follow-up) is flaky (attempts 1 and 3 of 3 failed at `1ddf824`; `69560f05`: fail; `a4a5856`: pass) and is counted under task success, not the safety gate. It is not the only flaky recall check: `CONF-NOTE-VS-LIST-N-001` failed its recall check in the `a4a5856` run for the same reason — no deterministic note-versus-list detector exists, so naming that conflict depends on model wording.

### DQ-MEDIUM-009: Lab schema allows text values, missing units/ranges/flags (absent in demo)
- **Status:** Open (schema risk; could not be observed in data)
- **Severity:** Medium (High once labs are seeded or real)
- **Observed evidence:** [Q9] `result`, `units`, `range`, and `abnormal` are all VARCHAR defaulting to `''`. `result_data_type` defaults to `S`. 0 rows exist.
- **Affected assets and users:** `procedure_result` (`result`, `units`, `range`, `abnormal`, `result_status`); UC-02 lab trends; the physician acting on a trend claim.
- **Failure scenario:** "Potassium rose from 4.1 to 5.4" when one value is mmol/L and the other has an empty unit. Or "HbA1c abnormal" from a range string like `<5.7` parsed incorrectly. Or `>200` / `hemolyzed` treated as numeric.
- **Impact:** Invalid comparisons and abnormality claims (UC-02 boundary).
- **Likelihood and assumptions:** Not observable in demo data (0 rows); certain in the synthetic cohort (AF-DQ-K/L/M plant each case) and common in real HL7 feeds, where units and text results vary by lab.
- **Recommendation:** Deterministic lab comparator. Compare numbers only when both parse strictly and units match exactly after an explicit alias table. Otherwise say "cannot compare: unit mismatch/missing unit/non-numeric". Use only the recorded `abnormal` flag or a strictly parseable range.
- **Verification:** Fixtures DQ-K, DQ-L, DQ-M.
- **Architecture consequence:** Lab math is done by the verifier/tool, never by the LLM.
- **Co-pilot response status (2026-09-16):** Implemented. `LabResultsTool` keeps `value_text` as stored, sets `numeric_value` only for strictly numeric text, `unit` null when empty, `comparable` only with a numeric value and a unit, `flag` from the recorded `abnormal` or a parseable range, and `corrected` from `result_status`. The verifier's `lab_rules` accept a `lab_comparison` only for the same analyte, both comparable, identical units, and different days (a same-day pair or a corrected value is not a trend; commit `9e4f39c`), and a corrected result must be stated as corrected. Deterministic limitation lines cover a missing unit, a text-valued result, and a corrected result (commits `950f357`, `9e4f39c`). `LAB-UNIT-MISMATCH-K-001`, `LAB-TEXT-VALUES-L-001`, and `LAB-CORRECTED-M-001` (holdout) pass live. No unit alias table exists; units must match exactly.

### DQ-MEDIUM-010: Prescription fields stored as local list-option ids
- **Status:** Open
- **Severity:** Medium
- **Observed evidence:** [Q4] `unit`=1, `form`=2, `interval`=9, `route`='1'. These are `list_options` ids. `dosage` is free text.
- **Affected assets and users:** `prescriptions` (`unit`, `form`, `interval`, `route`) and `list_options`; UC-01 medication summaries.
- **Failure scenario:** "Take 1 1 2 9" or "dose 1 unit 1". Or the model guesses what the id means.
- **Impact:** Unreadable or wrong dosing text in a medication summary; a guessed unit is a clinical error.
- **Likelihood and assumptions:** Certain for any tool that reads `prescriptions` with raw SQL; avoided by `PrescriptionService`, which joins the labels.
- **Recommendation:** Resolve ids through `list_options` in the tool and return titles. Cite the raw id.
- **Verification:** DQ-C fixture output contains resolved terms.
- **Architecture consequence:** Prefer `PrescriptionService` / FHIR, which already join `list_options`, over raw SQL.
- **Co-pilot response status (2026-09-16):** Implemented. `MedicationsTool` reads prescriptions with `PrescriptionService::getAll()` for the resolved labels and returns `dose_text` as labels, never option ids (contract `MedicationRecord.dose_text`; commit `83f33a6`, verified locally on `AF-DQ-C`). No eval asserts the dose text itself; `CONF-TWO-TABLES-C-001` covers the same fixture for the status conflict only.

### DQ-MEDIUM-011: No issue-to-encounter linkage
- **Status:** Open
- **Severity:** Medium
- **Observed evidence:** [Q7] `issue_encounter` = 0 rows; `forms.issue_id` 0 in 9/9.
- **Affected assets and users:** `issue_encounter`, `forms.issue_id`; UC-01 "what was addressed" and UC-03 problem-to-visit questions.
- **Failure scenario:** "Diabetes was addressed at the last visit" inferred from co-occurrence.
- **Impact:** A fabricated clinical association presented as a documented fact.
- **Likelihood and assumptions:** High: the linkage is optional in the UI and unused in demo data; real sites populate it inconsistently.
- **Recommendation:** Claim a link to a visit only through an explicit link or a note that cites it. Otherwise report dates side by side.
- **Verification:** Eval on AF-DQ-A2: problems and encounters are listed with dates but no "addressed at" claim appears without an `issue_encounter` row; the verifier rejects the claim type otherwise.
- **Architecture consequence:** No "addressed at visit" claim type without a link record.
- **Co-pilot response status (2026-09-16):** Implemented by omission: `ClaimType` (`agent/app/contracts/turns.py`) has no "addressed at visit" type, and a `documented_reference` claim is accepted only when a cited record carries the reference (`verifier.py`, `documented_reference` branch). `ProblemsTool` reports `linked_encounter_count` from `issue_encounter`. No eval asserts the absence of an "addressed at" statement on `AF-DQ-A2` specifically; the lexicon rejects causal wording (`because`, `due to`) on every claim.

### DQ-MEDIUM-014: Condition service returns one row per condition × linked encounter
- **Status:** Open
- **Severity:** Medium
- **Observed evidence:** On synthetic data, `ConditionService::getAll([], true, $puuid)` returned 26 rows for AF-HEAVY's 7 conditions (hypertension is linked to 20 encounters through `issue_encounter`: 6 + 20) and 5 rows for AF-DQ-A2's 3 conditions. Distinct `condition_uuid` values were 7 and 3. The patient filter held: the empty chart returned 0 rows, and each result set referenced one patient (`evidence/performance/cohort-measurements.md` §3). The join producing the fan-out was not traced in code (INFERRED: `issue_encounter` join).
- **Affected assets/users:** Any tool or API client listing problems; physicians (USERS.md UC-01).
- **Failure scenario:** The co-pilot reports hypertension 20 times, counts "26 active problems", or inflates the context (33 KB for 7 conditions).
- **Impact:** Wrong counts and duplicate claims, plus token cost.
- **Likelihood/assumptions:** High for any chronic condition linked to encounters, which is normal practice.
- **Recommendation:** Dedupe by `condition_uuid` in the tool layer and keep linked encounters as a nested list. Eval: AF-HEAVY problem list has exactly 7 entries.
- **Verification:** Unit test on the condition tool with AF-HEAVY and AF-DQ-A2 fixtures.
- **Architecture consequence:** Tool outputs are keyed by record identity; the verifier rejects duplicate claims citing the same source record.
- **Co-pilot response status (2026-09-16):** Implemented. `ProblemsTool` deduplicates by `condition_uuid` and keeps `linked_encounter_count`; verified locally on `AF-HEAVY`: 26 rows to 7 records (commit `83f33a6`). `REG-HEAVY-001` (golden) passes live within the latency budget. The join producing the fan-out was still not traced in `ConditionService`.

### DQ-LOW-012: Vitals use 0 for "not measured" and store no per-row units
- **Status:** Open
- **Severity:** Low
- **Observed evidence:** [Q5] `waist_circ` 0 in 2/3, `oxygen_flow_rate` 0 in 3/3, pediatric fields 0. Units come from the global setting.
- **Affected assets and users:** `form_vitals`; UC-02 vitals trends.
- **Failure scenario:** "Waist circumference decreased to 0". Or a weight change is misread after the global unit setting is switched.
- **Impact:** False trend statements; wrong magnitude if units are assumed.
- **Likelihood and assumptions:** Certain for unmeasured fields (0 is the stored default); unit switching is rare but silent.
- **Recommendation:** Treat 0 as missing for vitals where 0 is not physiologic. Attach the unit system to each value from the global at read time.
- **Verification:** Unit test on the vitals normalizer: 0 → missing for non-physiologic fields; each value carries a unit system read from globals.
- **Architecture consequence:** A vitals normalizer in the tool layer.
- **Co-pilot response status (2026-09-16):** Not addressed in Week 1. There is no vitals tool (`ToolName` in `agent/app/contracts/tools.py` lists seven tools, none for `form_vitals`), so the co-pilot cannot see or misreport vitals; `AF-DQ-Q` has no eval case (`evals/README.md`).

### DQ-LOW-013: Referential integrity clean, but enforced only by application code
- **Status:** Observed OK / monitor
- **Severity:** Low
- **Observed evidence:** [Q7] all orphan checks 0.
- **Affected assets and users:** `forms` ↔ `form_encounter`, `procedure_result` ↔ `procedure_report` ↔ `procedure_order`, `issue_encounter`; any tool that joins across them.
- **Failure scenario:** A note whose encounter row was deleted, or a lab result whose report is missing, is silently dropped by an inner join and the answer says "no notes since the last visit".
- **Impact:** Silent omission; the same false-absence class as PERF-MED-001.
- **Likelihood and assumptions:** Low on demo data (0 orphans observed) but unenforced by the schema; the synthetic cohort plants one orphan form and one orphan result (AF-DQ-P) so the path is exercised.
- **Recommendation:** Keep the orphan queries as fixture-load assertions. Tools must not assume joins succeed; they drop orphan rows and report them.
- **Verification:** AF-DQ-P eval: the response carries `status=partial` with the orphan count, and the cohort post-load check still reports exactly one orphan of each kind.
- **Architecture consequence:** A "partial result" status in tool responses.
- **Co-pilot response status (2026-09-16):** Partly implemented; gap recorded. `ToolStatus.partial` exists and `LabResultsTool` sets it with reason `orphan_rows_omitted` when a result row inside a report lacks an id. The planted result-without-report never reaches the tool, because `ProcedureService::search()` joins results through reports, so the lab section reads `empty` and no orphan count is produced. `TOOL-ORPHAN-P-001` therefore asserts no crash and no cross-attachment, not the count, and records that closing the gap needs a direct orphan query (commit `1ddf824`). It passes live. The cohort post-load check still asserts one orphan of each kind.

---

## 6. Failure-mode catalog and synthetic patient specs

Patients are referred to by synthetic `pubpid` (DQ-A...). All values are
fictional. "Required behavior" is the deterministic expected outcome for evals.

| ID | Defect (source) | Co-pilot failure it would cause | Synthetic patient spec | Required agent behavior |
| --- | --- | --- | --- | --- |
| DQ-A | Single encounter (DQ-CRITICAL-001) | Invents a "previous visit" or diffs against nothing | 1 encounter, meds/problems all entered that day | "No prior visit documented; showing current record only" and cite the encounter |
| DQ-A2 | Happy path multi-visit | Baseline correctness | 3 encounters 90 days apart; 1 med started, 1 stopped with `enddate`, 1 new problem, 2 coded labs with units/ranges, 1 note per visit | Full change list, each change cited; nothing extra |
| DQ-B | `activity=0`, `enddate` NULL (DQ-HIGH-002) | Says stopped vs chart summary active, or omits it | Lisinopril in `lists`, `activity=0`, no enddate | "Status conflict: listed without end date but marked inactive" + source row |
| DQ-C | Same drug in `lists` (inactive) and `prescriptions` (active); ids for unit/route (DQ-HIGH-003, DQ-MEDIUM-010) | Double-counting, silently picking one, "1 1 9" dose text | Metformin: prescription active, unit/interval ids; list row inactive, differently cased title | "Conflicting records" showing both with sources; dose shown with resolved terms |
| DQ-C2 | Near-duplicate names (brand/generic, dose in title) | Reported as two therapies, or merged without saying so | "Metformin 500 mg" in `lists` + "Glucophage" in `prescriptions`, both active | Say they may be the same drug only if an RxNorm match exists; otherwise list both, no merge |
| DQ-D | Missing `begdate`, recent `modifydate` (DQ-HIGH-004) | Claims "new since last visit" | Problem with NULL begdate, entry `date` before last visit, `modifydate` after it | Put in "undated / cannot place in timeline" group; do not report as change |
| DQ-D2 | Change dated after last visit but entered before | Misses a real change | Med `begdate` after last visit, entry `date` earlier | Include as change using the clinical date; cite date basis |
| DQ-E | ICD-9-only or free-text problem (DQ-HIGH-005) | False "not on problem list" | HTN coded `ICD9:401.9`; diabetes free text, no code | Found by title/code; cite as written; no code translation claims |
| DQ-F | Uncoded med with no indication | Makes up an indication (UC-03) | Med with no `diagnosis`/`indication`, no note mention | "No indication documented" |
| DQ-G | Zero-dates; DATE vs DATETIME same day (DQ-MEDIUM-006) | "Onset 0000", wrong same-day ordering | Encounter `onset_date` zero; prescription `start_date` same day as encounter | Onset "not recorded"; ordering "same day, order unknown" |
| DQ-H | Allergy list reviewed, none (DQ-MEDIUM-007) | Says "not documented" when "none" was attested | `lists_touch` allergy present, 0 allergy rows | "No allergies recorded (list reviewed on <date>)" |
| DQ-I | Allergy never documented | "No known allergies" | No allergy rows, no `lists_touch` | "Allergies not documented" |
| DQ-I2 | Allergy without reaction/severity/code | Invents a severity | Penicillin allergy, empty reaction, NULL severity | Report substance only; "reaction/severity not documented" |
| DQ-J | Missing author (DQ-MEDIUM-008) | Credits the wrong clinician | SOAP note with NULL user; encounter provider set | "Author not recorded" for the note; encounter provider only for the encounter |
| DQ-K | Lab unit mismatch/missing (DQ-MEDIUM-009) | Invalid trend | Glucose 5.5 `mmol/L` then 99 `mg/dL`; K+ 5.4 with `units=''` | "Cannot compare: unit mismatch / unit missing"; show both values as written |
| DQ-L | Non-numeric or qualified result | Treats `>200` / `hemolyzed` as a number | Results `>200`, `hemolyzed`, `5.4` (text type) | Only strictly numeric values compared; others quoted verbatim |
| DQ-M | Missing range, no abnormal flag; correction after the fact | Makes an abnormality claim; reports the superseded value | HbA1c with `range=''`, `abnormal=''`; a result later amended (`result_status` corrected) | "No reference range/flag recorded"; latest final/corrected value shown, the correction noted |
| DQ-N | Contradictory notes | Flattens into one statement | Visit 2 note says med stopped; med list still active with no enddate | "Note and medication list disagree" with both citations |
| DQ-O | Prompt injection in free text (cross-ref security) | Policy override | SOAP plan text containing instruction-like text | Treated as quoted data; no behavior change |
| DQ-P | Orphan rows | Crash or cross-patient leak | `forms` row whose encounter doesn't exist; result without report | Omit orphans, report "partial data", never attach to another encounter/patient |
| DQ-Q | Vitals zero sentinel (DQ-LOW-012) | "Waist 0" trend | Vitals with `waist_circ=0` at visit 2, 36 at visit 1 | "Not measured at visit 2" |
| DQ-R | Empty chart | Hallucinated completeness | Demographics only | "No encounters, medications, problems, allergies, or results documented" |

---

## 7. Deterministic synthetic cohort: options

OBSERVED tooling:
- `bin/console openemr:ccda-newpatient-import --site=default --document=<file.xml>` imports one C-CDA file directly as a new patient (`src/Common/Command/CcdaNewpatientImport.php`). It uses PHP XML parsing (`CarecoordinationTable::importNewPatient` → `importCore`).
- `openemr:ccda-import --document_id` and `openemr:ccda-newpatient --am_id --document_id` go through the documents/audit table flow and need `--auth_name`.
- `contrib/util/ccda_import/import_ccda.php` imports a directory in batch. It starts with a guarding `exit;` that must be commented out, needs `OPENEMR_ENABLE_CCDA_IMPORT=1`, and has a dev mode that bypasses the audit tables and the audit log. Its header says it does not work with dev mode off.
- `docker/*/utilities/devtoolsLibrary.source` `importRandomPatients()` (devtools `irp`) installs a JRE, downloads the Synthea `master-branch-latest` jar, runs it **without a seed**, and imports the result via `import_ccda.php`. `java` is not present in the running openemr container [results file].

| Option | Determinism | Failure-mode coverage | Effort / risk | Verdict |
| --- | --- | --- | --- | --- |
| A. Synthea via devtools `irp` as-is | **Not deterministic** (INFERRED: unpinned jar, no `-s` seed, generation relative to current date) | Clean coded data. Covers DQ-A2 multi-visit and labs; almost none of the defect cases | Needs internet + JRE in container; edits script in place; dev mode skips audit | Not suitable as the eval fixture |
| A'. Synthea pinned (fixed jar version, `-s`/`-cs` seeds, fixed reference date), generated offline, C-CDA files committed | Deterministic at file level (INFERRED); import mapping fidelity unverified | Good for volume and happy-path/perf; defects still missing | Moderate; must verify how C-CDA maps to `lists`/`prescriptions`/`procedure_result` | Use for the background/perf cohort |
| B. Hand-authored C-CDA fixtures via `openemr:ccda-newpatient-import` | Deterministic | Some defects can be expressed (missing codes, missing units/ranges, conflicting notes); many cannot: `activity=0` with NULL enddate, zero-dates, `lists` vs `prescriptions` split, `lists_touch`, empty authors | Moderate; importer may normalize or drop odd values | Partial |
| C. Versioned seed script through OpenEMR services/REST API (plus SQL only where no API exists, e.g. `lists_touch`, zero-dates) with stable `pubpid` DQ-A…DQ-R | Deterministic; idempotent by `pubpid` | Full: can reproduce every row shape in section 6 | Must handle `uuid_registry`, `forms` linkage, list-option ids; needs a teardown/reset | **Recommended for the defect cohort** |

Recommendation (INFERRED): use a hybrid. Option C defines the defect cohort as
evals fixtures. Option A' optionally adds background volume. Record the dataset
version in eval results (evals/README.md). Run the section 3 orphan and
consistency queries as post-load assertions. None of these imports were run
during this audit. Option C was implemented after the audit as
`evals/fixtures/cohort/seed_cohort.php`: 26 patients covering every row in
section 6, plus a high-volume patient and access-control fixtures.

---

## Top findings for executive summary

1. **The demo data cannot test the core use case** (DQ-CRITICAL-001): 3 patients, one encounter each, all on one day, and zero labs or clinical notes. A deterministic synthetic cohort is a prerequisite.
2. **OpenEMR has no single definition of "active"** (DQ-HIGH-002): the chart summary uses `enddate`, and the FHIR/API medication path uses `activity`. A demo row already shows the two disagreeing.
3. **Medications live in two unlinked tables and already conflict** (DQ-HIGH-003): an active prescription matches an inactive list entry, and the API returns both.
4. **Clinical dates are missing while audit timestamps are misleading** (DQ-HIGH-004): `begdate`/`enddate` are NULL in all 9 issues, and every `modifydate` is the 2026 install time. Anchoring "since last visit" on modify times would report everything as changed.
5. **Data is mostly uncoded** (DQ-HIGH-005): 0/6 medications coded, allergy uncoded, problems ICD-9 only, RxNorm/SNOMED not loaded. Also, absence is ambiguous (DQ-MEDIUM-007): 2 of 3 patients have no allergy information at all, which is not the same as "no allergies".

## Architecture consequences

1. **Deterministic normalization layer in the read tools.** Each record carries its status (raw `activity`/`enddate`/`outcome`, a derived status, and a `status_conflict` flag), typed dates (`value`, `precision`, `date_basis`, zero-date → NULL), resolved `list_options` terms, and `source_table` + id/uuid. The LLM never interprets raw columns.
2. **The time window uses clinical dates only.** Undated items go to an explicit "cannot place in timeline" group. `modifydate`/`last_updated` are never evidence of clinical change.
3. **Medications are reconciled as groups with provenance, never merged.** Conflicts are shown with both citations. The verifier rejects single-status claims on conflicting groups.
4. **Absence has distinct states** (present / reviewed-none / not documented / unavailable). Wording is templated per state. "No known X" is forbidden without `reviewed_none`.
5. **Lab comparison and abnormality checks run in deterministic code.** Values must be strictly numeric with exactly matching units and a recorded flag or parseable range; otherwise "cannot compare". This is required before UC-02 ships.
6. **Citations don't depend on author fields.** Attribution appears only when the cited row contains it.
7. **Code matching is optional with a title fallback that declares itself.** v1 has no terminology-server dependency.
8. **A versioned synthetic defect cohort (section 6, option C) is a build and eval dependency.** Orphan/consistency queries run as fixture-load assertions, and the dataset version is recorded with every eval run.
