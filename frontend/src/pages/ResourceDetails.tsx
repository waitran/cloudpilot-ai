import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import { Badge, DataState, Pagination } from '../components/Collection';
import {
  bytes,
  collectionApi,
  date,
  decimal,
  params,
  type Bill,
  type Metric,
  type Page,
  type Resource,
} from '../lib/collection';

function MetricPlot({ points, unit }: { points: Metric[]; unit: string }) {
  if (!points.length)
    return <p className="data-notice">No samples in this window. Missing data is not zero.</p>;
  const times = points.map((p) => new Date(p.timestamp).getTime());
  const min = Math.min(...times),
    max = Math.max(...times);
  const ceiling = Math.max(...points.map((p) => Number(p.value)), 0.001);
  return (
    <figure className="metric-plot">
      <svg
        viewBox="0 0 640 180"
        role="img"
        aria-label={`Measured ${unit} samples; gaps are not interpolated`}
      >
        <line x1="35" y1="155" x2="625" y2="155" stroke="currentColor" opacity="0.2" />
        <text x="5" y="20" fill="currentColor" fontSize="11">
          {Number(ceiling.toPrecision(3))}
        </text>
        <text x="10" y="155" fill="currentColor" fontSize="11">
          0
        </text>
        {points.map((p) => (
          <circle
            key={p.id}
            cx={40 + ((new Date(p.timestamp).getTime() - min) / Math.max(1, max - min)) * 575}
            cy={150 - (Number(p.value) / ceiling) * 125}
            r="3"
            fill="#49c9b0"
          >
            <title>
              {date(p.timestamp)} · {p.value} {p.unit}
            </title>
          </circle>
        ))}
      </svg>
      <figcaption>
        <span>{date(new Date(min).toISOString())}</span>
        <span>{unit} · individual samples</span>
        <span>{date(new Date(max).toISOString())}</span>
      </figcaption>
    </figure>
  );
}

export function ResourceDetails() {
  const { id } = useParams();
  const [hours, setHours] = useState('24');
  const [windowEnd, setWindowEnd] = useState(() => new Date().toISOString());
  const [metric, setMetric] = useState('cpu_usage_cores');
  const [metricOffset, setMetricOffset] = useState(0);
  const [billOffset, setBillOffset] = useState(0);
  const resource = useQuery({
    queryKey: ['collection', 'resource', id],
    queryFn: ({ signal }) => collectionApi<Resource>(`/resources/${id}`, { signal }),
    refetchInterval: 10000,
  });
  const metrics = useQuery({
    queryKey: ['collection', 'metrics', id, hours, metric, metricOffset, windowEnd],
    queryFn: ({ signal }) => {
      const end = new Date(windowEnd);
      return collectionApi<Page<Metric>>(
        `/resources/${id}/metrics?${params({ start: new Date(end.getTime() - Number(hours) * 3600000).toISOString(), end: end.toISOString(), metric_name: metric, limit: 200, offset: metricOffset })}`,
        { signal },
      );
    },
  });
  const billing = useQuery({
    queryKey: ['collection', 'resource-billing', id, billOffset],
    queryFn: ({ signal }) =>
      collectionApi<Page<Bill>>(`/resources/${id}/billing?limit=20&offset=${billOffset}`, {
        signal,
      }),
  });
  const r = resource.data;
  return (
    <>
      <Link className="text-link back-link" to="/resources">
        ← All resources
      </Link>
      <DataState
        pending={resource.isPending}
        error={resource.error}
        retry={() => void resource.refetch()}
      >
        {r && (
          <>
            <div className="page-heading">
              <div>
                <div className="eyebrow">{r.resource_type.replaceAll('_', ' ').toUpperCase()}</div>
                <h1>{r.name}</h1>
                <p>
                  {r.account_or_cluster_id}
                  {r.namespace ? ` / ${r.namespace}` : ''} · {r.provider}
                </p>
              </div>
              <div>
                <Badge value={r.quality.status} />
                {r.is_synthetic && <Badge value="synthetic" />}
              </div>
            </div>
            <section className="collection-banner">
              <div>
                <strong>
                  {r.quality.optimization_ready
                    ? 'Data meets the history checks'
                    : 'Data is not ready for optimization'}
                </strong>
                <p>
                  {r.quality.reasons.length
                    ? r.quality.reasons.map((s) => s.replaceAll('_', ' ')).join(' · ')
                    : 'CPU and memory history is fresh and complete.'}
                </p>
                <small>
                  History: {(r.quality.history_seconds / 86400).toFixed(2)} days · Gaps:{' '}
                  {r.quality.gap_count} · Latest: {date(r.quality.latest_at)}
                </small>
              </div>
            </section>
            <div className="collection-grid">
              <section className="panel collection-panel">
                <h2>Resource configuration</h2>
                <dl className="resource-facts">
                  {[
                    ['Identity', r.external_id],
                    ['Status', r.status],
                    ['CPU capacity', decimal(r.cpu_capacity, 'cores')],
                    ['CPU allocatable', decimal(r.cpu_allocatable, 'cores')],
                    ['CPU requests', decimal(r.cpu_requests, 'cores')],
                    ['CPU limits', decimal(r.cpu_limits, 'cores')],
                    ['Memory capacity', bytes(r.memory_capacity_bytes)],
                    ['Memory allocatable', bytes(r.memory_allocatable_bytes)],
                    ['Memory requests', bytes(r.memory_requests_bytes)],
                    ['Memory limits', bytes(r.memory_limits_bytes)],
                    ['Request scope', String(r.configuration.request_scope || 'resource')],
                    [
                      'Region / zone',
                      [r.region, r.availability_zone].filter(Boolean).join(' / ') || 'Unavailable',
                    ],
                    ['First discovered', date(r.discovered_at)],
                    ['Last seen', date(r.last_seen_at)],
                  ].map(([label, value]) => (
                    <div key={label}>
                      <dt>{label}</dt>
                      <dd>{value}</dd>
                    </div>
                  ))}
                </dl>
              </section>
              <section className="panel collection-panel">
                <h2>Latest observations</h2>
                {Object.keys(r.latest_metrics).length ? (
                  Object.entries(r.latest_metrics).map(([name, sample]) => (
                    <div className="observation" key={name}>
                      <span>{name.replaceAll('_', ' ')}</span>
                      <strong>{decimal(sample.value, sample.unit)}</strong>
                      <small>{date(sample.timestamp)}</small>
                    </div>
                  ))
                ) : (
                  <p className="data-notice">No metrics collected for this identity.</p>
                )}
                <h3>Labels</h3>
                <div className="resource-labels">
                  {Object.entries(r.labels).length ? (
                    Object.entries(r.labels).map(([k, v]) => (
                      <code key={k}>
                        {k}={v}
                      </code>
                    ))
                  ) : (
                    <span className="muted">No labels</span>
                  )}
                </div>
                <details>
                  <summary>Discovery metadata</summary>
                  <pre className="resource-json">{JSON.stringify(r.configuration, null, 2)}</pre>
                </details>
              </section>
            </div>
            <section className="panel collection-panel">
              <div className="panel-heading">
                <h2>Measured utilization</h2>
                <div className="form-row data-form">
                  <label>
                    Metric
                    <select
                      value={metric}
                      onChange={(e) => {
                        setMetric(e.target.value);
                        setMetricOffset(0);
                      }}
                    >
                      <option value="cpu_usage_cores">CPU · cores</option>
                      <option value="memory_usage_bytes">Memory · bytes</option>
                    </select>
                  </label>
                  <label>
                    Window
                    <select
                      value={hours}
                      onChange={(e) => {
                        setHours(e.target.value);
                        setWindowEnd(new Date().toISOString());
                        setMetricOffset(0);
                      }}
                    >
                      <option value="1">Last hour</option>
                      <option value="24">Last 24 hours</option>
                      <option value="168">Last 7 days</option>
                    </select>
                  </label>
                </div>
              </div>
              <DataState
                pending={metrics.isPending}
                error={metrics.error}
                retry={() => void metrics.refetch()}
              >
                <MetricPlot
                  points={metrics.data?.items || []}
                  unit={metric === 'cpu_usage_cores' ? 'cores' : 'bytes'}
                />
                <p className="muted">
                  Plot shows this page of samples, newest first. Each dot is one stored measurement;
                  gaps are preserved.
                </p>
                <Pagination
                  total={metrics.data?.total || 0}
                  offset={metricOffset}
                  limit={200}
                  onChange={setMetricOffset}
                />
              </DataState>
            </section>
            <section className="panel collection-panel">
              <div className="panel-heading">
                <h2>Linked billing</h2>
                <span className="muted">All periods · exact imported amounts</span>
              </div>
              <DataState
                pending={billing.isPending}
                error={billing.error}
                retry={() => void billing.refetch()}
              >
                {billing.data?.items.length ? (
                  <>
                    <div className="table-scroll">
                      <table className="data-table">
                        <thead>
                          <tr>
                            <th>Service</th>
                            <th>Period</th>
                            <th>Amount</th>
                            <th>Cost type</th>
                          </tr>
                        </thead>
                        <tbody>
                          {billing.data.items.map((b) => (
                            <tr key={b.id}>
                              <td>{b.service}</td>
                              <td>
                                {date(b.period_start)} – {date(b.period_end)}
                              </td>
                              <td>
                                {b.amount} {b.currency}
                              </td>
                              <td>
                                <Badge value={b.cost_type} />
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <Pagination
                      total={billing.data.total}
                      offset={billOffset}
                      limit={20}
                      onChange={setBillOffset}
                    />
                  </>
                ) : (
                  <p className="data-notice">
                    No billing linked. Unmatched records remain in the source report.
                  </p>
                )}
              </DataState>
            </section>
          </>
        )}
      </DataState>
    </>
  );
}
