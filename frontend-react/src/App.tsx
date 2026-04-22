import React from 'react';
import { BrowserRouter, Routes, Route, Navigate, NavLink } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';

import Login from './views/Login';
import Home from './views/Home';
import Process from './views/Process';
import InteractionView from './views/InteractionView';
import SimulationRunView from './views/SimulationRunView';
import Ontology from './views/Ontology';
import InsightsView from './views/InsightsView';
import AdminDashboard from './views/AdminDashboard';

const ProtectedRoute = ({ children }: { children: React.ReactNode }) => {
  const { isAuthenticated } = useAuth();
  if (!isAuthenticated) return <Navigate to="/login" />;
  return children;
};

const Navigation: React.FC = () => {
  const { logout, user } = useAuth();
  return (
    <nav className="top-nav">
      <div className="nav-brand">CORTEX</div>

      <div className="nav-links">
        <NavLink to="/" end className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>HOME</NavLink>
        <NavLink to="/process" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>PROCESS</NavLink>
        <NavLink to="/ontology" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>ONTOLOGY</NavLink>
        <NavLink to="/interact" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>INTERACT</NavLink>
        <NavLink to="/simulate" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>SIMULATE</NavLink>
        <NavLink to="/insights" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>INSIGHTS</NavLink>
        {user?.scopes?.includes('admin') && (
          <NavLink to="/admin" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>ADMIN</NavLink>
        )}
      </div>

      <div className="nav-right">
        <span className="user-badge" title={`Logged in as ${user?.username}`}>
          {user?.username}
        </span>
        <button onClick={logout} className="logout-btn">LOGOUT</button>
      </div>

      <style>{`
        .top-nav {
          position: sticky;
          top: 0;
          z-index: 1000;
          padding: 0 2rem;
          height: 60px;
          border-bottom: 2px solid #000;
          background: #fff;
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 1rem;
        }

        .nav-brand {
          font-family: var(--font-mono);
          font-weight: 700;
          letter-spacing: 3px;
          font-size: 1rem;
          white-space: nowrap;
          flex-shrink: 0;
        }

        .nav-links {
          display: flex;
          gap: 0;
          align-items: stretch;
          height: 100%;
        }

        .nav-link {
          display: flex;
          align-items: center;
          padding: 0 1rem;
          font-family: var(--font-mono);
          font-size: 0.78rem;
          font-weight: 600;
          letter-spacing: 1px;
          text-decoration: none;
          color: #000;
          border-left: 1px solid transparent;
          border-right: 1px solid transparent;
          transition: background 0.15s ease, color 0.15s ease;
          white-space: nowrap;
        }

        .nav-link:hover {
          background: #f0f0f0;
          color: #000;
        }

        .nav-link.active {
          background: #000;
          color: #fff;
          border-color: #000;
        }

        .nav-right {
          display: flex;
          align-items: center;
          gap: 0.75rem;
          flex-shrink: 0;
        }

        .user-badge {
          font-family: var(--font-mono);
          font-size: 0.75rem;
          font-weight: 700;
          background: #000;
          color: #fff;
          padding: 0.2rem 0.6rem;
          letter-spacing: 0.5px;
          max-width: 120px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .logout-btn {
          font-family: var(--font-mono);
          font-size: 0.75rem;
          font-weight: 700;
          background: transparent;
          color: #000;
          border: 1.5px solid #000;
          padding: 0.25rem 0.75rem;
          cursor: pointer;
          letter-spacing: 0.5px;
          transition: all 0.15s ease;
          white-space: nowrap;
        }
        .logout-btn:hover {
          background: #000;
          color: #fff;
        }

        @media (max-width: 768px) {
          .top-nav { padding: 0 1rem; height: auto; flex-wrap: wrap; padding: 0.5rem 1rem; }
          .nav-link { padding: 0.4rem 0.6rem; font-size: 0.7rem; }
          .nav-brand { width: 100%; padding: 0.25rem 0; }
        }
      `}</style>
    </nav>
  );
};

const Layout = ({ children }: { children: React.ReactNode }) => (
  <>
    <Navigation />
    {children}
  </>
);

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />

          <Route path="/" element={<ProtectedRoute><Layout><Home /></Layout></ProtectedRoute>} />
          <Route path="/process" element={<ProtectedRoute><Layout><Process /></Layout></ProtectedRoute>} />
          <Route path="/ontology" element={<ProtectedRoute><Layout><Ontology /></Layout></ProtectedRoute>} />
          <Route path="/interact" element={<ProtectedRoute><Layout><InteractionView /></Layout></ProtectedRoute>} />
          <Route path="/simulate" element={<ProtectedRoute><Layout><SimulationRunView /></Layout></ProtectedRoute>} />
          <Route path="/insights" element={<ProtectedRoute><Layout><InsightsView /></Layout></ProtectedRoute>} />
          <Route path="/admin" element={<ProtectedRoute><Layout><AdminDashboard /></Layout></ProtectedRoute>} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
