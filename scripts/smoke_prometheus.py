"""Exercise the real Prometheus query/query_range API using explicit synthetic exporter data."""

import json
import os
import time
from datetime import UTC, datetime, timedelta
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4


def main():
    base = "http://127.0.0.1:" + os.environ.get("BACKEND_PORT", "18080") + "/api/v1"
    opener = build_opener(ProxyHandler({}))

    def request(path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        with opener.open(
            Request(base + path, data=data, headers={"Content-Type": "application/json"}),
            timeout=15,
        ) as response:
            return json.load(response)

    suffix = uuid4().hex[:12]
    scope = "prom-smoke-" + suffix
    # The synthetic Pod UID is intentionally identical to the exporter label.
    source = request(
        "/sources",
        {"name": scope + "-inventory", "scope": scope, "type": "csv", "is_synthetic": True},
    )
    boundary = "smoke" + suffix
    content = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="source_id"\r\n\r\n{source["id"]}\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="kind"\r\n\r\nresources\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="resources.csv"\r\n\r\n'
        "external_id,resource_type,name,namespace\nsynthetic-pod-uid-1,kubernetes_pod,synthetic-api,demo\n"
        f"\r\n--{boundary}--\r\n"
    ).encode()
    with opener.open(
        Request(
            base + "/imports/csv",
            data=content,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        ),
        timeout=15,
    ) as response:
        job = json.load(response)

    def wait(job):
        for _ in range(160):
            job = request("/ingestion-runs/" + job["id"])
            if job["status"] not in {"pending", "running"}:
                return job
            time.sleep(0.25)
        raise AssertionError("Prometheus job timed out")

    assert wait(job)["status"] == "completed"
    prom = request(
        "/sources",
        {"name": scope + "-metrics", "scope": scope, "type": "prometheus", "is_synthetic": True},
    )
    for _ in range(10):
        end = datetime.now(UTC)
        job = request(
            f"/sources/{prom['id']}/sync",
            {"start": (end - timedelta(minutes=1)).isoformat(), "end": end.isoformat(), "step": 15},
        )
        job = wait(job)
        resources = request("/resources?source_id=" + source["id"])["items"]
        latest = resources[0]["latest_metrics"]
        if {"cpu_usage_cores", "memory_usage_bytes"} <= latest.keys():
            assert float(latest["cpu_usage_cores"]["value"]) > 0
            assert float(latest["memory_usage_bytes"]["value"]) == 134217728
            assert not resources[0]["quality"]["optimization_ready"]
            print(
                "PASS: real Prometheus scraped explicit synthetic data; query_range -> worker -> PostgreSQL -> resource metrics"
            )
            return
        time.sleep(2)
    raise AssertionError("Synthetic CPU/memory did not arrive: " + str(job["error_summary"]))


if __name__ == "__main__":
    main()
