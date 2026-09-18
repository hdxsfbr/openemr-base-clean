# Runtime Alerts Runbook

The PRD requires three runtime alerts with a documented meaning and on-call
response: turn latency, error rate, and tool failure rate. The thresholds are
the "Runtime alert" column of the Decision Thresholds table in
`KEY_METRICS.md`; this runbook does not restate them differently, and it does
not loosen them (loosening needs a risk acceptance in the eval report).

The owner is on call. The alerts are evaluated by `agent/app/alerts.py` from
the agent's Prometheus text at `GET /copilot-api/metrics`, which holds
counters and gauges only (no PHI, no unbounded labels). The Langfuse project
shows the same signals visually (turn latency, status, tool status, tokens per
trace); this job exists so that an alert fires without anyone watching a
dashboard.

## Severity

| Severity | Meaning | Delivery |
| --- | --- | --- |
| `warn` | Logged. Look at it during the next working session. | JSON line in the job output; webhook when configured |
| `page` | The owner acts now. | Same; in one-shot mode exit code 2 so CI or a wrapper can escalate. The `alerts` compose service loops with `--interval 300` and never exits, so there the escalation is `--webhook` or a watch on `docker compose logs alerts` for `"severity": "page"` |

## Alert 1: turn latency

| Field | Value |
| --- | --- |
| Metric | `copilot_turn_latency_ms{quantile="p95",window="5m"}` and `{quantile="p99",window="5m"}`, gated on `copilot_turn_latency_count_5m > 0` |
| Window | 5 minutes (the agent's own rolling window) |
| Warn | p95 above 30,000 ms |
| Page | p95 above 45,000 ms, or p99 above 60,000 ms |

Why these numbers. `KEY_METRICS.md` accepts p95 under 30 s for the early
submission (measured 24 to 27 s per turn on 2026-09-15 with the 8 s design
goal tracked, not gated), pages at 45 s because that is the agent's own turn
wall clock (`turn_wall_clock_seconds`; a turn past it is returned as a 504),
and pages on any single request over 60 s. The agent exposes no maximum
gauge, so p99 stands in for "any request": with fewer than 100 turns in the
window p99 is the slowest turn.

What it usually means. The model provider is slow (narration and repair
dominate the turn), the tool fan-out is serialized against a busy OpenEMR, or
the Droplet is saturated.

First response.

1. `GET /copilot-api/ready`: every dependency should report `ok`. A slow but
   healthy `llm_provider` points at the provider; a failing `openemr_gateway`
   points at OpenEMR.
2. In Langfuse, open the slowest recent traces and read the stage spans
   (retrieve, plan, narrate, repair, verify). The correlation id on the trace
   matches the agent log line and the panel's error banner.
3. Check the Anthropic status page for an incident or elevated latency.
4. `GET /meta/health/livez` on the OpenEMR hostname and, over SSH, the CPU of
   the `openemr` and `mysql` containers; slow tools mean slow OpenEMR.
5. In the agent logs (`docker compose logs agent`), look for `circuit_open`
   and `timeout` model errors. The breaker in `app/model.py` opens after three
   consecutive failures and stays open for 60 s; while it is open, turns skip
   the model and return the deterministic fallback quickly, so a latency alert
   that coincides with an open breaker is the provider recovering, not the
   agent.

Mitigation. Nothing needs to be switched off. When the model is slow or down
the agent renders the deterministic, source-cited brief (the CAP-08 fallback),
so the panel stays useful; confirm it is rendering by asking a turn in the demo
chart. If the Droplet is saturated, stop the load source (an eval run, a load
test) before resizing anything. To rehearse this alert, send a turn with the
header `X-Copilot-Fault: model`; the fallback path must render and the turn
must stay under the page threshold. The header is honored only when the agent
runs with `COPILOT_FAULT_INJECTION=1`, which the demo deployment's compose
file sets by default and which is off everywhere else.

Resolved when p95 over the 5-minute window is back under 30 s for two
consecutive evaluations with at least one turn in the window, and the Langfuse
traces for the incident have been read (a slow turn that was a single heavy
chart is a note in the eval report, not a fix).

## Alert 2: error rate

| Field | Value |
| --- | --- |
| Metric | `copilot_requests_total{path,status}`; numerator `status="5xx"`, denominator all requests, both excluding the probe path classes `health`, `ready`, `metrics`, `root` (`PROBE_PATHS` in `app/alerts.py`) |
| Window | The counter delta since the previous run (5 minutes with the `alerts` service below; cumulative since process start on the first run) |
| Warn | Above 0.5% |
| Page | Above 2%, or `/ready` returning an error for 2 minutes (needs `--ready-url`) |

Why these numbers. `KEY_METRICS.md` defines the error rate as 5xx or
unhandled responses from the agent API and sets 0.5% warn and 2% page over
5 minutes, plus a page when `/ready` fails for 2 minutes. Probe paths are
excluded from the denominator so that a health poll every few seconds cannot
dilute failed turns. Readiness flaps are investigated, never accepted.

What it usually means. A bad deploy, an expired or missing secret, OpenEMR or
the gateway down, or the model provider failing in a way the agent did not
convert into a fallback (an unhandled exception is a 500 with code
`internal_error`).

First response.

1. `GET /copilot-api/ready` and read the per-dependency detail:
   `openemr_gateway`, `llm_provider`, `tracer`, `delegation_secret`,
   `state_store`. `not_configured` means a secret file is missing on the
   Droplet (`push-secrets.sh` restores it).
2. In Langfuse, filter recent traces by status `failed` and open one; the
   correlation id ties it to the agent log line with the exception.
3. Check the Anthropic status page if the failing stage is the model.
4. `GET /meta/health/livez`; if OpenEMR is down, the panel must already be
   showing "unavailable" rather than erroring.
5. Agent logs: an `unhandled` log line is a defect to fix; a run of
   `circuit_open` lines is the breaker doing its job.

Mitigation. If a deploy preceded the alert, redeploy the previous tagged
image. If a secret expired, push the new file and recreate the agent
container. The deterministic fallback keeps turns answering while the model is
unavailable, so a model outage alone should not raise the error rate; if it
does, that is a bug in the fallback path and the eval for that failure row in
`ARCHITECTURE.md` is the place to reproduce it. Rehearse with
`COPILOT_FAULT_INJECTION=1` and `X-Copilot-Fault: budget` (eval case
`MODEL-BUDGET-001`); it must degrade to the deterministic fallback without a
5xx. The value `tracer` is listed in `app/settings.py` but no graph node acts
on it today, so it does not rehearse a tracer outage.

Resolved when the rate over the last window is at or under 0.5% and `/ready`
has been 200 for two consecutive runs. For a page caused by a defect, resolved
also means the fix has an eval.

## Alert 3: tool failure rate

| Field | Value |
| --- | --- |
| Metric | `copilot_tool_calls_total{tool,status,reason}`; numerator `status="unavailable"` excluding `reason="forbidden"`, denominator all statuses (`ok`, `empty`, `partial`, `unavailable`) including the denials |
| Window | The counter delta since the previous run (5 minutes with the `alerts` service below) |
| Warn | Above 2% across all tools |
| Page | Above 5% across all tools, or one tool above 50% of its own calls |

Why these numbers. `KEY_METRICS.md` sets 2% warn and 5% page over 5 minutes,
and pages on a single tool above 50% because that is the shape of a broken
service path (PERF-MED-001, where the medication service raised on a healthy
chart). A failing tool is an OpenEMR or gateway defect and is never accepted.
`empty` and `partial` are successful retrievals and do not count.

Authorization denials are not failures. The metric carries a bounded
`reason` label (`TOOL_REASONS` in `app/contracts/tools.py` plus `none`,
`other`, and `http_Nxx`), and `reason="forbidden"` is left out of the
numerator only, so a front-desk user denied on every clinical tool moves
`copilot_denials_total` at the gateway and this rate not at all
(`test_tool_failure_ignores_forbidden_denials`: six denials among forty
calls, no alert). A burst of `forbidden` on a user who should have access is
a delegation or ACL problem, read from the gateway's audit rows.

What it usually means. One clinical service path broke (schema change,
upstream bug, database), the gateway is timing out (2 s per tool), or the
per-turn delegation token is being rejected, in which case every tool fails at
once and the OpenEMR audit log shows denials.

First response.

1. Read the alert message: it names the tool when one tool is over 50%.
2. `GET /copilot-api/ready`; `openemr_gateway` failing means the whole path is
   down, not one tool.
3. Read `copilot_tool_calls_total` by `reason` first (`timeout`,
   `transport_error`, `http_5xx`, `forbidden`, `contract_violation`,
   `service_error`, `audit_unavailable`, ...; the exact code of an
   `http_<code>` is on the tool span in Langfuse, the metric keeps only the
   class), then open a recent trace in Langfuse and read the tool spans.
4. `GET /meta/health/livez`, then run the failing tool's fixture test against
   the stack (the Bruno collection under `docs/api-collection` has one request
   per tool).
5. Agent logs are secondary here; the model circuit breaker does not affect
   tools. If every tool fails with `forbidden`, check the delegation secret on
   both sides (module and agent) and the gateway's audit rows.

Mitigation. The agent already marks the section as unavailable and claims
nothing about it, so the panel stays truthful with the other sections. Do not
patch OpenEMR live; fix the service path in the module or gateway, deploy, and
rerun the fixture. Rehearse with `COPILOT_FAULT_INJECTION=1` and
`X-Copilot-Fault: tool:<name>` (for example `tool:medications`); the section
must render as unavailable and this alert must fire on the next evaluation.

Resolved when the rate is at or under 2% across a full window and the tool
that paged has passed its fixture test against the deployed stack.

## Running the job

The evaluator is a pure function over one scrape, with the previous scrape
kept in a state file so that counters become rates. It runs from the agent's
own virtualenv or from inside the agent container; it needs only `httpx`.

```bash
cd agent && .venv/bin/python -m app.alerts \
  --url https://HOST/copilot-api/metrics \
  --ready-url https://HOST/copilot-api/ready \
  --state /var/tmp/copilot-alerts.json
```

Output is one JSON line per alert, or one `heartbeat` line when nothing
fires. Exit code 0 means no page, 2 means a page-severity alert fired, 1 means
the metrics endpoint could not be fetched (which is itself worth a look;
`/health` failing is the agent being down). `--interval 300` loops instead of
exiting; `--webhook URL` POSTs each alert record as JSON and is off by
default; `--timeout` sets the HTTP timeout (10 s default). The thresholds
and the rate math are covered by `agent/tests/test_alerts.py`.

On the Droplet the evaluation is scheduled by the `alerts` service in
`infra/digitalocean/runtime/compose.yaml` (added 2026-09-17, on the host
from the M3 deploy). It runs the agent image with

```
python -m app.alerts --url http://agent:8080/metrics --ready-url http://agent:8080/ready --state /var/lib/copilot/alerts-state.json --interval 300
```

on the `frontend` network, with the `agent_state` volume mounted at
`/var/lib/copilot` (`COPILOT_STATE_DIR`, so the state file survives a
container recreate), `restart: unless-stopped`, `depends_on` the agent being
healthy, and the image's inherited health check disabled (it probes port
8080, which this process never serves; left enabled it would stall
`docker compose up --wait` in `start.sh`). The 300 s interval matches the
5-minute rate window in `KEY_METRICS.md`. Read it with:

```bash
ssh deployer@<droplet-ip> 'cd /opt/agentforge && docker compose logs --tail 20 alerts'
ssh deployer@<droplet-ip> 'cd /opt/agentforge && docker compose logs alerts | grep "\"severity\": \"page\""'
```

Do not add a cron line as well: two evaluators sharing one state file break
the rate math (each sees the other's sample as "previous"). In interval mode
the process never exits, so exit code 2 is not available as an escalation;
to wire a pager, add `--webhook` to the service command pointing at the
receiver (an incoming webhook for a chat channel, or a paging service's
events endpoint). The POST body is the same record that is logged, so a
receiver needs only to read `severity`, `name`, and `message`. Nothing in
the record can carry PHI: it is built from counters, gauges, and fixed
message templates. Container logs rotate (json-file, 10 MiB, three files)
like every other service's.

The same evaluation also runs from any machine that can reach the public
hostname (the metrics path is read-only), which is how the alert rules are
checked before a demo.

## What the dashboard adds

Langfuse holds one PHI-free trace per turn with the stage spans, tool
statuses, verifier outcome, and token usage, and its dashboard views cover the
same three signals over any time range. Use it to explain an alert (which
stage, which tool, which correlation id); use this job to be told about one.
