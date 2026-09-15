# Fixture-Based Measurements: Synthetic Cohort `af-cohort-v1`

Date: 2026-09-14. Commit `fc95374` plus uncommitted audit work. Local
`development-easy` stack; Xdebug is loaded, so read timings as relative.
Cohort: `evals/fixtures/cohort/seed_cohort.php --anchor=2026-09-14`.

> **Synthetic data.** Every patient and defect here is planted. These
> measurements show how OpenEMR and the proposed tools behave on
> realistic-shaped data. They do not show how common any defect is in real
> charts, and they are not audit observations of production data.

## 1. Cohort load and determinism

| Check | Result |
| --- | --- |
| Volumes | 26 patients, 50 encounters, 44 issues, 3 prescriptions, 134 lab results, 67 clinical notes, 25 vitals, 12 appointments on the anchor date (11 with `audit-physician`) |
| Post-load assertions | patients 26/26; orphan forms 1/1 (intended, DQ-P); orphan lab results 1/1 (intended); forms attached to another patient's encounter 0; cohort rows missing UUID 0 |
| Determinism | Two consecutive loads gave identical MD5 checksums over 10 tables (patient_data, form_encounter, forms, lists, prescriptions, procedure_result, form_clinical_notes, form_vitals, appointments, lists_touch), with UUIDs excluded |
| Registry leak | `uuid_registry` row count identical after both loads (1,015) |

### Defect found while building the cohort: UUID backfill rewrites modification timestamps

The first version backfilled UUIDs with
`UuidRegistry::createMissingUuidsForTables()`. After that, **all 44** cohort
`lists` rows had `modifydate` equal to the load time (2026-09-15 00:04 UTC)
instead of their planted values, and the reload checksums differed.

- **OBSERVED mechanism:** the backfill assigns UUIDs with
  `UPDATE <table> SET uuid = ? WHERE <id> = ?`
  (`src/Common/Uuid/UuidRegistry.php:425`). That fires `ON UPDATE CURRENT_TIMESTAMP`
  columns on seven of the seeded tables: `lists.modifydate`,
  `patient_data.last_updated`, `form_encounter.last_update`,
  `form_clinical_notes.last_updated`, `form_vitals.last_updated`,
  `issue_encounter.updated_at`, and `procedure_providers.last_updated`
  (`information_schema.COLUMNS`).
- **OBSERVED call site:** `sql_upgrade.php:407` runs
  `UuidRegistry::populateAllMissingUuids()` during upgrades.
- **INFERRED:** this is the likely reason every demo `modifydate` equals the
  install/upgrade time (`data-quality.md` DQ-HIGH-004). Modification timestamps
  in OpenEMR can reflect maintenance jobs, not clinical edits.
- **Fix in the seed:** assign UUIDs at insert time via `createUuid()`, as the
  application services do. The planted DQ-D `modifydate` (anchor − 5 d)
  survived the reload afterwards.

## 2. In-process service latency on the heavy patient

`docs/audit/scripts/audit_service_timing.php 900023 10` (AF-HEAVY: 20 encounters, 7 problems,
9 medication entries, 120 lab results, 39 notes). Warm, in-process, n=10.

| Call | p50 ms | p95 ms | Rows | Demo pid 1 p50 ms (for comparison) |
| --- | ---: | ---: | ---: | ---: |
| `PatientService::findByPid` | 5.65 | 7.26 | 132 fields | 1.50 |
| `EncounterService::getEncountersForPatientByPid` | 24.53 | 36.50 | 20 | 3.57 |
| `PatientIssuesService::getActiveIssues` | 1.39 | 1.46 | 13 | 1.34 |
| `ConditionService::getAll(puuid)` | 6.87 | 7.83 | 26 | 1.59 |
| `AllergyIntoleranceService::getAll(puuid)` | 1.73 | 1.90 | 1 | 1.78 |
| `PrescriptionService::getAll(['puuid'])` | 2.16 | 2.18 | 0 | 4.62 |

## 3. Payload size per candidate tool (raw service output)

`docs/audit/scripts/audit_payload_sizes.php`: JSON-encodes each service result and reports
bytes. **~tokens = bytes ÷ 4** is a rough heuristic; JSON with UUIDs and
field names usually tokenizes worse. Measure with the provider tokenizer
before costing.

| Patient | Tool (service) | Rows | Distinct records | Bytes | ~Tokens | ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| AF-HEAVY | encounters (`EncounterService`) | 20 | 20 | 23,236 | 5,809 | 25.5 |
| AF-HEAVY | active issues (`PatientIssuesService`) | 13 | 13 | 17,918 | 4,479 | 2.4 |
| AF-HEAVY | conditions (`ConditionService`) | **26** | **7** | 33,409 | 8,352 | 5.7 |
| AF-HEAVY | allergies (`AllergyIntoleranceService`) | 1 | 1 | 1,271 | 317 | 2.1 |
| AF-HEAVY | labs (`ProcedureService::search`) | 20 orders / 120 results | 20 | 54,456 | 13,614 | 9.2 |
| AF-HEAVY | notes (`ClinicalNotesService`) | 39 | 39 | 38,320 | 9,580 | 7.5 |
| **AF-HEAVY** | **total** | | | **168,610** | **≈42,150** | **≈52** serial |
| AF-DQ-A2 | encounters | 3 | 3 | 3,495 | 873 | 6.0 |
| AF-DQ-A2 | active issues | 6 | 6 | 7,872 | 1,968 | 1.4 |
| AF-DQ-A2 | conditions | **5** | **3** | 6,492 | 1,623 | 2.1 |
| AF-DQ-A2 | allergies | 1 | 1 | 1,278 | 319 | 1.7 |
| AF-DQ-A2 | labs | 3 orders / 4 results | 3 | 4,144 | 1,036 | 2.8 |
| AF-DQ-A2 | notes | 3 | 3 | 2,804 | 701 | 1.9 |
| **AF-DQ-A2** | **total** | | | **26,085** | **≈6,520** | **≈16** serial |

The "distinct" column for encounters and allergies uses row counts: the
services return those identifiers under different keys, so the script's uuid
key did not match.

**Observations**

- **OBSERVED:** `ProcedureService::search()` with a `puuid` token returns
  orders with nested reports and results: 20 orders / 120 results for
  AF-HEAVY and 3 / 4 for AF-DQ-A2, matching what was seeded. This proves the
  lab path that avoids the broken `getAll()` (PERF-MED-001).
- **OBSERVED:** `ConditionService::getAll()` returns **one row per condition ×
  linked encounter**: 26 rows for 7 conditions (hypertension linked to 20
  encounters: 6 + 20), and 5 rows for 3 on AF-DQ-A2 (two conditions linked to
  2 encounters each). The patient filter holds: the empty chart AF-DQ-R
  returned 0 rows, and each result referenced exactly one patient.
- **OBSERVED:** Raw service output for a five-year chronic patient is about
  169 KB, roughly 42K tokens by heuristic. Labs (54 KB) and notes (38 KB)
  dominate.
- **INFERRED:** Passing raw service payloads to the model is not viable on
  cost or latency. Tools need field projection, a time window, row caps,
  deduplication, and explicit truncation flags.

## 4. Dashboard render: heavy vs near-empty chart

`docs/audit/scripts/page-timing.sh … 20 <pid>` plus `SHOW GLOBAL STATUS`
deltas (2 runs each, after warm-up; identical across runs).

| Patient | p50 ms | p95 ms | HTML bytes | SQL statements (Questions Δ) | SELECT (Com_select Δ) |
| --- | ---: | ---: | ---: | ---: | ---: |
| demo pid 1 (1 encounter, 5 issues) | 351.4 | 410.2 | 155,535 | 1,047 | 886 |
| AF-HEAVY (20 encounters, 120 results, 39 notes) | 362.6 | 402.3 | 156,829 | 1,161 | 1,011 |

**OBSERVED:** Dashboard cost barely depends on chart size (+3% p50, +114
statements). It is dominated by fixed rendering work (PERF-MED-002), not
clinical data volume.
