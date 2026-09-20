# AI Cost Analysis

Cost deliverable for the AgentForge Clinical Co-Pilot. Part A is what the
project has cost to build through 2026-09-20. Part B is what one co-pilot turn
costs at runtime and what that projects to at 100, 1K, 10K, and 100K users.
Every number that is not measured is labeled as an assumption or estimate.

## Prices used

| Item | Price | Source and date |
| --- | ---: | --- |
| Sonnet 5 base input | $2.00 / MTok | platform.claude.com/docs/en/about-claude/pricing, fetched 2026-09-15 |
| Sonnet 5 cache read | $0.20 / MTok | same page (0.1x base input) |
| Sonnet 5 5-minute cache write | $2.50 / MTok | same page (1.25x base input) |
| Sonnet 5 output | $10.00 / MTok | same page; the introductory $2/$10 rate is now standard |
| Droplet s-2vcpu-4gb | $24 / month ($0.03571 / h) | digitalocean.com/pricing/droplets, fetched 2026-09-15; matches `docs/deployment/digitalocean.md` and `infra/digitalocean/main.tf` |
| Droplet s-4vcpu-8gb | $48 / month ($0.07143 / h) | same sources |
| Langfuse Cloud | Hobby $0 (50K units), Core $29, Pro $199, overage $8 per 100K units | langfuse.com/pricing, fetched 2026-09-15 |

No repository file states Sonnet 5 per-token prices (`KEY_METRICS.md`,
`ARCHITECTURE.md`, and `docs/` were checked), so the published page is the
source.

## Part A: development cost through 2026-09-20

Measured from `git log`, the Terraform state, the DigitalOcean price list, and
the cost line every eval and load report writes into its own JSON.

| Item | Measured value |
| --- | --- |
| First project commit | 2026-09-11 (the base import of 2026-06-27 is upstream OpenEMR, not project work) |
| Calendar days elapsed | 10 (2026-09-11 to 2026-09-20), 9 with commits |
| Project commits | 151 by Andre Batista; 95 carry `Assisted-by: Claude Code` and 136 carry `Co-Authored-By` |
| Working time | Not reliably derivable from commit timestamps: several commits carry UTC rather than local offsets, which inflates any same-day first-to-last span (one date spans 25 h). The honest figure is the engineer-time estimate below |
| Droplet uptime | Production `s-2vcpu-4gb` created 2026-09-15 19:12 UTC and kept up since (106 h); CI runner `s-1vcpu-1gb` since 2026-09-16 05:04 UTC (96 h); three tier-comparison Droplets ~30 min each on 2026-09-18; one rehearsal Droplet ~40 min on 2026-09-18; two smoke windows on 2026-09-14 |

| Cost line | Amount | Basis |
| --- | ---: | --- |
| Production Droplet | $3.78 | 106 h at $0.03571/h; accrues $0.86/day while up |
| CI runner Droplet | $0.86 | 96 h at $0.00893/h |
| Tier-comparison and rehearsal Droplets | under $0.30 | Three tiers at $0.058–$0.117/h for ~30 min each (`docs/audit/evidence/performance/droplet-tier-comparison-2026-09-18.md`), plus the rehearsal host; all destroyed the same session |
| Snapshot storage | under $0.50 | `week1-final-2026-09-18` and the final snapshot at $0.06 per GB-month, prorated over days, not months |
| Observability (Langfuse hosted) | $0 | Hobby tier, per ADR-0007 |
| Model calls, eval runs | $9.79 measured | Sum of the `cost_usd_total` each report in `evals/results/` writes, at list price |
| Model calls, load tests | about $1.55 | The 10- and 50-user real-model runs of 2026-09-18; the `--fault model` control runs cost $0 |
| Model calls, tier-comparison runs | about $12–21 | 957 model calls across six real-model confirmation runs, priced at the $0.0127–$0.0223 per-call range measured the same day; not a billed figure |
| Model calls, interactive development | not metered | Hand-typed turns during development were never exported into the repo. The four post-deploy turns in Part B are the only ones with a recorded cost |
| AI assistance (Claude Code) | Estimate: $200–$800 list-price equivalent | No metered figure exists in the repo. Assumption: 40–70 assisted hours across 9 days at $10–$25/h at list prices. Usage ran on a subscription, so marginal cash cost was lower |
| Engineer time | 40–70 h (not priced) | No hourly rate is given in the project |

Measured, attributable cash spend is about $29–$38: roughly
$5 of infrastructure and $23–$32 of model calls, of which the
single largest line is not the product at all — it is the tier-comparison
capacity test, which spent more on the model in one afternoon than every eval
run of the week combined. The AI-assistance estimate dominates any fully
loaded figure, and remains an estimate.

**Teardown.** Both Droplets stay up until grading and the final AI interview
are confirmed, then the rotation checklist in
`docs/deployment/digitalocean.md` runs and they are destroyed. At $0.86 and
$0.21 per day they are the only lines still accruing.

## Part B: runtime cost per turn

Measured from the live deployment's `/metrics` counters after the last deploy:
4 turns, 11 model calls, input_tokens 4,097, output_tokens 7,798,
cache_read_tokens 14,551. Turn latency measured at 12 to 22 s. Model is
claude-sonnet-5 (ADR-0004). The counters carry no cache-write tokens at all:
the API reports them as `cache_creation_input_tokens`, outside
`input_tokens`, and `agent/app/model.py` (`_usage_of`) stores only
`input_tokens`, `output_tokens` and `cache_read_input_tokens`, so the
evidence pack and the system prompt (both sent with `cache_control`) are
priced at nothing the first time each is seen, not folded into the input
line below. The write line's size is not recoverable from the recorded
counters; storing `cache_creation_input_tokens` in `Usage` is the change
that would measure it.

| Per-turn line | Tokens | Rate | Cost |
| --- | ---: | ---: | ---: |
| Uncached input | 1,024 | $2.00 / MTok | $0.00205 |
| Cache-read input | 3,640 | $0.20 / MTok | $0.00073 |
| Output | 1,950 | $10.00 / MTok | $0.01950 |
| Total per turn (about 2.75 model calls) | | | **$0.0223** |
| Same turn with no cache discount (3,640 at $2.00) | | | $0.0288 |

Output tokens are 87 percent of the cost. Prompt caching saves $0.0066 per
turn, or 23 percent.

**Re-measured 2026-09-16 by the eval scorecard** (`evals/run.py`, same
list prices as the table above, `PRICE_PER_MTOK`). Latest tracked full run,
`evals/results/2026-09-16T073141Z-1ddf824.md`, 120 model-backed turns
(44 cases x 3 attempts): 2.24 model calls per turn, 608 input / 1,170
output / 5,106 cache-read tokens per turn, **$0.0127 per turn** (run total
$1.53). A later single full run at `69560f0`
(`evals/results/2026-09-16T081636Z-69560f05.md`) measured 2.3 calls, 612 / 1,139 / 4,870 tokens, $0.0124 per turn.
Two caveats on the scorecard figure. It is a lower bound, in two ways. The
runner that wrote every report through `a4a5856` priced uncached input as
`input_tokens - cache_read_tokens` clamped at zero, although the agent
reports the API's `input_tokens`, which is already net of cache reads
(`agent/app/model.py`, `_usage_of`), so with 608 uncached input tokens
against 5,106 cache reads the uncached-input line was $0; corrected
2026-09-17 in `evals/run.py` (`_cost_usd` now prices `input_tokens` at the
base rate with nothing subtracted), which raises the figure by about 10%
(`1ddf824` recomputes from its JSON to $0.0139 and `a4a5856` to $0.0139
against the $0.0127 both printed; the nine scorecard reports move from
$0.0121-$0.0141 to $0.0133-$0.0155). The recorded reports keep the figures
they printed, and a `compare.py` cost delta across that boundary carries
about +$0.0013 of correction. And cache writes are not counted at all: the
API reports them as `cache_creation_input_tokens`, outside `input_tokens`,
and the agent does not store that counter, although both the system prompt
and the evidence pack carry `cache_control`. The other caveat is that it is
the eval mix (about 45 percent follow-ups), not the usage model below. The projections below keep the earlier, higher
$0.0223 figure as the conservative basis, and since 2026-09-17 it is also
the eval runner's cost gate (`COST_PER_TURN_PROJECTION_USD = 0.0223` in
`evals/run.py`, beside `PRICE_PER_MTOK`; `cost_gate()`): PASS at or under
$0.0223 per model-backed turn; PASS (warn) between $0.0223 and $0.0446,
where the row's value text asks for risk acceptance in the report; FAIL and
release-blocking above $0.0446; NOT CONFIGURED only when a run had no
model-backed turn (`--offline-only`). Why the basis is higher than the eval
mix: the difference is output tokens, not a setting. The four post-deploy
turns above emitted about 1,950 output tokens each (7,798 over 4 turns)
against about 1,170 per turn in the eval mix (1,170 at `1ddf824` over 120
model-backed turns, 1,172 at `a4a5856` over 40, and 1,115 to 1,306 across
the nine live-run JSON reports that carry a scorecard). Output is priced at
$10 per MTok, so that gap alone is about $0.0078 of the $0.0096 difference;
the rest is the uncached-input line ($0.00205 in the four turns against $0
in the eval reports through `a4a5856`, which the runner printed because of
the clamp described above; at the corrected arithmetic the eval line is
about $0.0012 at 608 input tokens and the difference narrows to about
$0.0084), less a slightly larger cache-read line in the eval mix. No setting differs: `agent/app/settings.py` (model id, effort,
planning rounds, `max_output_tokens`) has not changed since before either
measurement; the narration prompt in `agent/app/model.py` changed once, at
`26a9a3d` on 2026-09-15, between the two, and the eval figure is the same on
both sides of that commit ($0.0127 at `836be65` before it, $0.0121 to
$0.0141 after). The likely cause is the question mix: the four turns were
hand-typed first questions on long charts, the eval mix is scripted with
about 45 percent follow-ups. So the eval figure is the lower bound, the
four-turn figure is the basis, and the gate's warn band (one to two times)
is where a token-mix change shows before it costs anything.

### Daily budget (from the token halt)

`agent/app/budget.py` halts model calls for the rest of the UTC day once
`daily_token_halt` (`agent/app/settings.py`, default 2,000,000; environment
`COPILOT_DAILY_TOKEN_HALT`) is reached, and every further turn takes the
deterministic fallback with the `model_budget_exhausted` limitation. The
counter adds `Usage.total`, which is input plus output tokens (cache reads
are not counted), and only for the narration and repair calls; the planning
call's tokens are added to the turn's own usage but not to the daily counter
(`agent/app/graph/nodes.py`). Per turn, the counted tokens are therefore at
most the scorecard's input plus output, and the halt allows at least:

| Token mix | Input + output per turn | Turns before the halt (at least) | List-price cost per turn | Model cost per day at the halt (at least) |
| --- | ---: | ---: | ---: | ---: |
| Eval mix (`1ddf824`, 120 model-backed turns) | 608 + 1,170 = 1,778 | about 1,125 | $0.0127 as printed; $0.0139 at the corrected arithmetic | about $14 as printed; about $15.6 corrected |
| Four post-deploy turns (Part B) | 1,024 + 1,950 = 2,974 | about 672 | $0.0223 | about $15 |

(2,000,000 / 1,778 = 1,125 and 1,125 x $0.0127 = $14.29, or $15.64 at the
corrected $0.0139; 2,000,000 / 2,974 = 672 and 672 x $0.0223 = $14.99.)
Either mix lands at about $14 to $16 of model spend per UTC day when the
halt fires; the **daily budget stays $14 per UTC day (warn) and $42 (page,
three times)**, set from the printed figures and not re-derived here. Spend past $15 in a day
means the halt did not hold or planning tokens dominated: `DailySpend` is
in-process memory, one counter per agent process, reset by a restart and not
shared across replicas, so a page at three times the budget is a detector of
a restarted or scaled-out agent (or of planning-heavy traffic), not a
normal-operation threshold. No cost alert evaluates this yet: the inputs are
the `copilot_tokens_total{kind=...}` counters on `/metrics`
(`agent/app/metrics.py`) priced at the rates above, and the check is manual
until an alert is written. The halt is a token ceiling, not a dollar one; at
the projection basis 1,100 turns would cost about $25, which is why the
budget is stated from the measured mixes and not from the basis.

### Usage model (assumption)

Each user is a primary-care physician who runs the co-pilot before each
visit: 20 visits per working day, 1 UC-01 turn plus 1 follow-up per visit on
average, 22 working days per month. That is 880 turns per user per month, or
$19.60 of model cost per user per month.

### Projections

| Users | Turns / month | Model cost | Infrastructure | Langfuse | Total / month |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 100 | 88,000 | $1,960 | $24 | $106 | $2,090 |
| 1,000 | 880,000 | $19,603 | $96 | about $930 | about $20,630 |
| 10,000 | 8,800,000 | $196,029 | $288 plus load balancer and managed database (not priced) | about $500 (self-hosted) | about $196,800 |
| 100,000 | 88,000,000 | $1,960,288 | $2,400 plus load balancer and managed database (not priced) | about $3,000 (self-hosted) | about $1,966,000 |

Infrastructure assumptions: one s-2vcpu-4gb Droplet carries everything up to
100 users (about 2.4 concurrent turns at peak). Beyond that, the agent
service and OpenEMR split onto separate s-4vcpu-8gb Droplets. The agent
service is async and waits on the model, so one node is assumed per 100
concurrent turns; at 17 s per turn over an 8 hour clinic day that is about
24 concurrent turns at 1K users, 240 at 10K, and 2,360 at 100K, giving 1, 3,
and 25 agent nodes with matching OpenEMR nodes. OpenEMR at 100K users is a
multi-site deployment and is outside this estimate.

Langfuse assumptions: about 12 units per turn (1 trace, 8 node spans, about
3 generations). Core plus overage at 100 users, Pro plus overage at 1K, and
self-hosted (ADR-0007's real-deployment path) above that with rough hosting
figures. Sampling traces at 10 percent would cut these lines by about 90
percent.

### What breaks first, by tier

The node counts above size the agent service (1 node per ~100 concurrent
turns) and assume matching OpenEMR nodes at the same count. The M4 load test
(2026-09-18, `docs/audit/evidence/performance/{load-test,baseline}-2026-09-18.md`)
found that assumption backwards: at 10 and 50 concurrent turns against a
single `s-2vcpu-4gb` Droplet, the agent's own CPU never exceeded 54% peak /
12% mean — nowhere near saturated — while OpenEMR's Apache/PHP and MariaDB
each independently saturated a full vCPU core, and turn p95 was already
45.0 s (past the 30 s budget) at just 10 concurrent turns. Every tool call is
an HTTP request from the agent back into the same OpenEMR/Apache process pool
that serves the browser UI (`agent/app/gateway_client.py:44`,
`tools.php:21`), so OpenEMR/MariaDB CPU is the real ceiling, not the agent,
and it is reached at roughly a tenth of the concurrency the current node
counts assume.

| Tier | Assumed peak concurrency | What breaks first | Change | Cost effect |
| --- | ---: | --- | --- | --- |
| 100 users | ~2.4 | Nothing measured — comfortably under the ~10-concurrent-turn range where the single co-located Droplet was already marginal in testing | None | No change to the $24/mo line |
| 1,000 users | ~24 | OpenEMR/MariaDB CPU on the Droplet, not the agent (1 agent node would be genuinely sufficient; 1 matching OpenEMR node, as currently assumed, would not) | Split OpenEMR+MariaDB onto Droplet(s) sized to OpenEMR's measured ceiling, decoupled from the agent's node count | The $96/mo figure assumes 1:1 agent:OpenEMR nodes; keeping OpenEMR under its measured ceiling at ~24 concurrent likely needs multiple OpenEMR-side nodes even with only 1 agent node — this tier's infra cost is understated in the table above |
| 10,000 users | ~240 | Same OpenEMR/MariaDB CPU wall, at a scale where the load balancer and managed database already flagged "not priced" become load-bearing, not optional | Managed database with real horizontal read scaling, load balancer across many OpenEMR nodes sized to the measured per-node ceiling rather than the agent's | The $288/mo figure is an order-of-magnitude understatement once OpenEMR is sized to its measured ceiling instead of the agent's; not repriced here pending a capacity curve past 50 concurrent |
| 100,000 users | ~2,360 | Same, at the scale the doc already scopes out | Multi-site OpenEMR architecture (existing scope boundary, unchanged) | Not estimated, consistent with the text above |

None of this changes the qualitative conclusion below (model cost dominates
by a wide enough margin that even a 5-10x infra correction at the 1K-10K
tiers stays a small fraction of the model line) — but the specific
per-tier infrastructure dollar figures above 100 users should be read as
directionally low, not firm quotes, until a load test runs past 50
concurrent turns.

### Sensitivity

- Follow-ups per visit double (3 turns per visit): 1,320 turns per user per
  month, $29.40 per user, and every model line above rises 1.5x ($2,940 at
  100 users, $2.94M at 100K).
- Prompt caching off: $0.0288 per turn, $25.37 per user per month, and the
  model line rises 29 percent ($2,537 at 100 users, $2.54M at 100K).
- Model cost scales linearly with users until the tier levers above apply
  (OpenEMR/MariaDB CPU forcing a node split once concurrency crosses the
  measured ~10-concurrent-turn ceiling per Droplet) — infrastructure and
  observability still stay a small fraction of the total at every tier even
  after that correction, so the model line remains the primary one worth
  optimizing, but "scales linearly" understates how the infrastructure line
  actually moves once the OpenEMR ceiling is crossed.

### Cheapest levers in the code today

1. **Skip the repair call when nothing is withheld.** Already the case:
   `agent/app/graph/nodes.py` routes `verify` straight to `render` when the
   verifier rejects nothing. The measured 2.75 calls per turn reflect this
   (2.24 in the 2026-09-16 eval scorecard, where 21.7 percent of
   model-backed turns needed a repair round); a repair costs about one
   narration when it does fire.
2. **Cap planning at one round for follow-ups.** Proposed change:
   `agent/app/settings.py` sets `max_plan_rounds = 3`; lowering it to 1 for
   follow-ups removes up to two planning calls on the worst turns and trims
   the 22 s latency tail. The saving is bounded by planning output, not
   narration.
3. **Shorter evidence packs.** `evidence_pack_max_chars = 48_000` (about 12K
   tokens) is the cache-read line. Halving it halves that line and shortens
   narration on long charts. Because output is 87 percent of per-turn cost,
   anything that reduces claims emitted per turn (a per-question claim cap) is
   worth more than any input-side change. A tighter `max_output_tokens` is not
   that lever: at 1,800, 10 percent of first-turn narrate calls were cut off
   mid-JSON and paid for a second full call (2026-09-19, about 3,000 output
   tokens across the two attempts where one uncapped call would have done),
   so the cap was raised to 3,200.
