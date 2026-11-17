from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, localcontext

from cloudpilot.modules.optimization.schemas import (
    Candidate,
    CostComparison,
    Evidence,
    Offer,
    Pricing,
    Size,
)

MIB = 1024**2
PROFILES = (("Lean", 15), ("Balanced", 30), ("Conservative", 50))


def target_size(evidence: Evidence, headroom: int, minimum: Size) -> Size:
    factor = Decimal(100 + headroom) / 100
    cpu_quantum = Decimal("0.01")
    memory_quantum = 16 * MIB
    cpu = (evidence.cpu.peak * factor).quantize(cpu_quantum, rounding=ROUND_CEILING)
    memory_chunks = (evidence.memory.peak * factor / memory_quantum).to_integral_value(
        rounding=ROUND_CEILING
    )
    return Size(
        cpu_cores=max(cpu, minimum.cpu_cores),
        memory_bytes=max(int(memory_chunks) * memory_quantum, minimum.memory_bytes),
    )


def compare_cost(pricing: Pricing, offer: Offer) -> CostComparison:
    with localcontext(prec=48):
        baseline = pricing.baseline_hourly_rate * pricing.hours + pricing.baseline_recurring_extra
        recurring = offer.hourly_rate * pricing.hours + offer.recurring_extra
        total = recurring + offer.transition_cost
        savings = baseline - total
        percent = (
            (savings * 100 / baseline).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if baseline
            else None
        )
    return CostComparison(
        baseline_total=baseline,
        candidate_recurring_total=recurring,
        transition_cost=offer.transition_cost,
        candidate_total=total,
        savings=savings,
        savings_percent=percent,
    )


def difference(name: str, baseline: Size, proposed: Size, headroom: int) -> Candidate:
    cpu = baseline.cpu_cores - proposed.cpu_cores
    memory = baseline.memory_bytes - proposed.memory_bytes
    if cpu >= 0 and memory >= 0:
        direction = "downsize" if cpu or memory else "unchanged"
    elif cpu <= 0 and memory <= 0:
        direction = "upsize"
    else:
        direction = "mixed"
    return Candidate(
        name=name,
        proposed=proposed,
        headroom_percent=headroom,
        cpu_released_cores=cpu,
        memory_released_bytes=memory,
        direction=direction,
    )


def propose(
    baseline: Size,
    evidence: Evidence,
    *,
    pod: bool,
    limits: tuple[Decimal | None, Decimal | None] = (None, None),
    pricing: Pricing | None = None,
) -> list[Candidate]:
    minimum = Size(
        cpu_cores=Decimal("0.05") if pod else Decimal(1), memory_bytes=(64 if pod else 512) * MIB
    )
    if pricing is not None:
        required = target_size(evidence, 30, minimum)
        matches = []
        for offer in pricing.offers:
            if offer.cpu_cores < required.cpu_cores or offer.memory_bytes < required.memory_bytes:
                continue
            size = Size(cpu_cores=offer.cpu_cores, memory_bytes=offer.memory_bytes)
            candidate = difference(offer.name, baseline, size, 30)
            candidate.cost = compare_cost(pricing, offer)
            matches.append((candidate.cost.candidate_total, candidate))
        return [
            candidate
            for _, candidate in sorted(matches, key=lambda item: (item[0], item[1].name))[:5]
        ]

    candidates = []
    # Keep the larger reserve when two profiles round to the same configuration.
    seen = {(baseline.cpu_cores, baseline.memory_bytes)}
    cpu_limit, memory_limit = limits
    for name, headroom in reversed(PROFILES):
        size = target_size(evidence, headroom, minimum)
        identity = (size.cpu_cores, size.memory_bytes)
        if identity in seen:
            continue
        if cpu_limit is not None and size.cpu_cores > cpu_limit:
            continue
        if memory_limit is not None and size.memory_bytes > memory_limit:
            continue
        candidates.append(difference(name, baseline, size, headroom))
        seen.add(identity)
    return candidates[::-1]
