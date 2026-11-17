from cloudpilot.db.database import Database
from cloudpilot.schemas.system import ComponentStatus


def component_statuses(database: Database) -> dict[str, ComponentStatus]:
    return {
        "backend": ComponentStatus(status="available"),
        "postgresql": ComponentStatus(
            status="available" if database.reachable() else "unavailable"
        ),
        "collector": ComponentStatus(status="planned"),
        "optimizer": ComponentStatus(status="planned"),
        "optimization_lab": ComponentStatus(status="planned"),
        "ai_agent": ComponentStatus(status="planned"),
    }
