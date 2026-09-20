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

Measured from `git log`, the Terraform state, the DigitalOcean price list, the
cost line every eval report writes into its own JSON, and the token counters
every load report writes into its own.

| Item | Measured value |
| --- | --- |
| First project commit | 2026-09-11 (the base import of 2026-06-27 is upstream OpenEMR, not project work) |
| Calendar days elapsed | 10 (2026-09-11 to 2026-09-20), 9 with commits |
| Project commits | 167 by Andre Batista at `ebaae17` (tag `week1-final`); 111 carry `Assisted-by: Claude Code` and 152 carry `Co-Authored-By` |
| Working time | Not reliably derivable from commit timestamps: several commits carry UTC rather than local offsets, which inflates any same-day first-to-last span (one date spans 25 h). The honest figure is the engineer-time estimate below |
| Droplet uptime | Production `s-2vcpu-4gb` created 2026-09-15 19:12 UTC and kept up since (109 h at 2026-09-20 08:00 UTC); CI runner `s-1vcpu-1gb` since 2026-09-16 05:04 UTC (99 h); three tier-comparison Droplets ~30 min each on 2026-09-18; one rehearsal Droplet ~40 min on 2026-09-18; two batched-gateway rehearsal Droplets under an hour each (`docs/audit/evidence/performance/batched-gateway-2026-09-19.md`); two smoke windows on 2026-09-14 |

| Cost line | Amount | Basis |
| --- | ---: | --- |
| Production Droplet | $3.89 | 109 h at $0.03571/h; accrues $0.86/day while up |
| CI runner Droplet | $0.88 | 99 h at $0.00893/h; accrues $0.21/day while up |
| Tier-comparison and rehearsal Droplets | under $0.40 | Three tiers at $0.058–$0.117/h for ~30 min each (`docs/audit/evidence/performance/droplet-tier-comparison-2026-09-18.md`, under $0.20), the rehearsal host, and the two batched-gateway rehearsal Droplets (under $0.10 by that evidence file); all destroyed the same session |
| Snapshot storage | under $0.50 | `week1-final-2026-09-18` and `week1-final-2026-09-20` at $0.06 per GB-month, prorated over days, not months |
| Observability (Langfuse hosted) | $0 | Hobby tier, per ADR-0007 |
| Model calls, eval runs | $11.58 measured | Sum of the `cost_usd_total` the 24 JSON reports in `evals/results/` write (the first, `c723920`, predates the scorecard and writes none), at list price: $9.79 through `6c787bd`, then $1.32 for the release run at `0f11642` and $0.47 for the single pass at the deployed tree (`4d2a9fd`). Reports from before the 2026-09-17 pricing fix keep the lower figure they printed (Part B) |
| Model calls, load and capacity runs | $12.18 measured | The `usage` token counters each real-model report in `evals/load/results/` writes, priced with the eval runner's `PRICE_PER_MTOK`: the M4 load test $0.76 (129 model calls), its re-run after the perf fix at `ba3105b` $0.79 (116), the six tier-comparison confirmation runs $8.57 (957), the batched-gateway experiments $1.99 (277), and a 2-user smoke $0.06 (9); 12.1755 before rounding. The `--fault model` runs cost $0. A turn that returned no body reports no usage (6 of 91 turns in the M4 run, 4 of 84 in the re-run, none elsewhere), so the first two lines are slightly low. The evidence files' own figures are rougher and read high: about $1.55 was the spend approved before the M4 run, and the tier-comparison and batched-gateway files' "$12–$21" and "$3.50–$6.20" multiply model calls by $0.0127–$0.0223, which is the cost of a turn of two to three calls, not of a call |
| Model calls, interactive development and unrecorded runs | not metered | Hand-typed turns during development were never exported into the repo; the four post-deploy turns in Part B are the only ones with a recorded cost. Also outside every sum above: the Markdown-only eval report `69560f05` ($0.49 as printed), CI live-eval jobs whose report stayed a CI artifact (job 79057 on pipeline 24351 is one; the four committed single passes of 2026-09-19 and 2026-09-20 cost $0.47 to $0.50 each), the real-model fixture A/B runs of `evals/prompt_ab.py`, the 12 briefs of `evals/brief_latency.py`, and the `evals/error_analysis.py` sampler; none writes a cost into the repo |
| AI assistance (Claude Code) | Estimate: $200–$800 list-price equivalent | No metered figure exists in the repo. Assumption: 40–70 assisted hours across 9 days at $10–$25/h at list prices. Usage ran on a subscription, so marginal cash cost was lower |
| Engineer time | 40–70 h (not priced) | No hourly rate is given in the project |

Measured, attributable cash spend is about $29: $5 to $6 of infrastructure
and about $24 of model calls at list price ($11.58 of eval runs, $12.18 of
load and capacity runs). Just over half of the model spend is not the product
being evaluated at all — it is capacity testing, and its largest part, the
tier comparison, spent $8.57 on the model in one afternoon. The
AI-assistance estimate dominates any fully loaded figure, and remains an
estimate.

**Teardown.** Both Droplets stay up until grading and the final AI interview
are confirmed, then the rotation checklist in
`docs/deployment/digitalocean.md` runs and they are destroyed. At $0.86 and
$0.21 per day they are the only lines still accruing.

## Part B: runtime cost per turn

Measured 2026-09-15 from the live deployment's `/metrics` counters after
that day's last deploy, and kept as the projection basis since: 4 turns, 11
model calls, input_tokens 4,097, output_tokens 7,798, cache_read_tokens
14,551. Turn latency measured at 12 to 22 s. Model is claude-sonnet-5
(ADR-0004). The counters carry no cache-write tokens at all:
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
list prices as the table above, `PRICE_PER_MTOK`). That day's tracked full
run, `evals/results/2026-09-16T073141Z-1ddf824.md`, 120 model-backed turns
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
$0.0084), less a slightly larger cache-read line in the eval mix. No setting
differed between the two: `agent/app/settings.py` (model id, effort, planning
rounds, `max_output_tokens`) did not change between those measurements (it
has since; see the 2026-09-20 re-measurement below); the narration prompt in
`agent/app/model.py` changed once, at
`26a9a3d` on 2026-09-15, between the two, and the eval figure is the same on
both sides of that commit ($0.0127 at `836be65` before it, $0.0121 to
$0.0141 after). The likely cause is the question mix: the four turns were
hand-typed first questions on long charts, the eval mix is scripted with
about 45 percent follow-ups. So the eval figure is the lower bound, the
four-turn figure is the basis, and the gate's warn band (one to two times)
is where a token-mix change shows before it costs anything.

**Re-measured 2026-09-20 by the release run.**
`evals/results/2026-09-20T051146Z-0f11642.md` (48 cases, 124 attempts, 126
model-backed turns): 1.56 model calls per turn, 293 input / 897 output /
4,413 cache-read tokens per turn, **$0.0104 per turn** (run total $1.32). It
is printed at the corrected arithmetic, so the like-for-like 2026-09-16
figure is $0.0139, not $0.0127. The single pass at the deployed runtime tree
(`evals/results/2026-09-20T064022Z-4d2a9fd.md`, 42 model-backed turns)
measured 1.62 calls, 308 / 985 / 4,164 tokens and $0.0113 per turn (run total
$0.47). This time the agent moved it, not the mix: `max_plan_rounds` 3 to 1
(`e2cd633`, 2026-09-18; $0.0133 to $0.0103 per turn on the suite,
`docs/audit/evidence/performance/model-experiments-2026-09-18.md`); no plan
call for the five follow-ups the agent writes itself (`KNOWN_PLANS`,
`089ef2b`, 2026-09-19; expected to save one model call, about $0.004, on
such a turn, not measured live,
`docs/audit/evidence/performance/known-plans-2026-09-19.md`); and follow-ups
at `low` effort (`f4f69ab`, 2026-09-19; $0.0116 to $0.0111,
`docs/audit/evidence/performance/followup-effort-2026-09-19.md`). The
narrate cap went the other way, 1,800 to 3,200 (`5d90982`), so that a
cut-off call is not paid for twice. Recomputed by turn type from the same
JSON, a UC-01 first turn costs $0.0118 (72 turns, 1,084 output tokens, 1.07
calls) and a follow-up $0.0086 (54 turns, 648 output tokens, 2.2 calls) at
`0f11642`, and $0.0135 and $0.0084 at `4d2a9fd`: the first turn is the more
expensive one, and it is the one brief-on-open spends (usage model below).
The basis and the gate stay $0.0223. Every full run since the gate was
configured printed $0.0103 to $0.0133, PASS without the warn band, so the
basis is now about twice the measured mix and the projections below are
conservative by about that factor.

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
| Release-run mix (`0f11642`, 126 model-backed turns) | 293 + 897 = 1,190 | about 1,680 | $0.0104 | about $17.5 |

(2,000,000 / 1,778 = 1,125 and 1,125 x $0.0127 = $14.29, or $15.64 at the
corrected $0.0139; 2,000,000 / 2,974 = 672 and 672 x $0.0223 = $14.99;
2,000,000 / 1,190 = 1,680 and 1,680 x $0.0104 = $17.47.)
The two earlier mixes land at about $14 to $16 of model spend per UTC day
when the halt fires. The release-run mix lands higher, about $17.5, although
each turn is cheaper, because output at $10 per MTok is now a larger share of
the tokens the halt counts (897 of 1,190, against 1,170 of 1,778); on it the
$14 warn line is crossed at about 1,350 turns, before the halt. The **daily
budget stays $14 per UTC day (warn) and $42 (page, three times)**, set from
the printed 2026-09-16 figures and not re-derived here. A brief prepared on
chart open counts toward the halt like any other narration. Spend well past
$18 in a day means the halt did not hold or planning tokens dominated:
`DailySpend` is in-process memory, one counter per agent process, reset by
a restart and not shared across replicas, so a page at three times the
budget is a detector of a restarted or scaled-out agent (or of
planning-heavy traffic), not a normal-operation threshold. No cost alert
evaluates this yet: the inputs are the `copilot_tokens_total{kind=...}`
counters on `/metrics` (`agent/app/metrics.py`) priced at the rates above,
and the check is manual until an alert is written. The halt is a token
ceiling, not a dollar one; at the projection basis 1,100 turns would cost
about $25, which is why the budget is stated from the measured mixes and not
from the basis.

### Usage model (assumption)

Each user is a primary-care physician who has the co-pilot's brief before
each visit: 20 visits per working day, 1 UC-01 turn plus 1 follow-up per
visit on average, 22 working days per month. That is 880 turns per user per
month, or $19.60 of model cost per user per month.

**Who starts the UC-01 turn (changed 2026-09-19, module 0.5.0).** Until
`789114a` the UC-01 turn was a click, so one per visit was an adoption
assumption. Since then the panel starts it itself as the chart finishes
loading, when `BriefPolicy` says so server-side (ADR-0003 amendment;
`COPILOT_BRIEF_ON_OPEN`). The code default is `visit_today`: a brief is
prepared when the open chart has a non-cancelled appointment dated today,
with any provider, for a user who holds at least one clinical section and is
not on a break-glass login. `off` restores the click, `always` prepares one
on every such chart open whatever the schedule, and an unknown value fails
closed to `off`. The demo Droplet runs `always`
(`infra/digitalocean/runtime/compose.yaml`), a demo override and not the
product default, so its own spend pattern is not the one projected here.

The 880 turns still hold under `visit_today`, and the table below is
unchanged, for this reason: the modeled physician opens each scheduled
patient's chart once per visit, that chart has a visit today, so one brief
per visit replaces the clicked UC-01 turn one for one, through the same turn
path at the same price. What changes is what the number means. The 440 UC-01
turns per user per month ($9.80 at the basis) are no longer spent when the
physician asks; they are spent when the chart opens, read or not, so they
are a floor set by the schedule and the mode, and only the 440 follow-ups
remain an adoption assumption. Three things start a brief that the model
above does not count, and none has a measured rate (the funnel counters in
`docs/operations/usage-funnel.md` exist for this, and no real session has
been recorded): a second clinical user opening the same chart (a brief
belongs to one user's conversation on one chart); the same user re-opening
it after the conversation's 30-minute idle window (inside it the transcript
is restored and no brief starts; a 60-second per-tab guard narrows, and does
not close, a reload mid-brief); and, in mode `always`, every chart open for
a patient not seen today. They are priced as parameters under Sensitivity.

An unread brief is priced in the commits that shipped it (`789114a`,
`4127593`) at about $0.011, which is the live suite's average over both turn
types at `f4f69ab4` ($0.0111). The first turn alone recomputes to $0.0118
and $0.0135 in the two 2026-09-20 runs (Part B above), and the 12 briefs of
the physician-wait run
(`docs/audit/evidence/performance/brief-latency-2026-09-19.md`) averaged
1,274 output tokens, $0.0127 of output alone; no other brief-specific cost
has been measured. All of it is under the $0.0223 basis, which the
projections apply to both turn types. Each brief also writes its
`copilot-tool-read` rows and two `copilot-model-disclosure` rows (one per
retrieval batch,
`docs/audit/evidence/compliance/04-model-disclosure-rows-2026-09-19.md`) to
OpenEMR's log table, read or not; that storage is not priced.

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
multi-site deployment and is outside this estimate. The 17 s is kept as the
assumption: it sits above the release run's model-backed p95 (15.8 s, p50
8.2 s) and the physician-wait run's turn p95 (16.9 s), so the concurrency
figures are upper bounds on that account.

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
45.0 s (past the 30 s budget) at just 10 concurrent turns. Every tool call
was then an HTTP request from the agent back into the same OpenEMR/Apache
process pool that serves the browser UI (`agent/app/gateway_client.py`; the
module's `public/gateway/tools.php` includes the same `interface/globals.php`
every chart page does), so OpenEMR/MariaDB CPU is the real ceiling, not the
agent, and it is reached at roughly a tenth of the concurrency the current
node counts assume.

Two fixes since then moved the numbers and not the ceiling. A pooled HTTP
client and checkpointer WAL mode (`ba3105b`,
`docs/audit/evidence/performance/agent-perf-fix-2026-09-18.md`) took the
50-user real-model turn p95 from 43.8 s to 30.5 s. Batching a turn's tool
fan-out into one or two gateway requests (`b40d456`,
`docs/audit/evidence/performance/batched-gateway-2026-09-19.md`, measured on
rehearsal Droplets of the same tier) brought 10 users to a 24.8 s turn p95
with every turn complete and no tool unavailable, and put the onset of
degradation between 10 and 15 users (37 percent of tool calls unavailable at
15), where both containers again exceed a full core. The table below
therefore stands. No load test has run with brief-on-open: the newest report
in `evals/load/results/` predates module 0.5.0, so the effect of a brief's
tool batches landing on OpenEMR at the same moment as the chart page that
triggered them is not measured.

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
concurrent turns. One has since, on single larger Droplets and not on the
node split priced here
(`docs/audit/evidence/performance/droplet-tier-comparison-2026-09-18.md`,
real model to 90 users): one `c-4` at $84 a month finished all 60 of 60
users with no tool call unavailable and 54 of 90 at the next level. It did
not reprice the figures above, which stay directionally low.

### Sensitivity

- Follow-ups per visit double (3 turns per visit): 1,320 turns per user per
  month, $29.40 per user, and every model line above rises 1.5x ($2,940 at
  100 users, $2.94M at 100K).
- One more brief per visit (a second clinical user opening the chart, or the
  physician re-opening it after the 30-minute idle window): the same
  arithmetic as the line above, 1,320 turns and $29.40 per user per month.
  How often either happens is not measured.
- Briefs prepared and never read, no follow-ups asked: the 440 UC-01 turns
  are still spent, $9.80 per user per month ($980 at 100 users, $0.98M at
  100K) for nothing. `drawer_open / brief_started` in
  `docs/operations/usage-funnel.md` is the measure; mode `off` spends
  nothing unasked and brings back the wait the brief removed (first turn p50
  9.7 s, p95 18.6 s in the release run).
- Mode `always` instead of `visit_today`: every chart open by a clinical
  user outside a visit (results, refills, messages) adds a brief. Each such
  open per working day adds 22 turns and $0.49 per user per month; chart
  opens per physician per day are not measured, so no total is given.
- Per-turn cost at the release run's $0.0104 instead of the basis: $9.15 per
  user per month, and every model line above is 47 percent of the figure
  shown ($915 at 100 users, $0.92M at 100K). The table keeps the basis
  because the basis is the gate.
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
   model-backed turns needed a repair round; 1.56 in the 2026-09-20 release
   run, 12.7 percent); a repair costs about one narration when it does fire.
2. **Cap planning at one round.** Done 2026-09-18 (`e2cd633`):
   `agent/app/settings.py` sets `max_plan_rounds = 1` (it was 3), and the
   runtime compose file defaults `COPILOT_MAX_PLAN_ROUNDS` to 1. On the live
   suite it took model calls per turn from 2.19 to 1.64, cost per turn from
   $0.0133 to $0.0103 and follow-up p95 from 28.9 s to 12.4 s with no case
   lost (`docs/audit/evidence/performance/model-experiments-2026-09-18.md`).
   Two smaller ones followed on 2026-09-19: the five follow-ups the agent
   writes itself skip the plan call (`KNOWN_PLANS`; about $0.004 each, not
   measured live), and follow-ups run at `low` effort (`effort_followup`;
   $0.0116 to $0.0111 per turn on the live suite).
3. **Choose the brief mode.** `COPILOT_BRIEF_ON_OPEN` decides how many UC-01
   first turns, the more expensive turn type, are spent without being asked
   for: `visit_today` (the code default) spends one per chart opened for a
   patient seen today, `always` one per chart open, `off` none. It is an
   environment variable, not a code change, and the funnel's waste rate is
   the number that should move it.
4. **Shorter evidence packs.** `evidence_pack_max_chars = 48_000` (about 12K
   tokens) is the cache-read line. Halving it halves that line and shortens
   narration on long charts. Because output is 87 percent of per-turn cost,
   anything that reduces claims emitted per turn (a per-question claim cap) is
   worth more than any input-side change. A tighter `max_output_tokens` is not
   that lever: at 1,800, 10 percent of first-turn narrate calls were cut off
   mid-JSON and paid for a second full call (2026-09-19, about 3,000 output
   tokens across the two attempts where one uncapped call would have done),
   so the cap was raised to 3,200.
