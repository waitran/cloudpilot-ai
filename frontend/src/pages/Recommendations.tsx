import { useState, type FormEvent } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';
import { Badge, DataState, Pagination } from '../components/Collection';
import {
  bytes,
  collectionApi,
  date,
  decimal,
  params,
  post,
  type Page,
  type Resource,
} from '../lib/collection';

type Size = { cpu_cores: string; memory_bytes: string };
type Stats = { samples: number; p95: string; peak: string; interval_seconds: number };
type Comparison = {
  baseline_total: string;
  candidate_recurring_total: string;
  transition_cost: string;
  candidate_total: string;
  savings: string;
  savings_percent: string | null;
};
type Analysis = {
  resource_name: string;
  is_synthetic: boolean;
  evaluated_at: string;
  status: 'candidates' | 'no_candidates' | 'insufficient_data' | 'unsupported_resource';
  reasons: string[];
  baseline_kind: 'vm_capacity' | 'pod_requests';
  baseline: Size | null;
  evidence: { start: string; end: string; cpu: Stats; memory: Stats } | null;
  pricing: { currency: string; reference: string; hours: number } | null;
  candidates: {
    name: string;
    proposed: Size;
    headroom_percent: number;
    cpu_released_cores: string;
    memory_released_bytes: string;
    direction: 'downsize' | 'upsize' | 'mixed' | 'unchanged';
    cost: Comparison | null;
  }[];
};

const statusText = {
  candidates: 'Candidates available',
  no_candidates: 'No matching candidates',
  insufficient_data: 'Insufficient data',
  unsupported_resource: 'Resource type is outside this analysis',
};

const issue = (code: string) => code.replaceAll('_', ' ').replace(':', ' · ');

function Report({ result }: { result: Analysis }) {
  const { baseline, candidates, evidence, pricing } = result;
  const money = (amount: string) => `${amount} ${pricing?.currency ?? ''}`;
  function download() {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' }),
    );
    const link = document.createElement('a');
    link.href = url;
    link.download = 'cloudpilot-analysis.json';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
  return (
    <section className="panel collection-panel" aria-label="Analysis report">
      <div className="panel-heading">
        <h2>{result.resource_name}</h2>
        <div>
          {result.is_synthetic && <Badge value="synthetic" />}{' '}
          <button type="button" className="secondary-button" onClick={download}>
            Download JSON
          </button>
        </div>
      </div>
      <p role="status">
        {statusText[result.status]} · {date(result.evaluated_at)}
      </p>
      {result.reasons.length > 0 && (
        <ul>
          {result.reasons.map((reason) => (
            <li key={reason}>{issue(reason)}</li>
          ))}
        </ul>
      )}
      {baseline && (
        <p>
          Current {result.baseline_kind === 'pod_requests' ? 'pod requests' : 'VM capacity'} ·{' '}
          {decimal(baseline.cpu_cores, 'cores')} · {bytes(baseline.memory_bytes)}
        </p>
      )}
      {evidence && (
        <>
          <p className="muted">
            Observation window · {date(evidence.start)} – {date(evidence.end)}
          </p>
          <p>
            CPU peak {decimal(evidence.cpu.peak, 'cores')} · p95{' '}
            {decimal(evidence.cpu.p95, 'cores')} · {evidence.cpu.samples} samples at{' '}
            {evidence.cpu.interval_seconds}s
          </p>
          <p>
            RAM peak {bytes(evidence.memory.peak)} · p95 {bytes(evidence.memory.p95)} ·{' '}
            {evidence.memory.samples} samples at {evidence.memory.interval_seconds}s
          </p>
        </>
      )}
      {candidates.length > 0 && (
        <>
          {pricing && (
            <p>
              Cost scenario · {pricing.hours} hours · {pricing.reference}
            </p>
          )}
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Candidate</th>
                  <th scope="col">CPU / RAM</th>
                  <th scope="col">Capacity freed¹</th>
                  <th scope="col">Estimated cost</th>
                  <th scope="col">Estimated savings</th>
                </tr>
              </thead>
              <tbody>
                {candidates.map((candidate) => (
                  <tr key={candidate.name}>
                    <th scope="row">
                      {candidate.name}
                      <small>
                        {candidate.direction} · {candidate.headroom_percent}% reserve
                      </small>
                      {result.baseline_kind === 'pod_requests' && (
                        <Link
                          className="text-link"
                          to={`/capacity?cpu=${Math.round(Number(candidate.proposed.cpu_cores) * 1000)}&memory=${candidate.proposed.memory_bytes}`}
                        >
                          Check placement
                        </Link>
                      )}
                    </th>
                    <td>
                      {decimal(candidate.proposed.cpu_cores, 'cores')}
                      <small>{bytes(candidate.proposed.memory_bytes)}</small>
                    </td>
                    <td>
                      {decimal(candidate.cpu_released_cores, 'cores')}
                      <small>{bytes(candidate.memory_released_bytes)}</small>
                    </td>
                    <td>
                      {candidate.cost ? (
                        <>
                          <span>{money(candidate.cost.candidate_total)}</span>
                          <small>Current {money(candidate.cost.baseline_total)}</small>
                          <small>Recurring {money(candidate.cost.candidate_recurring_total)}</small>
                          <small>Transition {money(candidate.cost.transition_cost)}</small>
                        </>
                      ) : (
                        'Unavailable'
                      )}
                    </td>
                    <td>
                      {candidate.cost ? (
                        <>
                          {money(candidate.cost.savings)}{' '}
                          {candidate.cost.savings_percent !== null && (
                            <small>{candidate.cost.savings_percent}%</small>
                          )}
                        </>
                      ) : (
                        'Unavailable'
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted">
            ¹ A negative value means the candidate needs more capacity. Candidate configurations
            need placement and SLO validation.
          </p>
        </>
      )}
    </section>
  );
}

function AnalyzeResource({ resource }: { resource: Resource }) {
  const [priced, setPriced] = useState(false);
  const [offerCount, setOfferCount] = useState(1);
  const mutation = useMutation({
    mutationFn: (body: unknown) =>
      collectionApi<Analysis>(`/optimization/resources/${resource.id}/analyze`, post(body)),
  });
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const field = (key: string) => String(data.get(key) ?? '').trim();
    mutation.mutate({
      pricing: priced
        ? {
            currency: field('currency').toUpperCase(),
            reference: field('reference'),
            hours: Number(field('hours')),
            baseline_hourly_rate: field('baseline_rate'),
            baseline_recurring_extra: field('baseline_extra') || '0',
            offers: Array.from({ length: offerCount }, (_, i) => ({
              name: field(`offer_name_${i}`),
              cpu_cores: field(`offer_cpu_${i}`),
              memory_bytes: Number(field(`offer_mib_${i}`)) * 1048576,
              hourly_rate: field(`offer_rate_${i}`),
              recurring_extra: field(`offer_extra_${i}`) || '0',
              transition_cost: field(`offer_transition_${i}`) || '0',
            })),
          }
        : null,
    });
  }

  return (
    <>
      <section className="panel collection-panel">
        <div className="panel-heading">
          <h2>Analyze {resource.name}</h2>
          {resource.is_synthetic && <Badge value="synthetic" />}
        </div>
        <form className="data-form" onSubmit={submit}>
          <p className="muted">
            Uses seven days of fresh CPU and RAM samples. Sizing starts at the highest observed
            usage plus a reserve.
          </p>
          {resource.resource_type === 'virtual_machine' && (
            <label className="check-label">
              <input
                type="checkbox"
                checked={priced}
                disabled={mutation.isPending}
                onChange={(e) => setPriced(e.target.checked)}
              />
              Compare manually priced VM offers
            </label>
          )}
          {priced && (
            <>
              <p className="muted">
                Use quotes for the same region, currency and billing assumptions. Enter all
                applicable recurring extras for the full comparison period, including any charges
                that continue after switching.
              </p>
              <div className="form-row">
                <label>
                  Quote reference
                  <input
                    name="reference"
                    maxLength={160}
                    required
                    placeholder="Catalog or quote and date"
                  />
                </label>
                <label>
                  Currency
                  <input
                    name="currency"
                    defaultValue="USD"
                    pattern="[A-Za-z]{3}"
                    maxLength={3}
                    required
                  />
                </label>
                <label>
                  Billable hours
                  <input
                    name="hours"
                    type="number"
                    min={1}
                    max={8760}
                    defaultValue={720}
                    required
                  />
                </label>
              </div>
              <div className="form-row">
                <label>
                  Current hourly rate
                  <input name="baseline_rate" type="number" min="0" step="any" required />
                </label>
                <label>
                  Current recurring extras
                  <input name="baseline_extra" type="number" min="0" step="any" placeholder="0" />
                </label>
              </div>
              {Array.from({ length: offerCount }, (_, i) => (
                <fieldset className="offer-fields" key={i}>
                  <legend>Offer {i + 1}</legend>
                  <div className="form-row">
                    <label>
                      Instance name
                      <input name={`offer_name_${i}`} maxLength={160} required />
                    </label>
                    <label>
                      CPU cores
                      <input
                        name={`offer_cpu_${i}`}
                        type="number"
                        min="0.01"
                        max="100000"
                        step="any"
                        required
                      />
                    </label>
                    <label>
                      RAM MiB
                      <input
                        name={`offer_mib_${i}`}
                        type="number"
                        min="1"
                        max="953674316"
                        required
                      />
                    </label>
                  </div>
                  <div className="form-row">
                    <label>
                      Hourly rate
                      <input name={`offer_rate_${i}`} type="number" min="0" step="any" required />
                    </label>
                    <label>
                      Recurring extras
                      <input
                        name={`offer_extra_${i}`}
                        type="number"
                        min="0"
                        step="any"
                        placeholder="0"
                      />
                    </label>
                    <label>
                      One-time transition
                      <input
                        name={`offer_transition_${i}`}
                        type="number"
                        min="0"
                        step="any"
                        placeholder="0"
                      />
                    </label>
                  </div>
                </fieldset>
              ))}
              <div className="form-row">
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => setOfferCount(offerCount + 1)}
                  disabled={offerCount >= 20 || mutation.isPending}
                >
                  Add offer
                </button>
                {offerCount > 1 && (
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={mutation.isPending}
                    onClick={() => setOfferCount(offerCount - 1)}
                  >
                    Remove last offer
                  </button>
                )}
              </div>
            </>
          )}
          <button className="primary-button" disabled={mutation.isPending}>
            {mutation.isPending ? 'Analyzing…' : 'Run analysis'}
          </button>
          {mutation.error && <p role="alert">{mutation.error.message}</p>}
        </form>
      </section>
      {mutation.data && <Report result={mutation.data} />}
    </>
  );
}

export function Recommendations() {
  const [search, setSearch] = useSearchParams();
  const resourceId = search.get('resource');
  const [kind, setKind] = useState('kubernetes_pod');
  const [name, setName] = useState('');
  const [offset, setOffset] = useState(0);
  const resources = useQuery({
    queryKey: ['collection', 'optimization-picker', kind, name, offset],
    queryFn: ({ signal }) =>
      collectionApi<Page<Resource>>(
        `/resources?${params({ resource_type: kind, q: name, offset, limit: 20 })}`,
        { signal },
      ),
    enabled: !resourceId,
  });
  const selected = useQuery({
    queryKey: ['collection', 'resource', resourceId],
    queryFn: ({ signal }) =>
      collectionApi<Resource>(`/resources/${encodeURIComponent(resourceId ?? '')}`, { signal }),
    enabled: !!resourceId,
  });
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>Recommendations</h1>
          <p>Compare CPU and RAM configurations against measured usage.</p>
        </div>
      </div>
      {resourceId ? (
        <>
          <button
            type="button"
            className="secondary-button back-link"
            onClick={() => setSearch({})}
          >
            Choose another resource
          </button>
          <DataState
            pending={selected.isPending}
            error={selected.error}
            retry={() => void selected.refetch()}
          >
            {selected.data && <AnalyzeResource key={selected.data.id} resource={selected.data} />}
          </DataState>
        </>
      ) : (
        <section className="panel collection-panel">
          <h2>Choose a resource</h2>
          <form
            className="form-row data-form"
            onSubmit={(event) => {
              event.preventDefault();
              setName(String(new FormData(event.currentTarget).get('name') ?? '').trim());
              setOffset(0);
            }}
          >
            <label>
              Resource type
              <select
                value={kind}
                onChange={(event) => {
                  setKind(event.target.value);
                  setOffset(0);
                }}
              >
                <option value="kubernetes_pod">Kubernetes pod</option>
                <option value="virtual_machine">Virtual machine</option>
              </select>
            </label>
            <label>
              Name
              <input name="name" maxLength={100} placeholder="Search by name" />
            </label>
            <button className="secondary-button">Search</button>
          </form>
          <DataState
            pending={resources.isPending}
            error={resources.error}
            retry={() => void resources.refetch()}
          >
            {resources.data &&
              (resources.data.items.length > 0 ? (
                <>
                  <div className="table-scroll">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th scope="col">Resource</th>
                          <th scope="col">Scope</th>
                          <th scope="col">Data quality</th>
                          <th scope="col">Analysis</th>
                        </tr>
                      </thead>
                      <tbody>
                        {resources.data.items.map((resource) => (
                          <tr key={resource.id}>
                            <td>
                              {resource.name} {resource.is_synthetic && <Badge value="synthetic" />}
                            </td>
                            <td>
                              {resource.account_or_cluster_id}
                              {resource.namespace && ` / ${resource.namespace}`}
                            </td>
                            <td>
                              <Badge value={resource.quality.status} />
                            </td>
                            <td>
                              <button
                                className="secondary-button"
                                onClick={() => setSearch({ resource: resource.id })}
                              >
                                Select
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <Pagination
                    total={resources.data.total}
                    limit={20}
                    offset={offset}
                    onChange={setOffset}
                  />
                </>
              ) : (
                <p className="data-notice">
                  No resources match this filter.{' '}
                  <Link className="text-link" to="/sources">
                    Open sources & imports
                  </Link>
                </p>
              ))}
          </DataState>
        </section>
      )}
    </>
  );
}
