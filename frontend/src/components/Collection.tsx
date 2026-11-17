import type { ReactNode } from 'react';

export function Badge({ value }: { value: string }) {
  return <span className={`data-badge data-${value}`}>{value.replaceAll('_', ' ')}</span>;
}
export function DataState({
  pending,
  error,
  retry,
  children,
}: {
  pending: boolean;
  error: Error | null;
  retry: () => void;
  children: ReactNode;
}) {
  if (pending)
    return (
      <p role="status" className="data-notice">
        Loading collection data…
      </p>
    );
  if (error)
    return (
      <div role="alert" className="data-notice">
        <p>{error.message}</p>
        <button className="secondary-button" onClick={retry}>
          Retry
        </button>
      </div>
    );
  return children;
}
export function Pagination({
  total,
  offset,
  limit,
  onChange,
}: {
  total: number;
  offset: number;
  limit: number;
  onChange: (offset: number) => void;
}) {
  return (
    <div className="data-pagination">
      <span>
        {total ? `${offset + 1}–${Math.min(offset + limit, total)} of ${total}` : '0 results'}
      </span>
      <div>
        <button
          className="secondary-button"
          disabled={offset === 0}
          onClick={() => onChange(Math.max(0, offset - limit))}
        >
          Previous
        </button>
        <button
          className="secondary-button"
          disabled={offset + limit >= total}
          onClick={() => onChange(offset + limit)}
        >
          Next
        </button>
      </div>
    </div>
  );
}
