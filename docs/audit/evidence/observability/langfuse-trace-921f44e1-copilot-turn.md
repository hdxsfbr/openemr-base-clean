# Langfuse trace export: one `copilot.turn` with its correlation id

Exported 2026-09-16 through the Langfuse public API (`GET /api/public/traces/921f44e1de3dc19deb130609664fa3bc`), saved verbatim next to this file as `langfuse-trace-921f44e1-copilot-turn.json` (two Langfuse UI-only fields, `htmlPath` and `_deprecation`, dropped). This is the turn used in `docs/operations/correlation-id-walkthrough.md`: eval case `CIT-UC01-A2-001`, synthetic patient AF-DQ-A2, user `audit-physician`.

| Field | Value |
| --- | --- |
| Trace id | `921f44e1de3dc19deb130609664fa3bc` |
| Name | `copilot.turn` |
| Session id (= conversation id) | `34289f7e08fb8e6a4198bf9d3b8daa26` |
| Tags | `copilot`, `turn` (traces since commit `74a1bf6` carry the turn type instead of `turn`) |
| `metadata.correlation_id` | `75a29aa756c7985f.1` |
| `metadata.turn_type` | `turn` |
| Timestamp | 2026-09-16T01:34:39.610Z |
| Latency | 21.223 s |
| Total cost | $0.0281 |
| Observations | 19 |
| `userId` | None (never set; the user lives only in the OpenEMR audit log) |

## Observation tree (start offsets from the first span)

| Offset ms | Type | Name | Level | Input | Output |
| --- | --- | --- | --- | --- | --- |
| 0 | SPAN | `copilot.turn` | DEFAULT | `{"digest": true, "type": "NoneType"}` | `{"digest": true, "type": "NoneType"}` |
| 2 | CHAIN | `copilot.turn` | DEFAULT | `{"digest": true, "type": "NoneType"}` | `{"digest": true, "keys": ["accepted", "answered_at", "budget_limit", "` |
| 7 | CHAIN | `authorize` | DEFAULT | `{"digest": true, "type": "NoneType"}` | `{"digest": true, "keys": ["budget_limit", "route", "started_at", "timi` |
| 10 | CHAIN | `router` | DEFAULT | `{"digest": true, "type": "NoneType"}` | `{"digest": true, "chars": 8}` |
| 17 | CHAIN | `classify` | DEFAULT | `{"digest": true, "type": "NoneType"}` | `{"digest": true, "keys": ["route", "timings_ms", "turn_type"], "bytes"` |
| 19 | CHAIN | `router` | DEFAULT | `{"digest": true, "type": "NoneType"}` | `{"digest": true, "chars": 8}` |
| 24 | CHAIN | `retrieve` | DEFAULT | `{"digest": true, "type": "NoneType"}` | `{"digest": true, "keys": ["evidence", "pending_calls", "reference_enco` |
| 1097 | CHAIN | `router` | DEFAULT | `{"digest": true, "type": "NoneType"}` | `{"digest": true, "chars": 7}` |
| 1101 | CHAIN | `narrate` | DEFAULT | `{"digest": true, "type": "NoneType"}` | `{"digest": true, "keys": ["raw_claims", "raw_suggestions", "raw_summar` |
| 1103 | GENERATION | `narrate` | DEFAULT | `{"digest": true, "type": "NoneType"}` | `{"digest": true, "type": "NoneType"}` |
| 11276 | CHAIN | `router` | DEFAULT | `{"digest": true, "type": "NoneType"}` | `{"digest": true, "chars": 6}` |
| 11280 | CHAIN | `verify` | DEFAULT | `{"digest": true, "type": "NoneType"}` | `{"digest": true, "keys": ["accepted", "rejected", "route", "rules", "t` |
| 11283 | CHAIN | `router` | DEFAULT | `{"digest": true, "type": "NoneType"}` | `{"digest": true, "chars": 6}` |
| 11286 | CHAIN | `repair` | DEFAULT | `{"digest": true, "type": "NoneType"}` | `{"digest": true, "keys": ["raw_claims", "raw_summary", "repair_attempt` |
| 11288 | GENERATION | `repair` | DEFAULT | `{"digest": true, "type": "NoneType"}` | `{"digest": true, "type": "NoneType"}` |
| 21179 | CHAIN | `router` | DEFAULT | `{"digest": true, "type": "NoneType"}` | `{"digest": true, "chars": 6}` |
| 21186 | CHAIN | `verify` | DEFAULT | `{"digest": true, "type": "NoneType"}` | `{"digest": true, "keys": ["accepted", "rejected", "route", "rules", "t` |
| 21190 | CHAIN | `router` | DEFAULT | `{"digest": true, "type": "NoneType"}` | `{"digest": true, "chars": 6}` |
| 21209 | CHAIN | `render` | DEFAULT | `{"digest": true, "type": "NoneType"}` | `{"digest": true, "keys": ["accepted", "answered_at", "conversation_tok` |

## PHI check

Every observation input and output in the export is either `null` or a digest object of the form `{"digest": true, "keys": [...], "bytes": n}` produced by the client-side mask (ADR-0007). Checked mechanically over the JSON on 2026-09-16:

- Unmasked input or output fields: none.
- Cohort patient keys (`AF-DQ-*`), pid-like numbers (`900xxx`), and the demo usernames: 0 matches in the raw JSON.
- The one `Last, First`-shaped string in the raw JSON is `Cloud, Langfuse` inside the Langfuse SDK scope attributes, not a person.

The trace therefore shows the correlation id, the graph node order, the two generations with token usage and cost, and the repair round, without any chart content. Joining it to a user or patient requires the OpenEMR `log` table, which is the intended boundary.
