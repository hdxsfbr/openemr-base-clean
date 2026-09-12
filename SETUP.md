# Local Development Setup

## Current Status

The OpenEMR easy-development stack was verified locally on September 11, 2026.
All seven services started successfully, the login flow accepted the seeded
administrator credentials, and OpenEMR, phpMyAdmin, and Mailpit returned HTTP
200 responses.

Realistic challenge-specific sample patient data is not yet loaded. Stage 1 of
the PRD remains incomplete until the demo cohort and its repeatable seed process
are added.

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
- The existing readiness endpoint returns `setup_required` in its body after a
  successful installation, while the Docker health check accepts the HTTP 200
  response. This must be recorded in the audit and corrected or replaced for
  the agent deployment.

## Remaining Setup Work

- [ ] Define and seed realistic demo patients covering happy, incomplete,
      conflicting, and access-controlled scenarios.
- [ ] Add an automated smoke test for login and required dependencies.
- [ ] Select and document the deployment environment.
- [ ] Create a production-oriented compose/deployment configuration.
- [ ] Add secret management, real TLS, restricted networks, backups, and
      rollback instructions.
- [ ] Fold the final concise setup path into the root `README.md`.
