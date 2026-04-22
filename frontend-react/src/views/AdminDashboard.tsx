import React, { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../context/AuthContext';
import {
  BarChart2, Cpu, Users, Database, Settings,
  Trash2, Check, X, Play, RefreshCw, Shield,
  AlertTriangle, Zap, GitBranch, Info
} from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

// ─── Helpers ──────────────────────────────────────────────────────────────────
const Spinner = () => (
  <span className="inline-block w-[14px] h-[14px] border-2 border-[#ccc] border-t-black rounded-full animate-spin"/>
);

// ─── Tab Components ──────────────────────────────────────────────────────────

const OverviewTab = ({ stats, health, onRefresh }: { stats: any; health: any; onRefresh: () => void }) => (
  <div>
    {/* KPI Grid */}
    <div className="grid grid-cols-[repeat(auto-fit,minmax(180px,1fr))] gap-4 mb-8">
      {[
        { label:'Graph Nodes', value: stats?.graph?.nodes ?? stats?.total_nodes ?? '—', icon:<Database size={16}/> },
        { label:'Relationships', value: stats?.graph?.relationships ?? stats?.total_relationships ?? '—', icon:<GitBranch size={16}/> },
        { label:'Documents', value: stats?.documents?.total ?? stats?.total_documents ?? '—', icon:<Database size={16}/> },
        { label:'Est. LLM Cost', value: `$${(stats?.costs?.total_estimated_usd ?? 0).toFixed(4)}`, icon:<BarChart2 size={16}/> },
      ].map(c => (
        <div key={c.label} className="status-card">
          <div className="flex justify-between items-center mb-2">
            <div className="status-label">{c.label}</div>
            {c.icon}
          </div>
          <div className="metric-value">{c.value}</div>
        </div>
      ))}
    </div>

    {/* System health */}
    <div className="card mb-6">
      <div className="flex justify-between items-center mb-4">
        <h2 className="title-md">System Health</h2>
        <button className="btn btn-outline py-1 px-3 text-xs" onClick={onRefresh}>
          <RefreshCw size={13}/> Refresh
        </button>
      </div>
      {health ? (
        <div className="grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-3">
          {Object.entries(health).map(([k, v]: [string, any]) => {
            const isOk = v === true || v === 'ok' || v === 'connected' || v === 'healthy';
            const isErr = v === false || v === 'error' || v === 'disconnected';
            return (
              <div key={k} className="border-[1.5px] border-[#e5e5e5] py-2.5 px-3.5 flex items-center gap-2">
                <span className={`indicator ${isOk ? 'online' : isErr ? 'offline' : 'pending'}`}/>
                <div>
                  <div className="status-label">{k.toUpperCase()}</div>
                  <div className="font-mono text-[0.8rem] font-bold">
                    {typeof v === 'object' ? JSON.stringify(v) : String(v)}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="text-center p-6 text-[var(--muted-color)] font-mono text-[0.85rem]">
          Loading health data…
        </div>
      )}
    </div>

    {/* Provider info */}
    {stats?.system && (
      <div className="card">
        <h2 className="title-md mb-4">LLM Provider</h2>
        <div className="flex gap-4 flex-wrap">
          {Object.entries(stats.system).map(([k, v]: any) => (
            <div key={k} className="chip">{k}: <strong>{String(v)}</strong></div>
          ))}
        </div>
      </div>
    )}
  </div>
);

const UsersTab = ({ token }: { token: string | null }) => {
  const [users, setUsers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState('');

  const fetchUsers = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/admin/users`, { headers: { Authorization: `Bearer ${token}` } });
      if (res.ok) {
        const json = await res.json();
        setUsers(json.users || []);
      }
    } finally { setLoading(false); }
  }, [token]);

  useEffect(() => { fetchUsers(); }, [fetchUsers]);

  const updateRole = async (username: string, scopes: string) => {
    const res = await fetch(`${API_BASE}/admin/users/${username}/role`, {
      method: 'PUT',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ scopes: [scopes] })
    });
    if (res.ok) {
      setUsers(u => u.map(usr => usr.username === username ? { ...usr, scopes: [scopes] } : usr));
      setMsg(`Role updated for ${username}`);
      setTimeout(() => setMsg(''), 3000);
    } else {
      setMsg(`Failed to update role for ${username}`);
      setTimeout(() => setMsg(''), 3000);
    }
  };

  return (
    <div className="card">
      <div className="flex justify-between items-center mb-4">
        <h2 className="title-md">Registered Users</h2>
        <button className="btn btn-outline py-1 px-3 text-xs" onClick={fetchUsers}>
          <RefreshCw size={13}/> Refresh
        </button>
      </div>
      {msg && <div className="bg-[#dcfce7] text-[#166534] py-2 px-3 mb-4 font-mono text-[0.8rem]">{msg}</div>}
      {loading ? (
        <div className="text-center p-8"><Spinner/></div>
      ) : (
        <div className="overflow-x-auto">
          <table className="data-table">
            <thead><tr><th>Username</th><th>Scope</th><th>Change Role</th></tr></thead>
            <tbody>
              {users.map(u => {
                const isAdminUser = u.username === 'admin';
                const currentScope = u.scopes?.includes('admin') ? 'admin' : (u.scopes?.includes('write') ? 'write' : 'read');
                return (
                  <tr key={u.username}>
                    <td className="font-mono font-semibold">
                      {u.username}
                      {isAdminUser && <span className="chip filled ml-1.5 text-[0.62rem]">PROTECTED</span>}
                    </td>
                    <td><span className="chip">{u.scopes?.join(', ') || 'none'}</span></td>
                    <td>
                      {isAdminUser ? (
                        <span className="font-mono text-xs text-[var(--muted-color)]">—</span>
                      ) : (
                        <select
                          className="search-input w-auto py-1 px-2 text-[0.82rem]"
                          value={currentScope}
                          onChange={e => updateRole(u.username, e.target.value)}
                        >
                          <option value="read">Read Only</option>
                          <option value="write">Read / Write</option>
                          <option value="admin">Admin</option>
                        </select>
                      )}
                    </td>
                  </tr>
                );
              })}
              {users.length === 0 && (
                <tr><td colSpan={3} className="text-center p-8 text-[var(--muted-color)]">No users found.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

const DocumentsTab = ({ token }: { token: string | null }) => {
  const [docs, setDocs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState('');

  const fetchDocs = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/admin/documents`, { headers: { Authorization: `Bearer ${token}` } });
      if (res.ok) {
        const json = await res.json();
        setDocs(json.documents || []);
      }
    } finally { setLoading(false); }
  }, [token]);

  useEffect(() => { fetchDocs(); }, [fetchDocs]);

  const deleteDoc = async (id: string, filename: string) => {
    if (!window.confirm(`Delete "${filename}" and all its graph data? This cannot be undone.`)) return;
    const res = await fetch(`${API_BASE}/admin/documents/${id}`, { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } });
    if (res.ok) {
      setDocs(d => d.filter(doc => doc.id !== id));
      setMsg('Document deleted.');
      setTimeout(() => setMsg(''), 3000);
    }
  };

  const reIngestDoc = async (id: string, filename: string) => {
    setMsg(`Re-ingesting "${filename}"...`);
    try {
      const res = await fetch(`${API_BASE}/admin/documents/${id}/reingest`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setMsg(`Re-ingestion queued for "${filename}". Task: ${data.task_id?.slice(0,8)}…`);
        setTimeout(() => { setMsg(''); fetchDocs(); }, 5000);
      } else {
        setMsg(`Failed to re-ingest "${filename}"`);
        setTimeout(() => setMsg(''), 3000);
      }
    } catch {
      setMsg('Network error during re-ingest.');
      setTimeout(() => setMsg(''), 3000);
    }
  };

  return (
    <div className="card">
      <div className="flex justify-between items-center mb-4">
        <h2 className="title-md">Document Vault</h2>
        <span className="font-mono text-xs text-[var(--muted-color)]">{docs.length} documents</span>
      </div>
      {msg && <div className={`py-2 px-3 mb-4 font-mono text-[0.8rem] ${(msg.includes('Failed') || msg.includes('error')) ? 'bg-[#fef2f2] text-[#dc2626]' : 'bg-[#dcfce7] text-[#166534]'}`}>{msg}</div>}
      {loading ? (
        <div className="text-center p-8"><Spinner/></div>
      ) : (
        <div className="overflow-x-auto">
          <table className="data-table">
            <thead><tr><th>ID</th><th>Filename</th><th>Status</th><th>Actions</th></tr></thead>
            <tbody>
              {docs.map(d => (
                <tr key={d.id}>
                  <td className="font-mono text-[0.78rem] text-[var(--muted-color)]">{d.id?.substring(0,12)}…</td>
                  <td className="font-mono font-semibold">{d.filename}</td>
                  <td>
                    <span className={`chip ${d.status === 'completed' ? 'success' : d.status === 'failed' ? 'error' : 'warning'}`}>
                      {d.status || 'unknown'}
                    </span>
                  </td>
                  <td className="flex gap-1.5 flex-wrap">
                    {(d.status === 'failed' || d.status === 'pending') && (
                      <button className="btn text-[0.72rem] py-1 px-2 border-[#2563eb] text-[#2563eb] bg-[#eff6ff]"
                        onClick={() => reIngestDoc(d.id, d.filename)}>
                        <Play size={11}/> Re-Ingest
                      </button>
                    )}
                    <button className="btn btn-danger text-xs py-1 px-2.5" onClick={() => deleteDoc(d.id, d.filename)}>
                      <Trash2 size={12}/> Delete
                    </button>
                  </td>
                </tr>
              ))}
              {docs.length === 0 && (
                <tr><td colSpan={4} className="text-center p-8 text-[var(--muted-color)]">No documents uploaded yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

const GraphCRUDTab = ({ token }: { token: string | null }) => {
  const [nodes, setNodes] = useState<any[]>([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState('');

  const search = async (e?: React.FormEvent) => {
    e?.preventDefault();
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/admin/graph/nodes?query=${encodeURIComponent(query)}&limit=100`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) setNodes((await res.json()).nodes || []);
    } finally { setLoading(false); }
  };

  const deleteNode = async (id: string) => {
    if (!window.confirm('Detach and delete this node?')) return;
    const res = await fetch(`${API_BASE}/admin/graph/nodes/${id}`, {
      method: 'DELETE', headers: { Authorization: `Bearer ${token}` }
    });
    if (res.ok) {
      setNodes(n => n.filter(nd => nd.id !== id));
      setMsg('Node deleted.');
      setTimeout(() => setMsg(''), 3000);
    }
  };

  return (
    <div className="card">
      <h2 className="title-md mb-4">Graph Node Browser</h2>
      <div className="page-info-bar">
        <Info size={14}/>
        <span>Search and inspect nodes directly in Neo4j. Use label names or property values. <strong>DELETE</strong> detaches all relationships before removing the node.</span>
      </div>
      {msg && <div className="bg-[#dcfce7] text-[#166534] py-2 px-3 mb-4 font-mono text-[0.8rem]">{msg}</div>}
      <form onSubmit={search} className="flex gap-3 mb-6">
        <input type="text" value={query} onChange={e => setQuery(e.target.value)}
          placeholder="Search node labels or properties…" className="search-input flex-1"/>
        <button type="submit" className="btn btn-primary" disabled={loading}>
          {loading ? <Spinner/> : null} Search
        </button>
      </form>
      <div className="overflow-x-auto max-h-[420px] overflow-y-auto">
        <table className="data-table">
          <thead><tr><th>ID</th><th>Labels</th><th>Properties</th><th>Action</th></tr></thead>
          <tbody>
            {nodes.map((n, i) => (
              <tr key={i}>
                <td className="font-mono text-[0.78rem] text-[var(--muted-color)]">{n.id}</td>
                <td className="font-mono text-[#2563eb]">{n.labels?.join(', ')}</td>
                <td className="font-mono text-[0.78rem] text-[var(--muted-color)] max-w-[260px] whitespace-nowrap overflow-hidden text-ellipsis">
                  {JSON.stringify(n.properties)}
                </td>
                <td>
                  <button className="btn btn-danger text-xs py-1 px-2.5" onClick={() => deleteNode(n.id)}>
                    <Trash2 size={12}/> Delete
                  </button>
                </td>
              </tr>
            ))}
            {nodes.length === 0 && (
              <tr><td colSpan={4} className="text-center p-8 text-[var(--muted-color)]">
                {loading ? 'Searching…' : 'Enter a search term above to browse nodes.'}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

const OntologyGovernanceTab = ({ token }: { token: string | null }) => {
  const [proposals, setProposals] = useState<any[]>([]);
  const [driftReports, setDriftReports] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [detectLoading, setDetectLoading] = useState(false);
  const [msg, setMsg] = useState('');

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [propRes, driftRes] = await Promise.all([
        fetch(`${API_BASE}/admin/ontology/pending`, { headers: { Authorization: `Bearer ${token}` } }),
        fetch(`${API_BASE}/ontology/drift`, { headers: { Authorization: `Bearer ${token}` } }),
      ]);
      if (propRes.ok) setProposals((await propRes.json()).proposals || []);
      if (driftRes.ok) setDriftReports((await driftRes.json()).reports || []);
    } finally { setLoading(false); }
  }, [token]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleProposal = async (id: string, action: 'approve' | 'reject') => {
    const res = await fetch(`${API_BASE}/admin/ontology/${action}/${id}`, {
      method: 'POST', headers: { Authorization: `Bearer ${token}` }
    });
    if (res.ok) {
      setProposals(p => p.filter(o => o.id !== id));
      setMsg(`Proposal ${action}d.`);
      setTimeout(() => setMsg(''), 3000);
    }
  };

  const handleDrift = async (id: string, action: 'approve' | 'reject') => {
    const res = await fetch(`${API_BASE}/ontology/drift/${id}/${action}`, {
      method: 'POST', headers: { Authorization: `Bearer ${token}` }
    });
    if (res.ok) {
      setDriftReports(d => d.filter(r => r.id !== id));
      setMsg(`Drift report ${action}d.`);
      setTimeout(() => setMsg(''), 3000);
    }
  };

  const detectDrift = async () => {
    setDetectLoading(true);
    try {
      const res = await fetch(`${API_BASE}/ontology/drift/detect`, {
        method: 'POST', headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        setMsg('Drift detection complete. Refreshing…');
        await fetchData();
      }
    } finally {
      setDetectLoading(false);
      setTimeout(() => setMsg(''), 4000);
    }
  };

  return (
    <div>
      {msg && <div className="bg-[#dcfce7] text-[#166534] py-2.5 px-3.5 mb-4 font-mono text-[0.8rem] border border-[#bbf7d0]">{msg}</div>}

      {/* Drift detection */}
      <div className="card mb-6">
        <div className="flex justify-between items-center mb-3">
          <h2 className="title-md">Ontology Drift Reports</h2>
          <button className="btn btn-primary text-[0.8rem]" onClick={detectDrift} disabled={detectLoading}>
            {detectLoading ? <Spinner/> : <Zap size={13}/>} Run Drift Detection
          </button>
        </div>
        <p className="text-[var(--muted-color)] text-[0.85rem] mb-5 font-sans">
          Drift detection samples recent data and suggests additions or changes to the graph schema.
          Review and approve or reject proposals below.
        </p>
        {loading ? <div className="text-center p-6"><Spinner/></div> : (
          <div className="grid gap-3">
            {driftReports.map(r => (
              <div key={r.id} className="border-2 border-black p-4 flex justify-between items-start gap-4">
                <div className="flex-1">
                  <div className="flex gap-2 mb-1.5 flex-wrap">
                    <span className="chip">{r.status || 'pending'}</span>
                    <span className="chip">{r.new_entity_types?.length || 0} new types</span>
                  </div>
                  <p className="font-mono text-[0.78rem] text-[#555] m-0">
                    {r.summary || 'Drift report — review suggested schema changes.'}
                  </p>
                </div>
                <div className="flex gap-2 shrink-0">
                  <button className="btn bg-[#f0fdf4] text-[#16a34a] border-[#16a34a] py-1 px-3 text-[0.78rem]"
                    onClick={() => handleDrift(r.id, 'approve')}><Check size={13}/> Apply</button>
                  <button className="btn bg-[#fef2f2] text-[#dc2626] border-[#dc2626] py-1 px-3 text-[0.78rem]"
                    onClick={() => handleDrift(r.id, 'reject')}><X size={13}/> Reject</button>
                </div>
              </div>
            ))}
            {driftReports.length === 0 && (
              <div className="empty-state p-8">No pending drift reports. Run drift detection above.</div>
            )}
          </div>
        )}
      </div>

      {/* Manual proposals */}
      <div className="card">
        <h2 className="title-md mb-3">Manual Schema Proposals</h2>
        <div className="grid gap-3">
          {proposals.map(o => (
            <div key={o.id} className="border-[1.5px] border-[#e5e5e5] p-3.5 flex justify-between items-center gap-4">
              <div className="flex items-center gap-3">
                <span className="chip">{o.type}</span>
                <span className="font-mono text-[0.85rem]">{o.name}</span>
              </div>
              <div className="flex gap-2">
                <button className="btn bg-[#f0fdf4] text-[#16a34a] border-[#16a34a] py-1 px-3 text-[0.78rem]"
                  onClick={() => handleProposal(o.id, 'approve')}><Check size={13}/> Approve</button>
                <button className="btn bg-[#fef2f2] text-[#dc2626] border-[#dc2626] py-1 px-3 text-[0.78rem]"
                  onClick={() => handleProposal(o.id, 'reject')}><X size={13}/> Reject</button>
              </div>
            </div>
          ))}
          {proposals.length === 0 && (
            <div className="empty-state p-6">No pending manual proposals.</div>
          )}
        </div>
      </div>
    </div>
  );
};

const WorkersTab = ({ token }: { token: string | null }) => {
  const [tasks, setTasks] = useState<any>(null);
  const [health, setHealth] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [taskRes, healthRes] = await Promise.all([
        fetch(`${API_BASE}/admin/tasks`, { headers: { Authorization: `Bearer ${token}` } }),
        fetch(`${API_BASE}/system/health`, { headers: { Authorization: `Bearer ${token}` } }),
      ]);
      if (taskRes.ok) setTasks(await taskRes.json());
      if (healthRes.ok) setHealth(await healthRes.json());
    } finally { setLoading(false); }
  }, [token]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  return (
    <div>
      <div className="card mb-5">
        <div className="flex justify-between items-center mb-4">
          <h2 className="title-md">Celery Worker Status</h2>
          <button className="btn btn-outline text-xs py-1 px-3" onClick={fetchAll}>
            <RefreshCw size={13}/> Refresh
          </button>
        </div>
        {loading ? <div className="text-center p-6"><Spinner/></div> : (
          <div className="grid grid-cols-[repeat(auto-fit,minmax(160px,1fr))] gap-3">
            {[
              { label:'Active Tasks', value: tasks?.active_tasks ?? tasks?.active ?? 0 },
              { label:'Queued Tasks', value: tasks?.queued_tasks ?? tasks?.reserved ?? 0 },
              { label:'Completed', value: tasks?.completed_tasks ?? tasks?.total ?? 0 },
              { label:'Failed', value: tasks?.failed_tasks ?? 0 },
            ].map(m => (
              <div key={m.label} className="status-card">
                <div className="status-label">{m.label}</div>
                <div className="metric-value text-2xl">{m.value}</div>
              </div>
            ))}
          </div>
        )}
      </div>
      {health && (
        <div className="card">
          <h2 className="title-md mb-3">Service Health</h2>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-2.5">
            {Object.entries(health).map(([k, v]: any) => {
              const ok = v === true || v === 'ok' || v === 'connected' || v === 'healthy';
              return (
                <div key={k} className="border-[1.5px] border-[#e5e5e5] py-2 px-3 flex items-center gap-2">
                  <span className={`indicator ${ok ? 'online' : 'offline'}`}/>
                  <div>
                    <div className="status-label">{k}</div>
                    <div className="font-mono text-[0.78rem] font-bold">{String(v)}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};

const EnrichmentTab = ({ token }: { token: string | null }) => {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [batchSize, setBatchSize] = useState(20);
  const [minConnections, setMinConnections] = useState(1);
  const [driftLoading, setDriftLoading] = useState(false);
  const [driftResult, setDriftResult] = useState<any>(null);

  const runEnrichment = async () => {
    setLoading(true); setResult(null);
    try {
      const res = await fetch(`${API_BASE}/entities/enrich`, {
        method:'POST',
        headers:{ Authorization:`Bearer ${token}`, 'Content-Type':'application/json' },
        body: JSON.stringify({ batch_size: batchSize, min_connections: minConnections })
      });
      if (res.ok) setResult(await res.json());
    } finally { setLoading(false); }
  };

  const runDrift = async () => {
    setDriftLoading(true); setDriftResult(null);
    try {
      const res = await fetch(`${API_BASE}/ontology/drift/detect`, {
        method:'POST', headers:{ Authorization:`Bearer ${token}` }
      });
      if (res.ok) setDriftResult(await res.json());
    } finally { setDriftLoading(false); }
  };

  return (
    <div>
      {/* Entity Enrichment */}
      <div className="card mb-6">
        <h2 className="title-md mb-2">Entity Enrichment</h2>
        <p className="text-[var(--muted-color)] text-[0.85rem] mb-5">
          Synthesize rich LLM-generated profiles for all eligible entities by scanning their neighborhood context in the graph.
        </p>
        <div className="grid grid-cols-2 gap-4 mb-4 max-w-[360px]">
          <div>
            <label className="block font-mono text-[0.7rem] font-bold text-[#888] mb-1">BATCH SIZE</label>
            <input type="number" min={1} max={100} value={batchSize} onChange={e => setBatchSize(Number(e.target.value))}
              className="search-input w-full"/>
          </div>
          <div>
            <label className="block font-mono text-[0.7rem] font-bold text-[#888] mb-1">MIN CONNECTIONS</label>
            <input type="number" min={0} max={20} value={minConnections} onChange={e => setMinConnections(Number(e.target.value))}
              className="search-input w-full"/>
          </div>
        </div>
        <button className="btn btn-primary flex gap-2 items-center" onClick={runEnrichment} disabled={loading}>
          {loading ? <Spinner/> : <Zap size={14}/>}
          {loading ? 'Enriching…' : 'Run Entity Enrichment'}
        </button>
        {result && (
          <div className="mt-4 bg-[#f0fdf4] border border-[#bbf7d0] p-3 font-mono text-[0.82rem] text-[#166534]">
            ✓ {result.message || `Enriched ${result.enriched_count ?? '?'} entities`}
          </div>
        )}
      </div>

      {/* Drift Detection */}
      <div className="card">
        <h2 className="title-md mb-2">Ontology Drift Detection</h2>
        <p className="text-[var(--muted-color)] text-[0.85rem] mb-5">
          Analyse recent data samples to detect schema evolution and generate a drift report for admin review.
        </p>
        <button className="btn btn-primary flex gap-2 items-center" onClick={runDrift} disabled={driftLoading}>
          {driftLoading ? <Spinner/> : <GitBranch size={14}/>}
          {driftLoading ? 'Detecting…' : 'Run Drift Detection'}
        </button>
        {driftResult && (
          <div className="mt-4 bg-[#eff6ff] border border-[#bfdbfe] p-3 font-mono text-[0.82rem] text-[#1d4ed8]">
            ✓ Drift report created. ID: {driftResult.report_id || driftResult.id || '—'} → Review in Ontology Governance tab.
          </div>
        )}
      </div>
    </div>
  );
};

const SandboxTab = ({ token }: { token: string | null }) => {
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState('');

  const trigger = async (endpoint: string, label: string) => {
    setLoading(true); setMsg('');
    try {
      const res = await fetch(`${API_BASE}${endpoint}`, {
        method:'POST', headers:{ Authorization:`Bearer ${token}` }
      });
      setMsg(res.ok ? `✓ ${label} dispatched to Celery worker.` : `✗ Failed to trigger ${label}.`);
    } catch {
      setMsg(`✗ Network error.`);
    } finally { setLoading(false); }
  };

  return (
    <div className="card">
      <h2 className="title-md mb-2">MiroFish God-Mode Sandbox</h2>
      <p className="text-[var(--muted-color)] text-[0.85rem] mb-6">
        Control the simulation loops that connect Knowledge Graph entities into living agents.
      </p>
      {msg && (
        <div className={`py-2.5 px-3.5 mb-4 font-mono text-[0.82rem] border ${msg.startsWith('✓') ? 'bg-[#dcfce7] text-[#166534] border-[#bbf7d0]' : 'bg-[#fef2f2] text-[#dc2626] border-[#fecaca]'}`}>
          {msg}
        </div>
      )}
      <div className="flex flex-col gap-4 max-w-[420px]">
        {[
          { endpoint:'/v1/simulation/generate_personas', label:'Generate Agent Personas', icon:<Users size={14}/>,
            desc:'Converts raw graph nodes into living psychological profiles for agent simulation.' },
          { endpoint:'/v1/simulation/tick', label:'Force Simulation Tick', icon:<Play size={14}/>,
            desc:'Forces agents to read their local graph memory and output a new interaction edge.' },
        ].map(item => (
          <div key={item.endpoint} className="border-2 border-black p-4">
            <button className="btn btn-primary flex gap-2 items-center w-full justify-center mb-2" onClick={() => trigger(item.endpoint, item.label)} disabled={loading}>
              {loading ? <Spinner/> : item.icon} {item.label}
            </button>
            <p className="m-0 text-[0.78rem] text-[var(--muted-color)] font-sans">{item.desc}</p>
          </div>
        ))}
      </div>
    </div>
  );
};

// ─── Main Dashboard ───────────────────────────────────────────────────────────
export default function AdminDashboard() {
  const { token, user } = useAuth();
  const [activeTab, setActiveTab] = useState('overview');
  const [stats, setStats] = useState<any>(null);
  const [health, setHealth] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchOverview = useCallback(async () => {
    if (!token) return;
    try {
      const [statsRes, healthRes] = await Promise.all([
        fetch(`${API_BASE}/admin/stats`, { headers: { Authorization: `Bearer ${token}` } }),
        fetch(`${API_BASE}/system/health`, { headers: { Authorization: `Bearer ${token}` } }),
      ]);
      if (statsRes.ok) setStats(await statsRes.json());
      if (healthRes.ok) setHealth(await healthRes.json());
    } catch (err: any) {
      setError(err.message);
    }
  }, [token]);

  useEffect(() => { fetchOverview(); }, [fetchOverview]);

  if (user && user.username !== 'admin' && !user.scopes?.includes('admin')) {
    return (
      <div className="container flex-center min-h-[60vh] flex-col gap-4">
        <Shield size={48} className="opacity-30"/>
        <h2 className="title-md">Access Denied</h2>
        <p className="text-[var(--muted-color)]">You need administrative privileges to view this page.</p>
      </div>
    );
  }

  const TABS = [
    { id:'overview',   label:'Overview',           icon:<BarChart2 size={14}/> },
    { id:'users',      label:'Users',              icon:<Users size={14}/> },
    { id:'documents',  label:'Documents',          icon:<Database size={14}/> },
    { id:'graph',      label:'Graph CRUD',         icon:<GitBranch size={14}/> },
    { id:'ontology',   label:'Ontology',           icon:<Settings size={14}/> },
    { id:'workers',    label:'Workers',            icon:<Cpu size={14}/> },
    { id:'enrichment', label:'Enrichment / Drift', icon:<Zap size={14}/> },
    { id:'sandbox',    label:'God-Mode Sandbox',   icon:<Play size={14}/> },
  ];

  return (
    <div className="container fade-in py-8 px-10 max-w-[1400px]">
      {/* Header */}
      <div className="flex justify-between items-start mb-6">
        <div>
          <h1 className="text-3xl font-bold font-display tracking-tight">Admin Control Center</h1>
          <p className="text-[#666] mt-2 text-[0.95rem]">Manage graph data, workers, users, and platform configuration</p>
        </div>
        {error && (
          <div className="bg-[#fef2f2] text-[#dc2626] py-2 px-4 border border-[#fecaca] font-mono text-[0.85rem] flex items-center gap-2 rounded shadow-sm">
            <AlertTriangle size={15}/> {error}
          </div>
        )}
      </div>

      <div className="grid grid-cols-[240px_1fr] gap-8 mt-2">
        {/* Sidebar nav */}
        <div className="bg-white border-2 border-black p-3">
          <nav className="flex flex-col gap-1.5">
            {TABS.map(tab => (
              <button
                key={tab.id}
                className={`flex items-center w-full justify-start gap-2.5 py-2 px-3 text-[0.85rem] font-medium border-[1.5px] transition-colors ${activeTab === tab.id ? 'bg-black text-white border-black' : 'bg-transparent text-black border-transparent hover:bg-gray-100'}`}
                onClick={() => setActiveTab(tab.id)}
              >
                {tab.icon} {tab.label}
              </button>
            ))}
          </nav>
        </div>

        {/* Main content */}
        <div>
          {activeTab === 'overview' && <OverviewTab stats={stats} health={health} onRefresh={fetchOverview}/>}
          {activeTab === 'users' && <UsersTab token={token}/>}
          {activeTab === 'documents' && <DocumentsTab token={token}/>}
          {activeTab === 'graph' && <GraphCRUDTab token={token}/>}
          {activeTab === 'ontology' && <OntologyGovernanceTab token={token}/>}
          {activeTab === 'workers' && <WorkersTab token={token}/>}
          {activeTab === 'enrichment' && <EnrichmentTab token={token}/>}
          {activeTab === 'sandbox' && <SandboxTab token={token}/>}
        </div>
      </div>

      <style>{`
        @keyframes spin { 100% { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}
