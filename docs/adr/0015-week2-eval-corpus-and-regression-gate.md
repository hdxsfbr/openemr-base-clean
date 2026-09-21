# ADR-0015: Additive Week 2 golden set and regression-blocking gate

- **Status:** Accepted 2026-09-21 (owner approval)
- **Date:** 2026-09-21
- **Owners:** Andre Batista (Week 2 evaluation and release policy)
- **Related requirements:** Week 2 PRD 50-case golden dataset, Boolean
  rubrics, greater-than-five-percent regression rule, PR-blocking Git hook or
  equivalent, and grader-injected regression proof.
- **Related decisions:** ADR-0006 (deterministic verification), ADR-0007
  (PHI-free telemetry), ADR-0011 (reviewed document records), ADR-0012
  (claim and citation classes), ADR-0013 (supervisor and handoffs), and
  ADR-0014 (operational budgets).

## Context

The Week 1 suite contains 48 cases: 15 deterministic golden cases and 33
behavioral-coverage cases, including four holdouts. The Week 2 PRD repeatedly
requires a 50-case golden dataset that exercises extraction, retrieval,
citations, refusals, and missing-data behavior. It does not cap the corpus at
50. Treating the existing 48 cases plus two document cases as the deliverable
would preserve the count but leave the new document, retrieval, routing, source
resolution, and privacy boundaries materially under-tested.

The current comparison script reports differences but does not enforce the
PRD's regression arithmetic. The current live GitLab eval job is manual,
allowed to fail, and may test a deployment that does not match the candidate
commit. These are observed Week 1 constraints; the controls below are planned
Week 2 behavior, not implemented safeguards.

## Decision

1. The existing 48 cases remain. Week 2 adds at least 35 new deterministic-
   verdict golden cases, growing the golden set from 15 to at least 50 and the
   complete release corpus from 48 to at least 83. Fifty is a floor, not a
   target or cap. No case is deleted, weakened, or reclassified merely to meet
   the count.
2. `golden set` means the regression-blocking tier whose verdicts come only
   from deterministic Boolean assertions. Behavioral-coverage and holdout
   cases remain additive parts of the release corpus. A model may produce the
   artifact under test, but no model grades, approves, or overrides a blocking
   verdict.
3. The normative corpus allocation, rubrics, thresholds, baseline governance,
   CI enforcement, and mutation proof are defined in
   [`docs/specs/week2-eval-corpus-and-regression-gate.md`](../specs/week2-eval-corpus-and-regression-gate.md).
4. Every golden case declares the applicable PRD rubrics:
   `schema_valid`, `citation_present`, `factually_consistent`, `safe_refusal`,
   and `no_phi_in_logs`. A golden case passes only when every applicable
   rubric passes. Missing, skipped, or unmeasured required rubrics block.
5. Candidate results are compared with a pinned, owner-approved baseline over
   the same manifest, fixtures, rubric version, execution policy, and runtime
   identity. A category blocks when it falls below its declared threshold or
   drops by more than five absolute percentage points. Any new safety or
   integrity failure blocks regardless of aggregate percentage.
6. GitLab is the release authority. The required candidate-matched jobs are
   automatic and non-optional for affected merge requests and protected-branch
   pushes. A versioned local pre-push hook provides fast feedback but cannot
   substitute for GitLab enforcement.
7. Release evidence includes an intentionally injected, non-committed
   regression that makes the gate fail for the expected case, rubric, and
   category, followed by a green run after removal against the same baseline.

## Alternatives Considered

### Stop at exactly 50 total cases

Rejected because it would require only two additions to the Week 1 suite and
would not credibly exercise the Week 2 risk surface.

### Promote existing coverage cases until 50 are labelled golden

Rejected as a quota shortcut. An existing case may become golden only when its
verdict is fully deterministic and it protects a required foundational
invariant; promotion does not replace the planned 35-or-more new Week 2 cases.

### Let a model judge blocking clinical quality

Rejected because a probabilistic grader cannot authorize its own clinical
claims, refusals, citations, or privacy behavior. Calibrated model judging may
be reported separately for non-blocking prose-quality research.

### Rely on a developer-side Git hook

Rejected as the authority because local hooks can be absent or bypassed and do
not prove the candidate commit passed. The hook remains useful as a fast local
mirror of deterministic checks.

## Consequences

- The Week 2 release suite is larger and more expensive than the PRD's minimum,
  so deterministic fixture-backed cases are preferred wherever they protect
  the same boundary as a live model call.
- Model-backed cases that cannot pass the deterministic rubric reliably remain
  visible failures; they are not softened by a model judge or excluded from the
  denominator.
- Corpus and baseline changes become reviewed product changes rather than
  incidental result-file updates.
- The full gate must exercise a runtime built from the candidate commit; the
  existing manual production-targeted job cannot be relabelled as compliant.

## Verification

Implementation is complete only when the manifest contains at least 50 golden
cases and at least 83 total retained cases, all required rubric and baseline
checks are executable, protected-branch enforcement is demonstrated, and the
same-baseline red/green mutation evidence is accessible. Results must identify
the exact commit, corpus and fixture hashes, rubric version, runtime, model,
prompt, and attempt policy.
