import { useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Database, Upload, RefreshCw } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Badge, DataState } from '../components/Collection';
import {
  collectionApi,
  date,
  post,
  type BillingGroup,
  type Page,
  type Run,
  type Source,
} from '../lib/collection';
import { useSystemInfo } from '../lib/queries';

export function Sources() {
  const cache = useQueryClient();
  const [selected, setSelected] = useState('');
  const [kind, setKind] = useState('resources');
  const [file, setFile] = useState<File | null>(null);
  const [uploadError, setUploadError] = useState('');
  const [hours, setHours] = useState('1');
  const [lastRun, setLastRun] = useState('');
  const info = useSystemInfo();
  const sources = useQuery({
    queryKey: ['collection', 'sources'],
    queryFn: ({ signal }) => collectionApi<Page<Source>>('/sources?limit=200', { signal }),
    refetchInterval: 5000,
  });
  const runs = useQuery({
    queryKey: ['collection', 'runs'],
    queryFn: ({ signal }) => collectionApi<Page<Run>>('/ingestion-runs?limit=20', { signal }),
    refetchInterval: 2000,
  });
  const billing = useQuery({
    queryKey: ['collection', 'billing'],
    queryFn: ({ signal }) => collectionApi<BillingGroup[]>('/billing/summary', { signal }),
    refetchInterval: 10000,
  });
  const source = sources.data?.items.find((s) => s.id === selected);
  function refresh() {
    void cache.invalidateQueries({ queryKey: ['collection'] });
  }
  const create = useMutation({
    mutationFn: (body: unknown) => collectionApi<Source>('/sources', post(body)),
    onSuccess: (value) => {
      setSelected(value.id);
      refresh();
    },
  });
  const sync = useMutation({
    mutationFn: () => {
      const end = new Date();
      return collectionApi<Run>(
        `/sources/${selected}/sync`,
        post({
          start: new Date(end.getTime() - Number(hours) * 3600000).toISOString(),
          end: end.toISOString(),
          step: Number(hours) > 24 ? 120 : 60,
        }),
      );
    },
    onSuccess: (value) => {
      setLastRun(value.id);
      refresh();
    },
  });
  const upload = useMutation({
    mutationFn: () => {
      const body = new FormData();
      body.set('source_id', selected);
      body.set('kind', kind);
      body.set('file', file!);
      return collectionApi<Run>('/imports/csv', { method: 'POST', body });
    },
    onSuccess: (value) => {
      setLastRun(value.id);
      refresh();
    },
  });
  function createSource(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    create.mutate({
      name: form.get('name'),
      type: form.get('type'),
      scope: form.get('scope'),
      is_synthetic: form.get('synthetic') === 'on',
    });
  }
  function importFile(event: FormEvent) {
    event.preventDefault();
    setUploadError('');
    if (!file || file.size > 2 * 1024 * 1024) {
      setUploadError('Choose a CSV file up to 2 MiB.');
      return;
    }
    upload.mutate();
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">DATA COLLECTION</div>
          <h1>Sources & imports</h1>
          <p>Bring infrastructure, utilization and billing into one workspace.</p>
        </div>
        <Link className="secondary-button" to="/resources">
          View resources
        </Link>
      </div>
      <div className="collection-banner">
        <Database size={20} />
        <div>
          <strong>Read-only discovery</strong>
          <p>Connections use server configuration. Nothing changes in your infrastructure.</p>
        </div>
        <Badge value={info.data?.components.collector?.status || 'unavailable'} />
        <span className="muted">Worker</span>
      </div>
      <div className="collection-grid">
        <section className="panel collection-panel">
          <div className="panel-heading">
            <h2>Register a source</h2>
          </div>
          <form className="data-form" onSubmit={createSource}>
            <label>
              Source name
              <input name="name" required maxLength={100} placeholder="Production inventory" />
            </label>
            <div className="form-row">
              <label>
                Connector
                <select name="type">
                  <option value="csv">CSV import</option>
                  <option value="kubernetes">Kubernetes</option>
                  <option value="prometheus">Prometheus</option>
                </select>
              </label>
              <label>
                Scope
                <input
                  name="scope"
                  required
                  maxLength={100}
                  pattern="[\w.-]+"
                  placeholder="cluster-prod"
                />
              </label>
            </div>
            <p className="muted">
              Use the same scope for matching inventory, metrics and billing. Each connector uses
              the endpoint configured on the server.
            </p>
            <label className="check-label">
              <input name="synthetic" type="checkbox" />
              Synthetic / demo data
            </label>
            <button className="primary-button" disabled={create.isPending}>
              {create.isPending ? 'Registering…' : 'Register source'}
            </button>
            {create.error && <p role="alert">{create.error.message}</p>}
          </form>
        </section>
        <section className="panel collection-panel">
          <div className="panel-heading">
            <h2>Collect data</h2>
            <Upload size={18} />
          </div>
          <div className="data-form">
            <label>
              Source
              <select
                value={selected}
                onChange={(e) => {
                  setSelected(e.target.value);
                  sync.reset();
                  upload.reset();
                  setLastRun('');
                }}
              >
                <option value="">Select a source</option>
                {sources.data?.items.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} · {s.scope}
                    {s.is_synthetic ? ' · synthetic' : ''}
                  </option>
                ))}
              </select>
            </label>
            {source?.type === 'csv' && (
              <form className="data-form" onSubmit={importFile}>
                <label>
                  Record type
                  <select value={kind} onChange={(e) => setKind(e.target.value)}>
                    <option value="resources">Resources</option>
                    <option value="metrics">Metrics</option>
                    <option value="billing">Billing</option>
                  </select>
                </label>
                <label>
                  CSV file · UTF-8 · up to 2 MiB
                  <input
                    type="file"
                    accept=".csv,text/csv"
                    required
                    onChange={(e) => {
                      setFile(e.target.files?.[0] || null);
                      setUploadError('');
                    }}
                  />
                </label>
                <p className="muted">
                  Templates and column definitions are in docs/development/collection.md. Uploads
                  run in the durable queue; invalid rows appear in the report below.
                </p>
                <button className="primary-button" disabled={upload.isPending}>
                  {upload.isPending ? 'Uploading…' : 'Queue CSV import'}
                </button>
              </form>
            )}
            {source && source.type !== 'csv' && (
              <>
                <label>
                  History window
                  <select value={hours} onChange={(e) => setHours(e.target.value)}>
                    <option value="1">Last hour</option>
                    <option value="24">Last 24 hours</option>
                    <option value="168">Last 7 days</option>
                  </select>
                </label>
                <p className="muted">
                  Kubernetes collects the current inventory. Prometheus queries CPU and memory
                  history from the configured cAdvisor profile.
                </p>
                <button
                  className="primary-button"
                  disabled={sync.isPending}
                  onClick={() => sync.mutate()}
                >
                  <RefreshCw size={16} />
                  Queue sync
                </button>
              </>
            )}
            {!source && (
              <p className="muted">Register a source, then select it here to collect data.</p>
            )}
            {(uploadError || upload.error || sync.error) && (
              <p role="alert">{uploadError || upload.error?.message || sync.error?.message}</p>
            )}
            {lastRun && (
              <p role="status">
                Queued job <code>{lastRun.slice(0, 8)}</code>. Progress appears below.
              </p>
            )}
          </div>
        </section>
      </div>
      <section className="panel collection-panel">
        <div className="panel-heading">
          <h2>Source registry</h2>
          <span className="muted">{sources.data?.total ?? '—'} sources</span>
        </div>
        <DataState
          pending={sources.isPending}
          error={sources.error}
          retry={() => void sources.refetch()}
        >
          {sources.data?.items.length === 0 ? (
            <p className="data-notice">No sources yet. Register your first connection above.</p>
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Name / scope</th>
                    <th>Connector</th>
                    <th>Last run</th>
                    <th>Last full success</th>
                    <th>Data</th>
                  </tr>
                </thead>
                <tbody>
                  {sources.data?.items.map((s) => (
                    <tr key={s.id}>
                      <td>
                        <button className="text-link" onClick={() => setSelected(s.id)}>
                          {s.name}
                        </button>
                        <small>{s.scope}</small>
                      </td>
                      <td>{s.type}</td>
                      <td>
                        <Badge value={s.status} />
                      </td>
                      <td>{date(s.last_success_at)}</td>
                      <td>
                        {s.is_synthetic ? <Badge value="synthetic" /> : 'Observed / imported'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </DataState>
      </section>
      <section className="panel collection-panel">
        <div className="panel-heading">
          <h2>Ingestion history</h2>
          <span className="muted">Latest 20 · refreshes every 2s</span>
        </div>
        <DataState pending={runs.isPending} error={runs.error} retry={() => void runs.refetch()}>
          {!runs.data?.items.length ? (
            <p className="data-notice">No collection runs yet.</p>
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Run / source</th>
                    <th>Status</th>
                    <th>Read</th>
                    <th>Created</th>
                    <th>Updated</th>
                    <th>Rejected</th>
                    <th>Report</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.data.items.map((r) => (
                    <tr key={r.id}>
                      <td>
                        <code>{r.id.slice(0, 8)}</code>
                        <small>
                          {sources.data?.items.find((s) => s.id === r.source_id)?.name ||
                            r.source_id.slice(0, 8)}
                        </small>
                        <small>{date(r.created_at)}</small>
                      </td>
                      <td>
                        <Badge value={r.status} />
                      </td>
                      <td>{r.records_read}</td>
                      <td>{r.records_created}</td>
                      <td>{r.records_updated}</td>
                      <td>{r.records_rejected}</td>
                      <td>
                        {r.error_summary.length ? (
                          <details>
                            <summary>{r.error_summary.length} reported issues</summary>
                            <ul>
                              {r.error_summary.map((e, i) => (
                                <li key={i}>
                                  {e.row ? `Row ${e.row}: ` : ''}
                                  {e.code.replaceAll('_', ' ')}
                                  {e.metric ? ` · ${e.metric}` : ''}
                                </li>
                              ))}
                            </ul>
                          </details>
                        ) : (
                          <span className="muted">
                            {['pending', 'running'].includes(r.status)
                              ? 'Waiting for worker'
                              : 'No row errors'}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </DataState>
      </section>
      <section className="panel collection-panel">
        <div className="panel-heading">
          <h2>Billing coverage</h2>
          <span className="muted">All imported periods</span>
        </div>
        <DataState
          pending={billing.isPending}
          error={billing.error}
          retry={() => void billing.refetch()}
        >
          {!billing.data?.length ? (
            <p className="data-notice">No billing imported. Missing costs remain unavailable.</p>
          ) : (
            <div className="billing-cards">
              {billing.data.map((g) => (
                <article key={`${g.currency}-${g.cost_type}-${g.is_synthetic}`}>
                  <span>
                    {g.cost_type} · {g.is_synthetic ? 'synthetic' : 'imported'}
                  </span>
                  <strong>
                    {g.amount} {g.currency}
                  </strong>
                  <small>
                    {g.records} records · {g.unmatched_records} unmatched
                  </small>
                </article>
              ))}
            </div>
          )}
        </DataState>
        <p className="muted">
          Currencies and cost types are kept separate. Unmatched records are retained and linked
          when a unique resource appears.
        </p>
      </section>
    </>
  );
}
