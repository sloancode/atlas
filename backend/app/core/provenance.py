"""Data provenance primitives.

Every number ATLAS shows must carry where it came from, when it was
retrieved, which period it describes, and what kind of value it is. A value
that could not be retrieved is represented explicitly as MISSING with
`value=None` -- never as a plausible-looking placeholder.
"""

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel, Field, model_validator

T = TypeVar("T")


class DataStatus(StrEnum):
    LIVE = "live"  # fetched from the source moments ago
    DELAYED = "delayed"  # source publishes with a known delay (e.g. 15-min quotes)
    HISTORICAL = "historical"  # stored snapshot of a past fetch
    ESTIMATED = "estimated"  # derived using at least one assumption
    INCOMPLETE = "incomplete"  # computed, but some required inputs are missing
    MISSING = "missing"  # not available; value is None
    SIMULATED = "simulated"  # paper portfolio only -- never real money


class Period(BaseModel):
    start: date
    end: date  # inclusive

    @model_validator(mode="after")
    def _ordered(self) -> "Period":
        if self.end < self.start:
            raise ValueError("period end precedes start")
        return self

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


class Provenance(BaseModel):
    source: str  # e.g. "shopify.admin_graphql", "user_input", "derived"
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    period: Period | None = None
    status: DataStatus
    notes: list[str] = Field(default_factory=list)  # assumptions, missing inputs


class DataPoint(BaseModel, Generic[T]):
    value: T | None
    provenance: Provenance

    @model_validator(mode="after")
    def _missing_has_no_value(self) -> "DataPoint[T]":
        if self.provenance.status == DataStatus.MISSING and self.value is not None:
            raise ValueError("a MISSING data point must not carry a value")
        if self.provenance.status != DataStatus.MISSING and self.value is None:
            raise ValueError("a data point without a value must be MISSING")
        return self

    @classmethod
    def missing(cls, source: str, reason: str, period: Period | None = None) -> "DataPoint[T]":
        return cls(
            value=None,
            provenance=Provenance(
                source=source, status=DataStatus.MISSING, period=period, notes=[reason]
            ),
        )
