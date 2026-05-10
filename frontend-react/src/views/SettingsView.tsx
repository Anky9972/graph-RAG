import React, { useState, useEffect } from 'react';

interface Settings {
  default_llm_provider: string;
  embedding_provider: string;
  openai_api_key: string;
  openai_model: string;
  anthropic_api_key: string;
  anthropic_model: string;
  google_api_key: string;
  gemini_model: string;
  ollama_base_url: string;
  ollama_model: string;
  ollama_embedding_model: string;
  huggingface_api_key: string;
  huggingface_model: string;
  huggingface_embedding_model: string;
}

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

const SettingsView: React.FC = () => {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const [ollamaModels, setOllamaModels] = useState<string[]>([]);
  const [hfModels, setHfModels] = useState<string[]>([]);

  // State for tracking if custom input is shown
  const [showCustom, setShowCustom] = useState<Record<string, boolean>>({});

  useEffect(() => {
    fetchSettings();
    fetchHfModels();
  }, []);

  useEffect(() => {
    if (settings?.ollama_base_url) {
      fetchOllamaModels(settings.ollama_base_url);
    }
  }, [settings?.ollama_base_url]);

  const fetchOllamaModels = async (baseUrl: string) => {
    try {
      const res = await fetch(`${API_BASE}/system/ollama/models?base_url=${encodeURIComponent(baseUrl)}`);
      if (res.ok) {
        const data = await res.json();
        setOllamaModels(data.models || []);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const fetchHfModels = async () => {
    try {
      const res = await fetch(`${API_BASE}/system/huggingface/models`);
      if (res.ok) {
        const data = await res.json();
        setHfModels(data.models || []);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const fetchSettings = async () => {
    try {
      const response = await fetch(`${API_BASE}/system/settings`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('token')}`
        }
      });
      if (!response.ok) throw new Error('Failed to fetch settings');
      const data = await response.json();
      // Replace nulls with empty strings for input values
      const sanitizedData = Object.keys(data).reduce((acc, key) => {
        acc[key as keyof Settings] = data[key] || '';
        return acc;
      }, {} as Settings);
      setSettings(sanitizedData);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const { name, value } = e.target;
    if (settings) {
      if (value === '__custom__') {
        setShowCustom({ ...showCustom, [name]: true });
        setSettings({ ...settings, [name]: '' });
      } else {
        setSettings({ ...settings, [name]: value });
      }
    }
  };

  const renderDropdownOrInput = (name: keyof Settings, options: string[], placeholder: string = "") => {
    // Always include the current value in the options so the select doesn't break
    const currentValue = settings?.[name] as string;
    const finalOptions = [...options];
    if (currentValue && !finalOptions.includes(currentValue)) {
      finalOptions.unshift(currentValue);
    }

    const isCustom = showCustom[name];
    
    if (isCustom) {
      return (
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <input 
            type="text" 
            name={name} 
            value={currentValue || ''} 
            onChange={handleChange}
            placeholder={placeholder}
            style={{ padding: '0.5rem', border: '1px solid #ccc', flex: 1 }}
          />
          <button 
            type="button" 
            onClick={() => {
              setShowCustom({ ...showCustom, [name]: false });
              setSettings({ ...settings!, [name]: finalOptions[0] || '' });
            }}
            style={{ padding: '0.5rem', background: '#eee', border: '1px solid #ccc', cursor: 'pointer' }}
          >
            Cancel
          </button>
        </div>
      );
    }

    return (
      <select 
        name={name} 
        value={currentValue || ''} 
        onChange={handleChange}
        style={{ padding: '0.5rem', border: '1px solid #ccc' }}
      >
        <option value="" disabled>Select a model...</option>
        {finalOptions.map(m => <option key={m} value={m}>{m}</option>)}
        <option value="__custom__">-- Type custom model --</option>
      </select>
    );
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSuccess(null);

    try {
      const response = await fetch(`${API_BASE}/system/settings`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('token')}`
        },
        body: JSON.stringify(settings)
      });
      
      if (!response.ok) throw new Error('Failed to save settings');
      
      setSuccess('Settings updated successfully!');
      setTimeout(() => setSuccess(null), 3000);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div style={{ padding: '2rem' }}>Loading settings...</div>;

  return (
    <div style={{ padding: '2rem', maxWidth: '800px', margin: '0 auto', fontFamily: 'var(--font-sans)' }}>
      <h1 style={{ fontSize: '1.5rem', marginBottom: '1.5rem', borderBottom: '2px solid #000', paddingBottom: '0.5rem' }}>SYSTEM SETTINGS</h1>
      
      {error && <div style={{ background: '#fee', color: '#c00', padding: '1rem', marginBottom: '1rem', border: '1px solid #c00' }}>{error}</div>}
      {success && <div style={{ background: '#efe', color: '#090', padding: '1rem', marginBottom: '1rem', border: '1px solid #090' }}>{success}</div>}

      <form onSubmit={handleSave} style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
        
        {/* Global Providers */}
        <div style={{ padding: '1.5rem', border: '1px solid #ddd', background: '#fcfcfc' }}>
          <h2 style={{ fontSize: '1.1rem', marginBottom: '1rem' }}>Global Providers</h2>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              <label style={{ fontWeight: 600, fontSize: '0.85rem' }}>Default LLM Provider</label>
              <select 
                name="default_llm_provider" 
                value={settings?.default_llm_provider} 
                onChange={handleChange}
                style={{ padding: '0.5rem', border: '1px solid #ccc' }}
              >
                <option value="ollama">Ollama</option>
                <option value="openai">OpenAI</option>
                <option value="anthropic">Anthropic</option>
                <option value="gemini">Gemini</option>
                <option value="huggingface">Hugging Face</option>
              </select>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              <label style={{ fontWeight: 600, fontSize: '0.85rem' }}>Embedding Provider</label>
              <select 
                name="embedding_provider" 
                value={settings?.embedding_provider} 
                onChange={handleChange}
                style={{ padding: '0.5rem', border: '1px solid #ccc' }}
              >
                <option value="ollama">Ollama</option>
                <option value="openai">OpenAI</option>
                <option value="huggingface">Hugging Face</option>
              </select>
            </div>
          </div>
        </div>

        {/* Hugging Face Settings */}
        <div style={{ padding: '1.5rem', border: '1px solid #ddd' }}>
          <h2 style={{ fontSize: '1.1rem', marginBottom: '1rem' }}>Hugging Face</h2>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              <label style={{ fontWeight: 600, fontSize: '0.85rem' }}>API Token</label>
              <input 
                type="password" 
                name="huggingface_api_key" 
                value={settings?.huggingface_api_key} 
                onChange={handleChange}
                style={{ padding: '0.5rem', border: '1px solid #ccc' }}
                placeholder="hf_..."
              />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              <label style={{ fontWeight: 600, fontSize: '0.85rem' }}>LLM Model</label>
              {renderDropdownOrInput('huggingface_model', hfModels, 'meta-llama/Meta-Llama-3-8B-Instruct')}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              <label style={{ fontWeight: 600, fontSize: '0.85rem' }}>Embedding Model</label>
              {renderDropdownOrInput('huggingface_embedding_model', hfModels, 'BAAI/bge-large-en-v1.5')}
            </div>
          </div>
        </div>

        {/* Gemini Settings */}
        <div style={{ padding: '1.5rem', border: '1px solid #ddd' }}>
          <h2 style={{ fontSize: '1.1rem', marginBottom: '1rem' }}>Google Gemini</h2>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              <label style={{ fontWeight: 600, fontSize: '0.85rem' }}>Google API Key</label>
              <input 
                type="password" 
                name="google_api_key" 
                value={settings?.google_api_key} 
                onChange={handleChange}
                style={{ padding: '0.5rem', border: '1px solid #ccc' }}
              />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              <label style={{ fontWeight: 600, fontSize: '0.85rem' }}>Model</label>
              <input 
                type="text" 
                name="gemini_model" 
                value={settings?.gemini_model} 
                onChange={handleChange}
                style={{ padding: '0.5rem', border: '1px solid #ccc' }}
              />
            </div>
          </div>
        </div>

        {/* Ollama Settings */}
        <div style={{ padding: '1.5rem', border: '1px solid #ddd' }}>
          <h2 style={{ fontSize: '1.1rem', marginBottom: '1rem' }}>Ollama</h2>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', gridColumn: 'span 2' }}>
              <label style={{ fontWeight: 600, fontSize: '0.85rem' }}>Base URL</label>
              <input 
                type="text" 
                name="ollama_base_url" 
                value={settings?.ollama_base_url} 
                onChange={handleChange}
                style={{ padding: '0.5rem', border: '1px solid #ccc' }}
              />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              <label style={{ fontWeight: 600, fontSize: '0.85rem' }}>LLM Model</label>
              {renderDropdownOrInput('ollama_model', ollamaModels, 'llama3')}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              <label style={{ fontWeight: 600, fontSize: '0.85rem' }}>Embedding Model</label>
              {renderDropdownOrInput('ollama_embedding_model', ollamaModels, 'nomic-embed-text')}
            </div>
          </div>
        </div>

        {/* OpenAI Settings */}
        <div style={{ padding: '1.5rem', border: '1px solid #ddd' }}>
          <h2 style={{ fontSize: '1.1rem', marginBottom: '1rem' }}>OpenAI</h2>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              <label style={{ fontWeight: 600, fontSize: '0.85rem' }}>API Key</label>
              <input 
                type="password" 
                name="openai_api_key" 
                value={settings?.openai_api_key} 
                onChange={handleChange}
                style={{ padding: '0.5rem', border: '1px solid #ccc' }}
              />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              <label style={{ fontWeight: 600, fontSize: '0.85rem' }}>Model</label>
              <input 
                type="text" 
                name="openai_model" 
                value={settings?.openai_model} 
                onChange={handleChange}
                style={{ padding: '0.5rem', border: '1px solid #ccc' }}
              />
            </div>
          </div>
        </div>

        {/* Anthropic Settings */}
        <div style={{ padding: '1.5rem', border: '1px solid #ddd' }}>
          <h2 style={{ fontSize: '1.1rem', marginBottom: '1rem' }}>Anthropic</h2>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              <label style={{ fontWeight: 600, fontSize: '0.85rem' }}>API Key</label>
              <input 
                type="password" 
                name="anthropic_api_key" 
                value={settings?.anthropic_api_key} 
                onChange={handleChange}
                style={{ padding: '0.5rem', border: '1px solid #ccc' }}
              />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              <label style={{ fontWeight: 600, fontSize: '0.85rem' }}>Model</label>
              <input 
                type="text" 
                name="anthropic_model" 
                value={settings?.anthropic_model} 
                onChange={handleChange}
                style={{ padding: '0.5rem', border: '1px solid #ccc' }}
              />
            </div>
          </div>
        </div>

        <button 
          type="submit" 
          disabled={saving}
          style={{ 
            padding: '0.75rem', 
            background: '#000', 
            color: '#fff', 
            fontWeight: 'bold', 
            border: 'none', 
            cursor: saving ? 'not-allowed' : 'pointer',
            opacity: saving ? 0.7 : 1,
            marginTop: '1rem'
          }}
        >
          {saving ? 'SAVING...' : 'SAVE SETTINGS'}
        </button>
      </form>
    </div>
  );
};

export default SettingsView;
