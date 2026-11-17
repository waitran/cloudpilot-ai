from fastapi import APIRouter, Request, Response

from cloudpilot.schemas.system import ComponentStatus, Liveness, Readiness, SystemInfo
from cloudpilot.services.system import component_statuses

router = APIRouter(prefix="/api/v1", tags=["System"])


@router.get("/health/live", response_model=Liveness)
def live() -> Liveness:
    return Liveness()


@router.get("/health/ready", response_model=Readiness, responses={503: {"model": Readiness}})
def ready(request: Request, response: Response) -> Readiness:
    reachable = request.app.state.database.reachable()
    if not reachable:
        response.status_code = 503
    return Readiness(
        status="ready" if reachable else "not_ready",
        components={
            "postgresql": ComponentStatus(status="available" if reachable else "unavailable")
        },
    )


@router.get("/system/info", response_model=SystemInfo)
def info(request: Request) -> SystemInfo:
    settings = request.app.state.settings
    return SystemInfo(
        name=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        components=component_statuses(request.app.state.database),
    )
