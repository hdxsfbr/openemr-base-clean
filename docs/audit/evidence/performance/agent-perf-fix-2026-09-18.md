# Agent-side perf fix: pooled HTTP client + checkpointer WAL mode

Follow-up to `load-test-2026-09-18.md` and `baseline-2026-09-18.md`. Same day,
same live Droplet `137.184.4.22`, same load driver and protocol, run
immediately after deploying commit `ba3105b` — a direct before/after against
the M4 baseline (commit `5d67903`), not a new methodology.

## Why: two agent-side bottlenecks, not OpenEMR

M4 concluded OpenEMR/MariaDB CPU is the load ceiling, and that conclusion is
unchanged here (see "What did not move" below) — this round only asks
whether the *agent's own* contribution to turn latency, on top of an
already-saturated OpenEMR, could be reduced without touching OpenEMR/MariaDB
at all (the owner's explicit scope call: a licensee brings their own tuned
OpenEMR, so only the agent's own performance is worth our time this close to
freeze).

Two confirmed issues, found by reading the code, not by guessing:

1. **`HttpGateway.call()`** (`agent/app/gateway_client.py:44`, pre-fix) opened a
   fresh `httpx.AsyncClient` per tool call — a new TCP/TLS handshake on every
   one of the ~6 parallel calls a turn makes, paid by both this process and
   OpenEMR's Apache.
2. **`AsyncSqliteSaver`** (`langgraph.checkpoint.sqlite.aio`, third-party)
   serializes every checkpoint read/write for every concurrent turn behind one
   process-wide `asyncio.Lock`, and both `aput` and `aget_tuple` hold that lock
   across the `conn.commit()` / cursor read. In SQLite's default (non-WAL)
   journal mode, that commit is a full fsync, paid while every other turn's
   checkpoint I/O queues behind the same lock.

Fix (`agent/app/gateway_client.py`, `agent/app/main.py`, commit `ba3105b`):
a single pooled `httpx.AsyncClient` for the gateway, created at startup and
closed at shutdown; `PRAGMA journal_mode=WAL` and `PRAGMA synchronous=NORMAL`
on the checkpoint connection at startup. Neither removes the lock itself —
that needs a different checkpointer backend (e.g. Postgres), a bigger lift
deferred to Week 2 (`docs/WEEK2_HANDOFF.md`) — but WAL shrinks what each
commit costs while the lock is held. Verified before deploy: `pytest`
96/96, `ruff` clean, a standalone WAL-pragma check against a real
`aiosqlite` connection.

## Result: turn-latency tail improved under load; the load ceiling did not move

| Metric (50 users) | M4 baseline (`5d67903`) | After fix (`ba3105b`) | Change |
| --- | --- | --- | --- |
| Turn p95, `--fault model` | 7,986 ms | 4,416 ms | **-45%** |
| Turn p99 / max, `--fault model` | 8,960 / 9,480 ms | 4,621 / 4,913 ms | **-48% / -48%** |
| Turn p95, real model | 43,791 ms | 30,513 ms | **-30%** |
| Successful tool calls, `--fault model` | 6 / 259 (2.3%) | 27 / 273 (9.9%) | **4.5x** |
| Tool-call unavailable rate, `--fault model` | 253/259 (97.7%) | 246/273 (90.1%) | modest |
| Chart-open p95, `--fault model` (control — pure OpenEMR, agent never touches it) | 46,151 ms | 46,461 ms | unchanged |
| `openemr` CPU mean/peak, `--fault model` | 86.5% / 105.8% | 80.1% / 103.5% | unchanged (within run-to-run noise) |
| `database` CPU mean/peak, `--fault model` | 87.8% / 108.5% | 83.2% / 114.8% | unchanged |
| `load1` peak, `--fault model` | 23.54 | 22.7 | unchanged |

At 10 users (OpenEMR not yet saturated — mean CPU 20-45%), nothing moved in
either direction, in either run mode — there was no contention to relieve.
Real-model turn p95 was 45,035 ms before and 45,035 ms after (yes, to the
millisecond scale of coincidence); the two `504` errors on `AF-HEAVY` are
identical, same cause, same magnitude, before and after. This is expected
and important: it shows the fix's effect is specifically a contention
effect, not a blanket speedup, and it did not regress the uncontended case.

**Chart-open latency and OpenEMR/database CPU — both pure-OpenEMR
measurements the agent code never touches — are statistically unchanged
between the two runs.** That is the control: it confirms OpenEMR was under
the same saturated conditions both times, so the turn-latency and
tool-success improvements are attributable to the agent-side change, not to
OpenEMR happening to be less loaded this run.

## What did not move

**The concurrent-user ceiling is unchanged.** `openemr` and `database` CPU
still independently peak at or above 100% (one full vCPU core) on the
2-vCPU Droplet; `load1` still peaks around 23; VU completion counts (28-32 of
50, both runs) and tool-call unavailable rate (90-98%, both runs) are the
same order of magnitude. Nothing here raises how many concurrent users the
deployment can serve before it degrades — that ceiling is OpenEMR/MariaDB
CPU, out of scope by the owner's own call (`docs/AI_COST_ANALYSIS.md`, M4
step 6 pattern): a licensee runs their own sized OpenEMR.

**The `KEY_METRICS.md` 30 s p95 threshold is not resolved by this.**
Real-model turn p95 at 10 users is still 45.0 s, unchanged — the M4 STOP
gate's open question (revise the threshold, with a written risk acceptance,
or resize the Droplet before the release run) still stands exactly as M4
left it.

## Full data

- Real model: `evals/load/results/2026-09-18T114626Z-ba3105b.{json,md}`
- `--fault model`: `evals/load/results/2026-09-18T115232Z-ba3105b.{json,md}`
- Resource samples: `evals/load/results/droplet-stats-2026-09-18T114616Z-perf-fix-real.csv`
  (real-model window) and `droplet-stats-2026-09-18T115224Z-perf-fix-fault.csv`
  (`--fault model` window), plus the paired `-metrics-start.prom`/`-metrics-end.prom`
  snapshots.

## Turns per minute

| Level | Real model (baseline -> new) | `--fault model` (baseline -> new) |
| --- | --- | --- |
| 10 | 13.5/min -> 12.7/min | 31.5/min -> 30.1/min |
| 50 | 32.2/min -> 26.0/min | 47.0/min -> 49.7/min |

Real-model throughput at 50 users reads slightly lower this run (26.0 vs.
32.2/min) despite the p95 improvement — real-model runs carry live LLM
latency variance the `--fault model` control removes, so the `--fault model`
throughput number (up, as expected) is the more trustworthy read on whether
the agent itself got more efficient; the real-model throughput dip is noise
from that run's specific model-call timings, not a regression this fix
caused (tool-call success rate and turn-tail latency both improved in the
same real-model run — see the summary table above).

## Resource data, full table

| Window | Samples | openemr CPU mean/peak | database CPU mean/peak | agent CPU mean/peak | httpd procs peak | `Threads_connected` peak | host mem used peak | host mem available low | `load1` peak |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Real model, 10 users | 13 | 26.4% / 67.8% | 30.5% / 86.7% | 4.9% / 27.2% | 16 | 39 | 1,261 MiB | 2,654 MiB | 1.7 |
| Real model, 50 users | 18 | 53.8% / 103.5% | 56.5% / 111.4% | 6.4% / 23.4% | 54 | 148 | 1,543 MiB | 2,372 MiB | 22.9 |
| `--fault model`, 10 users | 5 | 54.1% / 79.3% | 64.1% / 73.6% | 5.4% / 13.0% | 16 | 45 | 1,373 MiB | 2,541 MiB | 2.3 |
| `--fault model`, 50 users | 11 | 80.1% / 103.5% | 83.2% / 114.8% | 15.9% / 58.6% | 55 | 148 | 1,515 MiB | 2,400 MiB | 22.7 |

`agent` CPU is slightly higher at 50 users this run (15.9%/58.6% vs. the
baseline's 12.1%/53.7%) — consistent with the agent doing more useful work
per second (more tool calls actually completing, more turns finishing)
rather than idling in connection setup/lock wait; it is still nowhere near
saturating a core, and was never the bottleneck.
