import { ApiError } from './api';

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}
export interface Source {
  id: string;
  name: string;
  type: 'csv' | 'prometheus' | 'kubernetes';
  scope: string;
  is_synthetic: boolean;
  status: string;
  last_success_at: string | null;
  last_error_at: string | null;
  discovery_metadata: Record<string, unknown>;
}
export interface Run {
  id: string;
  source_id: string;
  status: string;
  created_at: string;
  records_read: number;
  records_created: number;
  records_updated: number;
  records_rejected: number;
  error_summary: { code: string; row?: number; metric?: string }[];
  attempts: number;
}
export interface Quality {
  status: string;
  reasons: string[];
  optimization_ready: boolean;
  history_seconds: number;
  gap_count: number;
  latest_at: string | null;
}
export interface Resource {
  id: string;
  source_id: string;
  external_id: string;
  name: string;
  provider: string;
  resource_type: string;
  account_or_cluster_id: string;
  namespace: string | null;
  region: string | null;
  availability_zone: string | null;
  status: string;
  is_synthetic: boolean;
  last_seen_at: string;
  discovered_at: string;
  cpu_capacity: string | null;
  memory_capacity_bytes: string | null;
  cpu_requests: string | null;
  memory_requests_bytes: string | null;
  cpu_limits: string | null;
  memory_limits_bytes: string | null;
  cpu_allocatable: string | null;
  memory_allocatable_bytes: string | null;
  configuration: Record<string, unknown>;
  labels: Record<string, string>;
  quality: Quality;
  latest_metrics: Record<string, { value: string; unit: string; timestamp: string }>;
}
export interface Metric {
  id: string;
  source_id: string;
  metric_name: string;
  value: string;
  unit: string;
  timestamp: string;
  quality_status: string;
}
export interface Bill {
  id: string;
  service: string;
  period_start: string;
  period_end: string;
  amount: string;
  currency: string;
  cost_type: string;
  external_resource_id: string;
}
export interface BillingGroup {
  currency: string;
  cost_type: string;
  is_synthetic: boolean;
  amount: string;
  records: number;
  unmatched_records: number;
}
export interface QualitySummary {
  total_resources: number;
  states: Record<string, number>;
  optimization_ready: number;
  sources_without_success: number;
}

export function params(values: Record<string, string | number | boolean | undefined>) {
  return new URLSearchParams(
    Object.entries(values)
      .filter(([, v]) => v !== undefined && v !== '')
      .map(([k, v]) => [k, String(v)]),
  ).toString();
}
export async function collectionApi<T>(path: string, init?: RequestInit): Promise<T> {
  const base = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');
  try {
    const response = await fetch(`${base}/api/v1${path}`, {
      ...init,
      signal: init?.signal || AbortSignal.timeout(15000),
      cache: 'no-store',
      headers: { Accept: 'application/json', ...init?.headers },
    });
    const body: unknown = await response.json();
    if (!response.ok) {
      const error = body as { error?: { message?: string } };
      throw new ApiError(error.error?.message || 'The request failed.', response.status);
    }
    return body as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError('Could not reach the collection API. Try again.');
  }
}
export const post = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});
export const date = (value: string | null) => (value ? new Date(value).toLocaleString() : 'Never');
export const decimal = (value: string | null | undefined, unit = '') =>
  value == null
    ? 'Unavailable'
    : `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 4 })}${unit ? ` ${unit}` : ''}`;
export const bytes = (value: string | null | undefined) =>
  value == null
    ? 'Unavailable'
    : `${(Number(value) / 1048576).toLocaleString(undefined, { maximumFractionDigits: 2 })} MiB`;
