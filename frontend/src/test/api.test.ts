import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, getSystemInfo } from '../lib/api';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('API client', () => {
  it('rejects HTTP failures without exposing response details', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('private details', { status: 500 })),
    );
    await expect(getSystemInfo()).rejects.toMatchObject({ status: 500, name: 'ApiError' });
  });
  it('rejects malformed system responses', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'ok' }))),
    );
    await expect(getSystemInfo()).rejects.toThrow('unexpected response');
  });
  it('cancels requests after the deadline', async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_url, options: RequestInit) =>
          new Promise((_resolve, reject) =>
            options.signal?.addEventListener('abort', () =>
              reject(new DOMException('Aborted', 'AbortError')),
            ),
          ),
      ),
    );
    const request = getSystemInfo();
    const assertion = expect(request).rejects.toBeInstanceOf(ApiError);
    await vi.advanceTimersByTimeAsync(8000);
    await assertion;
  });
});
