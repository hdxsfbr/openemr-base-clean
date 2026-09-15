# ADR-0001: Ephemeral Single-Droplet Baseline on DigitalOcean

- **Status:** Accepted for baseline smoke testing; externally verified live on
  2026-09-14 (provisioned, TLS-passing, demo data loaded, destroyed after
  verification). The audit completed 2026-09-14 (owner-reviewed) and hit the
  first revisit trigger: [`AUDIT.md`](../../AUDIT.md) SEC-HIGH-500 and
  SEC-MEDIUM-504 require a Caddy path allowlist, our own image carrying the
  co-pilot module, and a restricted agent container before the evaluator
  deployment (OpenEMR container hardening is documented, not changed:
  `AUDIT.md` §7.3)
- **Date:** 2026-09-13
- **Owners:** Project team
- **Related requirements:** Public deployment, reproducible setup, TLS,
  baseline infrastructure profile
- **Related use cases:** Infrastructure only; no clinical capability is added

## Context

The challenge needs a publicly reachable, production-oriented OpenEMR baseline
early in a one-week build. The local easy-development stack publishes
administrative and data services, uses development credentials and tooling, and
must not be exposed publicly. The initial deployment must be inexpensive,
quick to recreate, small enough to understand, and replaceable if the audit or
measured load invalidates it.

## Decision

Use Terraform to create one short-lived DigitalOcean Basic Droplet and Cloud
Firewall. Run Caddy, OpenEMR, and MariaDB with Docker Compose on that host.
Caddy is the only public application service and terminates valid TLS. MariaDB
has no public host port and sits on an internal Docker network. SSH is
key-only and restricted to explicitly configured source CIDRs.

Use the 2 vCPU / 4 GiB Basic size for infrastructure smoke tests and destroy it
immediately afterward. The 4 vCPU / 8 GiB size is the first fallback if
measurement shows memory pressure. Do not attach paid backups, block storage,
a load balancer, or a reserved IP during disposable testing.

Generate application secrets on the Droplet rather than placing them in
cloud-init or Terraform state. Use only synthetic/demo records.

## Alternatives Considered

### Easy-development Compose on a Droplet

- Benefits: Already runs locally and includes discovery tools.
- Costs and risks: Public database and administrative surfaces, default
  credentials, profiling/debug tooling, and unrelated services.
- Reason rejected: Violates the repository's explicit public-deployment gate.

### Managed database and load balancer from day one

- Benefits: Better component isolation, managed backups, and a clearer scale
  path.
- Costs and risks: More cost and operational surface before workload evidence.
- Reason rejected: Premature for a disposable baseline; revisit after audit and
  load measurements.

### Kubernetes

- Benefits: Standard orchestration, health management, and scaling primitives.
- Costs and risks: Substantial setup, debugging, and explanation burden for a
  three-container one-week project.
- Reason rejected: No demonstrated scaling or reliability need.

## Consequences

### Positive

- Low smoke-test cost and fast full teardown.
- Public TLS without exposing OpenEMR or MariaDB directly.
- Reproducible infrastructure with a deliberately small dependency surface.
- Straightforward vertical and horizontal migration path after measurement.

### Negative and residual risk

- The host and database share one failure domain.
- Docker group membership is effectively host-root capability.
- Disposable smoke deployments have no backup and are destroyed with their
  data.
- A public `sslip.io` hostname is suitable only for short testing, not the
  evaluator environment.
- The upstream image validates infrastructure only and does not include future
  project code.
- The final deployment decision remains subject to audit evidence.
- Both the pinned release image and current `flex` tags strip their own
  upgrade tooling (`sql_upgrade.php`, `acl_upgrade.php`) after boot, so loading
  demo data on a live deployment currently requires a manual workaround
  (temporarily restoring those two files from the repo, running the upgrade,
  removing them again). See `docs/deployment/digitalocean.md` for the exact
  steps. Must be replaced by baking the demo cohort into a project-owned image
  at build time before the evaluator deployment.

## Verification

- `terraform validate` passes from a clean initialization.
- `docker compose config --quiet` passes with non-secret test placeholders.
- The Cloud Firewall exposes only 22 from the configured CIDR and 80/443
  publicly.
- An external smoke test validates trusted TLS, OpenEMR liveness, and a rendered
  OpenEMR page. **Done 2026-09-14**: passed against a live Droplet at a
  `sslip.io` hostname with demo data loaded.
- `terraform destroy` removes the Droplet and all Terraform-managed resources.
  **Done 2026-09-14**: confirmed zero Droplets remaining via the DigitalOcean
  API after destroy.

## Revisit Triggers

- Audit findings require stronger host, secret, or data isolation.
- The 4 GiB host swaps, saturates, or misses latency targets.
- Required uptime, restore-time, or availability targets exceed a single-host
  design.
- The evaluator deployment begins retaining data that needs backup and restore.
