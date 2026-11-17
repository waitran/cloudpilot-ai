import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from cloudpilot.modules.collection.connectors.base import CollectionError
from cloudpilot.modules.collection.connectors.csv_import import MAX_UPLOAD, parse_csv
from cloudpilot.modules.collection.connectors.kubernetes import (
    KubernetesConnector,
    container_resources,
)
from cloudpilot.modules.collection.connectors.prometheus import PrometheusConnector
from cloudpilot.modules.collection.normalizers.values import quantity
from cloudpilot.modules.collection.schemas import SyncRequest
from kubernetes import client
from pydantic import ValidationError


def window():
    end = datetime.now(UTC) - timedelta(seconds=5)
    return SyncRequest(start=end - timedelta(minutes=10), end=end)


def test_csv_rejects_bad_rows_without_leaking_values():
    raw = b"external_id,resource_type,name,cpu_capacity\nvm-1,virtual_machine,ok,2\nvm-2,virtual_machine,SECRET,-1\nvm-1,virtual_machine,duplicate,2\n"
    payload = parse_csv(raw, "resources")
    assert payload["records_read"] == 3
    assert payload["records_rejected"] == 2
    assert payload["errors"][1]["code"] == "duplicate_record"
    assert "SECRET" not in json.dumps(payload["errors"])


@pytest.mark.parametrize(
    "raw,kind,code",
    [
        (b"x,x\n1,2\n", "resources", "invalid_csv_headers"),
        (b"x\n", "resources", "invalid_csv_headers"),
        (b"\xff", "resources", "csv_requires_utf8"),
        (b"x" * (MAX_UPLOAD + 1), "metrics", "file_too_large"),
    ],
)
def test_csv_rejects_invalid_file(raw, kind, code):
    with pytest.raises(CollectionError, match=code):
        parse_csv(raw, kind)


def test_csv_units_timezone_nan_and_missing_do_not_become_zero():
    at = datetime.now(UTC).isoformat()
    payload = parse_csv(
        (
            "external_resource_id,metric_name,value,unit,timestamp\n"
            f"v,cpu_usage_cores,250,millicores,{at}\n"
            f"v,memory_usage_bytes,1,MiB,{at}\n"
            f"v,cpu_usage_cores,NaN,cores,{at}\n"
            "v,cpu_usage_cores,1,cores,2026-01-01T00:00:00\n"
        ).encode(),
        "metrics",
    )
    assert [Decimal(r["value"]) for r in payload["records"]] == [Decimal("0.25"), Decimal(1048576)]
    assert payload["records_rejected"] == 2


def test_billing_decimal_hash_and_credit_validation():
    raw = b"external_resource_id,service,period_start,period_end,amount,currency\nv,compute,2026-01-01T00:00:00Z,2026-01-02T00:00:00Z,0.123456789,USD\n"
    first, second = parse_csv(raw, "billing"), parse_csv(raw, "billing")
    assert first["records"] == second["records"]
    assert first["records"][0]["amount"] == "0.123456789"
    assert parse_csv(raw.replace(b"0.123456789", b"-1"), "billing")["records_rejected"] == 1


def test_csv_cannot_inject_pod_lifecycle_configuration():
    payload = parse_csv(
        b'external_id,resource_type,name,configuration\nu,kubernetes_pod,p,"{""created_at"":""2026-01-01T00:00:00Z""}"\n',
        "resources",
    )
    assert payload["records_rejected"] == 1


@pytest.mark.parametrize("delta,step", [(8 * 86400, 60), (86400, 1), (7 * 86400, 15)])
def test_range_limits(delta, step):
    end = datetime.now(UTC)
    with pytest.raises(ValidationError):
        SyncRequest(start=end - timedelta(seconds=delta), end=end, step=step)


def test_kubernetes_quantities_and_effective_sidecar_requests():
    assert quantity("250m") == Decimal("0.25")
    assert quantity("128Mi", memory=True) == 134217728
    assert quantity(None) is None
    containers = [
        client.V1Container(
            name="app",
            resources=client.V1ResourceRequirements(requests={"cpu": "200m", "memory": "64Mi"}),
        )
    ]
    init = [
        client.V1Container(
            name="sidecar",
            restart_policy="Always",
            resources=client.V1ResourceRequirements(requests={"cpu": "100m"}),
        ),
        client.V1Container(
            name="init", resources=client.V1ResourceRequirements(requests={"cpu": "1"})
        ),
    ]
    spec = client.V1PodSpec(containers=containers, init_containers=init)
    assert container_resources(spec, "requests")["cpu"] == Decimal("1.1")
    assert container_resources(spec, "limits")["cpu"] is None


def test_prometheus_uses_fixed_queries_and_rejects_nan():
    w = window()
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("query"):
            data = {"resultType": "vector", "result": []}
        else:
            data = {
                "resultType": "matrix",
                "result": [
                    {
                        "metric": {"namespace": "default", "pod": "p", "uid": "u"},
                        "values": [[w.start.timestamp(), "NaN"], [w.end.timestamp(), "0"]],
                    }
                ],
            }
        return httpx.Response(200, json={"status": "success", "data": data})

    batch = asyncio.run(
        PrometheusConnector("http://prom.test", transport=httpx.MockTransport(handler)).collect(w)
    )
    assert len(requests) == 3
    assert batch.records_rejected == 2
    assert len(batch.metrics) == 2
    assert batch.metrics[0]["value"] == "0E-9"
    assert batch.metrics[0]["external_resource_id"] == "u"
    assert all(r.method == "GET" for r in requests)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503),
        httpx.Response(200, json={"status": "error"}),
        httpx.Response(200, json={"status": "success", "warnings": ["partial"], "data": {}}),
    ],
)
def test_prometheus_failures_are_sanitized(response):
    transport = httpx.MockTransport(lambda _: response)
    with pytest.raises(CollectionError):
        asyncio.run(PrometheusConnector("http://prom.test", transport=transport).collect(window()))


def test_official_kubernetes_client_uses_only_read_endpoints():
    api = client.ApiClient(client.Configuration(host="https://cluster.test"))
    paths = []

    def request(method, url, **kwargs):
        paths.append((method, url))
        if url.endswith("/pods"):
            items = [
                {
                    "metadata": {
                        "name": "same-name",
                        "namespace": "default",
                        "uid": "stable-uid",
                        "creationTimestamp": "2026-01-01T00:00:00Z",
                    },
                    "spec": {
                        "containers": [
                            {
                                "name": "app",
                                "resources": {
                                    "requests": {"cpu": "100m", "memory": "128Mi"},
                                    "limits": {"cpu": "1", "memory": "256Mi"},
                                },
                            }
                        ]
                    },
                    "status": {"phase": "Running"},
                }
            ]
            kind = "PodList"
        else:
            items, kind = [], "List"
        return SimpleNamespace(
            data=json.dumps({"apiVersion": "v1", "kind": kind, "metadata": {}, "items": items}),
            status=200,
            getheaders=lambda: {},
        )

    api.rest_client.request = request
    batch = asyncio.run(KubernetesConnector("disabled", api_client=api).collect(window()))
    assert len(paths) == 5
    assert all(method == "GET" for method, _ in paths)
    pod = batch.resources[0]
    assert pod.external_id == "stable-uid"
    assert pod.cpu_requests == Decimal("0.1")
    assert pod.cpu_limits == 1
    assert pod.memory_requests_bytes == 134217728
    assert batch.discovery_metadata["complete_inventory"] is True
    api.close()
