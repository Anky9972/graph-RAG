import React, { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../context/AuthContext';
import { BarChart2, TrendingUp, AlertTriangle, CheckCircle, RefreshCw, Zap, FileText, GitCommit, MessageSquare } from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

interface EvalDashboard {
  total_evaluations: number;
  avg_overall_score: number;
  avg_faithfulness: number;
  avg_relevancy: number;
  hallucination_rate: number;
  trend_data: TrendPoint[];
}

interface TrendPoint {
  timestamp: string;
  overall_score: number;
  faithfulness: number;
  answer_relevancy: number;
  hallucination_detected: boolean;
  document_id?: string;
}

interface EvalForm {
  question: string;
  answer: string;
  contexts: string;
}

// Helper: build markdown from report result
function buildReportMarkdown(result: any, topic: string): string {
  const lines: string[] = [];
  lines.push(`# ${result.topic || topic}`);
  lines.push('');
  if (result.confidence !== undefined) {
    lines.push(`**Confidence:** ${(result.confidence * 100).toFixed(1)}%`);
  }
  if (result.tool_calls_made !== undefined) {
    lines.push(`**Tool calls:** ${result.tool_calls_made}`);
  }
  lines.push(`**Generated:** ${new Date().toLocaleString()}`);
  lines.push('');

  if (result.executive_summary) {
    lines.push('## Executive Summary');
    lines.push('');
    lines.push(result.executive_summary);
    lines.push('');
  }

  if (result.sections && typeof result.sections === 'object' && !Array.isArray(result.sections)) {
    Object.entries(result.sections).forEach(([title, content], i) => {
      lines.push(`## ${i + 1}. ${title}`);
      lines.push('');
      lines.push(String(content));
      lines.push('');
    });
  } else if (Array.isArray(result.sections)) {
    result.sections.forEach((s: any, i: number) => {
      lines.push(`## ${i + 1}. ${s.title || ''}`);
      lines.push('');
      lines.push(s.content || '');
      lines.push('');
    });
  } else if (!result.sections) {
    lines.push(result.report || result.content || result.markdown || JSON.stringify(result, null, 2));
    lines.push('');
  }

  if (result.key_entities && result.key_entities.length > 0) {
    lines.push('## Key Entities');
    lines.push('');
    lines.push(result.key_entities.join(', '));
  }

  return lines.join('\n');
}

const InsightsView: React.FC = () => {
  const { token } = useAuth();
  const [dashboard, setDashboard] = useState<EvalDashboard | null>(null);
  const [loading, setLoading] = useState(false);
  const [evalForm, setEvalForm] = useState<EvalForm>({ question: '', answer: '', contexts: '' });
  const [evalResult, setEvalResult] = useState<any>(null);
  const [evalLoading, setEvalLoading] = useState(false);
  const [communities, setCommunities] = useState<any[]>([]);
  const [communityLoading, setCommunityLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<'metrics' | 'evaluate' | 'communities' | 'export' | 'report' | 'graph-update' | 'entity-chat'>('metrics');

  // Report Agent state
  const [reportTopic, setReportTopic] = useState('');
  const [reportDepth, setReportDepth] = useState(3);
  const [reportResult, setReportResult] = useState<any>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [reportTimestamp, setReportTimestamp] = useState<Date | null>(null);
  const [copyDone, setCopyDone] = useState(false);

  // Graph Update state
  const [updateText, setUpdateText] = useState('');
  const [updateResult, setUpdateResult] = useState<any>(null);
  const [updateLoading, setUpdateLoading] = useState(false);

  // Entity Chat state
  const [entities, setEntities] = useState<any[]>([]);
  const [selectedEntity, setSelectedEntity] = useState('');
  const [entityContext, setEntityContext] = useState('');
  const [chatMsg, setChatMsg] = useState('');
  const [chatHistory, setChatHistory] = useState<{role: string; content: string}[]>([]);
  const [chatLoading, setChatLoading] = useState(false);

  const fetchDashboard = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/eval/dashboard?limit=200`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) setDashboard(await res.json());
    } catch (e) { console.error(e); }
    setLoading(false);
  }, [token]);

  const fetchCommunities = useCallback(async () => {
    setCommunityLoading(true);
    try {
      const res = await fetch(`${API_BASE}/graph/communities?limit=30`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setCommunities(data.communities || []);
      }
    } catch (e) { console.error(e); }
    setCommunityLoading(false);
  }, [token]);

  const fetchEntities = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/admin/graph/nodes?query=&limit=200`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setEntities((data.nodes || []).slice(0, 100));
      }
    } catch {}
  }, [token]);

  useEffect(() => {
    fetchDashboard();
    fetchCommunities();
    fetchEntities();
  }, [fetchDashboard, fetchCommunities, fetchEntities]);

  const runEval = async () => {
    if (!evalForm.question || !evalForm.answer || !evalForm.contexts) return;
    setEvalLoading(true);
    setEvalResult(null);
    try {
      const res = await fetch(`${API_BASE}/eval/score`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          question: evalForm.question,
          answer: evalForm.answer,
          contexts: evalForm.contexts.split('\n---\n').map(c => c.trim()).filter(Boolean)
        })
      });
      if (res.ok) {
        setEvalResult(await res.json());
        fetchDashboard(); // Refresh metrics
      }
    } catch (e) { console.error(e); }
    setEvalLoading(false);
  };

  const runReport = async () => {
    if (!reportTopic.trim()) return;
    setReportLoading(true); setReportResult(null);
    try {
      const res = await fetch(`${API_BASE}/report`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ topic: reportTopic, depth: reportDepth })
      });
      if (res.ok) {
        setReportResult(await res.json());
        setReportTimestamp(new Date());
      }
    } catch (e) { console.error(e); }
    setReportLoading(false);
  };

  const runGraphUpdate = async () => {
    if (!updateText.trim()) return;
    setUpdateLoading(true); setUpdateResult(null);
    try {
      const res = await fetch(`${API_BASE}/graph/update`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ text: updateText })
      });
      if (res.ok) setUpdateResult(await res.json());
    } catch (e) { console.error(e); }
    setUpdateLoading(false);
  };

  const sendEntityChat = async () => {
    if (!selectedEntity || !chatMsg.trim()) return;
    const userMsg = { role: 'user', content: chatMsg };
    setChatHistory(h => [...h, userMsg]);
    setChatMsg('');
    setChatLoading(true);
    try {
      const res = await fetch(`${API_BASE}/entities/${encodeURIComponent(selectedEntity)}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ message: userMsg.content })
      });
      if (res.ok) {
        const data = await res.json();
        setChatHistory(h => [...h, { role: 'assistant', content: data.response || data.answer || JSON.stringify(data) }]);
      }
    } catch (e) { console.error(e); }
    setChatLoading(false);
  };

  const assignCommunities = async () => {
    setCommunityLoading(true);
    try {
      const res = await fetch(`${API_BASE}/graph/communities/assign`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        alert(`✓ ${data.message}`);
        fetchCommunities();
      }
    } catch (e) { console.error(e); }
    setCommunityLoading(false);
  };

  const exportGraph = async (fmt: string) => {
    const res = await fetch(`${API_BASE}/graph/export?format=${fmt}`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (!res.ok) return;
    const blob = await res.blob();
    const ext = fmt === 'json' ? 'json' : fmt === 'cypher' ? 'cypher' : 'graphml';
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `graph_export.${ext}`; a.click();
    URL.revokeObjectURL(url);
  };

  const handleCopyReport = () => {
    if (!reportResult) return;
    const text = buildReportMarkdown(reportResult, reportTopic);
    navigator.clipboard.writeText(text).then(() => {
      setCopyDone(true);
      setTimeout(() => setCopyDone(false), 2000);
    });
  };

  const handleDownloadReport = () => {
    if (!reportResult) return;
    const text = buildReportMarkdown(reportResult, reportTopic);
    const blob = new Blob([text], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `report_${reportTopic.slice(0, 30).replace(/\s+/g, '_')}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const score2color = (s: number) => {
    if (s >= 0.8) return '#16a34a';
    if (s >= 0.6) return '#d97706';
    return '#dc2626';
  };
  const score2label = (s: number) => s >= 0.8 ? 'HIGH' : s >= 0.6 ? 'MEDIUM' : 'LOW';

  const ScoreBar: React.FC<{ label: string; value: number }> = ({ label, value }) => (
    <div style={{ marginBottom: '1rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.25rem', fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }}>
        <span>{label}</span>
        <span style={{ color: score2color(value), fontWeight: 700 }}>{(value * 100).toFixed(1)}%</span>
      </div>
      <div style={{ height: '8px', background: '#e5e7eb', position: 'relative' }}>
        <div style={{ position: 'absolute', left: 0, top: 0, height: '100%', width: `${value * 100}%`, background: score2color(value), transition: 'width 0.6s ease' }} />
      </div>
    </div>
  );

  const confidenceBadgeColor = (c: number) =>
    c >= 0.8 ? '#16a34a' : c >= 0.6 ? '#d97706' : '#dc2626';

  return (
    <div className="container" style={{ maxWidth: '1100px', paddingBottom: '3rem' }}>
      <div className="page-header flex-between" style={{ marginBottom: '2rem' }}>
        <div>
          <h1>INSIGHTS HQ</h1>
          <p className="mono-text">QUALITY METRICS // EVAL DASHBOARD // GRAPH INTELLIGENCE</p>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button className="app-btn mono-text" onClick={fetchDashboard} disabled={loading} style={{ padding: '0.5rem 1rem', fontSize: '0.8rem' }}>
            <RefreshCw size={14} style={{ display: 'inline', marginRight: '0.4rem' }} />
            REFRESH
          </button>
        </div>
      </div>

      {/* Tab Nav */}
      <div style={{ display: 'flex', borderBottom: '3px solid #000', marginBottom: '2rem', gap: 0, flexWrap: 'wrap' }}>
        {([
          { id: 'metrics', label: 'METRICS' },
          { id: 'evaluate', label: 'EVALUATE' },
          { id: 'communities', label: 'COMMUNITIES' },
          { id: 'export', label: 'EXPORT' },
          { id: 'report', label: '⚡ REPORT' },
          { id: 'graph-update', label: '↑ LIVE UPDATE' },
          { id: 'entity-chat', label: '💬 ENTITY CHAT' },
        ] as const).map(t => (
          <button
            key={t.id}
            onClick={() => setActiveTab(t.id as any)}
            className="mono-text"
            style={{
              padding: '0.65rem 1.2rem', fontWeight: 700, fontSize: '0.78rem', letterSpacing: '0.8px',
              border: 'none', borderBottom: activeTab === t.id ? '3px solid #000' : 'none',
              background: activeTab === t.id ? '#000' : 'transparent',
              color: activeTab === t.id ? '#fff' : '#000', cursor: 'pointer',
              marginBottom: '-3px', textTransform: 'uppercase', whiteSpace: 'nowrap'
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* ── METRICS TAB ── */}
      {activeTab === 'metrics' && (
        <div>
          {loading ? (
            <div className="mono-text" style={{ textAlign: 'center', padding: '3rem', color: '#aaa' }}>LOADING METRICS...</div>
          ) : !dashboard || dashboard.total_evaluations === 0 ? (
            <div style={{ border: '3px solid #000', padding: '3rem', textAlign: 'center' }}>
              <BarChart2 size={48} style={{ marginBottom: '1rem', opacity: 0.3 }} />
              <p className="mono-text" style={{ color: '#777' }}>NO EVALUATION DATA YET</p>
              <p className="mono-text" style={{ color: '#999', fontSize: '0.85rem', marginTop: '0.5rem' }}>
                Use the EVALUATE tab to score Q&A pairs and build your quality history.
              </p>
            </div>
          ) : (
            <>
              {/* KPI Cards */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem', marginBottom: '2rem' }}>
                {[
                  { label: 'TOTAL EVALS', value: dashboard.total_evaluations, raw: true, icon: <BarChart2 size={20} /> },
                  { label: 'AVG QUALITY', value: dashboard.avg_overall_score, icon: <TrendingUp size={20} /> },
                  { label: 'FAITHFULNESS', value: dashboard.avg_faithfulness, icon: <CheckCircle size={20} /> },
                  { label: 'HALLUCINATION RATE', value: dashboard.hallucination_rate, invert: true, icon: <AlertTriangle size={20} /> },
                ].map(card => (
                  <div key={card.label} style={{ border: '3px solid #000', padding: '1.5rem', background: (card.invert ? dashboard.hallucination_rate > 0.3 : false) ? '#fff5f5' : '#fff' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1rem' }}>
                      <span className="mono-text" style={{ fontSize: '0.7rem', fontWeight: 700, letterSpacing: '1px', color: '#666' }}>{card.label}</span>
                      {card.icon}
                    </div>
                    <div className="mono-text" style={{
                      fontSize: '2rem', fontWeight: 900,
                      color: card.raw ? '#000' : score2color(card.invert ? 1 - (card.value as number) : (card.value as number))
                    }}>
                      {card.raw ? card.value : `${((card.value as number) * 100).toFixed(1)}%`}
                    </div>
                  </div>
                ))}
              </div>

              {/* Score Breakdown */}
              <div style={{ border: '3px solid #000', padding: '1.5rem', marginBottom: '2rem' }}>
                <h3 className="mono-text" style={{ marginBottom: '1.5rem', borderBottom: '1px dotted #000', paddingBottom: '0.5rem' }}>METRIC BREAKDOWN</h3>
                <ScoreBar label="Overall Quality Score" value={dashboard.avg_overall_score} />
                <ScoreBar label="Faithfulness (grounding)" value={dashboard.avg_faithfulness} />
                <ScoreBar label="Answer Relevancy" value={dashboard.avg_relevancy} />
                <ScoreBar label="Non-hallucination Rate" value={1 - dashboard.hallucination_rate} />
              </div>

              {/* Trend Table */}
              {dashboard.trend_data.length > 0 && (
                <div style={{ border: '3px solid #000', padding: '1.5rem' }}>
                  <h3 className="mono-text" style={{ marginBottom: '1.5rem', borderBottom: '1px dotted #000', paddingBottom: '0.5rem' }}>EVALUATION HISTORY (LATEST {Math.min(dashboard.trend_data.length, 20)})</h3>
                  <div style={{ overflowX: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }}>
                      <thead>
                        <tr style={{ borderBottom: '2px solid #000' }}>
                          {['TIMESTAMP', 'QUALITY', 'FAITHFULNESS', 'RELEVANCY', 'HALLUCINATION'].map(h => (
                            <th key={h} style={{ padding: '0.5rem', textAlign: 'left', fontWeight: 700 }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {dashboard.trend_data.slice(0, 20).map((p, i) => (
                          <tr key={i} style={{ borderBottom: '1px dotted #ddd', background: i % 2 === 0 ? '#fafafa' : '#fff' }}>
                            <td style={{ padding: '0.5rem' }}>{p.timestamp}</td>
                            <td style={{ padding: '0.5rem', color: score2color(p.overall_score), fontWeight: 700 }}>{(p.overall_score * 100).toFixed(1)}%</td>
                            <td style={{ padding: '0.5rem', color: score2color(p.faithfulness) }}>{(p.faithfulness * 100).toFixed(1)}%</td>
                            <td style={{ padding: '0.5rem', color: score2color(p.answer_relevancy) }}>{(p.answer_relevancy * 100).toFixed(1)}%</td>
                            <td style={{ padding: '0.5rem' }}>
                              <span style={{ background: p.hallucination_detected ? '#dc2626' : '#16a34a', color: '#fff', padding: '0.1rem 0.5rem', fontSize: '0.7rem', fontWeight: 700 }}>
                                {p.hallucination_detected ? 'YES' : 'NO'}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* ── EVALUATE TAB ── */}
      {activeTab === 'evaluate' && (
        <div>
          <div style={{ border: '3px solid #000', padding: '2rem', marginBottom: '2rem' }}>
            <h3 className="mono-text" style={{ marginBottom: '1.5rem' }}>
              <Zap size={16} style={{ display: 'inline', marginRight: '0.5rem' }} />
              SCORE A Q&A PAIR
            </h3>
            <p className="mono-text" style={{ fontSize: '0.8rem', color: '#666', marginBottom: '1.5rem' }}>
              Paste a question, its generated answer, and the retrieved context chunks (separate chunks with "---").
            </p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div>
                <label className="mono-text" style={{ fontSize: '0.8rem', fontWeight: 700, display: 'block', marginBottom: '0.5rem' }}>QUESTION</label>
                <textarea value={evalForm.question} onChange={e => setEvalForm(f => ({ ...f, question: e.target.value }))}
                  rows={2} style={{ width: '100%', border: '2px solid #000', padding: '0.75rem', fontFamily: 'var(--font-mono)', fontSize: '0.9rem', resize: 'vertical', boxSizing: 'border-box' }} />
              </div>
              <div>
                <label className="mono-text" style={{ fontSize: '0.8rem', fontWeight: 700, display: 'block', marginBottom: '0.5rem' }}>GENERATED ANSWER</label>
                <textarea value={evalForm.answer} onChange={e => setEvalForm(f => ({ ...f, answer: e.target.value }))}
                  rows={4} style={{ width: '100%', border: '2px solid #000', padding: '0.75rem', fontFamily: 'var(--font-mono)', fontSize: '0.9rem', resize: 'vertical', boxSizing: 'border-box' }} />
              </div>
              <div>
                <label className="mono-text" style={{ fontSize: '0.8rem', fontWeight: 700, display: 'block', marginBottom: '0.5rem' }}>CONTEXT CHUNKS (separate with "---" on its own line)</label>
                <textarea value={evalForm.contexts} onChange={e => setEvalForm(f => ({ ...f, contexts: e.target.value }))}
                  rows={6} placeholder={'Context chunk 1 text...\n---\nContext chunk 2 text...'} style={{ width: '100%', border: '2px solid #000', padding: '0.75rem', fontFamily: 'var(--font-mono)', fontSize: '0.85rem', resize: 'vertical', boxSizing: 'border-box' }} />
              </div>
              <button className="app-btn mono-text" onClick={runEval} disabled={evalLoading || !evalForm.question || !evalForm.answer || !evalForm.contexts}
                style={{ alignSelf: 'flex-start', padding: '0.75rem 2rem' }}>
                {evalLoading ? 'EVALUATING...' : 'RUN EVALUATION'}
              </button>
            </div>
          </div>

          {evalResult && (
            <div style={{ border: '3px solid #000', padding: '2rem', background: evalResult.hallucination_detected ? '#fff5f5' : '#f0fdf4' }}>
              <h3 className="mono-text" style={{ marginBottom: '1.5rem' }}>
                {evalResult.hallucination_detected
                  ? <><AlertTriangle size={16} style={{ display: 'inline', marginRight: '0.5rem', color: '#dc2626' }} />HALLUCINATION RISK DETECTED</>
                  : <><CheckCircle size={16} style={{ display: 'inline', marginRight: '0.5rem', color: '#16a34a' }} />EVALUATION RESULTS</>
                }
              </h3>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '1rem', marginBottom: '1.5rem' }}>
                {[
                  { label: 'OVERALL', value: evalResult.overall_score },
                  { label: 'FAITHFULNESS', value: evalResult.faithfulness },
                  { label: 'RELEVANCY', value: evalResult.answer_relevancy },
                  { label: 'PRECISION', value: evalResult.context_precision },
                ].map(m => (
                  <div key={m.label} style={{ border: `2px solid ${score2color(m.value)}`, padding: '1rem', textAlign: 'center' }}>
                    <div className="mono-text" style={{ fontSize: '0.7rem', fontWeight: 700, color: '#666', marginBottom: '0.5rem' }}>{m.label}</div>
                    <div className="mono-text" style={{ fontSize: '1.8rem', fontWeight: 900, color: score2color(m.value) }}>
                      {(m.value * 100).toFixed(0)}%
                    </div>
                    <div className="mono-text" style={{ fontSize: '0.65rem', color: score2color(m.value), marginTop: '0.25rem' }}>{score2label(m.value)}</div>
                  </div>
                ))}
              </div>
              <div className="mono-text" style={{ fontSize: '0.75rem', color: '#777', borderTop: '1px dotted #ccc', paddingTop: '0.75rem' }}>
                Saved to Neo4j for trending. Eval ID: {evalResult.eval_id || 'N/A'}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── COMMUNITIES TAB ── */}
      {activeTab === 'communities' && (
        <div>
          <div style={{ display: 'flex', gap: '1rem', marginBottom: '2rem', alignItems: 'center' }}>
            <button className="app-btn mono-text" onClick={assignCommunities} disabled={communityLoading} style={{ padding: '0.75rem 1.5rem' }}>
              {communityLoading ? 'DETECTING...' : '⚡ DETECT COMMUNITIES'}
            </button>
            <span className="mono-text" style={{ fontSize: '0.8rem', color: '#666' }}>
              Run after ingesting documents to cluster entities into related groups (enables community search).
            </span>
          </div>

          {communities.length === 0 ? (
            <div style={{ border: '3px solid #000', padding: '3rem', textAlign: 'center' }}>
              <p className="mono-text" style={{ color: '#777' }}>NO COMMUNITIES DETECTED YET</p>
              <p className="mono-text" style={{ color: '#999', fontSize: '0.85rem', marginTop: '0.5rem' }}>Click "Detect Communities" above to cluster your knowledge graph entities.</p>
            </div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: '1rem' }}>
              {communities.map((c, i) => (
                <div key={i} style={{ border: '2px solid #000', padding: '1.25rem' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
                    <span className="mono-text" style={{ fontWeight: 700, fontSize: '0.85rem' }}>CLUSTER #{c.community_id}</span>
                    <span className="mono-text" style={{ fontSize: '0.75rem', background: '#000', color: '#fff', padding: '0.15rem 0.5rem' }}>
                      {c.entity_count} entities
                    </span>
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.35rem' }}>
                    {(c.sample_entities || []).map((e: string, ei: number) => (
                      <span key={ei} style={{ background: '#f3f4f6', border: '1px solid #d1d5db', padding: '0.15rem 0.5rem', fontSize: '0.75rem', fontFamily: 'var(--font-mono)' }}>{e}</span>
                    ))}
                    {c.entity_count > (c.sample_entities || []).length && (
                      <span style={{ color: '#666', fontSize: '0.75rem', fontFamily: 'var(--font-mono)', padding: '0.15rem 0' }}>
                        +{c.entity_count - (c.sample_entities || []).length} more
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── EXPORT TAB ── */}
      {activeTab === 'export' && (
        <div>
          <div style={{ border: '3px solid #000', padding: '2rem', marginBottom: '2rem' }}>
            <h3 className="mono-text" style={{ marginBottom: '1.5rem' }}>EXPORT KNOWLEDGE GRAPH</h3>
            <p className="mono-text" style={{ fontSize: '0.85rem', color: '#555', marginBottom: '2rem', lineHeight: '1.6' }}>
              Export your knowledge graph for use in external tools, backups, or further analysis.
            </p>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: '1rem' }}>
              {[
                { fmt: 'json', label: 'JSON', desc: 'Nodes & edges as JSON. For custom processing or visualization.' },
                { fmt: 'cypher', label: 'CYPHER', desc: 'Cypher CREATE statements. Re-import to any Neo4j instance.' },
                { fmt: 'graphml', label: 'GRAPHML', desc: 'GraphML XML. Compatible with Gephi, yEd, and most graph tools.' },
              ].map(e => (
                <div key={e.fmt} style={{ border: '2px solid #000', padding: '1.5rem' }}>
                  <div className="mono-text" style={{ fontWeight: 900, fontSize: '1.1rem', marginBottom: '0.5rem' }}>.{e.label}</div>
                  <p style={{ fontSize: '0.82rem', color: '#555', marginBottom: '1.25rem', fontFamily: 'var(--font-sans)', lineHeight: '1.5' }}>{e.desc}</p>
                  <button className="app-btn mono-text" onClick={() => exportGraph(e.fmt)} style={{ width: '100%', textAlign: 'center' }}>
                    DOWNLOAD .{e.label}
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── REPORT AGENT TAB ── */}
      {activeTab === 'report' && (
        <div>
          <div className="page-info-bar">
            <FileText size={14}/>
            <span><strong>REPORT AGENT</strong> — Enter any topic or question. The ReACT agent autonomously queries the knowledge graph using multiple retrieval strategies and synthesizes a deep multi-section report. More <strong>depth</strong> = more reasoning steps.</span>
          </div>

          {/* Input form */}
          <div style={{ border: '3px solid #000', padding: '2rem', marginBottom: '2rem' }}>
            <h3 className="mono-text" style={{ marginBottom: '1.5rem' }}>
              <Zap size={16} style={{ display: 'inline', marginRight: '0.5rem' }}/>GENERATE ANALYTICAL REPORT
            </h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div>
                <label className="mono-text" style={{ fontSize: '0.8rem', fontWeight: 700, display: 'block', marginBottom: '0.5rem' }}>TOPIC OR QUESTION</label>
                <textarea value={reportTopic} onChange={e => setReportTopic(e.target.value)}
                  rows={3} placeholder="e.g. 'Summarize all relationships between Company X and its investors'"
                  style={{ width: '100%', border: '2px solid #000', padding: '0.75rem', fontFamily: 'var(--font-mono)', fontSize: '0.9rem', resize: 'vertical', boxSizing: 'border-box' }}/>
              </div>
              <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
                <div>
                  <label className="mono-text" style={{ fontSize: '0.8rem', fontWeight: 700, display: 'block', marginBottom: '0.5rem' }}>DEPTH (REASONING STEPS)</label>
                  <select value={reportDepth} onChange={e => setReportDepth(Number(e.target.value))}
                    style={{ border: '2px solid #000', padding: '0.5rem 0.75rem', fontFamily: 'var(--font-mono)', fontSize: '0.9rem' }}>
                    {[1, 2, 3, 4, 5].map(n => <option key={n} value={n}>{n} {n === 1 ? '(fast)' : n === 5 ? '(deep)' : ''}</option>)}
                  </select>
                </div>
                <button className="app-btn mono-text" onClick={runReport} disabled={reportLoading || !reportTopic.trim()}
                  style={{ alignSelf: 'flex-end', padding: '0.75rem 2rem' }}>
                  {reportLoading ? 'GENERATING...' : 'GENERATE REPORT'}
                </button>
              </div>
            </div>
          </div>

          {/* Empty state */}
          {!reportResult && !reportLoading && (
            <div style={{ border: '3px dashed #e5e5e5', padding: '4rem 2rem', textAlign: 'center' }}>
              <FileText size={44} style={{ opacity: 0.18, marginBottom: '1rem' }} />
              <p className="mono-text" style={{ color: '#aaa', fontSize: '0.85rem', letterSpacing: '1px' }}>NO REPORT GENERATED YET</p>
              <p style={{ color: '#bbb', fontSize: '0.8rem', marginTop: '0.5rem', fontFamily: 'var(--font-sans)' }}>
                Enter a topic above and click Generate to produce an AI-powered analytical report from the knowledge graph.
              </p>
            </div>
          )}

          {/* Loading state */}
          {reportLoading && (
            <div style={{ border: '3px solid #000', padding: '2.5rem', textAlign: 'center' }}>
              <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '0.9rem', marginBottom: '0.75rem' }}>
                ⚡ AGENT REASONING…
              </div>
              <div style={{ fontFamily: 'var(--font-sans)', fontSize: '0.82rem', color: 'var(--muted-color)' }}>
                Querying knowledge graph with depth {reportDepth}. This may take 20–60 seconds.
              </div>
            </div>
          )}

          {/* Report output */}
          {reportResult && (
            <div style={{ border: '3px solid #000' }}>
              {/* Report header bar */}
              <div style={{ background: '#000', color: '#fff', padding: '0.85rem 1.5rem', display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '0.82rem', flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  📄 {(reportResult.topic || reportTopic).toUpperCase()}
                </span>
                {/* Confidence badge */}
                {reportResult.confidence !== undefined && (
                  <span style={{
                    background: confidenceBadgeColor(reportResult.confidence),
                    color: '#fff',
                    padding: '2px 10px',
                    fontFamily: 'var(--font-mono)',
                    fontSize: '0.72rem',
                    fontWeight: 700,
                    letterSpacing: '0.5px',
                    flexShrink: 0,
                  }}>
                    CONF: {(reportResult.confidence * 100).toFixed(0)}%
                  </span>
                )}
                {reportResult.tool_calls_made !== undefined && (
                  <span style={{ background: '#333', color: '#fff', padding: '2px 10px', fontFamily: 'var(--font-mono)', fontSize: '0.72rem', fontWeight: 700, flexShrink: 0 }}>
                    {reportResult.tool_calls_made} CALLS
                  </span>
                )}
                {/* Actions */}
                <button
                  onClick={handleCopyReport}
                  style={{ background: copyDone ? '#16a34a' : 'transparent', color: '#fff', border: '1px solid #555', padding: '3px 10px', fontFamily: 'var(--font-mono)', fontSize: '0.72rem', cursor: 'pointer', flexShrink: 0 }}
                >
                  {copyDone ? '✓ COPIED' : '📋 COPY'}
                </button>
                <button
                  onClick={handleDownloadReport}
                  style={{ background: 'transparent', color: '#fff', border: '1px solid #555', padding: '3px 10px', fontFamily: 'var(--font-mono)', fontSize: '0.72rem', cursor: 'pointer', flexShrink: 0 }}
                >
                  ⬇ .MD
                </button>
              </div>

              <div style={{ padding: '2rem' }}>
                {/* Meta info row */}
                <div style={{ display: 'flex', gap: '1.5rem', flexWrap: 'wrap', marginBottom: '2rem', paddingBottom: '1rem', borderBottom: '1px dotted #ddd', fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: '#888' }}>
                  {reportTimestamp && <div>Generated: {reportTimestamp.toLocaleString()}</div>}
                  {reportResult.tool_calls_made !== undefined && (
                    <div>Depth: {reportDepth} · Tool calls: {reportResult.tool_calls_made}</div>
                  )}
                  {reportResult.confidence !== undefined && (
                    <div style={{ color: confidenceBadgeColor(reportResult.confidence), fontWeight: 700 }}>
                      Confidence: {(reportResult.confidence * 100).toFixed(1)}%
                    </div>
                  )}
                </div>

                {/* Executive summary */}
                {reportResult.executive_summary && (
                  <div style={{ marginBottom: '2.5rem', borderLeft: '4px solid #f59e0b', paddingLeft: '1.25rem' }}>
                    <h4 className="mono-text" style={{ fontSize: '0.72rem', marginBottom: '0.75rem', color: '#d97706', letterSpacing: '1.5px' }}>
                      EXECUTIVE SUMMARY
                    </h4>
                    <p style={{ fontFamily: 'var(--font-sans)', lineHeight: 1.9, fontSize: '1rem', fontWeight: 500, whiteSpace: 'pre-wrap', color: '#111' }}>
                      {reportResult.executive_summary}
                    </p>
                  </div>
                )}

                {/* Sections */}
                {reportResult.sections && typeof reportResult.sections === 'object' && !Array.isArray(reportResult.sections) ? (
                  Object.entries(reportResult.sections).map(([title, content], i) => (
                    <div key={i} style={{ marginBottom: '2rem', paddingBottom: '1.5rem', borderBottom: '1px dotted #e5e5e5' }}>
                      <h4 className="mono-text" style={{ fontSize: '0.8rem', marginBottom: '1rem', color: '#000', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span style={{ background: '#000', color: '#fff', padding: '2px 8px', fontSize: '0.65rem', flexShrink: 0 }}>{i + 1}</span>
                        {title.toUpperCase()}
                      </h4>
                      <p style={{ fontFamily: 'var(--font-sans)', lineHeight: 1.85, fontSize: '0.92rem', whiteSpace: 'pre-wrap', color: '#333' }}>
                        {String(content)}
                      </p>
                    </div>
                  ))
                ) : (
                  reportResult.sections?.map?.((s: any, i: number) => (
                    <div key={i} style={{ marginBottom: '2rem', paddingBottom: '1.5rem', borderBottom: '1px dotted #e5e5e5' }}>
                      <h4 className="mono-text" style={{ fontSize: '0.8rem', marginBottom: '1rem', color: '#000', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span style={{ background: '#000', color: '#fff', padding: '2px 8px', fontSize: '0.65rem', flexShrink: 0 }}>{i + 1}</span>
                        {s.title?.toUpperCase()}
                      </h4>
                      <p style={{ fontFamily: 'var(--font-sans)', lineHeight: 1.85, fontSize: '0.92rem', whiteSpace: 'pre-wrap', color: '#333' }}>
                        {s.content}
                      </p>
                    </div>
                  ))
                )}

                {!reportResult.sections && (
                  <p style={{ fontFamily: 'var(--font-sans)', lineHeight: 1.85, whiteSpace: 'pre-wrap', color: '#333' }}>
                    {reportResult.report || reportResult.content || reportResult.markdown || JSON.stringify(reportResult, null, 2)}
                  </p>
                )}

                {/* Key entities */}
                {reportResult.key_entities && reportResult.key_entities.length > 0 && (
                  <div style={{ marginTop: '2rem', paddingTop: '1rem', borderTop: '1px dotted #ccc' }}>
                    <h4 className="mono-text" style={{ fontSize: '0.68rem', color: '#888', marginBottom: '0.5rem', letterSpacing: '1.5px' }}>
                      KEY ENTITIES REFERENCED
                    </h4>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem' }}>
                      {reportResult.key_entities.map((e: string, i: number) => (
                        <span key={i} style={{ background: '#f3f4f6', border: '1.5px solid #e5e5e5', padding: '2px 8px', fontSize: '0.75rem', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
                          {e}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── LIVE GRAPH UPDATE TAB ── */}
      {activeTab === 'graph-update' && (
        <div>
          <div className="page-info-bar">
            <GitCommit size={14}/>
            <span><strong>LIVE GRAPH UPDATE</strong> — Paste any text (news article, note, policy). The system extracts entities and relationships and merges them into the live knowledge graph without re-running ingestion. Uses <strong>MERGE</strong> to prevent duplicates.</span>
          </div>
          <div style={{ border: '3px solid #000', padding: '2rem', marginBottom: '2rem' }}>
            <h3 className="mono-text" style={{ marginBottom: '1.5rem' }}><GitCommit size={16} style={{ display: 'inline', marginRight: '0.5rem' }}/>INJECT KNOWLEDGE INTO GRAPH</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div>
                <label className="mono-text" style={{ fontSize: '0.8rem', fontWeight: 700, display: 'block', marginBottom: '0.5rem' }}>TEXT TO INJECT</label>
                <textarea value={updateText} onChange={e => setUpdateText(e.target.value)}
                  rows={8} placeholder="Paste any text — news, reports, notes, or raw facts..."
                  style={{ width: '100%', border: '2px solid #000', padding: '0.75rem', fontFamily: 'var(--font-mono)', fontSize: '0.88rem', resize: 'vertical', boxSizing: 'border-box' }}/>
              </div>
              <button className="app-btn mono-text" onClick={runGraphUpdate} disabled={updateLoading || !updateText.trim()}
                style={{ alignSelf: 'flex-start', padding: '0.75rem 2rem' }}>
                {updateLoading ? 'INJECTING...' : 'INJECT INTO GRAPH'}
              </button>
            </div>
          </div>
          {updateResult && (
            <div style={{ border: '3px solid #000', padding: '1.5rem', background: '#f0fdf4' }}>
              <h3 className="mono-text" style={{ marginBottom: '1rem', color: '#166534' }}>✓ GRAPH UPDATED</h3>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px,1fr))', gap: '0.75rem', marginBottom: '1rem' }}>
                {[
                  ['Entities Added', updateResult.entities_added ?? updateResult.nodes_created],
                  ['Relationships Added', updateResult.relationships_added ?? updateResult.edges_created],
                  ['Merged Existing', updateResult.entities_merged ?? '—'],
                ].map(([label, val]) => (
                  <div key={label as string} style={{ border: '2px solid #000', padding: '1rem', textAlign: 'center' }}>
                    <div className="mono-text" style={{ fontSize: '0.68rem', color: '#888', marginBottom: '0.35rem' }}>{label}</div>
                    <div className="mono-text" style={{ fontSize: '1.6rem', fontWeight: 900 }}>{val ?? '—'}</div>
                  </div>
                ))}
              </div>
              {updateResult.message && (
                <p className="mono-text" style={{ fontSize: '0.82rem', color: '#555' }}>{updateResult.message}</p>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── ENTITY CHAT TAB ── */}
      {activeTab === 'entity-chat' && (
        <div>
          <div className="page-info-bar">
            <MessageSquare size={14}/>
            <span><strong>ENTITY CHAT</strong> — Select an entity from the graph and interview it. The agent synthesizes answers from its neighborhood context, relationships, and LLM-generated profile.</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '1.5rem' }}>
            {/* Config panel */}
            <div style={{ border: '3px solid #000', padding: '1.5rem' }}>
              <h3 className="mono-text" style={{ marginBottom: '1.25rem', fontSize: '0.9rem' }}>SELECT ENTITY</h3>
              <div style={{ marginBottom: '1rem' }}>
                <label className="mono-text" style={{ fontSize: '0.75rem', fontWeight: 700, color: '#888', display: 'block', marginBottom: '0.4rem' }}>ENTITY NAME</label>
                <select value={selectedEntity} onChange={e => { setSelectedEntity(e.target.value); setChatHistory([]); }}
                  style={{ width: '100%', border: '2px solid #000', padding: '0.5rem', fontFamily: 'var(--font-mono)', fontSize: '0.85rem' }}>
                  <option value="">— Select entity —</option>
                  {entities.map((n: any) => (
                    <option key={n.id} value={n.properties?.name || n.properties?.label || n.id}>
                      {n.labels?.[0]} · {n.properties?.name || n.properties?.label || n.id}
                    </option>
                  ))}
                </select>
              </div>
              <div style={{ marginBottom: '1rem' }}>
                <label className="mono-text" style={{ fontSize: '0.75rem', fontWeight: 700, color: '#888', display: 'block', marginBottom: '0.4rem' }}>EXTRA CONTEXT (OPTIONAL)</label>
                <textarea value={entityContext} onChange={e => setEntityContext(e.target.value)}
                  rows={3} placeholder="Add any additional context or constraints..."
                  style={{ width: '100%', border: '2px solid #000', padding: '0.5rem', fontFamily: 'var(--font-mono)', fontSize: '0.82rem', resize: 'vertical' }}/>
              </div>
              <button className="app-btn mono-text" style={{ width: '100%', justifyContent: 'center' }}
                onClick={() => setChatHistory([])}>CLEAR CHAT</button>
            </div>
            {/* Chat window */}
            <div style={{ border: '3px solid #000', display: 'flex', flexDirection: 'column', minHeight: 400 }}>
              <div style={{ background: '#000', color: '#fff', padding: '0.5rem 1rem', fontFamily: 'var(--font-mono)', fontSize: '0.78rem', fontWeight: 700 }}>
                {selectedEntity ? `CHATTING WITH: ${selectedEntity.toUpperCase()}` : 'SELECT AN ENTITY TO BEGIN'}
              </div>
              <div style={{ flex: 1, overflowY: 'auto', padding: '1rem', display: 'flex', flexDirection: 'column', gap: '0.75rem', minHeight: 280, maxHeight: 400 }}>
                {chatHistory.length === 0 && (
                  <div style={{ textAlign: 'center', padding: '2rem', color: '#ccc', fontFamily: 'var(--font-mono)', fontSize: '0.82rem' }}>
                    {selectedEntity ? 'Ask this entity anything…' : 'Select an entity to start chatting'}
                  </div>
                )}
                {chatHistory.map((m, i) => (
                  <div key={i} style={{
                    alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
                    background: m.role === 'user' ? '#000' : '#f3f4f6',
                    color: m.role === 'user' ? '#fff' : '#000',
                    padding: '0.6rem 1rem',
                    maxWidth: '85%',
                    fontFamily: 'var(--font-sans)', fontSize: '0.88rem', lineHeight: 1.6
                  }}>
                    {m.content}
                  </div>
                ))}
                {chatLoading && (
                  <div style={{ alignSelf: 'flex-start', background: '#f3f4f6', padding: '0.6rem 1rem', fontFamily: 'var(--font-mono)', fontSize: '0.82rem', color: '#888' }}>
                    Thinking…
                  </div>
                )}
              </div>
              <div style={{ borderTop: '2px solid #000', display: 'flex', gap: 0 }}>
                <input type="text" value={chatMsg} onChange={e => setChatMsg(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && !e.shiftKey && sendEntityChat()}
                  placeholder={selectedEntity ? 'Ask a question…' : 'Select an entity first'}
                  disabled={!selectedEntity || chatLoading}
                  style={{ flex: 1, border: 'none', padding: '0.75rem 1rem', fontFamily: 'var(--font-mono)', fontSize: '0.88rem', outline: 'none' }}/>
                <button className="app-btn" onClick={sendEntityChat} disabled={!selectedEntity || !chatMsg.trim() || chatLoading}
                  style={{ border: 'none', borderLeft: '2px solid #000', borderRadius: 0, minWidth: 80 }}>
                  SEND
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default InsightsView;
