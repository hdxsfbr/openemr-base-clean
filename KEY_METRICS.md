# Key Metrics

These are initial metric hypotheses. Final definitions and thresholds must be
validated against the target workflow, eval dataset, and deployed baseline.
Each metric is intended to prove a specific part of the product promise to a
hospital technology leader.

## Product and Safety Metrics

| Metric | Initial definition | Proposed target | Why it matters | Evidence source |
| --- | --- | --- | --- | --- |
| Unsupported factual claim rate | Displayed patient-specific factual claims with no valid supporting source / all displayed factual claims | 0% | A fluent unsupported claim is the central clinical safety failure. | Deterministic verifier and eval review |
| Citation correctness | Citations that resolve to the correct patient, record, and supporting fields / all citations | At least 99%; investigate every miss | Citation presence alone does not establish trust if it points to irrelevant evidence. | Gold eval dataset and click-through audit |
| Authorization leakage | Requests where data outside the user's permitted patient/scope reaches a tool result, model context, response, log, or trace | 0 | Proves enforcement across the whole data path, not just the UI. | Adversarial auth tests and audit logs |
| Clinical workflow task success | Gold cases where the physician's defined information need is answered completely enough and without a critical error | Establish baseline; target at least 90% for supported cases | Measures whether the co-pilot is useful for its intentionally narrow job. | Versioned eval dataset with human rubric |
| Explicit uncertainty recall | Gold cases requiring uncertainty or "not documented" where the response communicates it | 100% for designated safety cases | Demonstrates the system recognizes limits instead of filling gaps. | Missing/conflicting-data evals |
| Safe degradation rate | Injected dependency failures that return the specified denial, partial, or deterministic fallback behavior | 100% for supported failure modes | A clinical tool must remain predictable when dependencies fail. | Fault-injection integration tests |
| Time to first useful evidence | Time from accepted request until the UI renders the first verified, sourced fact | p95 under 2 seconds, subject to baseline | Fits the 90-second pre-visit workflow and rewards progressive usefulness. | Browser and server traces |
| Complete verified response latency | Time from accepted request to a final verified response or explicit fallback | p95 under 8 seconds, subject to baseline | Slow correct answers will not be used between visits. | Traces and load tests |

## Operational Diagnostic Metrics

These help explain and improve outcomes but are not product-success claims on
their own:

- Request count and active/in-flight or queue depth.
- Error rate by stage and error class.
- Tool call count, latency, failure rate, and retry count.
- LLM latency, structured-output validation failures, tokens, and cost.
- Verification pass/fail rate and rejected-claim count.
- Cache hit rate, isolated by data/tool version where applicable.
- CPU, memory, throughput, and saturation during named load scenarios.

## Measurement Rules

- Metric names, units, labels, numerator, denominator, and exclusions must be
  defined before results are reported.
- Report sample sizes and confidence limitations.
- Separate warm/cold, cached/uncached, success/failure, and concurrency levels.
- Do not include raw PHI or unbounded patient/user labels in metrics.
- Version the model, prompt, tool contracts, verifier, dataset, and commit with
  each eval report.
- Do not improve a metric by silently narrowing the supported population; record
  scope changes explicitly.

## Decision Thresholds

TODO: After baseline measurement, define which failures block deployment, which
trigger an alert, and which require a documented risk acceptance.
