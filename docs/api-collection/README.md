# Runnable API Collection (Bruno)

The PRD requires a runnable collection graders can drive without reading
source. This folder is a [Bruno](https://www.usebruno.com/) collection: open
it in the Bruno app, or run it headlessly:

```bash
npm install -g @usebruno/cli
cd docs/api-collection && bru run --env deployed --env-var DEMO_PASSWORD="$(ssh deployer@<droplet-ip> cat /opt/agentforge/secrets/demo_user_password)"
```

The demo clinician password is generated on the deployment host
(`docs/deployment/digitalocean.md`, "Manual Cycle"); never commit it.

Folders run in order (22 requests; the recorded runs are 21 of 21 and
predate the 22nd). Folder 1 performs the same handshake the
panel does (login, open chart, CSRF, start conversation, ticket); every turn
request in folders 2 and 3 mints a fresh ticket in its pre-request script,
because a ticket lives 90 seconds and is bound to one turn. Folder 2 runs the
UC-01 turn and follow-up, the UC-02 and UC-03 turns, and reads the
conversation state (`GET /v1/conversations/{id}`). Folder 3 holds the failure
examples (missing and tampered tokens, a patient id in tool parameters, model
and tool outages through fault injection, a turn after `end` and a ticket
after `end`, a Front Office login and turn with every clinical section
unavailable). Folder 4 checks `/health` and `/ready`.

Environments: `environments/deployed.bru` (the `sslip.io` deployment) and
`environments/local.bru` (dev stack on `localhost:8300`, agent on
`localhost:18080`), each with the cohort pids used by the requests and
`DEMO_PASSWORD` as a secret variable. The collection is not run in CI; the
release gates come from the eval suite (`evals/README.md`), which drives the
same handshake.

Without a model key on the target, the turns return `status: fallback` with
the deterministic, source-cited record brief; the assertions allow that so the
collection is runnable before the key is configured.
