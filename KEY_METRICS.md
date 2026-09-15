# Key Metrics

These metrics state, in advance, what "success" means for the primary-care
physician in `USERS.md` and how we would prove it to a hospital technology
leader. Definitions and thresholds are fixed now so that results cannot be
fitted to them later. Safety thresholds do not depend on a baseline; latency
thresholds are set from the audit's budget and are marked provisional until
the load baseline (target 2026-09-19) and the clinician interview
(`USERS.md`, Validation Work) confirm them.

## Product and Safety Metrics

Each row also states how the number could be gamed and what stops it; the
Week 3 interview asks exactly that, and a metric without that answer is not
one we would defend to a hospital CTO.

| Metric | Definition | Target | Why it matters | Evidence source | How it could be gamed, and what stops it |
| --- | --- | --- | --- | --- | --- |
| Unsupported factual claim rate | Displayed patient-specific factual claims with no valid supporting source / all displayed factual claims | 0% | A fluent unsupported claim is the central clinical safety failure. The verifier fails closed, so a displayed unsupported claim is a verifier defect, not a model one. | Deterministic verifier and eval review | Gamed by withholding everything (0/0) or by loosening what counts as "supported". Stopped by reporting withheld count and task success beside it, and by altered-fact evals that must be rejected |
| Citation correctness | Citations that resolve to the correct patient, record, and supporting fields / all citations | At least 99%; investigate every miss | Citation presence alone does not establish trust if it points to irrelevant evidence. | Gold eval dataset and click-through audit | Gamed by citing one safe record for every claim. Stopped by field-level matching per claim type, not existence checks |
| Authorization leakage | Requests where data outside the user's permitted patient/scope reaches a tool result, model context, response, log, or trace | 0 | Proves enforcement across the whole data path, not just the UI. Scope is parity with the chart (ADR-0002): the test is "could this user have seen this in the chart?" | Adversarial auth evals on `audit-*` users and `AF-ACL-*` patients; audit-log reconciliation | Gamed by testing only the UI path or only happy roles. Stopped by asserting on audit-event order and the absence of tool and model spans, per role and per fixture |
| Clinical workflow task success | Gold cases where the physician's defined information need (UC-01..03) is answered completely enough and without a critical error | At least 90% for supported cases | Measures whether the co-pilot is useful for its intentionally narrow job. | Versioned eval dataset with human rubric | Gamed by narrowing "supported cases" or writing easy gold cases. Stopped by the scope-change rule below, a fixed case list per release, and one hard case per `AF-DQ-*` defect |
| Explicit uncertainty recall | Gold cases requiring an absence, conflict, undated, or unavailable state (CAP-06) where the response communicates it | 100% for designated safety cases | Demonstrates the system recognizes limits instead of filling gaps. | `AF-DQ-*` evals | Gamed by hedging everything. Stopped by pairing with task success and with false-uncertainty cases where the record is clear |
| Safe degradation rate | Injected dependency failures that return the specified denial, partial, or deterministic fallback behavior | 100% for supported failure modes | A clinical tool must remain predictable when dependencies fail. | Fault-injection integration tests | Gamed by declaring few failure modes "supported". Stopped by the failure matrix in `ARCHITECTURE.md` being the list, one eval per row |
| Time to first useful evidence | Time from accepted request until the UI renders the first verified, sourced fact (the deterministic retrieval, before the narrative) | p95 under 2 s (provisional) | Fits the 90-second workflow and rewards progressive usefulness. The audit budget is gateway ≤50 ms plus tool fan-out ≤300 ms; the remainder is the agent hop and rendering. | Browser and server traces | Gamed by rendering a placeholder or a cached answer. Stopped by defining "evidence" as a sourced record from this turn's retrieval, and by warm/cold separation |
| Complete verified response latency | Time from accepted request to a final verified response or explicit fallback | p95 under 30 s (provisional, owner-accepted 2026-09-15 for the early submission); design goal remains 8 s | Slow correct answers will not be used between visits. Measured 2026-09-15 on the deployment with Sonnet 5: 24 to 27 s per turn (retrieve about 1 s, narration 5 to 9 s, repair 5 to 14 s, planning 10 to 12 s on follow-ups). The design budget of 8 s assumed a 4 s model call; the levers are fewer claims, skipping repair for a single withheld claim, and a cheaper planning call. | Traces and load tests | Gamed by falling back early or measuring only the three-visit chart. Stopped by reporting fallback rate beside latency and by `AF-HEAVY` in every run |
| Cost per verified turn | LLM spend per completed turn, by use case and by cohort chart size | Under the projection in `AI_COST_ANALYSIS.md` (to be set with the first measured token mix) | The product must be affordable at 20 patients per physician per day. Bounded by the 20K per-turn and 60K per-conversation token caps and the daily spend halt (ADR-0004). | Token accounting in traces | Gamed by excluding failed or fallback turns. Stopped by reporting cost per attempted turn and per verified turn together |

## Operational Diagnostic Metrics

These help explain and improve outcomes but are not product-success claims on
their own. They are what the operational dashboard shows in real time:

- Request count, error count and rate by stage and error class, and
  in-flight or queue depth.
- p50/p95/p99 latency per stage: gateway, tool fan-out, model, verifier.
- Tool call count, latency, failure rate, and retry count, per tool.
- LLM latency, structured-output validation failures, tokens, and cost.
- Verification pass/fail rate, rejected-claim count, and rejection reason.
- Authorization denial count by reason (`patient_context_changed`,
  `forbidden`, `squad`, `breakglass`, `unsupported_principal`).
- Cache hit rate, isolated by data/tool version where applicable.
- CPU, memory, throughput, and saturation during named load scenarios.

## Measurement Rules

- Metric names, units, labels, numerator, denominator, and exclusions are
  defined before results are reported.
- Report sample sizes and confidence limitations.
- Separate warm/cold, cached/uncached, success/failure, and concurrency
  levels; separate the three-visit and five-year synthetic charts.
- Do not include raw PHI or unbounded patient/user labels in metrics.
- Version the model, prompt, tool contracts, verifier, dataset, and commit
  with each eval report.
- Do not improve a metric by silently narrowing the supported population;
  record scope changes explicitly.
- Fixture-based results are synthetic. They show the system handles a planted
  defect, not how often the defect occurs in real charts.

## Decision Thresholds

Three classes of consequence. A metric can carry more than one.

- **Release gate.** Evaluated on the versioned eval suite before the AI layer
  is deployed publicly, and again for every change to the gateway, tools,
  verifier, prompt, or model. A failed gate blocks the deploy.
- **Runtime alert.** Evaluated continuously on the operational dashboard.
  Warning is logged; page means the owner acts now. The three alerts the PRD
  requires (p95 latency, error rate, tool failure rate) are marked.
- **Risk acceptance.** The result is below target but the deploy may proceed
  with a written note in the eval report naming the gap, the cause, and the
  fix date. Never available for safety gates.

| Metric | Release gate (blocks) | Runtime alert | Risk acceptance |
| --- | --- | --- | --- |
| Authorization leakage | Any leaking case | Page on any denial with reason `unsupported_principal` or a schema-rejected patient argument (someone is probing); page on any gateway tool call with no matching audit row (reconciliation job) | Never |
| Unsupported factual claim rate | Any displayed unsupported claim in the suite | Page on any verifier bypass (a response rendered without a verifier outcome); warn when the verifier rejection rate exceeds 20% over 15 minutes (model or prompt drift) | Never |
| Explicit uncertainty recall | Below 100% on designated safety cases | Warn when absence-state responses drop to zero over a day while `AF-DQ-*`-shaped charts are in use (a regression signal, not a proof) | Never for safety cases |
| Safe degradation rate | Below 100% on supported failure modes | See error rate and tool failure rate | Never |
| Citation correctness | Below 97%, or any miss that resolves to the wrong patient | None at runtime (measured by evals and click-through audit) | 97–99% with each miss root-caused and fixed by a named date |
| Clinical workflow task success | Below 80% on supported cases | None | 80–90% with the failing cases listed |
| Complete verified response latency | p95 above 45 s on the eval suite against the deployed stack (the turn wall clock) | **PRD alert 1:** warn at p95 above 30 s over 5 minutes; page at p95 above 45 s or any request over 60 s | p95 between 30 s and 45 s, only until the load baseline exists; the 8 s design goal is tracked, not gated |
| Time to first useful evidence | p95 above 4 s | Warn at p95 above 2 s over 5 minutes | p95 between 2 s and 4 s pending the clinician interview |
| Error rate (5xx or unhandled from the agent API) | Any error on a happy-path eval case | **PRD alert 2:** warn above 0.5% over 5 minutes; page above 2% over 5 minutes or any error in `/ready` for 2 minutes | Never for errors; readiness flaps are investigated, not accepted |
| Tool failure rate (`unavailable` from any clinical tool, excluding `forbidden`) | Any tool returning `unavailable` on a healthy stack | **PRD alert 3:** warn above 2% over 5 minutes; page above 5% over 5 minutes, or one tool above 50% (a broken service path such as PERF-MED-001) | Never; a failing tool is an OpenEMR or gateway defect |
| Cost per verified turn | Above twice the projection | Warn when daily spend exceeds the daily budget in `AI_COST_ANALYSIS.md`; page at three times; the daily halt engages at five times and routes every turn to the deterministic fallback until reset | Between one and two times the projection with the token mix explained |

**What each alert means and the response.** The PRD requires the meaning and
the on-call response for the three named alerts; the owner is on call.

| Alert | Likely meaning | First response |
| --- | --- | --- |
| p95 latency | Model provider slow, tool fan-out serialized, or the Droplet saturated | Check the stage breakdown on the dashboard: if the model stage dominates, confirm the provider status and the fallback (CAP-08) is rendering; if tools dominate, check OpenEMR and MariaDB CPU; if the gateway dominates, check Apache worker saturation |
| Error rate | Agent API or gateway failing requests: bad deploy, expired secret, OpenEMR down | Check `/ready` and its dependency detail; if a deploy preceded it, redeploy the previous tagged image; if OpenEMR is down, the panel must already be showing "unavailable" |
| Tool failure rate | A clinical service path broke (schema change, upstream bug, database) or the delegation token is being rejected | Identify which tool from the per-tool panel; run its fixture test against the stack; if the delegation path fails, every tool fails at once and the audit log shows denials |

**Rules for changing thresholds.**

- Tightening a threshold needs no record.
- Loosening one needs a risk acceptance in the eval report; loosening a
  safety gate (leakage, unsupported claims, uncertainty recall, degradation)
  is not permitted.
- The load baseline (10 and 50 concurrent users, target 2026-09-19) may
  revise only the latency and cost thresholds, and the revision is recorded
  with the baseline.
- A release run must execute the whole suite; category subsets are for
  development only. Each safety category must contain at least one negative
  case per role and per fixture it names, or the gate is "not run", which
  blocks.

## Metrics Considered and Not Chosen

- **User satisfaction or adoption.** Not measurable in a one-week build with
  no clinical users; click-through rate on citations is the proxy we keep.
- **Questions per session.** A vanity count; more turns can mean confusion.
- **Model-graded answer quality as a headline number.** Kept as a diagnostic,
  reported separately from deterministic checks, never aggregated with them
  (`evals/README.md`).
- **Aggregate pass rate.** Never reported without the safety-category
  breakdown; a high aggregate can hide a single leakage case.
