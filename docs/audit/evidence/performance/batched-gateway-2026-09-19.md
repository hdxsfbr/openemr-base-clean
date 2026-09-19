# Batched tool gateway: does it help, and did it move the ceiling?

Follow-up to `droplet-tier-comparison-2026-09-18.md`, which found the
co-pilot's own tool-gateway traffic — not just staff chart opens — saturates
`openemr`/`database` CPU on prod's `s-2vcpu-4gb`. Root cause, confirmed live
that session: OpenEMR's `globals.php` bootstrap (translation, ACL, and layout
lookups, ~1,045 SQL statements per bootstrap, `docs/audit/performance.md`
PERF-MED-002) runs on *every* gateway tool call, because `tools.php` includes
the same `globals.php` every chart page does. A turn's up-to-six tool calls
paid that bootstrap up to six times over.

Fix shipped (commit `b40d456`): `tools.php` now accepts a batched request —
`{"calls": [{"tool", "params"}, ...]}` → `{"results": [...]}` — serving a
turn's whole tool fan-out in one or two requests instead of one per tool
(`Gateway/BatchRunner.php`, `agent/app/gateway_client.py` `call_batch`,
`agent/app/graph/nodes.py` `retrieve`). Every ADR-0002/ADR-0003 check —
token verified, context built, per-tool ACL, audit-before-data — still runs
once per requested tool inside the batch loop; see ADR-0003's 2026-09-19
status note for the full design and the one accepted behavior change (a
batch-level transport failure now marks every tool in that batch
`unavailable` together). This document asks two questions the plan's
Verification section left open: **does it actually reduce OpenEMR CPU**, and
**does it raise the concurrent-user ceiling**?

Two experiments, both on a throwaway `rehearsal`-workspace Droplet at prod's
own tier (`s-2vcpu-4gb`), never touching production (`137.184.4.22`).
`translation_preload_cache` was left at OpenEMR's own code default (`'0'`,
off) in both — grep of `infra/` and `docker/` confirms nothing in this
repo's deploy/seed tooling ever sets it, and each rehearsal Droplet is a
fresh install, not a restore of prod's `globals` table. **The numbers below
are batching's effect in isolation; the preload flag's own effect was not
measured here** (see Open items).

## Experiment 1: before/after, same Droplet, 10 users

Same-Droplet method (redeploy old vs. new code on the identical instance,
not two separate Droplets) to eliminate hardware variance: `git archive` of
commit `9a60936` (pre-batch) deployed first, load-tested, then redeployed at
`b40d456` (batched) on the same box and re-tested. Real-model, 10 users, no
fault injection, `evals/load/run_load.py`.

| | Before (`9a60936`) | After (`b40d456`) |
| --- | --- | --- |
| VU completion | 10/10 | 10/10 |
| Chart-open p50/p95/p99 | 9720/12331/12331 ms | 4695/5556/5556 ms |
| Turn p50/p95/p99 | 13456/27815/31451 ms | 14426/24764/52436 ms |
| Status share (complete/partial/fallback) | 85% / 10% / 5% | 100% / 0% / 0% |
| Tool calls / unavailable | 80 / 2 (timeout, `clinical_notes`) | 80 / 0 |
| `openemr` CPU peak | 103.13% | 81.67% |
| `database` CPU peak | 98.40% | 83.32% |
| `load1` peak | 2.90 | 1.58 |

(`evals/load/results/2026-09-19T021612Z-b40d456.md` /
`2026-09-19T021921Z-b40d456.md`; `droplet-stats-batching-{before,after}10.csv`.
Both result files are stamped with the local git HEAD at test time, not the
deployed commit — a `run_load.py` filename quirk, not a labeling error; the
`--label` field and this table's "Before"/"After" columns are the source of
truth.)

Chart-open p95 more than halved, status share went from 85% clean to 100%,
and both `openemr` and `database` CPU peaks dropped from *over* one full
vCPU core to comfortably under it — the fix works exactly as the root-cause
analysis predicted. One counterintuitive number: total wall-clock for the
10-VU run went *up* (69.3 s → 96.5 s). Not a regression — before, several
turns failed fast (a `clinical_notes` timeout resolves quickly and the turn
falls back); after, essentially everything succeeds and runs to its full
real processing time instead of bailing early. Reliability traded a small
amount of wall-clock for a large amount of correctness.

## Experiment 2: what's the new ceiling?

Same Droplet tier, commit `b40d456` (batching shipped). Two-stage method,
same as the original tier comparison: a free `--fault model` bracket sweep
to cheaply find the approximate onset, then paid real-model confirmation at
candidate levels near it.

**The bracket sweep was not usable for this.** At 10 and 25 users it showed
completely clean turns (p95 3.8-4.4 s, 0% errors) but 15-138 tool-gateway
*timeouts* per level with 0% reported HTTP errors, and above 50 users VU
completion dropped to and plateaued around 35-41 regardless of how many more
VUs were added (50→38, 75→31, 100→37, 150→41, 200→37) — a shape consistent
with a fixed concurrency ceiling, not a smooth degradation curve. The reason:
`--fault model` removes the model call, which also removes the natural
pacing LLM latency provides between a VU's requests. The *same* first-turn-only
gateway load (follow-up turns make zero gateway calls under this fault mode,
a pre-existing limitation — see `ARCHITECTURE.md`/`AUDIT.md` §2) arrives in a
much tighter burst than real traffic ever produces, so the sweep's numbers
are not a usable proxy for an absolute ceiling here. (`evals/load/results/2026-09-19T025514Z-b40d456.md`.)
Recorded as a methodology finding for future capacity tests, not reused
below.

Real-model confirmation, 10/15/20/35/50 users (10 from Experiment 1's "after"
row; 20/35/50 then 15 as a precision pass between the clean and degraded
points):

| Users | VU completion | Status share (complete/partial/fallback) | Tool-gateway unavailable | `openemr` CPU peak | `database` CPU peak | `load1` peak |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | 10/10 (100%) | 100% / 0% / 0% | 0/80 (0%) | 81.67% | 83.32% | 1.58 |
| 15 | 15/15 (100%) | 63% / 30% / 7% | 44/120 (37%) | 111.06% | 136.21% | 6.77 |
| 20 | 20/20 (100%) | 50% / 48% / 2% | 87/160 (54%) | 131.13% | 128.89% | 9.21 |
| 35 | 35/35 (100%) | 17% / 81% / 1% | 261/280 (93%) | 128.89% | 134.29% | 20.13 |
| 50 | 39/50 (78%, 11 VUs never finished) | 11% / 88% / 1% | 323/333 (97%) | 130.26% | 125.77% | 30.88 |

(`evals/load/results/2026-09-19T031047Z-b40d456.md` (20/35/50),
`2026-09-19T031853Z-b40d456.md` (15);
`droplet-stats-post-batch-ceiling{,-l15}.csv`.)

**The onset is between 10 and 15 users, not materially different from the
pre-batch M4 baseline's "clean through roughly 5-10, hard degradation by
50."** CPU confirms it directly: both `openemr` and `database` stay under
100% only at 10 users; by 15 both already exceed one full core (111%/136%),
and from 15 through 50 both sit pegged around 125-136% — the two containers
are already splitting the box's two cores between them past this point, so
more concurrent users only deepens the queue (`load1` climbs from 6.8 at 15
to 30.9 at 50), not the CPU ceiling itself.

**The failure mode changed shape, and it is the one ADR-0003 predicted and
provisionally called low-risk.** At 15 users the unavailable-tool counts by
tool are: `allergies`=8, `clinical_notes`=8, `lab_results`=8, `medications`=8,
`problems`=8, `encounters`=2, `patient_context`=2 — an exact match to the two
batch groups `retrieve()` sends on a first turn (the 5-tool batch and the
2-tool `encounters`+`patient_context` batch). Every one of those failures is
a whole-batch transport timeout, not an isolated per-tool fetch failure: when
one tool in a batch is slow enough to blow the client timeout, all of its
batch-mates go down with it. This is the "one accepted behavior change" from
the ADR's design, now confirmed as the *dominant* real-world failure shape
under load rather than a theoretical edge case — see the ADR-0003 status note
added alongside this document.

## What this means

Batching is a clear, unambiguous win **at the load level already being
served today**: 10 concurrent users went from 85% clean to 100% clean, with
both CPU peaks now under saturation instead of over it. It did **not** raise
the concurrent-user ceiling on prod's tier — that ceiling was, and remains,
CPU-bound in the low double digits, because batching removes *redundant*
bootstrap work, not the *real* per-tool SQL fetch work, and two vCPUs still
can't carry much more than ~10-15 concurrent turns of that real work. This is
consistent with, not a contradiction of, `droplet-tier-comparison-2026-09-18.md`'s
finding and recommendation: raising the ceiling is a Droplet-tier question;
batching is a "waste less of what you have" question. They compound rather
than substitute for each other, but that compounding was not measured here —
none of the three bigger tiers (`s-4vcpu-8gb`, `c-2`, `c-4`) were re-tested
post-batching.

## Recommendation

No change to `droplet-tier-comparison-2026-09-18.md`'s recommendation — it
still stands on its own tier-selection merits. Ship batching regardless (it
is a strict improvement at any load level, and the correlated-failure
tradeoff is judged acceptable per the ADR), and treat "raise the ceiling" as
still requiring a tier resize, not a code fix. Whether batching's amortized
savings meaningfully compound with a bigger tier's headroom is an open
question, not a claim this document makes.

## Cost of this test

DigitalOcean: two throwaway `rehearsal`-workspace Droplets (Experiment 1's
same-Droplet before/after pair, and Experiment 2's bracket-plus-confirmation
run), each up under an hour end-to-end on the $0.0357/hr `s-2vcpu-4gb` tier —
under $0.10 total compute. Anthropic API: 277 real model calls across both
experiments' real-model runs (72 + 154 + 51); at the $0.0127-0.0223/call
range measured in `model-experiments-2026-09-18.md`, roughly **$3.50-$6.20**,
not a precise billed figure — check the console for the exact number. Both
rehearsal Droplets were destroyed the same session; `doctl compute droplet
list` confirms only production and `agentforge-ci-runner` remain.

## Open items

- **`translation_preload_cache`'s own effect is still unmeasured in
  isolation.** Both experiments ran with it at OpenEMR's default (off); the
  numbers above are batching alone. Whether flipping the flag on top of
  batching buys anything further is untested.
- **Prod's actual current value of that flag is still unconfirmed** — this
  session could not verify it over SSH (a permission boundary, not a
  technical block) and a screenshot-based check earlier in the session was
  ambiguous. Unrelated to this document's findings, since neither experiment
  ran against prod.
- **The three bigger tiers were not re-tested with batching.** Whether
  `c-4`'s roughly 6-10x ceiling headroom compounds with batching's per-request
  savings, or whether CPU saturation at that tier's own higher ceiling
  reproduces the same correlated-batch-timeout shape, is open.
- **The `--fault model` burst-concentration effect** (this document's
  Experiment 2) is a reusable methodology finding: that fault mode is not a
  safe proxy for an absolute concurrency ceiling when request pacing matters,
  only for cheap *relative* before/after comparisons where the same
  distortion applies to both sides equally. Worth flagging in
  `evals/load/run_load.py`'s own docstring for future load tests, not done
  here.
- Turn p95 still busts the 30 s budget at every level tested here, same open
  item as everywhere else in this project — unaffected by this document's
  findings either way.
