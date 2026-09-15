# Lead Auditor Spot-Check of Data-Quality Track Claims

Date: 2026-09-14. Commit `fc95374`. Local `development-easy` stack, pristine demo
data (profiled before any audit test users or data were added).

| Claim | Result | Evidence (aggregates only) |
| --- | --- | --- |
| Dataset cannot exercise UC-01 (DQ-CRITICAL-001) | **Confirmed** | `patient_data`=3, `form_encounter`=3 across 1 distinct date, `procedure_result`=0, `pnotes`=0, `prescriptions`=1. |
| Clinical begin/end dates absent for all issues (DQ-HIGH-004) | **Confirmed** | `lists`: allergy 1/1, medical_problem 3/3, medication 5/5 rows with NULL/zero `begdate` and `enddate`. |
| One medication inactive via `activity` flag with no end date (DQ-HIGH-002) | **Confirmed** | `lists` medication: 5 rows, 4 with `activity=1`, all 5 with no `enddate`. |
| `disappearList()` clears `activity` without setting `enddate` | **Confirmed** | `library/lists.inc.php:118-121`: `update lists set activity = '0' where id=?`. |
| Multiple "active" definitions across UI vs services | **Partially re-verified** | `disappearList` confirmed. The UI-card, `PatientIssuesService`, and `PrescriptionService` rules are as cited in `../../data-quality.md` §3.3 but were not independently re-read. Pin them with unit tests before relying on them. |
| No squad restrictions on demo patients | **Observed (lead)** | `patient_data.squad` empty for all 3 pids, so the squad-ACL path cannot be exercised without seeding. |
