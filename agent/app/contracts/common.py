"""Shared contract primitives."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

CONTRACT_VERSION = "1.0.0"

# Source identifiers are URIs (ARCHITECTURE.md, "Canonical Contracts"):
#   openemr:{table}:{id}[:{uuid}]   Week 1
#   document:{uuid}:page:{n}        Week 2 (reserved)
#   guideline:{doc}:{chunk}         Week 2 (reserved)
SourceId = Annotated[
    str,
    StringConstraints(pattern=r"^(openemr|document|guideline):[A-Za-z0-9_\-.:]{1,200}$", max_length=240),
]

CorrelationId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9\-._]{8,64}$")]


class StrictModel(BaseModel):
    """Every contract forbids unknown fields; a stray `pid` is a schema error."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class DatePrecision(StrEnum):
    day = "day"
    datetime = "datetime"
    unknown = "unknown"


class DateBasis(StrEnum):
    clinical = "clinical"  # onset, visit, collection, or start date recorded by a clinician
    entered = "entered"  # when the row was created
    modified = "modified"  # modifydate/last_updated: unreliable (DQ-HIGH-004)
    unknown = "unknown"


class ClinicalDate(StrictModel):
    """A date with its precision and provenance, so undated and maintenance-stamped
    rows are never mistaken for clinical events (DQ-HIGH-004, DQ-MEDIUM-006)."""

    value: date | datetime | None = None
    precision: DatePrecision = DatePrecision.unknown
    basis: DateBasis = DateBasis.unknown

    @property
    def known(self) -> bool:
        return self.value is not None and self.precision is not DatePrecision.unknown


class SourceRef(StrictModel):
    """Where a record came from. `source_id` is what claims cite and what the
    module maps to a chart URL."""

    source_id: SourceId
    table: str = Field(max_length=64)
    id: int = Field(ge=0)
    uuid: str | None = Field(default=None, max_length=36)
