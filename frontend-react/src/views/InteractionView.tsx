import React, { useState, useRef, useEffect, useCallback } from 'react';
import { useAuth } from '../context/AuthContext';
import {
  MessageSquare, Send, Bot, User as UserIcon, Zap,
  Menu, Info, X, ChevronDown, FileText, Plus
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

/* ── confidence colour helper ─────────────────────────────────────────────── */
const confColor = (c: number) => c >= 0.75 ? '#16a34a' : c >= 0.5 ? '#d97706' : '#dc2626';
const riskColor = (r: string) =>
  r.toLowerCase() === 'high' ? '#dc2626' : r.toLowerCase() === 'medium' ? '#d97706' : '#16a34a';

/* ─────────────────────────────────────────────────────────────────────────── */

const InteractionView: React.FC = () => {
  const { token, logout } = useAuth();

  // ── Core chat state ──────────────────────────────────────────────────────
  const [query, setQuery] = useState('');
  const [conversation, setConversation] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  // ── Document / mode state ────────────────────────────────────────────────
  const [documents, setDocuments] = useState<any[]>([]);
  const [selectedDocId, setSelectedDocId] = useState('');
  const [useGot, setUseGot] = useState(false);
  const [mode, setMode] = useState<'rag' | 'simulation'>('rag');
  const [agentId, setAgentId] = useState('');
  const [agentNodes, setAgentNodes] = useState<any[]>([]);

  // ── Thread history ────────────────────────────────────────────────────────
  const [pastConversations, setPastConversations] = useState<any[]>([]);
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null);

  // ── UI state ──────────────────────────────────────────────────────────────
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [drawerSource, setDrawerSource] = useState<any | null>(null);

  const endOfChatRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  /* ── auto-scroll ─────────────────────────────────────────────────────── */
  useEffect(() => {
    endOfChatRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [conversation]);

  /* ── initial data fetch ──────────────────────────────────────────────── */
  useEffect(() => {
    const fetchDocs = async () => {
      try {
        const res = await fetch(`${API_BASE}/documents`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        if (res.ok) setDocuments((await res.json()).documents);
      } catch {}
    };

    const fetchConvs = async () => {
      try {
        const res = await fetch(`${API_BASE}/conversations`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        if (res.ok) setPastConversations((await res.json()).conversations);
      } catch {}
    };

    const fetchAgents = async () => {
      try {
        const res = await fetch(`${API_BASE}/graph/visualization?limit=500`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        if (res.ok) setAgentNodes((await res.json()).nodes);
      } catch {}
    };

    fetchDocs();
    fetchConvs();
    fetchAgents();
  }, [token]);

  /* ── load an archived thread ─────────────────────────────────────────── */
  const loadConversation = useCallback(async (convId: string) => {
    try {
      const res = await fetch(`${API_BASE}/conversations/${convId}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setCurrentConversationId(data.id);
        setConversation(
          data.messages.map((m: any) => ({
            role: m.role,
            content: m.content,
            reasoning: m.reasoning || [],
            sources: m.sources || []
          }))
        );
        // On mobile: close sidebar after selecting
        if (window.innerWidth < 768) setSidebarOpen(false);
      }
    } catch {}
  }, [token]);

  const startNewConversation = useCallback(() => {
    setCurrentConversationId(null);
    setConversation([]);
    if (window.innerWidth < 768) setSidebarOpen(false);
    setTimeout(() => inputRef.current?.focus(), 100);
  }, []);

  /* ── submit query ────────────────────────────────────────────────────── */
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim() || loading) return;

    const userMessage = { role: 'user', content: query };
    const assistantPlaceholder = {
      role: 'assistant', content: '', sources: [], reasoning: [],
      confidence: null, drift_expanded: false
    };

    setConversation(prev => [...prev, userMessage, assistantPlaceholder]);
    setQuery('');
    setLoading(true);

    try {
      /* ── Simulation mode ──────────────────────────────────────────── */
      if (mode === 'simulation') {
        const res = await fetch(`${API_BASE}/v1/simulation/interview`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify({ agent_id: agentId, user_query: userMessage.content })
        });
        if (!res.ok) throw new Error('Simulation endpoint failed.');
        const data = await res.json();
        setConversation(prev => {
          const next = [...prev];
          next[next.length - 1] = {
            role: 'assistant',
            content: data.response,
            sources: [],
            reasoning: [`Simulated persona response for agent: ${data.agent_name || agentId}`],
            confidence: null
          };
          return next;
        });
        setLoading(false);
        return;
      }

      /* ── RAG streaming mode ─────────────────────────────────────────── */
      const reqBody: any = {
        query: userMessage.content,
        streaming: true,
        top_k: 5,
        use_got: useGot
      };
      if (selectedDocId) reqBody.document_id = selectedDocId;
      if (currentConversationId) reqBody.conversation_id = currentConversationId;

      const res = await fetch(`${API_BASE}/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(reqBody)
      });

      if (res.status === 401) { logout(); return; }
      if (!res.body) throw new Error('ReadableStream not supported.');

      const reader = res.body.getReader();
      const decoder = new TextDecoder('utf-8');

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const raw = decoder.decode(value);
        const chunks = raw.split('\n\n');

        for (const chunk of chunks) {
          if (chunk.trim() === 'data: [DONE]') { setLoading(false); break; }
          if (!chunk.startsWith('data: ')) continue;
          try {
            const data = JSON.parse(chunk.replace('data: ', ''));
            if (data.type === 'meta') {
              setCurrentConversationId(data.conversation_id);
              // Refresh thread list so it shows up in sidebar
              const convRes = await fetch(`${API_BASE}/conversations`, {
                headers: { Authorization: `Bearer ${token}` }
              });
              if (convRes.ok) setPastConversations((await convRes.json()).conversations);
              continue;
            }
            setConversation(prev => {
              const next = [...prev];
              const last = next.length - 1;
              if (data.type === 'step') {
                next[last] = { ...next[last], reasoning: [...(next[last].reasoning || []), data.content] };
              } else if (data.type === 'answer') {
                next[last] = {
                  ...next[last],
                  content: data.answer,
                  sources: data.sources,
                  confidence: data.confidence,
                  drift_expanded: data.drift_expanded || false,
                  hallucination_risk: data.hallucination_risk,
                  confidence_reasoning: data.confidence_reasoning
                };
              }
              return next;
            });
          } catch {}
        }
      }
    } catch (err) {
      console.error('Query error:', err);
      // Show error in the placeholder message
      setConversation(prev => {
        const next = [...prev];
        next[next.length - 1] = {
          ...next[next.length - 1],
          content: '⚠ An error occurred. Please check your connection or try again.'
        };
        return next;
      });
    } finally {
      setLoading(false);
    }
  };

  /* ── inline eval ─────────────────────────────────────────────────────── */
  const runInlineEval = async (msgIndex: number) => {
    const astMsg = conversation[msgIndex];
    if (astMsg.role !== 'assistant') return;

    let question = 'Contextual Query';
    for (let i = msgIndex - 1; i >= 0; i--) {
      if (conversation[i].role === 'user') { question = conversation[i].content; break; }
    }

    setConversation(prev => {
      const next = [...prev];
      next[msgIndex] = { ...next[msgIndex], evaluating: true };
      return next;
    });

    try {
      const contexts = (astMsg.sources || []).map((s: any) => s.text || JSON.stringify(s));
      const res = await fetch(`${API_BASE}/eval/score`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ question, answer: astMsg.content, contexts })
      });
      const evalData = res.ok ? await res.json() : null;
      setConversation(prev => {
        const next = [...prev];
        next[msgIndex] = { ...next[msgIndex], evaluating: false, ...(evalData ? { eval_result: evalData } : {}) };
        return next;
      });
    } catch {
      setConversation(prev => {
        const next = [...prev]; next[msgIndex] = { ...next[msgIndex], evaluating: false }; return next;
      });
    }
  };

  /* ── keyboard shortcut: Ctrl+/ or Cmd+/ to focus input ─────────────── */
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === '/') {
        e.preventDefault();
        inputRef.current?.focus();
      }
      if (e.key === 'Escape' && drawerSource) setDrawerSource(null);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [drawerSource]);

  /* ────────────────────────────────────────────────────────────────────── */
  return (
    <div className="iv-root">

      {/* ── Top header bar ──────────────────────────────────────────────── */}
      <div className="iv-header">
        {/* left: title + breadcrumb */}
        <div className="iv-header-left">
          <button
            className="iv-sidebar-toggle"
            onClick={() => setSidebarOpen(o => !o)}
            title={sidebarOpen ? 'Hide threads' : 'Show threads'}
          >
            <Menu size={18} />
          </button>
          <div>
            <h1 className="iv-title">AGENTIC INTERACTION</h1>
            <p className="mono-text iv-breadcrumb">TERMINAL // LOGIC QUERY INTERFACE</p>
          </div>
        </div>

        {/* right: controls */}
        <div className="iv-header-right">
          {/* Document filter */}
          <div className="iv-ctrl-group">
            <label className="iv-ctrl-label">SCOPE</label>
            <div className="iv-select-wrap">
              <select
                className="iv-select"
                value={selectedDocId}
                onChange={e => setSelectedDocId(e.target.value)}
              >
                <option value="">🌐 ALL DOCUMENTS</option>
                {documents.length === 0 ? (
                  <option disabled>No documents uploaded</option>
                ) : (
                  documents.map(doc => (
                    <option key={doc.id} value={doc.id}>
                      📄 {doc.filename.length > 32 ? doc.filename.substring(0, 30) + '…' : doc.filename}
                    </option>
                  ))
                )}
              </select>
              <ChevronDown size={13} className="iv-select-chevron" />
            </div>
          </div>

          {/* GoT toggle */}
          <button
            className={`iv-got-btn ${useGot ? 'active' : ''}`}
            onClick={() => setUseGot(g => !g)}
            title="Graph-of-Thought: runs all retrieval strategies in parallel for higher quality answers"
          >
            <Zap size={13} />
            GoT {useGot ? 'ON' : 'OFF'}
          </button>
        </div>
      </div>

      {/* ── Info bar ────────────────────────────────────────────────────── */}
      <div className="iv-info-bar">
        <Info size={13} />
        <span>
          <strong>Standard (Graph Logic)</strong>: multi-hop retrieval over the knowledge graph. &nbsp;
          <strong>GoT</strong>: runs all search strategies in parallel, best for complex questions. &nbsp;
          <strong>God-Mode</strong>: interviews a simulated AI persona by agent ID. &nbsp;
          Press <kbd>Ctrl+/</kbd> to focus input.
        </span>
      </div>

      {/* ── Main layout ─────────────────────────────────────────────────── */}
      <div className="iv-body">

        {/* ── Sidebar ────────────────────────────────────────────────────── */}
        <div className={`iv-sidebar ${sidebarOpen ? 'open' : 'closed'}`}>
          <button className="iv-new-thread" onClick={startNewConversation} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Plus size={16} /> NEW THREAD
          </button>

          <div className="iv-thread-list">
            <div className="iv-thread-header">ARCHIVED THREADS</div>
            {pastConversations.length === 0 ? (
              <div className="iv-empty-threads">No prior sequences</div>
            ) : (
              pastConversations.map(conv => (
                <div
                  key={conv.id}
                  className={`iv-thread-item ${currentConversationId === conv.id ? 'active' : ''}`}
                  onClick={() => loadConversation(conv.id)}
                >
                  <div className="iv-thread-title">
                    <MessageSquare size={12} style={{ display: 'inline', marginRight: '6px', verticalAlign: '-1px' }} />
                    {conv.title || 'Untitled thread'}
                  </div>
                  <div className="iv-thread-date">
                    {new Date(conv.created_at).toLocaleDateString()}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* ── Chat panel ──────────────────────────────────────────────────── */}
        <div className="iv-chat-panel">

          {/* messages */}
          <div className="iv-messages">
            {conversation.length === 0 ? (
              <div className="iv-empty-chat">
                <Bot size={40} style={{ opacity: 0.15 }} />
                <span>INITIALIZE QUERY SEQUENCE TO BEGIN GRAPH ANALYSIS…</span>
                <div className="iv-empty-hints">
                  <span>Try: "Summarize the main entities in this document"</span>
                  <span>Try: "What relationships exist between X and Y?"</span>
                  <span>Try: "Find all mentions of [topic] and their context"</span>
                </div>
              </div>
            ) : (
              conversation.map((msg, idx) => (
                <div key={idx} className={`iv-msg-row ${msg.role}`}>
                  <div className="iv-msg-avatar">
                    {msg.role === 'user' ? <UserIcon size={18} /> : <Bot size={18} />}
                  </div>

                  <div className="iv-msg-card">
                    {/* message header */}
                    <div className="iv-msg-header">
                      <span className="iv-msg-role">
                        {msg.role === 'user' ? 'YOU' : 'GRAPH REASONING SYSTEM'}
                      </span>

                      {msg.role === 'assistant' && msg.confidence != null && (
                        <div className="iv-msg-badges">
                          {msg.drift_expanded && (
                            <span className="iv-badge" style={{ background: '#3b82f6' }}>
                              DRIFT EXPANDED
                            </span>
                          )}
                          <span
                            className="iv-badge"
                            style={{ background: confColor(msg.confidence) }}
                            title={`Confidence: ${(msg.confidence * 100).toFixed(1)}%`}
                          >
                            {(msg.confidence * 100).toFixed(0)}% CONF
                          </span>
                          {msg.hallucination_risk && (
                            <span
                              className="iv-badge-outline"
                              style={{ color: riskColor(msg.hallucination_risk), borderColor: riskColor(msg.hallucination_risk) }}
                              title={msg.confidence_reasoning}
                            >
                              RISK: {msg.hallucination_risk.toUpperCase()}
                            </span>
                          )}
                        </div>
                      )}
                    </div>

                    {/* reasoning steps */}
                    {msg.role === 'assistant' && msg.reasoning?.length > 0 && (
                      <div className="iv-reasoning">
                        {msg.reasoning.map((step: string, si: number) => (
                          <div key={si} className="iv-reasoning-step">
                            <span className="iv-step-idx">{si + 1}</span>
                            <span>{step}</span>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* content */}
                    <div className="iv-msg-content">
                      {msg.role === 'assistant' && msg.content === '' && loading && idx === conversation.length - 1 ? (
                        <span className="iv-cursor">██</span>
                      ) : (
                        <div className="iv-markdown">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                        </div>
                      )}
                    </div>

                    {/* sources */}
                    {msg.sources?.length > 0 && (
                      <div className="iv-sources">
                        <div className="iv-sources-top">
                          <div className="iv-sources-label">
                            SOURCES:
                            <div className="iv-source-chips">
                              {msg.sources
                                .filter((v: any, i: number, a: any[]) =>
                                  a.findIndex(t => (t.metadata?.file_name || t.document_id) === (v.metadata?.file_name || v.document_id)) === i
                                )
                                .map((s: any, si: number) => (
                                  <button
                                    key={si}
                                    className="iv-source-chip"
                                    onClick={() => setDrawerSource(s)}
                                    title="Click to view source text"
                                  >
                                    {s.metadata?.file_name || s.document_id}
                                  </button>
                                ))}
                            </div>
                          </div>

                          {msg.role === 'assistant' && !msg.eval_result && (
                            <button
                              className="iv-eval-btn"
                              onClick={() => runInlineEval(idx)}
                              disabled={msg.evaluating}
                            >
                              {msg.evaluating ? 'EVALUATING…' : 'EVALUATE QUALITY'}
                            </button>
                          )}
                        </div>

                        {/* eval results */}
                        {msg.eval_result && (
                          <div className="iv-eval-result">
                            <div className="iv-eval-title">EVALUATION RESULTS</div>
                            <div className="iv-eval-grid">
                              {[
                                { label: 'OVERALL', value: msg.eval_result.overall_score ?? (msg.eval_result.faithfulness * 0.5 + (msg.eval_result.answer_relevancy || msg.eval_result.relevancy || 0) * 0.3 + (msg.eval_result.context_precision || msg.eval_result.precision || 0) * 0.2) },
                                { label: 'FAITHFULNESS', value: msg.eval_result.faithfulness },
                                { label: 'RELEVANCY', value: msg.eval_result.answer_relevancy ?? msg.eval_result.relevancy },
                                { label: 'PRECISION', value: msg.eval_result.context_precision ?? msg.eval_result.precision }
                              ].map((m, mi) => {
                                const val = typeof m.value === 'number' ? m.value : 0;
                                const pct = Math.round(val * 100);
                                return (
                                  <div key={mi} className="iv-eval-metric">
                                    <div className="iv-eval-label">{m.label}</div>
                                    <div className="iv-eval-bar-wrap">
                                      <div className="iv-eval-bar" style={{ width: `${pct}%`, background: confColor(val) }} />
                                    </div>
                                    <div className="iv-eval-pct" style={{ color: confColor(val) }}>{pct}%</div>
                                  </div>
                                );
                              })}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              ))
            )}
            <div ref={endOfChatRef} />
          </div>

          {/* ── Input area ─────────────────────────────────────────────── */}
          <form className="iv-input-area" onSubmit={handleSubmit}>
            {/* Mode + agent ID row */}
            <div className="iv-input-controls">
              <div className="iv-ctrl-group">
                <label className="iv-ctrl-label">INTERACTION MODE</label>
                <div className="iv-select-wrap">
                  <select
                    className="iv-select iv-select-dark"
                    value={mode}
                    onChange={e => setMode(e.target.value as 'rag' | 'simulation')}
                  >
                    <option value="rag">STANDARD (GRAPH LOGIC)</option>
                    <option value="simulation">GOD-MODE (PERSONA INTERVIEW)</option>
                  </select>
                  <ChevronDown size={13} className="iv-select-chevron" />
                </div>
              </div>

              {mode === 'simulation' && (
                <div className="iv-ctrl-group">
                  <label className="iv-ctrl-label" style={{ color: '#f59e0b' }}>TARGET PERSONA (GOD MODE)</label>
                  <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                    <div className="iv-select-wrap">
                      <select
                        className="iv-select iv-select-dark"
                        style={{ borderColor: '#f59e0b', width: '200px' }}
                        value={agentNodes.some(n => n.id === agentId) ? agentId : ""}
                        onChange={e => setAgentId(e.target.value)}
                      >
                        <option value="" disabled>Select from graph...</option>
                        {agentNodes.map(n => (
                          <option key={n.id} value={n.id}>
                            [{n.type}] {n.label.length > 20 ? n.label.substring(0, 18) + '…' : n.label}
                          </option>
                        ))}
                      </select>
                      <ChevronDown size={13} className="iv-select-chevron" />
                    </div>
                    <span style={{ color: '#666', fontSize: '0.65rem', fontFamily: 'var(--font-mono)' }}>OR</span>
                    <input
                      type="text"
                      value={agentId}
                      onChange={e => setAgentId(e.target.value)}
                      placeholder="Paste UUID..."
                      className="iv-agent-input"
                      style={{ width: '120px' }}
                    />
                  </div>
                </div>
              )}

              {/* Document scope chip (shows when doc selected) */}
              {selectedDocId && (
                <div className="iv-scope-chip">
                  <FileText size={12} />
                  <span>{documents.find(d => d.id === selectedDocId)?.filename?.substring(0, 24) || 'Filtered'}</span>
                  <button type="button" onClick={() => setSelectedDocId('')} title="Clear filter">
                    <X size={11} />
                  </button>
                </div>
              )}
            </div>

            {/* Text input row */}
            <div className="iv-input-row">
              <span className="iv-prompt-marker">&gt;</span>
              <input
                ref={inputRef}
                type="text"
                value={query}
                onChange={e => setQuery(e.target.value)}
                disabled={loading || (mode === 'simulation' && !agentId)}
                placeholder={
                  mode === 'simulation'
                    ? agentId ? 'INTERVIEW AGENT…' : 'ENTER AGENT ID ABOVE FIRST…'
                    : 'ENTER QUERY DIRECTIVE…'
                }
                className="iv-text-input"
                autoComplete="off"
              />
              <button
                type="submit"
                className="iv-send-btn"
                disabled={!query.trim() || loading || (mode === 'simulation' && !agentId)}
                title="Send (Enter)"
              >
                {loading ? (
                  <span className="iv-spinner" />
                ) : (
                  <Send size={18} />
                )}
              </button>
            </div>
          </form>
        </div>
      </div>

      {/* ── Source detail drawer ─────────────────────────────────────────── */}
      {drawerSource && (
        <div className="iv-drawer-overlay" onClick={() => setDrawerSource(null)}>
          <div className="iv-drawer" onClick={e => e.stopPropagation()}>
            <div className="iv-drawer-header">
              <h3 className="mono-text">SOURCE DETAIL</h3>
              <button className="iv-drawer-close" onClick={() => setDrawerSource(null)}>
                <X size={16} />
              </button>
            </div>
            <div className="iv-drawer-body">
              <div className="iv-drawer-meta">
                <div className="iv-meta-row">
                  <span className="iv-meta-key">DOCUMENT</span>
                  <span>{drawerSource.metadata?.file_name || drawerSource.document_id || '—'}</span>
                </div>
                <div className="iv-meta-row">
                  <span className="iv-meta-key">RELEVANCE</span>
                  <span>{drawerSource.score != null ? (drawerSource.score * 100).toFixed(1) + '%' : 'N/A'}</span>
                </div>
                <div className="iv-meta-row">
                  <span className="iv-meta-key">CHUNK ID</span>
                  <span style={{ wordBreak: 'break-all' }}>{drawerSource.id || '—'}</span>
                </div>
              </div>
              <hr className="iv-drawer-divider" />
              <div className="iv-drawer-text">{drawerSource.text || 'No text available.'}</div>
            </div>
          </div>
        </div>
      )}

      {/* ── Scoped styles ────────────────────────────────────────────────── */}
      <style>{`
        /* ── Root layout ───────────────────────────────────────────── */
        .iv-root {
          height: calc(100vh - 62px);
          display: flex;
          flex-direction: column;
          background: var(--bg-color);
          overflow: hidden;
        }

        /* ── Header ───────────────────────────────────────────────── */
        .iv-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 1rem;
          padding: 0.65rem 1.5rem;
          border-bottom: 3px solid var(--border-color);
          flex-shrink: 0;
          flex-wrap: wrap;
        }

        .iv-header-left {
          display: flex;
          align-items: center;
          gap: 0.75rem;
          min-width: 0;
        }

        .iv-title {
          font-size: 1rem;
          letter-spacing: 2px;
          margin: 0;
          line-height: 1.1;
        }

        .iv-breadcrumb {
          font-size: 0.7rem;
          color: var(--muted-color);
          margin: 0;
        }

        .iv-sidebar-toggle {
          border: 2px solid var(--border-color);
          background: var(--bg-color);
          color: var(--text-color);
          width: 34px;
          height: 34px;
          display: flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          flex-shrink: 0;
          transition: all 0.13s;
        }
        .iv-sidebar-toggle:hover { background: var(--text-color); color: var(--bg-color); }

        .iv-header-right {
          display: flex;
          align-items: flex-end;
          gap: 0.75rem;
          flex-wrap: wrap;
        }

        /* ── Control group ─────────────────────────────────────────── */
        .iv-ctrl-group {
          display: flex;
          flex-direction: column;
          gap: 2px;
        }
        .iv-ctrl-label {
          font-family: var(--font-mono);
          font-size: 0.6rem;
          font-weight: 700;
          color: var(--muted-color);
          letter-spacing: 1px;
          text-transform: uppercase;
        }

        /* ── Uniform select ────────────────────────────────────────── */
        .iv-select-wrap {
          position: relative;
          display: inline-flex;
          align-items: center;
        }
        .iv-select-chevron {
          position: absolute;
          right: 8px;
          pointer-events: none;
          color: var(--muted-color);
        }
        .iv-select {
          font-family: var(--font-mono);
          font-size: 0.82rem;
          font-weight: 700;
          border: 2px solid var(--border-color);
          background: var(--bg-color);
          color: var(--text-color);
          padding: 0.32rem 2rem 0.32rem 0.65rem;
          cursor: pointer;
          appearance: none;
          -webkit-appearance: none;
          outline: none;
          max-width: 260px;
        }
        .iv-select:focus { box-shadow: 2px 2px 0 var(--border-color); }

        /* Dark variant (input area) */
        .iv-select-dark {
          background: #111;
          color: #e5e7eb;
          border-color: #333;
        }
        .iv-select-dark option { background: #111; color: #e5e7eb; }

        /* ── GoT button ────────────────────────────────────────────── */
        .iv-got-btn {
          display: inline-flex;
          align-items: center;
          gap: 5px;
          border: 2px solid var(--border-color);
          background: var(--bg-color);
          color: var(--text-color);
          font-family: var(--font-mono);
          font-size: 0.75rem;
          font-weight: 700;
          padding: 0.32rem 0.75rem;
          cursor: pointer;
          transition: all 0.13s;
          white-space: nowrap;
        }
        .iv-got-btn.active { background: #000; color: #fff; border-color: #000; }
        .iv-got-btn:hover:not(.active) { background: #f3f4f6; }

        /* ── Info bar ──────────────────────────────────────────────── */
        .iv-info-bar {
          display: flex;
          align-items: flex-start;
          gap: 0.5rem;
          padding: 0.45rem 1.5rem;
          background: var(--surface-color);
          border-bottom: 1px solid #e5e5e5;
          font-size: 0.75rem;
          color: var(--muted-color);
          line-height: 1.5;
          flex-shrink: 0;
        }
        .iv-info-bar strong { color: var(--text-color); }
        .iv-info-bar kbd {
          background: #e5e7eb; border: 1px solid #d1d5db;
          border-radius: 3px; padding: 0 4px;
          font-family: var(--font-mono); font-size: 0.7rem;
        }

        /* ── Body: sidebar + chat ──────────────────────────────────── */
        .iv-body {
          display: flex;
          flex: 1;
          min-height: 0;
          overflow: hidden;
        }

        /* ── Sidebar ───────────────────────────────────────────────── */
        .iv-sidebar {
          display: flex;
          flex-direction: column;
          border-right: 3px solid var(--border-color);
          background: var(--bg-color);
          flex-shrink: 0;
          overflow: hidden;
          transition: width 0.22s ease;
        }
        .iv-sidebar.open  { width: 220px; }
        .iv-sidebar.closed { width: 0; border-right: none; }

        .iv-new-thread {
          width: 100%;
          border: none;
          border-bottom: 3px solid var(--border-color);
          padding: 0.9rem 1rem;
          background: #000;
          color: #fff;
          font-family: var(--font-mono);
          font-size: 0.82rem;
          font-weight: 700;
          letter-spacing: 1px;
          cursor: pointer;
          flex-shrink: 0;
          text-align: left;
          transition: background 0.13s;
          white-space: nowrap;
        }
        .iv-new-thread:hover { background: #222; }

        .iv-thread-list {
          flex: 1;
          overflow-y: auto;
          padding: 0.75rem;
        }

        .iv-thread-header {
          font-family: var(--font-mono);
          font-size: 0.6rem;
          font-weight: 700;
          color: var(--muted-color);
          letter-spacing: 1px;
          border-bottom: 1px dotted var(--border-color);
          padding-bottom: 0.4rem;
          margin-bottom: 0.6rem;
          white-space: nowrap;
        }

        .iv-thread-item {
          padding: 0.6rem 0.7rem;
          border: 1.5px solid var(--border-color);
          cursor: pointer;
          margin-bottom: 0.4rem;
          transition: background 0.13s;
        }
        .iv-thread-item:hover, .iv-thread-item.active {
          background: var(--text-color);
          color: var(--bg-color);
          border-color: var(--text-color);
        }
        .iv-thread-title {
          font-family: var(--font-mono);
          font-size: 0.78rem;
          font-weight: 600;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .iv-thread-date {
          font-family: var(--font-mono);
          font-size: 0.65rem;
          opacity: 0.65;
          margin-top: 3px;
        }
        .iv-empty-threads {
          font-family: var(--font-mono);
          color: #bbb;
          font-size: 0.78rem;
          text-align: center;
          padding: 1.5rem 0;
        }

        /* ── Chat panel ────────────────────────────────────────────── */
        .iv-chat-panel {
          flex: 1;
          min-width: 0;
          display: flex;
          flex-direction: column;
          overflow: hidden;
        }

        /* ── Messages ──────────────────────────────────────────────── */
        .iv-messages {
          flex: 1;
          overflow-y: auto;
          padding: 1.5rem;
          display: flex;
          flex-direction: column;
          gap: 1.5rem;
          scroll-behavior: smooth;
        }

        .iv-empty-chat {
          flex: 1;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 1rem;
          color: var(--muted-color);
          font-family: var(--font-mono);
          font-size: 0.88rem;
          letter-spacing: 1.5px;
          text-align: center;
          padding: 3rem;
        }
        .iv-empty-hints {
          display: flex;
          flex-direction: column;
          gap: 0.4rem;
          margin-top: 0.75rem;
          font-size: 0.72rem;
          opacity: 0.6;
        }

        /* ── Message row ─────────────────────────────────────────── */
        .iv-msg-row {
          display: flex;
          gap: 1rem;
          align-items: flex-start;
          max-width: 90%;
        }
        .iv-msg-row.user {
          align-self: flex-end;
          flex-direction: row-reverse;
          max-width: 72%;
        }
        .iv-msg-row.assistant { align-self: flex-start; max-width: 90%; }

        .iv-msg-avatar {
          width: 36px;
          height: 36px;
          border: 2px solid var(--border-color);
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
          background: var(--bg-color);
        }
        .iv-msg-row.assistant .iv-msg-avatar {
          background: #000;
          color: #fff;
          border-color: #000;
        }

        .iv-msg-card {
          flex: 1;
          border: 2px solid var(--border-color);
          background: var(--bg-color);
          min-width: 0;
          box-shadow: 4px 4px 0 rgba(0,0,0,0.05);
        }
        .iv-msg-row.assistant .iv-msg-card {
          border-left: 4px solid #000;
        }
        .iv-msg-row.user .iv-msg-card {
          border-color: #000;
          background: #f8f8f8;
          border-right: 4px solid #000;
        }

        .iv-msg-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          flex-wrap: wrap;
          gap: 0.5rem;
          padding: 0.5rem 0.85rem;
          border-bottom: 1px dotted var(--border-color);
          background: var(--surface-color);
        }
        .iv-msg-role {
          font-family: var(--font-mono);
          font-size: 0.68rem;
          font-weight: 700;
          letter-spacing: 1px;
          color: var(--muted-color);
        }

        .iv-msg-badges {
          display: flex;
          align-items: center;
          gap: 0.4rem;
          flex-wrap: wrap;
        }
        .iv-badge {
          font-family: var(--font-mono);
          font-size: 0.65rem;
          font-weight: 700;
          color: #fff;
          padding: 1px 7px;
          letter-spacing: 0.3px;
        }
        .iv-badge-outline {
          font-family: var(--font-mono);
          font-size: 0.65rem;
          font-weight: 700;
          padding: 1px 6px;
          border: 1.5px solid;
          cursor: help;
        }

        /* ── Reasoning chain ─────────────────────────────────────── */
        .iv-reasoning {
          padding: 0.75rem 0.85rem;
          background: #fafafa;
          border-bottom: 1px dotted var(--border-color);
          display: flex;
          flex-direction: column;
          gap: 3px;
        }
        .iv-reasoning-step {
          display: flex;
          gap: 0.5rem;
          font-family: var(--font-mono);
          font-size: 0.75rem;
          color: #555;
          line-height: 1.5;
        }
        .iv-step-idx {
          background: #000;
          color: #fff;
          font-size: 0.6rem;
          font-weight: 700;
          width: 16px;
          height: 16px;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
          margin-top: 2px;
        }

        /* ── Message content ─────────────────────────────────────── */
        .iv-msg-content {
          padding: 0.85rem;
        }

        .iv-markdown { font-family: var(--font-sans); font-size: 0.97rem; line-height: 1.8; }
        .iv-markdown p { margin-bottom: 0.75rem; }
        .iv-markdown p:last-child { margin-bottom: 0; }
        .iv-markdown ul, .iv-markdown ol { margin-bottom: 0.75rem; padding-left: 1.5rem; }
        .iv-markdown li { margin-bottom: 0.2rem; }
        .iv-markdown h1, .iv-markdown h2, .iv-markdown h3 { font-family: var(--font-display); margin: 1rem 0 0.5rem; }
        .iv-markdown code { font-family: var(--font-mono); background: #f3f4f6; padding: 1px 5px; font-size: 0.85em; }
        .iv-markdown pre { background: #1e293b; color: #e2e8f0; padding: 1rem; overflow-x: auto; margin-bottom: 0.75rem; }
        .iv-markdown pre code { background: transparent; color: inherit; padding: 0; }
        .iv-markdown table { border-collapse: collapse; width: 100%; margin-bottom: 0.75rem; font-size: 0.9rem; }
        .iv-markdown th, .iv-markdown td { border: 1px solid var(--border-color); padding: 0.4rem 0.6rem; }
        .iv-markdown th { background: var(--surface-color); font-family: var(--font-mono); font-size: 0.75rem; }
        .iv-markdown blockquote { border-left: 3px solid #000; margin: 0 0 0.75rem; padding: 0.5rem 0.75rem; color: #555; background: #fafafa; }

        .iv-cursor { animation: blink 0.9s step-end infinite; font-size: 1.1rem; }
        @keyframes blink { 50% { opacity: 0; } }

        /* ── Sources ──────────────────────────────────────────────── */
        .iv-sources {
          padding: 0.65rem 0.85rem;
          border-top: 1px dashed var(--border-color);
          background: #fafafa;
        }
        .iv-sources-top {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 0.75rem;
          flex-wrap: wrap;
        }
        .iv-sources-label {
          font-family: var(--font-mono);
          font-size: 0.7rem;
          font-weight: 700;
          color: var(--muted-color);
          display: flex;
          align-items: center;
          gap: 0.5rem;
          flex-wrap: wrap;
        }
        .iv-source-chips { display: flex; flex-wrap: wrap; gap: 4px; }
        .iv-source-chip {
          background: var(--bg-color);
          border: 1px solid var(--border-color);
          padding: 2px 8px;
          cursor: pointer;
          font-family: var(--font-mono);
          font-size: 0.7rem;
          transition: all 0.12s;
        }
        .iv-source-chip:hover { background: #000; color: #fff; border-color: #000; }

        .iv-eval-btn {
          font-family: var(--font-mono);
          font-size: 0.68rem;
          font-weight: 700;
          border: 2px solid #000;
          background: var(--bg-color);
          color: var(--text-color);
          padding: 2px 10px;
          cursor: pointer;
          letter-spacing: 0.5px;
          white-space: nowrap;
          transition: all 0.12s;
          flex-shrink: 0;
        }
        .iv-eval-btn:hover:not(:disabled) { background: #000; color: #fff; }
        .iv-eval-btn:disabled { opacity: 0.4; cursor: not-allowed; }

        /* ── Eval results ─────────────────────────────────────────── */
        .iv-eval-result {
          margin-top: 0.65rem;
          padding: 0.75rem;
          border: 1px solid var(--border-color);
          background: var(--bg-color);
        }
        .iv-eval-title {
          font-family: var(--font-mono);
          font-size: 0.65rem;
          font-weight: 700;
          color: var(--muted-color);
          letter-spacing: 1px;
          margin-bottom: 0.6rem;
        }
        .iv-eval-grid { display: flex; flex-direction: column; gap: 0.4rem; }
        .iv-eval-metric { display: flex; align-items: center; gap: 0.6rem; }
        .iv-eval-label { font-family: var(--font-mono); font-size: 0.65rem; color: #666; width: 80px; flex-shrink: 0; }
        .iv-eval-bar-wrap { flex: 1; height: 5px; background: #e5e7eb; }
        .iv-eval-bar { height: 100%; transition: width 0.4s ease; }
        .iv-eval-pct { font-family: var(--font-mono); font-size: 0.72rem; font-weight: 700; width: 36px; text-align: right; }

        /* ── Input area ───────────────────────────────────────────── */
        .iv-input-area {
          border-top: 3px solid var(--border-color);
          background: #000;
          flex-shrink: 0;
          display: flex;
          flex-direction: column;
        }

        .iv-input-controls {
          display: flex;
          align-items: flex-end;
          gap: 1rem;
          padding: 0.55rem 1rem 0.45rem;
          border-bottom: 1px dotted #333;
          flex-wrap: wrap;
        }
        .iv-input-controls .iv-ctrl-label { color: #888; }
        .iv-input-controls .iv-select-chevron { color: #888; }

        .iv-agent-input {
          font-family: var(--font-mono);
          font-size: 0.82rem;
          font-weight: 600;
          border: 2px solid #444;
          background: #111;
          color: #fff;
          padding: 0.32rem 0.65rem;
          width: 160px;
          outline: none;
        }
        .iv-agent-input:focus { border-color: #f59e0b; box-shadow: 2px 2px 0 #f59e0b; }
        .iv-agent-input::placeholder { color: #888; }

        .iv-scope-chip {
          display: inline-flex;
          align-items: center;
          gap: 5px;
          border: 1.5px solid #444;
          background: #111;
          color: #aaa;
          font-family: var(--font-mono);
          font-size: 0.7rem;
          padding: 3px 8px;
          align-self: flex-end;
          margin-bottom: 2px;
        }
        .iv-scope-chip button {
          background: none;
          border: none;
          color: #aaa;
          cursor: pointer;
          padding: 0;
          display: flex;
          align-items: center;
        }
        .iv-scope-chip button:hover { color: #ef4444; }

        /* ── Text input row ───────────────────────────────────────── */
        .iv-input-row {
          display: flex;
          align-items: center;
          padding: 0 0.5rem 0 1rem;
          gap: 0.5rem;
          min-height: 56px;
        }

        .iv-prompt-marker {
          font-family: var(--font-mono);
          font-size: 1.3rem;
          font-weight: 700;
          color: #fff;
          flex-shrink: 0;
          user-select: none;
        }

        .iv-text-input {
          flex: 1;
          background: transparent;
          border: none;
          outline: none;
          font-family: var(--font-mono);
          font-size: 1rem;
          color: #fff;
          padding: 0.75rem 0.5rem;
          caret-color: #fff;
        }
        .iv-text-input::placeholder { color: #666; }
        .iv-text-input:disabled { opacity: 0.4; cursor: not-allowed; }

        .iv-send-btn {
          width: 44px;
          height: 44px;
          border: 2px solid #444;
          background: #111;
          color: #888;
          display: flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          flex-shrink: 0;
          transition: all 0.13s;
        }
        .iv-send-btn:hover:not(:disabled) { background: #fff; color: #000; border-color: #fff; }
        .iv-send-btn:disabled { opacity: 0.35; cursor: not-allowed; pointer-events: none; }

        .iv-spinner {
          width: 18px;
          height: 18px;
          border: 2px solid #444;
          border-top-color: #fff;
          border-radius: 50%;
          animation: spin 0.8s linear infinite;
        }
        @keyframes spin { 100% { transform: rotate(360deg); } }

        /* ── Source drawer (modal style) ─────────────────────────── */
        .iv-drawer-overlay {
          position: fixed;
          inset: 0;
          background: rgba(0,0,0,0.4);
          z-index: 999;
          display: flex;
          align-items: stretch;
          justify-content: flex-end;
        }

        .iv-drawer {
          width: min(420px, 95vw);
          background: var(--bg-color);
          border-left: 3px solid var(--border-color);
          display: flex;
          flex-direction: column;
          animation: slideIn 0.22s ease-out;
          box-shadow: -8px 0 32px rgba(0,0,0,0.15);
        }
        @keyframes slideIn { from { transform: translateX(100%); } to { transform: translateX(0); } }

        .iv-drawer-header {
          padding: 1rem 1.25rem;
          border-bottom: 3px solid var(--border-color);
          background: var(--surface-color);
          display: flex;
          align-items: center;
          justify-content: space-between;
          flex-shrink: 0;
        }
        .iv-drawer-header h3 { margin: 0; font-size: 0.85rem; }

        .iv-drawer-close {
          width: 32px;
          height: 32px;
          border: 2px solid var(--border-color);
          background: var(--bg-color);
          color: var(--text-color);
          display: flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          transition: all 0.12s;
        }
        .iv-drawer-close:hover { background: #000; color: #fff; border-color: #000; }

        .iv-drawer-body {
          flex: 1;
          overflow-y: auto;
          padding: 1.25rem;
        }

        .iv-drawer-meta { margin-bottom: 1rem; }
        .iv-meta-row {
          display: flex;
          gap: 0.75rem;
          margin-bottom: 0.5rem;
          font-family: var(--font-mono);
          font-size: 0.8rem;
          align-items: flex-start;
        }
        .iv-meta-key { font-weight: 700; color: var(--muted-color); min-width: 80px; flex-shrink: 0; }

        .iv-drawer-divider {
          border: none;
          border-top: 1px dashed var(--border-color);
          margin: 0.75rem 0 1rem;
        }

        .iv-drawer-text {
          font-family: var(--font-mono);
          font-size: 0.82rem;
          line-height: 1.7;
          white-space: pre-wrap;
          color: #444;
        }

        /* ── Responsive ──────────────────────────────────────────── */
        @media (max-width: 768px) {
          .iv-header { padding: 0.5rem 0.75rem; }
          .iv-title { font-size: 0.88rem; letter-spacing: 1px; }
          .iv-info-bar { display: none; }
          .iv-sidebar.open { width: 200px; }
          .iv-messages { padding: 1rem 0.75rem; }
          .iv-msg-row { max-width: 100% !important; }
          .iv-msg-avatar { width: 28px; height: 28px; }
          .iv-msg-card { font-size: 0.9rem; }
          .iv-msg-content { padding: 0.6rem; }
          .iv-input-controls { padding: 0.4rem 0.75rem; gap: 0.5rem; }
          .iv-input-row { min-height: 46px; }
          .iv-text-input { font-size: 0.9rem; }
          .iv-select { max-width: 200px; }
        }

        @media (max-width: 480px) {
          .iv-sidebar.open { 
            position: absolute;
            left: 0; top: 0; bottom: 0;
            z-index: 50;
            border-right: 3px solid #000;
            box-shadow: 4px 0 20px rgba(0,0,0,0.2);
          }
          .iv-msg-row.user { max-width: 90% !important; }
        }
      `}</style>
    </div>
  );
};

export default InteractionView;
