# Lead Auditor Spot-Check of Architecture Track Claims

Date: 2026-09-14. Commit `fc95374`. Local `development-easy` stack.
These are independent re-verifications before synthesis into `AUDIT.md`.

| Claim | Result | Evidence |
| --- | --- | --- |
| No patient-level authorization on the REST/FHIR bearer-token path (ARCH-HIGH-003) | **Confirmed, with scope clarified** | `src/RestControllers/Authorization/BearerTokenAuthorizationStrategy.php:479-485`: `checkUserHasAccessToPatient()` has a TODO comment and returns `true` unconditionally. Its only caller (`:443`) binds a SMART EHR-launch patient to a token. General clinician-token requests have no patient filter at all, only role (`:383-385`), scope, and section ACL checks. The stub is identical in the deployed `openemr:8.1.1` image. |
| The in-session "local API" skips scope authorization entirely | **Confirmed** | `src/RestControllers/Authorization/LocalApiAuthorizationController.php:111` sets `skipAuthorization=true`; `src/RestControllers/Subscriber/AuthorizationListener.php:154-157` returns before any role or scope check when `isLocalApi()` or `skipAuthorization`. An embedded module calling the local API gets **no** ACL enforcement from the API layer. |
| SMART patient-context search checks only role-level `patients/demo` | **Confirmed** | `src/RestControllers/SMART/PatientContextSearchController.php:84-90`. |
| Apache prefork with 60 s PHP limit (ARCH-MEDIUM-006) | **Confirmed** | `httpd -V`: `Server MPM: prefork`. Container `php.ini`: `max_execution_time = 60`. The CLI reports 0, which is the normal CLI override. |
| Working example module exists for chart embedding | **Confirmed** | `interface/modules/custom_modules/oe-module-dashboard-context/` (`openemr.bootstrap.php`, `ModuleManagerListener.php`, `src/`, `sql/`). |
| Session `pid` is shared by all tabs of one login (ARCH-HIGH-001) | **Consistent with code; effect still INFERRED** | `library/restoreSession.php:26-30` keeps a distinct session only per *login* (per top-level window created by a new login). Tabs and frames inside one login share it. Two-tab live test (Q1) still required. |
