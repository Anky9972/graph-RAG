import React, { useEffect, useState, useRef } from 'react';
import { useAuth } from '../context/AuthContext';
import { Network, Server, Cpu, Database, Activity, ArrowRight, Zap, GitBranch, MessageSquare, TrendingUp, RefreshCw } from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

// Animated counter hook
function useCountUp(target: number, duration = 1200) {
  const [val, setVal] = useState(0);
  const prev = useRef(0);
  useEffect(() => {
    if (target === 0) { setVal(0); return; }
    const start = prev.current;
    const diff = target - start;
    const startTime = performance.now();
    const tick = (now: number) => {
      const t = Math.min((now - startTime) / duration, 1);
      const ease = 1 - Math.pow(1 - t, 3);
      setVal(Math.round(start + diff * ease));
      if (t < 1) requestAnimationFrame(tick);
      else prev.current = target;
    };
    requestAnimationFrame(tick);
  }, [target]);
  return val;
}

const StatCounter: React.FC<{ value: number | string; label: string; suffix?: string }> = ({ value, label, suffix = '' }) => {
  const numVal = typeof value === 'number' ? value : parseInt(String(value)) || 0;
  const animated = useCountUp(numVal);
  return (
    <div className="hm-stat-block">
      <div className="hm-stat-value">{typeof value === 'number' ? animated : value}{suffix}</div>
      <div className="hm-stat-key">{label}</div>
    </div>
  );
};

const Home: React.FC = () => {
  const { token, logout, user } = useAuth();
  const [health, setHealth] = useState<any>(null);
  const [stats, setStats] = useState<any>(null);
  const [myStats, setMyStats] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());

  const fetchData = async () => {
    setLoading(true);
    try {
      const [healthRes, statsRes, myStatsRes] = await Promise.all([
        fetch(`${API_BASE}/system/health`),
        fetch(`${API_BASE}/system/stats`, { headers: { Authorization: `Bearer ${token}` } }),
        fetch(`${API_BASE}/system/my-stats`, { headers: { Authorization: `Bearer ${token}` } }).catch(() => null),
      ]);
      if (statsRes.status === 401) { logout(); return; }
      if (healthRes.ok) setHealth(await healthRes.json());
      if (statsRes.ok) setStats(await statsRes.json());
      if (myStatsRes?.ok) setMyStats(await myStatsRes.json());
    } catch (err) {
      console.error('Failed to fetch system data', err);
    } finally {
      setLoading(false);
      setLastRefresh(new Date());
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [token]);

  const isOnline = (v: boolean | undefined) => v === true;

  const systemOk = health ? (isOnline(health.neo4j_connected) && isOnline(health.redis_connected)) : false;

  return (
    <div className="container fade-in max-w-[1300px] pb-12">

      {/* ── Hero ─────────────────────────────────────── */}
      <div className="hm-hero">
        <div className="hm-hero-left">
          <div className="hm-hero-label">CORTEX PLATFORM</div>
          <h1 className="hm-hero-title">
            Agentic Knowledge<br />
            <span className="hm-hero-accent">Intelligence</span>
          </h1>
          <p className="hm-hero-sub">
            Production-grade knowledge graph · Real-time extraction · Multi-hop reasoning
          </p>
          <div className="hm-hero-ctas">
            <a href="/process" className="hm-cta-primary">
              <Database size={16} /> Ingest Documents <ArrowRight size={14} />
            </a>
            <a href="/interact" className="hm-cta-secondary">
              <Cpu size={16} /> Query Graph <ArrowRight size={14} />
            </a>
          </div>
        </div>

        <div className="hm-hero-right">
          <div className={`hm-system-badge ${systemOk ? 'ok' : 'warn'}`}>
            <span className={`hm-pulse-dot ${systemOk ? 'green' : 'yellow'}`} />
            <span className="hm-badge-label">
              {loading ? 'CHECKING...' : systemOk ? 'SYSTEM OPERATIONAL' : 'SYSTEM DEGRADED'}
            </span>
            <button className="hm-refresh-btn" onClick={fetchData} title="Refresh">
              <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
            </button>
          </div>

          <div className="hm-infra-stack">
            {[
              { label: 'NEO4J', ok: isOnline(health?.neo4j_connected) },
              { label: 'REDIS', ok: isOnline(health?.redis_connected) },
              { label: `${health?.workers_active ?? 0} WORKERS`, ok: true, neutral: true },
              { label: 'API', ok: true },
            ].map(s => (
              <div key={s.label} className="hm-infra-row">
                <span className={`hm-dot ${s.neutral ? 'neutral' : s.ok ? 'online' : 'offline'}`} />
                <span className="hm-infra-name">{s.label}</span>
                <span className={`hm-infra-badge ${s.neutral ? 'neutral' : s.ok ? 'ok' : 'fail'}`}>
                  {s.neutral ? 'ACTIVE' : s.ok ? 'CONNECTED' : 'OFFLINE'}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── Platform Metrics ─────────────────────────── */}
      <div className="hm-section">
        <div className="hm-section-label">PLATFORM METRICS</div>
        <div className="hm-metrics-row">
          <StatCounter value={stats?.documents_count ?? 0} label="DOCUMENTS" />
          <div className="hm-metric-divider" />
          <StatCounter value={stats?.entities_count ?? 0} label="ENTITIES" />
          <div className="hm-metric-divider" />
          <StatCounter value={stats?.relationships_count ?? 0} label="RELATIONSHIPS" />
          <div className="hm-metric-divider" />
          <StatCounter value={stats?.chunks_count ?? 0} label="CHUNKS" />
          <div className="hm-metric-divider" />
          <div className="hm-stat-block">
            <div className="hm-stat-value text-2xl">
              {stats?.ontology_version ?? '—'}
            </div>
            <div className="hm-stat-key">ONTOLOGY VER</div>
          </div>
        </div>
      </div>

      {/* ── Main Grid ────────────────────────────────── */}
      <div className="hm-main-grid">

        {/* Quick Actions */}
        <div className="hm-card hm-actions-card">
          <div className="hm-card-head">
            <Activity size={16} /> QUICK ACTIONS
          </div>
          <div className="hm-action-list">
            {[
              { href: '/process',  icon: <Database size={18}/>,  label: 'INGEST DOCUMENTS',  desc: 'Upload PDFs, text, or crawl URLs' },
              { href: '/interact', icon: <Cpu size={18}/>,       label: 'QUERY KNOWLEDGE',   desc: 'Ask questions across the graph' },
              { href: '/simulate', icon: <Network size={18}/>,   label: 'EXPLORE NODES',     desc: 'Interactive D3 force visualization' },
              { href: '/ontology', icon: <Server size={18}/>,    label: 'MANAGE ONTOLOGY',   desc: 'Edit schema & run AI refinement' },
              { href: '/insights', icon: <TrendingUp size={18}/>,label: 'INSIGHTS',           desc: 'Quality metrics & AI reports' },
            ].map(a => (
              <a key={a.href} href={a.href} className="hm-action-item">
                <span className="hm-action-icon">{a.icon}</span>
                <div className="hm-action-text">
                  <div className="hm-action-label">{a.label}</div>
                  <div className="hm-action-desc">{a.desc}</div>
                </div>
                <ArrowRight size={14} className="hm-action-arrow" />
              </a>
            ))}
          </div>
        </div>

        {/* Right column: My Activity + Feature cards */}
        <div className="flex flex-col gap-6">

          {/* User Activity */}
          <div className="hm-card">
            <div className="hm-card-head">
              <MessageSquare size={16} /> MY ACTIVITY
              {user && <span className="ml-auto font-mono text-[0.7rem] text-[#666666]">@{user.username}</span>}
            </div>
            <div className="hm-activity-grid">
              <div className="hm-activity-chip">
                <div className="hm-activity-val">{myStats?.conversation_count ?? '—'}</div>
                <div className="hm-activity-key">CONVERSATIONS</div>
              </div>
              <div className="hm-activity-chip">
                <div className="hm-activity-val">{myStats?.message_count ?? '—'}</div>
                <div className="hm-activity-key">QUERIES SENT</div>
              </div>
              <div className="hm-activity-chip">
                <div className="hm-activity-val">{myStats?.last_active ? new Date(myStats.last_active).toLocaleDateString() : '—'}</div>
                <div className="hm-activity-key">LAST ACTIVE</div>
              </div>
            </div>
            {!myStats && (
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem', color: 'var(--muted-color)', marginTop: '0.75rem' }}>
                Start querying the graph to build your activity history.
              </div>
            )}
          </div>

          {/* Graph intelligence card */}
          <div className="hm-card hm-graph-card">
            <div className="hm-card-head">
              <GitBranch size={16} /> KNOWLEDGE GRAPH
            </div>
            <div style={{ fontSize: '0.85rem', lineHeight: 1.7, color: 'var(--muted-color)', marginBottom: '1rem' }}>
              Neo4j-powered semantic knowledge graph. Multi-hop reasoning, entity enrichment, and community detection built in.
            </div>
            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
              {['Entities', 'Relationships', 'Communities', 'Graph Export'].map(tag => (
                <span key={tag} className="hm-tag">{tag}</span>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* ── Feature Showcase ─────────────────────────── */}
      <div className="hm-features-section">
        <div className="hm-section-label" style={{ marginBottom: '1.5rem' }}>PLATFORM CAPABILITIES</div>
        <div className="hm-features-grid">
          {[
            {
              icon: <Database size={24}/>,
              title: 'DOCUMENT INGESTION',
              desc: 'Ingest PDFs, text files, Markdown, and web URLs. Celery workers extract entities and relationships into the knowledge graph automatically via LLM pipelines.',
              color: '#2563eb',
            },
            {
              icon: <Network size={24}/>,
              title: 'GRAPH INTELLIGENCE',
              desc: 'Neo4j-powered knowledge graph with rich entity relationships. Query across documents globally or per-source with full ontology control.',
              color: '#7c3aed',
            },
            {
              icon: <Cpu size={24}/>,
              title: 'AGENTIC LOGIC',
              desc: 'Multi-step ReACT reasoning agent that searches the graph, retrieves relevant chunks, and streams answers with confidence scoring in real time.',
              color: '#059669',
            },
            {
              icon: <Zap size={24}/>,
              title: 'LLM-AS-JUDGE',
              desc: 'Inline faithfulness evaluation using heuristic scoring. Detects hallucination risk, context precision, and answer quality on every response.',
              color: '#d97706',
            },
            {
              icon: <Activity size={24}/>,
              title: 'LIVE SIMULATION',
              desc: 'Interactive D3 force graph with color-coded entity types, physics controls, fullscreen mode, PNG export, and node detail modals.',
              color: '#dc2626',
            },
            {
              icon: <TrendingUp size={24}/>,
              title: 'ONTOLOGY DRIFT',
              desc: 'Automated schema drift detection that spots when new data no longer fits the current ontology. Propose and approve schema expansions.',
              color: '#0891b2',
            },
          ].map(f => (
            <div key={f.title} className="hm-feature-card" style={{ '--feature-color': f.color } as any}>
              <div className="hm-feature-icon" style={{ color: f.color }}>{f.icon}</div>
              <div className="hm-feature-title">{f.title}</div>
              <div className="hm-feature-desc">{f.desc}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Footer bar */}
      <div className="hm-footer-bar">
        <span className="hm-footer-brand">CORTEX_PLATFORM</span>
        <span style={{ color: 'var(--muted-color)', fontSize: '0.72rem', fontFamily: 'var(--font-mono)' }}>
          Last refreshed: {lastRefresh.toLocaleTimeString()}
        </span>
        <span style={{ color: 'var(--muted-color)', fontSize: '0.72rem', fontFamily: 'var(--font-mono)' }}>
          v{health ? '1.0' : '—'} · Neo4j + Redis + Celery
        </span>
      </div>

      <style>{`
        /* ── Hero ── */
        .hm-hero {
          display: grid;
          grid-template-columns: 1fr 320px;
          gap: 2rem;
          padding: 2.5rem 0 2rem;
          border-bottom: 3px solid #000;
          margin-bottom: 2.5rem;
          align-items: center;
        }
        .hm-hero-label {
          font-family: var(--font-mono);
          font-size: 0.72rem;
          font-weight: 700;
          letter-spacing: 3px;
          color: var(--muted-color);
          margin-bottom: 0.75rem;
        }
        .hm-hero-title {
          font-family: var(--font-display);
          font-size: clamp(2rem, 4vw, 3rem);
          font-weight: 800;
          line-height: 1.1;
          margin-bottom: 0.75rem;
          letter-spacing: -0.5px;
        }
        .hm-hero-accent {
          position: relative;
          display: inline-block;
        }
        .hm-hero-accent::after {
          content: '';
          position: absolute;
          left: 0; bottom: 2px;
          width: 100%; height: 4px;
          background: #000;
        }
        .hm-hero-sub {
          color: var(--muted-color);
          font-size: 0.95rem;
          line-height: 1.6;
          margin-bottom: 1.5rem;
          max-width: 480px;
        }
        .hm-hero-ctas {
          display: flex;
          gap: 0.75rem;
          flex-wrap: wrap;
        }
        .hm-cta-primary {
          display: inline-flex;
          align-items: center;
          gap: 0.5rem;
          background: #000;
          color: #fff;
          padding: 0.65rem 1.25rem;
          font-family: var(--font-mono);
          font-size: 0.8rem;
          font-weight: 700;
          letter-spacing: 0.5px;
          text-decoration: none;
          transition: background 0.15s, transform 0.15s;
          border: 2px solid #000;
        }
        .hm-cta-primary:hover {
          background: #333;
          color: #fff;
          transform: translateY(-1px);
          box-shadow: 3px 3px 0 rgba(0,0,0,0.2);
        }
        .hm-cta-secondary {
          display: inline-flex;
          align-items: center;
          gap: 0.5rem;
          background: transparent;
          color: #000;
          padding: 0.65rem 1.25rem;
          font-family: var(--font-mono);
          font-size: 0.8rem;
          font-weight: 700;
          letter-spacing: 0.5px;
          text-decoration: none;
          border: 2px solid #000;
          transition: background 0.15s, transform 0.15s;
        }
        .hm-cta-secondary:hover {
          background: #000;
          color: #fff;
          transform: translateY(-1px);
        }

        /* System badge */
        .hm-system-badge {
          display: flex;
          align-items: center;
          gap: 0.6rem;
          border: 2px solid #000;
          padding: 0.5rem 0.85rem;
          margin-bottom: 1rem;
          font-family: var(--font-mono);
          font-size: 0.72rem;
          font-weight: 700;
          letter-spacing: 1px;
        }
        .hm-system-badge.warn { border-color: #d97706; color: #d97706; }
        .hm-pulse-dot {
          width: 8px; height: 8px;
          border-radius: 50%;
          flex-shrink: 0;
          animation: pulseGlow 2s ease-in-out infinite;
        }
        .hm-pulse-dot.green { background: #16a34a; box-shadow: 0 0 0 0 rgba(22,163,74,0.4); }
        .hm-pulse-dot.yellow { background: #d97706; box-shadow: 0 0 0 0 rgba(217,119,6,0.4); }
        @keyframes pulseGlow {
          0%, 100% { box-shadow: 0 0 0 0 rgba(22,163,74,0.4); }
          50% { box-shadow: 0 0 0 5px rgba(22,163,74,0); }
        }
        .hm-badge-label { flex: 1; }
        .hm-refresh-btn {
          background: none;
          border: none;
          cursor: pointer;
          padding: 0;
          color: var(--muted-color);
          display: flex;
          align-items: center;
          transition: color 0.15s;
        }
        .hm-refresh-btn:hover { color: #000; background: none; }

        /* Infra stack */
        .hm-infra-stack { display: flex; flex-direction: column; gap: 0.5rem; }
        .hm-infra-row {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          padding: 0.4rem 0.6rem;
          border: 1.5px solid #e5e5e5;
          font-family: var(--font-mono);
          font-size: 0.78rem;
        }
        .hm-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
        .hm-dot.online { background: #16a34a; }
        .hm-dot.offline { background: #dc2626; }
        .hm-dot.neutral { background: #9ca3af; }
        .hm-infra-name { flex: 1; font-weight: 600; color: var(--muted-color); }
        .hm-infra-badge {
          font-size: 0.65rem;
          font-weight: 700;
          padding: 1px 6px;
          letter-spacing: 0.5px;
        }
        .hm-infra-badge.ok { background: #dcfce7; color: #16a34a; }
        .hm-infra-badge.fail { background: #fee2e2; color: #dc2626; }
        .hm-infra-badge.neutral { background: #f3f4f6; color: #6b7280; }

        /* ── Section label ── */
        .hm-section { margin-bottom: 2.5rem; }
        .hm-section-label {
          font-family: var(--font-mono);
          font-size: 0.68rem;
          font-weight: 700;
          letter-spacing: 3px;
          color: var(--muted-color);
          margin-bottom: 1rem;
        }

        /* ── Metrics row ── */
        .hm-metrics-row {
          display: flex;
          align-items: center;
          border: 3px solid #000;
          overflow: hidden;
        }
        .hm-stat-block {
          flex: 1;
          min-width: 0;
          padding: 1.25rem 1.5rem;
          text-align: center;
        }
        .hm-stat-value {
          font-family: var(--font-mono);
          font-size: 2.2rem;
          font-weight: 900;
          line-height: 1;
          margin-bottom: 0.3rem;
        }
        .hm-stat-key {
          font-family: var(--font-mono);
          font-size: 0.6rem;
          color: var(--muted-color);
          letter-spacing: 1.5px;
          font-weight: 700;
        }
        .hm-metric-divider {
          width: 1px;
          height: 60px;
          background: #000;
          flex-shrink: 0;
        }

        /* ── Main grid ── */
        .hm-main-grid {
          display: grid;
          grid-template-columns: 1fr 360px;
          gap: 1.5rem;
          margin-bottom: 3rem;
        }

        /* ── Card base ── */
        .hm-card {
          border: 2px solid #000;
          padding: 1.5rem;
          background: #fff;
          transition: transform 0.15s, box-shadow 0.15s;
        }
        .hm-card:hover {
          transform: translateY(-2px);
          box-shadow: 4px 4px 0 #000;
        }
        .hm-card-head {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          font-family: var(--font-mono);
          font-size: 0.72rem;
          font-weight: 700;
          letter-spacing: 1.5px;
          margin-bottom: 1.25rem;
          padding-bottom: 0.75rem;
          border-bottom: 2px solid #000;
        }

        /* ── Actions ── */
        .hm-actions-card {
          background: #fafafa;
        }
        .hm-action-list { display: flex; flex-direction: column; gap: 0.4rem; }
        .hm-action-item {
          display: flex;
          align-items: center;
          gap: 0.75rem;
          padding: 0.7rem 0.75rem;
          border: 1.5px solid #e5e5e5;
          text-decoration: none;
          color: #000;
          transition: all 0.15s;
          background: #fff;
        }
        .hm-action-item:hover {
          background: #000;
          color: #fff;
          border-color: #000;
          transform: translateX(3px);
          box-shadow: -3px 3px 0 rgba(0,0,0,0.1);
        }
        .hm-action-icon {
          width: 36px; height: 36px;
          display: flex; align-items: center; justify-content: center;
          background: #000;
          color: #fff;
          flex-shrink: 0;
          transition: background 0.15s;
        }
        .hm-action-item:hover .hm-action-icon { background: #fff; color: #000; }
        .hm-action-text { flex: 1; min-width: 0; }
        .hm-action-label {
          font-family: var(--font-mono);
          font-size: 0.8rem;
          font-weight: 700;
          letter-spacing: 0.5px;
        }
        .hm-action-desc {
          font-size: 0.75rem;
          color: var(--muted-color);
          margin-top: 0.1rem;
        }
        .hm-action-item:hover .hm-action-desc { color: rgba(255,255,255,0.7); }
        .hm-action-arrow { flex-shrink: 0; transition: transform 0.15s; }
        .hm-action-item:hover .hm-action-arrow { transform: translateX(3px); }

        /* ── Activity ── */
        .hm-activity-grid {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 0.75rem;
        }
        .hm-activity-chip {
          border: 1.5px solid #e5e5e5;
          padding: 0.75rem 0.5rem;
          text-align: center;
        }
        .hm-activity-val {
          font-family: var(--font-mono);
          font-size: 1.3rem;
          font-weight: 900;
          line-height: 1;
          margin-bottom: 0.25rem;
        }
        .hm-activity-key {
          font-family: var(--font-mono);
          font-size: 0.58rem;
          color: var(--muted-color);
          letter-spacing: 1px;
          font-weight: 700;
        }

        /* ── Graph card ── */
        .hm-graph-card {}
        .hm-tag {
          display: inline-block;
          background: #f3f4f6;
          border: 1.5px solid #e5e5e5;
          font-family: var(--font-mono);
          font-size: 0.68rem;
          font-weight: 700;
          padding: 2px 8px;
          letter-spacing: 0.5px;
        }

        /* ── Features ── */
        .hm-features-section {
          border-top: 3px solid #000;
          padding-top: 2.5rem;
          margin-bottom: 2rem;
        }
        .hm-features-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
          gap: 1rem;
        }
        .hm-feature-card {
          border: 2px solid #e5e5e5;
          padding: 1.5rem;
          transition: border-color 0.2s, box-shadow 0.2s, transform 0.2s;
          position: relative;
          overflow: hidden;
        }
        .hm-feature-card::before {
          content: '';
          position: absolute;
          left: 0; top: 0; bottom: 0;
          width: 3px;
          background: var(--feature-color, #000);
          opacity: 0;
          transition: opacity 0.2s;
        }
        .hm-feature-card:hover {
          border-color: #000;
          box-shadow: 4px 4px 0 #000;
          transform: translateY(-2px);
        }
        .hm-feature-card:hover::before { opacity: 1; }
        .hm-feature-icon {
          margin-bottom: 0.85rem;
          transition: transform 0.2s;
        }
        .hm-feature-card:hover .hm-feature-icon { transform: scale(1.1); }
        .hm-feature-title {
          font-family: var(--font-mono);
          font-size: 0.72rem;
          font-weight: 700;
          letter-spacing: 1px;
          margin-bottom: 0.5rem;
        }
        .hm-feature-desc {
          font-size: 0.82rem;
          color: var(--muted-color);
          line-height: 1.65;
        }

        /* ── Footer ── */
        .hm-footer-bar {
          display: flex;
          align-items: center;
          gap: 1.5rem;
          border-top: 1px solid #e5e5e5;
          padding-top: 1.25rem;
          margin-top: 1rem;
        }
        .hm-footer-brand {
          font-family: var(--font-mono);
          font-size: 0.72rem;
          font-weight: 700;
          letter-spacing: 2px;
          margin-right: auto;
        }

        /* ── Responsive ── */
        @media (max-width: 900px) {
          .hm-hero { grid-template-columns: 1fr; }
          .hm-hero-right { order: -1; }
          .hm-main-grid { grid-template-columns: 1fr; }
          .hm-metrics-row { flex-wrap: wrap; }
          .hm-metric-divider { display: none; }
          .hm-stat-block { flex: 0 0 50%; border-bottom: 1px solid #000; }
        }
      `}</style>
    </div>
  );
};

export default Home;
