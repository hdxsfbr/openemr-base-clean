# Brief-on-open latency (2026-09-20T030400Z)

`https://openemr-137-184-4-22.sslip.io` as `audit-physician`, 12 completed briefs of 12 attempted, 3 per chart across AF-DQ-A2, AF-DQ-N, AF-HEAVY, AF-DQ-I.

## What the physician waits for

`T_ready` is chart open to a verified brief on screen. `W(L)` is what is
left of it once the physician has spent `L` seconds reading the chart
before opening the drawer: `W(L) = max(0, T_ready - L)`. The old flow
started nothing until the click, so its wait was the whole turn at every `L`.

| Reading lag L | W(L) p50 | W(L) p95 | Old flow p50 | Old flow p95 |
| --- | --- | --- | --- | --- |
| 0 s | 13.4 s | 17.5 s | 12.7 s | 16.9 s |
| 2 s | 11.4 s | 15.5 s | 12.7 s | 16.9 s |
| 5 s | 8.4 s | 12.5 s | 12.7 s | 16.9 s |
| 10 s | 3.4 s | 7.5 s | 12.7 s | 16.9 s |
| 15 s | 0.0 s | 2.5 s | 12.7 s | 16.9 s |
| 20 s | 0.0 s | 0.0 s | 12.7 s | 16.9 s |
| 30 s | 0.0 s | 0.0 s | 12.7 s | 16.9 s |

## Stages

| | p50 | p95 | max |
| --- | --- | --- | --- |
| Panel setup (session, conversation, ticket) | 0.6 s | 0.7 s | 0.716 s |
| Turn (retrieve, narrate, verify, repair) | 12.7 s | 16.9 s | 18.2 s |
| **T_ready** (chart open to brief) | **13.4 s** | **17.5 s** | 19.0 s |

Setup is 0.61 s on average, which is the cost of preparing a brief nobody reads, and the lag below which the old click flow was faster.

## Per chart

| Chart | n | T_ready p50 | T_ready p95 | model summary | repairs |
| --- | --- | --- | --- | --- | --- |
| AF-DQ-A2 | 3 | 17.5 s | 19.0 s | 3/3 | 0 |
| AF-DQ-N | 3 | 10.5 s | 13.4 s | 1/3 | 0 |
| AF-HEAVY | 3 | 14.1 s | 15.5 s | 3/3 | 0 |
| AF-DQ-I | 3 | 6.6 s | 6.8 s | 3/3 | 0 |

## Rows

| rep | chart | ready s | setup s | turn s | status | basis | claims | withheld | repair | out tok | ref |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | AF-DQ-A2 | 18.964 | 0.716 | 18.248 | complete | model | 7 | 0 | False | 2001 | `93829a7f3ccd5782.1` |
| 1 | AF-DQ-N | 10.519 | 0.705 | 9.815 | complete | model | 6 | 0 | False | 994 | `79f39f065143c872.1` |
| 1 | AF-HEAVY | 15.453 | 0.608 | 14.845 | complete | model | 7 | 0 | False | 1617 | `d4703dd0a9eef608.1` |
| 1 | AF-DQ-I | 6.781 | 0.637 | 6.145 | complete | model | 5 | 0 | False | 555 | `ce16ba9fa859ec56.1` |
| 2 | AF-DQ-A2 | 15.357 | 0.603 | 14.754 | complete | model | 7 | 0 | False | 1718 | `41e9a55302bd4a33.1` |
| 2 | AF-DQ-N | 13.358 | 0.641 | 12.717 | complete | deterministic | 6 | 0 | False | 1317 | `bc32a4ce3176858a.1` |
| 2 | AF-HEAVY | 14.128 | 0.611 | 13.518 | complete | model | 7 | 0 | False | 1447 | `ed94f88bfbbc8690.1` |
| 2 | AF-DQ-I | 6.259 | 0.539 | 5.719 | complete | model | 5 | 0 | False | 570 | `385bb125fef82c8a.1` |
| 3 | AF-DQ-A2 | 17.509 | 0.598 | 16.911 | complete | model | 8 | 0 | False | 2063 | `626b4694667f4a19.1` |
| 3 | AF-DQ-N | 9.318 | 0.576 | 8.742 | complete | deterministic | 6 | 0 | False | 934 | `bc0e5a6b44ea24e3.1` |
| 3 | AF-HEAVY | 13.127 | 0.571 | 12.555 | complete | model | 7 | 0 | False | 1504 | `4eceb4578568468b.1` |
| 3 | AF-DQ-I | 6.553 | 0.554 | 5.998 | complete | model | 5 | 0 | False | 564 | `08ff9f49e6a0859c.1` |

Read as a measurement of one deployment on one afternoon, not a gate: the
live suite (`evals/run.py`) stays the release gate for turn latency, and
`L` is a parameter here, not an observation -- no real physician session
has been timed between chart open and drawer open.
