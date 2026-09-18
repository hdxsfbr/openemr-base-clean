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

## Current Deployment (2026-09-16)

The deployment is live at `https://openemr-137-184-4-22.sslip.io` (Droplet
`137.184.4.22`). The deployed tag since 2026-09-16 is `week1` at commit
`e1dd331`, which is what the early submission was made from; `v0.2.0-slice`
(2026-09-15, superseding `v0.1.0-skeleton`) was the tag before it. Commits
after `e1dd331` up to `66a6711` touched only documentation; the M2 work on
branch `week1-final-push` (2026-09-17) changes `agent/` and
`infra/digitalocean/runtime/` (the `alerts` service, the `start.sh` gates,
log rotation), so the host keeps running the `week1` tree until the M3
deploy. No deployed image digest has been recorded yet; the final deploy
records one. The model and tracer keys
were pushed with `push-secrets.sh` on 2026-09-15, so turns run with
`claude-sonnet-5` and trace to Langfuse; the eleven eval reports in
`evals/results/` (2026-09-16 and 2026-09-17) and the manual CI job `test:evals-live`
(below) target this hostname, and the Bruno collection passes 21/21 against
it as `audit-physician` (`docs/SUBMISSION_CHECKLIST.md`). Without the model
key the narrative falls back to the deterministic source-cited brief
(`MODEL-OUTAGE-001`). Earlier baseline `v0.1.0-skeleton` was live at the same URL
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
`start.sh` builds the two project images on the host, starts the stack,
starts `caddy` a second time explicitly (it could stay in `Created`, see
"Known Gotchas"), exits non-zero unless `database`, `openemr`, `agent`,
`caddy` and `alerts` are all running, probes
`https://<hostname>/meta/health/livez` up to six times ten seconds apart, and
only then runs the one-shot `copilot-setup` job that registers and enables
the module. Re-running `deploy.sh` is idempotent; when a gate fails, read
the `docker compose ps` it prints and rerun. The gates and the `alerts`
service are in the tree since 2026-09-17 and first run on a host at the M3
deploy.

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
`~/.config/agentforge/` (override the directory with `AGENTFORGE_SECRETS_DIR`),
next to `do.env`, and are never committed. Push whichever exist, restart the
agent, and print `/ready` with:

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
- The `alerts` service (the agent image, no build of its own) running
  `python -m app.alerts --url http://agent:8080/metrics --ready-url
  http://agent:8080/ready --state /var/lib/copilot/alerts-state.json
  --interval 300`: the three PRD alert rules every 300 s, one JSON line per
  evaluation in `docker compose logs alerts`, state on the agent volume, its
  inherited health check disabled so it never blocks `up --wait`.
- Log rotation on every container (`x-logging` in `compose.yaml`: json-file,
  10 MiB, three files), so a long-lived host no longer grows unbounded logs.
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
| GitLab side | project runner #222 on the repository, untagged jobs allowed, locked to this project |
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

Why no pipeline existed before 2026-09-16 06:01: the lab GitLab account had
no confirmed email (`confirmed_at: null` on `/api/v4/user`), and GitLab
refuses pipeline creation to unconfirmed users even for project owners (the
symptoms: no "Run pipeline" button, `/-/pipelines/new` 404, the pipeline
editor "Unable to validate", the lint API "Insufficient permissions to create
a new pipeline"). Resending the confirmation from
`/users/confirmation/new` to the account's primary address fixed it. The
runner was never the problem; it was Online and Idle throughout.

The token comes from GitLab: Settings → CI/CD → Runners → the runner's page
(shown once at creation). Rotating it: reset the token on that page, put the
new value in the file, re-run `register.sh`. Retiring the runner:
`./tf.sh -chdir=runner destroy -var-file=../terraform.tfvars`, then delete
runner #222 on GitLab.

### What the pipeline runs

`.gitlab-ci.yml` has two stages. `lint`: `lint:whitespace`, `lint:php` (the
module), `lint:caddy` (`runtime/Caddyfile`), `lint:compose` (`runtime/compose.yaml`
with placeholder secrets). `test`: `test:agent` (pytest plus the contract
export drift check) and `test:evals-offline` (`python evals/run.py
--offline-only`, results kept as a 30-day artifact). The first green pipeline
on this runner is recorded in `docs/SUBMISSION_CHECKLIST.md`.

`test:evals-live` is a **manual** job (`when: manual`, `allow_failure: false`)
that runs the full suite against the deployment with
`python evals/run.py --base-url "$COPILOT_EVAL_BASE_URL" --label "gitlab-ci $CI_PIPELINE_ID"`;
`COPILOT_EVAL_BASE_URL` defaults to `https://openemr-137-184-4-22.sslip.io`
and must follow the hostname if it changes. It exits 2 unless the masked CI
variable `DEMO_PASSWORD` (the shared demo clinician password from
`/opt/agentforge/secrets/demo_user_password`) is set on the project. Results
under `evals/results/` attach as a 90-day artifact; the job's exit code
follows the release gates (a non-blocking recall miss is reported, not
fatal). It is manual so a push never spends model budget by itself (about
$0.50 and 12 minutes per run).

## Failure and Recovery

- If TLS issuance is still converging, wait one minute and rerun `smoke.sh`.
- If deployment fails, inspect `docker compose ps` and redacted container logs
  over SSH. Never paste raw application logs into public artifacts.
- If the fast cycle reports that automatic destruction failed, run
  `./destroy.sh --yes` immediately and verify the Droplet is absent in the
  control panel.
- `start.sh` now fails loudly: a service not running after `up --wait`, or
  the public `livez` probe failing six times, exits non-zero with `docker
  compose ps` (and the last Caddy log lines) on stderr. Rerun `deploy.sh`
  after reading them; it is idempotent.
- Destroying a host destroys its database and generated credentials. The
  disposable smoke cycle takes no backup; for a host worth keeping, run
  `backup.sh` first (next section).

### After grading: credential rotation (dated checklist)

Run after the Week 1 grade is posted and the final video is up; not before.
Rotate in this order (externally usable keys first, then what the host
holds, then the host, then provider and repository tokens, then keys). Date
each line as it is done, by file name only; never write a value anywhere.

1. `[ ] <date>` Model key, `~/.config/agentforge/anthropic_api_key` (and
   `anthropic_workspace_id` if the key is organization-level): create the new
   key in the Anthropic Console, then revoke the old one there. Write it
   without shell history:
   `(umask 077; read -rsp 'new value: ' v; printf '%s' "$v" > ~/.config/agentforge/anthropic_api_key; unset v)`.
   If the Droplet is still up: `./push-secrets.sh 137.184.4.22`.
2. `[ ] <date>` Tracer keys, `~/.config/agentforge/langfuse_public_key` and
   `langfuse_secret_key`: Langfuse project settings, API keys, create the new
   pair, delete the old one; write both files as in step 1; `./push-secrets.sh`
   if the Droplet is still up.
3. `[ ] <date>` Host-generated secrets in `/opt/agentforge/secrets/`
   (`mysql_root_password`, `mysql_password`, `openemr_admin_password`,
   `copilot_delegation_secret`, `demo_user_password`, written by
   `runtime/start.sh` only when absent): rotated by ending the host.
   `cd infra/digitalocean && set -a; . ~/.config/agentforge/do.env; set +a && ./destroy.sh --yes`,
   then the "Configure" section's resource-count loop must print `droplets: 0`.
   An in-place rotation of `copilot_delegation_secret` is untested and is not
   described here. Delete the M4 snapshot too, since it carries these files:
   `doctl compute snapshot list` then `doctl compute snapshot delete <id>` for
   `week1-final-2026-09-19`.
4. `[ ] <date>` CI variable `DEMO_PASSWORD` (GitLab, Settings, CI/CD,
   Variables): delete it; it named the destroyed host's `demo_user_password`.
5. `[ ] <date>` DigitalOcean API token, `~/.config/agentforge/do.env`:
   `unset DIGITALOCEAN_TOKEN`; in the control panel (API, Tokens) generate a
   new token and revoke the old; rewrite `do.env` at mode 600 with
   `(umask 077; read -rsp 'token: ' v; printf 'DIGITALOCEAN_TOKEN=%s\n' "$v" > ~/.config/agentforge/do.env; unset v)`.
6. `[ ] <date>` CI runner token, `~/.config/agentforge/gitlab_runner_token`:
   either retire the runner, `./tf.sh -chdir=runner destroy -var-file=../terraform.tfvars`
   then delete runner #222 on GitLab, or reset the token on the runner's page,
   write the file as in step 1, and re-run
   `./runner/register.sh "$(./tf.sh -chdir=runner output -raw runner_ip)" ~/.config/agentforge/gitlab_runner_token`.
7. `[ ] <date>` GitLab personal access token, `~/.config/agentforge/gitlab_pat`
   and `~/.config/agentforge/git-credentials`, and the write token embedded in
   the `gitlab` remote URL: revoke every token under GitLab User settings,
   Access tokens; then
   `git remote set-url gitlab https://labs.gauntletai.com/andrebatista/andrebatista-openemr-base-clean.git`
   and `shred -u ~/.config/agentforge/git-credentials ~/.config/agentforge/gitlab_pat`.
   Never run `git remote -v` before the URL is replaced.
8. `[ ] <date>` Deploy SSH key, `~/.ssh/id_ed25519` (or the override in
   `terraform.tfvars`): `ssh-keygen -t ed25519 -a 64 -f ~/.ssh/id_ed25519_agentforge`,
   point `terraform.tfvars` at the new public key, remove the old key under
   DigitalOcean Settings, Security. No `tf.sh apply` is needed once step 3 ran.
9. `[ ] <date>` Backups and state copies: `~/.config/agentforge/backups/`
   holds `<host>-<stamp>.tar.age` (or `.gpg`) archives from `backup.sh`
   whose `config.tar` carries `/opt/agentforge/secrets` and `.env`;
   keep one only while its passphrase is kept, otherwise `shred -u` it.
   `~/.config/agentforge/tfstate/<date>/` holds no secret by design and stays
   at mode 600.
10. `[ ] <date>` Langfuse traces are synthetic and PHI-free; deleting the
    project is optional and is not a rotation step.

## Backup and Restore

`infra/digitalocean/backup.sh` and `restore.sh` run on the operator's machine
and work over SSH (written 2026-09-17; **neither has been run against a host
yet** — that is the M4 rehearsal below). Neither has a default host: `--host`
is mandatory, and `--dry-run` prints every command without contacting
anything.

```bash
cd infra/digitalocean
./backup.sh --host "$DROPLET_IP"                 # passphrase prompt; prints the archive path
./backup.sh --host "$DROPLET_IP" --dry-run       # print the commands, contact nothing
./restore.sh --host "$DROPLET_IP" --archive ~/.config/agentforge/backups/<host>-<stamp>.tar.age
```

`backup.sh` writes one archive under `~/.config/agentforge/backups/` (mode
600, never in the repository), encrypted with `age` when it is installed and
with `gpg --symmetric` (AES256) otherwise, holding:

- `openemr.sql.gz`: `mariadb-dump --single-transaction` of the `openemr`
  database, run inside the `database` container. The root password is read
  there from the container's own `MARIADB_ROOT_PASSWORD_FILE` into
  `MYSQL_PWD`; it is never printed and never passed as an argument.
- `openemr_sites.tar` and `agent_state.tar`: the `openemr_sites` and
  `agent_state` volumes. The compose project name `agentforge-openemr`
  prefixes them on the host (`agentforge-openemr_openemr_sites`,
  `agentforge-openemr_agent_state`); the scripts resolve the names through
  the Compose volume labels rather than hard-coding them.
- `config.tar`: `/opt/agentforge/secrets` and `/opt/agentforge/.env`.
- `manifest.txt` (host, time, image ids, container status) and `SHA256SUMS`,
  which `restore.sh` checks before it touches a host.

Not captured: `openemr_logs`, `openemr_ssl`, `caddy_data`, `caddy_config`
(they regenerate) and the raw `database_data` files (the dump replaces
them). The agent state is copied hot, so a checkpoint mid-write may be
inconsistent; conversations are ephemeral demo state.

**Why the secrets are in the backup, and why losing them is fatal.** Every
password in the stack is generated on the host by `start.sh` the first time
it runs (`openssl rand`): the MariaDB root and `openemr` users, the OpenEMR
admin, the delegation secret, and the shared demo clinician password
(`DEMO_PASSWORD`, whose hashes sit in the database). If
`/opt/agentforge/secrets` is lost, the database volume is orphaned (no
credential can open MariaDB or OpenEMR any more) and the next `start.sh`
generates a new `DEMO_PASSWORD` that matches no seeded user, so the eval
harness, the Bruno collection and the CI variable all stop working. A
Droplet snapshot does not help with a deleted directory; the encrypted
archive does.

`restore.sh` deletes the host's database volume, so back up first. In order:

1. Decrypt into a 0700 temp directory on the operator's machine and verify
   `SHA256SUMS`; nothing on the host is touched until the archive is intact.
2. Stop `openemr`, `agent` and `alerts` (those present in the host's compose
   file).
3. Untar `secrets/` and `.env` into `/opt/agentforge`. `--skip-env` keeps the
   host's own `.env`, for restoring one host's archive onto a host with a
   different hostname.
4. Remove the `database` container, delete `database_data`, and start
   `database` again so MariaDB initialises from the restored secrets. MariaDB
   reads `MARIADB_*_PASSWORD_FILE` only into an empty volume, so a volume
   initialised under other secrets (a fresh Droplet, or a host whose secrets
   directory was lost) can never accept the restored credentials; a re-init
   always can.
5. Load the dump through `mariadb` inside the container (same `MYSQL_PWD`
   handling).
6. Replace the contents of the `openemr_sites` and `agent_state` volumes.
7. `docker compose up --detach --wait`, then print `docker compose ps`.

After a restore the demo clinician password is the one from the archive. The
host must have been deployed once (`deploy.sh`) so the project, images and
volumes exist; `restore.sh` asks you to type the host before step 2 unless
`--yes` is given.

## Rehearsal Runbook: clean deploy, rollback, roll-forward, restore

**The default Terraform workspace and the live Droplet `137.184.4.22` are
never touched by this runbook.** Every Terraform command below runs in the
`rehearsal` workspace with its own state and its own `project_name`, every
`deploy.sh`, `backup.sh` and `restore.sh` call names the rehearsal IP
explicitly, and the throwaway SSH key is registered under a different
DigitalOcean name. **`smoke-cycle.sh` and a default-workspace `./tf.sh apply`
both target the live Droplet**: `smoke-cycle.sh` runs `tf.sh apply` and then
`destroy.sh --yes` in whatever workspace is selected, which is `default`
unless you changed it. Never run either as part of a rehearsal. Execution is
human-gated (`docs/FINAL_PUSH_PLAN.md`, M3 and M4); agents prepare and
watch, and fill the timing table at the end.

Cost: one `s-2vcpu-4gb` Droplet at $0.03571 per hour, so a rehearsal done in
one sitting is under $0.20 of compute, plus about $0.15 of model spend for
each `--golden-only` run: 7 of the 14 golden cases are model-backed (the other
7 are `mode: offline`), 8 model turns in all at $0.0127 to $0.0223 each.
Destroy the same day.

Before starting: `git status --porcelain` is empty on the branch being
rehearsed; the DigitalOcean token is loaded
(`set -a; . ~/.config/agentforge/do.env; set +a`); `TLS_EMAIL` is set in the
shell; and `./tf.sh workspace show` prints `default`, the live workspace you
are about to leave.

### 1. Throwaway SSH key

DigitalOcean registers a public key once per account and `main.tf` creates a
`digitalocean_ssh_key` resource, so a second stack with the same key fails on
the duplicate fingerprint. The rehearsal uses its own key:

```bash
ssh-keygen -t ed25519 -a 64 -C agentforge-rehearsal -f ~/.ssh/agentforge_rehearsal
ssh-add ~/.ssh/agentforge_rehearsal     # deploy.sh, backup.sh and restore.sh use plain ssh
```

### 2. Rehearsal workspace and Droplet

`terraform.tfvars` (the SSH allowlist) is auto-loaded in every workspace. The
two `-var` flags override the defaults in `variables.tf` (`project_name`,
default `agentforge-openemr-smoke`; `ssh_public_key_path`, default
`~/.ssh/id_ed25519.pub`). Keep the `~` literal inside the quotes: `tf.sh` may
run Terraform in a container whose HOME is `/tmp/terraform-home` with
`~/.ssh` mounted read-only there, and Terraform expands it. The plan file is
ignored by Git (`*.tfplan`), as is the workspace state under
`terraform.tfstate.d/` (`*.tfstate`).

```bash
cd infra/digitalocean
./tf.sh workspace new rehearsal          # or: ./tf.sh workspace select rehearsal
./tf.sh workspace show                   # must print: rehearsal
REHEARSAL_VARS=(-var project_name=agentforge-rehearsal -var 'ssh_public_key_path=~/.ssh/agentforge_rehearsal.pub')
./tf.sh plan "${REHEARSAL_VARS[@]}" -out=rehearsal.tfplan
./tf.sh apply rehearsal.tfplan
REHEARSAL_IP="$(./tf.sh output -raw ipv4_address)"
REHEARSAL_HOST="$(./tf.sh output -raw smoke_hostname)"
[[ "$REHEARSAL_IP" != "137.184.4.22" ]] || { echo "wrong workspace, stop"; false; }
```

### 3. Clean deploy at HEAD (T1)

```bash
./deploy.sh "$REHEARSAL_IP" "$REHEARSAL_HOST" "$TLS_EMAIL"
```

`deploy.sh` pushes the operator's model and tracer keys from
`~/.config/agentforge/` to whatever host it targets (`deploy.sh:60`); the
golden run needs the model key. To rehearse without them, prefix
`AGENTFORGE_SECRETS_DIR=/nonexistent` (then `/ready` stays 503 and the
model-backed golden cases fail, as designed). On a brand-new `sslip.io`
hostname, certificate issuance can outlast the six `livez` probes at the end
of `start.sh`; rerun `deploy.sh`, it is idempotent. T1 is the wall-clock time
from the `deploy.sh` call to its "Deployment started" line.

### 4. Seed and verify (T2)

```bash
ssh "deployer@$REHEARSAL_IP" 'cd /opt/agentforge && docker compose --profile demo run --rm demo-seed | tee "logs/demo-seed-$(date +%F).log"'
./smoke.sh "$REHEARSAL_HOST"
curl -s "https://$REHEARSAL_HOST/copilot-api/ready"
ssh "deployer@$REHEARSAL_IP" 'cd /opt/agentforge && docker compose ps && docker compose logs --tail 3 alerts'   # five services Up; a heartbeat line
cd ../..
DEMO_PASSWORD="$(ssh "deployer@$REHEARSAL_IP" cat /opt/agentforge/secrets/demo_user_password)" \
  agent/.venv/bin/python evals/run.py --golden-only --base-url "https://$REHEARSAL_HOST" --label "rehearsal: HEAD clean deploy"
cd infra/digitalocean
```

The report lands in `evals/results/` labelled as a rehearsal; keep or discard
it deliberately, and never point the harness at the live host from this
shell by mistake (`--base-url` is explicit above for that reason).

### 5. Backup (T3)

```bash
./backup.sh --host "$REHEARSAL_IP"       # passphrase prompt; note the archive path it prints
ssh "deployer@$REHEARSAL_IP" 'cd /opt/agentforge && sha256sum secrets/* | sha256sum'   # fingerprint of the secrets, compared after the restore
```

### 6. Rollback to tag `week1` (T4)

```bash
git worktree add /tmp/rb week1
/tmp/rb/infra/digitalocean/deploy.sh "$REHEARSAL_IP" "$REHEARSAL_HOST" "$TLS_EMAIL"
./smoke.sh "$REHEARSAL_HOST"
curl -s "https://$REHEARSAL_HOST/copilot-api/health"
```

The `week1` tree has no `alerts` service and its `start.sh` has neither the
Caddy recovery nor the gates: expect a Compose warning about the orphan
`alerts` container (harmless, it keeps running the HEAD image) and keep
`ssh "deployer@$REHEARSAL_IP" 'cd /opt/agentforge && docker compose up --detach --wait --wait-timeout 120 caddy'`
at hand. Then the golden run again with `--label "rehearsal: week1 rollback"`
(step 4, last three lines). T4 runs from the `deploy.sh` call to the first
green `smoke.sh`.

### 7. Roll forward to HEAD (T5)

From the main checkout, at HEAD:

```bash
./deploy.sh "$REHEARSAL_IP" "$REHEARSAL_HOST" "$TLS_EMAIL"
./smoke.sh "$REHEARSAL_HOST"
curl -s "https://$REHEARSAL_HOST/copilot-api/health"
ssh "deployer@$REHEARSAL_IP" 'cd /opt/agentforge && docker compose ps'   # alerts running again
```

### 8. Restore (T6)

```bash
./restore.sh --host "$REHEARSAL_IP" --archive ~/.config/agentforge/backups/<file from step 5>
./smoke.sh "$REHEARSAL_HOST"
curl -s "https://$REHEARSAL_HOST/copilot-api/ready"
ssh "deployer@$REHEARSAL_IP" 'cd /opt/agentforge && sha256sum secrets/* | sha256sum'   # equals the step-5 fingerprint
```

Then the golden run once more with `--label "rehearsal: restore"`. To make
the restore prove something, change state between steps 5 and 8 (one panel
turn after the roll-forward creates a conversation in `agent_state`) and
confirm it is gone afterwards. T6 runs from the `restore.sh` call to the
first green `smoke.sh`.

### 9. Destroy the same day (T7)

```bash
./tf.sh workspace show                   # must print: rehearsal
./tf.sh destroy "${REHEARSAL_VARS[@]}"   # answer yes
./tf.sh workspace select default
./tf.sh workspace delete rehearsal
ssh-add -d ~/.ssh/agentforge_rehearsal && rm ~/.ssh/agentforge_rehearsal ~/.ssh/agentforge_rehearsal.pub
ssh-keygen -R "$REHEARSAL_IP"
git worktree remove /tmp/rb
unset DIGITALOCEAN_TOKEN
```

Confirm in the control panel, or with the resource-count loop under
"Configure", that the count is back to what it was before step 2 (the live
Droplet and the CI runner remain).

### Timings

Filled during the M4 rehearsal; an empty row means that step has not been
rehearsed.

Rehearsed 2026-09-18 against a `s-2vcpu-4gb` at `146.190.154.222`
(`agentforge-rehearsal`), owner-run with the orchestrator driving once SSH was
working and watching/timing throughout, per the human-gate above. Two real
issues found and fixed along the way, not artifacts of the rehearsal itself:
`deploy.sh`'s bootstrap-wait loop (36 attempts, 5s each = 180s) was too short
for a droplet whose SSH agent identity wasn't resolving yet on the operator's
machine (fixed locally with an `IdentityFile`/`IdentitiesOnly` pin in
`~/.ssh/config`, not a script change); and `push-secrets.sh`'s call inside
`deploy.sh` failing silently (`2>/dev/null ... || true`) meant the first T1
attempt deployed with `llm_provider`/`tracer` both `not_configured` and the
golden run passed 12/14 instead of 14/14 on two cases that require a real
model turn — re-running `push-secrets.sh` directly surfaced and fixed it. T6
also found and fixed a real `restore.sh` bug: `printf '--- end manifest
---\n\n'` at line 217 made bash's `printf` builtin misparse the leading `---`
as an option and abort (`printf: --: invalid option`) — always right after
printing the manifest, always before the destructive part, so nothing was at
risk, but the script never reached the confirmation prompt until fixed with
`printf -- '...'`. Restore was proven to actually restore, not no-op: a real
conversation turn created after the T3 backup came back
`{"code":"invalid_request","message":"Unknown conversation."}` after the T6
restore. Destroy left the account at exactly its pre-rehearsal resource count
(the live Droplet and the CI runner only).

| Step | Started (UTC) | Finished (UTC) | Wall-clock | Notes |
| --- | --- | --- | --- | --- |
| T1 clean deploy at HEAD | 08:47:03 | 08:49:39 | 2m36s | Second attempt; first attempt hit the SSH bootstrap-wait timeout (see above) and doesn't count toward this figure |
| T2 demo-seed and golden run | 08:32:30 | 08:35:40 | 3m10s | 14/14 golden; includes recovering from the `push-secrets.sh` gap (see above) |
| T3 `backup.sh` | 08:43:24 | 08:43:39 | 15s | `age` encryption; first attempt failed on a local gpg-agent/pinentry error, not counted |
| T4 rollback to `week1` (to green `smoke.sh`) | 08:47:03 | 08:49:39 | 2m36s | 14/14 golden on `week1` too; expected orphan-container warning for `alerts` (absent in that tag) |
| T5 roll forward to HEAD | 08:52:28 | 08:53:41 | 1m13s | All 5 services healthy, `alerts` back |
| T6 `restore.sh` (to green `smoke.sh`) | 09:00:18 | ~09:03:37 | ~3m19s | Finish time is the first post-restore `/ready` check, not a captured `smoke.sh` timestamp; found and fixed the `printf` bug above |
| T7 destroy | 09:11:55 | 09:12:~20 | ~25s | `tf.sh destroy` itself (droplet destruction was the long pole at 22s); confirmation typed, not auto-approved |

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
Since 2026-09-17 `start.sh` does this itself (a second `up --wait` on
`caddy`, then a running-services gate and a public liveness probe); the
manual command stays useful on a host deployed from an older tree, such as
the `week1` rollback target in the rehearsal runbook.

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
  the risk acceptance with its compensating controls is `AUDIT.md` section 9
  Residual Risk (SEC-MEDIUM-504), decided at plan M4 step 6.
- [x] **REST/FHIR** stay disabled and are unrouted at the edge (`/apis/*`,
  `/oauth2/*` 404).
- [x] **Readiness** from the agent's `/ready`; OpenEMR `readyz` is unrouted.
- [ ] Use an owned hostname and point DNS to the Droplet before the
  evaluator deployment; rotate deployment credentials.

**Documented, not changed here** (`AUDIT.md` §7.3; these are what a real
deployment would need): patched images and a vulnerability-scan gate
(SEC-HIGH-502); OpenEMR container hardening and removing `MYSQL_ROOT_PASS` from
its environment (SEC-MEDIUM-503); tested backup/restore and rollback
(COMP-MED-005) — `backup.sh`, `restore.sh` and the rehearsal runbook above
exist since 2026-09-17, and none of them has run against a host yet.
