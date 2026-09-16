# Lead Auditor Spot-Check of Dependencies/Secrets Track Claims

Date: 2026-09-14. Commit `fc95374`. Local `development-easy` stack.
Status codes and byte counts only. No file contents were retrieved into this
record.

| Claim | Result | Evidence |
| --- | --- | --- |
| Apache serves repository files that should never be web-reachable (SEC-HIGH-500) | **Confirmed on local stack** | `curl -s -o /dev/null -w "%{http_code} %{size_download}"` against `http://localhost:8300/`: `docker/development-easy/docker-compose.yml` → **200, 8117 B**; `composer.lock` → **200, 723545 B**; `.env.example` → **200, 279 B**. The pinned 8.1.1 image result (private keys 200) is the track's disposable-container observation and was not re-run here. |
| Deployment proxies all paths to that vhost | **Confirmed (config)** | `infra/digitalocean/runtime/Caddyfile:16` is a bare `reverse_proxy openemr:80` with no `path`/`handle` matcher or deny rules, so every path the image's Apache serves is publicly reachable. Not live-tested because the Droplet is destroyed; include in the cloud-window probe. |

| **Live public deployment** serves those files (cloud window 2026-09-14) | **Confirmed live** | Through Caddy with Let's Encrypt TLS on the upstream 8.1.1 image: `docker/development-easy/docker-compose.yml` 200 (7,215 B), `docker/library/sql-ssl-certs-keys/easy/server-key.pem` 200 (1,675 B), `tests/…/openemr-rsa384-private.key` 200 (3,272 B), `composer.lock` 200; `sites/default/documents/` 403. See `../security/cloud-probe-2026-09-14.txt` §1. |
| OpenEMR process holds the DB root password in its environment (SEC-MEDIUM-503) | **Confirmed for the Apache parent (root); workers INFERRED** | `MYSQL_ROOT_PASS` (name only) is present in container PID 1 environ, exported by `infra/digitalocean/runtime/openemr-entrypoint.sh:16-19`. `apache` worker environ was unreadable even as container root. See `../security/cloud-runtime-2026-09-14.md`. |

Architecture consequence retained for synthesis: the deployed image must be
project-built with a document root allowlist (or a Caddy path allowlist)
before any agent service or secret is added to the Droplet.

Superseded for the exposure claim (not for the measurements above):
`../security/cloud-probe-2026-09-15-allowlist.txt` (2026-09-15, commit
`06d1855`) shows HTTP 404 for the same paths after the Caddy deny-by-default
allowlist and the project image were deployed. The 2026-09-14 results stand as
the pre-fix baseline.
