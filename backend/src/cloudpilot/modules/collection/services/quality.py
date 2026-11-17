from datetime import timedelta

from sqlalchemy import case, func, select

from cloudpilot.modules.collection.models import DataSource, ResourceMetric, now
from cloudpilot.modules.collection.schemas import Quality, ResourceView


def resource_view(session, resource):
    result = ResourceView.model_validate(resource)
    ordered = (
        select(
            ResourceMetric.metric_name.label("name"),
            ResourceMetric.source_id.label("source"),
            ResourceMetric.timestamp.label("at"),
            ResourceMetric.value.label("value"),
            ResourceMetric.expected_interval_seconds.label("step"),
            func.lag(ResourceMetric.timestamp)
            .over(
                partition_by=(ResourceMetric.source_id, ResourceMetric.metric_name),
                order_by=ResourceMetric.timestamp,
            )
            .label("previous"),
        )
        .where(
            ResourceMetric.resource_id == resource.id,
            ResourceMetric.timestamp >= now() - timedelta(days=8),
        )
        .subquery()
    )
    gap = func.extract("epoch", ordered.c.at - ordered.c.previous) > ordered.c.step * 1.5
    rows = (
        session.execute(
            select(
                ordered.c.name,
                ordered.c.source,
                func.min(ordered.c.at).label("first"),
                func.max(ordered.c.at).label("last"),
                func.max(ordered.c.value).label("maximum"),
                func.sum(case((gap, 1), else_=0)).label("gaps"),
            ).group_by(ordered.c.name, ordered.c.source)
        )
        .mappings()
        .all()
    )
    latest_rows = session.scalars(
        select(ResourceMetric)
        .where(
            ResourceMetric.resource_id == resource.id,
            ResourceMetric.timestamp >= now() - timedelta(days=8),
        )
        .distinct(ResourceMetric.metric_name)
        .order_by(ResourceMetric.metric_name, ResourceMetric.timestamp.desc(), ResourceMetric.id)
    ).all()
    result.latest_metrics = {
        r.metric_name: {"value": str(r.value), "unit": r.unit, "timestamp": r.timestamp}
        for r in latest_rows
    }
    reasons, selected = [], []
    for name in ("cpu_usage_cores", "memory_usage_bytes"):
        options = [s for s in rows if s["name"] == name]
        if options:
            selected.append(max(options, key=lambda s: (s["last"], s["last"] - s["first"])))
            if len(options) > 1:
                reasons.append("multiple_metric_sources")
        else:
            reasons.append(f"missing_{name}")
    latest_at = max((s["last"] for s in selected), default=None)
    history = min((int((s["last"] - s["first"]).total_seconds()) for s in selected), default=0)
    gaps = sum(s["gaps"] for s in selected)
    if history < 7 * 86400:
        reasons.append("insufficient_history_7d")
    if gaps:
        reasons.append("metric_gaps")
    stale = any(s["last"] < now() - timedelta(minutes=15) for s in selected)
    if stale:
        reasons.append("metrics_stale")
    if resource.status == "not_seen" or resource.last_seen_at < now() - timedelta(days=1):
        reasons.append("inventory_stale")
    source_ids = {resource.source_id} | {s["source"] for s in selected}
    sources = session.scalars(select(DataSource).where(DataSource.id.in_(source_ids))).all()
    if any(s.status in {"failed", "partial"} for s in sources):
        reasons.append("source_degraded")
    invalid = any(
        (
            s["name"] == "cpu_usage_cores"
            and resource.cpu_capacity is not None
            and s["maximum"] > resource.cpu_capacity
        )
        or (
            s["name"] == "memory_usage_bytes"
            and resource.memory_capacity_bytes is not None
            and s["maximum"] > resource.memory_capacity_bytes
        )
        for s in rows
    )
    if invalid:
        reasons.append("usage_exceeds_known_capacity")
    status = (
        "invalid"
        if invalid
        else "unavailable"
        if not result.latest_metrics
        else "stale"
        if stale
        else "partial"
        if reasons
        else "healthy"
    )
    result.quality = Quality(
        status=status,
        reasons=sorted(set(reasons)),
        latest_at=latest_at,
        history_seconds=history,
        gap_count=gaps,
        optimization_ready=not reasons and len(selected) == 2,
    )
    return result
