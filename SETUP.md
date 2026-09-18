# Local Development Setup

## Current Status

The OpenEMR easy-development stack was verified locally on September 11, 2026.
All seven services started successfully, the login flow accepted the seeded
administrator credentials, and OpenEMR, phpMyAdmin, and Mailpit returned HTTP
200 responses. The bundled OpenEMR demo database was also loaded and upgraded
successfully to OpenEMR 8.2.0-dev (database revision 541 and ACL revision 13).

The bundled database provides a baseline for learning OpenEMR. On September 14,
2026 the deterministic synthetic cohort `af-cohort-v1` was added on top of it:
26 fictional patients, 50 encounters, 134 lab results, and 67 notes. Two
consecutive loads produced identical row checksums. See
[Load the Synthetic Cohort](#load-the-synthetic-cohort).

The co-pilot module (`interface/modules/custom_modules/oe-module-copilot/`)
is registered in the local stack with the CLI script below; the panel then
renders at the top of every patient dashboard.

## Prerequisites

- Git
- Docker Engine
- Docker Compose v2
- Sufficient disk space for the OpenEMR, MariaDB, Selenium, CouchDB, LDAP,
  phpMyAdmin, and Mailpit images

Node.js 24 is required for a host-side source build, but the development
container performs the Composer and frontend setup needed by this workflow.
Host PHP and Composer are not required.

## Start the Stack

From the repository root:

```bash
cd docker/development-easy
HOST_UID="$(id -u)" HOST_GID="$(id -g)" docker compose up -d
```

Watch the first-time initialization:

```bash
docker compose logs -f openemr
```

The first boot downloads large images, installs dependencies, builds themes,
initializes MariaDB, and seeds the administrator. Later starts reuse named
volumes and are substantially faster.

## Load the Built-In Demo Database

Use the bundled OpenEMR demo database to explore populated patient charts,
encounters, appointments, users, and access controls. **This command drops and
recreates the current OpenEMR database and removes uploaded files. Do not run it
against an environment containing data that must be preserved.**

From the repository root:

```bash
docker compose -f docker/development-easy/docker-compose.yml \
  exec -T openemr /root/devtools dev-reset-install-demodata
```

The command imports the OpenEMR 5.0.0.5 demo dump, runs the application's schema
and ACL upgrades through the checked-out version, populates missing UUIDs and
configuration defaults, and converts the database to `utf8mb4`. Restart CouchDB
after the reset as required by the development tooling:

```bash
docker compose -f docker/development-easy/docker-compose.yml restart couchdb
```

Verify the migrated database and baseline record counts:

```bash
docker compose -f docker/development-easy/docker-compose.yml exec -T mysql \
  mariadb -uopenemr -popenemr openemr -e \
  "SELECT * FROM version; \
   SELECT COUNT(*) AS patients FROM patient_data; \
   SELECT COUNT(*) AS encounters FROM form_encounter; \
   SELECT COUNT(*) AS appointments FROM openemr_postcalendar_events;"
```

The verified September 11, 2026 load produced 3 patients, 3 encounters, and 11
calendar events. These counts describe the pinned development image's bundled
baseline, not the final challenge evaluation dataset.

## Create the Audit Test Users

The access-control tests and the synthetic cohort expect three low-privilege
accounts in addition to the bundled `physician` user. Create them in the UI as
`admin`: **Admin → Users → Add User**.

| Username | Access Control group | Provider |
| --- | --- | --- |
| `audit-physician` | Physicians | checked |
| `audit-nurse` | Clinicians | unchecked |
| `audit-frontdesk` | Front Office | unchecked |

Use unique local passwords and never commit them. If you script user creation
instead of using the form, also set `groupname=Default`. Without it OpenEMR
rejects the login with "user not found in a group"
(`src/Common/Auth/AuthUtils.php:350-359`).

Verify:

```bash
docker compose -f docker/development-easy/docker-compose.yml exec -T mysql \
  mariadb -uopenemr -popenemr openemr -e \
  "SELECT u.username, g.name AS acl_group FROM users u JOIN gacl_aro a ON a.value = u.username JOIN gacl_groups_aro_map m ON m.aro_id = a.id JOIN gacl_aro_groups g ON g.id = m.group_id WHERE u.username LIKE 'audit-%';"
```

## Enable the Co-Pilot Module

The module ships with the repository (bind-mounted into the dev container).
Register and enable it, and create its table, without the Module Manager UI:

```bash
docker exec development-easy-openemr-1 sh -c 'cd /var/www/localhost/htdocs/openemr && su -s /bin/sh apache -c "php interface/modules/custom_modules/oe-module-copilot/bin/register_module.php"'
```

The script is idempotent and returns 404 over HTTP. Reload a patient
dashboard to see the "Clinical Co-Pilot" card; locally there is no edge, so
its status line reports the agent as unreachable until the agent runs and a
proxy publishes it at `/copilot-api`.

On a fresh local database without the audit users, create them with the same
script the deployment uses (the password file is never printed):

```bash
docker exec development-easy-openemr-1 sh -c 'cd /var/www/localhost/htdocs/openemr && printf "%s" "choose-a-local-password" > /tmp/demo_pw && su -s /bin/sh apache -c "DEMO_USER_PASSWORD_FILE=/tmp/demo_pw php evals/fixtures/cohort/seed_users.php --confirm-dev-data"; rm -f /tmp/demo_pw'
```

## Load the Synthetic Cohort

After the demo database is loaded and the audit test users exist, load the
deterministic synthetic cohort used by the audit and evals. It writes only
fictional patients (pids `900001–900099`, `pubpid` `AF-*`) and is safe to
re-run; each run replaces the previous cohort.

```bash
docker exec development-easy-openemr-1 sh -c 'cd /var/www/localhost/htdocs/openemr && su -s /bin/sh apache -c "php evals/fixtures/cohort/seed_cohort.php --confirm-dev-data --anchor=2026-09-14"'
```

The command prints a JSON manifest and exits non-zero if a post-load check
fails. Patient scenarios, guarantees, and side effects are documented in
[`evals/fixtures/cohort/README.md`](evals/fixtures/cohort/README.md).

## Run the Agent and the Evals

The agent service is a separate Python process; [`agent/README.md`](agent/README.md)
documents the venv, `pytest` (60 tests), and the environment variables that
point a local agent at the dev stack's gateway. The eval suite is documented
in [`evals/README.md`](evals/README.md); the offline subset needs no stack or
model key and is what CI runs on every push:

```bash
cd agent && python -m venv .venv && .venv/bin/pip install -e '.[dev]' && cd ..
agent/.venv/bin/python -m pytest -q agent/tests
agent/.venv/bin/python evals/run.py --offline-only
```

Live cases (`--golden-only` for the 14-case smoke set, or a full run) drive a
deployment through the same login handshake as the panel and need the demo
clinician password in `DEMO_PASSWORD`; see `evals/README.md`, "Running".

## Local Services

| Service | URL or address | Development credentials |
| --- | --- | --- |
| OpenEMR HTTP | <http://localhost:8300> | `admin` / `pass` |
| OpenEMR HTTPS | <https://localhost:9300> | `admin` / `pass` |
| phpMyAdmin | <http://localhost:8310> | `openemr` / `openemr`; server `mysql` |
| MariaDB | `localhost:8320` | `openemr` / `openemr`; database `openemr` |
| Mailpit | <http://localhost:8025> | None for local UI |
| Selenium | <http://localhost:4444> | See development compose configuration |

The local HTTPS certificate is self-signed and is expected to generate a browser
warning.

## Check Status

```bash
cd docker/development-easy
docker compose ps
curl --insecure https://localhost:9300/meta/health/livez
```

## Stop or Reset

Stop containers while preserving the database and dependency volumes:

```bash
docker compose down
```

Delete the development data and force a clean rebuild only when intentionally
resetting the environment:

```bash
docker compose down -v
```

## Known Development-Environment Risks

The easy-development stack is not suitable for public deployment:

- It exposes the database, phpMyAdmin, CouchDB, Mailpit, Selenium, and VNC ports.
- It uses default application and database credentials.
- It enables development tooling, Xdebug, and profiling.
- It contains token-like credentials in compose configuration that must not be
  reused in deployed infrastructure.
- `/meta/health/readyz` returns HTTP 200 with `setup_required` on a working
  install, because `library/sql.inc.php:59` overwrites the global `$config`
  that `InstallationCheck` reads. Exceptions also return 200 with their
  message. This was confirmed locally and on the public deployment
  (`AUDIT.md` SEC-MED-007). Do not use it as a readiness gate.
- The repository is the web root. Any file in it, including `docker/`, `tests/`,
  `evals/`, and `docs/`, is served over HTTP unless blocked (`AUDIT.md`
  SEC-HIGH-500). The audit and seed PHP scripts return 404 to web requests.

## Remaining Setup Work

- [x] Load and verify OpenEMR's bundled demo database for application discovery.
- [x] Define and seed realistic demo patients covering happy, incomplete,
      conflicting, and access-controlled scenarios (`evals/fixtures/cohort/`).
- [x] Add an automated smoke test for login and required dependencies
      (`infra/digitalocean/smoke.sh` for TLS and OpenEMR liveness; the Bruno
      collection's folder 1 and `evals/run.py` live cases log in through the
      same handshake as the panel; `/copilot-api/ready` checks the gateway,
      model, tracer keys, delegation secret, and state store).
- [x] Select and document the initial DigitalOcean deployment environment.
- [x] Create a production-oriented Compose and Terraform configuration.
- [x] Add secret management, real TLS, and restricted networks (file secrets,
      Let's Encrypt via Caddy, internal database network, agent on the
      frontend network only). Backups and rollback instructions remain.
- [ ] Add backups and rollback instructions.
- [ ] Fold the final concise setup path into the root `README.md`.

## Public Deployment Baseline

The initial DigitalOcean topology, cost-controlled smoke cycle, teardown rules,
and known limitations are documented in
[`docs/deployment/digitalocean.md`](docs/deployment/digitalocean.md). It was
provisioned and externally verified on September 14, 2026 (public TLS smoke
test, demo data loaded), re-provisioned the same evening for the audit's
public probe, and destroyed after each of those runs to control cost. What is
live at `https://openemr-137-184-4-22.sslip.io` today is commit `e1dd331`, tag
`week1`, deployed September 16, 2026 (health and readiness confirmed that day;
no runtime directory changed between `831e1d8` and `e1dd331`). The older
`v0.2.0-slice` tag served the deployment from September 15 and is no longer
what is deployed; no image digest has been recorded for the current deploy.
The deployment runs the project's own OpenEMR image carrying the co-pilot
module, behind a deny-by-default Caddy path allowlist; the audit required both
before an evaluator deployment (`AUDIT.md` SEC-HIGH-500; runbook sections
"Current Deployment" and "Before the Evaluator Deployment"). Still open there:
an owned hostname, backups and a rollback rehearsal, and restricting the
agent's egress to the model and tracer endpoints. GitLab CI runs on a separate
runner Droplet (`infra/digitalocean/runner/`, runbook section "CI Runner").
