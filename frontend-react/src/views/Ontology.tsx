import React, { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import { Database, GitMerge, Settings, Sparkles, Save, Info, Zap, AlertTriangle, Check, X, FileText } from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

const Ontology: React.FC = () => {
  const { token, logout } = useAuth();
  
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [refining, setRefining] = useState(false);
  const [deduping, setDeduping] = useState(false);
  const [enriching, setEnriching] = useState(false);
  const [detectingDrift, setDetectingDrift] = useState(false);
  const [driftReports, setDriftReports] = useState<any[]>([]);
  
  const [version, setVersion] = useState('');
  const [entityTypes, setEntityTypes] = useState('');
  const [relationshipTypes, setRelationshipTypes] = useState('');
  const [properties, setProperties] = useState('');
  const [feedback, setFeedback] = useState('');
  
  // "Global" baseline so we can restore when switching back to global mode
  const [globalEntityTypes, setGlobalEntityTypes] = useState('');
  const [globalRelationshipTypes, setGlobalRelationshipTypes] = useState('');
  const [globalProperties, setGlobalProperties] = useState('');
  
  const [documents, setDocuments] = useState<any[]>([]);
  const [selectedDocId, setSelectedDocId] = useState<string>('');
  const [stats, setStats] = useState<any>(null);
  const [docSchemaLoading, setDocSchemaLoading] = useState(false);
  
  const [message, setMessage] = useState('');

  /* ── Fetch global ontology ─────────────────────────────────────── */
  const fetchOntology = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/ontology`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.status === 401) { logout(); return; }
      if (res.ok) {
        const data = await res.json();
        setVersion(data.version || '1.0');
        const ent = data.entity_types?.join(', ') || '';
        const rel = data.relationship_types?.join(', ') || '';
        const props = JSON.stringify(data.properties || {}, null, 2);
        setEntityTypes(ent);
        setRelationshipTypes(rel);
        setProperties(props);
        // Save as global baseline
        setGlobalEntityTypes(ent);
        setGlobalRelationshipTypes(rel);
        setGlobalProperties(props);
      } else {
        setMessage('No active ontology found. Please upload documents first.');
      }
    } catch (err) {
      console.error(err);
      setMessage('FAILED TO LOAD ONTOLOGY API');
    } finally {
      setLoading(false);
    }
  };

  const fetchDocuments = async () => {
    try {
      const res = await fetch(`${API_BASE}/documents`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setDocuments(data.documents);
      }
    } catch (err) {
      console.error('Failed to fetch docs for dropdown', err);
    }
  };

  const fetchStats = async (docId: string) => {
    try {
      const url = new URL(`${API_BASE}/ontology/stats`);
      if (docId) url.searchParams.append('document_id', docId);
      const res = await fetch(url.toString(), {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) setStats(await res.json());
      else setStats(null);
    } catch { setStats(null); }
  };

  /* ── Fetch document-specific schema ─────────────────────────────── */
  const fetchDocSchema = async (docId: string) => {
    if (!docId) {
      // Restore global schema
      setEntityTypes(globalEntityTypes);
      setRelationshipTypes(globalRelationshipTypes);
      setProperties(globalProperties);
      return;
    }
    setDocSchemaLoading(true);
    try {
      const url = new URL(`${API_BASE}/ontology/stats`);
      url.searchParams.append('document_id', docId);
      const res = await fetch(url.toString(), {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        // Populate editor with document-specific entity types and relationships
        const docEntityTypes = (data.entity_stats || [])
          .map((s: any) => s.type)
          .filter(Boolean)
          .join(', ');
        const docRelTypes = (data.relationship_stats || [])
          .map((s: any) => s.type)
          .filter(Boolean)
          .join(', ');
        
        setEntityTypes(docEntityTypes || globalEntityTypes);
        setRelationshipTypes(docRelTypes || globalRelationshipTypes);
        // Properties: keep global properties since per-doc isn't tracked separately
        setProperties(globalProperties);
      }
    } catch (err) {
      console.error('Failed to fetch doc schema', err);
    } finally {
      setDocSchemaLoading(false);
    }
  };

  useEffect(() => {
    fetchOntology();
    fetchDocuments();
    fetchStats('');
  }, [token]);

  useEffect(() => {
    fetchStats(selectedDocId);
    fetchDocSchema(selectedDocId);
  }, [selectedDocId]);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setMessage('');
    
    let parsedProps = {};
    try {
      parsedProps = JSON.parse(properties);
    } catch (e) {
      setMessage('ERROR: PROPERTIES MUST BE VALID JSON');
      setSaving(false);
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/ontology`, {
        method: 'PUT',
        headers: { 
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}` 
        },
        body: JSON.stringify({
          entity_types: entityTypes.split(',').map(s => s.trim()).filter(Boolean),
          relationship_types: relationshipTypes.split(',').map(s => s.trim()).filter(Boolean),
          properties: parsedProps,
          approved: true
        })
      });
      
      if (res.status === 401) { logout(); return; }
      
      if (res.ok) {
        setMessage('ONTOLOGY SCHEMA UPDATED');
        fetchOntology();
        setSelectedDocId(''); // reset to global after save
      } else {
        setMessage('FAILED TO SAVE SCHEMA');
      }
    } catch (err) {
      console.error(err);
      setMessage('API ERROR DURING SAVE');
    } finally {
      setSaving(false);
    }
  };

  const handleRefine = async () => {
    setRefining(true);
    setMessage('ANALYZING GRAPH FOR UPGRADES... (THIS MAY TAKE 30s+)');
    try {
      const res = await fetch(`${API_BASE}/ontology/refine`, {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}` 
        },
        body: JSON.stringify({ 
          feedback: feedback || undefined,
          document_id: selectedDocId || undefined
        })
      });
      
      if (res.status === 401) { logout(); return; }
      
      if (res.ok) {
        const data = await res.json();
        setMessage(`SUCCESS: ${data.changes}`);
        fetchOntology();
      } else {
        setMessage('FAILED TO REFINE SCHEMA');
      }
    } catch (err) {
      console.error(err);
      setMessage('API ERROR DURING REFINE');
    } finally {
      setRefining(false);
    }
  };

  const handleDeduplicate = async () => {
    if (!window.confirm("Run semantic merging? This cannot be undone.")) return;
    setDeduping(true);
    setMessage('SCANNING GRAPH FOR DUPLICATE ENTITIES... (THIS MAY TAKE AWHILE)');
    try {
      const res = await fetch(`${API_BASE}/entities/deduplicate`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.status === 401) { logout(); return; }
      if (res.ok) {
        const data = await res.json();
        setMessage(`DEDUPLICATION COMPLETE: Merged ${data.merged_count} entities.`);
      } else {
        setMessage('FAILED TO DEDUPLICATE ENTITIES');
      }
    } catch (err) {
      console.error(err);
      setMessage('API ERROR DURING DEDUPLICATION');
    } finally {
      setDeduping(false);
    }
  };

  const handleEnrichEntities = async () => {
    setEnriching(true);
    setMessage('GENERATING ENTITY PROFILES FROM GRAPH NEIGHBORHOODS...');
    try {
      const res = await fetch(`${API_BASE}/entities/enrich`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ batch_size: 20, min_connections: 1 })
      });
      if (res.status === 401) { logout(); return; }
      if (res.ok) {
        const data = await res.json();
        setMessage(`ENRICHMENT COMPLETE: ${data.message || `${data.enriched_count ?? '?'} entities profiled.`}`);
      } else {
        setMessage('FAILED TO ENRICH ENTITIES');
      }
    } catch {
      setMessage('API ERROR DURING ENRICHMENT');
    } finally {
      setEnriching(false);
    }
  };

  const handleDetectDrift = async () => {
    setDetectingDrift(true);
    setMessage('ANALYZING GRAPH DATA FOR SCHEMA DRIFT...');
    try {
      const res = await fetch(`${API_BASE}/ontology/drift/detect`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.status === 401) { logout(); return; }
      if (res.ok) {
        const data = await res.json();
        setMessage(`DRIFT REPORT CREATED: ID ${data.report_id || data.id || '—'}`);
        fetchDriftReports();
      } else {
        setMessage('FAILED TO DETECT DRIFT');
      }
    } catch {
      setMessage('API ERROR DURING DRIFT DETECTION');
    } finally {
      setDetectingDrift(false);
    }
  };

  const fetchDriftReports = async () => {
    try {
      const res = await fetch(`${API_BASE}/ontology/drift`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setDriftReports(data.reports || []);
      }
    } catch {}
  };

  const handleDriftAction = async (id: string, action: 'approve' | 'reject') => {
    const res = await fetch(`${API_BASE}/ontology/drift/${id}/${action}`, {
      method: 'POST', headers: { Authorization: `Bearer ${token}` }
    });
    if (res.ok) {
      setDriftReports(d => d.filter(r => r.id !== id));
      setMessage(`Drift report ${action}d.`);
    }
  };

  const selectedDoc = documents.find(d => d.id === selectedDocId);

  return (
    <div className="container" style={{ animation: 'fadeIn 0.5s ease' }}>
      <div className="page-header flex-between">
        <div>
          <h1>ONTOLOGY MANAGEMENT</h1>
          <p className="mono-text">SCHEMA CONTROL &amp; GRAPH REFINEMENT</p>
        </div>
        <Database size={32} />
      </div>

      {/* Help info bar */}
      <div className="page-info-bar">
        <Info size={14}/>
        <span>
          <strong>ENTITY TYPES</strong> define what kinds of nodes exist in your graph.
          <strong> RELATIONSHIP TYPES</strong> define how they connect.
          Use <strong>LLM REFINEMENT</strong> to auto-suggest schema improvements from your data.
          Use <strong>DRIFT DETECTION</strong> to detect when new data doesn't fit the current schema.
          Use <strong>ENTITY ENRICHMENT</strong> to synthesize rich profiles for all graph nodes.
        </span>
      </div>

      <div className="ontology-layout">
        {/* Schema Editor */}
        <div className="card editor-card">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.5rem' }}>
            <h2 className="mono-text flex-center" style={{ gap: '0.5rem', margin: 0 }}>
              <Settings size={20}/> EDIT SCHEMA {version ? `v${version}` : ''}
            </h2>
            {selectedDocId && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', background: '#000', color: '#fff', padding: '3px 10px', fontFamily: 'var(--font-mono)', fontSize: '0.68rem', fontWeight: 700, letterSpacing: '0.5px' }}>
                <FileText size={11} />
                DOC SCOPE: {selectedDoc?.filename?.slice(0, 22) ?? selectedDocId.slice(0, 12)}…
              </div>
            )}
          </div>

          {/* Document selector in editor header */}
          <div style={{ marginBottom: '1.25rem', padding: '0.75rem', background: '#f5f5f5', border: '1.5px solid #e5e5e5' }}>
            <label className="control-label" style={{ display: 'block', marginBottom: '0.4rem' }}>
              POPULATE FROM DOCUMENT
            </label>
            <select
              className="mono-text doc-dropdown"
              value={selectedDocId}
              onChange={(e) => setSelectedDocId(e.target.value)}
              style={{ width: '100%' }}
            >
              <option value="">🌐 GLOBAL — Full Ontology Schema</option>
              {documents.map(doc => (
                <option key={doc.id} value={doc.id}>📄 {doc.filename}</option>
              ))}
            </select>
            {docSchemaLoading && (
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: 'var(--muted-color)', marginTop: '0.4rem' }}>
                ↻ Loading document schema…
              </div>
            )}
            {selectedDocId && !docSchemaLoading && (
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color: '#16a34a', marginTop: '0.4rem', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                <Check size={11}/> Schema populated from "{selectedDoc?.filename ?? selectedDocId}"
              </div>
            )}
          </div>
          
          {loading ? (
            <div className="mono-text" style={{ padding: '2rem', textAlign: 'center' }}>LOADING SCHEMA...</div>
          ) : (
            <form onSubmit={handleSave} className="schema-form">
              <div className="form-group">
                <label className="mono-text">ENTITY TYPES (COMMA-SEPARATED)</label>
                <textarea 
                  value={entityTypes} 
                  onChange={(e) => setEntityTypes(e.target.value)}
                  className="mono-text"
                  rows={3}
                  placeholder="Person, Organization, Location, Event…"
                />
              </div>

              <div className="form-group">
                <label className="mono-text">RELATIONSHIP TYPES (COMMA-SEPARATED)</label>
                <textarea 
                  value={relationshipTypes} 
                  onChange={(e) => setRelationshipTypes(e.target.value)}
                  className="mono-text"
                  rows={3}
                  placeholder="WORKS_FOR, LOCATED_IN, RELATED_TO…"
                />
              </div>

              <div className="form-group">
                <label className="mono-text">PROPERTIES BINDING (JSON FORMAT)</label>
                <textarea 
                  value={properties} 
                  onChange={(e) => setProperties(e.target.value)}
                  className="mono-text dict-editor"
                  rows={8}
                />
              </div>

              <button 
                type="submit" 
                className="app-btn full-width" 
                disabled={saving}
                style={{ display: 'flex', justifyContent: 'center', gap: '8px' }}
              >
                <Save size={18} /> {saving ? 'SAVING...' : 'COMMIT SCHEMA CHANGES'}
              </button>
            </form>
          )}

        </div>

        {/* AI Tools */}
        <div className="tools-card-container">
          <div className="card tools-card">
            <h2 className="mono-text flex-center" style={{ gap: '0.5rem' }}>
              <Sparkles size={20}/> LLM REFINEMENT
            </h2>
            <p style={{ marginTop: '1rem', marginBottom: '0.75rem', fontSize: '0.88rem', lineHeight: 1.6 }}>
              Use the LLM Agent to scan existing document chunks and automatically suggest expansions or restructuring to the current ontology schema.
            </p>

            <div className="refine-info-box">
              <Info size={13} />
              <span>
                <strong>Global mode:</strong> samples random chunks from all documents.<br/>
                <strong>Targeted mode:</strong> only scans chunks from the selected document — useful for domain-specific refinement.
              </span>
            </div>

            <label className="control-label" style={{ display: 'block', marginBottom: '0.4rem', marginTop: '1rem' }}>REFINEMENT SCOPE</label>
            <select 
              className="mono-text doc-dropdown" 
              value={selectedDocId} 
              onChange={(e) => setSelectedDocId(e.target.value)}
              style={{ width: '100%', marginBottom: '1rem' }}
            >
              <option value="">🌐 GLOBAL — ALL DOCUMENTS (RANDOM CHUNKS)</option>
              {documents.map(doc => (
                <option key={doc.id} value={doc.id}>📄 TARGET: {doc.filename}</option>
              ))}
            </select>
            <label className="control-label" style={{ display: 'block', marginBottom: '0.4rem' }}>OPTIONAL CRITERIA</label>
            <textarea 
              placeholder="e.g., 'Focus heavily on extracting medical symptoms and treatment names'"
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              className="mono-text"
              rows={3}
              style={{ width: '100%', marginBottom: '1rem' }}
            />
            <button 
              onClick={handleRefine}
              className="app-btn outline-btn full-width" 
              disabled={refining || loading}
              style={{ display: 'flex', justifyContent: 'center', gap: '8px' }}
            >
              <Sparkles size={18} /> {refining ? 'ANALYZING GRAPH...' : 'REFINE SCHEMA'}
            </button>
          </div>

          <div className="card tools-card" style={{ marginTop: '2rem' }}>
            <h2 className="mono-text flex-center" style={{ gap: '0.5rem' }}>
              <GitMerge size={20}/> IDENTITY RESOLUTION
            </h2>
            <p style={{ marginTop: '1rem', marginBottom: '1rem', fontSize: '0.9rem', lineHeight: 1.5 }}>
              Scan the entire Knowledge Graph and use Semantic Embedding comparisons to detect and permanently merge duplicated entities.
            </p>
            <button
              onClick={handleDeduplicate}
              className="app-btn outline-btn full-width"
              disabled={deduping || loading}
              style={{ display: 'flex', justifyContent: 'center', gap: '8px' }}
            >
              <GitMerge size={18} /> {deduping ? 'MERGING...' : 'DEDUPLICATE ENTITIES'}
            </button>
          </div>

          {/* Entity Enrichment */}
          <div className="card tools-card" style={{ marginTop: '2rem' }}>
            <h2 className="mono-text flex-center" style={{ gap: '0.5rem' }}>
              <Zap size={20}/> ENTITY ENRICHMENT
            </h2>
            <p style={{ marginTop: '1rem', marginBottom: '1rem', fontSize: '0.9rem', lineHeight: 1.5 }}>
              Generate rich LLM-synthesized profiles for all eligible entities using their graph neighborhood context. Profiles power the Entity Chat feature.
            </p>
            <button
              onClick={handleEnrichEntities}
              className="app-btn outline-btn full-width"
              disabled={enriching || loading}
              style={{ display: 'flex', justifyContent: 'center', gap: '8px' }}
            >
              <Zap size={18} /> {enriching ? 'ENRICHING...' : 'ENRICH ALL ENTITIES'}
            </button>
          </div>

          {/* Drift Detection */}
          <div className="card tools-card" style={{ marginTop: '2rem' }}>
            <h2 className="mono-text flex-center" style={{ gap: '0.5rem' }}>
              <AlertTriangle size={20}/> ONTOLOGY DRIFT
            </h2>
            <p style={{ marginTop: '1rem', marginBottom: '1rem', fontSize: '0.9rem', lineHeight: 1.5 }}>
              Detect when new incoming data no longer fits the current schema. The drift detector proposes additions for review.
            </p>
            <button
              onClick={handleDetectDrift}
              className="app-btn outline-btn full-width"
              disabled={detectingDrift || loading}
              style={{ display: 'flex', justifyContent: 'center', gap: '8px', marginBottom: driftReports.length > 0 ? '1rem' : 0 }}
            >
              <AlertTriangle size={18} /> {detectingDrift ? 'DETECTING...' : 'DETECT DRIFT'}
            </button>
            {driftReports.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', marginTop: '0.5rem' }}>
                <div className="control-label" style={{ marginBottom: '0.25rem' }}>PENDING DRIFT REPORTS</div>
                {driftReports.slice(0, 3).map(r => (
                  <div key={r.id} style={{ border: '1px solid #e5e5e5', padding: '0.6rem 0.75rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.5rem' }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {r.summary || r.id}
                    </span>
                    <div style={{ display: 'flex', gap: '4px', flexShrink: 0 }}>
                      <button onClick={() => handleDriftAction(r.id, 'approve')}
                        style={{ background: '#f0fdf4', color: '#16a34a', border: '1px solid #16a34a', padding: '2px 8px', cursor: 'pointer', fontSize: '0.72rem' }}>
                        <Check size={10}/>
                      </button>
                      <button onClick={() => handleDriftAction(r.id, 'reject')}
                        style={{ background: '#fef2f2', color: '#dc2626', border: '1px solid #dc2626', padding: '2px 8px', cursor: 'pointer', fontSize: '0.72rem' }}>
                        <X size={10}/>
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* ── Live Stats Panel ── */}
          {stats && (
            <div className="card tools-card stats-panel" style={{ marginTop: '2rem' }}>
              <h2 className="mono-text flex-center" style={{ gap: '0.5rem', marginBottom: '1rem' }}>
                <Database size={20}/> GRAPH STATISTICS
                {selectedDocId && <span className="scope-badge">DOC FILTERED</span>}
              </h2>

              <div className="stats-summary">
                <div className="sum-chip">
                  <div className="sum-val">{stats.total_entities}</div>
                  <div className="sum-key">TOTAL ENTITIES</div>
                </div>
                <div className="sum-chip">
                  <div className="sum-val">{stats.total_relationships}</div>
                  <div className="sum-key">RELATIONSHIPS</div>
                </div>
              </div>

              {stats.entity_stats?.length > 0 && (
                <>
                  <div className="stat-section-lbl">ENTITY TYPES</div>
                  {stats.entity_stats.slice(0, 8).map((s: any) => (
                    <div key={s.type} className="stat-bar-row">
                      <span className="stat-bar-label">{s.type}</span>
                      <div className="stat-bar-track">
                        <div
                          className="stat-bar-fill"
                          style={{ width: `${Math.min(100, (s.count / stats.total_entities) * 100)}%` }}
                        />
                      </div>
                      <span className="stat-bar-count">{s.count}</span>
                    </div>
                  ))}
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {message && (
        <div className={`status-toast ${message.includes('ERROR') || message.includes('FAILED') ? 'error' : ''}`}>
          <Info size={20} /> {message}
          <button 
            onClick={() => setMessage('')} 
            className="toast-dismiss-btn"
          >
            &times;
          </button>
        </div>
      )}

      <style>{`
        .doc-dropdown {
          background: var(--bg-color);
          color: var(--text-color);
          border: 2px solid var(--border-color);
          padding: 0.5rem;
          font-size: 0.9rem;
          font-weight: bold;
          outline: none;
          max-width: 100%;
          text-overflow: ellipsis;
        }

        .ontology-layout {
          display: grid;
          grid-template-columns: 3fr 2fr;
          gap: 2rem;
          margin-top: 1rem;
        }
        
        @media (max-width: 768px) {
          .ontology-layout {
            grid-template-columns: 1fr;
          }
        }

        .form-group {
          margin-bottom: 1.5rem;
        }

        .form-group label {
          display: block;
          margin-bottom: 0.5rem;
          font-weight: bold;
          font-size: 0.85rem;
          color: #555;
        }

        .form-group textarea {
          width: 100%;
          padding: 1rem;
          border: 2px solid var(--border-color);
          background: var(--bg-color);
          color: var(--text-color);
          resize: vertical;
          font-size: 0.9rem;
        }

        .form-group textarea:focus {
          outline: none;
          border-color: #555;
        }

        .dict-editor {
          font-family: var(--font-mono);
          white-space: pre;
          background-color: #fafafa !important;
        }

        .status-toast {
          position: fixed;
          bottom: 2rem;
          right: 2rem;
          background: var(--text-color);
          color: var(--bg-color);
          padding: 1rem 1.5rem;
          border-left: 6px solid var(--text-color);
          box-shadow: 4px 4px 0 var(--border-color);
          display: flex;
          align-items: center;
          gap: 1rem;
          z-index: 9999;
          font-family: var(--font-mono);
          font-weight: bold;
          font-size: 0.9rem;
          animation: slideUp 0.3s ease-out;
          max-width: 400px;
        }

        .status-toast.error {
          border-left-color: #ff0000;
        }

        .refine-info-box {
          background: #f5f5f5;
          border-left: 3px solid #000;
          padding: 0.5rem 0.75rem;
          font-size: 0.78rem;
          line-height: 1.6;
          display: flex;
          gap: 0.5rem;
          align-items: flex-start;
        }

        .control-label {
          font-family: var(--font-mono);
          font-size: 0.7rem;
          font-weight: 700;
          color: #666;
          letter-spacing: 1px;
          text-transform: uppercase;
        }

        .outline-btn {
          background: transparent !important;
          color: var(--text-color) !important;
          border: 2px solid var(--text-color) !important;
        }
        .outline-btn:hover:not(:disabled) {
          background: var(--text-color) !important;
          color: var(--bg-color) !important;
        }

        /* ── Stats panel ── */
        .stats-summary {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 0.75rem;
          margin-bottom: 1rem;
        }
        .sum-chip {
          border: 1.5px solid #e5e5e5;
          padding: 0.6rem 0.75rem;
          text-align: center;
        }
        .sum-val {
          font-family: var(--font-mono);
          font-size: 1.4rem;
          font-weight: 700;
          line-height: 1;
        }
        .sum-key {
          font-family: var(--font-mono);
          font-size: 0.62rem;
          color: #888;
          letter-spacing: 1px;
          margin-top: 0.2rem;
        }
        .stat-section-lbl {
          font-family: var(--font-mono);
          font-size: 0.65rem;
          font-weight: 700;
          color: #888;
          letter-spacing: 1px;
          margin-bottom: 0.5rem;
        }
        .stat-bar-row {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          margin-bottom: 0.35rem;
          font-family: var(--font-mono);
          font-size: 0.75rem;
        }
        .stat-bar-label {
          width: 90px;
          flex-shrink: 0;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          color: #444;
        }
        .stat-bar-track {
          flex: 1;
          height: 6px;
          background: #e5e5e5;
          border-radius: 2px;
          overflow: hidden;
        }
        .stat-bar-fill {
          height: 100%;
          background: #000;
          transition: width 0.4s ease;
        }
        .stat-bar-count {
          width: 28px;
          text-align: right;
          color: #666;
          font-size: 0.72rem;
        }
        .scope-badge {
          font-size: 0.6rem;
          background: #000;
          color: #fff;
          padding: 2px 6px;
          letter-spacing: 0.5px;
          margin-left: 0.4rem;
        }
      `}</style>
    </div>
  );
};

export default Ontology;
