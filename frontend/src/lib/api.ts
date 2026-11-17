export type ComponentState = 'available' | 'unavailable' | 'planned';
export interface SystemInfo {
  name: string;
  version: string;
  environment: string;
  components: Record<string, { status: ComponentState }>;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

function isSystemInfo(value: unknown): value is SystemInfo {
  if (!value || typeof value !== 'object') return false;
  const info = value as Partial<SystemInfo>;
  return (
    typeof info.name === 'string' &&
    typeof info.version === 'string' &&
    typeof info.environment === 'string' &&
    !!info.components &&
    typeof info.components === 'object' &&
    !!info.components.backend &&
    !!info.components.postgresql &&
    Object.values(info.components).every(
      (component) =>
        component && ['available', 'unavailable', 'planned'].includes(component.status),
    )
  );
}

export async function getSystemInfo(signal?: AbortSignal): Promise<SystemInfo> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener('abort', abort, { once: true });
  if (signal?.aborted) controller.abort();
  const timeout = setTimeout(abort, 8000);
  try {
    const base = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');
    const response = await fetch(`${base}/api/v1/system/info`, {
      signal: controller.signal,
      headers: { Accept: 'application/json' },
      cache: 'no-store',
    });
    if (!response.ok)
      throw new ApiError('The backend could not complete the request.', response.status);
    const data: unknown = await response.json();
    if (!isSystemInfo(data)) throw new ApiError('The backend returned an unexpected response.');
    return data;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (controller.signal.aborted) throw new ApiError('The request timed out or was cancelled.');
    throw new ApiError('The backend is unreachable. Check that it is running.');
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener('abort', abort);
  }
}
