from datetime import datetime, timedelta

from cloudpilot.modules.feasibility.schemas import (
    Check,
    NodeCapacity,
    Placement,
    Pod,
    Report,
    Resources,
    ScaleOption,
    Scenario,
)


def free_after_reserve(total: int, occupied: int, reserve_percent: int) -> int:
    return max(0, total * (100 - reserve_percent) // 100 - occupied)


def node_capacity(
    name: str, eligible: bool, total: Resources, used: Resources, pod: Pod, reserve: int
) -> NodeCapacity:
    cpu = free_after_reserve(total.cpu_millicores, used.cpu_millicores, reserve)
    memory = free_after_reserve(total.memory_bytes, used.memory_bytes, reserve)
    pods = max(0, total.pods - used.pods)
    return NodeCapacity(
        name=name,
        eligible=eligible,
        free_cpu_millicores=cpu,
        free_memory_bytes=memory,
        free_pod_slots=pods,
        replica_slots=min(cpu // pod.cpu_millicores, memory // pod.memory_bytes, pods)
        if eligible
        else 0,
    )


def surviving_slots(existing: list[int], new_slots: int, new_nodes: int, lost: int) -> int:
    largest = sorted([*existing, *([new_slots] * min(lost, new_nodes))], reverse=True)[:lost]
    return sum(existing) + new_slots * new_nodes - sum(largest)


def place(nodes: list[tuple[str, int]], replicas: int) -> list[Placement]:
    placement = []
    for name, slots in nodes:
        count = min(slots, replicas)
        if count:
            placement.append(Placement(node=name, replicas=count))
            replicas -= count
        if not replicas:
            break
    return placement


def quota_checks(scenario: Scenario) -> tuple[list[Check], list[Check]]:
    snap, pod, count = scenario.snapshot, scenario.pod, scenario.additional_replicas
    missing, blockers = [], []
    dimensions = [("pod_ips", 1, snap.pod_ips_remaining, "IP addresses")]
    if snap.pod_ips_remaining is None:
        missing.append(Check(code="pod_ip_capacity_unknown"))
    if snap.namespace_quota is None:
        missing.append(Check(code="namespace_quota_unknown"))
    else:
        quota = snap.namespace_quota
        dimensions.extend(
            [
                ("namespace_pods", 1, quota.pods, "pods"),
                ("namespace_cpu", pod.cpu_millicores, quota.cpu_millicores, "millicores"),
                ("namespace_memory", pod.memory_bytes, quota.memory_bytes, "bytes"),
                (
                    "namespace_cpu_limits",
                    pod.cpu_limit_millicores,
                    quota.cpu_limit_millicores,
                    "millicores",
                ),
                (
                    "namespace_memory_limits",
                    pod.memory_limit_bytes,
                    quota.memory_limit_bytes,
                    "bytes",
                ),
            ]
        )
    for code, per_pod, remaining, unit in dimensions:
        if remaining is None:
            continue
        if per_pod is None:
            missing.append(Check(code=f"{code}_requires_effective_limit"))
        elif count * per_pod > remaining:
            blockers.append(
                Check(
                    code=f"{code}_exceeded",
                    required=count * per_pod,
                    available=remaining,
                    unit=unit,
                )
            )
    return missing, blockers


def evaluate(scenario: Scenario, now: datetime) -> Report:
    snap = scenario.snapshot
    report = Report(status="insufficient_data", evaluated_at=now, scenario=scenario)
    if snap.observed_at > now + timedelta(seconds=60) or now - snap.observed_at > timedelta(
        minutes=15
    ):
        report.checks = [Check(code="snapshot_expired_or_future")]
        return report
    missing, blockers = quota_checks(scenario)
    if not snap.constraints_reviewed:
        missing.append(Check(code="admission_and_placement_not_reviewed"))
    if scenario.tolerate_lost_nodes and not snap.failure_load_accounted:
        missing.append(Check(code="incumbent_failover_load_unknown"))
    if not snap.inventory_complete:
        missing.append(Check(code="inventory_incomplete"))
    # The quotas are tied to the exact effective specification reviewed by the operator.
    if missing:
        report.checks = missing + blockers
        return report
    if blockers:
        report.status = "infeasible"
        report.checks = blockers
        return report

    request = scenario.additional_replicas
    lost = scenario.tolerate_lost_nodes
    report.nodes = [
        node_capacity(
            n.name, n.eligible, n.allocatable, n.occupied, scenario.pod, scenario.reserve_percent
        )
        for n in sorted(snap.nodes, key=lambda n: n.name)
    ]
    locations = [(node.name, node.replica_slots) for node in report.nodes if node.replica_slots]
    existing = [slots for _, slots in locations]
    report.current_slots = sum(existing)
    report.current_slots_after_node_loss = surviving_slots(existing, 0, 0, lost)
    if report.current_slots_after_node_loss >= request:
        report.status = "feasible_now"
        report.placement = place(locations, request)
        return report
    report.checks.append(
        Check(
            code="current_capacity_shortfall",
            required=request,
            available=report.current_slots_after_node_loss,
            unit="pods",
        )
    )

    # The optimistic bound deliberately ignores shared cloud constraints and loss reserve.
    # It proves impossibility only when even the relaxed total cannot cover demand.
    optimistic_slots = report.current_slots
    unknown = not snap.pools_complete
    for pool in sorted(snap.pools, key=lambda p: p.name):
        slots = node_capacity(
            pool.name,
            pool.eligible,
            pool.allocatable,
            pool.daemon_requests,
            scenario.pod,
            scenario.reserve_percent,
        ).replica_slots
        if not slots or not pool.scale_limit_remaining or pool.provider_nodes_available == 0:
            report.checks.append(Check(code="pool_unavailable_or_pod_does_not_fit", pool=pool.name))
            continue
        ready = pool.ready_within_seconds
        if ready is not None and ready > scenario.capacity_deadline_seconds:
            report.checks.append(
                Check(
                    code="pool_misses_deadline",
                    pool=pool.name,
                    required=ready,
                    available=scenario.capacity_deadline_seconds,
                    unit="seconds",
                )
            )
            continue
        if pool.provider_nodes_available is None or ready is None:
            unknown = True
            optimistic_slots += slots * pool.scale_limit_remaining
            report.checks.append(Check(code="pool_supply_or_startup_unknown", pool=pool.name))
            continue
        limit = min(pool.scale_limit_remaining, pool.provider_nodes_available)
        optimistic_slots += slots * limit
        capacity = surviving_slots(existing, slots, limit, lost)
        if capacity < request:
            report.checks.append(
                Check(
                    code="pool_node_limit",
                    pool=pool.name,
                    required=request,
                    available=capacity,
                    unit="pods",
                )
            )
            continue
        low, high = 1, limit
        while low < high:
            middle = (low + high) // 2
            if surviving_slots(existing, slots, middle, lost) >= request:
                high = middle
            else:
                low = middle + 1
        report.scale_options.append(
            ScaleOption(
                pool=pool.name,
                new_nodes=low,
                slots_per_new_node=slots,
                capacity_after_node_loss=surviving_slots(existing, slots, low, lost),
                ready_within_seconds=ready,
                replicas_on_existing_nodes=min(report.current_slots, request),
                replicas_on_new_nodes=max(0, request - report.current_slots),
            )
        )

    report.scale_options.sort(
        key=lambda option: (option.new_nodes, option.ready_within_seconds, option.pool)
    )
    if report.scale_options:
        report.status = "scale_out_required"
    elif snap.pools_complete and optimistic_slots < request:
        report.status = "infeasible"
        report.checks.append(
            Check(
                code="capacity_upper_bound",
                required=request,
                available=optimistic_slots,
                unit="pods",
            )
        )
    elif unknown:
        report.checks.append(Check(code="scale_out_evidence_incomplete"))
    else:
        report.status = "no_plan_found"
        report.checks.append(Check(code="no_single_pool_plan"))
    return report
