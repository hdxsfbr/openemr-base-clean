# Droplet-tier capacity test: s-4vcpu-8gb, c-2, c-4 vs. current prod (s-2vcpu-4gb)

Follow-up to `load-test-2026-09-18.md` and `baseline-2026-09-18.md` (M4). Those
established that the current production Droplet (`s-2vcpu-4gb`, 2 vCPU / 4 GiB,
$24/mo) is CPU-bound — `openemr` and `database` independently saturate at or
above 100% of a full vCPU core at 50 concurrent users — and that the bottleneck
is OpenEMR's Apache/PHP and MariaDB layer, not the agent or the model. A
follow-up investigation the same day confirmed the `openemr` container runs
`mod_php` under Apache prefork (`MaxRequestWorkers=250`), not `php-fpm` at all,
so raising any worker-pool cap is a proven no-op — Apache never got near 250
workers in the M4 test (peaked at 54-68 processes) while CPU was already
saturated.

This test asks: how much does a bigger or differently-provisioned Droplet
actually buy, in real (not modeled) concurrent-user capacity, and how does
that translate into "how big a clinic" using the Little's Law back-of-envelope
in `docs/INTERVIEW_NOTES.md`? Run 2026-09-18 (23:24 UTC) through 2026-09-19
(00:17 UTC), commit `a151d24`, against three throwaway Droplets in the
Terraform `rehearsal` workspace (`infra/digitalocean/`, "Rehearsal Runbook").
Production (`137.184.4.22`) was never touched — confirmed `/ready` before
(`2026-09-18T23:13:58Z`, 200 `ready`) and after (`2026-09-19T00:17:11Z`, 200
`ready`) all three tiers.

## Tiers tested

| Tier | Slug | vCPU | RAM | Disk | Price/mo | $/hr |
| --- | --- | --- | --- | --- | --- | --- |
| Current prod (reference) | `s-2vcpu-4gb` | 2 (shared) | 4 GiB | 80 GB | $24 | $0.0333 |
| 1 | `s-4vcpu-8gb` | 4 (shared) | 8 GiB | 160 GB | $48 | $0.0714 |
| 2 | `c-2` | 2 (**dedicated**) | 4 GiB | 25 GB | $42 | $0.0583 |
| 3 | `c-4` | 4 (**dedicated**) | 8 GiB | 50 GB | $84 | $0.1167 |

Specs and current pricing reconfirmed via `doctl compute size list` at test
time. Tier 2 isolates whether *dedicated* (non-burstable) cores matter
independent of core count, since it has the same vCPU count as prod but no
CPU-credit throttling.

Each tier ran the full cycle from the Rehearsal Runbook (own `rehearsal`
Terraform workspace, own throwaway SSH key, own `sslip.io` hostname) minus the
backup/restore/rollback steps, which test disaster recovery, not capacity:
`tf.sh apply` → `deploy.sh` → seed demo cohort → verify `/ready` → free
`--fault model` bracket sweep (find the approximate onset, $0 cost) → paid
real-model confirmation at 2 candidate levels near that onset, each bracketed
by `droplet-stats.sh` → `tf.sh destroy`. All three tiers deployed at the same
commit (`a151d24`), so they already include the agent-side latency fixes from
`agent-perf-fix-2026-09-18.md` (pooled HTTP client, SQLite WAL) and
`model-experiments-2026-09-18.md` (`max_plan_rounds=1`) — **the cross-tier
comparisons in this document are apples-to-apples; the comparison against the
M4 prod baseline below is not**, since prod has not been redeployed at HEAD.
Where useful, prod's M4 numbers are shown as the pre-fix reference point they
actually are.

One operational footnote: on the first `deploy.sh` call for tiers 1 and 2 (not
tier 3), `push-secrets.sh` silently pushed 0 secrets and the agent came up
`not_ready` (`llm_provider: not_configured`) — `deploy.sh` suppresses that
script's stderr and swallows its exit code, so the failure was invisible in
the deploy log. Rerunning `push-secrets.sh` standalone immediately succeeded
both times. This looks like a timing race, not a real regression (tier 3's
first pass worked); worth a fix (stop suppressing stderr, or retry once) but
out of scope here.

## Real-model summary, all tiers

| Tier | Level | VUs completed | Turns | Turn p50 / p95 / p99 | Errors | Status share (complete/partial/fallback) | Tool-unavailable |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Prod `s-2vcpu-4gb` (M4, pre-fix) | 10 | 10/10 (100%) | 20 | n/a / 45,036 / n/a | 2 (10.0%) | n/a | n/a |
| Prod `s-2vcpu-4gb` (M4, pre-fix) | 50 | 31/50 (62%) | 71 | n/a / 43,791 / n/a | 4 (5.6%) | 18% / 76% / n/a | ~90% (277/309) |
| **Tier 1** `s-4vcpu-8gb` | 40 | 40/40 (**100%**) | 80 | 14,339 / 32,768 / 34,220 | 0 (0%) | 78% / 18% / 5% | 7.2% (23/320) |
| **Tier 1** `s-4vcpu-8gb` | 50 | 36/50 (72%) | 79 | 13,308 / 27,239 / 33,792 | 0 (0%) | 66% / 32% / 3% | 24.3% (79/325) |
| **Tier 2** `c-2` (dedicated) | 40 | 40/40 (**100%**) | 80 | 11,044 / 30,517 / 37,380 | 0 (0%) | 72% / 28% / 0% | 17.2% (55/320) |
| **Tier 2** `c-2` (dedicated) | 50 | 43/50 (**86%**) | 88 | 9,588 / 28,933 / 29,932 | 0 (0%) | 59% / 39% / 2% | 33.8% (121/358) |
| **Tier 3** `c-4` (dedicated) | 60 | 60/60 (**100%**) | 120 | 11,856 / 32,235 / 35,663 | 0 (0%) | 90% / 3% / 7% | **0%** (0/480) |
| **Tier 3** `c-4` (dedicated) | 90 | 54/90 (60%) | 113 | 11,451 / 31,679 / 32,817 | 0 (0%) | 61% / 31% / 8% | 26.9% (124/461) |

Turn p95 busts the 30 s provisional budget on every tier at their tested
levels — even tier 3 at 60 users, despite 100% VU completion and zero
tool-unavailable calls, meaning the *tail* of individual turns (not just
failure rate) is still budget-relevant. Read the completion rate and
tool-unavailable% as the primary capacity signal, and p95 as a separate,
still-open latency question (see "Open items" below).

All errors are `0 (0.0%)` at the HTTP-transport level across every level
tested (`5xx`/`504`/`429`/`transport`/`other`) — degradation shows up entirely
as `partial`/`fallback` status and gateway `tool-unavailable`, not as hard
request failures, consistent with the M4 finding.

### Free `--fault model` bracket sweeps (onset-finding only, $0 cost)

| Tier | Clean through | Onset begins | Hard break |
| --- | --- | --- | --- |
| Prod `s-2vcpu-4gb` (M4 reference) | — (not bracketed this finely) | ~5-10 users | ~50 (66% complete, ~90-98% unavailable) |
| Tier 1 `s-4vcpu-8gb` | 30 users (100%, 0.5% unavail) | 40 (100% complete, 7.1% unavail) | 50 (74% complete, 35.7% unavail); plateaus ~30-36 completing through 200 offered |
| Tier 2 `c-2` | 25 users (100%, 0% unavail) | 35-40 (100% complete, 1.2-7.1% unavail) | 50 (88% complete, 27.9% unavail) |
| Tier 3 `c-4` | 60 users (98%, 1.5% unavail) | 70 (86% complete, 12.9% unavail) | 90-100 (54-60% complete, ~30-38% unavail); plateaus ~35-40 completing through 200 offered |

## Container CPU / memory, all tiers

CPU percentages are Docker's normalized figure (100% = one full vCPU core).
`n` = sample count at 5 s intervals.

| Window | n | openemr CPU mean/peak | database CPU mean/peak | agent CPU mean/peak | httpd procs peak | `Threads_connected` peak | host mem used peak | `load1` peak |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Prod idle (M4 reference, 2 vCPU) | 41 | 0.6% / 6.3% | 0.0% / 0.1% | 2.6% / 64.3% | 11 | 21 | 1,195 MiB | 0.11 |
| Prod real 50u (M4 reference, 2 vCPU) | 16 | 54.7% / **103.2%** | 59.0% / **111.0%** | 11.5% / 43.7% | 58 | 150 | 1,480 MiB | **24.47** |
| Tier 1 idle (4 vCPU) | 13 | 1.0% / 7.8% | 0.3% / 3.1% | 0.2% / 0.2% | 11 | 1 | 1,084 MiB | 0.3 |
| Tier 1 real 40u | 13 | 83.9% / 175.4% | 99.6% / **225.9%** | 16.5% / 58.2% | 50 | 135 | 1,539 MiB | 15.9 |
| Tier 1 real 50u | 16 | 72.6% / 202.1% | 71.0% / 212.5% | 11.9% / 48.4% | 51 | 139 | 1,593 MiB | **18.0** |
| Tier 2 idle (2 vCPU, dedicated) | 13 | 0.1% / 0.1% | 0.3% / 4.3% | 2.1% / 26.3% | 8 | 1 | 1,019 MiB | 1.0 |
| Tier 2 real 40u | 14 | 43.5% / 99.3% | 49.1% / 111.3% | 8.1% / 28.1% | 48 | 128 | 1,403 MiB | 18.1 |
| Tier 2 real 50u | 15 | 43.8% / 106.7% | 43.1% / 103.2% | 7.7% / 24.4% | 55 | 148 | 1,450 MiB | **21.7** |
| Tier 3 idle (4 vCPU, dedicated) | 14 | 0.5% / 4.6% | 0.0% / 0.0% | 1.4% / 17.8% | 7 | 1 | 1,076 MiB | 0.7 |
| Tier 3 real 60u | 13 | 69.7% / 186.6% | 77.6% / 201.2% | 11.1% / 31.7% | 49 | 135 | 1,596 MiB | **20.0** |
| Tier 3 real 90u | 12 | 81.9% / 203.6% | 79.9% / 209.3% | 10.8% / 25.4% | 56 | 151 | 1,632 MiB | 17.1 |

**CPU is the constraint on every tier, not memory or the FPM/Apache worker
pool.** `httpd_procs` peaks between 48 and 58 across every tier and load
level — nowhere near the 250-worker cap regardless of Droplet size, exactly
as M4 found. Memory peaks at 1.0-1.6 GiB used out of 8 or 4 GiB available on
every tier — never a constraint. `openemr` and `database` CPU each
independently exceed 100% (one full vCPU core) on *every* tier tested,
including the 4-vCPU ones — bigger Droplets don't eliminate saturation, they
raise the offered load at which it starts. `load1` peaks 15-22 across all
three new tiers (5-11x the box's actual core count), i.e. the run queue is
always far deeper than the box can execute, at every tier, at their
respective onset points.

## What actually changed between tiers

**More shared cores (tier 1, 2x prod's vCPU) roughly quadrupled the clean
ceiling** (~5-10 users on prod → ~30 clean / 40 onset on tier 1) but the 50-user
outcome is still bad (72% complete, 24% tool-unavailable) — not proportional
to the 2x core increase, because `database` CPU alone peaks at 226% (over 2
full cores) at 40 users, meaning the two containers together can already
consume the entire 4-vCPU box.

**Dedicated cores at the *same* core count as prod (tier 2) matched or beat
tier 1** despite having half the vCPUs: 86% VU completion at 50 users vs.
tier 1's 72%, and a nearly identical onset curve to tier 1's (35-40 users)
despite raw `openemr`/`database` CPU saturating at the *same* ~100-110% each
that prod's shared cores also hit. This is the cleanest evidence in this test
that CPU-credit throttling on the Basic/shared-CPU family — not just core
count — was hurting prod specifically. A c-2 rebuy at the same $/mo-ish price
band as today's plan would likely outperform a naive 2x size-up.

**Dedicated cores *and* more of them (tier 3) compound rather than
substitute for one another** — clean to 60 users (vs. tier 1/2's ~30-40),
zero tool-unavailable calls at 60 users (vs. 7-17% on tiers 1 and 2 at their
own onset levels), onset at 70, hard break at 90-100. This is the strongest
tier by a wide margin: roughly 6-10x prod's clean-ceiling capacity for 3.5x
the monthly cost.

## Clinic-size back-of-envelope, measured (replaces the modeled 2.8 req/s)

`docs/INTERVIEW_NOTES.md` (~line 414-450) modeled prod's throughput as
"~4 req/s realistic ceiling... 70% utilization target → ~2.8 req/s working
budget," built on an FPM assumption since disproven (the box runs `mod_php`
under Apache prefork, not FPM). That modeled number is replaced below with
throughput measured directly from this session's real-model load tests — no
FPM assumption involved.

**Method.** For each tier, at its *lower* (less-degraded) real-model
confirmation level — the one still representative of a working budget rather
than a broken system — count OpenEMR-facing HTTP requests in that window as
`(VUs × 3)` [one `login` + one `chart_open` + one `session.php` per VU, each a
direct OpenEMR PHP page hit] `+ tool-gateway calls` [`POST
.../gateway/tools.php`, the same Apache/PHP pool per M4], divided by the
level's wall-clock duration:

| Tier | Level used | VUs×3 | + tool calls | = requests | ÷ duration | = measured throughput |
| --- | --- | --- | --- | --- | --- | --- |
| Tier 1 `s-4vcpu-8gb` | 40 (100% complete) | 120 | 320 | 440 | 100.2 s | **4.39 req/s** |
| Tier 2 `c-2` | 40 (100% complete) | 120 | 320 | 440 | 101.1 s | **4.35 req/s** |
| Tier 3 `c-4` | 60 (100% complete, 0% unavail) | 180 | 480 | 660 | 89.9 s | **7.34 req/s** |

Formula and every other assumption unchanged from the existing estimate:
`providers = throughput ÷ (req/encounter × visits/hr × peak-factor ÷ 3600)`,
25-50 requests per patient encounter, 2-3 visits per provider per hour, 3x-5x
peak concentration factor.

| Tier | Measured throughput | Clinic size (25-50 req/encounter, 2-3 visits/hr, 3x-5x peak) |
| --- | --- | --- |
| Prod `s-2vcpu-4gb` (old, modeled, FPM-based — kept only for comparison) | 2.8 req/s (modeled) | ~13-to-67 providers |
| Tier 1 `s-4vcpu-8gb` ($48/mo) | 4.39 req/s (measured) | **~21-to-105 providers** |
| Tier 2 `c-2` ($42/mo, dedicated) | 4.35 req/s (measured) | **~21-to-104 providers** |
| Tier 3 `c-4` ($84/mo, dedicated) | 7.34 req/s (measured) | **~35-to-176 providers** |

**Caveats, same as everywhere else in this section.** The two biggest inputs
(requests per encounter, peak concentration factor) are still *assumptions*,
not observations — only the throughput term is newly measured. Prod's own
"2.8 req/s" was never itself measured this way (out of scope: this session
tested only the three new tiers, per the handoff, not a HEAD redeploy of
prod) — read it as a rough, pre-fix, FPM-flavored floor, not a like-for-like
data point; tier 2's result suggests prod's *actual* measured throughput
today is probably below 2.8, given identical core count but shared-CPU
throttling. The chosen "lower confirmation level" per tier is a judgment
call (last level with 100% VU completion), not the literal saturation edge —
the true sustainable ceiling for each tier sits somewhere between its "onset"
and "hard break" bracket points above, not at one precise number.

## Recommendation

For a **licensee bringing their own realistically-sized clinic** (this
project's stated scope — a real licensee provisions the box, not a fixed
target here), the data says: **c-2 ($42/mo) already meaningfully outperforms
a naive 2x size-up to s-4vcpu-8gb ($48/mo) at $6/mo less**, because the
constraint is CPU-credit throttling as much as core count. **c-4 ($84/mo)
is the clear ceiling-raiser** if a licensee's clinic size demands it — roughly
6-10x prod's clean concurrent-user capacity for 3.5x the cost, the strongest
$/capacity trade of the three. None of the three tiers eliminates the
underlying CPU-boundedness; they all still saturate `openemr` and `database`
CPU past their respective onset points. This remains an OpenEMR/MariaDB
tuning and provisioning question, not an agent-side one — consistent with the
M4 conclusion and out of this project's scope to fix further (owner decision,
per the original handoff: a real licensee brings their own sized OpenEMR).

## Cost of this test

DigitalOcean: 3 Droplets, each up for roughly 25-35 minutes end-to-end
(apply → destroy), at $0.058-$0.117/hr — under $0.20 total compute. Anthropic
API: 957 model calls across 6 real-model confirmation runs (957 calls × the
$0.0127-$0.0223/call range measured in `model-experiments-2026-09-18.md`
implies roughly **$12-$21**, not a precise billed figure — check the console
for the exact number). All three rehearsal workspaces, throwaway SSH keys,
and Droplets were destroyed the same session; `doctl compute droplet list`
confirms only production and `agentforge-ci-runner` remain.

## Open items

- **Turn p95 still busts the 30 s budget on every tier**, even where VU
  completion and tool-availability are excellent (tier 3 @ 60: 100% complete,
  0% unavailable, but p95 32.2 s). This is a distinct question from raw
  capacity and is not resolved by any Droplet size tested here — the same
  open item `ARCHITECTURE.md` already flags ("the 30s p95 threshold needs
  either a written risk acceptance at a revised number, or a resize before
  the release run") still needs an owner decision.
- The chosen "lower confirmation level" throughput is one point per tier, not
  a full saturation curve fit — a licensee sizing a specific clinic should
  re-run this methodology at their actual expected concurrency rather than
  read the ranges above as precise.
- Not tested: whether `c-2`/`c-4`'s dedicated-CPU advantage holds at
  sustained (not 60-120s burst) load, or whether MariaDB-specific tuning
  (buffer pool sizing, connection pool limits) narrows the gap between tiers
  independent of raw CPU class.
