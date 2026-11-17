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
    fireEvent.click(screen.getByRole('link', { name: 'Resources' }));
    expect(await screen.findByText('A little further on the horizon.')).toBeInTheDocument();
    expect(screen.getByText('Stage 2 · Data collection')).toBeInTheDocument();
    expect(screen.queryByText(/\$[0-9]/)).not.toBeInTheDocument();
  });

  it('settings reuse centralized API data', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(info))));
    renderApp('/settings');
    await waitFor(() => expect(screen.getByText('testing')).toBeInTheDocument());
    expect(screen.getByText('Same-origin proxy')).toBeInTheDocument();
  });
});
