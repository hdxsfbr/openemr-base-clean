# DigitalOcean Deployment Runbook

## Status and Scope

This is a reproducible, single-Droplet baseline for demo data and short-lived
smoke testing. Terraform, Compose, Caddy, shell scripts, and a local cold start
through the TLS proxy were validated on September 13, 2026. It was provisioned
and externally verified for real on September 14, 2026: a live Droplet, valid
public TLS, and the bundled OpenEMR demo dataset (3 patients, 3 encounters, 11
appointments; schema upgraded to current) all confirmed reachable at a
`sslip.io` hostname, then destroyed again to stop billing. A second window
(23:34–23:42 UTC) re-provisioned from reviewed saved Terraform plans for the
audit's unauthenticated public probe and read-only configuration dump, then
destroyed. See `docs/audit/evidence/security/cloud-probe-2026-09-14.txt` and
`cloud-runtime-2026-09-14.md`. It still does not
make the application suitable for real patient data — see "Before the
Evaluator Deployment" below.

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
- Terraform 1.7+, OpenTofu, or Docker installed locally. `tf.sh` automatically
  uses a pinned Terraform container when neither CLI is installed.
- An Ed25519 SSH public key at `~/.ssh/id_ed25519.pub`, or an override in
  `terraform.tfvars`.
- A DigitalOcean API token with write access. Never commit it, put it in a
  Terraform variable file, or paste it into project logs or chat.
- Cloud-init installs Docker Engine and the Compose plugin on the Droplet.

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

Load the API token without writing it to shell history. On the owner's
machine it is kept outside the repository at `~/.config/agentforge/do.env`
(mode 600, exports `DIGITALOCEAN_TOKEN`):

```bash
set -a; . ~/.config/agentforge/do.env; set +a
```

Anywhere else, read it interactively:

```bash
read -rsp "DigitalOcean token: " DIGITALOCEAN_TOKEN
export DIGITALOCEAN_TOKEN
printf '\n'
```

To confirm nothing is running before or after a cycle:

```bash
for r in droplets firewalls reserved_ips volumes; do printf '%s: ' "$r"; curl -s -H "Authorization: Bearer $DIGITALOCEAN_TOKEN" "https://api.digitalocean.com/v2/$r?per_page=50" | python3 -c "import sys,json;d=json.load(sys.stdin);print(len(d[[k for k in d if isinstance(d[k],list)][0]]))"; done
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

## Current Deployment (2026-09-15)

Tag `v0.2.0-slice` (2026-09-15, superseding `v0.1.0-skeleton`) is live at
`https://openemr-137-184-4-22.sslip.io`: the UC-01 turn runs end to end
through the panel, per-turn ticket, agent, gateway, and verifier, and the
Bruno collection passes 20/20 against it as `audit-physician`. Until the
model key is written the narrative is replaced by the deterministic
source-cited brief. Earlier baseline `v0.1.0-skeleton` was live at the same URL
(Droplet `137.184.4.22`, kept up during build days at about $0.86/day):
project OpenEMR image with the co-pilot module, the agent service
(`/copilot-api/health` 200, `/copilot-api/ready` 503 until the model and
tracer keys are supplied), deny-by-default edge (probe evidence:
`docs/audit/evidence/security/cloud-probe-2026-09-15-allowlist.txt`), demo
users and the 26-patient cohort seeded, and the panel rendering on cohort
charts for `audit-physician`. The `sslip.io` hostname is still the disposable
one; an owned hostname is a pre-submission task.

## Manual Cycle

To inspect each stage:

```bash
./tf.sh init
./tf.sh plan -out=deploy.tfplan
./tf.sh apply deploy.tfplan

DROPLET_IP="$(./tf.sh output -raw ipv4_address)"
PUBLIC_HOSTNAME="$(./tf.sh output -raw smoke_hostname)"

./deploy.sh "$DROPLET_IP" "$PUBLIC_HOSTNAME" you@example.com
./smoke.sh "$PUBLIC_HOSTNAME"
```

`deploy.sh` copies the runtime files, then the build contexts (the module
under `build/openemr/`, the agent under `build/agent/`) and the synthetic
cohort under `demo/cohort/` (a read-only bind mount, never in an image).
`start.sh` builds the two project images on the host, starts the stack, and
runs the one-shot `copilot-setup` job that registers and enables the module.
Re-running `deploy.sh` is idempotent.

Seed the demo users (`physician`, `audit-physician`, `audit-nurse`,
`audit-frontdesk`) and the synthetic cohort in one job, and keep its manifest
in the deploy log:

```bash
ssh "deployer@$DROPLET_IP" 'cd /opt/agentforge && docker compose --profile demo run --rm demo-seed | tee "logs/demo-seed-$(date +%F).log"'
```

The job exits non-zero if any post-load check fails. The shared demo
clinician password is generated on the host; read it only over SSH:

```bash
ssh "deployer@$DROPLET_IP" cat /opt/agentforge/secrets/demo_user_password
```

Operator-supplied secrets (`anthropic_api_key`, `langfuse_public_key`,
`langfuse_secret_key`, and `anthropic_workspace_id` only when the Anthropic key
is organization-level rather than workspace-scoped) live on the operator's machine as one file each in
`~/.config/agentforge/`, next to `do.env`, and are never committed. Push
whichever exist and restart the agent with:

```bash
./push-secrets.sh "$DROPLET_IP"
```

`deploy.sh` runs the same push before `start.sh`, so a redeploy keeps them.
On the Droplet they are mode 0644 inside the 0700 secrets directory (Compose
file secrets keep the host mode and the agent runs as uid 10001). Until they
exist the agent's `/ready` reports each as `not_configured`.

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
- Caddy and MariaDB containers with pinned image digests; the project OpenEMR
  image (pinned upstream release plus the co-pilot module) and the agent
  service image, both built on the Droplet from contexts `deploy.sh` copies.
- Two one-shot jobs behind Compose profiles: `copilot-setup` (module
  registration) and `demo-seed` (demo users and synthetic cohort).
- Droplet-local named volumes (database, sites, logs, TLS, agent state, Caddy)
  and randomly generated demo credentials.

Terraform state remains local and ignored by Git. Application secrets are
generated on the Droplet, stored with owner-only permissions, and are not
placed in cloud-init or Terraform state.

## CI Runner (2026-09-16)

The lab GitLab (`labs.gauntletai.com`) had no shared runners available to
the project and its pipeline subsystem was failing on 2026-09-16 (no pipeline
ever created, "Unable to validate CI/CD configuration" in the editor), so the
project has its own runner on a dedicated Droplet. It is deliberately not on
the demo host and not on the owner's workstation: a runner executes whatever
`.gitlab-ci.yml` says at the built commit and needs the Docker socket, so it
lives on a machine that holds nothing else.

| Item | Value |
| --- | --- |
| Terraform root | `infra/digitalocean/runner/` (own state; destroying it never touches the demo host) |
| Droplet | `agentforge-ci-runner`, `s-1vcpu-1gb` ($6/month, $0.00893/h), `sfo3`, Ubuntu 24.04, 2 GB swap |
| Firewall | inbound SSH from `allowed_ssh_cidrs` only; outbound open (the runner polls GitLab, nothing connects in) |
| GitLab side | project runner #221 on the repository, untagged jobs allowed, not shared with any other project |
| Executor | Docker, unprivileged, `concurrent = 1`, default image `alpine:3.20` |

Create and register (the runner authentication token is read from a local
file and never printed, stored in Terraform state, or put in user data):

```bash
cd infra/digitalocean
set -a; source ~/.config/agentforge/do.env; set +a
./tf.sh -chdir=runner init -input=false
./tf.sh -chdir=runner apply -input=false -var-file=../terraform.tfvars
./runner/register.sh "$(./tf.sh -chdir=runner output -raw runner_ip)" ~/.config/agentforge/gitlab_runner_token
```

The token comes from GitLab: Settings → CI/CD → Runners → the runner's page
(shown once at creation). Rotating it: reset the token on that page, put the
new value in the file, re-run `register.sh`. Retiring the runner:
`./tf.sh -chdir=runner destroy -var-file=../terraform.tfvars`, then delete
runner #221 on GitLab.

## Failure and Recovery

- If TLS issuance is still converging, wait one minute and rerun `smoke.sh`.
- If deployment fails, inspect `docker compose ps` and redacted container logs
  over SSH. Never paste raw application logs into public artifacts.
- If the fast cycle reports that automatic destruction failed, run
  `./destroy.sh --yes` immediately and verify the Droplet is absent in the
  control panel.
- Destroying this smoke host destroys its database and generated credentials.
  There is intentionally no backup for the disposable cycle.

## Known Gotchas From the First Live Run (2026-09-14)

**cloud-init reports `error` on Ubuntu 24.04 (found 2026-09-15).** The last
`runcmd` step, `systemctl reload ssh`, fails because ssh is socket-activated
and not running until the first connection; everything before it (Docker,
Compose, the `deployer` user, `/opt/agentforge`) completes. The template now
uses `try-reload-or-restart`, and `deploy.sh` proceeds on an `error` status
when Docker is present rather than timing out.

**The demo-data workaround below is no longer needed.** The synthetic cohort
and demo users load through the `demo-seed` job against the release image's
own schema without the upgrade tooling; the paragraph is kept for the
bundled 5.0.0.5 demo dump only, which the deployment no longer uses.

**Upgrade tooling is stripped from the running image.** Both the pinned
release image and newer `:flex` tags remove `sql_upgrade.php` and
`acl_upgrade.php` from the webroot after their own boot-time setup completes
(deliberate hardening — these are setup-only entry points). This means
`demoData()`'s `devtoolsLibrary.source` function can import the OpenEMR
5.0.0.5 demo dump but cannot finish the schema/ACL upgrade on those images.
The exact `flex` digest pinned in `docker/development-easy` (the one used
locally) still has this behavior too when run standalone, without the local
repo bind-mounted over it. The workaround used for this deployment:
`docker compose cp` the repo's own `sql_upgrade.php` and `acl_upgrade.php`
into the running container, invoke `upgradeOpenEMR` and
`changeEncodingCollation` from `devtoolsLibrary.source` directly (CLI mode via
`run_php_as_apache`), then delete both files again afterward to restore the
hardened state. This is safe because it uses the exact same source the local
dev stack already runs, but it is a manual step, not something `deploy.sh`
does today. Before the evaluator deployment, replace it with the `demo-seed`
job described below, so no long-running container ever carries upgrade
tooling or `evals/`.

**Caddy can get stuck in `Created` state.** Its `depends_on: condition:
service_healthy` on `openemr` sometimes resolves after `docker compose up
--wait`'s window has already returned (e.g. when re-deploying with a
different image tag that needs to build/boot from scratch), leaving Caddy
created but never started. Symptom: the public URL times out even though
`docker compose ps` shows `openemr` and `database` healthy. Fix: `docker
compose up --detach --wait --wait-timeout 120 caddy` to start it explicitly.
Worth a `start.sh` follow-up to check for and recover from this automatically.

## Before the Evaluator Deployment

The audit (`AUDIT.md` §7.2) scopes what this project changes here. It plans
the co-pilot; it does not repair OpenEMR.

**Required before deploying the agent** (status as of 2026-09-15):

- [x] **Caddy deny-by-default path allowlist** (`runtime/Caddyfile`): only
  OpenEMR application paths and `/meta/health/livez` reach Apache;
  `/copilot-api/*` goes to the agent; the module's gateway and CLI paths
  are unrouted. Probe evidence:
  `docs/audit/evidence/security/cloud-probe-2026-09-15-allowlist.txt`
  (20 sensitive paths at 404).
- [x] **Our own image** (`infra/image/openemr.Dockerfile`, root
  `.dockerignore`): the pinned release plus the module only. Verified the
  built image has no `evals/`.
- [x] **Demo seeding job** `demo-seed` (profile `demo`): read-only bind mount
  outside the web root; runs `seed_users.php` then `seed_cohort.php`; exits
  non-zero on a failed check. It is run explicitly after `start.sh`, not
  inside it, so a seeding failure never blocks the application start.
- [x] **Agent container** on the `frontend` network only with file secrets.
  [ ] Egress restriction to the model and tracer endpoints is not in place;
  recorded as residual risk until done.
- [x] **REST/FHIR** stay disabled and are unrouted at the edge (`/apis/*`,
  `/oauth2/*` 404).
- [x] **Readiness** from the agent's `/ready`; OpenEMR `readyz` is unrouted.
- [ ] Use an owned hostname and point DNS to the Droplet before the
  evaluator deployment; rotate deployment credentials.

**Documented, not changed here** (`AUDIT.md` §7.3; these are what a real
deployment would need): patched images and a vulnerability-scan gate
(SEC-HIGH-502); OpenEMR container hardening and removing `MYSQL_ROOT_PASS` from
its environment (SEC-MEDIUM-503); tested backup/restore and rollback
(COMP-MED-005).
