from dataclasses import dataclass, field
from typing import Protocol

from cloudpilot.modules.collection.schemas import ResourceInput, SyncRequest


class CollectionError(Exception):
    def __init__(self, code: str, status: int = 422):
        self.code = code
        self.status = status
        super().__init__(code)


@dataclass
class Batch:
    csv_row_numbers: list[int] = field(default_factory=list)
    resources: list[ResourceInput] = field(default_factory=list)
    metrics: list[dict] = field(default_factory=list)
    billing: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    records_read: int = 0
    records_rejected: int = 0
    discovery_metadata: dict = field(default_factory=dict)


class Connector(Protocol):
    async def collect(self, window: SyncRequest) -> Batch: ...
