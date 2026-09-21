# Domain Docs

This is a single-context repository. Engineering skills should use the following
domain documentation when exploring or changing the codebase.

## Before exploring

- Read `CONTEXT.md` at the repository root when it exists.
- Read ADRs under `docs/adr/` that touch the area being changed.

If these files do not exist, proceed without flagging their absence or creating
them upfront. Domain documentation is created lazily when terms or decisions are
resolved.

## Use the glossary vocabulary

When output names a domain concept, use the term defined in `CONTEXT.md`. If the
needed concept is not defined there, treat that as a possible domain-model gap.

## Flag ADR conflicts

If proposed work contradicts an existing ADR, surface the conflict explicitly
instead of silently overriding the decision.
