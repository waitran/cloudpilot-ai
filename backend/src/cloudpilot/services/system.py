from datetime import timedelta

from cloudpilot.db.database import Database
from cloudpilot.modules.collection.models import WorkerHeartbeat, now
from cloudpilot.schemas.system import ComponentStatus


def collector_status(database):
    try:
        with database.sessions() as session:
            heartbeat = session.get(WorkerHeartbeat, "collector")
            return (
                "available"
                if heartbeat and heartbeat.last_seen_at > now() - timedelta(minutes=5)
                else "unavailable"
            )
    except Exception:
        return "unavailable"


def component_statuses(database: Database) -> dict[str, ComponentStatus]:
    postgres_status = "available" if database.reachable() else "unavailable"
    return {
        "backend": ComponentStatus(status="available"),
        "postgresql": ComponentStatus(status=postgres_status),
        "collector": ComponentStatus(status=collector_status(database)),
        "optimizer": ComponentStatus(status=postgres_status),
        "optimization_lab": ComponentStatus(status="planned"),
        "ai_agent": ComponentStatus(status="planned"),
    }
