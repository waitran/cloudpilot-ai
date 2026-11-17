from datetime import datetime, timedelta
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from cloudpilot.modules.collection.connectors.base import Batch, CollectionError
from cloudpilot.modules.collection.models import (
    BillingRecord,
    DataSource,
    InfrastructureResource,
    IngestionRun,
    ResourceMetric,
    now,
)
from cloudpilot.modules.collection.schemas import BillingInput, MetricInput, ResourceInput


def candidates(session: Session, source: DataSource, external_id: str, provider=None):
    query = select(InfrastructureResource).where(
        InfrastructureResource.account_or_cluster_id == source.scope,
        InfrastructureResource.is_synthetic == source.is_synthetic,
        InfrastructureResource.external_id == external_id,
    )
    if provider:
        query = query.where(InfrastructureResource.provider == provider)
    return session.scalars(query.limit(2)).all()


def match_resource(session, source, item):
    external_id = item["external_resource_id"]
    if external_id != "__resolve_pod__":
        matches = candidates(session, source, external_id, item.get("identity_provider"))
    else:
        # Names alone are not identities: require fresh, unique inventory and a lifecycle
        # timestamp supplied by the Kubernetes API, never by uploaded CSV configuration.
        at = datetime.fromisoformat(item["timestamp"])
        matches = session.scalars(
            select(InfrastructureResource)
            .where(
                InfrastructureResource.account_or_cluster_id == source.scope,
                InfrastructureResource.is_synthetic == source.is_synthetic,
                InfrastructureResource.provider == "kubernetes",
                InfrastructureResource.resource_type == "kubernetes_pod",
                InfrastructureResource.namespace == item.get("namespace"),
                InfrastructureResource.name == item.get("pod"),
                InfrastructureResource.status != "not_seen",
                InfrastructureResource.last_seen_at >= now() - timedelta(minutes=15),
            )
            .limit(2)
        ).all()
        matches = [
            r
            for r in matches
            if r.configuration.get("created_at")
            and datetime.fromisoformat(r.configuration["created_at"]) <= at <= r.last_seen_at
        ]
    if len(matches) != 1:
        raise CollectionError("resource_mapping_missing_or_ambiguous")
    return matches[0]


def ingest(session: Session, source: DataSource, run: IngestionRun, batch: Batch):
    run.records_read = batch.records_read
    run.records_rejected = batch.records_rejected
    errors = batch.errors[:100]
    seen_ids = []
    groups = [
        ("resources", batch.resources),
        ("metrics", batch.metrics),
        ("billing", batch.billing),
    ]
    for kind, items in groups:
        for index, item in enumerate(items, 1):
            try:
                with session.begin_nested():
                    if kind == "resources":
                        record = (
                            item
                            if isinstance(item, ResourceInput)
                            else ResourceInput.model_validate(item)
                        )
                        values = record.model_dump()
                        matches = candidates(session, source, record.external_id, record.provider)
                        obj = matches[0] if matches else None
                        created = obj is None
                        if obj is None:
                            obj = InfrastructureResource(
                                source_id=source.id,
                                account_or_cluster_id=source.scope,
                                is_synthetic=source.is_synthetic,
                            )
                            session.add(obj)
                        for key, value in values.items():
                            setattr(obj, key, value)
                        obj.source_id = source.id
                        obj.last_seen_at = now()
                        session.flush()
                        seen_ids.append(obj.id)
                    elif kind == "metrics":
                        resource = match_resource(session, source, item)
                        record = MetricInput.model_validate(
                            {k: v for k, v in item.items() if k in MetricInput.model_fields}
                        )
                        obj = session.scalar(
                            select(ResourceMetric).where(
                                ResourceMetric.resource_id == resource.id,
                                ResourceMetric.source_id == source.id,
                                ResourceMetric.metric_name == record.metric_name,
                                ResourceMetric.timestamp == record.timestamp,
                            )
                        )
                        created = obj is None
                        if obj is None:
                            obj = ResourceMetric(resource_id=resource.id, source_id=source.id)
                            session.add(obj)
                        for key, value in record.model_dump(
                            exclude={"external_resource_id"}
                        ).items():
                            setattr(obj, key, value)
                        obj.collected_at = now()
                    else:
                        record = BillingInput.model_validate(item)
                        matches = candidates(session, source, record.external_resource_id)
                        obj = session.scalar(
                            select(BillingRecord).where(
                                BillingRecord.source_id == source.id,
                                BillingRecord.external_record_id == record.external_record_id,
                            )
                        )
                        created = obj is None
                        if obj is None:
                            obj = BillingRecord(source_id=source.id)
                            session.add(obj)
                        for key, value in record.model_dump().items():
                            setattr(obj, key, value)
                        obj.resource_id = matches[0].id if len(matches) == 1 else None
                        obj.imported_at = now()
                    session.flush()
                if created:
                    run.records_created += 1
                else:
                    run.records_updated += 1
            except (CollectionError, ValidationError):
                run.records_rejected += 1
                if len(errors) < 100:
                    errors.append(
                        {
                            "row": batch.csv_row_numbers[index - 1]
                            if batch.csv_row_numbers
                            else index,
                            "kind": kind,
                            "code": "record_invalid_or_unmapped",
                        }
                    )
    if batch.discovery_metadata:
        source.discovery_metadata = batch.discovery_metadata
    if batch.discovery_metadata.get("complete_inventory") and not run.records_rejected:
        old = session.scalars(
            select(InfrastructureResource).where(
                InfrastructureResource.source_id == source.id,
                InfrastructureResource.id.not_in(seen_ids),
            )
        )
        for resource in old:
            resource.status = "not_seen"
    # Reconcile previously unmatched billing only within the same scope and provenance.
    if batch.resources:
        bills = session.scalars(
            select(BillingRecord)
            .join(DataSource)
            .where(
                DataSource.scope == source.scope,
                DataSource.is_synthetic == source.is_synthetic,
            )
        )
        for bill in bills:
            matches = candidates(session, source, bill.external_resource_id)
            bill.resource_id = matches[0].id if len(matches) == 1 else None
    run.error_summary = errors
    rejected = run.records_rejected
    run.status = (
        "failed"
        if not run.records_created + run.records_updated and rejected
        else "partial"
        if rejected or errors
        else "completed"
    )
    finish(source, run)


def finish(source, run):
    run.finished_at = now()
    run.lease_until = None
    run.lease_owner = None
    run.payload = {}  # Validated uploads are retained only until the durable job finishes.
    source.status = run.status
    if run.status == "completed":
        source.last_success_at = run.finished_at
    else:
        source.last_error_at = run.finished_at


def claim(database):
    with database.sessions.begin() as session:
        run = session.scalar(
            select(IngestionRun)
            .where(
                or_(
                    IngestionRun.status == "pending",
                    and_(IngestionRun.status == "running", IngestionRun.lease_until < now()),
                )
            )
            .order_by(IngestionRun.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not run:
            return None
        if run.attempts >= 3:
            source = session.get(DataSource, run.source_id)
            run.status = "failed"
            run.error_summary = [{"code": "worker_retry_limit"}]
            finish(source, run)
            return None
        run.status = "running"
        run.started_at = now()
        run.attempts += 1
        run.lease_until = now() + timedelta(minutes=10)
        run.lease_owner = uuid4()
        return run.id, run.lease_owner, run.source_id, run.payload
