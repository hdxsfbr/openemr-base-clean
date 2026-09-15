# Live Test: Cross-Patient Chart Access by Role (SEC-HIGH-001)

Date: 2026-09-14. Commit `fc95374`. Local `development-easy` stack, demo data.
This ran after the data-quality profile of pristine data completed.

## Setup (test fixtures; no real users or patients)

- Three users created through the application's own admin form
  (`interface/usergroup/usergroup_admin.php`, `mode=new_user`, CSRF token and
  admin re-authentication): `audit-physician` (Physicians, authorized=1),
  `audit-nurse` (Clinicians), `audit-frontdesk` (Front Office). All are in
  facility 3. Random passwords are held only in a local scratch file outside
  the repository.
- Setup note: the form writes a legacy `groups` row with an empty name when
  `groupname` is omitted. `AuthUtils` (`src/Common/Auth/AuthUtils.php:350-359`)
  then rejects login with "user not found in a group". The rows were set to
  `Default` to match every existing user. This is a minor admin-UX defect, not
  a security finding.
- None of the test users is the provider or care-team member for any patient,
  has an appointment with any patient, or has any relationship to one. No
  demo patient has a `squad` set.

## Procedure

For each user: log in (`POST interface/main/main_screen.php?auth=login`, which
returns 302 on success), then
`GET interface/patient_file/summary/demographics.php?set_pid=<pid>` for pid 1
and pid 2. Recorded HTTP status, byte count, presence of the unauthorized
partial or a login redirect, and which dashboard section labels appear.
Section labels confirm the cards rendered. Card *data* contents were not
extracted, by design.

## Results

| User (role) | pid | HTTP | Bytes | Unauthorized / redirected | Section labels rendered |
| --- | --- | --- | --- | --- | --- |
| audit-physician (Physicians) | 1 | 200 | 155,536 | no / no | Allergies, Amendments, Care Team, Clinical Reminders, Demographics, Disclosures, Labs, Medical Problems, Medications, Messages, Prescriptions, Vitals |
| audit-physician (Physicians) | 2 | 200 | 156,169 | no / no | same |
| audit-nurse (Clinicians) | 1 | 200 | 154,158 | no / no | same |
| audit-nurse (Clinicians) | 2 | 200 | 154,791 | no / no | same |
| audit-frontdesk (Front Office) | 1 | 200 | 143,845 | no / no | Amendments, Care Team, Demographics, Prescriptions |
| audit-frontdesk (Front Office) | 2 | 200 | 144,001 | no / no | same |

## Audit log produced by the test

`SELECT user, event, patient_id, success, COUNT(*) FROM log WHERE user LIKE 'audit-%' ... GROUP BY ...`

| User | `view` events (patient_id) | Other events |
| --- | --- | --- |
| audit-physician | pid 1 ×1, pid 2 ×1, success=1 | login success=1 (and the earlier group-row failure, success=0); http-request-select/update; other-insert |
| audit-nurse | pid 1 ×1, pid 2 ×1, success=1 | same pattern |
| audit-frontdesk | pid 1 ×1, pid 2 ×1, success=1 | same pattern |

The log attributes each chart open to user and patient, which is enough for
after-the-fact review. Nothing indicates an access outside a care
relationship, because OpenEMR has no such concept.

## Follow-up: does session pid bypass section ACLs? (SEC-HIGH-002)

With `audit-frontdesk`'s session pid set to 2 by the previous request:

| Request | HTTP | Bytes | Result |
| --- | --- | --- | --- |
| `stats_full.php?active=all&category=medication` | 403 | 1,810 | unauthorized partial, 0 issue rows |
| `stats_full.php?active=all&category=allergy` | 403 | 1,810 | unauthorized partial, 0 issue rows |
| `stats_full.php?active=all&category=medical_problem` | 403 | 1,810 | unauthorized partial, 0 issue rows |

`stats_full.php` re-checks `AclMain::aclCheckIssue()` (lines 43, 223), so there
was no leak on this page. This is a negative result, recorded as such.

## Interpretation

- **OBSERVED:** Any Physicians- or Clinicians-group user can open the full
  clinical dashboard of any patient, with no relationship required. Front
  Office opens demographics for any patient; its clinical cards are reduced by
  section ACLs. This confirms SEC-HIGH-001 live.
- **Caveat:** the "Prescriptions" label on the Front Office page may be a menu
  or heading rather than rendered prescription data. See the
  `stats_full.php` follow-up in `security.md` (SEC-HIGH-002).
