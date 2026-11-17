import { useState, type FormEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Box, Search } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Badge, DataState, Pagination } from '../components/Collection';
import {
  bytes,
  collectionApi,
  date,
  decimal,
  params,
  type Page,
  type QualitySummary,
  type Resource,
  type Source,
} from '../lib/collection';

export function Resources() {
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [offset, setOffset] = useState(0);
  const query = useQuery({
    queryKey: ['collection', 'resources', filters, offset],
    queryFn: ({ signal }) =>
      collectionApi<Page<Resource>>(`/resources?${params({ ...filters, limit: 20, offset })}`, {
        signal,
      }),
    refetchInterval: 10000,
  });
  const sources = useQuery({
    queryKey: ['collection', 'sources'],
    queryFn: ({ signal }) => collectionApi<Page<Source>>('/sources?limit=200', { signal }),
  });
  const quality = useQuery({
    queryKey: ['collection', 'quality'],
    queryFn: ({ signal }) => collectionApi<QualitySummary>('/data-quality/summary', { signal }),
    refetchInterval: 10000,
  });
  function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setFilters(Object.fromEntries([...data.entries()].map(([k, v]) => [k, String(v)])));
    setOffset(0);
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">OBSERVE BEFORE YOU OPTIMIZE</div>
          <h1>Resources</h1>
          <p>Inventory, measured utilization and data quality.</p>
        </div>
        <Link className="primary-button" to="/sources">
          Manage sources
        </Link>
      </div>
      <div className="collection-stats">
        <article>
          <span>Discovered resources</span>
          <strong>{quality.data?.total_resources ?? '—'}</strong>
        </article>
        <article>
          <span>Healthy data</span>
          <strong>{quality.data?.states.healthy ?? '—'}</strong>
        </article>
        <article>
          <span>Ready for future analysis</span>
          <strong>{quality.data?.optimization_ready ?? '—'}</strong>
        </article>
        <article>
          <span>Sources without a full success</span>
          <strong>{quality.data?.sources_without_success ?? '—'}</strong>
        </article>
      </div>
      {quality.error && (
        <p role="alert">Data quality summary unavailable: {quality.error.message}</p>
      )}
      <section className="panel collection-panel">
        <div className="panel-heading">
          <h2>
            <Box size={18} /> Resource inventory
          </h2>
          <span className="subtle-pill">READ ONLY</span>
        </div>
        <form className="resource-filters data-form" onSubmit={search}>
          <label className="search-field">
            Resource name
            <input name="q" maxLength={100} placeholder="Search by name…" />
          </label>
          <label>
            Type
            <select name="resource_type">
              <option value="">All types</option>
              {[
                'virtual_machine',
                'kubernetes_node',
                'kubernetes_pod',
                'kubernetes_deployment',
                'kubernetes_statefulset',
              ].map((t) => (
                <option key={t} value={t}>
                  {t.replaceAll('_', ' ')}
                </option>
              ))}
            </select>
          </label>
          <label>
            Source
            <select name="source_id">
              <option value="">All sources</option>
              {sources.data?.items.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Namespace
            <input name="namespace" placeholder="All namespaces" maxLength={256} />
          </label>
          <label>
            Data
            <select name="is_synthetic">
              <option value="">All data</option>
              <option value="false">Observed / imported</option>
              <option value="true">Synthetic only</option>
            </select>
          </label>
          <label>
            Sort
            <select name="sort">
              <option value="name">Name</option>
              <option value="last_seen">Last seen</option>
            </select>
          </label>
          <button className="secondary-button">
            <Search size={16} />
            Apply
          </button>
        </form>
        <DataState pending={query.isPending} error={query.error} retry={() => void query.refetch()}>
          {query.data?.items.length ? (
            <>
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Resource / identity</th>
                      <th>Type / scope</th>
                      <th>CPU / memory usage</th>
                      <th>Data quality</th>
                      <th>Last discovered</th>
                    </tr>
                  </thead>
                  <tbody>
                    {query.data.items.map((r) => (
                      <tr key={r.id}>
                        <td>
                          <Link className="text-link" to={`/resources/${r.id}`}>
                            {r.name}
                          </Link>
                          <small title={r.external_id}>
                            {r.external_id.length > 26
                              ? `${r.external_id.slice(0, 26)}…`
                              : r.external_id}
                          </small>
                          {r.is_synthetic && <Badge value="synthetic" />}
                        </td>
                        <td>
                          {r.resource_type.replace('kubernetes_', 'k8s ').replaceAll('_', ' ')}
                          <small>
                            {r.account_or_cluster_id}
                            {r.namespace ? ` / ${r.namespace}` : ''}
                          </small>
                        </td>
                        <td>
                          {decimal(r.latest_metrics.cpu_usage_cores?.value, 'cores')}
                          <small>{bytes(r.latest_metrics.memory_usage_bytes?.value)}</small>
                        </td>
                        <td>
                          <Badge value={r.quality.status} />
                          <small>
                            {r.quality.optimization_ready ? 'History complete' : 'More data needed'}
                          </small>
                        </td>
                        <td>{date(r.last_seen_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pagination
                total={query.data.total}
                offset={offset}
                limit={20}
                onChange={setOffset}
              />
            </>
          ) : (
            <div className="collection-empty">
              <Box size={32} />
              <h3>
                {Object.values(filters).some(Boolean)
                  ? 'No matching resources'
                  : 'Your inventory starts here'}
              </h3>
              <p>
                Connect Kubernetes or upload a resource CSV. Metrics and billing stay unavailable
                until collected.
              </p>
              <Link className="primary-button" to="/sources">
                Open sources & imports
              </Link>
            </div>
          )}
        </DataState>
      </section>
      <p className="muted">
        Data quality uses CPU and memory history, freshness, gaps and source health. No savings or
        resource changes are generated in this stage.
      </p>
    </>
  );
}
