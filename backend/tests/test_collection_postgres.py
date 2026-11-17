import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from cloudpilot.core.config import Settings
from cloudpilot.db.database import Database
from cloudpilot.main import create_app
from cloudpilot.modules.collection.connectors.base import Batch, CollectionError
from cloudpilot.modules.collection.models import (
    BillingRecord,
    InfrastructureResource,
    IngestionRun,
    ResourceMetric,
    now,
)
from cloudpilot.modules.collection.schemas import ResourceInput
from cloudpilot.modules.collection.services.ingestion import claim
from cloudpilot.modules.collection.tasks.worker import process_one
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.engine import make_url

pytestmark = pytest.mark.integration


@pytest.fixture
def collection(monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not provided")
    assert (make_url(url).database or "").endswith("_test")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("ENVIRONMENT", "testing")
    settings = Settings(_env_file=None)
    command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
    database = Database(settings)
    with database.engine.begin() as c:
        c.execute(text("TRUNCATE data_sources, worker_heartbeats CASCADE"))
    with TestClient(create_app(settings)) as client:
        yield client, database, settings
    database.close()


def source(client, type="csv", scope="test", synthetic=True):
    response = client.post(
        "/api/v1/sources",
        json={"name": str(uuid4()), "type": type, "scope": scope, "is_synthetic": synthetic},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def upload(client, source_id, kind, content):
    response = client.post(
        "/api/v1/imports/csv",
        data={"source_id": source_id, "kind": kind},
        files={"file": ("test.csv", content, "text/csv")},
    )
    assert response.status_code == 202, response.text
    return response.json()["id"]


def run(client, identifier):
    return client.get(f"/api/v1/ingestion-runs/{identifier}").json()


def test_durable_csv_pipeline_idempotency_billing_reconciliation_and_quality(collection):
    client, database, settings = collection
    sid = source(client)
    billing = "external_resource_id,service,period_start,period_end,amount,currency\nvm,compute,2026-01-01T00:00:00Z,2026-01-02T00:00:00Z,0.1,USD\nvm,compute,2026-01-01T00:00:00Z,2026-01-02T00:00:00Z,0.2,EUR\nmissing,compute,2026-01-01T00:00:00Z,2026-01-02T00:00:00Z,0.2,USD\n"
    job = upload(client, sid, "billing", billing)
    assert run(client, job)["status"] == "pending"
    process_one(database, settings)
    assert run(client, job)["records_created"] == 3
    assert sum(g["unmatched_records"] for g in client.get("/api/v1/billing/summary").json()) == 3
    resources = "external_id,resource_type,name,cpu_capacity,memory_capacity_bytes\nvm,virtual_machine,server,2,1073741824\nbad,virtual_machine,bad,-2,0\n"
    job = upload(client, sid, "resources", resources)
    process_one(database, settings)
    assert run(client, job)["status"] == "partial"
    assert run(client, job)["records_rejected"] == 1
    assert sum(g["unmatched_records"] for g in client.get("/api/v1/billing/summary").json()) == 1
    at = datetime.now(UTC) - timedelta(seconds=5)
    metrics = (
        "external_resource_id,metric_name,value,unit,timestamp\n"
        f"vm,cpu_usage_cores,250,millicores,{at.isoformat()}\n"
        f"vm,memory_usage_bytes,128,MiB,{at.isoformat()}\n"
        f"unknown,cpu_usage_cores,1,cores,{at.isoformat()}\n"
    )
    for _ in range(2):
        job = upload(client, sid, "metrics", metrics)
        process_one(database, settings)
        assert run(client, job)["status"] == "partial"
    assert run(client, job)["records_updated"] == 2
    response = client.get("/api/v1/resources").json()
    assert response["total"] == 1
    resource = response["items"][0]
    rid = resource["id"]
    assert resource["last_seen_at"].endswith("Z")
    assert resource["quality"]["status"] == "partial"
    assert resource["quality"]["optimization_ready"] is False
    assert "insufficient_history_7d" in resource["quality"]["reasons"]
    assert client.get(f"/api/v1/resources/{rid}/metrics").json()["total"] == 2
    assert client.get(f"/api/v1/resources/{rid}/billing").json()["total"] == 2
    groups = client.get("/api/v1/billing/summary").json()
    assert {g["currency"]: g["amount"] for g in groups} == {
        "EUR": "0.200000000",
        "USD": "0.300000000",
    }
    assert client.get("/api/v1/data-quality/summary").json()["states"]["partial"] == 1
    assert client.get("/api/v1/resources", params={"q": "%"}).json()["total"] == 0
    with database.sessions() as s:
        assert s.scalar(select(func.count()).select_from(BillingRecord)) == 3
        assert s.scalar(select(func.count()).select_from(ResourceMetric)) == 2
        assert s.get(IngestionRun, __import__("uuid").UUID(job)).payload == {}


def test_leases_survive_process_loss_and_fence_old_workers(collection):
    client, database, settings = collection
    sid = source(client)
    identifier = upload(
        client, sid, "resources", "external_id,resource_type,name\nu,virtual_machine,vm\n"
    )
    first = claim(database)
    assert first and run(client, identifier)["status"] == "running"
    assert claim(database) is None
    with database.sessions.begin() as s:
        job = s.get(IngestionRun, first[0])
        job.lease_until = now() - timedelta(seconds=1)
    assert process_one(database, settings)
    assert run(client, identifier)["status"] == "completed"
    assert run(client, identifier)["attempts"] == 2
    assert client.get("/api/v1/resources").json()["total"] == 1


def test_source_failure_preserves_last_success_and_other_sources(collection):
    client, database, settings = collection
    sid = source(client, "kubernetes")
    end = datetime.now(UTC)
    body = {"start": (end - timedelta(hours=1)).isoformat(), "end": end.isoformat()}

    class Good:
        async def collect(self, _):
            return Batch(
                resources=[
                    ResourceInput(
                        external_id="uid",
                        provider="kubernetes",
                        resource_type="kubernetes_pod",
                        name="p",
                    )
                ],
                records_read=1,
            )

    class Bad:
        async def collect(self, _):
            raise CollectionError("kubernetes_unavailable_or_invalid")

    response = client.post(f"/api/v1/sources/{sid}/sync", json=body)
    assert response.status_code == 202
    assert client.post(f"/api/v1/sources/{sid}/sync", json=body).status_code == 409
    process_one(database, settings, Good())
    success = client.get(f"/api/v1/sources/{sid}").json()["last_success_at"]
    assert success
    response = client.post(f"/api/v1/sources/{sid}/sync", json=body)
    process_one(database, settings, Bad())
    assert run(client, response.json()["id"])["status"] == "failed"
    assert client.get(f"/api/v1/sources/{sid}").json()["last_success_at"] == success
    assert client.get("/api/v1/resources").json()["total"] == 1
    assert client.get("/api/v1/health/ready").status_code == 200
    assert source(client, scope="another")


def test_api_rejects_paths_queries_large_files_and_invalid_windows(collection):
    client, _, _ = collection
    assert (
        client.post(
            "/api/v1/sources",
            json={"name": "bad", "type": "prometheus", "scope": "test", "url": "http://internal"},
        ).status_code
        == 422
    )
    assert client.get("/api/v1/resources?limit=1000").status_code == 422
    assert client.get("/api/v1/resources?sort=DROP").status_code == 422
    assert (
        client.post(
            "/api/v1/imports/csv",
            content=b"x" * (2 * 1024 * 1024 + 65537),
            headers={"Content-Type": "multipart/form-data"},
        ).status_code
        == 413
    )
    sid = source(client, "prometheus")
    assert (
        client.post(
            f"/api/v1/sources/{sid}/sync",
            json={"start": "2026-01-01", "end": "2026-02-01", "query": "secret"},
        ).status_code
        == 422
    )


def test_scope_and_synthetic_data_never_cross_match(collection):
    client, database, settings = collection
    for scope, synthetic in [("a", True), ("b", True), ("a", False)]:
        sid = source(client, scope=scope, synthetic=synthetic)
        upload(client, sid, "resources", "external_id,resource_type,name\nu,virtual_machine,vm\n")
        process_one(database, settings)
    assert client.get("/api/v1/resources").json()["total"] == 3
    assert client.get("/api/v1/resources?is_synthetic=false").json()["total"] == 1
    with database.sessions() as s:
        assert s.scalar(select(func.count()).select_from(InfrastructureResource)) == 3


def test_quality_history_gaps_stale_capacity_and_source_health(collection):
    client, database, settings = collection
    sid = source(client, synthetic=False)
    upload(
        client,
        sid,
        "resources",
        "external_id,resource_type,name,cpu_capacity,memory_capacity_bytes\nu,virtual_machine,vm,2,1073741824\n",
    )
    process_one(database, settings)
    rid = client.get("/api/v1/resources").json()["items"][0]["id"]

    sid, rid = UUID(sid), UUID(rid)
    end = now() - timedelta(seconds=5)
    with database.sessions.begin() as session:
        session.add_all(
            [
                ResourceMetric(
                    resource_id=rid,
                    source_id=sid,
                    metric_name=name,
                    value=value,
                    unit=unit,
                    timestamp=end - timedelta(hours=i),
                    expected_interval_seconds=3600,
                )
                for name, value, unit in [
                    ("cpu_usage_cores", "0.25", "cores"),
                    ("memory_usage_bytes", "100000", "bytes"),
                ]
                for i in range(169)
            ]
        )
    healthy = client.get(f"/api/v1/resources/{rid}").json()["quality"]
    assert healthy["status"] == "healthy"
    assert healthy["optimization_ready"] is True
    with database.sessions.begin() as s:
        sample = s.scalar(
            select(ResourceMetric).where(
                ResourceMetric.metric_name == "cpu_usage_cores",
                ResourceMetric.timestamp == end - timedelta(hours=20),
            )
        )
        s.delete(sample)
    gaps = client.get(f"/api/v1/resources/{rid}").json()["quality"]
    assert gaps["gap_count"] == 1 and gaps["status"] == "partial"
    with database.sessions.begin() as s:
        sample = s.scalar(
            select(ResourceMetric).where(ResourceMetric.metric_name == "cpu_usage_cores")
        )
        sample.value = 3
    assert client.get(f"/api/v1/resources/{rid}").json()["quality"]["status"] == "invalid"
    with database.sessions.begin() as s:
        for sample in s.scalars(select(ResourceMetric)):
            sample.value = 1
            sample.timestamp -= timedelta(minutes=30)
    assert client.get(f"/api/v1/resources/{rid}").json()["quality"]["status"] == "stale"


def test_prometheus_name_without_uid_cannot_match_csv_inventory(collection):
    client, database, settings = collection
    csv_id = source(client)
    upload(
        client,
        csv_id,
        "resources",
        "external_id,resource_type,name,namespace\nu,kubernetes_pod,api,default\n",
    )
    process_one(database, settings)
    prom_id = source(client, "prometheus")
    end = now()
    body = {"start": (end - timedelta(hours=1)).isoformat(), "end": end.isoformat()}
    job = client.post(f"/api/v1/sources/{prom_id}/sync", json=body).json()

    class Ambiguous:
        async def collect(self, _):
            return Batch(
                records_read=1,
                metrics=[
                    {
                        "external_resource_id": "__resolve_pod__",
                        "pod": "api",
                        "namespace": "default",
                        "timestamp": end.isoformat(),
                        "value": "1",
                        "unit": "cores",
                        "metric_name": "cpu_usage_cores",
                    }
                ],
            )

    process_one(database, settings, Ambiguous())
    assert run(client, job["id"])["records_rejected"] == 1
    with database.sessions() as s:
        assert s.scalar(select(func.count()).select_from(ResourceMetric)) == 0


def seed_optimization_resource(collection, pod=False):
    client, database, settings = collection
    sid = source(client)
    kind = "kubernetes_pod" if pod else "virtual_machine"
    fields = (
        "cpu_requests,memory_requests_bytes,cpu_limits,memory_limits_bytes"
        if pod
        else "cpu_capacity,memory_capacity_bytes"
    )
    values = "2,2147483648,2,2147483648" if pod else "4,4294967296"
    upload(
        client,
        sid,
        "resources",
        f"external_id,resource_type,name,{fields}\nopt-1,{kind},sample,{values}\n",
    )
    process_one(database, settings)
    resource = client.get("/api/v1/resources").json()["items"][0]
    at = now() - timedelta(minutes=1)

    with database.sessions.begin() as session:
        session.add_all(
            ResourceMetric(
                resource_id=UUID(resource["id"]),
                source_id=UUID(sid),
                metric_name=name,
                value=peak if hours == 100 else usual,
                unit=unit,
                timestamp=at - timedelta(hours=hours),
                expected_interval_seconds=3600,
            )
            for hours in range(169)
            for name, unit, usual, peak in (
                ("cpu_usage_cores", "cores", "0.3", "0.8"),
                ("memory_usage_bytes", "bytes", "134217728", "536870912"),
            )
        )
    return f"/api/v1/optimization/resources/{resource['id']}/analyze"


def test_optimizer_returns_pod_candidates_and_refuses_gaps(collection):
    client, database, _ = collection
    endpoint = seed_optimization_resource(collection, pod=True)
    response = client.post(endpoint, json={})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "candidates"
    assert result["is_synthetic"]
    assert result["baseline_kind"] == "pod_requests"
    assert result["evidence"]["cpu"]["peak"] == "0.800000000"
    assert result["evidence"]["cpu"]["p95"] == "0.300000000"
    assert result["evidence"]["memory"]["samples"] == 169
    assert len(result["candidates"]) == 3
    assert all(c["cost"] is None and c["direction"] == "downsize" for c in result["candidates"])
    assert result["candidates"][1]["proposed"]["cpu_cores"] == "1.04"
    assert result["candidates"][1]["proposed"]["memory_bytes"] == "704643072"
    with database.sessions.begin() as s:
        oldest = s.scalar(
            select(ResourceMetric.timestamp).order_by(ResourceMetric.timestamp).limit(1)
        )
        s.execute(
            delete(ResourceMetric).where(ResourceMetric.timestamp == oldest + timedelta(hours=48))
        )
    incomplete = client.post(endpoint, json={}).json()
    assert incomplete["status"] == "insufficient_data"
    assert incomplete["candidates"] == []
    assert "memory_usage_bytes:gaps" in incomplete["reasons"]


def test_optimizer_prices_matching_vm_offers_with_exact_transition_cost(collection):
    client, _, _ = collection
    endpoint = seed_optimization_resource(collection)
    pricing = {
        "currency": "EUR",
        "reference": "Synthetic terms for integration test",
        "hours": 720,
        "baseline_hourly_rate": "0.12",
        "baseline_recurring_extra": "10.05",
        "offers": [
            {
                "name": "too small",
                "cpu_cores": 1,
                "memory_bytes": 2147483648,
                "hourly_rate": "0.01",
            },
            {
                "name": "candidate B",
                "cpu_cores": 2,
                "memory_bytes": 2147483648,
                "hourly_rate": "0.02",
                "transition_cost": "100",
            },
            {
                "name": "candidate A",
                "cpu_cores": 2,
                "memory_bytes": 2147483648,
                "hourly_rate": "0.075",
                "recurring_extra": "10.05",
                "transition_cost": "15",
            },
        ],
    }
    result = client.post(endpoint, json={"pricing": pricing})
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["pricing"]["reference"] == pricing["reference"]
    assert [c["name"] for c in data["candidates"]] == ["candidate A", "candidate B"]
    best, expensive = [c["cost"] for c in data["candidates"]]
    assert Decimal(best["baseline_total"]) == Decimal("96.45")
    assert Decimal(best["candidate_total"]) == Decimal("79.05")
    assert Decimal(best["savings"]) == Decimal("17.40")
    assert Decimal(best["savings_percent"]) == Decimal("18.04")
    assert Decimal(expensive["savings"]) < 0
    no_offer = client.post(endpoint, json={"pricing": {**pricing, "offers": pricing["offers"][:1]}})
    assert no_offer.json()["status"] == "no_candidates"
    invalid = client.post(endpoint, json={"pricing": {**pricing, "hours": 0}})
    assert invalid.status_code == 422
