# AI Cost Analysis

## Executive Summary

TODO: Summarize measured development spend, cost per successful verified
workflow, dominant cost drivers, and the architecture changes required at each
scale tier.

## Measurement Scope

| Field | Value |
| --- | --- |
| Measurement period | TODO |
| Model and pricing date | TODO |
| Application commit | TODO |
| Prompt/tool-contract version | TODO |
| Requests included/excluded | TODO |

## Actual Development Spend

| Category | Usage | Unit cost | Total | Evidence |
| --- | ---: | ---: | ---: | --- |
| Input tokens | TODO | TODO | TODO | TODO |
| Cached input tokens | TODO | TODO | TODO | TODO |
| Output tokens | TODO | TODO | TODO | TODO |
| Embeddings, if any | TODO | TODO | TODO | TODO |
| Eval runs | TODO | TODO | TODO | TODO |
| Observability | TODO | TODO | TODO | TODO |
| Infrastructure | TODO | TODO | TODO | TODO |

## Production Workload Assumptions

TODO: Define active users, clinical days per month, conversations per user,
turns per conversation, tool mix, retry rate, response size, peak concurrency,
retention, and support/on-call assumptions. Use measured request distributions
rather than one average prompt.

## Scale Projections

| Scale | Monthly workload | AI | Application/worker | Database/cache | Observability/storage | Operations/support | Estimated total | Required architecture change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 100 users | TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO |
| 1,000 users | TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO |
| 10,000 users | TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO |
| 100,000 users | TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO |

## Sensitivity Analysis

- TODO: Model choice and fallback routing.
- TODO: Conversation and retrieved-context length.
- TODO: Cache hit rate and invalidation cost.
- TODO: Retry/eval sampling rate.
- TODO: Peak-to-average concurrency.
- TODO: Trace retention and PHI-safe storage.

## Cost Controls and Tradeoffs

TODO: Describe limits, budgets, model routing, prompt compaction, deterministic
paths, caching, batch evals, anomaly alerts, and the safety consequences of each
optimization.
