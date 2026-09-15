# In-Process Service Latency and Dashboard Query Composition

Date: 2026-09-14. Commit `fc95374`. Local `development-easy` stack (Xdebug
loaded; see caveats in `page-timing-local.md`). Demo pid 1.

## 1. Clinical service latency (what agent tools would call)

Script: `docs/audit/scripts/audit_service_timing.php 1 10`, run as the `apache` user inside
the container (OpenEMR refuses root CLI, `src/Common/Command/RootCliGuard.php:66`).
It measures wall time per call with `hrtime`, 10 iterations, and prints record
counts only.

| Call | n | p50 ms | p95 ms | max ms | Records | Status |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `PatientService::findByPid` | 10 | 1.50 | 1.66 | 1.87 | 132 (fields) | ok |
| `EncounterService::getEncountersForPatientByPid` | 10 | 3.57 | 3.72 | 4.83 | 1 | ok |
| `PatientIssuesService::getActiveIssues` | 10 | 1.34 | 1.61 | 2.33 | 5 | ok |
| `ConditionService::getAll(puuid)` | 10 | 1.59 | 1.94 | 3.39 | 2 | ok |
| `AllergyIntoleranceService::getAll(puuid)` | 10 | 1.78 | 2.04 | 2.24 | 1 | ok |
| `PrescriptionService::getAll(['puuid'])` | 10 | 4.62 | 4.99 | 5.25 | 0 | ok |
| `ProcedureService::getAll(puuid)` | 0 | — | — | — | — | **SQL syntax error** |

The serial p50 sum of the working calls is ≈14 ms. Caveat: the demo chart is
tiny, and calls are warm and in-process with no HTTP or auth overhead.

**`ProcedureService::getAll()` is broken:** the base SQL ends with a bare
`LEFT JOIN` before `WHERE` (`src/Services/ProcedureService.php:648`). MariaDB
rejects it (`You have an error in your SQL syntax … near 'WHERE porder.activity = 1'`).
Caller: `src/RestControllers/ProcedureRestController.php:80` (REST
`GET /api/procedure`).

## 2. What one dashboard render actually queries

Method: MariaDB general log (original `general_log=0`, `log_output=FILE`
recorded first). Set `log_output=TABLE`, truncate, log **one**
`demographics.php?set_pid=1` request, turn logging off, and aggregate statement
*shapes* with quoted literals and digits stripped. Then truncate
`mysql.general_log` and restore the original settings (verified `0 FILE`). No
literal values were exported.

Totals: 757 prepared statements executed plus 284 text queries across 4
connections, consistent with the ≈1,045 from the `Questions` counter.

| Count | Statement shape (truncated) | Source |
| ---: | --- | --- |
| 431 | `SELECT lang_definitions.definition FROM lang_definitions JOIN lang_constants …` | per-string translation (`xl()`), uncached |
| 104 | `SELECT grp_group_id, grp_unchecked FROM layout_group_properties WHERE grp_form_id = ? …` | layout rendering |
| 56 | `SELECT a.id,a.allow,a.return_value FROM gacl_acl a LEFT JOIN gacl_aco_map …` | `aclCheckCore` → phpGACL, uncached per request |
| 56 | `SELECT DISTINCT gN.id FROM gacl_aro o, gacl_groups_aro_map gm, …` | same (group resolution) |
| 42 | `SELECT title FROM list_options WHERE list_id = ? AND option_id = ? …` | per-field code → label |
| 31 | `SHOW TABLES` | schema probing |
| 30 | `SET AUTOCOMMIT=N` | connection handling |
| 28 | `SELECT setting_value FROM user_settings …` | per-card user prefs |
| 20 | `SELECT * FROM clinical_rules WHERE id=? AND pid=?` | CDR reminder evaluation |
| 15 / 15 | `BEGIN` / `COMMIT` | |
| 8 | `SELECT option_id, title FROM list_options WHERE list_id = ?` | |
| 7 | `SELECT * FROM layout_options …` | |
| 5 / 5 | `SHOW COLUMNS FROM contact …` | |

## Interpretation

- **OBSERVED:** Clinical data is a small share of the dashboard's cost. Most
  statements are translation, layout, ACL, and list-label lookups repeated per
  field or card with no request cache.
- **OBSERVED:** The clinical services themselves return in low single-digit
  milliseconds at demo scale.
- **INFERRED:** Agent tools that call services directly avoid ≈95% of the
  dashboard's query load and ≈0.35 s of render time. They must not reuse
  page-rendering helpers (`xl`, layout renderers) per field. ACL decisions
  should be computed once per tool call, not per record.
