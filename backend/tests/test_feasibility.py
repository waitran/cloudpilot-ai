from datetime import UTC, datetime, timedelta

import pytest
from cloudpilot.modules.feasibility.engine import evaluate
from cloudpilot.modules.feasibility.schemas import Scenario

AT = datetime(2026, 11, 18, tzinfo=UTC)
GIB = 1024**3


def resources(cpu=0, ram=0, pods=0):
    return {"cpu_millicores": cpu, "memory_bytes": ram * GIB, "pods": pods}


def node(name, free_cpu=4000, free_ram=8, eligible=True, free_pods=10):
    return {
        "name": name,
        "eligible": eligible,
        "allocatable": resources(4000, 8, 10),
        "occupied": resources(4000 - free_cpu, 8 - free_ram, 10 - free_pods),
    }


def pool(name, cpu=2000, max_new=3, available=3, ready=120):
    return {
        "name": name,
        "eligible": True,
        "allocatable": resources(cpu, 8, 20),
        "daemon_requests": resources(200, 1, 2),
        "scale_limit_remaining": max_new,
        "provider_nodes_available": available,
        "ready_within_seconds": ready,
    }


@pytest.fixture
def body():
    return {
        "additional_replicas": 3,
        "pod": {"cpu_millicores": 1000, "memory_bytes": GIB},
        "reserve_percent": 0,
        "capacity_deadline_seconds": 180,
        "snapshot": {
            "context": "test-cluster",
            "namespace": "app",
            "observed_at": AT.isoformat(),
            "synthetic": True,
            "inventory_complete": True,
            "constraints_reviewed": True,
            "nodes": [node("worker-1")],
            "namespace_quota": {},
            "pod_ips_remaining": 10,
            "pools_complete": True,
        },
    }


def report(body):
    return evaluate(Scenario.model_validate(body), AT)


def test_fragmentation_and_node_eligibility(body):
    body["snapshot"]["nodes"] = [
        node("cpu-small", free_cpu=900),
        node("ram-full", free_ram=0),
        node("other-zone", eligible=False),
    ]
    result = report(body)
    assert result.status == "infeasible"
    assert result.current_slots == 0
    assert result.checks[-1].code == "capacity_upper_bound"


def test_reserve_and_pod_slots_apply_per_node(body):
    body["reserve_percent"] = 25
    body["snapshot"]["nodes"] = [
        node("worker-1", free_cpu=2900),
        node("worker-2", free_pods=2),
    ]
    result = report(body)
    assert result.status == "feasible_now"
    assert [n.replica_slots for n in result.nodes] == [1, 2]
    assert [(p.node, p.replicas) for p in result.placement] == [("worker-1", 1), ("worker-2", 2)]


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("pod_ips_remaining", 2, "pod_ips_exceeded"),
        ("namespace_quota", {"pods": 2}, "namespace_pods_exceeded"),
        ("namespace_quota", {"cpu_millicores": 2999}, "namespace_cpu_exceeded"),
        ("namespace_quota", {"memory_bytes": 2 * GIB}, "namespace_memory_exceeded"),
    ],
)
def test_confirmed_quota_blocks_even_if_nodes_fit(body, field, value, code):
    body["snapshot"][field] = value
    result = report(body)
    assert result.status == "infeasible"
    assert result.checks[0].code == code
    assert result.scale_options == []


def test_quota_based_on_limits_needs_effective_limit(body):
    body["snapshot"]["namespace_quota"] = {"memory_limit_bytes": 4 * GIB}
    result = report(body)
    assert result.status == "insufficient_data"
    assert result.checks[0].code == "namespace_memory_limits_requires_effective_limit"
    body["pod"]["memory_limit_bytes"] = 2 * GIB
    result = report(body)
    assert result.status == "infeasible"
    assert result.checks[0].required == 6 * GIB


def test_scale_out_alternatives_skip_late_and_exhausted_pools(body):
    body["additional_replicas"] = 5
    body["snapshot"]["nodes"] = [node("worker-1", free_cpu=2000)]
    body["snapshot"]["pools"] = [
        pool("standard"),
        pool("large", cpu=4500),
        pool("late", cpu=8000, ready=181),
        pool("provider-quota", cpu=8000, available=0),
    ]
    result = report(body)
    assert result.status == "scale_out_required"
    assert [(option.pool, option.new_nodes) for option in result.scale_options] == [
        ("large", 1),
        ("standard", 3),
    ]
    assert result.scale_options[0].replicas_on_new_nodes == 3
    assert {check.code for check in result.checks} >= {
        "pool_misses_deadline",
        "pool_unavailable_or_pod_does_not_fit",
    }


def test_failover_uses_worst_lost_capacity_and_requires_displaced_load(body):
    body["tolerate_lost_nodes"] = 1
    body["snapshot"]["nodes"] = [node("worker-1"), node("worker-2", free_cpu=2000)]
    body["snapshot"]["pools"] = [pool("standard")]
    assert report(body).checks[0].code == "incumbent_failover_load_unknown"
    body["snapshot"]["failure_load_accounted"] = True
    result = report(body)
    assert result.current_slots_after_node_loss == 2
    assert result.status == "scale_out_required"
    assert result.scale_options[0].new_nodes == 1
    assert result.scale_options[0].capacity_after_node_loss == 3


def test_known_alternatives_cannot_prove_a_hybrid_plan_impossible(body):
    body["snapshot"]["nodes"] = []
    body["snapshot"]["pools"] = [
        pool("pool-A", cpu=2400, max_new=1),
        pool("pool-B", cpu=2400, max_new=1),
    ]
    assert report(body).status == "no_plan_found"
    body["snapshot"]["pools"][1]["provider_nodes_available"] = None
    assert report(body).status == "insufficient_data"


def test_incomplete_or_expired_snapshot_never_approves(body):
    body["snapshot"]["constraints_reviewed"] = False
    body["snapshot"]["pod_ips_remaining"] = None
    assert {check.code for check in report(body).checks} == {
        "admission_and_placement_not_reviewed",
        "pod_ip_capacity_unknown",
    }
    snapshot = Scenario.model_validate(body)
    assert (
        evaluate(snapshot, AT + timedelta(minutes=16)).checks[0].code
        == "snapshot_expired_or_future"
    )


def test_api_preserves_snapshot_and_rejects_invalid_limit(client, body):
    body["snapshot"]["observed_at"] = datetime.now(UTC).isoformat()
    result = client.post("/api/v1/feasibility/evaluate", json=body)
    assert result.status_code == 200
    assert result.json()["status"] == "feasible_now"
    assert result.json()["scenario"]["snapshot"]["synthetic"]
    body["pod"]["cpu_limit_millicores"] = 999
    assert client.post("/api/v1/feasibility/evaluate", json=body).status_code == 422
