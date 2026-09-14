# ADR-0001: Ephemeral Single-Droplet Baseline on DigitalOcean

- **Status:** Accepted for baseline smoke testing; final topology pending audit
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

## Verification

- `terraform validate` passes from a clean initialization.
- `docker compose config --quiet` passes with non-secret test placeholders.
- The Cloud Firewall exposes only 22 from the configured CIDR and 80/443
  publicly.
- An external smoke test validates trusted TLS, OpenEMR liveness, and a rendered
  OpenEMR page.
- `terraform destroy` removes the Droplet and all Terraform-managed resources.

## Revisit Triggers

- Audit findings require stronger host, secret, or data isolation.
- The 4 GiB host swaps, saturates, or misses latency targets.
- Required uptime, restore-time, or availability targets exceed a single-host
  design.
- The evaluator deployment begins retaining data that needs backup and restore.
