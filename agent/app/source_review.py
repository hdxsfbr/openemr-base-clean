"""Trusted click-to-source resolver boundary for the module UI."""

from __future__ import annotations

from typing import Protocol

from .contracts.common import StrictModel
from .contracts.week2 import Citation


class SourceReviewEnvelope(StrictModel):
    citation: Citation
    source: dict[str, object]


class SourceReviewResolver(Protocol):
    async def resolve(
        self,
        conversation_id: str,
        turn_id: str,
        citation: dict[str, object],
    ) -> SourceReviewEnvelope | None: ...
