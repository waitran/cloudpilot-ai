from fastapi import APIRouter

from cloudpilot.modules.collection.models import now
from cloudpilot.modules.feasibility.engine import evaluate
from cloudpilot.modules.feasibility.schemas import Report, Scenario
from cloudpilot.schemas.system import ErrorResponse

router = APIRouter(
    prefix="/api/v1/feasibility",
    tags=["Feasibility"],
    responses={422: {"model": ErrorResponse}},
)


@router.post("/evaluate", response_model=Report)
def evaluate_scenario(body: Scenario) -> Report:
    """Evaluate peak placement of identical additional pods against an operator snapshot."""
    return evaluate(body, now())
