from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ResourceType = Literal[
    "virtual_machine",
    "kubernetes_node",
    "kubernetes_pod",
    "kubernetes_deployment",
    "kubernetes_statefulset",
]
MetricName = Literal[
    "cpu_usage_cores",
    "memory_usage_bytes",
    "network_receive_bytes_per_second",
    "network_transmit_bytes_per_second",
    "cpu_throttling_ratio",
]
Positive = Annotated[Decimal, Field(ge=0, le=Decimal("1e15"), max_digits=24, decimal_places=9)]
METRICS = {
    "cpu_usage_cores": "cores",
    "memory_usage_bytes": "bytes",
    "network_receive_bytes_per_second": "bytes/s",
    "network_transmit_bytes_per_second": "bytes/s",
    "cpu_throttling_ratio": "ratio",
}


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone_required")
    return value.astimezone(UTC)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class SourceCreate(Input):
    name: str = Field(min_length=1, max_length=100, pattern=r"^[\w .-]+$")
    type: Literal["csv", "prometheus", "kubernetes"]
    scope: str = Field(min_length=1, max_length=100, pattern=r"^[\w.-]+$")
    is_synthetic: bool = False


class ResourceInput(Input):
    external_id: str = Field(min_length=1, max_length=512)
    resource_type: ResourceType
    name: str = Field(min_length=1, max_length=256)
    provider: str = Field(default="csv", pattern=r"^[\w-]{1,30}$")
    namespace: str | None = Field(default=None, max_length=256)
    region: str | None = Field(default=None, max_length=100)
    availability_zone: str | None = Field(default=None, max_length=100)
    status: str = Field(default="unknown", max_length=40)
    cpu_capacity: Positive | None = None
    memory_capacity_bytes: Positive | None = None
    cpu_requests: Positive | None = None
    memory_requests_bytes: Positive | None = None
    cpu_limits: Positive | None = None
    memory_limits_bytes: Positive | None = None
    cpu_allocatable: Positive | None = None
    memory_allocatable_bytes: Positive | None = None
    labels: dict[str, str] = Field(default_factory=dict, max_length=64)
    configuration: dict = Field(default_factory=dict)

    @field_validator(
        "memory_capacity_bytes",
        "memory_requests_bytes",
        "memory_limits_bytes",
        "memory_allocatable_bytes",
    )
    @classmethod
    def whole_bytes(cls, value):
        if value is not None and value != value.to_integral_value():
            raise ValueError("integer_bytes_required")
        return value

    @field_validator("labels")
    @classmethod
    def safe_labels(cls, value):
        for key, item in value.items():
            if len(key) > 256 or len(item) > 256:
                raise ValueError("label_too_long")
            if any(word in key.lower() for word in ["password", "token", "secret", "credential"]):
                raise ValueError("sensitive_label")
        return value


class MetricInput(Input):
    external_resource_id: str = Field(min_length=1, max_length=512)
    metric_name: MetricName
    value: Decimal = Field(ge=0, le=Decimal("1e18"), max_digits=30, decimal_places=9)
    unit: str
    timestamp: datetime
    expected_interval_seconds: int = Field(default=60, ge=15, le=3600)

    @field_validator("timestamp")
    @classmethod
    def valid_time(cls, value):
        value = utc(value)
        if value > datetime.now(UTC) + timedelta(minutes=2):
            raise ValueError("future_timestamp")
        return value

    @model_validator(mode="after")
    def units(self):
        if self.unit != METRICS[self.metric_name]:
            raise ValueError("invalid_unit")
        if self.metric_name == "cpu_throttling_ratio" and self.value > 1:
            raise ValueError("invalid_ratio")
        if (
            self.metric_name == "memory_usage_bytes"
            and self.value != self.value.to_integral_value()
        ):
            raise ValueError("integer_bytes_required")
        return self


class BillingInput(Input):
    external_resource_id: str = Field(min_length=1, max_length=512)
    external_record_id: str = Field(default="", max_length=128)
    service: str = Field(min_length=1, max_length=100)
    period_start: datetime
    period_end: datetime
    amount: Decimal = Field(
        ge=Decimal("-1e14"), le=Decimal("1e14"), max_digits=24, decimal_places=9
    )
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    cost_type: Literal["actual", "estimated", "forecast", "credit"] = "actual"

    @field_validator("period_start", "period_end")
    @classmethod
    def timestamps(cls, value):
        return utc(value)

    @field_validator("currency")
    @classmethod
    def known_currency(cls, value):
        if value not in {
            "USD",
            "EUR",
            "RUB",
            "GBP",
            "CNY",
            "JPY",
            "CHF",
            "CAD",
            "AUD",
            "KZT",
            "TRY",
            "AED",
            "INR",
            "BRL",
            "SGD",
            "HKD",
            "KRW",
            "SEK",
            "NOK",
            "DKK",
            "PLN",
            "UZS",
        }:
            raise ValueError("unsupported_currency")
        return value

    @model_validator(mode="after")
    def period(self):
        if self.period_end <= self.period_start:
            raise ValueError("invalid_period")
        if self.amount < 0 and self.cost_type != "credit":
            raise ValueError("negative_cost_requires_credit")
        if self.cost_type != "forecast" and self.period_end > datetime.now(UTC) + timedelta(
            minutes=2
        ):
            raise ValueError("future_billing_period")
        return self


class SyncRequest(Input):
    start: datetime
    end: datetime
    step: int = Field(default=60, ge=15, le=3600)

    @field_validator("start", "end")
    @classmethod
    def timestamps(cls, value):
        return utc(value)

    @model_validator(mode="after")
    def bounded_window(self):
        if not timedelta(0) < self.end - self.start <= timedelta(days=7):
            raise ValueError("window_must_be_between_zero_and_seven_days")
        if self.end > datetime.now(UTC) + timedelta(minutes=2):
            raise ValueError("future_window")
        if (self.end - self.start).total_seconds() / self.step + 1 > 10000:
            raise ValueError("too_many_points_per_series")
        return self


class Quality(BaseModel):
    status: Literal["healthy", "partial", "stale", "unavailable", "invalid"]
    reasons: list[str] = []
    optimization_ready: bool = False
    latest_at: datetime | None = None
    history_seconds: int = 0
    gap_count: int = 0


class SourceView(SourceCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: str
    settings: dict
    discovery_metadata: dict
    created_at: datetime
    last_success_at: datetime | None
    last_error_at: datetime | None


class RunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    source_id: UUID
    status: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    records_read: int
    records_created: int
    records_updated: int
    records_rejected: int
    error_summary: list[dict]
    attempts: int


class ResourceView(ResourceInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    source_id: UUID
    account_or_cluster_id: str
    is_synthetic: bool
    discovered_at: datetime
    last_seen_at: datetime
    quality: Quality = Field(default_factory=lambda: Quality(status="unavailable"))
    latest_metrics: dict[str, dict] = Field(default_factory=dict)


class MetricView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    resource_id: UUID
    source_id: UUID
    metric_name: str
    value: Decimal
    unit: str
    timestamp: datetime
    collected_at: datetime
    quality_status: str


class BillingView(BillingInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    source_id: UUID
    resource_id: UUID | None
    imported_at: datetime


class BillingGroup(BaseModel):
    currency: str
    cost_type: str
    is_synthetic: bool
    amount: Decimal
    records: int
    unmatched_records: int


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class QualitySummary(BaseModel):
    total_resources: int
    states: dict[str, int]
    optimization_ready: int
    sources_without_success: int
