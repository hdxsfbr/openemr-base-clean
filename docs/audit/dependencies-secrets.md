# Pre-Build Audit — Dependencies & Secrets (Security section)

- **Scope:** third-party dependency vulnerabilities (Composer, npm, container images), static analysis (Semgrep), secrets inventory, network exposure and runtime identity for the dev stack (`docker/development-easy`) vs. the deployment path (`infra/digitalocean`).
- **Date:** 2026-09-14. **Auditor:** automated agent, reviewed evidence only; no source, data, settings, or running containers were modified.
- **Evidence:** `docs/audit/evidence/dependencies/` — `COMMANDS.txt` (every command, tool digest, sanitized output), `composer-audit.json`, `npm-audit-*.json`, `trivy-config-*.json`. The five raw Trivy image scans and `semgrep-raw.json` (≈9.5 MB together, secret match/code fields redacted) are kept locally but gitignored as generated scanner output; the counts and sampled results below are the committed record, and `COMMANDS.txt` regenerates the raw files against the same pinned digests.
- **Labels:** **OBSERVED** = backed by a command result or `file:line`. **INFERRED** = reasoning given, not directly tested.
- **Secret handling:** no secret values are recorded. Token-like strings are described by type, length, and an 8-character SHA-256 fingerprint of the decoded value. No credential was used against any service.

## 1. Deployment path in one paragraph

OBSERVED (`infra/digitalocean/runtime/compose.yaml`, `main.tf`): one Droplet runs Caddy 2.10.2 (publishes 80/443), upstream `openemr/openemr:8.1.1` (pinned digest, no host ports, networks `frontend`+`backend`), and MariaDB 11.8.8 (no host ports, `backend` is `internal: true`). Secrets are generated on the Droplet (`start.sh:32-36`, `openssl rand -hex 24`, mode 600) and supplied as compose file secrets. The DO Cloud Firewall allows 22 only from `allowed_ssh_cidrs` (validated not to be world-open, `variables.tf:36-47`), 80/443 from anywhere, and all egress. **Key consequence:** the deployed OpenEMR code and PHP vendor tree come from the upstream 8.1.1 image, **not** from this repository's `composer.lock`/`package-lock.json` (OBSERVED: image `vendor/composer/installed.json` has `twig/twig v3.24.0`; repo `composer.lock` has `v3.27.1`). Repo dependency audits describe the *future* project image; image scans describe what is actually deployed today.

## 2. Dependency audit

### 2.1 Composer (`composer audit --locked`, repo lock) — OBSERVED

187 prod / 61 dev packages. 20 advisories:

| Package (lock version) | Prod/dev | High | Medium | Low | Notes |
|---|---|---|---|---|---|
| guzzlehttp/guzzle 7.12.1 | prod | 1 (CVE-2026-69246 non-canonical host bypasses host-based checks) | 6 | – | fix 7.15.2 |
| guzzlehttp/psr7 2.12.1 | prod | – | 1 (host confusion) | – | fix 2.12.3 |
| phpoffice/phpspreadsheet 5.8.0 | prod | 3 (XLS/OLE loop DoS, Gnumeric gzip bomb, WEBSERVICE() SSRF via redirect) | – | – | |
| dompdf/dompdf v3.1.5 | prod | – | 4 (incl. local file read via SVG data-URI) | 2 | fix 3.1.6 |
| smarty/smarty v4.5.6 | prod | – | 2 (`{fetch}` SSRF, symlink traversal) | – | fix 4.5.7 |
| squizlabs/php_codesniffer 4.0.1 | **dev** | 1 (OS command injection) | – | – | not deployed |

Abandoned: laminas-config, laminas-json, laminas-loader, php-http/message-factory, symfony/inflector, yubico/u2flib-server.

Reachability of High items:
- **PhpSpreadsheet (3 High):** INFERRED low. OBSERVED `src/Services/SpreadSheetService.php:21,145` uses `IOFactory::createWriter` only (exports in `interface/reports/appointments_report.php`, `library/ajax/immunization_export.php`). The two DoS CVEs need the *reader* on attacker files. The SSRF needs formula calculation of `WEBSERVICE()`. Neither pattern was found.
- **Guzzle CVE-2026-69246:** INFERRED medium relevance. About 23 app files build Guzzle clients (`src/Common/Http/HttpClient.php`, `oeHttp.php`, `interface/usergroup/npi_lookup.php`, fax/SMS/telehealth modules). A grep for app code comparing `getHost()` to an allowlist found nothing, so no current code path is known to depend on host checks. It **will** matter if the co-pilot service enforces an LLM/FHIR egress allowlist with Guzzle.
- **phpcs:** dev-only. INFERRED it does not reach a production image if the image uses `composer install --no-dev`.
- **Twig (not flagged in repo lock, which is patched):** the *deployed image* has v3.24.0 with 6 Critical sandbox/compile CVEs (see 2.3). INFERRED exploitation requires attacker-controlled templates; OpenEMR templates are server-side files, so practical risk is lower than the rating, but it is an unpatched Critical in the running artifact.

### 2.2 npm — OBSERVED

| Run | Critical | High | Moderate | Low | Total |
|---|---|---|---|---|---|
| `npm audit --omit=dev` (247 prod deps) | 0 | 0 | 5 | 0 | 5 |
| `npm audit` (1186 deps) | 2 | 11 | 11 | 2 | 26 |

- Runtime (browser-shipped) moderates: `dompurify` 3.4.11 (sanitizer bypasses; used by `portal/messaging/messages.php`, `portal/messaging/js/messages.js`, admin user/facility forms), `jszip`/`fflate` via `dwv` (DICOM viewer), and `validate.js` (ReDoS, no fix, client-side only). INFERRED: the DOMPurify bypass is the only one of real interest, because it weakens XSS defense on patient-portal messaging.
- Critical/High are all **build-time dev tooling**: `napa` → `tar`/`tar-pack`/`decompress` (Zip Slip, arbitrary file write), `postcss`, `svgo`, `js-yaml`, `brace-expansion`, `browserslist`, `immutable`, `nanoid`, `ws`, `fast-uri`. INFERRED: not reachable from the web app. However, `napa` downloads unpinned archives at install time (`package.json:112-121`: GitHub archives, jqueryui.com zips, NLM lforms zip) and extracts them with vulnerable `tar`/`decompress`. That is a **build supply-chain** risk for any future project image.
- The deployed 8.1.1 image separately ships `ccdaservice/node_modules/tar` 7.5.11 (Critical CVE-2026-59873, gzip-bomb DoS). OBSERVED in Trivy.

### 2.3 Container images (Trivy 0.69.3, vuln+secret+misconfig) — OBSERVED

| Image (digest pinned in) | OS | Critical | High | Medium | Low | Fixable C/H | Highlights |
|---|---|---|---|---|---|---|---|
| openemr 8.1.1 `796adaa7…` (**infra**) | Alpine 3.23.5 | 8 | 226 | 246 | 75 | 8/223 | twig 3.24.0 (6 Critical); spring-beans 5.2.10 CVE-2022-22965 inside `Documentation/EHI_Export/schemaspy/jars/schemaspy.jar` (no `java` binary in image, so INFERRED not executable); node `tar`; apache2 2.4.67 (5 High, fix 2.4.68); curl 8.19 (10 High); apr-util; c-ares. **84 secret hits** (private keys; see SEC-HIGH-500) |
| openemr flex `1d2c8345…` (dev) | Alpine 3.23.5 | 1 | 182 | 223 | 66 | 1/182 | OS packages only (nodejs 24.14.1 Critical, apache2, curl, imagemagick) — app code is bind-mounted from the repo |
| caddy 2.10.2-alpine `4c6e91c6…` (**infra, internet-facing**) | Alpine 3.22.3 | 6 | 77 | 70 | 37 | 6/77 | Caddy itself: 7 High (CVE-2026-27586/87/88/90, CVE-2026-45135 "Remote Code E…", CVE-2026-52845), fixed ≤ 2.11.4; Go stdlib crypto/tls Critical CVE-2025-68121; smallstep/certificates Critical; OpenSSL 3.5.5 Critical/High; musl, zlib High |
| mariadb 11.8.8 `24e76fce…` (infra) | Ubuntu 24.04 | 1 | 21 | 133 | 27 | 1/21 | Critical/High are all in `/usr/local/bin/gosu` (Go 1.24.6 stdlib). INFERRED low reachability: gosu only drops privileges at start and does no network I/O |
| mariadb 11.8.8 `be1ef4fe…` (dev) | Ubuntu 24.04 | 1 | 23 | 214 | 49 | 1/23 | Same, plus OpenSSL High. **Different digest than infra for the same tag** |

Trivy image misconfig on 8.1.1 (DS-0002 root user, etc.) is from Dockerfiles copied into the image under `/tmp/openemr` and describes those files, not the image. Trivy `config` on `infra/digitalocean`: DIG-0001 ×2 (world ingress 80/443, intended) and **DIG-0003 ×3 (unrestricted egress TCP/UDP/ICMP, `main.tf:54-69`)**. Trivy has no compose checks; compose was reviewed manually (§5).

## 3. Semgrep (`./run-semgrep.sh`, p/php + p/security-audit + p/javascript + p/nodejs + `semgrep.yaml`) — OBSERVED

594 results (316 ERROR, 278 WARNING) across 5,730 files. 6 scan errors (4 timeouts in `swagger/*.js` bundles, 2 partial parses). `run-semgrep.sh` uses `semgrep/semgrep:latest` (resolved 1.176.1), which is **not pinned**.

| Category | Rules (count) | Top locations |
|---|---|---|
| SQL injection | tainted-sql-string 68, openemr-sql-injection-sqlstatement 64, openemr-sql-injection-sqlquery 40 | interface/billing, interface/main, interface/patient_file, gacl/admin, library/spreadsheet.inc.php |
| XSS | echoed-request 128, var-in-href 68, unquoted-attribute-var 55, openemr-js-innerhtml-dynamic 55, openemr-js-eval-ajax-response 13, openemr-xsl-disable-output-escaping 18, var-in-script-tag 9, react dangerouslySetInnerHTML 4 | library/ajax, interface/forms, ccr/*.xsl |
| Path traversal / file | tainted-filename 66 | interface/patient_file, interface/fax, interface/billing |
| SSRF | tainted-url-host 1 | interface/fax/fax_dispatch.php |
| Deserialization | extract-user-data 2; no unserialize rule hits | growthchart |
| Info disclosure | phpinfo-use 1 | ci/phpinfo.php |

**Manually verified samples (10). No confirmed true positive:**

| Location | Verdict | Reason (OBSERVED) |
|---|---|---|
| `interface/billing/sl_eob_search.php:392` | False positive | IDs bound with `?` placeholders (`:394-397`) |
| `interface/drugs/drug_inventory.php:91` | False positive | Only constant SQL fragments; user values go into `$binds` |
| `gacl/admin/acl_admin.php:101-104` | False positive (mitigated) | `$db->qStr()` quoting, CSRF check (`:106`), `AclMain::aclCheckCore('admin','acl')` gate (`:17`) |
| `library/spreadsheet.inc.php:125-160` | False positive | `escape_table_name()` plus bound values |
| `custom/qrda_functions.php:108` (and `:37,:42`) | Weak pattern, not exploitable as found | `add_escape_custom(implode(",", $patArr))` inside **unquoted** `IN (...)`. INFERRED safe because `$patArr` comes from report results in `custom/export_qrda_xml.php`, not request input. Fragile: flag for refactor to placeholders |
| `custom/qrda_download.php:50-53` | False positive | `check_file_dir_name($qrda_fname)` (`:37`) plus CSRF check (`:35`) |
| `interface/fax/fax_dispatch.php:174` (SSRF) | False positive | Builds a `file://` URL for a DB row from `check_file_dir_name`-sanitized path (`:124-150`); no outbound request |
| `interface/forms/vitals/growthchart/chart.php:507` | False positive | `extract()` on the server function `getPatientAgeYMD()` result, not user data |
| `controllers/C_Document.class.php:715` | False positive | Echoes encrypted ciphertext as an `application/octet-stream` attachment |
| `ci/phpinfo.php:11` | Guarded | Dies unless `OPENEMR_ENABLE_CI_PHP` is set; OBSERVED guard message returned on the dev stack and env var not set |

Unserialize (manual grep): 58 `unserialize(` occurrences in src/library/interface/portal. The 2 lacking `allowed_classes` are comments (`src/Services/PatientService.php:994`, `src/Gacl/Gacl.php:642`). **Unreviewed:** the other ~584 results. Given 10/10 false positives or mitigated, treat the raw counts as triage input, not as a finding count. XSS `echoed-request` in `library/ajax` and the `xsl disable-output-escaping` cases in CCR/CCDA viewers are the best next review targets, because C-CDA content can be attacker-supplied.

## 4. Secrets inventory

| # | Item (file:line) | Type (no values) | Provenance (INFERRED unless noted) | Reaches deployment path? |
|---|---|---|---|---|
| S1 | `docker/development-easy/docker-compose.yml:75-77` (identical in `development-easy-light:75-77`, `development-easy-redis:180-182`, `development-insane:224-226`) | `GITHUB_COMPOSER_TOKEN`: 40 lowercase hex (legacy GitHub token format), fp `ae8ed247`. `…_ENCODED`: base64 of a `ghp_`-prefixed 40-char string (GitHub classic PAT format), fp `fafe95dc`. `…_ENCODED_ALTERNATE`: space-separated decimal ASCII of a *different* `ghp_` 40-char string, fp `be8fa6f1` | Upstream OpenEMR dev tooling. The encodings look designed to evade GitHub secret scanning (the literal-prefix grep found no `ghp_` hits). Consumed by `docker/flex/openemr.sh:766-790` to set composer GitHub auth. `git log -S` shows it in fork commit `ef3d490` (2026-06-27), probably the import. Validity **not tested** | **Yes, indirectly.** Not set in the infra compose env (OBSERVED). But the file ships in the upstream 8.1.1 image webroot and is **served over HTTP** (SEC-HIGH-500) |
| S2 | `docker/library/{sql,couchdb-config,ldap}-ssl-certs-keys/{easy,insane}/*-key.pem` (18 files), `ci/nginx/dummy-key`, `docker/library/dockers/dev-nginx/dummy-key` | RSA/PKCS#8 private keys (CA, server, client) | Upstream public dev fixtures. Dev MariaDB uses the `easy` server key (`dev compose:9-11`) | Not used by infra (MariaDB has no TLS config; OBSERVED `compose.yaml:7-10`). **Present and served over HTTP** in the 8.1.1 image webroot (SEC-HIGH-500). Also in an image layer at `/tmp/openemr` (Trivy layer `COPY /openemr /tmp/openemr`) |
| S3 | `tests/Tests/data/Unit/Common/Auth/Grant/openemr-rsa384-private.key` | RSA private key (test JWT signing fixture) | Upstream unit-test fixture | Served over HTTP from deployed image. INFERRED not the site OAuth2 key (OpenEMR generates per-site keys under `sites/*/documents/certificates`, which is `Require all denied`) |
| S4 | `/etc/ssl/apache2/server.key` in both OpenEMR images | Private key baked at image build (sha256 prefix `1b7b9f17c0c0` in 8.1.1) | Upstream build | INFERRED identical for every user of the image. Caddy proxies to `openemr:80` over plain HTTP, so this key is not used on the public edge; internal hop is unencrypted (PRE-005 context) |
| S5 | `sites/default/sqlconf.php:8-9` | DB login/password equal the upstream default placeholder; `$config = 0` | Upstream installer template | INFERRED no: deployment mounts named volume `openemr_sites` populated by the image's setup with generated secrets. Served URL executes as PHP with empty output (OBSERVED 200 text/html, no content leak) |
| S6 | dev compose default creds `:14,63-67,93-94,102-103,133,169-170` | MySQL root/root, openemr/openemr, OE admin/pass, CouchDB admin/password, SMTP openemr/openemr, Selenium VNC static password | Upstream dev defaults | No (OBSERVED infra uses file secrets; `OE_USER: challenge-admin`) |
| S7 | `Documentation/api/AUTHENTICATION.md:333,672,682`, `tests/Tests/Api/ApiTestClient.php:50` (`BOGUS_REFRESH_TOKEN`) | Example/bogus refresh-token strings | Docs/test fixtures | Docs dir ships in image; INFERRED non-functional examples |
| S8 | `infra/digitalocean/terraform.tfstate`, `terraform.tfstate.backup`, `deploy.tfplan`, `terraform.tfvars` (local, mode 0644) | State: droplet IP, SSH **public** key, cloud-init user_data; `sensitive_attributes: []`; no password/private key markers (OBSERVED). tfvars: operator's SSH source CIDR only. Plan: public key and sshd config text only | Local operator run 2026-09-14 | Not committed: `.gitignore:8-14` covers `.terraform/`, `*.tfstate*`, `*.tfplan`, `*.tfvars` (`!*.tfvars.example`), `infra/digitalocean/runtime/secrets/`; `git ls-files` shows only `terraform.tfvars.example`. **No `.dockerignore` exists** (OBSERVED), so a future `docker build .` would copy these files plus S1–S3 into an image |
| S9 | DigitalOcean API token | Env var `DIGITALOCEAN_TOKEN` only (`tf.sh:28-30`, runbook) | Operator | Never written to files (OBSERVED no `dop_v1_` in repo, plan, or state) |
| S10 | Runtime app secrets | `runtime/secrets/{mysql_root_password,mysql_password,openemr_admin_password}` generated on the Droplet | `start.sh` | Not in cloud-init/state (OBSERVED). See SEC-MEDIUM-503 for env exposure |

## 5. Network exposure & runtime identity — dev vs deployment

| Control | Dev (`docker/development-easy`) — OBSERVED live | Deployment (`infra/digitalocean`) — OBSERVED config |
|---|---|---|
| Published ports | 10 ports on `0.0.0.0` and `[::]` (`ss -ltn`): 8300/9300 OpenEMR, 8310 phpMyAdmin (HTTP 200), 8320 MariaDB, 5984/6984 CouchDB, 4444 Selenium (status 200), 7900 VNC, 8025 Mailpit UI/API (200, unauthenticated), 1025 SMTP (accept-any auth) | Caddy 80/443 only. OpenEMR and MariaDB not published |
| Networks | Single default bridge | `frontend` (caddy, openemr), `backend` `internal: true` (openemr, database) |
| Default credentials | Yes (S6) | Random 48-hex per secret, file secrets, mode 600 |
| Xdebug / profiling (PRE-004) | `xdebug.mode=debug,profile`, `start_with_request=trigger`, output `/tmp`, client host `host.docker.internal` | Not configured in compose; `php -m` in the 8.1.1 image shows no xdebug (disposable container). **Refuted for the deployment path** |
| Container user | Apache workers uid 1000 `apache`, master `root` | Same image behavior: Apache master root, workers `apache`; Caddy image `User` unset, so root. **No `user:` override** |
| Capabilities / privileges | Not privileged, default caps | No `cap_drop`, no `security_opt: no-new-privileges`, no `read_only`, no `tmpfs`, no mem/CPU/pids limits |
| Healthchecks | openemr (readyz, PRE-003), mysql, selenium, mailpit | database (connect+innodb), openemr (`/meta/health/livez`); **caddy none** |
| Secrets in env | Plaintext in compose | Entrypoint reads files and then **exports** `MYSQL_ROOT_PASS`, `MYSQL_PASS`, `OE_PASS` into the long-lived PHP/Apache process env (`openemr-entrypoint.sh:16-19`) |
| Host firewall | Unknown (sudo required; not run) | DO Cloud Firewall: 22 from restricted CIDRs, 80/443 world, **egress all** |
| TLS | Self-signed (PRE-005) | Caddy ACME public cert, HSTS; Caddy→OpenEMR plaintext HTTP on the Docker bridge; `admin off` |
| Upgrade/setup scripts | Present (repo mount) | `setup.php`, `admin.php`, `sql_upgrade.php`, `acl_upgrade.php` present in fresh image; runbook says boot removes the upgrade scripts. Manual run-time re-copy documented |

**PRE item verdicts for the deployment path**
- **PRE-001 (exposed admin/data services, default creds):** Confirmed for the dev host (OBSERVED all bindings on 0.0.0.0/[::]; whether the LAN or internet can reach them depends on the host firewall, which was not verified). **Refuted for infra**: only Caddy is published, the DB is on an internal network, and credentials are generated. Residual: the deployed OpenEMR serves static repo artifacts (SEC-HIGH-500).
- **PRE-002 (token-like credentials):** Confirmed. Three distinct GitHub-token-format values are committed in four dev compose files. They are not injected into the deployment env, but they **do reach the public deployment as a downloadable file** via the upstream image webroot. Validity unknown by rule.
- **PRE-004 (Xdebug/profiling):** Confirmed on dev (debug+profile, trigger mode on a 0.0.0.0-bound port). **Refuted for infra** (no extension loaded, no env).

## 6. Findings

### SEC-HIGH-500 — Deployed OpenEMR image publicly serves private keys, dev compose credentials, and dependency manifests

- **Status:** Open. **Confirmed live** on the public deployment in the 2026-09-14 cloud window (`evidence/security/cloud-probe-2026-09-14.txt` §1)
- **Severity:** High
- **Observed evidence:** A disposable container of `openemr/openemr:8.1.1@sha256:796adaa7…` was started with `--network none`. Apache ran with a temporary self-signed cert (created only so it would start), and status codes only were checked on `http://localhost/` (the vhost Caddy proxies to, `Caddyfile:16`): `docker/library/sql-ssl-certs-keys/easy/server-key.pem` **200**, `tests/Tests/data/Unit/Common/Auth/Grant/openemr-rsa384-private.key` **200**, `docker/development-easy/docker-compose.yml` **200** (the file contains 3 `GITHUB_COMPOSER_TOKEN` lines), `composer.lock` **200**, `sites/default/documents/` 403. Apache config in the image denies only `sites/*/documents` and `bin` (`/etc/apache2/conf.d/openemr.conf:93-131`). Same 200 results on the running dev stack (`https://127.0.0.1:9300`). Trivy reported 84 secret-scanner private-key hits in the image.
- **Affected assets/users:** Anyone on the internet who can reach the public hostname. Assets: S1 token-like values, S2 dev CA/server/client keys, S3 test JWT key, and exact dependency versions for exploit targeting.
- **Threat scenario:** An unauthenticated attacker requests well-known repo paths through Caddy. They harvest possibly-valid GitHub tokens and keys, and use `composer.lock`/`package.json` to fingerprint vulnerable versions (§2.3). If a future build reuses any `docker/library` key for real TLS/DB auth, it is already public.
- **Impact:** Credential disclosure (validity unknown). Precise vulnerability fingerprinting of a PHI system. Reputational/compliance exposure if found by a scanner.
- **Likelihood/assumptions:** High likelihood of discovery (paths are public in the upstream GitHub repo). Impact of the keys is INFERRED limited today because they are dev fixtures and not used by infra.
- **Recommendation:** At Caddy, allowlist the paths OpenEMR needs, or deny `/docker/*`, `/tests/*`, `/ci/*`, `/contrib/*`, `/Documentation/*`, `/swagger/*` (unless the API docs are intended), `/*.lock`, `/*.json` at the root, `/*.md`, `/*.yml`, `/*.xml`, `/bin/*`, `/setup.php`, `/admin.php`, `/sql_upgrade.php`, `/acl_upgrade.php`. In the project-owned image, delete `docker/`, `tests/`, `ci/`, `contrib/`, dev tooling, and `/tmp/openemr` layers (multi-stage build, not `rm` in a later layer). Add a `.dockerignore`.
- **Verification:** `smoke.sh` extension: `curl -s -o /dev/null -w '%{http_code}' https://$HOST/docker/development-easy/docker-compose.yml` (and the key/test/lock paths) must return 403/404. `trivy image --scanners secret` on the project image must report 0 private keys.
- **Architecture consequence:** Caddy is the right control point for a deny-by-default path policy. The co-pilot's routes must be explicitly allowlisted there too.
- **Deployment response status (2026-09-16):** Done for our edge and image. `infra/digitalocean/runtime/Caddyfile` is deny-by-default (only `/`, `index.php`, `controller.php`, `/interface/*`, `/public/*`, `/library/*`, `/sites/*/images/*`, `/meta/health/livez` reach Apache; `/copilot-api/*` goes to the agent; the module's gateway and CLI paths return 404). Probe on 2026-09-15 against the deployment: 14 of 15 sensitive paths 404 (`interface/main/backup.php` answers 400, because `/interface/*` is an allowlisted application path handled by OpenEMR's own auth), all 5 API/OAuth paths 404, `sites/default/documents/` 404 (`evidence/security/cloud-probe-2026-09-15-allowlist.txt`). The project image adds only the module to the pinned base and the root `.dockerignore` excludes everything else. Not done: `trivy image --scanners secret` on the project image, and a `smoke.sh` assertion for these paths. The upstream image contents are unchanged behind the allowlist.

### SEC-HIGH-501 — GitHub-token-format credentials committed in dev compose files (PRE-002)

- **Status:** Open
- **Severity:** High (until validity is established; downgrade to Low if confirmed revoked)
- **Observed evidence:** §4 S1. Three distinct values (fingerprints `ae8ed247`, `fafe95dc`, `be8fa6f1`) across 4 compose files × 3 lines. Consumed by `docker/flex/openemr.sh:766-790`. Present in the upstream image and served publicly (SEC-HIGH-500).
- **Affected assets/users:** The GitHub account that owns the tokens (INFERRED upstream OpenEMR maintainers or a bot). Composer installs in dev containers.
- **Threat scenario:** Someone who reads the repo or downloads the served file decodes the base64/decimal encodings and uses the tokens for GitHub API quota or, if scoped, repo access. Obfuscation defeats GitHub push protection, so revocation may never have happened.
- **Impact:** Unknown scope, possibly none (classic PATs with no scopes are commonly used only for API rate limits). This fork re-publishes them.
- **Likelihood/assumptions:** Not tested by rule. INFERRED intentionally low-privilege, rate-limit-only tokens.
- **Recommendation:** Remove from all compose files in the fork and use `${GITHUB_COMPOSER_TOKEN:-}` from an untracked `.env`. Notify upstream/security@open-emr.org to confirm scope and revoke. Never pass these to any deployment env.
- **Verification:** `git grep -n GITHUB_COMPOSER_TOKEN -- 'docker/**/docker-compose.yml'` shows only variable references. The fingerprint classifier in `COMMANDS.txt` finds no literals.
- **Architecture consequence:** Establishes the policy that the co-pilot LLM key must never live in compose files, image layers, or the webroot (see §8).
- **Status (2026-09-16):** Unchanged in the fork: the three token lines are still present in all four dev compose files (`git grep -c GITHUB_COMPOSER_TOKEN` = 3 each). They are not in the deployment environment, and the served path is now 404 behind the Caddy allowlist (SEC-HIGH-500 status). No removal, revocation, or upstream notification is recorded in this repository. The LLM key policy is followed: `anthropic_api_key` is a Compose file secret mounted only into the agent (`runtime/compose.yaml`).

### SEC-HIGH-502 — Internet-facing and application images carry fixable Critical/High CVEs; deployed PHP vendor tree lags the repo

- **Status:** Open
- **Severity:** High
- **Observed evidence:** §2.3. Caddy 2.10.2: 6 Critical/77 High, all fixable, including 7 High in Caddy itself fixed in 2.11.x and Go crypto/tls Critical. OpenEMR 8.1.1: 8 Critical/226 High (twig 3.24.0 ×6 Critical, apache2 2.4.67, curl, node tar), 223 of 226 High fixable. MariaDB: gosu Go stdlib Critical. The dev MariaDB digest differs from infra for the same tag.
- **Affected assets/users:** Public edge (Caddy), the application tier, all users and PHI.
- **Threat scenario:** Remote attacker exploits a Caddy/HTTP2/TLS parsing bug at the edge, or an Apache httpd buffer-overflow CVE on the proxied vhost.
- **Impact:** Edge compromise can mean TLS key theft and traffic interception of PHI; DoS of the EHR.
- **Likelihood/assumptions:** INFERRED moderate. Many CVEs are in modules not enabled (e.g., mod_proxy_html, Windows-only Caddy file_server). Exploitability per CVE was not validated.
- **Recommendation:** Bump Caddy to the latest 2.11.x digest. Build a project-owned OpenEMR image from this repo's patched lock on a current Alpine base. Re-pin MariaDB to a current 11.8 digest shared by dev and infra. Add `trivy image --severity CRITICAL,HIGH --ignore-unfixed --exit-code 1` to CI for every pinned digest, and renew pins on a schedule.
- **Verification:** Re-run the Trivy commands in `COMMANDS.txt`: 0 fixable Critical and a documented, reviewed High exception list.
- **Architecture consequence:** The co-pilot image must be built and pinned the same way (digest plus CI scan gate), not pulled as `:latest`.
- **Status (2026-09-16):** Documented, not fixed. `runtime/compose.yaml` still pins `caddy:2.10.2-alpine@sha256:4c6e91c6…`, `mariadb:11.8.8@sha256:24e76fce…`, and the `openemr/openemr:8.1.1@sha256:796adaa7…` base for the project image. `.gitlab-ci.yml` runs whitespace, PHP, Caddy, and Compose lint, the agent tests, and the offline and manual live evals; there is no Trivy or secret-scan job. The agent image is built locally on the Droplet by `start.sh` and is not digest-pinned.

### SEC-MEDIUM-503 — Deployment containers run with default privileges and the app process holds the DB root password

- **Status:** Open
- **Severity:** Medium
- **Observed evidence:** `compose.yaml` has no `user`, `cap_drop`, `read_only`, `security_opt`, or resource limits on any service. Caddy image `User` is empty (root). `openemr-entrypoint.sh:16-19` exports `MYSQL_ROOT_PASS` into the environment inherited by Apache/PHP. The openemr service receives the `mysql_root_password` secret (`compose.yaml:47-50`). `openemr.sh` uses root only for DB setup (`docker/flex/openemr.sh:359,371`). Caddy has no healthcheck. ADR-0001 notes the docker group is host-root.
- **Affected assets/users:** MariaDB (all PHI), Droplet host.
- **Threat scenario:** Any PHP RCE or file-read (e.g., `/proc/self/environ` via an LFI) yields DB root credentials, which allow full database control including the audit `log` table.
- **Impact:** Full PHI read/write plus audit tampering, beyond the `openemr` DB user's grants.
- **Likelihood/assumptions:** Requires a separate app-layer bug. The OpenEMR attack surface is large (§3 counts).
- **Recommendation:** After first install, remove `mysql_root_password` from the openemr service (a one-shot init job, or unset after setup) and do not export it. Add `cap_drop: [ALL]` with minimal `cap_add` (NET_BIND_SERVICE for Caddy), `security_opt: [no-new-privileges:true]`, `read_only: true` + `tmpfs` where feasible (Caddy, and the future agent service), mem/pids limits, and a Caddy healthcheck.
- **Verification:** `docker compose exec openemr sh -c 'cat /proc/1/environ | tr "\0" "\n" | cut -d= -f1'` shows no `MYSQL_ROOT_PASS`. `docker inspect` shows CapDrop ALL and NoNewPrivileges.
- **Architecture consequence:** The agent service holds **no database credentials of any kind** (`AGENTS.md`: the model or agent service never queries the OpenEMR database). Its only data path is the authenticated module gateway inside OpenEMR, called with a short-lived, user- and patient-bound delegation. The gateway runs in the OpenEMR process and therefore uses the existing `openemr` application account; only the LLM and tracing keys are the agent service's secrets, and they are mounted there alone (SEC-MEDIUM-504).
- **Status (2026-09-16):** The agent-side consequence holds in `runtime/compose.yaml`: the `agent` service is on `frontend` only and receives `anthropic_api_key`, `anthropic_workspace_id`, `copilot_delegation_secret`, and the two Langfuse keys, with no MySQL secret; it runs as uid 10001. The OpenEMR container is unchanged: `openemr-entrypoint.sh:19` still exports `MYSQL_ROOT_PASS`, no service has `cap_drop`, `no-new-privileges`, `read_only`, or resource limits, and Caddy still has no healthcheck.

### SEC-MEDIUM-504 — Unrestricted Droplet egress

- **Status:** Open
- **Severity:** Medium (rises once an LLM agent with PHI access is deployed)
- **Observed evidence:** `infra/digitalocean/main.tf:54-69` allows all TCP/UDP/ICMP egress; Trivy DIG-0003 ×3.
- **Affected assets/users:** PHI in MariaDB; future agent prompts and outputs.
- **Threat scenario:** A compromised container, or a prompt-injected agent tool call, exfiltrates PHI to an arbitrary host. SSRF paths (§2.1 Guzzle/Smarty/PhpSpreadsheet classes) have unrestricted destinations.
- **Impact:** PHI breach.
- **Likelihood/assumptions:** INFERRED requires another bug or injection. Egress is needed today for ACME, apt, and image pulls.
- **Recommendation:** Restrict firewall egress to 443/80 (plus DNS 53). In the future agent service, enforce an application-level allowlist (the LLM provider hostname only) using a patched HTTP client that canonicalizes hosts (Guzzle ≥ 7.15.2). Consider an egress proxy.
- **Verification:** `trivy config infra/digitalocean` shows no DIG-0003. From the agent container, a request to a non-allowlisted host fails.
- **Architecture consequence:** The agent should call the LLM through one egress path that can log and enforce destinations.
- **Status (2026-09-16):** Not done. `infra/digitalocean/main.tf` still allows all TCP, UDP, and ICMP egress; no application-level destination allowlist exists in the agent. `docs/deployment/digitalocean.md` records the gap as residual risk.

### SEC-MEDIUM-505 — Dev stack exposes data/admin services on all interfaces with default credentials and Xdebug (PRE-001, PRE-004)

- **Status:** Open (dev workstation only; refuted for deployment)
- **Severity:** Medium (Low if the host firewall blocks inbound; not verified)
- **Observed evidence:** §5 table. 10 ports on 0.0.0.0/[::]: phpMyAdmin 200, Mailpit API 200 unauthenticated, Selenium 200, MariaDB root/root. `xdebug.mode=debug,profile`, `start_with_request=trigger`.
- **Affected assets/users:** Developer machine, any synthetic or demo PHI loaded locally, co-located networks (café/office Wi-Fi).
- **Threat scenario:** A LAN peer connects to 8320 with root/root, or uses phpMyAdmin, and reads or alters the DB. Mailpit reveals password-reset emails. An `XDEBUG_TRIGGER` cookie makes the app attempt debug connections and writes profiles to `/tmp`.
- **Impact:** Local data compromise; possible pivot via Selenium/VNC.
- **Likelihood/assumptions:** Depends on host firewall and network.
- **Recommendation:** Bind dev ports to `127.0.0.1` via `${WT_BIND:-127.0.0.1}:port:port` in a local override. Keep ADR-0001's rule that dev compose never runs on a Droplet. Profile only on demand.
- **Verification:** `ss -ltn` shows 127.0.0.1 bindings only.
- **Architecture consequence:** Performance measurements taken on this dev stack include Xdebug debug+profile overhead and must not be used as production baselines (PRE-004).

### SEC-MEDIUM-506 — Build supply chain: unpinned archive downloads extracted by vulnerable tooling; unpinned scanner

- **Status:** Open
- **Severity:** Medium
- **Observed evidence:** `package.json:112-121` `napa` fetches 8 remote archives (GitHub tag/commit archives, jqueryui.com, clinicaltables.nlm.nih.gov) with no integrity hashes. `npm audit`: `napa` High, `tar` Critical, `decompress` Critical (Zip Slip). `run-semgrep.sh` uses `semgrep/semgrep:latest`. Runtime npm moderates: DOMPurify 3.4.11 bypasses (portal messaging).
- **Affected assets/users:** Future project image build; patient-portal users (DOMPurify).
- **Threat scenario:** A compromised or MITM'd archive host writes files outside `node_modules` during `npm install`, or ships malicious JS that becomes part of the served front end.
- **Impact:** Code execution in the build and malicious JS served to clinicians (session/PHI theft).
- **Likelihood/assumptions:** Low probability, high impact. TLS protects transport but not upstream compromise.
- **Recommendation:** Vendor or hash-pin napa archives (or replace them with npm packages). Update `tar`/`decompress` via overrides. Upgrade DOMPurify to ≥ 3.4.13. Pin the semgrep image digest. Build images in CI with `npm ci --omit=dev` output copied into a clean runtime stage.
- **Verification:** `npm audit --omit=dev` shows 0 moderate+ (or documented exceptions); `npm audit` shows 0 critical. `grep -n 'semgrep/semgrep@sha256' run-semgrep.sh`.
- **Architecture consequence:** The co-pilot's own dependencies need lockfile, integrity, and scan gates from day one.
- **Status (2026-09-16):** Unchanged. `run-semgrep.sh:136` still uses `semgrep/semgrep:latest`; `napa` archives are not pinned; no scan gate in `.gitlab-ci.yml`.

### SEC-LOW-507 — Vulnerable prod PHP libraries in repo lock (Guzzle host bypass, dompdf file read, Smarty SSRF, PhpSpreadsheet)

- **Status:** Open
- **Severity:** Low today (reachability limited; see §2.1). Medium for any new code using Guzzle host allowlists.
- **Observed evidence:** `composer-audit.json`: 5 High (4 prod, 1 dev), 13 Medium, 2 Low. Dompdf used at `interface/modules/zend_modules/module/Carecoordination/src/Carecoordination/Model/EncountermanagerTable.php:201` to render C-CDA XSL output to PDF with default options. INFERRED the SVG/data-URI local file read is reachable if an imported C-CDA injects SVG into the HTML, but this was not tested.
- **Affected assets/users:** Care-coordination C-CDA import/view users; outbound HTTP integrations.
- **Threat scenario:** A malicious inbound C-CDA with embedded SVG makes dompdf read local files (e.g., `sqlconf.php`) into a generated PDF.
- **Impact:** Server file disclosure (DB credentials).
- **Likelihood/assumptions:** Requires C-CDA import by an authenticated user; not exploited or tested.
- **Recommendation:** `composer update guzzlehttp/guzzle guzzlehttp/psr7 dompdf/dompdf smarty/smarty phpoffice/phpspreadsheet squizlabs/php_codesniffer`, run tests, then include in the project image.
- **Verification:** `composer audit --locked` shows 0 High/Medium for these packages.
- **Architecture consequence:** None beyond the image rebuild in SEC-HIGH-502.

### SEC-LOW-508 — No `.dockerignore`; local Terraform artifacts world-readable in working tree

- **Status:** Open
- **Severity:** Low
- **Observed evidence:** `.dockerignore` absent. `infra/digitalocean/terraform.tfstate*`, `deploy.tfplan`, `terraform.tfvars` are mode 0644 with no secrets (§4 S8) and are gitignored (`.gitignore:8-14`) and untracked.
- **Affected assets/users:** Operator IP, droplet metadata; future image contents.
- **Threat scenario:** A future `docker build .` for the project image copies tfstate, tfvars, `docs/audit/evidence`, dev keys, and the dev compose files into an image layer.
- **Impact:** Info disclosure. It becomes secret disclosure once state ever holds sensitive attributes (e.g., a DO token or DB password added to Terraform later).
- **Likelihood/assumptions:** Low today (no secrets in state, files untracked). Certain to matter the first time a project image is built from the repository root, which §7.2 of `AUDIT.md` plans.
- **Recommendation:** Add a `.dockerignore` (`.git`, `infra/`, `docker/`, `tests/`, `ci/`, `docs/`, `*.tfstate*`, `*.tfvars`, `*.tfplan`, `.env*`, `node_modules`). `chmod 600` the local state. Keep application secrets out of Terraform (current design is correct).
- **Verification:** `docker build` context listing excludes these paths; image `trivy --scanners secret` is clean.
- **Architecture consequence:** Supports SEC-HIGH-500 remediation.
- **Status (2026-09-16):** `.dockerignore` added at the repository root in allow-list form (`*` excluded, only `interface/modules/custom_modules/oe-module-copilot/` included), so a root build context carries nothing but the module. The local Terraform artifacts are still mode 0644 (`terraform.tfstate`, `deploy.tfplan`) and 0664 (`terraform.tfvars`), still untracked.

### SEC-INFO-509 — Semgrep baseline: 594 unreviewed results; sampled results are false positives

- **Status:** Accepted as baseline (triage pending)
- **Severity:** Informational
- **Observed evidence:** §3. 10/10 verified samples were false positives or mitigated. One fragile pattern: unquoted `IN()` with `add_escape_custom` in `custom/qrda_functions.php:37,42,108`.
- **Affected assets/users:** OpenEMR application code as a whole; indirectly every user, if any of the 584 untriaged results is real.
- **Threat scenario:** A real injection or XSS hides among the untriaged results and is reachable on the public deployment.
- **Impact:** Unknown until triaged; the sampled results suggest low.
- **Likelihood/assumptions:** Low per result (0/10 sampled were real) but not zero across 584. Triage is out of scope: OpenEMR is documented, not fixed.
- **Recommendation:** Store `semgrep-raw.json` as a baseline, gate CI on *new* ERROR findings only, and prioritize review of `library/ajax` echoed-request and CCR/CCDA `disable-output-escaping` XSL.
- **Verification:** A CI job diffs results against the baseline.
- **Architecture consequence:** Any co-pilot UI rendering C-CDA/clinical text must encode output and not rely on legacy XSL viewers.

## 7. Not run / limitations

- Host firewall state (ufw/nft) needs sudo; not checked. PRE-001 internet/LAN reachability of dev ports is therefore INFERRED.
- GitHub token validity and scope: not tested (by rule).
- The deployed Droplet was destroyed; deployment checks used the pinned image in a disposable network-less container plus the committed compose/Terraform config, not a live host.
- Trivy has no docker-compose misconfiguration rules; compose review was manual.
- Semgrep: ~584 results unreviewed. Registry rulesets are fetched at scan time (`:latest` image), so results may drift between runs.
- CVE exploitability per image package was not validated; counts are scanner output.

## Top findings for the executive summary

1. **SEC-HIGH-500:** The public deployment would serve dev/test private keys, the dev compose file containing GitHub-token-format values, and `composer.lock` to unauthenticated users. Verified against the exact pinned 8.1.1 image; Caddy proxies every path.
2. **SEC-HIGH-501 (PRE-002 confirmed):** Three GitHub-token-format credentials are committed (obfuscated via base64/decimal) in four dev compose files. Not injected into deployment env, but reachable through #1. Validity unknown; remove and request revocation.
3. **SEC-HIGH-502:** The internet-facing Caddy 2.10.2 (6 Critical/77 High, all fixable) and upstream OpenEMR 8.1.1 (8 Critical/226 High, including Twig 3.24.0 while the repo lock has the patched 3.27.1) are stale. The deployed code is not built from this repo.
4. **SEC-MEDIUM-503:** No container hardening. The OpenEMR PHP process keeps the MariaDB root password in its environment.
5. **PRE-001/PRE-004:** Confirmed on the dev stack (10 services on 0.0.0.0, default creds, Xdebug debug+profile) and **refuted for the deployment path** (only Caddy published, internal DB network, generated secrets, no Xdebug).

## Architecture consequences

- **LLM API key location:** Generate or place it on the Droplet as a compose file secret (e.g., `runtime/secrets/llm_api_key`, mode 600, covered by the existing `.gitignore:14`), mounted **only** into the agent service. Read it from `/run/secrets/…` in code at call time; do not export it to the process env and never pass it through OpenEMR, Caddy, cloud-init, Terraform variables/state, image layers, or the webroot. Use a provider key scoped to one project with a spend cap, and rotate on every redeploy of the evaluator environment. Redact it from logs and traces.
- **Agent isolation:** Run the agent as a separate container on its own network. It reaches OpenEMR via the internal HTTP API (FHIR/REST with a read-only OAuth2 client and scopes), not by joining `backend`, and never gets DB credentials. If direct DB reads are unavoidable, create a dedicated SELECT-only MariaDB user on specific tables.
  *Status 2026-09-16:* superseded in one respect by ADR-0003: the agent reaches OpenEMR through the module's tool gateway over the internal Docker network with a per-turn delegation token, not through FHIR/REST with an OAuth2 client. The rest holds: separate container, `frontend` network only, no DB credentials of any kind, no direct DB reads.
- **Egress:** The agent is the only component that needs the LLM endpoint. Restrict Droplet egress (SEC-MEDIUM-504) and enforce an in-app destination allowlist with a patched HTTP client.
- **Edge policy:** Make Caddy deny-by-default for non-application paths (SEC-HIGH-500) and add explicit routes for the co-pilot UI/API. Consider adding `-X-Powered-By` and a CSP.
- **Image supply chain:** Build project-owned OpenEMR and agent images from this repo's lockfiles in a multi-stage build with `.dockerignore`, pin by digest, and gate on Trivy (Critical/High fixable) and secret scans. Share one digest per component between dev and infra.
- **Least privilege at runtime:** `cap_drop: ALL`, `no-new-privileges`, `read_only` + tmpfs, resource limits, non-root user for the agent, and removal of DB root credentials from the app container after install.
- **Measurement hygiene:** Do not use dev-stack latency (Xdebug profile mode) as a performance baseline for the co-pilot.

## Addendum: cloud window (2026-09-14)

The Droplet was re-provisioned for about 8 minutes after this track completed. Confirmed live:

- SEC-HIGH-500: public HTTP 200 for the dev TLS private key, the test JWT private key, the dev `docker-compose.yml`, and `composer.lock`.
- SEC-MEDIUM-503: no container hardening; `MYSQL_ROOT_PASS` present in the Apache parent process environment.
- PRE-001/PRE-004 refuted for the deployment: only 80/443 published; Xdebug not loaded.

See `evidence/dependencies/lead-spot-check.md` and `evidence/security/cloud-runtime-2026-09-14.md`. Statements above saying the Droplet was unavailable describe the state during this track's run.
