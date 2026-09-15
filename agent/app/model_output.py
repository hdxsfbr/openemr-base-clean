"""Model-facing output schema. Deliberately unconstrained (no regex, no length
limits, no bounds): structured output compiles the schema into a grammar and
constraints make it "too complex" or slow. The strict contract (app.contracts)
is enforced after parsing by `to_claims`, which coerces ids, caps text, drops
malformed source ids, and never lets an unparseable claim through."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from .contracts import Claim, ClaimFacts, ClaimType

SOURCE_ID_RE = re.compile(r"^(openemr|document|guideline):[A-Za-z0-9_\-.:]{1,200}$")


class ModelClaimFacts(BaseModel):
    section: str | None = None
    kind: str | None = None
    date: str | None = None
    name: str | None = None
    status: str | None = None
    analyte: str | None = None
    value_text: str | None = None
    unit: str | None = None
    flag: str | None = None
    earlier_source_id: str | None = None
    later_source_id: str | None = None
    direction: str | None = None
    medication_name: str | None = None
    mention: str | None = None
    state: str | None = None
    reading: str | None = None


class ModelClaim(BaseModel):
    type: ClaimType
    text: str
    facts: ModelClaimFacts = Field(default_factory=ModelClaimFacts)
    source_ids: list[str] = Field(default_factory=list)


class ModelTurnClaims(BaseModel):
    claims: list[ModelClaim] = Field(default_factory=list)


def _cap(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value[:limit] if value else None


def to_claims(output: ModelTurnClaims, max_claims: int = 40) -> tuple[list[Claim], list[dict[str, str]]]:
    """Convert model output into strict contract claims. Returns (claims, dropped)
    where dropped lists claims the contract itself refused."""
    claims: list[Claim] = []
    dropped: list[dict[str, str]] = []
    for index, mc in enumerate(output.claims[:max_claims], start=1):
        claim_id = f"c{index}"
        sources = [s.strip() for s in mc.source_ids if isinstance(s, str) and SOURCE_ID_RE.match(s.strip())][:8]
        facts = ClaimFacts(
            section=_cap(mc.facts.section, 32), kind=_cap(mc.facts.kind, 32), date=_cap(mc.facts.date, 10),
            name=_cap(mc.facts.name, 255), status=_cap(mc.facts.status, 32), analyte=_cap(mc.facts.analyte, 255),
            value_text=_cap(mc.facts.value_text, 255), unit=_cap(mc.facts.unit, 64), flag=_cap(mc.facts.flag, 16),
            earlier_source_id=_cap(mc.facts.earlier_source_id, 240), later_source_id=_cap(mc.facts.later_source_id, 240),
            direction=_cap(mc.facts.direction, 8), medication_name=_cap(mc.facts.medication_name, 255),
            mention=_cap(mc.facts.mention, 300), state=_cap(mc.facts.state, 32), reading=_cap(mc.facts.reading, 300),
        )
        text = _cap(mc.text, 400)
        if not text:
            dropped.append({"claim_id": claim_id, "rule": "contract", "detail": "empty text"})
            continue
        try:
            claims.append(Claim(id=claim_id, type=mc.type, text=text, facts=facts, source_ids=sources, section=facts.section))
        except Exception as exc:  # noqa: BLE001
            dropped.append({"claim_id": claim_id, "rule": "contract", "detail": exc.__class__.__name__})
    return claims, dropped
