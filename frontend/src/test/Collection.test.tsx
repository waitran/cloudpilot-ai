import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from '../App';
import type { Resource, Source } from '../lib/collection';

const source: Source = {
  id: 'source-1',
  name: 'Demo import',
  type: 'csv',
  scope: 'demo',
  is_synthetic: true,
  status: 'completed',
  last_success_at: '2026-01-01T00:00:00Z',
  last_error_at: null,
  discovery_metadata: {},
};
const resource: Resource = {
  id: 'r-1',
  source_id: source.id,
  external_id: 'uid-1',
  name: 'api-pod',
  provider: 'kubernetes',
  resource_type: 'kubernetes_pod',
  account_or_cluster_id: 'demo',
  namespace: 'default',
  region: null,
  availability_zone: null,
  status: 'Running',
  is_synthetic: true,
  last_seen_at: '2026-01-01T00:00:00Z',
  discovered_at: '2026-01-01T00:00:00Z',
  cpu_capacity: null,
  memory_capacity_bytes: null,
  cpu_allocatable: null,
  memory_allocatable_bytes: null,
  cpu_requests: '0.25',
  memory_requests_bytes: '134217728',
  cpu_limits: '1',
  memory_limits_bytes: '536870912',
  configuration: { request_scope: 'pod' },
  labels: { app: 'api' },
  quality: {
    status: 'partial',
    reasons: ['metric_gaps', 'insufficient_history_7d'],
    optimization_ready: false,
    history_seconds: 60,
    gap_count: 1,
    latest_at: null,
  },
  latest_metrics: {},
};
function page<T>(items: T[]) {
  return { items, total: items.length, limit: 20, offset: 0 };
}
function setup(path: string, handler?: (url: string, init?: RequestInit) => unknown) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const custom = handler?.(url, init);
    if (custom instanceof Response) return custom;
    if (custom !== undefined) return new Response(JSON.stringify(custom));
    if (url.includes('/system/info'))
      return new Response(
        JSON.stringify({
          name: 'CloudPilot AI',
          version: '0.1.0',
          environment: 'testing',
          components: {
            backend: { status: 'available' },
            postgresql: { status: 'available' },
            collector: { status: 'available' },
          },
        }),
      );
    if (url === '/api/v1/resources/r-1') return new Response(JSON.stringify(resource));
    if (url.includes('/sources')) return new Response(JSON.stringify(page([source])));
    if (url.includes('/data-quality/summary'))
      return new Response(
        JSON.stringify({
          total_resources: 0,
          states: {},
          optimization_ready: 0,
          sources_without_success: 0,
        }),
      );
    if (url.includes('/billing/summary')) return new Response('[]');
    return new Response(JSON.stringify(page([])));
  });
  vi.stubGlobal('fetch', fetchMock);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return fetchMock;
}
afterEach(() => vi.unstubAllGlobals());

describe('data collection workspace', () => {
  it('shows a truthful empty inventory and a source action', async () => {
    setup('/resources');
    expect(await screen.findByText('Your inventory starts here')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open sources & imports' })).toHaveAttribute(
      'href',
      '/sources',
    );
    expect(screen.queryByText(/\$\d/)).not.toBeInTheDocument();
  });
  it('filters resources through the API and links stable identities', async () => {
    const fetch = setup('/resources', (url) =>
      url.startsWith('/api/v1/resources?') ? page([resource]) : undefined,
    );
    expect(await screen.findByRole('link', { name: 'api-pod' })).toHaveAttribute(
      'href',
      '/resources/r-1',
    );
    expect(screen.getAllByText('Unavailable').length).toBeGreaterThan(0);
    fireEvent.change(screen.getByLabelText('Resource name'), { target: { value: 'api %' } });
    fireEvent.change(screen.getByLabelText('Data'), { target: { value: 'true' } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    await waitFor(() =>
      expect(
        fetch.mock.calls.some(
          ([url]) => url.includes('q=api+%25') && url.includes('is_synthetic=true'),
        ),
      ).toBe(true),
    );
  });
  it('shows collection errors with retry', async () => {
    setup('/resources', (url) =>
      url.startsWith('/api/v1/resources?')
        ? new Response(JSON.stringify({ error: { message: 'Database unavailable' } }), {
            status: 503,
          })
        : undefined,
    );
    expect(await screen.findByRole('alert')).toHaveTextContent('Database unavailable');
    expect(screen.getByRole('button', { name: 'Retry' })).toBeEnabled();
  });
  it('details show missing observations and quality reasons without inventing data', async () => {
    setup('/resources/r-1');
    expect(await screen.findByRole('heading', { name: 'api-pod' })).toBeInTheDocument();
    expect(screen.getByText(/metric gaps · insufficient history 7d/)).toBeInTheDocument();
    expect(screen.getByText('No metrics collected for this identity.')).toBeInTheDocument();
    expect(
      await screen.findByText('No samples in this window. Missing data is not zero.'),
    ).toBeInTheDocument();
    expect(await screen.findByText(/No billing linked/)).toBeInTheDocument();
  });
  it('queues a CSV upload and reports the durable job identifier', async () => {
    const fetch = setup('/sources', (url, init) =>
      url === '/api/v1/imports/csv' && init?.method === 'POST'
        ? { id: 'run-12345678', status: 'pending' }
        : undefined,
    );
    await screen.findByRole('option', { name: /Demo import/ });
    fireEvent.change(screen.getByLabelText('Source'), { target: { value: source.id } });
    await userEvent.upload(
      screen.getByLabelText('CSV file · UTF-8 · up to 2 MiB'),
      new File(['external_id,resource_type,name\nu,virtual_machine,vm\n'], 'resources.csv', {
        type: 'text/csv',
      }),
    );
    const input = screen.getByLabelText('CSV file · UTF-8 · up to 2 MiB') as HTMLInputElement;
    expect(input.files?.length).toBe(1);
    // JSDOM does not update native file validity after a synthetic file selection.
    fireEvent.submit(screen.getByRole('button', { name: 'Queue CSV import' }).closest('form')!);
    expect(await screen.findByText('run-1234')).toBeInTheDocument();
    const call = fetch.mock.calls.find(([url]) => url === '/api/v1/imports/csv');
    expect((call?.[1]?.body as FormData).get('source_id')).toBe(source.id);
    expect((call?.[1]?.body as FormData).get('kind')).toBe('resources');
  });
  it('rejects oversized files before sending them', async () => {
    const fetch = setup('/sources');
    await screen.findByRole('option', { name: /Demo import/ });
    fireEvent.change(screen.getByLabelText('Source'), { target: { value: source.id } });
    await userEvent.upload(
      screen.getByLabelText('CSV file · UTF-8 · up to 2 MiB'),
      new File(['x'.repeat(2 * 1024 * 1024 + 1)], 'large.csv', { type: 'text/csv' }),
    );
    const input = screen.getByLabelText('CSV file · UTF-8 · up to 2 MiB') as HTMLInputElement;
    expect(input.files?.length).toBe(1);
    // JSDOM does not update native file validity after a synthetic file selection.
    fireEvent.submit(screen.getByRole('button', { name: 'Queue CSV import' }).closest('form')!);
    expect(await screen.findByRole('alert')).toHaveTextContent('up to 2 MiB');
    expect(fetch.mock.calls.some(([url]) => url === '/api/v1/imports/csv')).toBe(false);
  });
  it('keeps exact billing amounts and currency categories visible', async () => {
    setup('/sources', (url) =>
      url.includes('/billing/summary')
        ? [
            {
              currency: 'USD',
              cost_type: 'actual',
              is_synthetic: true,
              amount: '0.123456789',
              records: 2,
              unmatched_records: 1,
            },
            {
              currency: 'EUR',
              cost_type: 'estimated',
              is_synthetic: false,
              amount: '0.2',
              records: 1,
              unmatched_records: 0,
            },
          ]
        : undefined,
    );
    expect(await screen.findByText('0.123456789 USD')).toBeInTheDocument();
    expect(screen.getByText('0.2 EUR')).toBeInTheDocument();
    expect(screen.getByText('2 records · 1 unmatched')).toBeInTheDocument();
  });
});
