from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import text

from cloudpilot.modules.collection.api import DB, get_or_404
from cloudpilot.modules.collection.models import InfrastructureResource, now
from cloudpilot.modules.optimization.schemas import Analysis, AnalysisRequest
from cloudpilot.modules.optimization.service import analyze
from cloudpilot.schemas.system import ErrorResponse

router = APIRouter(
    prefix="/api/v1/optimization",
    tags=["Optimization"],
    responses={code: {"model": ErrorResponse} for code in (404, 422, 503)},
)


@router.post("/resources/{resource_id}/analyze", response_model=Analysis)
def analyze_resource(resource_id: UUID, body: AnalysisRequest, session: DB) -> Analysis:
    """Compare sizing candidates from one consistent, read-only inventory and metrics snapshot."""
    session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
    resource = get_or_404(session, InfrastructureResource, resource_id)
    return analyze(session, resource, body, now())
