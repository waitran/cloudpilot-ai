import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from '../App';
import type { SystemInfo } from '../lib/api';

const info: SystemInfo = {
  name: 'CloudPilot AI',
  version: '0.1.0',
  environment: 'testing',
  components: { backend: { status: 'available' }, postgresql: { status: 'available' } },
};

function renderApp(path = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return client;
}

afterEach(() => vi.unstubAllGlobals());

describe('application workspace', () => {
  it('loads and displays actual API status', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(info)));
    vi.stubGlobal('fetch', fetchMock);
    renderApp();
    expect(screen.getByRole('status', { name: 'Loading system status' })).toBeInTheDocument();
    expect(await screen.findByText('Your foundation is ready')).toBeInTheDocument();
    expect(screen.getByText('v0.1.0')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/system/info');
  });

  it('shows a real database failure without reporting readiness', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            ...info,
            components: { ...info.components, postgresql: { status: 'unavailable' } },
          }),
        ),
      ),
    );
    renderApp();
    expect(await screen.findByText('Database connection needs attention')).toBeInTheDocument();
    expect(screen.queryByText('Your foundation is ready')).not.toBeInTheDocument();
  });

  it('handles an API outage and can retry', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('Network failed'));
    vi.stubGlobal('fetch', fetchMock);
    renderApp();
    const alert = await screen.findByRole('alert', {}, { timeout: 5000 });
    expect(alert).toHaveTextContent('We couldn’t reach your backend.');
    fetchMock.mockResolvedValue(new Response(JSON.stringify(info)));
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText('Your foundation is ready')).toBeInTheDocument();
  });

  it('navigates to planned modules without fake metrics', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(info))));
    renderApp();
    await screen.findByText('Your foundation is ready');
    fireEvent.click(screen.getByRole('link', { name: 'Optimization Lab' }));
    expect(await screen.findByText('A little further on the horizon.')).toBeInTheDocument();
    expect(screen.getByText('Stage 6 · Experiment validation')).toBeInTheDocument();
    expect(screen.queryByText(/\$[0-9]/)).not.toBeInTheDocument();
  });

  it('runs sizing for the selected VM and displays the estimated and capacity changes', async () => {
    const resource = {
      id: 'vm-1',
      name: 'api-worker',
      resource_type: 'virtual_machine',
      is_synthetic: true,
    };
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/resources/vm-1')) return new Response(JSON.stringify(resource));
      if (url.endsWith('/optimization/resources/vm-1/analyze') && init?.method === 'POST') {
        return new Response(
          JSON.stringify({
            resource_name: resource.name,
            is_synthetic: true,
            status: 'candidates',
            evaluated_at: '2026-11-17T22:30:00Z',
            reasons: [],
            baseline_kind: 'vm_capacity',
            baseline: { cpu_cores: '4', memory_bytes: '4294967296' },
            pricing: { currency: 'USD', hours: 720, reference: 'Example quote' },
            evidence: null,
            candidates: [
              {
                name: 'vm-small',
                proposed: { cpu_cores: '2', memory_bytes: '2147483648' },
                headroom_percent: 30,
                cpu_released_cores: '2',
                memory_released_bytes: '2147483648',
                direction: 'downsize',
                cost: {
                  candidate_total: '59.5',
                  baseline_total: '86.4',
                  candidate_recurring_total: '54',
                  transition_cost: '5.5',
                  savings: '26.9',
                  savings_percent: '31.13',
                },
              },
            ],
          }),
        );
      }
      throw new Error('Unexpected request');
    });
    vi.stubGlobal('fetch', fetchMock);
    renderApp('/recommendations?resource=vm-1');
    await screen.findByRole('heading', { name: 'Analyze api-worker' });
    fireEvent.click(screen.getByLabelText('Compare manually priced VM offers'));
    for (const [label, value] of Object.entries({
      'Quote reference': 'Example quote',
      'Current hourly rate': '0.12',
      'Instance name': 'vm-small',
      'CPU cores': '2',
      'RAM MiB': '2048',
      'Hourly rate': '0.075',
      'One-time transition': '5.5',
    })) {
      fireEvent.change(screen.getByLabelText(label, { exact: true }), { target: { value } });
    }
    fireEvent.click(screen.getByRole('button', { name: 'Run analysis' }));
    expect(await screen.findByText('59.5 USD')).toBeInTheDocument();
    expect(screen.getByText('Transition 5.5 USD')).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([url]) => url.endsWith('/analyze'));
    expect(JSON.parse(String(call?.[1]?.body)).pricing.offers[0]).toMatchObject({
      name: 'vm-small',
      memory_bytes: 2147483648,
      hourly_rate: '0.075',
      transition_cost: '5.5',
    });
  });

  it('submits a synthetic capacity scenario and displays a scale-out alternative', async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      const scenario = JSON.parse(String(init?.body));
      return new Response(
        JSON.stringify({
          status: 'scale_out_required',
          evaluated_at: '2026-11-18T01:00:00Z',
          scenario,
          current_slots: 1,
          current_slots_after_node_loss: 1,
          nodes: [],
          placement: [],
          checks: [
            {
              code: 'current_capacity_shortfall',
              required: '5',
              available: '1',
              unit: 'pods',
              pool: null,
            },
          ],
          scale_options: [
            {
              pool: 'large',
              new_nodes: 1,
              slots_per_new_node: 6,
              ready_within_seconds: 180,
              capacity_after_node_loss: 7,
              replicas_on_existing_nodes: 1,
              replicas_on_new_nodes: 4,
            },
          ],
        }),
      );
    });
    vi.stubGlobal('fetch', fetchMock);
    renderApp('/capacity');
    fireEvent.click(screen.getByRole('button', { name: 'Load synthetic example' }));
    fireEvent.click(screen.getByRole('button', { name: 'Check capacity' }));
    expect(
      await screen.findByRole('heading', { name: 'Additional nodes required' }),
    ).toBeInTheDocument();
    expect(screen.getByText('180s')).toBeInTheDocument();
    expect(screen.getByText('synthetic')).toBeInTheDocument();
    const call = fetchMock.mock.calls[0];
    expect(call?.[0]).toBe('/api/v1/feasibility/evaluate');
    expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
      additional_replicas: 5,
      pod: { cpu_millicores: 500, memory_bytes: 536870912 },
      snapshot: { synthetic: true, context: 'synthetic-demo' },
    });
  });

  it('settings reuse centralized API data', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(info))));
    renderApp('/settings');
    await waitFor(() => expect(screen.getByText('testing')).toBeInTheDocument());
    expect(screen.getByText('Same-origin proxy')).toBeInTheDocument();
  });
});
