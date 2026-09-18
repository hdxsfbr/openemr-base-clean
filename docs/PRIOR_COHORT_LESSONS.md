# Lessons From a Prior Cohort

Source: a summary of a previous Gauntlet cohort's Slack channel for this same
OpenEMR project (Feb–Mar 2026, ~150 messages), shared on 2026-09-14. These are
**second-hand anecdotes**, not verified findings. The OpenEMR mechanics
transfer because it is the same codebase; tool, host, and schedule details may
not. Each item below records where this project already stands and what, if
anything, we do about it.

## Summary: what changes for us

1. **Deploy the agent skeleton on Tuesday, before features.** The
   infrastructure is proven, but no co-pilot code has been deployed. A stub
   module plus agent container on the Droplet should exist before any real
   tool work. *(Done 2026-09-15: `v0.1.0-skeleton`, then `v0.2.0-slice`; the
   deployed tag since 2026-09-16 is `week1` at commit `e1dd331`;
   `docs/deployment/digitalocean.md` "Current Deployment".)*
2. **Tag a known-good commit before every checkpoint and before adding scope
   late in the week.** Submit the smaller working thing rather than
   hot-fixing live. *(Status 2026-09-17: three tags exist — `v0.1.0-skeleton`
   and `v0.2.0-slice`, both 2026-09-15, and `week1`, written 2026-09-16 at
   commit `e1dd331`, which is what is deployed. The early submission was made
   from a tag, not an untagged commit. Rollback rehearsal is still an open
   checklist item.)*
3. **Add explicit conversation-isolation and paraphrase-tolerant evals.** Both
   failures happened to others, and both are cheap to test with our fixtures.
   *(Status 2026-09-16: isolation cases `ISO-NEW-CONVERSATION-001`,
   `AUTH-SWITCH-001`, `ISO-FOLLOWUP-CHAIN-001` exist; assertions are on
   structured claims, never prose; `CIT-PARAPHRASE-ADVICE-001` covers the
   verifier side of paraphrase. See the table below for what is still open.)*
4. **Keep observability non-blocking.** Plan for the tracer being
   rate-limited or down.

---

## Tips that help

| Tip from prior cohort | Where we stand | Action |
| --- | --- | --- |
| Default sample patients are nearly empty; seed early. They used `docker compose exec openemr /root/devtools import-random-patients 100 true` (documented in `CONTRIBUTING.md:585-593`) | **Ahead.** We audited the demo data (`AUDIT.md` DQ-CRITICAL-001) and built the deterministic defect cohort `af-cohort-v1` (`evals/fixtures/cohort/`) | Keep `af-cohort-v1` as the eval source of truth. `import-random-patients` generates Synthea patients without a fixed seed, needs Java and internet in the container, and is not reproducible (`docs/audit/data-quality.md` §7). It is fine as optional **background volume** for load tests, never as eval fixtures |
| Deploy on day one ("deploy hello world and move from there"); late deployment ate a full evening for several people | **Partly done** (as of 2026-09-14). The OpenEMR stack was provisioned and verified on DigitalOcean twice on 2026-09-14, then destroyed each time to save cost. Nothing co-pilot-related had been deployed yet. **Update 2026-09-16:** the skeleton (`v0.1.0-skeleton`) and the vertical slice (`v0.2.0-slice`) were deployed on 2026-09-15 and the Droplet has been kept up during build days (`docs/deployment/digitalocean.md` "Current Deployment") | **Tuesday morning:** deploy a stub custom module (panel that says "hello") plus a stub agent container with `/health` through Caddy before writing tools. Consider leaving the Droplet up during build days (≈$0.86/day for 4 GiB) so config drift is caught continuously, not the night before a deadline |
| Start from `docker/development-easy`; the "insane" variants only add monitoring nobody needed | **Done.** Local work uses `development-easy`. `AGENTS.md` forbids deploying it publicly; the deployment uses `infra/digitalocean` | None |
| Most treated OpenEMR as a black box via FHIR/REST; OAuth2/FHIR auth setup was the biggest pain point (a 25-reply thread, repeated 401s) | **Deliberately different.** The audit chose in-process services behind a thin custom-module gateway under the user's session (`AUDIT.md` §3.4, §8 row 3). That avoids OAuth setup entirely and keeps user identity, which a service token would discard (SEC-HIGH-001, SEC-MED-005) | Stay with the module gateway. **Brownfield risk:** use only supported module events and services, never patch core (per `AGENTS.md`). If we ever fall back to SMART/FHIR, read `Documentation/api/AUTHENTICATION.md` and the root-level `API_README.md` / `FHIR_README.md` first, and budget for the OAuth flow |
| Railway `railway up` reused a Docker build cache; connect the repo for fresh builds | **Not applicable** (DigitalOcean + Terraform + Compose) | Analogous risk: redeploying with the same image tag can run a stale image. Pin project images **by digest** (already the pattern in `infra/digitalocean`), and note the documented Caddy `Created`-state gotcha (`docs/deployment/digitalocean.md`) |

## Things that bit people

| Pain point | Where we stand | Action |
| --- | --- | --- |
| Inconsistent data model: id vs uuid vs enum; date vs datetime vs epoch, varying by table and era | **Confirmed by our audit:** zero-dates and time-zone-less datetimes (DQ-MEDIUM-006), option-id dose fields (DQ-MEDIUM-010), two medication sources (DQ-HIGH-003), binary UUIDs next to integer ids, duplicate condition rows (DQ-MEDIUM-014) | Tools own normalization (`AUDIT.md` §7.1): typed dates with precision and basis, resolved list labels, `source_table` + id **and** uuid on every record. Never assume a pattern holds across tables; unit-test each tool against `AF-DQ-*` patients |
| Chat agent leaked context from a previous conversation after a "fresh" session (typed "Jane" four times, got four different previously discussed answers) | **Covered in design, not yet tested** (as of 2026-09-14). "Conversation isolation" is an eval category (`evals/README.md`), and conversations are to be bound server-side to (site, user, pid) (`AUDIT.md` §7.1, ARCH-HIGH-001). **Update 2026-09-16:** binding lives in the module table `copilot_conversation` (ADR-0005); of the four evals below, (1) is `ISO-NEW-CONVERSATION-001` and (2) is `AUTH-SWITCH-001`, both passing in every recorded run; (3) and (4) are not yet cases (open in ADR-0005 "Verification") | Add explicit evals: (1) a new conversation for the same patient carries **no** prior turns; (2) a patient switch ends the conversation; (3) the same question asked across N fresh sessions yields the same verified facts with no references to earlier sessions; (4) two users on the same patient never see each other's history. Never keep conversation state in a process-global or model-side memory, and never in browser storage |
| PHI to a third-party LLM was raised with no clean answer | **Answered in the audit:** `AUDIT.md` §5.5 and `docs/audit/compliance.md` §4 | Interview-ready answer: the PRD lets us assume a BAA; the provider is a business associate; minimum necessary still applies, so tools send projected, windowed fields with no direct identifiers; an LLM BAA does not cover hosted tracing, so telemetry is PHI-free or self-hosted; prompts and responses never go into ordinary logs |
| Evals broke on trivial wording drift ("Confirm" vs "Verify") | **Design fits:** the planned response schema is structured claims + `source_ids[]` + limitations (`ARCHITECTURE.md` "Verification Design"). **Update 2026-09-16:** `evals/run.py` matches claim types, source tables, statuses, limitation kinds, and evidence status; model-wording checks are labelled `recall:` and sit under a non-blocking gate | Assert on **structured output**: which claims exist, their source IDs, typed values, status flags, and absence states. Never compare prose. Where wording matters (e.g. "not documented"), match a small set of accepted phrasings or a status enum. Reserve model-graded checks for tone and completeness, reported separately |
| Cautionary tale: a working subset at noon, more features added, collapse, a broken revert, missed deadline | Not yet relevant; highest schedule risk later in the week. **Update 2026-09-17:** three tags exist — `v0.1.0-skeleton` and `v0.2.0-slice` (2026-09-15) and `week1` (2026-09-16, commit `e1dd331`), and `week1` is what is deployed, so the early submission did go out from a tagged commit. The rollback rehearsal in `docs/SUBMISSION_CHECKLIST.md` is still unticked and no image digest has been recorded | **Release discipline:** `git tag` a known-good commit (and record its image digest) at every green checkpoint; deploy only tagged commits; freeze scope several hours before each deadline (`docs/PROJECT_PLAN.md` targets 10:00 AM for final); rollback = redeploy the previous tag, rehearsed once before Wednesday. Submit the smaller working thing |

## Smaller notes

| Note | Our response |
| --- | --- |
| Claude Code compacts context often on a repo this size | Keep decisions in files, not chat: `AGENTS.md`, `docs/PROJECT_PLAN.md`, `AUDIT.md`, ADRs. Prefer focused sessions per component; restate the relevant doc paths when starting a session |
| LangSmith rate limits hit some people | Observability must not block care (the `ARCHITECTURE.md` failure matrix already says so). Buffer or drop spans on tracer errors, keep correlation-ID structured logs locally as the fallback, and prefer self-hosted Langfuse, which the compliance analysis already favors |
| Ramp cards rejected by some hosts (DigitalOcean, Linode) | DigitalOcean billing already works for us (two successful provisions on 2026-09-14). Keep a backup host in mind only if billing changes |
| A ~$5/week 2 GB droplet ran someone's full stack | Idle OpenEMR ≈333 MiB plus MariaDB ≈229 MiB locally. With Caddy, the agent service, and possibly self-hosted Langfuse, stay on 4 GiB (`docs/adr/0001-ephemeral-single-droplet-baseline.md`) and revisit after load tests |
