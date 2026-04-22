import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { LogIn, UserPlus, Eye, EyeOff } from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

/* ─── Typewriter ─── */
const useTypewriter = (words: string[], speed = 80, pause = 2200) => {
  const [index, setIndex] = useState(0);
  const [sub, setSub] = useState(0);
  const [deleting, setDeleting] = useState(false);
  const [text, setText] = useState('');
  useEffect(() => {
    const word = words[index % words.length];
    const timer = setTimeout(() => {
      if (!deleting) {
        setText(word.slice(0, sub + 1));
        setSub(s => s + 1);
        if (sub + 1 === word.length) setTimeout(() => setDeleting(true), pause);
      } else {
        setText(word.slice(0, sub - 1));
        setSub(s => s - 1);
        if (sub - 1 === 0) { setDeleting(false); setIndex(i => i + 1); }
      }
    }, deleting ? speed / 2 : speed);
    return () => clearTimeout(timer);
  }, [sub, deleting, index]);
  return text;
};

const Login: React.FC = () => {
  const [isRegistering, setIsRegistering] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  const { login } = useAuth();
  const navigate = useNavigate();

  const rotatingWords = ['Knowledge Graphs.', 'Logic Engines.', 'LLM Reasoning.', 'Entity Networks.', 'Semantic Search.'];
  const rotating = useTypewriter(rotatingWords);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      if (isRegistering) {
        const regRes = await fetch(`${API_BASE}/auth/register`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, password, scopes: ['read', 'write', 'admin'] }),
        });
        if (!regRes.ok) {
          const errData = await regRes.json();
          throw new Error(errData.detail || 'Registration failed');
        }
      }
      const loginRes = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      if (!loginRes.ok) {
        const errData = await loginRes.json();
        throw new Error(errData.detail || 'Login failed');
      }
      const { access_token } = await loginRes.json();
      const userRes = await fetch(`${API_BASE}/auth/me`, {
        headers: { Authorization: `Bearer ${access_token}` },
      });
      if (!userRes.ok) throw new Error('Failed to fetch user profile');
      const user = await userRes.json();
      login(access_token, user);
      navigate('/');
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="lp-root">

      {/* ── Brand mark top-left ── */}
      <div className="lp-brand">
        <span className="lp-brand-dot" />
        CORTEX
      </div>

      {/* ── Version badge top-right ── */}
      <div className="lp-version">v1.0 · PRODUCTION</div>

      {/* ── Giant background wordmark ── */}
      <div className="lp-bg-word" aria-hidden>COR</div>
      <div className="lp-bg-word lp-bg-word-2" aria-hidden>TEX</div>

      {/* ── Hero headline, top-center area ── */}
      <div className="lp-headline">
        <div className="lp-headline-super">AGENTIC KNOWLEDGE PLATFORM</div>
        <h1 className="lp-headline-h1">
          Enterprise-grade<br/>
          <span className="lp-headline-rotating">
            {rotating}<span className="lp-cursor">|</span>
          </span>
        </h1>
      </div>

      {/* ── Floating stat chips ── */}
      <div className="lp-stat lp-stat-1">
        <div className="lp-stat-num">Neo4j</div>
        <div className="lp-stat-key">GRAPH ENGINE</div>
      </div>
      <div className="lp-stat lp-stat-2">
        <div className="lp-stat-num">ReACT</div>
        <div className="lp-stat-key">AGENT LOOP</div>
      </div>
      <div className="lp-stat lp-stat-3">
        <div className="lp-stat-num">EVAL</div>
        <div className="lp-stat-key">SCORING</div>
      </div>
      <div className="lp-stat lp-stat-4">
        <div className="lp-stat-num">Multi-hop</div>
        <div className="lp-stat-key">REASONING</div>
      </div>

      {/* ── Vertical feature list bottom-left ── */}
      <div className="lp-features">
        <div className="lp-features-label">CAPABILITIES</div>
        {[
          'Document ingestion → Knowledge graph',
          'LLM entity & relationship extraction',
          'Agentic multi-step query reasoning',
          'Hallucination risk scoring',
          'Ontology drift detection & governance',
          'Entity enrichment & deduplication',
          'Interactive D3 force visualization',
          'Export: JSON · Cypher · GraphML',
        ].map((f, i) => (
          <div key={i} className="lp-feature-row">
            <span className="lp-feature-tick">→</span>
            <span>{f}</span>
          </div>
        ))}
      </div>

      {/* ── Horizontal tech stack bottom-center ── */}
      <div className="lp-stack">
        {['FastAPI', 'Neo4j', 'Redis', 'Celery', 'Gemini', 'LangChain'].map(t => (
          <span key={t} className="lp-stack-tag">{t}</span>
        ))}
      </div>

      {/* ── Bottom-right quote ── */}
      <div className="lp-quote">
        "Knowledge is only useful<br/>when it can be reasoned over."
      </div>

      {/* ── Decorative rule lines ── */}
      <div className="lp-rule lp-rule-h1" aria-hidden />
      <div className="lp-rule lp-rule-h2" aria-hidden />
      <div className="lp-rule lp-rule-v1" aria-hidden />

      {/* ── LOGIN CARD (right side, vertically centered) ── */}
      <div className="lp-card-wrap">
        <div className="login-card">
          <h2 className="login-title">
            {isRegistering ? 'INITIALIZE ACCESS' : 'SYSTEM AUTH'}
          </h2>

          {error && <div className="error-banner">{error}</div>}

          <form onSubmit={handleSubmit} className="login-form">
            <div className="input-group">
              <label>IDENTIFIER [USER]</label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                className="mono-text"
                autoComplete="username"
              />
            </div>

            <div className="input-group">
              <label>KEY [PASS]</label>
              <div className="password-wrapper">
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  className="mono-text"
                  autoComplete="current-password"
                />
                <button
                  type="button"
                  className="eye-btn"
                  onClick={() => setShowPassword(!showPassword)}
                  tabIndex={-1}
                  title="Toggle visibility"
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            <button type="submit" className="app-btn auth-btn" disabled={loading}>
              {loading
                ? 'PROCESSING...'
                : isRegistering
                  ? <><UserPlus size={16} /> REGISTER</>
                  : <><LogIn size={16} /> AUTHENTICATE →</>
              }
            </button>
          </form>

          <p className="toggle-mode">
            <button type="button" className="text-btn" onClick={() => setIsRegistering(!isRegistering)}>
              {isRegistering ? 'RETURN TO LOGIN' : 'REQUEST ACCESS (REGISTER)'}
            </button>
          </p>

          <div className="lp-card-footer">
            <span>CORTEX PLATFORM</span>
            <span>SECURED · ENCRYPTED</span>
          </div>
        </div>
      </div>

      <style>{`
        /* ── Root ── */
        .lp-root {
          position: fixed;
          inset: 0;
          background: #fff;
          overflow: hidden;
          font-family: var(--font-sans);
        }

        /* ── Brand top-left ── */
        .lp-brand {
          position: absolute;
          top: 2rem;
          left: 2.5rem;
          font-family: var(--font-mono);
          font-size: 0.75rem;
          font-weight: 900;
          letter-spacing: 3px;
          display: flex;
          align-items: center;
          gap: 0.5rem;
          z-index: 10;
        }
        .lp-brand-dot {
          width: 8px; height: 8px;
          background: #000;
          border-radius: 50%;
          animation: brandPulse 2.5s ease-in-out infinite;
        }
        @keyframes brandPulse {
          0%, 100% { transform: scale(1); }
          50% { transform: scale(1.4); }
        }

        /* ── Version badge ── */
        .lp-version {
          position: absolute;
          top: 2rem;
          right: 420px;
          font-family: var(--font-mono);
          font-size: 0.65rem;
          font-weight: 700;
          letter-spacing: 2px;
          color: #aaa;
          z-index: 10;
        }

        /* ── Giant background wordmarks ── */
        .lp-bg-word {
          position: absolute;
          top: -0.15em;
          left: -0.05em;
          font-family: var(--font-display);
          font-size: clamp(200px, 28vw, 380px);
          font-weight: 900;
          line-height: 1;
          color: transparent;
          -webkit-text-stroke: 1.5px #ebebeb;
          letter-spacing: -0.04em;
          pointer-events: none;
          user-select: none;
          z-index: 0;
        }
        .lp-bg-word-2 {
          top: auto;
          bottom: -0.1em;
          left: auto;
          right: 360px;
          -webkit-text-stroke: 1.5px #f0f0f0;
          font-size: clamp(160px, 22vw, 300px);
        }

        /* ── Hero headline ── */
        .lp-headline {
          position: absolute;
          top: 5rem;
          left: 2.5rem;
          right: 420px;
          z-index: 5;
        }
        .lp-headline-super {
          font-family: var(--font-mono);
          font-size: 0.65rem;
          font-weight: 700;
          letter-spacing: 4px;
          color: #999;
          margin-bottom: 0.75rem;
        }
        .lp-headline-h1 {
          font-family: var(--font-display);
          font-size: clamp(2rem, 3.8vw, 3.4rem);
          font-weight: 800;
          line-height: 1.15;
          letter-spacing: -0.5px;
        }
        .lp-headline-rotating {
          display: inline-block;
          border-bottom: 4px solid #000;
          min-width: 2ch;
        }
        .lp-cursor {
          display: inline-block;
          width: 2px;
          animation: blink 0.9s step-end infinite;
          font-weight: 300;
          margin-left: 1px;
        }
        @keyframes blink { 50% { opacity: 0; } }

        /* ── Floating stat chips ── */
        .lp-stat {
          position: absolute;
          border: 2px solid #000;
          padding: 0.6rem 0.9rem;
          z-index: 5;
          background: #fff;
          transition: transform 0.2s, box-shadow 0.2s;
        }
        .lp-stat:hover {
          transform: translateY(-3px);
          box-shadow: 4px 4px 0 #000;
        }
        .lp-stat-num {
          font-family: var(--font-mono);
          font-size: 0.88rem;
          font-weight: 900;
          line-height: 1;
          margin-bottom: 0.2rem;
        }
        .lp-stat-key {
          font-family: var(--font-mono);
          font-size: 0.58rem;
          color: #888;
          letter-spacing: 1px;
          font-weight: 700;
        }
        .lp-stat-1 { top: 36%;  left: 2.5rem; }
        .lp-stat-2 { top: 37%;  left: 9rem; }
        .lp-stat-3 { top: 44%;  left: 2.5rem; }
        .lp-stat-4 { top: 44%;  left: 9rem; }

        /* ── Feature list ── */
        .lp-features {
          position: absolute;
          bottom: 5rem;
          left: 2.5rem;
          width: 340px;
          z-index: 5;
        }
        .lp-features-label {
          font-family: var(--font-mono);
          font-size: 0.6rem;
          font-weight: 700;
          letter-spacing: 3px;
          color: #bbb;
          margin-bottom: 0.6rem;
        }
        .lp-feature-row {
          display: flex;
          gap: 0.5rem;
          font-family: var(--font-sans);
          font-size: 0.78rem;
          color: #333;
          padding: 0.22rem 0;
          border-bottom: 1px solid #f0f0f0;
          line-height: 1.5;
        }
        .lp-feature-tick {
          font-family: var(--font-mono);
          font-size: 0.72rem;
          font-weight: 700;
          color: #000;
          flex-shrink: 0;
          margin-top: 1px;
        }

        /* ── Tech stack ── */
        .lp-stack {
          position: absolute;
          bottom: 1.75rem;
          left: 2.5rem;
          right: 420px;
          display: flex;
          gap: 0.5rem;
          flex-wrap: wrap;
          z-index: 5;
        }
        .lp-stack-tag {
          font-family: var(--font-mono);
          font-size: 0.65rem;
          font-weight: 700;
          letter-spacing: 0.5px;
          border: 1.5px solid #000;
          padding: 2px 8px;
          background: #fff;
        }

        /* ── Bottom-right quote ── */
        .lp-quote {
          position: absolute;
          bottom: 4rem;
          right: 420px;
          width: 240px;
          font-family: var(--font-display);
          font-size: 0.82rem;
          font-style: italic;
          color: #bbb;
          text-align: right;
          line-height: 1.6;
          z-index: 5;
        }

        /* ── Decorative rules ── */
        .lp-rule {
          position: absolute;
          background: #e8e8e8;
          z-index: 4;
          pointer-events: none;
        }
        .lp-rule-h1 {
          top: 4rem;
          left: 0; right: 0;
          height: 1px;
        }
        .lp-rule-h2 {
          bottom: 3.5rem;
          left: 0; right: 0;
          height: 1px;
        }
        .lp-rule-v1 {
          top: 0; bottom: 0;
          right: 400px;
          width: 2px;
          background: #000;
        }

        /* ── Login card ── */
        .lp-card-wrap {
          position: absolute;
          top: 0; bottom: 0;
          right: 0;
          width: 400px;
          display: flex;
          align-items: center;
          justify-content: center;
          background: #fff;
          z-index: 20;
          padding: 2rem 2.5rem;
        }

        .login-card {
          width: 100%;
          animation: slideUp 0.45s ease both;
        }
        @keyframes slideUp {
          from { transform: translateY(16px); opacity: 0; }
          to   { transform: translateY(0);    opacity: 1; }
        }

        .login-title {
          font-family: var(--font-display);
          font-size: 1.15rem;
          font-weight: 800;
          letter-spacing: 2px;
          margin-bottom: 2rem;
          text-transform: uppercase;
          border-bottom: 3px solid #000;
          padding-bottom: 1rem;
        }

        .input-group {
          margin-bottom: 1.25rem;
        }
        .input-group label {
          display: block;
          font-family: var(--font-mono);
          font-size: 0.72rem;
          font-weight: 700;
          letter-spacing: 1px;
          margin-bottom: 0.4rem;
          color: #555;
        }
        .input-group input {
          width: 100%;
          border: 2px solid #000;
          padding: 0.75rem;
          font-size: 0.95rem;
          background: #fafafa;
          transition: box-shadow 0.15s;
        }
        .input-group input:focus {
          outline: none;
          box-shadow: 3px 3px 0 #000;
          background: #fff;
        }
        .password-wrapper {
          position: relative;
          display: flex;
          align-items: center;
        }
        .password-wrapper input { padding-right: 2.5rem; }
        .eye-btn {
          position: absolute;
          right: 0.5rem;
          background: none !important;
          border: none !important;
          cursor: pointer;
          color: #888;
          display: flex;
          align-items: center;
          transition: color 0.15s !important;
        }
        .eye-btn:hover { background: none !important; color: #000 !important; }

        .auth-btn {
          width: 100%;
          padding: 0.9rem;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 0.5rem;
          margin-top: 0.5rem;
          font-size: 0.85rem;
          letter-spacing: 1px;
          background: #000;
          color: #fff;
          border: 2px solid #000;
          transition: background 0.15s, transform 0.15s;
        }
        .auth-btn:hover:not(:disabled) {
          background: #222;
          transform: translateY(-1px);
          box-shadow: 3px 3px 0 rgba(0,0,0,0.2);
        }
        .auth-btn:disabled { opacity: 0.5; }

        .error-banner {
          background: #000;
          color: #fff;
          padding: 0.6rem 0.75rem;
          margin-bottom: 1.25rem;
          font-family: var(--font-mono);
          font-size: 0.78rem;
          border-left: 4px solid #dc2626;
        }

        .toggle-mode {
          text-align: center;
          margin-top: 1.25rem;
        }
        .text-btn {
          background: none;
          border: none;
          color: #555;
          text-decoration: underline;
          text-underline-offset: 4px;
          cursor: pointer;
          font-family: var(--font-mono);
          font-size: 0.72rem;
          letter-spacing: 0.5px;
          transition: color 0.15s;
        }
        .text-btn:hover { color: #000; background: none; }

        .lp-card-footer {
          display: flex;
          justify-content: space-between;
          margin-top: 2rem;
          padding-top: 1rem;
          border-top: 1px solid #e5e5e5;
          font-family: var(--font-mono);
          font-size: 0.6rem;
          color: #bbb;
          letter-spacing: 0.5px;
        }

        /* ── Responsive ── */
        @media (max-width: 800px) {
          .lp-headline { right: 2rem; }
          .lp-version { right: 2rem; }
          .lp-rule-v1 { display: none; }
          .lp-card-wrap {
            position: fixed;
            inset: 0;
            width: 100%;
            background: rgba(255,255,255,0.95);
            backdrop-filter: blur(8px);
          }
          .lp-bg-word, .lp-bg-word-2, .lp-features, .lp-stack, .lp-quote,
          .lp-stat-1, .lp-stat-2, .lp-stat-3, .lp-stat-4 { display: none; }
        }

        @media (max-height: 750px) {
          .lp-headline { top: 4rem; }
          .lp-headline-h1 { font-size: clamp(1.8rem, 3.5vw, 2.8rem); }
          .lp-stat-1 { top: 32%; }
          .lp-stat-2 { top: 33%; }
          .lp-stat-3 { top: 41%; }
          .lp-stat-4 { top: 41%; }
          .lp-features { bottom: 4rem; transform: scale(0.9); transform-origin: left bottom; }
          .lp-stack { display: none; }
        }
      `}</style>
    </div>
  );
};

export default Login;
