from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    Field,
    PlainSerializer,
    StringConstraints,
    field_validator,
    model_validator,
)

from cloudpilot.modules.collection.schemas import Input, utc

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
CPU = Annotated[int, Field(strict=True, ge=0, le=100_000_000)]
RAM = Annotated[int, Field(strict=True, ge=0, le=10**15)]
Count = Annotated[int, Field(strict=True, ge=0, le=100_000)]
Duration = Annotated[int, Field(strict=True, ge=0, le=86_400)]


class Resources(Input):
    cpu_millicores: CPU
    memory_bytes: RAM
    pods: Count


class Node(Input):
    name: Name
    eligible: bool
    allocatable: Resources
    occupied: Resources


class Pod(Input):
    cpu_millicores: Annotated[CPU, Field(gt=0)]
    memory_bytes: Annotated[RAM, Field(gt=0)]
    cpu_limit_millicores: CPU | None = None
    memory_limit_bytes: RAM | None = None

    @model_validator(mode="after")
    def limits_cover_requests(self) -> Self:
        if (
            self.cpu_limit_millicores is not None
            and self.cpu_limit_millicores < self.cpu_millicores
        ):
            raise ValueError("CPU limit is below its request")
        if self.memory_limit_bytes is not None and self.memory_limit_bytes < self.memory_bytes:
            raise ValueError("Memory limit is below its request")
        return self


class Quota(Input):
    # Null fields mean no effective limit after matching applicable quotas for this pod spec.
    pods: Count | None = None
    cpu_millicores: CPU | None = None
    memory_bytes: RAM | None = None
    cpu_limit_millicores: CPU | None = None
    memory_limit_bytes: RAM | None = None


class Pool(Input):
    name: Name
    eligible: bool
    allocatable: Resources
    daemon_requests: Resources
    scale_limit_remaining: Count
    # Effective allowance considering provider quota, stock, and node subnet capacity.
    provider_nodes_available: Count | None = None
    ready_within_seconds: Duration | None = None


class Snapshot(Input):
    context: Name
    namespace: Name
    observed_at: datetime
    synthetic: bool
    # The inventory contains all eligible nodes, with all resident requests/slots counted.
    inventory_complete: bool
    # Admission and supported scheduling assumptions were checked for this exact pod spec.
    constraints_reviewed: bool
    failure_load_accounted: bool = False
    nodes: list[Node] = Field(max_length=500)
    namespace_quota: Quota | None = None
    pod_ips_remaining: Count | None = None
    pools_complete: bool = False
    pools: list[Pool] = Field(default_factory=list, max_length=30)

    @field_validator("observed_at")
    @classmethod
    def timestamp(cls, value: datetime) -> datetime:
        return utc(value)

    @model_validator(mode="after")
    def unique_names(self) -> Self:
        for entries in (self.nodes, self.pools):
            if len({entry.name for entry in entries}) != len(entries):
                raise ValueError("Node and pool names must be unique within each list")
        return self


class Scenario(Input):
    # Additional replicas at peak, while current pods still occupy node and quota capacity.
    additional_replicas: int = Field(strict=True, ge=1, le=10000)
    pod: Pod
    reserve_percent: int = Field(default=15, strict=True, ge=0, le=75)
    tolerate_lost_nodes: int = Field(default=0, strict=True, ge=0, le=3)
    capacity_deadline_seconds: Duration
    snapshot: Snapshot


class Check(BaseModel):
    code: str
    required: Annotated[int, PlainSerializer(str, return_type=str, when_used="json")] | None = None
    available: Annotated[int, PlainSerializer(str, return_type=str, when_used="json")] | None = None
    unit: str | None = None
    pool: str | None = None


class NodeCapacity(BaseModel):
    name: str
    eligible: bool
    free_cpu_millicores: int
    free_memory_bytes: int
    free_pod_slots: int
    replica_slots: int


class Placement(BaseModel):
    node: str
    replicas: int


class ScaleOption(BaseModel):
    pool: str
    new_nodes: int
    slots_per_new_node: int
    capacity_after_node_loss: int
    ready_within_seconds: int
    replicas_on_existing_nodes: int
    replicas_on_new_nodes: int


class Report(BaseModel):
    status: Literal[
        "feasible_now", "scale_out_required", "infeasible", "insufficient_data", "no_plan_found"
    ]
    evaluated_at: datetime
    scenario: Scenario
    current_slots: int | None = None
    current_slots_after_node_loss: int | None = None
    nodes: list[NodeCapacity] = Field(default_factory=list)
    placement: list[Placement] = Field(default_factory=list)
    scale_options: list[ScaleOption] = Field(default_factory=list)
    checks: list[Check] = Field(default_factory=list)
