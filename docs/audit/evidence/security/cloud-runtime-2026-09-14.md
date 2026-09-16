# Cloud Window: Deployed Runtime Configuration

> Superseded for topology and public reachability by the 2026-09-15
> deployment: the Droplet now runs the project image (`agentforge/openemr:local`,
> pinned 8.1.1 base plus the co-pilot module), an agent service on the
> `frontend` network, and a deny-by-default Caddyfile
> (`infra/digitalocean/runtime/compose.yaml`, `Caddyfile`); the post-allowlist
> probe is `cloud-probe-2026-09-15-allowlist.txt`. The globals, grants, and
> container-hardening observations below were not re-collected after that
> redeploy and remain the only recorded values. Nothing below is altered.

Date: 2026-09-14. Commit `fc95374`. Provisioned 23:34:28Z via the reviewed saved
Terraform plan (4 resources: Droplet `s-2vcpu-4gb`/sfo3/Ubuntu 24.04, firewall,
project, SSH key). Deployed with `infra/digitalocean/deploy.sh` using the
default upstream image `openemr/openemr:8.1.1@sha256:796adaa7…`. Smoke test
passed 23:38:55Z after the documented TLS issuance delay. The demo cohort was
**not** loaded; the database contains 0 patients.

All values below were gathered read-only over SSH. Secret values were read
inside the remote shell only and never printed; environment variables are
recorded by **name** only.

## Containers and exposure

| Container | Image | Published | Networks | User / hardening |
| --- | --- | --- | --- | --- |
| caddy | `caddy:2.10.2-alpine` | 80, 443 (IPv4+IPv6) | frontend | default user; `cap_drop=[]`, no `no-new-privileges`, rootfs writable, no memory limit |
| openemr | `openemr/openemr:8.1.1` | none | backend, frontend | same defaults; Apache parent runs as root, workers as `apache` |
| database | `mariadb:11.8.8` | none | backend | same defaults |

- `backend` network `internal=true`; `frontend` `internal=false`.
- Host listening sockets: 22, 80, 443 (plus local resolver 53). From the
  auditor's IP (the allowed SSH CIDR): 22/80/443 open, 3306/8080/9300
  closed/filtered.
- Xdebug **not loaded**. Apache MPM prefork. PHP `max_execution_time=0` in CLI
  (web limit not re-read here).

## Sensitive files present in the deployed webroot

`docker/development-easy/docker-compose.yml`,
`docker/library/sql-ssl-certs-keys/easy/server-key.pem`, `tests/`, and
`composer.lock` are present. `sql_upgrade.php`, `acl_upgrade.php`,
`setup.php`, and `admin.php` are absent (removed by the image after setup).
Public reachability is in `cloud-probe-2026-09-14.txt` §1.

## Process environment (names only)

- Container PID 1 (Apache parent, root): `OE_PASS`, `MYSQL_PASS`,
  `MYSQL_ROOT_PASS`, exported by `infra/digitalocean/runtime/openemr-entrypoint.sh:16-19`.
- Apache worker processes (`apache` user): `/proc/<pid>/environ` not readable
  even with `docker exec -u 0` (permission denied). Inheritance by forked
  workers is the normal behavior but is **INFERRED**, not observed.

## Security-relevant globals (deployed vs local dev)

| Global | Deployed | Local dev | Note |
| --- | --- | --- | --- |
| `rest_api` | 0 | 1 | Deployment has REST disabled |
| `rest_fhir_api` | 0 | 1 | FHIR disabled; `metadata` and `smart-configuration` still return 200, `Patient` returns 401 |
| `rest_portal_api` | 0 | 1 | |
| `rest_system_scopes_api` | 0 | 1 | |
| `oauth_password_grant` | 0 | 3 | Password grant **off** in deployment |
| `oauth_app_manual_approval` | 0 | 0 | Auto-enable logic still applies if APIs are later enabled |
| `oauth_ehr_launch_authorization_flow_skip` | 1 | 1 | |
| `site_addr_oath` | empty | `https://localhost:9300` | Consistent with OIDC discovery returning 404 publicly |
| `enable_auditlog` | 1 | 1 | |
| `audit_events_query` | 1 | empty | SELECT auditing **on** in deployment (code default) |
| `audit_events_patient-record` | 1 | 1 | |
| `api_log_option` | 2 | 2 | Full response bodies would be logged if APIs were enabled |
| `gbl_force_log_breakglass` | 1 | 1 | |
| `password_max_failed_logins` | 20 | 20 | |
| `ip_max_failed_logins` | 100 | 100 | |
| `secure_password` | 1 | empty | Complexity **on** in deployment |
| `gbl_minimum_password_length` | 9 | 9 | |
| `timeout` | 7200 | 7200 | |
| `restrict_user_facility` | 0 | empty | |

Other: `users` 4 (1 active), `patient_data` 0, `login_mfa_registrations` 0.

## Database account privileges

`SHOW GRANTS FOR 'openemr'@'%'`: `GRANT USAGE ON *.*` and
`GRANT ALL PRIVILEGES ON openemr.*`. The application account can alter or
drop the audit tables (`log`, `log_comment_encrypt`, `api_log`), which
supports COMP-HIGH-001.

## Teardown

A reviewed saved destroy plan showed `0 to add, 0 to change, 4 to destroy`.
Applying it at 23:42:34Z removed the firewall, project, Droplet, and SSH key
(`Apply complete! Resources: 0 added, 0 changed, 4 destroyed`). The environment
was live about 8 minutes: provision 23:34:28Z → destroy complete 23:42:34Z,
≈$0.01 compute at $0.03571/h. Generated deployment secrets were destroyed with
the Droplet. Local Terraform state (git-ignored) holds no resources, and the
saved plan files were deleted.
