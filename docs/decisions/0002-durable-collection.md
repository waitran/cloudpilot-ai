# ADR 0002: PostgreSQL queue and server-owned collection profiles

Status: accepted for stage 2.

Collection jobs must survive API restarts. IngestionRun stores the validated payload,
status, counters, lease and fencing owner in the same PostgreSQL database as inventory.
A separate worker claims jobs with SKIP LOCKED. Unique active-source and data-identity
constraints prevent conflicting jobs and duplicate observations. No Redis/Celery service
is needed at this scale. This is an at-least-once queue; database upserts provide idempotency.

Connectors are read only. Source registration never accepts an arbitrary URL, PromQL,
credential or file path. Endpoint and Kubernetes identity are configured by the operator.
The initial Prometheus profile covers cAdvisor pod CPU/memory; inventory UID/scope and
synthetic provenance constrain joins. Billing uses Decimal and preserves unmatched records.

Consequences: one server-owned endpoint profile per connector type per installation,
manually triggered sync, explicit query/response and inventory limits, no automatic retention.
A production service would need authentication, multi-tenant scopes, per-worker health,
retention, scheduled jobs and materialized quality snapshots for large inventories.
These are documented boundaries, not silently simulated features.
