import csv
import hashlib
import io
import json

from pydantic import ValidationError

from cloudpilot.modules.collection.connectors.base import CollectionError
from cloudpilot.modules.collection.normalizers.values import normalize_metric
from cloudpilot.modules.collection.schemas import BillingInput, MetricInput, ResourceInput

MAX_UPLOAD = 2 * 1024 * 1024
MAX_ROWS = 10000
MODELS = {"resources": ResourceInput, "metrics": MetricInput, "billing": BillingInput}


def parse_csv(raw: bytes, kind: str) -> dict:
    if len(raw) > MAX_UPLOAD:
        raise CollectionError("file_too_large", 413)
    if kind not in MODELS:
        raise CollectionError("invalid_csv_kind")
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise CollectionError("csv_requires_utf8") from None
    reader = csv.DictReader(io.StringIO(content), strict=True)
    headers = reader.fieldnames or []
    model = MODELS[kind]
    if not headers or len(headers) != len(set(headers)) or set(headers) - set(model.model_fields):
        raise CollectionError("invalid_csv_headers")
    records, errors, seen = [], [], set()
    row_numbers = []
    read = 0
    try:
        for index, row in enumerate(reader, 2):
            read += 1
            if read > MAX_ROWS:
                raise CollectionError("too_many_csv_rows", 413)
            try:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError("invalid_columns")
                row = {key: value for key, value in row.items() if value != ""}
                if kind == "resources":
                    row["labels"] = json.loads(row.get("labels", "{}"))
                    row["configuration"] = json.loads(row.get("configuration", "{}"))
                    # CSV cannot inject lifecycle evidence used by Prometheus name matching.
                    if row["configuration"]:
                        raise ValueError("csv_configuration_not_supported")
                    if row.get("resource_type", "").startswith("kubernetes_"):
                        row.setdefault("provider", "kubernetes")
                if kind == "metrics":
                    row = normalize_metric(row)
                item = model.model_validate(row).model_dump(mode="json")
                if kind == "billing" and not item["external_record_id"]:
                    item["external_record_id"] = hashlib.sha256(
                        json.dumps(item, sort_keys=True).encode()
                    ).hexdigest()
                if kind == "resources":
                    key = (item["provider"], item["external_id"])
                elif kind == "metrics":
                    key = (item["external_resource_id"], item["metric_name"], item["timestamp"])
                else:
                    key = item["external_record_id"]
                if key in seen:
                    raise ValueError("duplicate_record")
                seen.add(key)
                records.append(item)
                row_numbers.append(index)
            except (ValidationError, ValueError, TypeError, ArithmeticError) as error:
                code = "invalid_row"
                if isinstance(error, ValidationError):
                    code = (
                        "invalid_" + str(error.errors()[0]["loc"][0])
                        if error.errors()[0]["loc"]
                        else "invalid_row"
                    )
                elif isinstance(error, ValueError) and str(error) in {
                    "duplicate_record",
                    "csv_configuration_not_supported",
                    "invalid_columns",
                }:
                    code = str(error)
                errors.append({"row": index, "code": code})
    except csv.Error:
        raise CollectionError("malformed_csv") from None
    if not read:
        raise CollectionError("empty_csv")
    return {
        "row_numbers": row_numbers,
        "kind": "csv",
        "record_type": kind,
        "records": records,
        "errors": errors[:100],
        "records_read": read,
        "records_rejected": read - len(records),
    }
