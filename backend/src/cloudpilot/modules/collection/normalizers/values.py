from decimal import ROUND_CEILING, Decimal

from kubernetes.utils.quantity import parse_quantity

from cloudpilot.modules.collection.connectors.base import CollectionError

METRIC_CONVERSIONS = {
    ("cpu_usage_cores", "millicores"): (Decimal("0.001"), "cores"),
    ("memory_usage_bytes", "KiB"): (Decimal(1024), "bytes"),
    ("memory_usage_bytes", "MiB"): (Decimal(1024**2), "bytes"),
    ("memory_usage_bytes", "GiB"): (Decimal(1024**3), "bytes"),
}


def normalize_metric(row: dict) -> dict:
    result = dict(row)
    conversion = METRIC_CONVERSIONS.get((result.get("metric_name"), result.get("unit")))
    if conversion:
        result["value"] = str(Decimal(result["value"]) * conversion[0])
        result["unit"] = conversion[1]
    return result


def quantity(value, memory=False):
    if value is None:
        return None
    result = parse_quantity(str(value))
    if not result.is_finite() or result < 0:
        raise CollectionError("invalid_kubernetes_quantity")
    if memory:
        return result.to_integral_value(rounding=ROUND_CEILING)
    return result
