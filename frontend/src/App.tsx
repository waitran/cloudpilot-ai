import { Link, Route, Routes } from 'react-router-dom';
import { Layout } from './components/Layout';
import { Overview } from './pages/Overview';
import { Planned } from './pages/Planned';
import { Resources } from './pages/Resources';
import { Sources } from './pages/Sources';
import { ResourceDetails } from './pages/ResourceDetails';
import { Settings } from './pages/Settings';

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Overview />} />
        <Route path="resources" element={<Resources />} />
        <Route path="resources/:id" element={<ResourceDetails />} />
        <Route path="sources" element={<Sources />} />
        <Route path="recommendations" element={<Planned page="recommendations" />} />
        <Route path="lab" element={<Planned page="lab" />} />
        <Route path="agent" element={<Planned page="agent" />} />
        <Route path="settings" element={<Settings />} />
        <Route
          path="*"
          element={
            <section className="empty-panel">
              <h1>Page not found</h1>
              <Link className="primary-button" to="/">
                Back to overview
              </Link>
            </section>
          }
        />
      </Route>
    </Routes>
  );
}
