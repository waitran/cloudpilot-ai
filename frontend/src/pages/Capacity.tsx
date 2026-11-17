import { useState, type FormEvent } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { Badge } from '../components/Collection';
import { bytes, collectionApi, date, post } from '../lib/collection';

type Check = {
  code: string;
  required: string | null;
  available: string | null;
  unit: string | null;
  pool: string | null;
};
type Report = {
  status:
    'feasible_now' | 'scale_out_required' | 'infeasible' | 'insufficient_data' | 'no_plan_found';
  evaluated_at: string;
  scenario: {
    snapshot: { context: string; namespace: string; observed_at: string; synthetic: boolean };
    additional_replicas: number;
  };
  current_slots: number | null;
  current_slots_after_node_loss: number | null;
  checks: Check[];
  placement: { node: string; replicas: number }[];
  nodes: {
    name: string;
    eligible: boolean;
    free_cpu_millicores: number;
    free_memory_bytes: number;
    free_pod_slots: number;
    replica_slots: number;
  }[];
  scale_options: {
    pool: string;
    new_nodes: number;
    slots_per_new_node: number;
    ready_within_seconds: number;
    capacity_after_node_loss: number;
    replicas_on_existing_nodes: number;
    replicas_on_new_nodes: number;
  }[];
};

const statusText = {
  feasible_now: 'Fits on existing nodes',
  scale_out_required: 'Additional nodes required',
  infeasible: 'Blocked by current constraints',
  insufficient_data: 'Insufficient evidence',
  no_plan_found: 'No single-pool plan found',
};

const messages: Record<string, string> = {
  snapshot_expired_or_future: 'Update the observation time and refresh the snapshot.',
  inventory_incomplete: 'Confirm that all eligible nodes and resident requests are included.',
  admission_and_placement_not_reviewed:
    'Review admission and placement for the exact pod specification.',
  incumbent_failover_load_unknown:
    'Account for existing workloads that must move after a node loss.',
  namespace_quota_unknown:
    'Provide remaining applicable namespace quota or confirm there is no quota.',
  pod_ip_capacity_unknown: 'Provide confirmed free pod IP capacity.',
  current_capacity_shortfall:
    'Current nodes have too few replica slots under the selected reserve.',
  pool_unavailable_or_pod_does_not_fit:
    'Pool has no available nodes or the pod does not fit its shape.',
  pool_misses_deadline: 'Pool startup exceeds the capacity deadline.',
  pool_supply_or_startup_unknown: 'Provider capacity or startup time is unconfirmed.',
  pool_node_limit: 'This pool cannot close the capacity shortfall within its node allowance.',
  capacity_upper_bound: 'Even the optimistic total across the eligible pools is too small.',
  scale_out_evidence_incomplete: 'Supply and startup evidence for all eligible pools is needed.',
  no_single_pool_plan: 'A combination of different pools may still meet the requirement.',
};

const emptySnapshot = {
  context: '',
  namespace: '',
  observed_at: '',
  synthetic: false,
  inventory_complete: false,
  constraints_reviewed: false,
  failure_load_accounted: false,
  nodes: [],
  namespace_quota: null,
  pod_ips_remaining: null,
  pools_complete: false,
  pools: [],
};

function demoSnapshot() {
  const resources = (cpu: number, ramGiB: number, pods: number) => ({
    cpu_millicores: cpu,
    memory_bytes: ramGiB * 1024 ** 3,
    pods,
  });
  return {
    ...emptySnapshot,
    context: 'synthetic-demo',
    namespace: 'demo',
    observed_at: new Date().toISOString(),
    synthetic: true,
    inventory_complete: true,
    constraints_reviewed: true,
    failure_load_accounted: true,
    nodes: [
      {
        name: 'demo-existing-1',
        eligible: true,
        allocatable: resources(4000, 8, 20),
        occupied: resources(2900, 6, 9),
      },
    ],
    namespace_quota: { pods: 12, cpu_millicores: 8000, memory_bytes: 16 * 1024 ** 3 },
    pod_ips_remaining: 20,
    pools_complete: true,
    pools: [
      {
        name: 'standard',
        eligible: true,
        allocatable: resources(2000, 4, 16),
        daemon_requests: resources(200, 1, 3),
        scale_limit_remaining: 4,
        provider_nodes_available: 3,
        ready_within_seconds: 125,
      },
      {
        name: 'large',
        eligible: true,
        allocatable: resources(4000, 8, 20),
        daemon_requests: resources(300, 1, 3),
        scale_limit_remaining: 2,
        provider_nodes_available: 2,
        ready_within_seconds: 180,
      },
    ],
  };
}

function Result({ report }: { report: Report }) {
  const snap = report.scenario.snapshot;
  return (
    <section className="panel collection-panel" aria-label="Placement report">
      <div className="panel-heading">
        <h2>{statusText[report.status]}</h2>
        {snap.synthetic && <Badge value="synthetic" />}
      </div>
      <p className="muted">
        {snap.context} / {snap.namespace} · snapshot {date(snap.observed_at)} · evaluated{' '}
        {date(report.evaluated_at)}
      </p>
      {report.current_slots !== null && (
        <p>
          Requested {report.scenario.additional_replicas} · current slots {report.current_slots} ·
          slots after node loss {report.current_slots_after_node_loss}
        </p>
      )}
      {report.checks.length > 0 && (
        <ul>
          {report.checks.map((check) => (
            <li key={`${check.code}:${check.pool ?? ''}`}>
              {check.pool && `${check.pool} · `}
              {messages[check.code] ?? check.code.replaceAll('_', ' ')}
              {check.required !== null && (
                <>
                  {' '}
                  ({check.required} needed, {check.available} available · {check.unit})
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      {report.nodes.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <caption>Existing nodes</caption>
            <thead>
              <tr>
                <th>Node</th>
                <th>Eligible</th>
                <th>Free CPU</th>
                <th>Free RAM</th>
                <th>Free pod slots</th>
                <th>Replica slots</th>
                <th>Example placement</th>
              </tr>
            </thead>
            <tbody>
              {report.nodes.map((node) => (
                <tr key={node.name}>
                  <th scope="row">{node.name}</th>
                  <td>{node.eligible ? 'Yes' : 'No'}</td>
                  <td>{node.free_cpu_millicores}m</td>
                  <td>{bytes(String(node.free_memory_bytes))}</td>
                  <td>{node.free_pod_slots}</td>
                  <td>{node.replica_slots}</td>
                  <td>
                    {report.status === 'feasible_now'
                      ? (report.placement.find((item) => item.node === node.name)?.replicas ?? 0)
                      : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {report.scale_options.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <caption>Scale-out alternatives</caption>
            <thead>
              <tr>
                <th>Node pool</th>
                <th>New nodes</th>
                <th>Slots per new node</th>
                <th>Existing / new replicas</th>
                <th>Slots after node loss</th>
                <th>Ready within</th>
              </tr>
            </thead>
            <tbody>
              {report.scale_options.map((option) => (
                <tr key={option.pool}>
                  <th scope="row">{option.pool}</th>
                  <td>{option.new_nodes}</td>
                  <td>{option.slots_per_new_node}</td>
                  <td>
                    {option.replicas_on_existing_nodes} / {option.replicas_on_new_nodes}
                  </td>
                  <td>{option.capacity_after_node_loss}</td>
                  <td>{option.ready_within_seconds}s</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted">
        Placement is conditional on the supplied snapshot. Performance and SLO require load testing.
      </p>
    </section>
  );
}

export function Capacity() {
  const [search] = useSearchParams();
  const [snapshot, setSnapshot] = useState(JSON.stringify(emptySnapshot, null, 2));
  const [parseError, setParseError] = useState('');
  const [cpu, setCpu] = useState(search.get('cpu') ?? '');
  const [memory, setMemory] = useState(search.get('memory') ?? '');
  const [replicas, setReplicas] = useState('1');
  const mutation = useMutation({
    mutationFn: (body: unknown) => collectionApi<Report>('/feasibility/evaluate', post(body)),
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setParseError('');
    let inventory: unknown;
    try {
      inventory = JSON.parse(snapshot);
    } catch {
      mutation.reset();
      setParseError('The cluster snapshot must be valid JSON.');
      return;
    }
    const number = (field: string) => Number(data.get(field));
    const optional = (field: string) => (data.get(field) === '' ? null : number(field));
    mutation.mutate({
      pod: {
        cpu_millicores: Number(cpu),
        memory_bytes: Number(memory),
        cpu_limit_millicores: optional('cpu_limit'),
        memory_limit_bytes: optional('memory_limit'),
      },
      additional_replicas: Number(replicas),
      reserve_percent: number('reserve'),
      tolerate_lost_nodes: number('lost'),
      capacity_deadline_seconds: number('deadline'),
      snapshot: inventory,
    });
  }

  function loadDemo() {
    setSnapshot(JSON.stringify(demoSnapshot(), null, 2));
    setCpu('500');
    setMemory('536870912');
    setReplicas('5');
    setParseError('');
    mutation.reset();
  }

  return (
    <>
      <div className="page-heading">
        <div>
          <h1>Capacity planning</h1>
          <p>Check placement and node capacity for a peak rollout or replica increase.</p>
        </div>
      </div>
      <section className="panel collection-panel">
        <form className="data-form" onSubmit={submit}>
          <div className="form-row">
            <label>
              Additional replicas
              <input
                type="number"
                min={1}
                max={10000}
                value={replicas}
                onChange={(event) => setReplicas(event.target.value)}
                required
              />
            </label>
            <label>
              CPU request (millicores)
              <input
                type="number"
                min={1}
                max={100000000}
                value={cpu}
                onChange={(event) => setCpu(event.target.value)}
                required
              />
            </label>
            <label>
              RAM request (bytes)
              <input
                type="number"
                min={1}
                max={10 ** 15}
                value={memory}
                onChange={(event) => setMemory(event.target.value)}
                required
              />
            </label>
          </div>
          <div className="form-row">
            <label>
              CPU limit (millicores)
              <input
                type="number"
                name="cpu_limit"
                min={1}
                max={100000000}
                placeholder="Optional"
              />
            </label>
            <label>
              RAM limit (bytes)
              <input
                type="number"
                name="memory_limit"
                min={1}
                max={10 ** 15}
                placeholder="Optional"
              />
            </label>
          </div>
          <div className="form-row">
            <label>
              CPU and RAM reserve (%)
              <input type="number" name="reserve" min={0} max={75} defaultValue={15} required />
            </label>
            <label>
              Node losses to tolerate
              <input type="number" name="lost" min={0} max={3} defaultValue={0} required />
            </label>
            <label>
              Capacity deadline (seconds)
              <input
                type="number"
                name="deadline"
                min={0}
                max={86400}
                defaultValue={300}
                required
              />
            </label>
          </div>
          <p className="muted">
            Count existing pods, including old replicas during rollout, in occupied resources and
            quota usage.
          </p>
          <label>
            Cluster snapshot (JSON)
            <textarea
              rows={12}
              maxLength={1000000}
              value={snapshot}
              onChange={(event) => setSnapshot(event.target.value)}
              spellCheck={false}
              required
            />
          </label>
          <div className="form-row">
            <button className="primary-button" disabled={mutation.isPending}>
              {mutation.isPending ? 'Checking…' : 'Check capacity'}
            </button>
            <button
              type="button"
              className="secondary-button"
              onClick={loadDemo}
              disabled={mutation.isPending}
            >
              Load synthetic example
            </button>
          </div>
          {(parseError || mutation.error) && (
            <p role="alert">{parseError || mutation.error?.message}</p>
          )}
        </form>
      </section>
      {mutation.data && <Result report={mutation.data} />}
    </>
  );
}
