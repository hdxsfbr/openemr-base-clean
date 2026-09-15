# Baseline Page Latency — Local Development Stack

Date: 2026-09-14 (≈23:07 UTC). Commit `fc95374`.
Script: `docs/audit/scripts/page-timing.sh http://localhost:8300 20 1`, run as
the local dev admin. Sequential requests (concurrency 1). Nothing else was
using the stack; all audit tracks had finished.

## Environment caveats (read before comparing)

- The `development-easy` stack is **not representative of production**: Xdebug
  is loaded (`xdebug.mode=debug,profile`, `start_with_request=trigger`; see
  `dependencies-secrets.md`), the repository is bind-mounted, Apache is prefork,
  and the host is a 31 GiB workstation, not the 2 vCPU / 4 GiB Droplet.
- The data is tiny: pid 1 has 1 encounter and 5 issues. Latency with realistic
  chart sizes is **unmeasured**.
- Results are from the loopback interface with no TLS and no Caddy hop.

## Idle container baseline (before the run)

| Container | CPU | Memory |
| --- | --- | --- |
| development-easy-openemr-1 | 0.24% | 332.6 MiB |
| development-easy-mysql-1 | 0.01% | 229.2 MiB |

## Results (n=20 each)

| Page | p50 ms | p95 ms | max ms | Bytes | HTTP |
| --- | ---: | ---: | ---: | ---: | --- |
| Patient dashboard (`demographics.php?set_pid=1`) | 359.5 | 395.8 | 498.8 | 155,535 | 200 |
| Encounter history (`history/encounters.php`) | 127.0 | 151.1 | 203.1 | 9,826 | 200 |
| Login page | 130.2 | 138.7 | 141.9 | 8,846 | 200 |
| `/meta/health/readyz` | 85.4 | 94.0 | 100.7 | 136 | 200 |

## Database statements per dashboard load

Method: `SHOW GLOBAL STATUS` (`Questions`, `Com_*`) read immediately before
and after a single authenticated
`GET demographics.php?set_pid=1`, repeated 3 times after one warm-up load.
The stack was otherwise idle. No server settings were changed. Each window
also includes about 1–2 statements from the status probe itself.

| Run | Δ Questions | Δ Com_select | Δ Com_insert | Δ Com_update | Δ Com_delete |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 1,047 | 886 | 7 | 1 | 0 |
| 2 | 1,047 | 886 | 7 | 1 | 0 |
| 3 | 1,047 | 886 | 7 | 1 | 0 |

**OBSERVED:** About 1,045 statements, 886 of them SELECTs, run for one dashboard
render of a chart with 1 encounter and 5 issues. The count is deterministic
across runs. The 7 INSERTs per view are audit-log and session-tracking writes
(`view`/`http-request` events seen in `log`). Their source breakdown is
pending a short general-log capture.

## Public deployment comparison (cloud window, 2026-09-14 ≈23:40 UTC)

DigitalOcean `s-2vcpu-4gb` in sfo3 running upstream `openemr/openemr:8.1.1`
behind Caddy 2.10.2 with Let's Encrypt TLS. Measured from the auditor's
workstation over the public internet (`docs/audit/scripts/cloud-probe.sh`, §6),
n=20 sequential, **unauthenticated** pages only. Numbers include the WAN round
trip and TLS. Source: `../security/cloud-probe-2026-09-14.txt`.

| Page | p50 ms | p95 ms | TTFB p50 ms | HTTP |
| --- | ---: | ---: | ---: | --- |
| Login page | 158.8 | 187.2 | 158.8 | 20× 200 |
| FHIR `metadata` (35.8 KB capability statement) | 689.2 | 1,023.3 | 674.7 | 20× 200 |
| `/meta/health/readyz` | 124.9 | 138.3 | 123.6 | 20× 200 |

- **OBSERVED:** The login page costs about 30 ms more than local, the WAN/TLS
  overhead. `readyz` is about 40 ms slower.
- **OBSERVED:** FHIR `metadata` p95 is about 1 s on the Droplet. It is
  generated per request (TTFB ≈ total), so the FHIR layer has a high fixed
  cost per call. This is another reason agent tools should not fan out through
  the HTTP FHIR API.
- **Not measured on the Droplet:** authenticated dashboard latency and service
  timings. The demo cohort was not loaded in this window, because the upgrade
  step requires the manual workaround in `docs/deployment/digitalocean.md`.

## Observations

- **OBSERVED:** The chart dashboard (≈360 ms p50) is the slowest page tested
  even on a near-empty chart. It returns ≈155 KB of HTML because every card is
  server-rendered in one request.
- **OBSERVED:** `readyz` costs ≈85 ms because it bootstraps the full framework
  on every probe (`meta/health/index.php` comment). A 10 s probe interval is
  negligible; a 1 s interval is not.
- **INFERRED:** Screen-scraping or reusing the dashboard render path for agent
  tools would add ≈0.4 s before any model call. Tools should call narrow
  services directly and fetch in parallel.
- p99 is not reported; n=20 is too small. The 10/50-concurrent load tests
  required by the PRD are a later deliverable against the deployed agent.
