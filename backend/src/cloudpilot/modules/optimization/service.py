from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from cloudpilot.modules.collection.connectors.base import CollectionError
from cloudpilot.modules.collection.models import DataSource, InfrastructureResource, ResourceMetric
from cloudpilot.modules.optimization.engine import propose
from cloudpilot.modules.optimization.schemas import (
    Analysis,
    AnalysisRequest,
    Evidence,
    SeriesStats,
    Size,
)

HISTORY = timedelta(days=7)
FRESHNESS = timedelta(minutes=15)
MAX_SAMPLES = 100000
SERIES = {"cpu_usage_cores": "cores", "memory_usage_bytes": "bytes"}


def summarize(
    rows, start: datetime, end: datetime, unit: str
) -> tuple[SeriesStats | None, str | None]:
    if not rows:
        return None, "missing"
    if len({row.source_id for row in rows}) != 1:
        return None, "multiple_sources"
    # Include the nearest point on or before the beginning of the requested window.
    before = [row for row in rows if row.timestamp <= start]
    if not before:
        return None, "insufficient_history"
    window = [before[-1], *(row for row in rows if row.timestamp > start)]
    steps = {row.expected_interval_seconds for row in window}
    if len(steps) != 1:
        return None, "inconsistent_interval"
    interval = steps.pop()
    if end - window[-1].timestamp > FRESHNESS:
        return None, "stale"
    if not 15 <= interval <= 3600:
        return None, "invalid_interval"
    if end - window[-1].timestamp > timedelta(seconds=interval * 1.5):
        return None, "window_end_missing"
    if any(
        later.timestamp - earlier.timestamp > timedelta(seconds=interval * 1.5)
        for earlier, later in zip(window, window[1:])
    ):
        return None, "gaps"
    if any(
        row.unit != unit
        or row.quality_status != "healthy"
        or not row.value.is_finite()
        or row.value < 0
        for row in window
    ):
        return None, "invalid_samples"
    values = sorted(row.value for row in window)
    rank = (95 * len(values) + 99) // 100
    return SeriesStats(
        source_id=window[0].source_id,
        first_sample=window[0].timestamp,
        last_sample=window[-1].timestamp,
        samples=len(values),
        interval_seconds=interval,
        p95=values[rank - 1],
        peak=values[-1],
    ), None


def analyze(
    session: Session, resource: InfrastructureResource, body: AnalysisRequest, at: datetime
) -> Analysis:
    result = Analysis(
        resource_id=resource.id,
        resource_name=resource.name,
        is_synthetic=resource.is_synthetic,
        evaluated_at=at,
        status="insufficient_data",
    )
    pod = resource.resource_type == "kubernetes_pod"
    if not pod and resource.resource_type != "virtual_machine":
        result.status = "unsupported_resource"
        result.reasons = ["resource_type_requires_workload_aggregation"]
        return result
    if pod and body.pricing is not None:
        raise CollectionError("pricing_requires_virtual_machine")
    result.pricing = body.pricing
    result.baseline_kind = "pod_requests" if pod else "vm_capacity"
    cpu = resource.cpu_requests if pod else resource.cpu_capacity
    memory = resource.memory_requests_bytes if pod else resource.memory_capacity_bytes
    if cpu is None or cpu <= 0 or memory is None or memory <= 0:
        result.reasons = ["missing_positive_baseline"]
        return result
    result.baseline = Size(cpu_cores=cpu, memory_bytes=int(memory))
    if resource.status.lower() in {"not_seen", "failed", "succeeded", "terminated"} or (
        at - resource.last_seen_at > timedelta(days=1)
    ):
        result.reasons = ["inventory_stale_or_inactive"]
        return result

    rows = session.scalars(
        select(ResourceMetric)
        .where(
            ResourceMetric.resource_id == resource.id,
            ResourceMetric.metric_name.in_(SERIES),
            ResourceMetric.timestamp >= at - HISTORY - FRESHNESS - timedelta(hours=2),
            ResourceMetric.timestamp <= at,
        )
        .order_by(ResourceMetric.timestamp)
        .limit(MAX_SAMPLES + 1)
    ).all()
    if len(rows) > MAX_SAMPLES:
        result.reasons = ["sample_limit_exceeded"]
        return result
    end = rows[-1].timestamp if rows else at
    start = end - HISTORY
    evidence = []
    for name, unit in SERIES.items():
        stats, reason = summarize(
            [row for row in rows if row.metric_name == name],
            start,
            end,
            unit,
        )
        if reason:
            result.reasons.append(f"{name}:{reason}")
        elif stats is not None:
            if at - stats.last_sample > FRESHNESS:
                result.reasons.append(f"{name}:stale")
            evidence.append(stats)
    if result.reasons or len(evidence) != 2:
        return result

    sources = session.scalars(
        select(DataSource).where(
            DataSource.id.in_({resource.source_id, *(stats.source_id for stats in evidence)})
        )
    ).all()
    if any(source.status in {"failed", "partial"} for source in sources):
        result.reasons = ["source_degraded"]
        return result
    result.evidence = Evidence(start=start, end=end, cpu=evidence[0], memory=evidence[1])
    if not pod and (evidence[0].peak > cpu or evidence[1].peak > memory):
        result.reasons = ["observations_exceed_vm_capacity"]
        return result

    limits: tuple[Decimal | None, Decimal | None] = (None, None)
    if pod:
        limits = resource.cpu_limits, resource.memory_limits_bytes
        result.cpu_limit_cores = limits[0]
        result.memory_limit_bytes = int(limits[1]) if limits[1] is not None else None
        if (limits[0] is not None and max(cpu, evidence[0].peak) > limits[0]) or (
            limits[1] is not None and max(memory, evidence[1].peak) > limits[1]
        ):
            result.reasons = ["requests_or_observations_exceed_pod_limits"]
            return result

    result.candidates = propose(
        result.baseline, result.evidence, pod=pod, limits=limits, pricing=body.pricing
    )
    if result.candidates:
        result.status = "candidates"
    else:
        result.status = "no_candidates"
        result.reasons = [
            "no_offer_meets_sizing_threshold"
            if body.pricing
            else "no_distinct_candidate_within_limits"
        ]
    return result
