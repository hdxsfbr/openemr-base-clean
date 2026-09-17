# Observability evidence (sanitized, for evaluators without Langfuse access)

The Langfuse project is private to the owner's account, so this folder holds
what an evaluator would otherwise see there: the dashboard panels that cover
the PRD's operational metrics, and one full trace with its correlation id.
Everything here comes from the deployment's own traffic (eval runs and demo
turns against the synthetic `af-cohort-v1` cohort); nothing was staged.

## Dashboard panels

Dashboard **Clinical Co-Pilot** in project "My Project" on Langfuse Cloud US
(`https://us.cloud.langfuse.com`), time range "past 1 day", captured
2026-09-16 about 18:15 Pacific. Panel definitions and the PRD metric each
covers are in `docs/operations/langfuse-dashboard.md`; the axis times are
Pacific, so the eval bursts between 6 PM and 2 AM are the nine full runs of
2026-09-16 01:57Z to 08:16Z (`evals/results/`), and the 11 AM to 1 PM bars
are later demo and repeat runs.

| File | Panel | PRD metric |
| --- | --- | --- |
| `langfuse-dashboard-clinical-copilot-2026-09-16.png` | All nine panels on one sheet | overview |
| `langfuse-panel-01-turns-over-time.png` | `copilot.turn` traces per hour | Requests |
| `langfuse-panel-02-latency-p50.png` | p50 latency of `copilot.turn` | p50 latency |
| `langfuse-panel-03-latency-p95.png` | p95 latency of `copilot.turn` | p95 latency |
| `langfuse-panel-04-model-cost.png` | Total model cost per hour | Cost |
| `langfuse-panel-05-tokens-by-usage-type.png` | Tokens by usage type (input, output, cache read, total) | Tokens |
| `langfuse-panel-06-generations-by-name.png` | GENERATION observations by name (`plan`, `narrate`, `repair`) | Retry count: each `repair` is one verifier-driven retry |
| `langfuse-panel-07-tool-calls-by-name.png` | TOOL observations by name (seven gateway tools) | Tool calls |
| `langfuse-panel-08-tool-errors-by-name.png` | TOOL observations at level ERROR by name | Tool failures |
| `langfuse-panel-09-error-level-observations.png` | ERROR-level observations per hour | Errors |

How the images were made: the Langfuse page draws each panel as an inline
SVG. The SVGs were serialized from the live page with their computed styles,
rasterized in the browser at 1.5x onto the dashboard's dark background with
the panel title, subtitle, and legend, and saved as PNG. They are therefore
exact renderings of what the dashboard showed, not re-plots of exported
data. Panel 07's legend runs past the right edge; the seven series are
`patient_context`, `lab_results`, `encounters`, `medications`, `problems`,
`allergies`, `clinical_notes`. Read against the numbers: the p95 spike to
about 42 s near 2 AM is the `REG-HEAVY-001` chart and the same-commit
repeat run, and the tool-error bars are the injected `TOOL-OUTAGE-LABS-001`
and authorization-denial cases, not production failures
(`evals/results/2026-09-16T073141Z-1ddf824.md`).

## One trace with its correlation id

`langfuse-trace-921f44e1-copilot-turn.json` is the verbatim public-API export
of trace `921f44e1de3dc19deb130609664fa3bc`, the turn walked through in
`docs/operations/correlation-id-walkthrough.md` (ref `75a29aa756c7985f.1`,
case `CIT-UC01-A2-001`). `langfuse-trace-921f44e1-copilot-turn.md` summarizes
it: 19 observations in graph order, two generations with token usage and
cost, one repair round, and the PHI check.

## What was checked before committing

- Every image was opened and inspected: chart geometry, axis labels, series
  names, and panel titles only. No patient, user, email, organization, or
  key appears in any image; the Langfuse sidebar (which shows the owner's
  account) was excluded from the render.
- Every observation input and output in the trace export is `null` or a
  digest object from the client-side mask (ADR-0007). A mechanical scan of
  the raw JSON found no cohort patient keys, pid-like numbers, or demo
  usernames (details in the trace summary).
- The cohort itself is synthetic (`evals/fixtures/cohort/README.md`), so even
  an unmasked value would not have been real PHI; the mask is verified anyway
  because production data would flow through the same path.
