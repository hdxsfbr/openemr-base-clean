# Load driver and Droplet sampler

Built in MILESTONE M2 of [docs/FINAL_PUSH_PLAN.md](../../docs/FINAL_PUSH_PLAN.md)
(tasks L1 to L3). **Running either tool against the deployment is M4 and
human-gated:** every model-backed turn spends model budget (plan invariant 5),
and the `--users 2` smoke that validates the pipeline is an owner-approved step,
not something a CI job or an agent starts. As of 2026-09-17 no run exists;
`results/` holds only `.gitkeep`.

## Files

```text
evals/load/
  run_load.py        # asyncio + httpx.AsyncClient driver; no dependency beyond agent/.venv
  test_run_load.py   # offline pytest: pure functions plus the VU flow over httpx.MockTransport
  results/           # <UTC>-<sha>.json and .md per run; droplet-stats CSVs and .prom snapshots
  README.md
docs/audit/scripts/droplet-stats.sh   # read-only SSH sampler, 5 s CSV rows, /metrics start and end
```

## What a run measures

Each virtual user (VU) is one OpenEMR login that walks the same handshake the
eval harness (`evals/run.py`, class `Session`) and the panel use: login, chart
open, `session.php`, start, ticket, the UC-01 first turn ("What changed since
the last visit?"), ticket, one follow-up ("Which of those lab results are
flagged abnormal?"), ticket, history. VUs alternate between `audit-physician`
and `physician` and round-robin over AF-DQ-A2 (pid 900001), AF-DQ-N (900018)
and AF-HEAVY (900023), the pids checked against `evals/cases/cohort.json`.
Levels run in order (default 1, 10, 50) with a 30 s ramp per level; `/metrics`
is read before and after each level so every counter in the report is a delta
for that level alone. At 1 and 10 users the first turn is streamed and the
time to the `event: evidence` frame (TTFE) is recorded beside the full turn
time. The full schema and the per-key definitions are in the module docstring
of `run_load.py`; the short form:

- per level and per scenario: p50 / p95 / p99 (nearest rank, the same formula
  as `evals/run.py`) for chart open, ticket and turn, plus login, session,
  start, history and TTFE;
- error rate split by 5xx, 504, 429 and transport (plus `other`), denials
  (turn 401/403, handshake 401/403, `copilot_denials_total` deltas);
- status share complete / partial / fallback / failed / denied, and the agent's
  own `copilot_turns_total` deltas as a cross-check;
- tool `unavailable` counts by reason and by tool from `copilot_tool_calls_total`
  deltas. The parser keeps every label, so it reads both the deployed label
  set (`tool`, `status`; reasons aggregate as `unlabelled`) and the
  `reason`-labelled set the agent emits after M2;
- summed token usage and per-step HTTP status counts;
- one record per VU (`vu_records`): user, chart, where it stopped, and each
  turn's HTTP status, body status, latency and correlation id.

Latencies count every request that received an HTTP response, whatever its
status; transport failures are errors, not latencies. Results carry the two
demo account names and, per VU and turn, the correlation id
(`levels[].vu_records`, the join key to Langfuse traces and the agent's
correlation-id log lines); never a ticket token, CSRF value or cookie, and no
PHI (synthetic cohort `af-cohort-v1`).

## Running (M4, owner-approved)

```bash
# Password from the Droplet, never on the command line (no --password flag exists).
export DEMO_PASSWORD="$(ssh deployer@137.184.4.22 cat /opt/agentforge/secrets/demo_user_password)"
HOST=https://openemr-137-184-4-22.sslip.io

# Schedule only, no network: what the run would do.
agent/.venv/bin/python evals/load/run_load.py --base-url "$HOST" --users 2 --plan

# Smoke (M3 step 4): two VUs, about $0.05, produces a results JSON that validates the pipeline.
agent/.venv/bin/python evals/load/run_load.py --base-url "$HOST" --users 2 --label smoke \
  --metrics-url "$HOST/copilot-api/metrics"

# Baseline (M4): 1, 10 and 50 users with the sampler running in another terminal.
docs/audit/scripts/droplet-stats.sh --label baseline &
agent/.venv/bin/python evals/load/run_load.py --base-url "$HOST" --users 1,10,50 --label baseline \
  --metrics-url "$HOST/copilot-api/metrics"
kill -INT %1      # the sampler writes its end /metrics snapshot on interrupt

# Capacity without provider limits or spend: the model call is replaced by the fallback.
agent/.venv/bin/python evals/load/run_load.py --base-url "$HOST" --users 10,50 --label fault-model --fault model
```

The sampler (`docs/audit/scripts/droplet-stats.sh --help`) is read-only over
SSH: per 5 s row it records `docker stats` for the openemr, database, agent
and caddy containers, `docker top <openemr> | grep -c httpd` against the 250
prefork cap, `Threads_connected` from a `SHOW GLOBAL STATUS` run inside the
database container (the password is read from the container's own
`MARIADB_PASSWORD_FILE` and never leaves it), host `free -m` (no swap is
configured) and the 1-minute load average; `/metrics` is saved at the start
and the end of each run. One sampler run per load level (`--label level-10`,
`--duration`) gives clean per-level CSVs; a single long run can be sliced by
`ts_utc` against the level `started_at`/`finished_at` in the JSON.

## Expected failures at 50 users (record them; do not fix during the window)

Numbers checked against the code on 2026-09-17; the citations are in the
`run_load.py` docstring.

- **300 gateway requests against 250 workers.** The UC-01 first turn fans out
  six tools through a per-turn semaphore of `tool_concurrency` 6
  (`agent/app/settings.py`, `agent/app/graph/nodes.py`), so 50 first turns in
  flight are up to 300 concurrent gateway requests. Apache in the pinned
  OpenEMR image is mpm_prefork with `MaxRequestWorkers 250`
  (`docs/audit/architecture.md`); `infra/` pins the image and does not change
  the MPM. Chart opens from the same VUs queue on the same workers.
- **The likely shape is `partial`, not 5xx.** A gateway call that waits longer
  than `gateway_timeout_seconds` 2.0 comes back as an `unavailable` envelope
  with reason `timeout` (`agent/app/gateway_client.py`); the turn still renders
  with a limitation and reports status `partial`. Look at
  `tool_unavailable.by_reason.timeout` and `status_counts.partial`.
- **504 is the second shape.** The JSON turn path has a 45 s wall clock
  (`turn_wall_clock_seconds`; `agent/app/api.py`), so queued turns past it
  return `504 dependency_unavailable`, counted under `errors["504"]`.
- **Provider 429s convert turns to `fallback` for a minute.** The model client
  retries once on 429/5xx and the circuit breaker opens for a 60 s cooldown
  (`agent/app/model.py`); while it is open every turn takes the deterministic
  fallback. `--fault model` removes that effect to measure capacity alone.
- **A 429 from the agent itself is not expected.** Its limiter is per
  conversation (`turns_per_minute` 10) and this scenario sends two turns per
  conversation.

## Tests

```bash
agent/.venv/bin/python -m pytest -q evals/load/test_run_load.py
```

Offline only: percentiles, buckets, the SSE framer, the metrics parser with
both label sets, the level summary and the schema, plus the whole VU flow
(JSON and streamed turns, 504, denial, missing panel, transport failure)
against an in-process fake stack through `httpx.MockTransport`. No socket is
opened and no model budget is spent.

## Not covered

- No think time between steps; the scenario is a burst per VU, which is the
  harsher reading of "concurrent users".
- 25 VUs share one login name at 50 users. No OpenEMR setting that prevents
  concurrent logins for one user was found (`library/globals.inc.php`,
  `src/Common/Auth/AuthUtils.php`, `library/authentication/`), but that is
  unverified live: the run must confirm it from `step_http.login` in the JSON
  (302 for every VU) before any 50-user number is quoted.
- Streamed turns are not bounded by the agent's 45 s wall clock, only by the
  driver's 90 s client timeout, so the 1- and 10-user turn tails come from a
  different path than the 50-user tail; `stream_levels` in the JSON says which.
- The sampler needs SSH as `deployer`; it never changes anything on the host.
