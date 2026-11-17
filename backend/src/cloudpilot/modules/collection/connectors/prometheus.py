import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import httpx

from cloudpilot.modules.collection.connectors.base import Batch, CollectionError
from cloudpilot.modules.collection.schemas import METRICS, SyncRequest

# This server-owned profile intentionally contains no user-supplied PromQL.
PROFILE = {
    "cpu_usage_cores": 'sum by(namespace,pod,uid,pod_uid)(rate(container_cpu_usage_seconds_total{container!="",container!="POD",pod!=""}[5m]))',
    "memory_usage_bytes": 'sum by(namespace,pod,uid,pod_uid)(container_memory_working_set_bytes{container!="",container!="POD",pod!=""})',
}
MAX_RESPONSE = 4 * 1024 * 1024


class PrometheusConnector:
    def __init__(self, url: str, token: str | None = None, transport=None):
        self.url, self.token, self.transport = url, token, transport

    async def collect(self, window: SyncRequest) -> Batch:
        batch = Batch()
        if not self.url:
            raise CollectionError("prometheus_not_configured", 503)
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            async with httpx.AsyncClient(
                base_url=self.url.rstrip("/") + "/",
                headers=headers,
                timeout=httpx.Timeout(20, connect=3),
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
            ) as client:
                await self._query(client, "api/v1/query", {"query": "up"}, "vector")
                for name, query in PROFILE.items():
                    results = await self._query(
                        client,
                        "api/v1/query_range",
                        {
                            "query": query,
                            "start": window.start.timestamp(),
                            "end": window.end.timestamp(),
                            "step": window.step,
                        },
                        "matrix",
                    )
                    if not results:
                        batch.errors.append({"code": "metric_unavailable", "metric": name})
                    points = 0
                    for series in results:
                        labels, values = series.get("metric", {}), series.get("values", [])
                        if len(values) > 10000:
                            raise CollectionError("prometheus_point_limit")
                        uid = labels.get("uid") or labels.get("pod_uid")
                        for timestamp, raw in values:
                            points += 1
                            batch.records_read += 1
                            if points > 50000:
                                raise CollectionError("prometheus_point_limit")
                            try:
                                value = Decimal(raw)
                                at = datetime.fromtimestamp(float(timestamp), UTC)
                                if not value.is_finite() or value < 0:
                                    raise ValueError
                                if not window.start <= at <= window.end:
                                    raise ValueError
                                value = value.quantize(Decimal("0.000000001"))
                                if name == "memory_usage_bytes":
                                    if value != value.to_integral_value():
                                        raise ValueError
                                batch.metrics.append(
                                    {
                                        "external_resource_id": uid or "__resolve_pod__",
                                        "metric_name": name,
                                        "value": str(value),
                                        "unit": METRICS[name],
                                        "timestamp": at.isoformat(),
                                        "expected_interval_seconds": window.step,
                                        "pod": labels.get("pod"),
                                        "namespace": labels.get("namespace"),
                                        "identity_provider": "kubernetes",
                                    }
                                )
                            except (ValueError, InvalidOperation, OverflowError, TypeError):
                                batch.records_rejected += 1
                                if len(batch.errors) < 100:
                                    batch.errors.append(
                                        {"code": "invalid_prometheus_sample", "metric": name}
                                    )
        except CollectionError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise CollectionError("prometheus_unavailable_or_invalid", 503) from None
        return batch

    async def _query(self, client, path, params, expected):
        async with client.stream("GET", path, params=params) as response:
            if response.status_code != 200:
                raise CollectionError("prometheus_http_error", 503)
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw) > MAX_RESPONSE:
                    raise CollectionError("prometheus_response_limit")
        data = json.loads(raw)
        if data.get("status") != "success" or data.get("warnings"):
            raise CollectionError("prometheus_query_incomplete")
        body = data["data"]
        result = body["result"]
        if body["resultType"] != expected or not isinstance(result, list):
            raise CollectionError("prometheus_invalid_response")
        if len(result) > 100:
            raise CollectionError("prometheus_series_limit")
        return result
