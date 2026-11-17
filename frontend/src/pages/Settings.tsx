import { useSystemInfo } from '../lib/queries';

export function Settings() {
  const query = useSystemInfo();
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">YOUR WORKSPACE</div>
          <h1>Settings</h1>
          <p>Application details and connection information.</p>
        </div>
      </div>
      <section className="panel settings-panel">
        <h2>Environment</h2>
        {query.isPending ? (
          <p role="status">Loading configuration…</p>
        ) : query.isError ? (
          <div role="alert">
            <p>Couldn’t load application details.</p>
            <button className="secondary-button" onClick={() => void query.refetch()}>
              Try again
            </button>
          </div>
        ) : (
          <dl>
            <div>
              <dt>Application</dt>
              <dd>{query.data.name}</dd>
            </div>
            <div>
              <dt>Version</dt>
              <dd>{query.data.version}</dd>
            </div>
            <div>
              <dt>Environment</dt>
              <dd>{query.data.environment}</dd>
            </div>
            <div>
              <dt>API connection</dt>
              <dd>{import.meta.env.VITE_API_BASE_URL || 'Same-origin proxy'}</dd>
            </div>
          </dl>
        )}
        <p className="settings-note">
          Configuration is managed through environment variables. Cloud connections and account
          settings will be added in later stages.
        </p>
      </section>
    </>
  );
}
