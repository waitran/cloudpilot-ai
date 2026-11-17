from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, PlainSerializer, StringConstraints, model_validator

from cloudpilot.modules.collection.schemas import Input

Bytes = Annotated[int, PlainSerializer(str, return_type=str, when_used="json")]
Money = Annotated[Decimal, Field(ge=0, le=Decimal("1e12"), decimal_places=9)]
PriceLabel = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]


class Offer(Input):
    name: PriceLabel
    cpu_cores: Decimal = Field(gt=0, le=100000, decimal_places=9)
    memory_bytes: int = Field(gt=0, le=10**15)
    hourly_rate: Money
    recurring_extra: Money = Decimal(0)
    transition_cost: Money = Decimal(0)


class Pricing(Input):
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    reference: PriceLabel
    hours: int = Field(ge=1, le=8760)
    baseline_hourly_rate: Money
    baseline_recurring_extra: Money = Decimal(0)
    offers: list[Offer] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_offers(self):
        if len({o.name.casefold() for o in self.offers}) != len(self.offers):
            raise ValueError("offer_names_must_be_unique")
        return self


class AnalysisRequest(Input):
    pricing: Pricing | None = None


class Size(BaseModel):
    cpu_cores: Decimal
    memory_bytes: Bytes


class SeriesStats(BaseModel):
    source_id: UUID
    first_sample: datetime
    last_sample: datetime
    samples: int
    interval_seconds: int
    p95: Decimal
    peak: Decimal


class Evidence(BaseModel):
    start: datetime
    end: datetime
    cpu: SeriesStats
    memory: SeriesStats


class CostComparison(BaseModel):
    baseline_total: Decimal
    candidate_recurring_total: Decimal
    transition_cost: Decimal
    candidate_total: Decimal
    savings: Decimal
    savings_percent: Decimal | None


class Candidate(BaseModel):
    name: str
    proposed: Size
    headroom_percent: int
    cpu_released_cores: Decimal
    memory_released_bytes: Bytes
    direction: Literal["downsize", "upsize", "mixed", "unchanged"]
    cost: CostComparison | None = None


class Analysis(BaseModel):
    resource_id: UUID
    resource_name: str
    is_synthetic: bool
    evaluated_at: datetime
    policy_version: Literal["peak-headroom-v1"] = "peak-headroom-v1"
    status: Literal["candidates", "no_candidates", "insufficient_data", "unsupported_resource"]
    reasons: list[str] = Field(default_factory=list)
    baseline_kind: Literal["pod_requests", "vm_capacity"] | None = None
    baseline: Size | None = None
    cpu_limit_cores: Decimal | None = None
    memory_limit_bytes: Bytes | None = None
    evidence: Evidence | None = None
    pricing: Pricing | None = None
    candidates: list[Candidate] = Field(default_factory=list)
