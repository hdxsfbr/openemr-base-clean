# DigitalOcean Deployment Runbook

## Status and Scope

This is a reproducible, single-Droplet baseline for demo data and short-lived
smoke testing. Terraform, Compose, Caddy, shell scripts, and a local cold start
through the TLS proxy were validated on September 13, 2026. It has not yet been
provisioned or externally verified, and it does not make the application
suitable for real patient data.

The stack exposes only Caddy on ports 80 and 443. Caddy redirects HTTP to HTTPS
and obtains a public certificate. OpenEMR and MariaDB are not published on host
ports, and MariaDB is isolated on an internal Docker network. SSH is restricted
to CIDRs explicitly supplied to Terraform.

The default OpenEMR image is the pinned upstream 8.1.1 production image. That is
appropriate for validating the infrastructure path, but it does not contain
future project code from this repository. Supply a pinned project image with
the optional argument to `deploy.sh` before testing custom functionality.

## Cost-Controlled Smoke Test

DigitalOcean Basic Droplets are billed while allocated, even when powered off.
Destroy the Droplet to stop compute billing. Bundled-CPU Droplets use
per-second billing with a 60-second or $0.01 minimum. As of September 13, 2026,
the default 2 vCPU / 4 GiB Droplet is $0.03571 per hour ($24 monthly cap), and
the larger 4 vCPU / 8 GiB option is $0.07143 per hour ($48 monthly cap).

| Elapsed allocation | 4 GiB default | 8 GiB fallback |
| --- | ---: | ---: |
| 15–45 minute quick cycle | $0.01–$0.03 | $0.02–$0.06 |
| 1 hour | $0.04 | $0.08 |
| 2 hours | $0.08 | $0.15 |
| 6 hours | $0.22 | $0.43 |
| 24 hours | $0.86 | $1.72 |

These estimates are conservatively rounded up to the next cent, are compute
only, and exclude tax. The smoke configuration intentionally disables Droplet
backups and creates no load balancer, managed database, block volume, snapshot,
or reserved IP. Normal smoke-test bandwidth should remain inside the Droplet's
included transfer.

Official references:

- [Droplet pricing and billing behavior](https://docs.digitalocean.com/products/droplets/details/pricing/)
- [Basic Droplet prices](https://www.digitalocean.com/pricing/droplets)
- [Reserved IP pricing](https://docs.digitalocean.com/products/networking/reserved-ips/details/pricing/)
- [Snapshot pricing](https://docs.digitalocean.com/products/snapshots/details/pricing/)

## Prerequisites

- A DigitalOcean account with payment verification completed.
- Terraform 1.7+ or OpenTofu installed locally.
- An Ed25519 SSH public key at `~/.ssh/id_ed25519.pub`, or an override in
  `terraform.tfvars`.
- A DigitalOcean API token with write access. Never commit it, put it in a
  Terraform variable file, or paste it into project logs or chat.
- Docker is not required locally; cloud-init installs Docker Engine and the
  Compose plugin on the Droplet.

If needed, create an SSH key locally:

```bash
ssh-keygen -t ed25519 -a 64
```

## Configure

From `infra/digitalocean`:

```bash
cp terraform.tfvars.example terraform.tfvars
curl --fail --silent --show-error https://api.ipify.org
```

Replace the documentation-only address in `terraform.tfvars` with the returned
address followed by `/32`. Recheck it after changing networks; Terraform
intentionally rejects world-open SSH.

Load the API token without writing it to shell history:

```bash
read -rsp "DigitalOcean token: " DIGITALOCEAN_TOKEN
export DIGITALOCEAN_TOKEN
printf '\n'
```

## Fastest Safe Cycle

The following command provisions the host, deploys the stack, verifies public
TLS and OpenEMR liveness, and destroys all Terraform-managed resources even if
the deploy or smoke test fails:

```bash
./smoke-cycle.sh you@example.com
```

It uses a disposable `sslip.io` hostname derived from the Droplet IP so the
smoke test does not require owned DNS. This external DNS dependency is only for
the disposable test; use an owned hostname for the evaluator deployment.

Set `KEEP_INFRA=1` only when intentionally retaining the environment for
debugging. It remains billable until `./destroy.sh --yes` succeeds.

## Manual Cycle

To inspect each stage:

```bash
./tf.sh init
./tf.sh plan -out=smoke.tfplan
./tf.sh apply smoke.tfplan

DROPLET_IP="$(./tf.sh output -raw ipv4_address)"
PUBLIC_HOSTNAME="$(./tf.sh output -raw smoke_hostname)"

./deploy.sh "$DROPLET_IP" "$PUBLIC_HOSTNAME" you@example.com
./smoke.sh "$PUBLIC_HOSTNAME"
```

Retrieve the generated demo administrator password only over SSH:

```bash
ssh "deployer@$DROPLET_IP" \
  cat /opt/agentforge/secrets/openemr_admin_password
```

The username is `challenge-admin`. Do not record the generated password in a
screenshot, issue, commit, trace, or ordinary log.

Destroy immediately after the test:

```bash
./destroy.sh --yes
unset DIGITALOCEAN_TOKEN
```

Confirm the destroy completed in Terraform output and in the DigitalOcean
control panel. Stopping containers or shutting down the Droplet does not stop
Droplet billing.

## What the Automation Creates

- One Ubuntu 24.04 Basic Droplet with monitoring enabled and backups disabled.
- One restricted DigitalOcean Cloud Firewall.
- One ephemeral project and SSH key record.
- Docker, Compose, and a non-password `deployer` user installed by cloud-init.
- Caddy, OpenEMR, and MariaDB containers with pinned image digests.
- Droplet-local named volumes and randomly generated demo credentials.

Terraform state remains local and ignored by Git. Application secrets are
generated on the Droplet, stored with owner-only permissions, and are not
placed in cloud-init or Terraform state.

## Failure and Recovery

- If TLS issuance is still converging, wait one minute and rerun `smoke.sh`.
- If deployment fails, inspect `docker compose ps` and redacted container logs
  over SSH. Never paste raw application logs into public artifacts.
- If the fast cycle reports that automatic destruction failed, run
  `./destroy.sh --yes` immediately and verify the Droplet is absent in the
  control panel.
- Destroying this smoke host destroys its database and generated credentials.
  There is intentionally no backup for the disposable cycle.

## Before the Evaluator Deployment

- Build and pin a project-owned production image rather than the upstream
  baseline image.
- Use an owned hostname and point DNS to the Droplet before starting Caddy.
- Complete the audit and revisit this topology against its findings.
- Add tested backup/restore and rollback procedures before keeping data.
- Add meaningful readiness checks; the current upstream readiness semantics are
  a known audit item.
- Load only deterministic synthetic/demo data and rotate deployment credentials.
