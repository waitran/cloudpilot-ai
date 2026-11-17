import { useState } from 'react';
import {
  ArrowUpRight,
  Bot,
  Box,
  ChevronDown,
  ChevronRight,
  Cloud,
  FlaskConical,
  LayoutDashboard,
  Lightbulb,
  Menu,
  Settings,
  ShieldCheck,
  X,
} from 'lucide-react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';

const navigation = [
  { path: '/', label: 'Overview', icon: LayoutDashboard },
  { path: '/resources', label: 'Resources', icon: Box },
  { path: '/recommendations', label: 'Recommendations', icon: Lightbulb },
  { path: '/lab', label: 'Optimization Lab', icon: FlaskConical },
  { path: '/agent', label: 'AI Agent', icon: Bot },
  { path: '/settings', label: 'Settings', icon: Settings },
];

export function Layout() {
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();
  const page = navigation.find((item) => item.path === location.pathname)?.label || 'Workspace';
  return (
    <div className="app-shell">
      <button
        className="mobile-menu icon-button"
        aria-label="Open navigation"
        onClick={() => setMenuOpen(true)}
      >
        <Menu size={22} />
      </button>
      {menuOpen && (
        <button
          className="scrim"
          aria-label="Close navigation overlay"
          onClick={() => setMenuOpen(false)}
        />
      )}
      <aside className={`sidebar ${menuOpen ? 'open' : ''}`}>
        <a className="brand" href="/" aria-label="CloudPilot AI home">
          <span className="brand-symbol">
            <Cloud size={24} strokeWidth={2.2} />
          </span>
          <span>
            CloudPilot<span className="brand-ai">AI</span>
          </span>
        </a>
        <button
          className="close-menu icon-button"
          aria-label="Close navigation"
          onClick={() => setMenuOpen(false)}
        >
          <X size={20} />
        </button>
        <div className="workspace-switch">
          <span className="workspace-avatar">W</span>
          <div>
            <strong>My workspace</strong>
            <span>Local environment</span>
          </div>
          <ChevronDown size={14} />
        </div>
        <div className="nav-caption">WORKSPACE</div>
        <nav aria-label="Main navigation">
          {navigation.map(({ path, label, icon: Icon }) => (
            <NavLink
              key={path}
              to={path}
              end={path === '/'}
              onClick={() => setMenuOpen(false)}
              className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
            >
              <Icon size={18} />
              <span>{label}</span>
              {label === 'AI Agent' && <span className="nav-new">SOON</span>}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="safety-note">
            <ShieldCheck size={20} />
            <strong>Your infrastructure. Your control.</strong>
            <p>Cloud access and automatic changes are not configured.</p>
          </div>
          <a href="/docs" target="_blank" rel="noreferrer" className="docs-link">
            API documentation <ArrowUpRight size={16} />
          </a>
          <div className="profile">
            <span className="workspace-avatar profile-avatar">L</span>
            <div>
              <strong>Local workspace</strong>
              <span>Application foundation</span>
            </div>
            <span className="online-dot" />
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            <span>Workspace</span>
            <ChevronRight size={14} />
            <strong>{page}</strong>
          </div>
          <div className="topbar-label">
            <span className="local-dot" />
            Local development
          </div>
        </header>
        <main id="main-content">
          <Outlet />
        </main>
        <footer className="main-footer">
          <span>CloudPilot AI</span>
          <span>Observe. Validate. Optimize.</span>
        </footer>
      </div>
    </div>
  );
}
