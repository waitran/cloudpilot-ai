"""Assert real local HTTP responses after startup; never invoke cloud operations."""

import json
import os
from urllib.request import ProxyHandler, build_opener


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


if __name__ == "__main__":
    main()
