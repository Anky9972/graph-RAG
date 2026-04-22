import React, { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import { Upload, FilePlus, Activity, Trash2, Eye, Globe, X, FileText, Link, Hash, BookOpen } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

interface PreviewData {
  filename: string;
  file_type: string;
  word_count: number;
  char_count: number;
  content: string;
}

const Process: React.FC = () => {
  const { token, logout } = useAuth();
  const [documents, setDocuments] = useState<any[]>([]);
  const [loadingDocs, setLoadingDocs] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState('');
  const [message, setMessage] = useState('');

  // Preview modal state
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewData, setPreviewData] = useState<PreviewData | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  interface TaskState {
    status: string;
    progress?: {
      current_chunk?: number;
      total_chunks?: number;
      file?: string;
    };
  }

  const [tasks, setTasks] = useState<Record<string, TaskState>>({});

  const fetchDocuments = async () => {
    setLoadingDocs(true);
    try {
      const res = await fetch(`${API_BASE}/documents`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.status === 401) { logout(); return; }
      if (res.ok) {
        const data = await res.json();
        setDocuments(data.documents);
      }
    } catch (err) {
      console.error('Failed to fetch docs', err);
    } finally {
      setLoadingDocs(false);
    }
  };

  useEffect(() => {
    fetchDocuments();
    const interval = setInterval(fetchDocuments, 10000);
    return () => clearInterval(interval);
  }, [token]);

  useEffect(() => {
    const activeTasks = Object.keys(tasks).filter(
      tid => tasks[tid].status !== 'completed' && tasks[tid].status !== 'failure'
    );
    if (activeTasks.length === 0) return;

    const interval = setInterval(() => {
      activeTasks.forEach(async (tid) => {
        try {
          const res = await fetch(`${API_BASE}/documents/status/${tid}`, {
            headers: { Authorization: `Bearer ${token}` }
          });
          if (res.status === 401) { logout(); return; }
          if (res.ok) {
            const data = await res.json();
            setTasks(prev => ({ ...prev, [tid]: { status: data.status, progress: data.progress } }));
            if (data.status === 'completed' || data.status === 'failure') fetchDocuments();
          }
        } catch (e) {}
      });
    }, 2000);

    return () => clearInterval(interval);
  }, [tasks, token]);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) setFile(e.target.files[0]);
  };

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setUploading(true);
    setMessage('');
    const formData = new FormData();
    formData.append('file', file);
    try {
      const res = await fetch(`${API_BASE}/documents/upload`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: formData
      });
      if (res.status === 401) { logout(); return; }
      const data = await res.json();
      if (!res.ok) {
        setMessage(`UPLOAD FAILED: ${data.detail}`);
      } else {
        setMessage('FILE UPLOADED. INGESTION TASK QUEUED.');
        if (data.task_id) setTasks(prev => ({ ...prev, [data.task_id]: { status: 'pending' } }));
        setFile(null);
        fetchDocuments();
      }
    } catch (err: any) {
      setMessage(`ERROR: ${err.message}`);
    } finally {
      setUploading(false);
    }
  };

  const handleUrlScrape = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim()) return;
    setUploading(true);
    setMessage('');
    try {
      const res = await fetch(`${API_BASE}/documents/scrape`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ url: url.trim() })
      });
      if (res.status === 401) { logout(); return; }
      const data = await res.json();
      if (!res.ok) {
        setMessage(`SCRAPE FAILED: ${data.detail}`);
      } else {
        setMessage('URL SCRAPED. INGESTION TASK QUEUED.');
        if (data.task_id) setTasks(prev => ({ ...prev, [data.task_id]: { status: 'pending' } }));
        setUrl('');
        fetchDocuments();
      }
    } catch (err: any) {
      setMessage(`ERROR: ${err.message}`);
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (docId: string) => {
    if (!window.confirm('WARNING: Delete this document and all its graph data?')) return;
    try {
      const res = await fetch(`${API_BASE}/documents/${docId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.status === 401) { logout(); return; }
      fetchDocuments();
    } catch (err) {
      console.error(err);
    }
  };

  const handleView = async (doc: any) => {
    const fileType = (doc.file_type || '').toLowerCase();

    // Text/scraped files → use inline preview modal
    if (fileType === '.txt' || fileType === '.md' || fileType === '') {
      setPreviewOpen(true);
      setPreviewLoading(true);
      setPreviewData(null);
      try {
        const res = await fetch(`${API_BASE}/documents/${doc.id}/preview`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        if (res.status === 401) { logout(); return; }
        if (res.ok) {
          const data = await res.json();
          setPreviewData(data);
        } else {
          const err = await res.json();
          setMessage(`PREVIEW ERROR: ${err.detail}`);
          setPreviewOpen(false);
        }
      } catch (err) {
        setMessage('ERROR: Failed to load preview.');
        setPreviewOpen(false);
      } finally {
        setPreviewLoading(false);
      }
      return;
    }

    // Binary files (PDF) → open in new tab as before
    const newTab = window.open('', '_blank');
    if (!newTab) { setMessage('ERROR: Please allow popups to view PDFs.'); return; }
    newTab.document.write('<div style="font-family:monospace;padding:20px;">Fetching secure document...</div>');
    try {
      const res = await fetch(`${API_BASE}/documents/${doc.id}/download`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.status === 401) { newTab.close(); logout(); return; }
      if (res.ok) {
        const contentType = res.headers.get('content-type') || 'application/pdf';
        const blob = await res.blob();
        const fileBlob = new Blob([blob], { type: contentType });
        const blobUrl = window.URL.createObjectURL(fileBlob);
        newTab.location.href = blobUrl;
      } else {
        newTab.close();
        setMessage('ERROR: Document file not found on server.');
      }
    } catch (err) {
      newTab.close();
      setMessage('ERROR: Failed to open document.');
    }
  };

  const isTxtDoc = (doc: any) => {
    const ft = (doc.file_type || '').toLowerCase();
    return ft === '.txt' || ft === '.md' || ft === '';
  };

  return (
    <div className="container" style={{ animation: 'fadeIn 0.5s ease' }}>
      <div className="page-header flex-between">
        <div>
          <h1>INGESTION PIPELINE</h1>
          <p className="mono-text">DATA PROCESSING &amp; GRAPH CONSTRUCTION</p>
        </div>
        <Activity size={32} />
      </div>

      <div className="process-layout">
        {/* Upload / Scrape Section */}
        <div className="card upload-card">
          <h2 className="mono-text flex-center"><FilePlus style={{ marginRight: '0.5rem' }}/> ADD DOCUMENT</h2>

          <form onSubmit={handleUpload} className="upload-form">
            <div className="file-input-wrapper">
              <input type="file" id="file-upload" onChange={handleFileChange} accept=".pdf,.txt,.md" />
              <label htmlFor="file-upload" className="file-label">
                {file ? file.name : 'SELECT FILE FOR INGESTION'}
              </label>
            </div>
            <button
              type="submit"
              className="app-btn full-width"
              disabled={!file || uploading}
              style={{ marginTop: '1rem', display: 'flex', justifyContent: 'center', gap: '8px' }}
            >
              {uploading && file ? 'UPLOADING...' : <><Upload size={18} /> INITIALIZE FILE INGESTION</>}
            </button>
          </form>

          <hr style={{ margin: '2rem 0', borderColor: 'var(--border-color)', borderStyle: 'dotted' }} />

          <h2 className="mono-text flex-center"><Globe style={{ marginRight: '0.5rem' }}/> SCRAPE URL</h2>
          <p style={{ fontSize: '0.85rem', color: '#666', marginBottom: '1rem', lineHeight: 1.5 }}>
            Paste any public URL — articles, docs, Wikipedia pages — to scrape and ingest the content into your knowledge graph.
          </p>
          <form onSubmit={handleUrlScrape} className="upload-form">
            <input
              type="url"
              className="query-input mono-text"
              placeholder="https://example.com/article"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              required
              style={{ width: '100%', marginBottom: '1rem' }}
            />
            <button
              type="submit"
              className="app-btn full-width"
              disabled={!url || uploading}
              style={{ display: 'flex', justifyContent: 'center', gap: '8px' }}
            >
              {uploading && url ? 'SCRAPING...' : <><Activity size={18} /> INGEST FROM URL</>}
            </button>
          </form>

          {Object.keys(tasks).length > 0 && (
            <div className="task-tracker" style={{ marginTop: '1rem' }}>
              <h4 className="mono-text">ACTIVE TASKS</h4>
              {Object.entries(tasks).map(([tid, taskObj]) => {
                const pct = (taskObj.progress?.current_chunk && taskObj.progress?.total_chunks)
                  ? Math.round((taskObj.progress.current_chunk / taskObj.progress.total_chunks) * 100)
                  : 0;
                return (
                  <div key={tid} className="task-row" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: '8px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', width: '100%' }}>
                      <span title={tid}>{tid.substring(0,8)}...</span>
                      <span className={`status-badge ${taskObj.status}`}>
                        {taskObj.status.toUpperCase()}{taskObj.status === 'processing' && pct > 0 ? ` ${pct}%` : ''}
                      </span>
                    </div>
                    {taskObj.status === 'processing' && taskObj.progress?.total_chunks && (
                      <div style={{ width: '100%', height: '4px', background: '#e0e0e0', borderRadius: '2px', overflow: 'hidden' }}>
                        <div style={{ width: `${pct}%`, height: '100%', background: '#000', transition: 'width 0.3s ease' }}></div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Corpus Table */}
        <div className="card documents-card">
          <h2 className="mono-text">CORPUS INDEX</h2>
          <div className="table-wrapper">
            <table className="docs-table">
              <thead>
                <tr>
                  <th>DOCUMENT NAME</th>
                  <th>TYPE</th>
                  <th>SIZE</th>
                  <th>INGESTED</th>
                  <th>ACTIONS</th>
                </tr>
              </thead>
              <tbody>
                {documents.length === 0 && !loadingDocs ? (
                  <tr><td colSpan={5} style={{ textAlign: 'center', padding: '3rem' }} className="mono-text">
                    <p style={{ marginBottom: '1rem' }}>NO DOCUMENTS INDEXED IN GRAPH DATABASE</p>
                    <p style={{ color: '#666', fontSize: '0.85rem' }}>Upload a file or scrape a URL above to begin.</p>
                  </td></tr>
                ) : loadingDocs ? (
                  <tr><td colSpan={5} style={{ textAlign: 'center', padding: '3rem' }} className="mono-text">
                    FETCHING CORPUS DATA...
                  </td></tr>
                ) : (
                  documents.map((doc: any) => (
                    <tr key={doc.id}>
                      <td className="mono-text" style={{ maxWidth: '220px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                          {isTxtDoc(doc) ? <Link size={14} /> : <FileText size={14} />}
                          {doc.filename}
                        </span>
                      </td>
                      <td>
                        <span className={`type-badge ${isTxtDoc(doc) ? 'scraped' : 'pdf'}`}>
                          {isTxtDoc(doc) ? 'WEB / TXT' : (doc.file_type || 'PDF').toUpperCase()}
                        </span>
                      </td>
                      <td className="mono-text">{(doc.size_bytes / 1024).toFixed(1)} KB</td>
                      <td className="mono-text" style={{ fontSize: '0.8rem' }}>{doc.upload_date?.substring(0,19) || '—'}</td>
                      <td style={{ whiteSpace: 'nowrap' }}>
                        <button
                          className="icon-btn"
                          onClick={() => handleView(doc)}
                          title={isTxtDoc(doc) ? 'Preview Content' : 'Open PDF'}
                          style={{ marginRight: '10px' }}
                        >
                          <Eye size={16} />
                        </button>
                        <button className="icon-btn" onClick={() => handleDelete(doc.id)} title="Delete Document">
                          <Trash2 size={16} />
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Document Preview Modal */}
      {previewOpen && (
        <div className="preview-overlay" onClick={() => setPreviewOpen(false)}>
          <div className="preview-modal" onClick={(e) => e.stopPropagation()}>
            {/* Modal Header */}
            <div className="preview-header">
              <div className="preview-header-left">
                <BookOpen size={20} />
                <div>
                  <div className="preview-title">{previewData?.filename || 'Loading...'}</div>
                  {previewData && (
                    <div className="preview-meta-row">
                      <span className="preview-meta-chip"><Hash size={12} /> {previewData.word_count.toLocaleString()} words</span>
                      <span className="preview-meta-chip"><FileText size={12} /> {(previewData.char_count / 1000).toFixed(1)}K chars</span>
                      <span className="type-badge scraped">WEB SCRAPE</span>
                    </div>
                  )}
                </div>
              </div>
              <button className="icon-btn" onClick={() => setPreviewOpen(false)} style={{ fontSize: '1.5rem' }}>
                <X size={22} />
              </button>
            </div>

            {/* Modal Body */}
            <div className="preview-body">
              {previewLoading ? (
                <div className="loading-spinner"><Activity size={32} style={{ animation: 'pulse 1.5s infinite' }} /> Fetching Content...</div>
              ) : previewData ? (
                <div className="markdown-content formatted">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{previewData.content}</ReactMarkdown>
                </div>
              ) : (
                <div className="error-text">Failed to load content.</div>
              )}
            </div>
          </div>
        </div>
      )}

      {message && (
        <div className={`status-toast ${message.includes('ERROR') || message.includes('FAILED') ? 'error' : ''}`}>
          <Activity size={20} /> {message}
          <button
            onClick={() => setMessage('')}
            className="toast-dismiss-btn"
          >
            &times;
          </button>
        </div>
      )}

      <style>{`
        .process-layout {
          display: grid;
          grid-template-columns: 1fr 2fr;
          gap: 2rem;
        }

        @media (max-width: 900px) {
          .process-layout { grid-template-columns: 1fr; }
        }

        .file-input-wrapper {
          position: relative;
          overflow: hidden;
          display: inline-block;
          width: 100%;
          border: 2px dashed var(--border-color);
          text-align: center;
          background: var(--hover-bg);
          transition: var(--transition-speed);
        }

        .file-input-wrapper:hover { background: #e0e0e0; }

        .file-input-wrapper input[type=file] {
          font-size: 100px;
          position: absolute;
          left: 0; top: 0;
          opacity: 0;
          cursor: pointer;
        }

        .file-label {
          display: block;
          padding: 2rem;
          font-family: var(--font-mono);
          font-weight: 600;
          cursor: pointer;
        }

        .task-tracker {
          margin-top: 2rem;
          border-top: 2px solid var(--border-color);
          padding-top: 1rem;
        }

        .task-row {
          display: flex;
          justify-content: space-between;
          padding: 0.5rem 0;
          font-family: var(--font-mono);
          font-size: 0.85rem;
          border-bottom: 1px dotted var(--border-color);
        }

        .status-badge {
          padding: 0.1rem 0.5rem;
          background: var(--text-color);
          color: var(--bg-color);
          font-weight: 700;
          font-size: 0.75rem;
          font-family: var(--font-mono);
        }
        .status-badge.processing { background: #666; }
        .status-badge.completed { background: #000; }
        .status-badge.failure { background: #990000; color: white; }

        .type-badge {
          display: inline-block;
          padding: 0.15rem 0.5rem;
          font-size: 0.7rem;
          font-family: var(--font-mono);
          font-weight: 700;
          letter-spacing: 0.5px;
          border: 1.5px solid var(--border-color);
        }
        .type-badge.scraped { background: #000; color: #fff; border-color: #000; }
        .type-badge.pdf { background: transparent; color: #444; }

        .table-wrapper {
          overflow-x: auto;
          margin-top: 1rem;
          width: 100%;
          -webkit-overflow-scrolling: touch;
        }

        .docs-table {
          width: 100%;
          border-collapse: collapse;
          border: 2px solid var(--border-color);
        }

        .docs-table th, .docs-table td {
          border: 1px solid var(--border-color);
          padding: 0.75rem;
          text-align: left;
          font-size: 0.9rem;
        }

        .docs-table th {
          background-color: var(--text-color);
          color: var(--bg-color);
          font-family: var(--font-display);
          letter-spacing: 1px;
          white-space: nowrap;
        }

        .docs-table tr:hover { background-color: var(--hover-bg); }

        .icon-btn {
          background: none;
          border: none;
          cursor: pointer;
          color: var(--text-color);
          padding: 4px;
        }
        .icon-btn:hover { color: #ff0000; }

        /* Preview Modal */
        .preview-overlay {
          position: fixed;
          inset: 0;
          background: rgba(0, 0, 0, 0.65);
          z-index: 5000;
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 2rem;
          animation: fadeIn 0.2s ease;
        }

        .preview-modal {
          background: var(--bg-color);
          border: 3px solid var(--border-color);
          box-shadow: 8px 8px 0 var(--border-color);
          width: 100%;
          max-width: 860px;
          max-height: 85vh;
          display: flex;
          flex-direction: column;
          animation: scaleIn 0.2s ease;
        }

        @keyframes scaleIn {
          from { transform: scale(0.95); opacity: 0; }
          to { transform: scale(1); opacity: 1; }
        }

        .preview-header {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          padding: 1.25rem 1.5rem;
          border-bottom: 2px solid var(--border-color);
          background: var(--text-color);
          color: var(--bg-color);
          gap: 1rem;
        }

        .preview-header-left {
          display: flex;
          align-items: flex-start;
          gap: 1rem;
          flex: 1;
          min-width: 0;
        }

        .preview-title {
          font-family: var(--font-mono);
          font-weight: 700;
          font-size: 0.95rem;
          word-break: break-all;
          margin-bottom: 0.4rem;
        }

        .preview-meta-row {
          display: flex;
          flex-wrap: wrap;
          gap: 0.5rem;
          align-items: center;
        }

        .preview-meta-chip {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          background: rgba(255,255,255,0.15);
          padding: 0.15rem 0.5rem;
          font-size: 0.75rem;
          font-family: var(--font-mono);
          border-radius: 2px;
        }

        .preview-header .icon-btn { color: var(--bg-color); }
        .preview-header .icon-btn:hover { color: #ffaaaa; }

        .preview-body {
          flex: 1;
          overflow-y: auto;
          padding: 0;
        }

        .markdown-content.formatted {
          padding: 2rem;
          font-family: var(--font-sans);
          line-height: 1.6;
          color: #333;
          font-size: 1rem;
        }

        .markdown-content.formatted h1,
        .markdown-content.formatted h2,
        .markdown-content.formatted h3 {
          font-family: var(--font-mono);
          color: #000;
          margin-top: 1.5em;
          margin-bottom: 0.5em;
          border-bottom: 2px solid #eaeaea;
          padding-bottom: 0.3em;
        }

        .markdown-content.formatted p {
          margin-bottom: 1em;
        }

        .markdown-content.formatted ul,
        .markdown-content.formatted ol {
          margin-bottom: 1em;
          padding-left: 2em;
        }

        .markdown-content.formatted a {
          color: #0056b3;
          text-decoration: underline;
        }

        .markdown-content.formatted code {
          font-family: var(--font-mono);
          background: #f4f4f4;
          padding: 0.1em 0.3em;
          border-radius: 3px;
          font-size: 0.9em;
        }

        .markdown-content.formatted pre {
          background: #111;
          color: #fff;
          padding: 1em;
          overflow-x: auto;
          border-radius: 4px;
        }

        .markdown-content.formatted pre code {
          background: transparent;
          color: inherit;
          padding: 0;
        }

        .markdown-content.formatted blockquote {
          border-left: 4px solid #ccc;
          margin: 0;
          padding-left: 1em;
          color: #666;
          font-style: italic;
        }

        .preview-loading {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 1rem;
          height: 300px;
          font-family: var(--font-mono);
          font-weight: bold;
          letter-spacing: 2px;
          color: #666;
        }

        .preview-content {
          font-family: var(--font-mono);
          font-size: 0.82rem;
          line-height: 1.7;
          white-space: pre-wrap;
          word-break: break-word;
          padding: 2rem;
          margin: 0;
          color: #111;
          border: none;
          background: #fafafa;
        }

        .spin-slow {
          animation: spin 1.5s linear infinite;
        }

        @keyframes spin {
          100% { transform: rotate(360deg); }
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
          max-width: 420px;
        }

        .status-toast.error { border-left-color: #ff0000; }

        @keyframes slideUp {
          from { transform: translateY(100px); opacity: 0; }
          to { transform: translateY(0); opacity: 1; }
        }

        @keyframes fadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }
      `}</style>
    </div>
  );
};

export default Process;
