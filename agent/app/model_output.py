"""Model-facing output schema. Deliberately unconstrained (no regex, no length
limits, no bounds): structured output compiles the schema into a grammar and
constraints make it "too complex" or slow. The strict contract (app.contracts)
is enforced after parsing by `to_claims`, which coerces ids, caps text, drops
malformed source ids, and never lets an unparseable claim through.

One malformed claim costs that claim, not the turn. The schema accepts what a
model gets wrong in practice (a claim with no `text`, an unknown `type`, a
number where a string belongs, `facts: null`) and `to_claims` drops what it
cannot use. Before 2026-09-19 any of those failed validation of the whole
output: the good claims and the summary were thrown away and the turn paid for
a second model call or fell back."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .contracts import Claim, ClaimFacts, ClaimType

SOURCE_ID_RE = re.compile(r"^(openemr|document|guideline):[A-Za-z0-9_\-.:]{1,200}$")


class ModelClaimFacts(BaseModel):
    model_config = ConfigDict(coerce_numbers_to_str=True)  # "value_text": 6.8 is a usable fact

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
    model_config = ConfigDict(coerce_numbers_to_str=True)

    type: str = ""  # checked against ClaimType by `to_claims`; an unknown type drops the claim
    text: str | None = None
    reading: str | None = None  # seen in practice: an interpretation's reading written beside `facts`, with no `text`
    facts: ModelClaimFacts = Field(default_factory=ModelClaimFacts)
    source_ids: list[str] = Field(default_factory=list)

    @field_validator("facts", mode="before")
    @classmethod
    def _facts_object(cls, value: Any) -> Any:
        return value if isinstance(value, dict) else {}

    @field_validator("source_ids", mode="before")
    @classmethod
    def _source_id_strings(cls, value: Any) -> list[str]:
        return [s for s in value if isinstance(s, str)] if isinstance(value, list) else []


class ModelTurnClaims(BaseModel):
    claims: list[ModelClaim] = Field(default_factory=list)
    summary: str | None = None
    suggestions: list[str] | None = None

    @field_validator("claims", mode="before")
    @classmethod
    def _claim_objects(cls, value: Any) -> list[Any]:
        return [c for c in value if isinstance(c, dict)] if isinstance(value, list) else []

    @field_validator("summary", mode="before")
    @classmethod
    def _summary_string(cls, value: Any) -> str | None:
        return value if isinstance(value, str) else None

    @field_validator("suggestions", mode="before")
    @classmethod
    def _suggestion_list(cls, value: Any) -> list[str] | None:
        return [s for s in value if isinstance(s, str)] if isinstance(value, list) else None


def model_suggestions(output: ModelTurnClaims, limit: int = 3, max_chars: int = 120) -> list[str]:
    """The model's follow-up questions, whitespace-collapsed and capped; the verifier filters them."""
    out: list[str] = []
    for item in output.suggestions or []:
        if isinstance(item, str):
            text = " ".join(item.split())[:max_chars]
            if text:
                out.append(text)
    return out[:limit]


def model_summary(output: ModelTurnClaims, limit: int = 600) -> str:
    """The model's summary, whitespace-collapsed and capped; empty when absent.
    An over-long summary is cut at its last complete sentence, not mid-word."""
    text = " ".join((output.summary or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    return cut[: end + 1] if end >= limit // 2 else cut


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
        try:
            claim_type = ClaimType(mc.type.strip())
        except ValueError:
            dropped.append({"claim_id": claim_id, "rule": "contract", "detail": "unknown type"})
            continue
        sources = [s.strip() for s in mc.source_ids if isinstance(s, str) and SOURCE_ID_RE.match(s.strip())][:8]
        facts = ClaimFacts(
            section=_cap(mc.facts.section, 32), kind=_cap(mc.facts.kind, 32), date=_cap(mc.facts.date, 10),
            name=_cap(mc.facts.name, 255), status=_cap(mc.facts.status, 32), analyte=_cap(mc.facts.analyte, 255),
            value_text=_cap(mc.facts.value_text, 255), unit=_cap(mc.facts.unit, 64), flag=_cap(mc.facts.flag, 16),
            earlier_source_id=_cap(mc.facts.earlier_source_id, 240), later_source_id=_cap(mc.facts.later_source_id, 240),
            direction=_cap(mc.facts.direction, 8), medication_name=_cap(mc.facts.medication_name, 255),
            mention=_cap(mc.facts.mention, 300), state=_cap(mc.facts.state, 32), reading=_cap(mc.facts.reading or mc.reading, 300),
        )
        text = _cap(mc.text, 400)
        if not text and claim_type is ClaimType.interpretation:
            text = _cap(mc.facts.reading or mc.reading, 400)  # an interpretation's reading is its text
        if not text:
            dropped.append({"claim_id": claim_id, "rule": "contract", "detail": "empty text"})
            continue
        try:
            claims.append(Claim(id=claim_id, type=claim_type, text=text, facts=facts, source_ids=sources, section=facts.section))
        except Exception as exc:  # noqa: BLE001
            dropped.append({"claim_id": claim_id, "rule": "contract", "detail": exc.__class__.__name__})
    return claims, dropped
