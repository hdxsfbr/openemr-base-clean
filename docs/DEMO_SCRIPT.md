# Demo Script (3 to 5 minutes)

Recorded by the owner. Every proof point in `docs/SUBMISSION_CHECKLIST.md`
"Demo Proof Points" appears once, in this order. Times are targets.

Before recording: log in as `audit-physician` in one tab, open AF-DQ-A2
(pid 900001), and have Langfuse open in a second tab with the project's
trace list filtered to the last hour. Keep a terminal ready with
`ssh deployer@137.184.4.22`.

| Time | On screen | Say | Proof point |
| --- | --- | --- | --- |
| 0:00 | AF-DQ-A2 dashboard, panel with three starter chips | "Physician, 90 seconds before a visit. The co-pilot lives in the chart, read-only. Nothing is retrieved until I ask." | context |
| 0:20 | Click "What changed since the last visit?"; progress line animates | "It retrieves six sections through OpenEMR's own access checks, the model writes claims, and a deterministic verifier checks every one against the records before anything renders." | normal sourced workflow |
| 0:45 | Answer: summary paragraph, claims table, "Verified" badge | "One paragraph answer, then the evidence. Every row cites a record." | per-claim citation |
| 1:00 | Click a `[1]` link on the amlodipine conflict row; the medication opens in OpenEMR | "Citations open the original record. This one is a conflict: end date and activity flag disagree, and it says so instead of guessing." | click-through to source; conflict state |
| 1:20 | Click a follow-up chip such as "Was the amlodipine status change documented in a note?" | "Follow-ups keep the window and chain more tools: this one planned a note search." | multi-turn, more than one tool |
| 1:45 | Type "What is the patient's lisinopril dose and should it change?" | "Dosing and recommendations are refused as a limitation, never answered." | refusal / honest limits |
| 2:05 | Switch to AF-DQ-I (pid 900012), ask the first question; point at "Allergies not documented" | "Missing data stays missing. This chart has no allergy review, so the answer says not documented, not 'no allergies'." | honest missing-data response |
| 2:30 | Log in as `audit-frontdesk` in another window, open AF-DQ-A2, ask the first question | "Front Office sees demographics in the chart and nothing clinical. The gateway denies each section before any model call, and the audit log records it." | authorization denial before LLM |
| 2:55 | Terminal: run the Bruno "Tool outage" request, or curl with `X-Copilot-Fault: tool:lab_results` | "Fault injection: the lab tool is down. The section is marked unavailable, nothing claims labs are absent, and the rest of the brief still renders." | visible partial behavior during a tool failure |
| 3:20 | Copy the `ref` from the panel's meta line; paste into the Langfuse search | "One correlation id runs the whole path: panel, ticket, gateway audit rows, agent logs, and this trace with nested tool, narrate, verify, and repair spans, token counts, and cost. No PHI in the trace." | correlation id through observability |
| 3:50 | `evals/results/<latest>.md` in the editor | "Thirty-three eval cases: authorization, citation, missing data, conflicts, labs, injection, tool and model failure, isolation. Pass rate by category, latency p50 and p95, tokens." | eval results |
| 4:10 | `AI_COST_ANALYSIS.md` per-turn table | "About two cents a turn at list price; projections at four tiers with the assumptions written down." | cost |
| 4:25 | Back on the panel | "Read-only, cited, verified, audited, and honest about what the chart does not say." | close |

Cuts if over time: drop the dosing refusal (1:45) and the cost slide (4:10).

Evidence to keep alongside the video: the eval results file, the Langfuse
trace URL for the demonstrated ref (private project; screenshot for
evaluators without access), and the commit hash shown by `git rev-parse HEAD`
at recording time.
