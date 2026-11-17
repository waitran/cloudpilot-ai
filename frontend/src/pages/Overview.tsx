import {
  ArrowRight,
  ArrowUpRight,
  Box,
  Check,
  Circle,
  Database,
  FlaskConical,
  Lightbulb,
  Radio,
  RefreshCw,
  Server,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { useSystemInfo } from '../lib/queries';

export function Overview() {
  const query = useSystemInfo();
  if (query.isPending)
    return (
      <div className="loading-view" role="status" aria-label="Loading system status">
        <div className="skeleton heading-skeleton" />
        <div className="skeleton hero-skeleton" />
        <div className="loading-grid">
          {[1, 2, 3].map((key) => (
            <div key={key} className="skeleton card-skeleton" />
          ))}
        </div>
        <p>Connecting to your workspace…</p>
      </div>
    );
  if (query.isError)
    return (
      <section className="error-view" role="alert">
        <span className="error-symbol">
          <TriangleAlert size={28} />
        </span>
        <div className="eyebrow">CONNECTION INTERRUPTED</div>
        <h1>We couldn’t reach your backend.</h1>
        <p>{query.error.message}</p>
        <p className="muted">System status is unavailable until a new response is received.</p>
        <button
          className="primary-button"
          disabled={query.isFetching}
          onClick={() => void query.refetch()}
        >
          <RefreshCw size={16} />
          {query.isFetching ? 'Reconnecting…' : 'Try again'}
        </button>
      </section>
    );
  const info = query.data;
  const databaseReady = info.components.postgresql?.status === 'available';
  const modules = [
    {
      title: 'Resource visibility',
      description: 'Your cloud resources, utilization and costs. One clear picture.',
      icon: Box,
      path: '/resources',
      stage: 'STAGE 02',
    },
    {
      title: 'Smarter recommendations',
      description: 'Find opportunities backed by real metrics and cost analysis.',
      icon: Lightbulb,
      path: '/recommendations',
      stage: 'STAGE 03',
    },
    {
      title: 'Validate before you change',
      description: 'Compare configurations under load. Protect your SLOs.',
      icon: FlaskConical,
      path: '/lab',
      stage: 'STAGE 06',
    },
  ];
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">YOUR INFRASTRUCTURE, AT A GLANCE</div>
          <h1>Overview</h1>
          <p>A clear view of your workspace. A foundation for what’s next.</p>
        </div>
        <button
          className="secondary-button"
          disabled={query.isFetching}
          onClick={() => void query.refetch()}
        >
          <RefreshCw size={15} className={query.isFetching ? 'spinning' : ''} />
          Refresh status
        </button>
      </div>
      <section className="hero-panel">
        <div className="hero-copy">
          <span className="hero-tag">
            <Sparkles size={13} /> A MORE INTENTIONAL CLOUD
          </span>
          <h2>
            Less waste.
            <br />
            <span>More possibility.</span>
          </h2>
          <p>
            Understand your infrastructure. Test every recommendation.
            <br className="desktop-break" /> Make your next move with confidence.
          </p>
          <Link className="primary-button" to="/resources">
            Explore your workspace <ArrowRight size={16} />
          </Link>
        </div>
        <div className="hero-visual" aria-hidden="true">
          <div className="orbit orbit-one" />
          <div className="orbit orbit-two" />
          <div className="diagram-node node-one">
            <Server size={22} />
          </div>
          <div className="diagram-node node-two">
            <Database size={21} />
          </div>
          <div className="diagram-core">
            <CloudMark />
          </div>
          <div className="diagram-node node-three">
            <ShieldCheck size={22} />
          </div>
          <div className="diagram-label">CLARITY → CONFIDENCE</div>
        </div>
      </section>
      <div className="section-heading">
        <h2>Workspace health</h2>
        <span>
          <span className="live-indicator" />
          Live from your API · refreshes every 15s
        </span>
      </div>
      <div className="status-grid">
        <article className="status-card">
          <div className="status-card-top">
            <span className="card-icon blue">
              <Server size={19} />
            </span>
            <span className="status-badge good">
              <span />
              Connected
            </span>
          </div>
          <h3>Backend API</h3>
          <div className="status-value">
            Online <Radio size={18} />
          </div>
          <p>Receiving live system information</p>
        </article>
        <article className="status-card">
          <div className="status-card-top">
            <span className="card-icon violet">
              <Database size={19} />
            </span>
            <span className={`status-badge ${databaseReady ? 'good' : 'warning'}`}>
              <span />
              {databaseReady ? 'Connected' : 'Unavailable'}
            </span>
          </div>
          <h3>PostgreSQL</h3>
          <div className="status-value">{databaseReady ? 'Ready' : 'Needs attention'}</div>
          <p>{databaseReady ? 'Database connection verified' : 'Check your database connection'}</p>
        </article>
        <article className="status-card">
          <div className="status-card-top">
            <span className="card-icon teal">
              <Box size={19} />
            </span>
            <span className="environment-badge">{info.environment}</span>
          </div>
          <h3>Application version</h3>
          <div className="status-value version">v{info.version}</div>
          <p>{info.name} · application foundation</p>
        </article>
      </div>
      <div className="middle-grid">
        <section className="panel readiness-panel">
          <div className="panel-heading">
            <h2>Infrastructure readiness</h2>
            <ShieldCheck size={19} className="muted" />
          </div>
          <div className="readiness-summary">
            <span className={`readiness-icon ${databaseReady ? 'ready' : 'degraded'}`}>
              {databaseReady ? <Check size={23} /> : <TriangleAlert size={23} />}
            </span>
            <div>
              <h3>
                {databaseReady ? 'Your foundation is ready' : 'Database connection needs attention'}
              </h3>
              <p>
                {databaseReady
                  ? 'Core services are connected and responding.'
                  : 'Backend is online. PostgreSQL is not responding.'}
              </p>
            </div>
          </div>
          <div className="service-row">
            <span>
              <Server size={16} />
              Backend service
            </span>
            <span className="service-state">
              <Check size={14} />
              Available
            </span>
          </div>
          <div className="service-row">
            <span>
              <Database size={16} />
              PostgreSQL connection
            </span>
            <span className={`service-state ${databaseReady ? '' : 'text-warning'}`}>
              {databaseReady ? <Check size={14} /> : <Circle size={12} />}
              {databaseReady ? 'Available' : 'Unavailable'}
            </span>
          </div>
          <div className="service-row">
            <span>
              <Box size={16} />
              Cloud integrations
            </span>
            <span className="muted">Not configured</span>
          </div>
        </section>
        <section className="panel next-panel">
          <div className="panel-heading">
            <h2>What’s next</h2>
            <span className="subtle-pill">THE ROAD AHEAD</span>
          </div>
          <div className="next-step">
            <span className="step-number">01</span>
            <div>
              <h3>Connect your infrastructure</h3>
              <p>Bring in resource and utilization data.</p>
              <span className="planned-label">Planned · data collection</span>
            </div>
          </div>
          <div className="next-step">
            <span className="step-number">02</span>
            <div>
              <h3>Discover opportunities</h3>
              <p>Turn real observations into better decisions.</p>
              <span className="planned-label">Planned · optimization engine</span>
            </div>
          </div>
          <Link to="/agent" className="text-link">
            Meet your future AI copilot <ArrowRight size={15} />
          </Link>
        </section>
      </div>
      <div className="section-heading">
        <h2>Built for the way you operate</h2>
        <span>Coming to your workspace</span>
      </div>
      <div className="module-grid">
        {modules.map(({ title, description, icon: Icon, path, stage }) => (
          <Link className="module-card" to={path} key={path}>
            <div className="module-card-heading">
              <Icon size={21} />
              <ArrowUpRight size={17} />
            </div>
            <h3>{title}</h3>
            <p>{description}</p>
            <span className="planned-label">{stage} · PLANNED</span>
          </Link>
        ))}
      </div>
      <div className="bottom-note">
        <ShieldCheck size={16} />
        <p>Real status. No simulated savings. Optimization starts when your data is connected.</p>
        <a href="/docs" target="_blank" rel="noreferrer">
          View API <ArrowUpRight size={14} />
        </a>
      </div>
    </>
  );
}

function CloudMark() {
  return (
    <svg width="56" height="44" viewBox="0 0 56 44" fill="none">
      <path
        d="M16 34H40C54 34 54 14 41 14C38 0 17 0 13 15C0 17 3 34 16 34Z"
        stroke="currentColor"
        strokeWidth="2.5"
      />
      <path
        d="M22 24L27 29L36 19"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
