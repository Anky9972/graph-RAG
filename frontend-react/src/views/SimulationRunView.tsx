import React, { useEffect, useState, useCallback, useRef } from 'react';
import { useAuth } from '../context/AuthContext';
import GraphCanvas, { DEFAULT_OPTIONS } from '../components/GraphCanvas';
import type { GraphOptions, GraphCanvasHandle } from '../components/GraphCanvas';
import {
  RefreshCw, Play, Database, Info, Maximize2, Minimize2,
  Download, SlidersHorizontal, X, Layers, Tag, Search,
  Image, GitBranch, HelpCircle
} from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

const TYPE_COLORS = [
  '#e63946','#457b9d','#2a9d8f','#e9c46a','#f4a261',
  '#6a4c93','#1982c4','#8ac926','#ff595e','#6a994e',
  '#bc4749','#a8dadc'
];

const SimulationRunView: React.FC = () => {
  const { token, logout } = useAuth();
  const [graphData, setGraphData] = useState<{ nodes: any[]; edges: any[] }>({ nodes: [], edges: [] });
  const [loading, setLoading] = useState(false);
  const [limit, setLimit] = useState(100);
  const [documents, setDocuments] = useState<any[]>([]);
  const [selectedDocId, setSelectedDocId] = useState('');
  const [nodeCount, setNodeCount] = useState(0);
  const [edgeCount, setEdgeCount] = useState(0);

  // UI state
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [showPanel, setShowPanel] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [showSearch, setShowSearch] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [highlightNodeIds, setHighlightNodeIds] = useState<Set<string>>(new Set());

  // Graph options
  const [options, setOptions] = useState<GraphOptions>({ ...DEFAULT_OPTIONS });

  // Canvas handle
  const canvasRef = useRef<GraphCanvasHandle>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Derived legend
  const typeLegend = React.useMemo(() => {
    const types = [...new Set(graphData.nodes.map(n => n.type || 'Unknown'))];
    return types.map((t, i) => ({ type: t, color: TYPE_COLORS[i % TYPE_COLORS.length] }));
  }, [graphData.nodes]);

  // Graph stats
  const degreeStats = React.useMemo(() => {
    if (!graphData.nodes.length) return null;
    const degMap = new Map<string, number>();
    graphData.nodes.forEach(n => degMap.set(n.id, 0));
    graphData.edges.forEach(e => {
      degMap.set(e.source, (degMap.get(e.source) || 0) + 1);
      degMap.set(e.target, (degMap.get(e.target) || 0) + 1);
    });
    const degrees = [...degMap.values()];
    const avg = degrees.reduce((a, b) => a + b, 0) / degrees.length;
    const max = Math.max(...degrees);
    const hubs = graphData.nodes.filter(n => (degMap.get(n.id) || 0) >= avg * 2);
    return { avg: avg.toFixed(1), max, hubs: hubs.slice(0, 5) };
  }, [graphData]);

  // ── Data fetching ──────────────────────────────────────────────────────
  const fetchDocuments = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/documents`, { headers: { Authorization: `Bearer ${token}` } });
      if (res.ok) setDocuments((await res.json()).documents);
    } catch {}
  }, [token]);

  const fetchGraph = useCallback(async (docId: string, nodeLimit: number) => {
    setLoading(true);
    try {
      const url = new URL(`${API_BASE}/graph/visualization`);
      url.searchParams.append('limit', nodeLimit.toString());
      if (docId) url.searchParams.append('document_id', docId);
      const res = await fetch(url.toString(), { headers: { Authorization: `Bearer ${token}` } });
      if (res.status === 401) { logout(); return; }
      if (res.ok) {
        const data = await res.json();
        setGraphData(data);
        setNodeCount(data.nodes?.length ?? 0);
        setEdgeCount(data.edges?.length ?? 0);
        setHighlightNodeIds(new Set());
        setSearchQuery('');
      }
    } catch (err) {
      console.error('Graph fetch error:', err);
    } finally {
      setLoading(false);
    }
  }, [token, logout]);

  const handleNodeUpdate = useCallback(async (nodeId: string, newName: string) => {
    try {
      const res = await fetch(`${API_BASE}/entities/${nodeId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ name: newName })
      });
      if (res.status === 401) { logout(); return; }
      if (res.ok) {
        setGraphData(prev => ({
          ...prev,
          nodes: prev.nodes.map(n => n.id === nodeId ? { ...n, label: newName } : n)
        }));
      }
    } catch {}
  }, [token, logout]);

  useEffect(() => { fetchDocuments(); }, [fetchDocuments]);
  useEffect(() => { fetchGraph(selectedDocId, limit); }, [fetchGraph, selectedDocId, limit]);

  // Search handler
  const handleSearch = useCallback((q: string) => {
    setSearchQuery(q);
    if (!q.trim()) {
      setHighlightNodeIds(new Set());
      return;
    }
    const lower = q.toLowerCase();
    const matched = new Set(
      graphData.nodes
        .filter(n =>
          n.label?.toLowerCase().includes(lower) ||
          n.type?.toLowerCase().includes(lower)
        )
        .map(n => n.id)
    );
    setHighlightNodeIds(matched);
    // Zoom to first match
    if (matched.size > 0) {
      const firstId = [...matched][0];
      canvasRef.current?.highlightNode(firstId);
    }
  }, [graphData.nodes]);

  // ── Fullscreen ─────────────────────────────────────────────────────────
  const toggleFullscreen = useCallback(() => {
    if (!isFullscreen) {
      containerRef.current?.requestFullscreen?.().catch(() => setIsFullscreen(true));
    } else {
      document.exitFullscreen?.().catch(() => setIsFullscreen(false));
    }
    setIsFullscreen(f => !f);
  }, [isFullscreen]);

  useEffect(() => {
    const handler = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener('fullscreenchange', handler);
    return () => document.removeEventListener('fullscreenchange', handler);
  }, []);

  // ── Option helpers ─────────────────────────────────────────────────────
  const setOpt = <K extends keyof GraphOptions>(key: K, val: GraphOptions[K]) =>
    setOptions(prev => ({ ...prev, [key]: val }));

  const selectedDocName = documents.find(d => d.id === selectedDocId)?.filename || '';

  return (
    <div ref={containerRef} className={`simulation-root${isFullscreen ? ' fullscreen' : ''}`}>

      {/* ── Top bar ──────────────────────────────────────────────────────── */}
      <div className="sim-topbar">
        <div className="sim-title-group">
          <h2>GRAPH VISUALIZATION</h2>
          <div className="sim-chips">
            <span className="s-chip"><Database size={11}/> {nodeCount} nodes</span>
            <span className="s-chip">{edgeCount} edges</span>
            {degreeStats && <span className="s-chip" title="Average connections per node">avg° {degreeStats.avg}</span>}
            {selectedDocId && (
              <span className="s-chip active" title={selectedDocName}>
                {selectedDocName.length > 22 ? selectedDocName.substring(0,20)+'…' : selectedDocName}
              </span>
            )}
          </div>
        </div>

        <div className="sim-controls">
          {/* Doc filter */}
          <div className="ctrl-grp">
            <label className="ctrl-lbl">DOCUMENT</label>
            <select className="sim-sel" value={selectedDocId} onChange={e => setSelectedDocId(e.target.value)}>
              <option value="">🌐 ALL</option>
              {documents.map(doc => (
                <option key={doc.id} value={doc.id}>📄 {doc.filename.length > 28 ? doc.filename.substring(0,26)+'…' : doc.filename}</option>
              ))}
            </select>
          </div>

          {/* Limit */}
          <div className="ctrl-grp">
            <label className="ctrl-lbl">NODES</label>
            <select className="sim-sel" value={limit} onChange={e => setLimit(Number(e.target.value))}>
              {[50, 100, 200, 500, 1000].map(v => <option key={v} value={v}>{v}</option>)}
            </select>
          </div>

          {/* Action buttons */}
          <div className="sim-actions">
            <button className="sim-icon-btn" title="Refresh graph" onClick={() => fetchGraph(selectedDocId, limit)} disabled={loading}>
              {loading ? <RefreshCw className="spin" size={15}/> : <Play size={15}/>}<span>REFRESH</span>
            </button>

            <button className="sim-icon-btn" title="Fit to view" onClick={() => canvasRef.current?.fitView()}>
              <Layers size={15}/><span>FIT</span>
            </button>

            {/* Edge labels quick toggle */}
            <button
              className={`sim-icon-btn${options.showEdgeLabels ? ' active' : ''}`}
              title={options.showEdgeLabels ? 'Hide edge labels' : 'Show edge labels'}
              onClick={() => setOpt('showEdgeLabels', !options.showEdgeLabels)}
            >
              <Tag size={15}/><span>LABELS</span>
            </button>

            {/* Search */}
            <button
              className={`sim-icon-btn${showSearch ? ' active' : ''}`}
              title="Search nodes"
              onClick={() => { setShowSearch(s => !s); if (showSearch) { setSearchQuery(''); setHighlightNodeIds(new Set()); } }}
            >
              <Search size={15}/><span>SEARCH</span>
            </button>

            {/* Export PNG */}
            <button className="sim-icon-btn" title="Export as PNG" onClick={() => canvasRef.current?.exportPNG()}>
              <Image size={15}/><span>PNG</span>
            </button>

            {/* Export SVG */}
            <button className="sim-icon-btn" title="Export as SVG" onClick={() => canvasRef.current?.exportSVG()}>
              <Download size={15}/><span>SVG</span>
            </button>

            {/* Options panel */}
            <button className={`sim-icon-btn${showPanel ? ' active' : ''}`} title="Advanced options" onClick={() => setShowPanel(p => !p)}>
              <SlidersHorizontal size={15}/><span>OPTIONS</span>
            </button>

            {/* Fullscreen */}
            <button className="sim-icon-btn" title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'} onClick={toggleFullscreen}>
              {isFullscreen ? <Minimize2 size={15}/> : <Maximize2 size={15}/>}
              <span>{isFullscreen ? 'EXIT' : 'FULL'}</span>
            </button>

            {/* Help */}
            <button className={`sim-icon-btn${showHelp ? ' active' : ''}`} title="Keyboard shortcuts & help" onClick={() => setShowHelp(h => !h)}>
              <HelpCircle size={15}/><span>?</span>
            </button>
          </div>
        </div>
      </div>

      {/* ── Node Search bar ──────────────────────────────────────────────── */}
      {showSearch && (
        <div className="search-bar-row">
          <Search size={14}/>
          <input
            autoFocus
            type="text"
            className="sim-search-input"
            placeholder="Search by node name or type…"
            value={searchQuery}
            onChange={e => handleSearch(e.target.value)}
          />
          {highlightNodeIds.size > 0 && (
            <span className="search-result-badge">{highlightNodeIds.size} match{highlightNodeIds.size !== 1 ? 'es' : ''}</span>
          )}
          <button className="sim-icon-btn" style={{ padding: '0.2rem 0.5rem' }} onClick={() => { setSearchQuery(''); setHighlightNodeIds(new Set()); }}>
            <X size={13}/>
          </button>
        </div>
      )}

      {/* ── Help modal ───────────────────────────────────────────────────── */}
      {showHelp && (
        <div className="advanced-panel">
          <div className="panel-header">
            <span>CONTROLS REFERENCE</span>
            <button className="toast-dismiss-btn" onClick={() => setShowHelp(false)}><X size={15}/></button>
          </div>
          <div className="panel-body" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1rem' }}>
            <div>
              <div className="opt-label">MOUSE / TOUCH</div>
              <table className="help-table">
                <tbody>
                  {[
                    ['Single click', 'Zoom to node'],
                    ['Double click', 'Edit node name'],
                    ['Drag node', 'Pin node position'],
                    ['Hover', 'Highlight neighbors'],
                    ['Scroll', 'Zoom in / out'],
                    ['Drag canvas', 'Pan view'],
                    ['Click canvas bg', 'Reset highlight'],
                  ].map(([k, v]) => (
                    <tr key={k}><td className="help-key">{k}</td><td className="help-val">{v}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div>
              <div className="opt-label">TOOLBAR BUTTONS</div>
              <table className="help-table">
                <tbody>
                  {[
                    ['REFRESH', 'Reload graph from Neo4j'],
                    ['FIT', 'Reset zoom/pan to center'],
                    ['LABELS', 'Toggle edge relation text'],
                    ['SEARCH', 'Find & highlight nodes'],
                    ['PNG/SVG', 'Export graph image'],
                    ['OPTIONS', 'Physics & display settings'],
                    ['FULL', 'Toggle fullscreen mode'],
                  ].map(([k, v]) => (
                    <tr key={k}><td className="help-key">{k}</td><td className="help-val">{v}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div>
              <div className="opt-label">TIPS</div>
              <ul className="help-tips">
                <li>Set <strong>NODES</strong> to 50 for better performance on large graphs</li>
                <li>Enable <strong>Curved edges</strong> to reduce visual overlap</li>
                <li><strong>Node size by degree</strong> makes hubs visually prominent</li>
                <li>Use <strong>SEARCH</strong> to find entities by name or type</li>
                <li>Increase <strong>Charge Strength</strong> to spread out dense clusters</li>
              </ul>
            </div>
          </div>
        </div>
      )}

      {/* ── Advanced options panel ────────────────────────────────────────── */}
      {showPanel && (
        <div className="advanced-panel">
          <div className="panel-header">
            <span>ADVANCED GRAPH OPTIONS</span>
            <button className="toast-dismiss-btn" onClick={() => setShowPanel(false)}><X size={15}/></button>
          </div>
          <div className="panel-body">
            {/* Display toggles */}
            <div className="opt-section">
              <div className="opt-label">DISPLAY</div>
              <div className="opt-row">
                {([
                  ['colorByType', 'Color nodes by entity type'],
                  ['showLabels', 'Show node name labels'],
                  ['showEdgeLabels', 'Show edge relation labels'],
                  ['showCurvedEdges', 'Curved edges (arc routing)'],
                  ['nodeSizeByDegree', 'Node size by connection count'],
                ] as [keyof GraphOptions, string][]).map(([key, label]) => (
                  <label key={key} className="opt-toggle">
                    <input type="checkbox"
                      checked={options[key] as boolean}
                      onChange={e => setOpt(key, e.target.checked)}
                    />
                    <span>{label}</span>
                  </label>
                ))}
              </div>
            </div>

            {/* Physics sliders */}
            <div className="opt-section">
              <div className="opt-label">PHYSICS</div>
              <div className="opt-sliders">
                {([
                  ['nodeRadius', 'Node Radius', 8, 40, 1],
                  ['linkDistance', 'Link Distance', 40, 500, 10],
                  ['chargeStrength', 'Repulsion', -1200, -30, 10],
                  ['centerGravity', 'Center Gravity', 0, 0.5, 0.01],
                ] as [keyof GraphOptions, string, number, number, number][]).map(([key, label, min, max, step]) => (
                  <div key={key} className="slider-row">
                    <label>{label}: <strong>{typeof options[key] === 'number' ? (options[key] as number).toFixed(key === 'centerGravity' ? 2 : 0) : options[key]}</strong></label>
                    <input type="range" min={min} max={max} step={step}
                      value={options[key] as number}
                      onChange={e => setOpt(key, Number(e.target.value))}
                    />
                  </div>
                ))}
              </div>
            </div>

            <button className="reset-btn" onClick={() => setOptions({ ...DEFAULT_OPTIONS })}>
              ↺ RESET TO DEFAULTS
            </button>
          </div>
        </div>
      )}

      {/* ── Canvas + Legend + Stats ───────────────────────────────────────── */}
      <div className="canvas-area">
        <div className="canvas-wrapper">
          {loading && graphData.nodes.length === 0 ? (
            <div className="loading-overlay">
              <RefreshCw className="spin" size={28}/>
              <span>INITIALIZING PHYSICS ENGINE...</span>
            </div>
          ) : graphData.nodes.length === 0 ? (
            <div className="loading-overlay empty">
              <Database size={40}/>
              <span>
                {selectedDocId
                  ? 'No entities found for this document.\nTry a different document or re-ingest.'
                  : 'No entity data in graph.\nIngest documents via the PROCESS tab first.'}
              </span>
            </div>
          ) : (
            <GraphCanvas
              ref={canvasRef}
              data={graphData}
              onNodeUpdate={handleNodeUpdate}
              options={options}
              highlightNodeIds={highlightNodeIds}
            />
          )}

          {loading && graphData.nodes.length > 0 && (
            <div className="refresh-pill">
              <RefreshCw className="spin" size={13}/> REFRESHING
            </div>
          )}
        </div>

        {/* ── Sidebar: Legend + Stats ─────────────────────────────────────── */}
        <div className="sidebar-panels">
          {/* Type Legend */}
          {options.colorByType && typeLegend.length > 0 && (
            <div className="legend-panel">
              <div className="legend-title">ENTITY TYPES</div>
              {typeLegend.map(({ type, color }) => (
                <div key={type} className="legend-row">
                  <span className="legend-dot" style={{ background: color }}/>
                  <span className="legend-type">{type}</span>
                </div>
              ))}
            </div>
          )}

          {/* Graph stats */}
          {degreeStats && (
            <div className="stats-sidebar">
              <div className="legend-title">NETWORK STATS</div>
              <div className="stat-row"><span>Avg Degree</span><strong>{degreeStats.avg}</strong></div>
              <div className="stat-row"><span>Max Degree</span><strong>{degreeStats.max}</strong></div>
              {degreeStats.hubs.length > 0 && (
                <>
                  <div className="legend-title" style={{ marginTop: '0.6rem' }}>HUB NODES</div>
                  {degreeStats.hubs.map((n: any) => (
                    <div
                      key={n.id}
                      className="hub-node-row"
                      title="Click to zoom to this node"
                      onClick={() => canvasRef.current?.highlightNode(n.id)}
                    >
                      <GitBranch size={10}/>
                      <span>{n.label?.length > 14 ? n.label.substring(0,12)+'…' : n.label}</span>
                    </div>
                  ))}
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ── Hint bar ──────────────────────────────────────────────────────── */}
      <div className="sim-hint">
        <Info size={11}/>
        <span>
          <strong>Click</strong> node to zoom · <strong>Double-click</strong> to rename · <strong>Hover</strong> to highlight neighbors ·
          <strong> Drag</strong> to pin · <strong>Scroll</strong> to zoom
        </span>
      </div>

      <style>{`
        .simulation-root {
          height: calc(100vh - 62px);
          display: flex;
          flex-direction: column;
          padding: 0.75rem 1.25rem 0.5rem;
          background: var(--bg-color);
          overflow: hidden;
          gap: 0;
        }
        .simulation-root.fullscreen {
          height: 100vh;
          position: fixed;
          inset: 0;
          z-index: 9999;
          background: #fff;
          padding: 0.75rem 1.25rem 0.5rem;
        }

        /* Top bar */
        .sim-topbar {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          flex-wrap: wrap;
          gap: 0.5rem;
          border-bottom: 2px solid #000;
          padding-bottom: 0.6rem;
          margin-bottom: 0.5rem;
        }
        .sim-title-group h2 { margin: 0 0 0.2rem; font-size: 1rem; letter-spacing: 2px; }
        .sim-chips { display: flex; flex-wrap: wrap; gap: 5px; }
        .s-chip {
          display: inline-flex; align-items: center; gap: 3px;
          border: 1.5px solid #000; padding: 1px 7px;
          font-family: var(--font-mono); font-size: 0.7rem; font-weight: 700;
        }
        .s-chip.active { background: #000; color: #fff; }

        .sim-controls { display: flex; align-items: flex-end; flex-wrap: wrap; gap: 0.6rem; }
        .ctrl-grp { display: flex; flex-direction: column; gap: 2px; }
        .ctrl-lbl {
          font-family: var(--font-mono); font-size: 0.62rem;
          font-weight: 700; color: #888; letter-spacing: 1px;
        }
        .sim-sel {
          font-family: var(--font-mono); font-size: 0.8rem;
          border: 2px solid #000; background: #fff; color: #000;
          padding: 0.28rem 0.55rem; cursor: pointer; min-width: 120px;
          max-width: 180px;
        }
        .sim-sel:focus { outline: none; box-shadow: 2px 2px 0 #000; }

        .sim-actions { display: flex; flex-wrap: wrap; gap: 5px; align-items: flex-end; }
        .sim-icon-btn {
          display: inline-flex; align-items: center; gap: 4px;
          border: 2px solid #000; background: #fff; color: #000;
          padding: 0.28rem 0.65rem; font-family: var(--font-mono);
          font-size: 0.7rem; font-weight: 700; cursor: pointer;
          letter-spacing: 0.5px; transition: all 0.13s ease;
          white-space: nowrap;
        }
        .sim-icon-btn:hover, .sim-icon-btn.active { background: #000; color: #fff; }
        .sim-icon-btn:disabled { opacity: 0.4; cursor: not-allowed; pointer-events: none; }

        /* Search bar */
        .search-bar-row {
          display: flex; align-items: center; gap: 0.5rem;
          border: 2px solid #000; padding: 0.3rem 0.75rem;
          margin-bottom: 0.5rem; background: #fafafa;
        }
        .sim-search-input {
          flex: 1; border: none; background: transparent;
          font-family: var(--font-mono); font-size: 0.85rem;
          color: #000; outline: none;
        }
        .search-result-badge {
          font-family: var(--font-mono); font-size: 0.72rem; font-weight: 700;
          background: #000; color: #fff; padding: 1px 8px;
        }

        /* Advanced panel */
        .advanced-panel {
          border: 2px solid #000; background: #fff;
          margin-bottom: 0.5rem; box-shadow: 3px 3px 0 #000;
        }
        .panel-header {
          display: flex; justify-content: space-between; align-items: center;
          padding: 0.4rem 0.9rem;
          background: #000; color: #fff;
          font-family: var(--font-mono); font-size: 0.75rem; font-weight: 700;
          letter-spacing: 1px;
        }
        .panel-body {
          display: flex; flex-wrap: wrap; gap: 1.25rem; padding: 0.9rem 1rem;
        }
        .opt-section { flex: 1; min-width: 160px; }
        .opt-label {
          font-family: var(--font-mono); font-size: 0.62rem; font-weight: 700;
          color: #888; letter-spacing: 1px; margin-bottom: 0.45rem;
        }
        .opt-row { display: flex; flex-direction: column; gap: 5px; }
        .opt-toggle {
          display: flex; align-items: center; gap: 7px;
          font-family: var(--font-mono); font-size: 0.77rem; cursor: pointer;
        }
        .opt-toggle input { cursor: pointer; }
        .opt-sliders { display: flex; flex-direction: column; gap: 0.55rem; }
        .slider-row {
          display: flex; flex-direction: column; gap: 3px;
          font-family: var(--font-mono); font-size: 0.75rem;
        }
        .slider-row input[type=range] { width: 100%; cursor: pointer; }
        .reset-btn {
          align-self: flex-end;
          border: 2px solid #000; background: #fff; color: #000;
          font-family: var(--font-mono); font-size: 0.72rem; font-weight: 700;
          padding: 0.3rem 0.9rem; cursor: pointer; letter-spacing: 0.5px;
          transition: all 0.13s ease;
        }
        .reset-btn:hover { background: #000; color: #fff; }

        /* Help table */
        .help-table { width: 100%; border-collapse: collapse; }
        .help-table td { vertical-align: top; padding: 2px 0; font-family: var(--font-mono); font-size: 0.74rem; }
        .help-key { color: #000; font-weight: 700; white-space: nowrap; padding-right: 0.75rem; }
        .help-val { color: #555; }
        .help-tips { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 5px; }
        .help-tips li { font-family: var(--font-mono); font-size: 0.74rem; color: #555; line-height: 1.4; }
        .help-tips li::before { content: '→ '; color: #000; font-weight: 700; }
        .help-tips strong { color: #000; }

        /* Canvas area */
        .canvas-area {
          flex: 1; display: flex; gap: 0.6rem; min-height: 0; overflow: hidden;
        }
        .canvas-wrapper {
          flex: 1; border: 2px solid #000;
          background: #fafafa; position: relative; overflow: hidden; min-height: 0;
        }
        .loading-overlay {
          position: absolute; inset: 0;
          display: flex; flex-direction: column; align-items: center; justify-content: center;
          gap: 1rem; background: rgba(255,255,255,0.92);
          font-family: var(--font-mono); font-size: 0.88rem;
          letter-spacing: 1.2px; color: #555;
          white-space: pre-line; text-align: center; padding: 2rem; z-index: 10;
        }
        .loading-overlay.empty { color: #bbb; }
        .refresh-pill {
          position: absolute; top: 8px; right: 8px;
          display: flex; align-items: center; gap: 5px;
          background: rgba(0,0,0,0.85); color: #fff;
          font-family: var(--font-mono); font-size: 0.7rem;
          padding: 2px 9px; z-index: 20;
        }

        /* Sidebar panels */
        .sidebar-panels {
          display: flex; flex-direction: column; gap: 0.5rem;
          width: 150px; flex-shrink: 0; overflow-y: auto;
        }
        .legend-panel, .stats-sidebar {
          border: 2px solid #000; background: #fff; padding: 0.65rem 0.75rem; flex-shrink: 0;
        }
        .legend-title {
          font-family: var(--font-mono); font-size: 0.6rem; font-weight: 700;
          color: #888; letter-spacing: 1px; margin-bottom: 0.5rem; text-transform: uppercase;
        }
        .legend-row { display: flex; align-items: center; gap: 7px; margin-bottom: 4px; }
        .legend-dot {
          width: 11px; height: 11px; border-radius: 50%; flex-shrink: 0;
          border: 1px solid rgba(0,0,0,0.15);
        }
        .legend-type {
          font-family: var(--font-mono); font-size: 0.72rem; font-weight: 600;
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .stat-row {
          display: flex; justify-content: space-between; align-items: center;
          font-family: var(--font-mono); font-size: 0.72rem;
          color: #555; margin-bottom: 3px;
        }
        .stat-row strong { color: #000; font-weight: 700; }
        .hub-node-row {
          display: flex; align-items: center; gap: 5px;
          font-family: var(--font-mono); font-size: 0.69rem;
          color: #333; margin-bottom: 3px; cursor: pointer;
          padding: 2px 4px; transition: background 0.12s;
        }
        .hub-node-row:hover { background: #f0f0f0; }

        /* Hint bar */
        .sim-hint {
          display: flex; align-items: center; gap: 5px;
          font-size: 0.69rem; color: #999; font-family: var(--font-mono);
          padding: 0.25rem 0; border-top: 1px dashed #ccc; margin-top: 0.25rem;
          flex-shrink: 0;
        }
        .sim-hint strong { color: #555; }

        .spin { animation: spin 1.2s linear infinite; }
        @keyframes spin { 100% { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
};

export default SimulationRunView;
