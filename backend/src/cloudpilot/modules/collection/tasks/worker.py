"""Durable at-least-once queue. Run as a separate process, never an HTTP background task."""

import asyncio
import logging
import signal
import sys
import threading
from datetime import timedelta

from cloudpilot.core.config import Settings
from cloudpilot.core.logging import configure_logging
from cloudpilot.db.database import Database
from cloudpilot.modules.collection.connectors.base import Batch, CollectionError
from cloudpilot.modules.collection.connectors.kubernetes import KubernetesConnector
from cloudpilot.modules.collection.connectors.prometheus import PrometheusConnector
from cloudpilot.modules.collection.models import DataSource, IngestionRun, WorkerHeartbeat, now
from cloudpilot.modules.collection.schemas import SyncRequest
from cloudpilot.modules.collection.services.ingestion import claim, finish, ingest

logger = logging.getLogger("cloudpilot.worker")


def process_one(database: Database, settings: Settings, connector=None) -> bool:
    claimed = claim(database)
    if claimed is None:
        return False
    run_id, owner, source_id, payload = claimed
    error = None
    try:
        if payload["kind"] == "csv":
            batch = Batch(
                records_read=payload["records_read"],
                records_rejected=payload["records_rejected"],
                errors=payload["errors"],
            )
            batch.csv_row_numbers = payload.get("row_numbers", [])
            setattr(batch, payload["record_type"], payload["records"])
        else:
            with database.sessions() as session:
                source = session.get(DataSource, source_id)
                if connector is None:
                    connector = (
                        PrometheusConnector(
                            settings.prometheus_url,
                            settings.prometheus_token.get_secret_value()
                            if settings.prometheus_token
                            else None,
                        )
                        if source.type == "prometheus"
                        else KubernetesConnector(
                            settings.kube_mode, settings.kube_config_file, settings.kube_context
                        )
                    )
            batch = asyncio.run(connector.collect(SyncRequest.model_validate(payload["window"])))
    except CollectionError as exc:
        error = exc.code
    except Exception:
        error = "connector_failed"
    try:
        with database.sessions.begin() as session:
            run = session.get(IngestionRun, run_id, with_for_update=True)
            if run.status != "running" or run.lease_owner != owner:
                return True  # An expired lease was reclaimed. This worker is fenced out.
            source = session.get(DataSource, source_id)
            if error:
                run.status = "failed"
                run.error_summary = [{"code": error}]
                finish(source, run)
            else:
                ingest(session, source, run, batch)
    except Exception:
        # Rollback leaves the leased job recoverable. Do not log DB/API credentials.
        logger.error("ingestion_transaction_failed run_id=%s", run_id)
    return True


def main():
    settings = Settings()
    configure_logging(settings.log_level)
    database = Database(settings)
    if "--check" in sys.argv:
        try:
            with database.sessions() as session:
                heartbeat = session.get(WorkerHeartbeat, "collector")
                healthy = heartbeat and heartbeat.last_seen_at > now() - timedelta(minutes=5)
        except Exception:
            healthy = False
        finally:
            database.close()
        raise SystemExit(0 if healthy else 1)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    try:
        while not stop.is_set():
            try:
                with database.sessions.begin() as session:
                    session.merge(WorkerHeartbeat(name="collector", last_seen_at=now()))
                if not process_one(database, settings):
                    stop.wait(2)
            except Exception:
                logger.error("worker_database_unavailable")
                stop.wait(5)
    finally:
        database.close()


if __name__ == "__main__":
    main()
