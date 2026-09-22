# ADR-0016: Reconcile Week 2 implementation slices with the accepted PRD

- **Status:** Accepted 2026-09-22 (implementation baseline for GitLab #26/#27)
- **Date:** 2026-09-22
- **Owners:** Andre Batista (scope and release boundary)
- **Related requirements:** Week 2 PRD Stages 1–5 and Core Requirements 1–7;
  GitLab #26 parent and #27 Slice 1.
- **Supersedes:** the conflicting Week 2-only portions of ADR-0014 and ADR-0015.

## Context

ADRs 0014 and 0015 were accepted design records before the parent task chose a
narrow, ordered seven-slice implementation plan. Their c-4 host redesign,
operational frameworks, at-least-83-corpus target, and “50 is a floor” rule do
not follow the Week 2 PRD or the accepted #26/#27 implementation contract.
They must not silently define this implementation base. The discarded
`codex/week2-implementation` branch is likewise not an implementation source.

## Decision

1. The Week 2 PRD and GitLab #26 with its ordered children are the sole
   implementation requirements. Existing ADRs remain historical design context
   unless this record or a later slice adopts a compatible part explicitly.
2. The release corpus is **exactly 50** high-signal synthetic/demo cases, as
   allocated by #26 Child 6. It retains relevant Week 1 boundary coverage by
   curation; it is not an additive 83-case minimum.
3. Week 2 does not add non-PRD operational frameworks: a host redesign,
   retention sweepers, capability-readiness matrix, spend ledger, version cap,
   audit outbox, or multi-service topology. The existing hardened synthetic
   deployment and PHI-free telemetry are extended only where a PRD line or
   slice acceptance criterion requires it.
4. Slice 1A implements only a server-derived, session/CSRF/ACL-bound lab PDF
   upload intent, native OpenEMR source storage, strict versioned contracts,
   and an internal authorized source-read seam. It does not make proposals
   clinical record facts, call a model, or introduce extraction/rendering.

## Consequences

- ADR-0015’s “at least 50 golden and 83 total” and ADR-0014’s non-PRD
  operational controls are retired for this implementation. Their observations
  and risk analysis remain available as historical evidence.
- Every slice must distinguish implemented evidence from planned later work;
  in particular, source upload is not derived-fact persistence and an
  extraction proposal is not chart truth.
- The branch base is current `main`; no code, contracts, or fixtures are
  copied from the discarded branch.

## Verification

Slice 1A verifies strict exported contracts, valid/invalid synthetic fixtures,
the session-derived upload boundary, retry/replay denial, native document
mapping, and internal token-authenticated source access. Later slices provide
the extraction, final 50-case gate, deployment, and operational evidence.
