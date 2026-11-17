from datetime import datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cloudpilot.modules.collection.connectors.base import CollectionError
from cloudpilot.modules.collection.connectors.csv_import import MAX_UPLOAD, parse_csv
from cloudpilot.modules.collection.models import (
    BillingRecord,
    DataSource,
    InfrastructureResource,
    IngestionRun,
    ResourceMetric,
    now,
)
from cloudpilot.modules.collection.schemas import (
    BillingGroup,
    BillingView,
    MetricName,
    MetricView,
    Page,
    QualitySummary,
    ResourceType,
    ResourceView,
    RunView,
    SourceCreate,
    SourceView,
    SyncRequest,
    utc,
)
from cloudpilot.modules.collection.services.quality import resource_view
from cloudpilot.schemas.system import ErrorResponse

router = APIRouter(
    prefix="/api/v1",
    tags=["Collection"],
    responses={code: {"model": ErrorResponse} for code in (404, 409, 413, 422, 503)},
)


def database_session(request: Request):
    yield from request.app.state.database.session()


DB = Annotated[Session, Depends(database_session)]
Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0, le=100000)]


def get_or_404(session, model, identifier):
    value = session.get(model, identifier)
    if value is None:
        raise CollectionError("not_found", 404)
    return value


def page(session, query, schema, limit, offset):
    total = session.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    return Page(
        items=[
            schema.model_validate(r) for r in session.scalars(query.limit(limit).offset(offset))
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


def enqueue(session, source, payload):
    run = IngestionRun(source_id=source.id, payload=payload)
    session.add(run)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise CollectionError("source_already_queued", 409) from None
    return run


@router.get("/sources", response_model=Page[SourceView])
def sources(session: DB, limit: Limit = 50, offset: Offset = 0):
    return page(
        session,
        select(DataSource).order_by(DataSource.created_at.desc()),
        SourceView,
        limit,
        offset,
    )


@router.post("/sources", response_model=SourceView, status_code=201)
def create_source(body: SourceCreate, session: DB):
    source = DataSource(
        **body.model_dump(),
        settings={
            "profile": "cadvisor-pods-v1"
            if body.type == "prometheus"
            else "read-only-v1"
            if body.type == "kubernetes"
            else "csv-v1"
        },
    )
    session.add(source)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise CollectionError("source_name_exists", 409) from None
    return source


@router.get("/sources/{source_id}", response_model=SourceView)
def source_detail(source_id: UUID, session: DB):
    return get_or_404(session, DataSource, source_id)


@router.post("/sources/{source_id}/sync", response_model=RunView, status_code=202)
def sync(source_id: UUID, body: SyncRequest, session: DB):
    source = get_or_404(session, DataSource, source_id)
    if source.type == "csv":
        raise CollectionError("csv_requires_upload")
    return enqueue(session, source, {"kind": "sync", "window": body.model_dump(mode="json")})


@router.post("/imports/csv", response_model=RunView, status_code=202)
def import_csv(
    session: DB,
    source_id: Annotated[UUID, Form()],
    kind: Annotated[Literal["resources", "metrics", "billing"], Form()],
    file: Annotated[UploadFile, File()],
):
    source = get_or_404(session, DataSource, source_id)
    if source.type != "csv":
        raise CollectionError("source_is_not_csv")
    payload = parse_csv(file.file.read(MAX_UPLOAD + 1), kind)
    return enqueue(session, source, payload)


@router.get("/ingestion-runs", response_model=Page[RunView])
def runs(session: DB, source_id: UUID | None = None, limit: Limit = 50, offset: Offset = 0):
    query = select(IngestionRun).order_by(IngestionRun.created_at.desc())
    if source_id:
        query = query.where(IngestionRun.source_id == source_id)
    return page(session, query, RunView, limit, offset)


@router.get("/ingestion-runs/{run_id}", response_model=RunView)
def run_detail(run_id: UUID, session: DB):
    return get_or_404(session, IngestionRun, run_id)


@router.get("/resources", response_model=Page[ResourceView])
def resources(
    session: DB,
    q: Annotated[str, Query(max_length=100)] = "",
    source_id: UUID | None = None,
    resource_type: ResourceType | None = None,
    namespace: Annotated[str | None, Query(max_length=256)] = None,
    is_synthetic: bool | None = None,
    sort: Literal["name", "last_seen"] = "name",
    limit: Limit = 50,
    offset: Offset = 0,
):
    query = select(InfrastructureResource)
    if q:
        query = query.where(InfrastructureResource.name.icontains(q, autoescape=True))
    for column, value in [
        (InfrastructureResource.source_id, source_id),
        (InfrastructureResource.resource_type, resource_type),
        (InfrastructureResource.namespace, namespace),
        (InfrastructureResource.is_synthetic, is_synthetic),
    ]:
        if value is not None:
            query = query.where(column == value)
    query = query.order_by(
        InfrastructureResource.name
        if sort == "name"
        else InfrastructureResource.last_seen_at.desc(),
        InfrastructureResource.id,
    )
    total = session.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    return Page(
        items=[
            resource_view(session, r) for r in session.scalars(query.limit(limit).offset(offset))
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/resources/{resource_id}", response_model=ResourceView)
def resource_detail(resource_id: UUID, session: DB):
    return resource_view(session, get_or_404(session, InfrastructureResource, resource_id))


def dates(start, end, max_days=None):
    try:
        end = utc(end) if end else now()
        start = utc(start) if start else end - timedelta(days=1)
    except ValueError:
        raise CollectionError("timezone_required") from None
    if (
        start >= end
        or (max_days and end - start > timedelta(days=max_days))
        or end > now() + timedelta(minutes=2)
    ):
        raise CollectionError("invalid_date_window")
    return start, end


@router.get("/resources/{resource_id}/metrics", response_model=Page[MetricView])
def metrics(
    resource_id: UUID,
    session: DB,
    start: datetime | None = None,
    end: datetime | None = None,
    metric_name: MetricName | None = None,
    limit: Limit = 200,
    offset: Offset = 0,
):
    get_or_404(session, InfrastructureResource, resource_id)
    start, end = dates(start, end, 7)
    query = (
        select(ResourceMetric)
        .where(
            ResourceMetric.resource_id == resource_id,
            ResourceMetric.timestamp >= start,
            ResourceMetric.timestamp <= end,
        )
        .order_by(ResourceMetric.timestamp.desc(), ResourceMetric.id)
    )
    if metric_name:
        query = query.where(ResourceMetric.metric_name == metric_name)
    return page(session, query, MetricView, limit, offset)


@router.get("/resources/{resource_id}/billing", response_model=Page[BillingView])
def resource_billing(
    resource_id: UUID,
    session: DB,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
):
    get_or_404(session, InfrastructureResource, resource_id)
    query = select(BillingRecord).where(BillingRecord.resource_id == resource_id)
    if start or end:
        start, end = dates(start, end, 366)
        query = query.where(BillingRecord.period_end > start, BillingRecord.period_start < end)
    return page(
        session, query.order_by(BillingRecord.period_start.desc()), BillingView, limit, offset
    )


@router.get("/billing/summary", response_model=list[BillingGroup])
def billing_summary(
    session: DB,
    source_id: UUID | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    is_synthetic: bool | None = None,
):
    query = select(
        BillingRecord.currency,
        BillingRecord.cost_type,
        DataSource.is_synthetic,
        func.sum(BillingRecord.amount).label("amount"),
        func.count().label("records"),
        func.sum(case((BillingRecord.resource_id.is_(None), 1), else_=0)).label(
            "unmatched_records"
        ),
    ).join(DataSource)
    if source_id:
        query = query.where(DataSource.id == source_id)
    if is_synthetic is not None:
        query = query.where(DataSource.is_synthetic == is_synthetic)
    if start or end:
        start, end = dates(start, end, 366)
        query = query.where(BillingRecord.period_end > start, BillingRecord.period_start < end)
    return (
        session.execute(
            query.group_by(
                BillingRecord.currency, BillingRecord.cost_type, DataSource.is_synthetic
            ).order_by(BillingRecord.currency, BillingRecord.cost_type)
        )
        .mappings()
        .all()
    )


@router.get("/data-quality/summary", response_model=QualitySummary)
def quality_summary(session: DB, is_synthetic: bool | None = None):
    # Explicit ceiling keeps this synchronous MVP summary bounded. Larger estates require
    # materialized quality snapshots; silently truncating a summary would be misleading.
    query = select(InfrastructureResource)
    if is_synthetic is not None:
        query = query.where(InfrastructureResource.is_synthetic == is_synthetic)
    resources = session.scalars(query.limit(1001)).all()
    if len(resources) > 1000:
        raise CollectionError("quality_summary_inventory_limit", 422)
    states = {s: 0 for s in ["healthy", "partial", "stale", "unavailable", "invalid"]}
    ready = 0
    for resource in resources:
        quality = resource_view(session, resource).quality
        states[quality.status] += 1
        ready += int(quality.optimization_ready)
    sources_query = (
        select(func.count()).select_from(DataSource).where(DataSource.last_success_at.is_(None))
    )
    if is_synthetic is not None:
        sources_query = sources_query.where(DataSource.is_synthetic == is_synthetic)
    return QualitySummary(
        total_resources=len(resources),
        states=states,
        optimization_ready=ready,
        sources_without_success=session.scalar(sources_query),
    )
