# Lead Auditor Spot-Check of Compliance Track Claims

Date: 2026-09-14. Commit `fc95374`. Local `development-easy` stack.
These are independent re-verifications of the compliance track's highest-impact
claims before synthesis into `AUDIT.md`. Method: code reading and read-only SQL.

| Claim | Result | Evidence |
| --- | --- | --- |
| Audit-log checksums are unkeyed and stored with the rows | **Confirmed** | `src/Common/Logging/Audit/LogTablesSink.php:63` `hash('sha3-512', implode('', array_values($logData)))`; `:83` same for API log; stored in `log_comment_encrypt.checksum` / `checksum_api` in the same database (`:86-91`). No HMAC or secret key, so anyone with DB write access can alter a row and recompute its checksum. |
| Admin "EventLog Backup" renames and drops log tables | **Confirmed** | `interface/main/backup.php:1015-1019` renames `log`, `log_comment_encrypt`, `api_log` to `*_backup` and swaps in new tables; `:1091-1095` and `:1105-1106` drop tables. |
| `api_log_option=2` stores full JSON response bodies (PHI) | **Confirmed** | Local global `api_log_option=2`. `src/RestControllers/Subscriber/ApiResponseLoggerListener.php:62-64` captures `$response->getContent()`; `:84-85` writes it to both `request_body` and `response`. Internal "local API" calls are skipped (`:53`). |
| SELECT-query audit logging is off locally despite code default on | **Confirmed** | Local `audit_events_query` is empty; default `'1'` at `library/globals.inc.php:2832-2836`. `audit_events_patient-record=1`. |

Not re-verified here: deployed-environment values, DB grants, retention, and
encryption coverage. Those remain as stated (and caveated) in `../../compliance.md`.
