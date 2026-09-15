# Index Coverage for Co-Pilot Read Paths

Date: 2026-09-14. Commit `fc95374`. Local MariaDB 11.8 (`development-easy`).
Source: `information_schema.STATISTICS` for the clinical tables UC-01 tools read.
Metadata only.

| Table | Patient index | Date/time index | Type/status index | Notes |
| --- | --- | --- | --- | --- |
| `lists` (problems, meds, allergies) | `pid` | none | `type` (separate single-column) | No `(pid, type)` or `(pid, modifydate)` composite. "Changed since" filters scan all of a patient's issues. |
| `lists_medication` | via `list_id` | none | `request_intent`, `usage_category` | 1:1 extension of `lists` rows. |
| `prescriptions` | `patient_id` | none | none | No date index for "started/changed since". |
| `form_encounter` | `(pid, encounter)` | `date` (global, not per-patient) | — | "Last visit before today" uses `pid` then filters date. |
| `forms` | `(pid, encounter)` | none | `form_id` | Registry for per-form note tables. |
| `form_clinical_notes` | **none** | none | — | Only `PRIMARY`, `uuid`. Patient lookups join through `forms`. |
| `form_soap` | **none** | none | — | Only `PRIMARY`. Same join-through-`forms` pattern. |
| `form_vitals` | `pid` | none | — | |
| `pnotes` | `pid` | none | — | |
| `issue_encounter` | `(pid, list_id, encounter)` unique | — | — | |
| `procedure_order` | `patient_id`; `(date_ordered, patient_id)` | `scheduled_date` | `order_intent` | Leading column of `datepid` is date, not patient. |
| `procedure_report` | via `procedure_order_id` | none | — | |
| `procedure_result` | via `procedure_report_id` | none | — | Labs require a 3-table join: order → report → result. |

## Assessment

- **OBSERVED:** Every clinical area has *some* patient-scoped access path. No
  table forces a full-table scan to find one patient's rows.
- **OBSERVED:** No clinical table has a `(patient, changed-at)` index. Note
  form tables have no patient column index at all; they are reached through
  `forms(pid, encounter)`.
- **INFERRED:** At demo scale (≤10 rows per patient) this is irrelevant. At
  realistic scale (hundreds of results and notes per chronic patient), "what
  changed since the last visit" filters date columns after the patient
  lookup. That is fine per patient, but it would matter for a
  whole-schedule prefetch ("all 20 patients on today's schedule").
- **Not measured:** `EXPLAIN` plans on realistic volumes. Revisit after the
  synthetic cohort is seeded (`data-quality.md`, DQ-CRITICAL-001) instead of
  adding indexes speculatively.
