# AI Cost Analysis

Cost deliverable for the AgentForge Clinical Co-Pilot. Part A is what the
project has cost to build through 2026-09-15. Part B is what one co-pilot turn
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

## Part A: development cost through 2026-09-15

Measured from `git log`, `docs/PROJECT_PLAN.md`, `docs/deployment/digitalocean.md`,
and `infra/digitalocean/terraform.tfstate`.

| Item | Measured value |
| --- | --- |
| First project commit | 2026-09-11 (the base import of 2026-06-27 is upstream OpenEMR, not project work) |
| Calendar days elapsed | 5 (2026-09-11 to 2026-09-15), 4 with commits |
| Project commits | 36 by Andre Batista; 24 carry the `Assisted-by: Claude Code` trailer |
| Commit-bounded working spans | 0.3 h (09-11), 0.1 h (09-13), 6.8 h (09-14), 6.1 h (09-15), about 13 h total |
| Droplet uptime | Two smoke windows on 2026-09-14 (about 4 and 8 minutes), then one s-2vcpu-4gb Droplet created 2026-09-15 19:11 UTC and kept up for build days |

| Cost line | Amount | Basis |
| --- | ---: | --- |
| Infrastructure (Droplet) | about $0.20 measured to date | 12 minutes on 09-14 at $0.03571/h plus under 5 hours on 09-15; accrues $0.86 per day while kept up |
| Observability (Langfuse hosted) | $0 | Hobby tier, per ADR-0007 |
| Agent model calls during development | Estimate: $1 to $15 | Assumption: 50 to 200 development turns at $0.022 (Part B), up to 2.5x that for the Opus 5 turns measured before ADR-0004 changed the model; console usage was not exported into the repo |
| AI assistance (Claude Code) | Estimate: $200 to $800 list-price equivalent | No metered figure exists in the repo. Assumption: 20 to 32 assisted hours (5 to 8 h on each of 4 active days; commit spans give 13 h and understate session time) times $10 to $25 per hour at Claude list prices. Usage ran on a subscription, so marginal cash cost may be lower |
| Engineer time | 20 to 32 h (not priced) | No hourly rate is given in the project |

Measured cash spend through 2026-09-15 is under $20; the AI assistance
estimate dominates any fully loaded figure.

## Part B: runtime cost per turn

Measured from the live deployment's `/metrics` counters after the last deploy:
4 turns, 11 model calls, input_tokens 4,097, output_tokens 7,798,
cache_read_tokens 14,551. Turn latency measured at 12 to 22 s. Model is
claude-sonnet-5 (ADR-0004). The counters do not separate cache-write tokens
from uncached input, so the write premium (1.25x on the evidence pack the
first time it is seen) is folded into the input line below and slightly
understated.

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
Two caveats on the scorecard figure. It is a lower bound: the runner prices
uncached input as `input_tokens - cache_read_tokens` clamped at zero, and
in these runs the reported `input_tokens` (608) is below `cache_read_tokens`
(5,106), so the uncached-input line is $0 and the cache-write premium is
not separated. And it is the eval mix (about 45 percent follow-ups), not
the usage model below. The projections below keep the earlier, higher
$0.0223 figure as the conservative basis; `KEY_METRICS.md` reports the cost
gate as NOT CONFIGURED until a projection threshold is chosen here, and
none is set yet.

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

### Sensitivity

- Follow-ups per visit double (3 turns per visit): 1,320 turns per user per
  month, $29.40 per user, and every model line above rises 1.5x ($2,940 at
  100 users, $2.94M at 100K).
- Prompt caching off: $0.0288 per turn, $25.37 per user per month, and the
  model line rises 29 percent ($2,537 at 100 users, $2.54M at 100K).
- Model cost scales linearly with users; infrastructure and observability
  stay under 1 percent of the total at every tier, so the model line is the
  only one worth optimizing.

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
   anything that reduces claims emitted per turn (a tighter
   `max_output_tokens`, 1,800 today, or a per-question claim cap) is worth
   more than any input-side change.
