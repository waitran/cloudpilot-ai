"""Assert real local HTTP responses after startup; never invoke cloud operations."""

import json
import os
from datetime import UTC, datetime
from urllib.request import ProxyHandler, Request, build_opener


def main() -> None:
    backend = "http://127.0.0.1:" + os.environ.get("BACKEND_PORT", "18080")
    frontend = "http://127.0.0.1:" + os.environ.get("FRONTEND_PORT", "15173")
    opener = build_opener(ProxyHandler({}))

    def get(url: str) -> bytes:
        with opener.open(url, timeout=10) as response:
            assert response.status == 200, f"HTTP failure for {url}"
            return response.read()

    assert json.loads(get(backend + "/api/v1/health/live"))["status"] == "alive"
    assert json.loads(get(backend + "/api/v1/health/ready"))["status"] == "ready"
    info = json.loads(get(backend + "/api/v1/system/info"))
    assert info["components"]["postgresql"]["status"] == "available"
    assert b"swagger" in get(backend + "/docs").lower()
    assert "/api/v1/system/info" in json.loads(get(backend + "/openapi.json"))["paths"]
    assert b"CloudPilot AI" in get(frontend + "/")
    assert json.loads(get(frontend + "/api/v1/system/info")) == info
    assert b"CloudPilot AI" in get(frontend + "/resources")
    print("PASS: liveness, readiness, system info, Swagger, frontend, API proxy and SPA routing")
    assert b"CloudPilot AI" in get(frontend + "/capacity")
    scenario = {
        "additional_replicas": 3,
        "pod": {"cpu_millicores": 500, "memory_bytes": 536870912},
        "capacity_deadline_seconds": 180,
        "snapshot": {
            "context": "explicit-synthetic-smoke",
            "namespace": "demo",
            "observed_at": datetime.now(UTC).isoformat(),
            "synthetic": True,
            "inventory_complete": True,
            "constraints_reviewed": True,
            "namespace_quota": {},
            "pod_ips_remaining": 10,
            "pools_complete": True,
            "nodes": [
                {
                    "name": "demo-node",
                    "eligible": True,
                    "allocatable": {"cpu_millicores": 4000, "memory_bytes": 8589934592, "pods": 20},
                    "occupied": {"cpu_millicores": 1000, "memory_bytes": 2147483648, "pods": 5},
                }
            ],
        },
    }

    def evaluate(body):
        request = Request(
            frontend + "/api/v1/feasibility/evaluate",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with opener.open(request, timeout=10) as response:
            return json.load(response)

    report = evaluate(scenario)
    assert report["status"] == "feasible_now"
    assert sum(p["replicas"] for p in report["placement"]) == 3
    scenario["snapshot"]["namespace_quota"] = {"pods": 2}
    assert evaluate(scenario)["status"] == "infeasible"
    scenario["snapshot"]["namespace_quota"] = None
    assert evaluate(scenario)["status"] == "insufficient_data"
    print(
        "PASS: feasibility through frontend proxy: placement, quota rejection, incomplete snapshot"
    )


if __name__ == "__main__":
    main()
