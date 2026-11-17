from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import UniqueConstraint

from cloudpilot.models.base import Base


def now() -> datetime:
    return datetime.now(UTC)


class DataSource(Base):
    __tablename__ = "data_sources"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    type: Mapped[str] = mapped_column(String(20))
    scope: Mapped[str] = mapped_column(String(100), index=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="idle")
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    discovery_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InfrastructureResource(Base):
    __tablename__ = "infrastructure_resources"
    __table_args__ = (
        UniqueConstraint("provider", "account_or_cluster_id", "external_id", "is_synthetic"),
        Index("ix_resources_scope_type", "account_or_cluster_id", "resource_type"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("data_sources.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(512))
    provider: Mapped[str] = mapped_column(String(30))
    account_or_cluster_id: Mapped[str] = mapped_column(String(100))
    is_synthetic: Mapped[bool] = mapped_column(Boolean)
    resource_type: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(256), index=True)
    namespace: Mapped[str | None] = mapped_column(String(256))
    region: Mapped[str | None] = mapped_column(String(100))
    availability_zone: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(40))
    cpu_capacity: Mapped[Decimal | None] = mapped_column(Numeric(24, 9))
    memory_capacity_bytes: Mapped[Decimal | None] = mapped_column(Numeric(24, 0))
    cpu_requests: Mapped[Decimal | None] = mapped_column(Numeric(24, 9))
    memory_requests_bytes: Mapped[Decimal | None] = mapped_column(Numeric(24, 0))
    cpu_limits: Mapped[Decimal | None] = mapped_column(Numeric(24, 9))
    memory_limits_bytes: Mapped[Decimal | None] = mapped_column(Numeric(24, 0))
    cpu_allocatable: Mapped[Decimal | None] = mapped_column(Numeric(24, 9))
    memory_allocatable_bytes: Mapped[Decimal | None] = mapped_column(Numeric(24, 0))
    labels: Mapped[dict] = mapped_column(JSON, default=dict)
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ResourceMetric(Base):
    __tablename__ = "resource_metrics"
    __table_args__ = (
        UniqueConstraint("resource_id", "source_id", "metric_name", "timestamp"),
        Index("ix_metrics_resource_time", "resource_id", "timestamp"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    resource_id: Mapped[UUID] = mapped_column(ForeignKey("infrastructure_resources.id"))
    source_id: Mapped[UUID] = mapped_column(ForeignKey("data_sources.id"), index=True)
    metric_name: Mapped[str] = mapped_column(String(80))
    value: Mapped[Decimal] = mapped_column(Numeric(30, 9))
    unit: Mapped[str] = mapped_column(String(20))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    quality_status: Mapped[str] = mapped_column(String(20), default="healthy")
    expected_interval_seconds: Mapped[int] = mapped_column(Integer, default=60)


class BillingRecord(Base):
    __tablename__ = "billing_records"
    __table_args__ = (
        UniqueConstraint("source_id", "external_record_id"),
        Index("ix_billing_resource_period", "resource_id", "period_start"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("data_sources.id"), index=True)
    resource_id: Mapped[UUID | None] = mapped_column(ForeignKey("infrastructure_resources.id"))
    external_record_id: Mapped[str] = mapped_column(String(128))
    external_resource_id: Mapped[str] = mapped_column(String(512))
    service: Mapped[str] = mapped_column(String(100))
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 9))
    currency: Mapped[str] = mapped_column(String(3))
    cost_type: Mapped[str] = mapped_column(String(20), default="actual")
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = (
        Index("ix_runs_claim", "status", "lease_until", "created_at"),
        Index(
            "ix_runs_active_source",
            "source_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'running')"),
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("data_sources.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    records_read: Mapped[int] = mapped_column(Integer, default=0)
    records_created: Mapped[int] = mapped_column(Integer, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, default=0)
    records_rejected: Mapped[int] = mapped_column(Integer, default=0)
    error_summary: Mapped[list] = mapped_column(JSON, default=list)
    payload: Mapped[dict] = mapped_column(JSON)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[UUID | None] = mapped_column()


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
