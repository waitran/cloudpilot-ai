"""Durable collection tables and deduplication constraints."""

from alembic import op

revision = "0002_collection"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

DDL = [
    "CREATE TABLE data_sources (\n\tid UUID NOT NULL, \n\tname VARCHAR(100) NOT NULL, \n\ttype VARCHAR(20) NOT NULL, \n\tscope VARCHAR(100) NOT NULL, \n\tis_synthetic BOOLEAN NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tsettings JSON NOT NULL, \n\tdiscovery_metadata JSON NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tlast_success_at TIMESTAMP WITH TIME ZONE, \n\tlast_error_at TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (id), \n\tUNIQUE (name)\n)",
    "CREATE INDEX ix_data_sources_scope ON data_sources (scope)",
    "CREATE TABLE worker_heartbeats (\n\tname VARCHAR(40) NOT NULL, \n\tlast_seen_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (name)\n)",
    "CREATE TABLE infrastructure_resources (\n\tid UUID NOT NULL, \n\tsource_id UUID NOT NULL, \n\texternal_id VARCHAR(512) NOT NULL, \n\tprovider VARCHAR(30) NOT NULL, \n\taccount_or_cluster_id VARCHAR(100) NOT NULL, \n\tis_synthetic BOOLEAN NOT NULL, \n\tresource_type VARCHAR(40) NOT NULL, \n\tname VARCHAR(256) NOT NULL, \n\tnamespace VARCHAR(256), \n\tregion VARCHAR(100), \n\tavailability_zone VARCHAR(100), \n\tstatus VARCHAR(40) NOT NULL, \n\tcpu_capacity NUMERIC(24, 9), \n\tmemory_capacity_bytes NUMERIC(24, 0), \n\tcpu_requests NUMERIC(24, 9), \n\tmemory_requests_bytes NUMERIC(24, 0), \n\tcpu_limits NUMERIC(24, 9), \n\tmemory_limits_bytes NUMERIC(24, 0), \n\tcpu_allocatable NUMERIC(24, 9), \n\tmemory_allocatable_bytes NUMERIC(24, 0), \n\tlabels JSON NOT NULL, \n\tconfiguration JSON NOT NULL, \n\tdiscovered_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tlast_seen_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (provider, account_or_cluster_id, external_id, is_synthetic), \n\tFOREIGN KEY(source_id) REFERENCES data_sources (id)\n)",
    "CREATE INDEX ix_infrastructure_resources_name ON infrastructure_resources (name)",
    "CREATE INDEX ix_infrastructure_resources_source_id ON infrastructure_resources (source_id)",
    "CREATE INDEX ix_resources_scope_type ON infrastructure_resources (account_or_cluster_id, resource_type)",
    "CREATE TABLE ingestion_runs (\n\tid UUID NOT NULL, \n\tsource_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tstarted_at TIMESTAMP WITH TIME ZONE, \n\tfinished_at TIMESTAMP WITH TIME ZONE, \n\tstatus VARCHAR(20) NOT NULL, \n\trecords_read INTEGER NOT NULL, \n\trecords_created INTEGER NOT NULL, \n\trecords_updated INTEGER NOT NULL, \n\trecords_rejected INTEGER NOT NULL, \n\terror_summary JSON NOT NULL, \n\tpayload JSON NOT NULL, \n\tattempts INTEGER NOT NULL, \n\tlease_until TIMESTAMP WITH TIME ZONE, \n\tlease_owner UUID, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(source_id) REFERENCES data_sources (id)\n)",
    "CREATE INDEX ix_ingestion_runs_source_id ON ingestion_runs (source_id)",
    "CREATE UNIQUE INDEX ix_runs_active_source ON ingestion_runs (source_id) WHERE status IN ('pending', 'running')",
    "CREATE INDEX ix_runs_claim ON ingestion_runs (status, lease_until, created_at)",
    "CREATE TABLE billing_records (\n\tid UUID NOT NULL, \n\tsource_id UUID NOT NULL, \n\tresource_id UUID, \n\texternal_record_id VARCHAR(128) NOT NULL, \n\texternal_resource_id VARCHAR(512) NOT NULL, \n\tservice VARCHAR(100) NOT NULL, \n\tperiod_start TIMESTAMP WITH TIME ZONE NOT NULL, \n\tperiod_end TIMESTAMP WITH TIME ZONE NOT NULL, \n\tamount NUMERIC(24, 9) NOT NULL, \n\tcurrency VARCHAR(3) NOT NULL, \n\tcost_type VARCHAR(20) NOT NULL, \n\timported_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (source_id, external_record_id), \n\tFOREIGN KEY(source_id) REFERENCES data_sources (id), \n\tFOREIGN KEY(resource_id) REFERENCES infrastructure_resources (id)\n)",
    "CREATE INDEX ix_billing_records_source_id ON billing_records (source_id)",
    "CREATE INDEX ix_billing_resource_period ON billing_records (resource_id, period_start)",
    "CREATE TABLE resource_metrics (\n\tid UUID NOT NULL, \n\tresource_id UUID NOT NULL, \n\tsource_id UUID NOT NULL, \n\tmetric_name VARCHAR(80) NOT NULL, \n\tvalue NUMERIC(30, 9) NOT NULL, \n\tunit VARCHAR(20) NOT NULL, \n\ttimestamp TIMESTAMP WITH TIME ZONE NOT NULL, \n\tcollected_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tquality_status VARCHAR(20) NOT NULL, \n\texpected_interval_seconds INTEGER NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (resource_id, source_id, metric_name, timestamp), \n\tFOREIGN KEY(resource_id) REFERENCES infrastructure_resources (id), \n\tFOREIGN KEY(source_id) REFERENCES data_sources (id)\n)",
    "CREATE INDEX ix_metrics_resource_time ON resource_metrics (resource_id, timestamp)",
    "CREATE INDEX ix_resource_metrics_source_id ON resource_metrics (source_id)",
]


def upgrade():
    for statement in DDL:
        op.execute(statement)


def downgrade():
    op.drop_table("resource_metrics")
    op.drop_table("billing_records")
    op.drop_table("ingestion_runs")
    op.drop_table("infrastructure_resources")
    op.drop_table("worker_heartbeats")
    op.drop_table("data_sources")
