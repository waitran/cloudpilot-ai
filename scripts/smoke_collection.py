"""Explicit synthetic HTTP smoke test: durable worker, CSV, persistence and idempotency."""

import json
import os
import time
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4


def main():
    base = "http://127.0.0.1:" + os.environ.get("FRONTEND_PORT", "15173") + "/api/v1"
    opener = build_opener(ProxyHandler({}))
    fixture = Path(__file__).resolve().parents[1] / "tests/fixtures/collection"

    def request(path, data=None, content_type="application/json"):
        req = Request(base + path, data=data, headers={"Content-Type": content_type})
        with opener.open(req, timeout=15) as response:
            return json.load(response)

    identifier = uuid4().hex[:12]
    source = request(
        "/sources",
        json.dumps(
            {
                "name": "smoke-" + identifier,
                "type": "csv",
                "scope": "smoke-" + identifier,
                "is_synthetic": True,
            }
        ).encode(),
    )

    def upload(kind, raw=None, expected="completed"):
        boundary = "cloudpilot-" + uuid4().hex
        body = bytearray()
        for key, value in {"source_id": source["id"], "kind": kind}.items():
            body.extend(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
            )
        body.extend(
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{kind}.csv"\r\nContent-Type: text/csv\r\n\r\n'.encode()
        )
        body.extend(raw if raw is not None else (fixture / (kind + ".csv")).read_bytes())
        body.extend(f"\r\n--{boundary}--\r\n".encode())
        run = request("/imports/csv", bytes(body), f"multipart/form-data; boundary={boundary}")
        for _ in range(120):
            run = request("/ingestion-runs/" + run["id"])
            if run["status"] not in {"pending", "running"}:
                assert run["status"] == expected, run["error_summary"]
                return run
            time.sleep(0.25)
        raise AssertionError("Worker did not finish the durable job")

    assert upload("resources")["records_created"] == 2
    assert upload("metrics")["records_created"] == 4
    assert upload("metrics")["records_updated"] == 4
    assert upload("billing")["records_created"] == 3
    assert upload("billing")["records_updated"] == 3
    # Verify the production proxy accepts >1 MiB; every oversized field is reported
    # as an invalid row without creating resources or bypassing the 2 MiB file limit.
    large = (
        b"external_id,resource_type,name\n"
        + (b"invalid,virtual_machine," + b"x" * 600 + b"\n") * 2500
    )
    assert 1024 * 1024 < len(large) < 2 * 1024 * 1024
    rejected = upload("resources", large, expected="failed")
    assert rejected["records_rejected"] == 2500
    resources = request("/resources?source_id=" + source["id"])
    assert resources["total"] == 2
    assert all(r["is_synthetic"] for r in resources["items"])
    assert all(not r["quality"]["optimization_ready"] for r in resources["items"])
    bills = request("/billing/summary?source_id=" + source["id"])
    assert sum(b["records"] for b in bills) == 3
    assert sum(b["unmatched_records"] for b in bills) == 1
    assert {b["currency"] for b in bills} == {"USD", "EUR"}
    print(
        "PASS: real frontend proxy upload (>1 MiB included) -> durable worker -> PostgreSQL -> resource/quality/billing API; repeated imports deduplicate"
    )
    print("Synthetic smoke scope: smoke-" + identifier)


if __name__ == "__main__":
    main()
