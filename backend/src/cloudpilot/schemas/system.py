from typing import Literal

from pydantic import BaseModel


class ComponentStatus(BaseModel):
    status: Literal["available", "unavailable", "planned"]


class Liveness(BaseModel):
    status: Literal["alive"] = "alive"


class Readiness(BaseModel):
    status: Literal["ready", "not_ready"]
    components: dict[str, ComponentStatus]


class SystemInfo(BaseModel):
    name: str
    version: str
    environment: str
    components: dict[str, ComponentStatus]


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
