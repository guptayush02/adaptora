import React, { useState, useEffect } from 'react';
import toast from 'react-hot-toast';
import { FiPlus, FiTrash2, FiKey, FiX, FiInfo } from 'react-icons/fi';
import { authService } from '../services/api';

const PROVIDERS = [
  {
    value: 'openai',
    label: 'OpenAI',
    fallbackModels: ['gpt-4', 'gpt-3.5-turbo'],
    helpUrl: 'https://platform.openai.com/api-keys',
  },
  {
    value: 'anthropic',
    label: 'Anthropic',
    fallbackModels: ['claude-3-opus', 'claude-3-sonnet'],
    helpUrl: 'https://console.anthropic.com/',
  },
  {
    value: 'ollama',
    label: 'Local AI',
    fallbackModels: ['mistral', 'llama2', 'neural-chat'],
    helpUrl: 'https://ollama.ai/',
  },
];

const providerLabel = (val) =>
  PROVIDERS.find((p) => p.value === val)?.label || val;

function ApiKeysPage() {
  const [apiKeys, setApiKeys] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [formLoading, setFormLoading] = useState(false);
  const [formData, setFormData] = useState({
    provider: 'openai',
    model_name: 'gpt-4',
    api_key: '',
  });
  const [modelOptions, setModelOptions] = useState([]);

  useEffect(() => {
    loadAPIKeys();
  }, []);

  const loadAPIKeys = async () => {
    try {
      setLoading(true);
      const keys = await authService.getAPIKeys();
      setApiKeys(keys || []);
    } catch (error) {
      toast.error('Failed to load API keys');
      console.error('Load error:', error);
    } finally {
      setLoading(false);
    }
  };

  const fetchModels = async (provider, api_key) => {
    try {
      setFormLoading(true);
      const res = await authService.getModels(provider, api_key);
      const models = res?.models || [];
      const fallback =
        PROVIDERS.find((p) => p.value === provider)?.fallbackModels || [];
      const list = models.length ? models : fallback;
      setModelOptions(list);
      setFormData((prev) => ({
        ...prev,
        model_name: list[0] || prev.model_name,
      }));
    } catch (err) {
      toast.error('Unable to fetch models for provider');
      console.error('Fetch models error:', err);
    } finally {
      setFormLoading(false);
    }
  };

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  const handleProviderChange = (e) => {
    const provider = e.target.value;
    const fallback =
      PROVIDERS.find((p) => p.value === provider)?.fallbackModels || [];
    setFormData((prev) => ({
      ...prev,
      provider,
      model_name: fallback[0] || '',
    }));
    setModelOptions(fallback);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (formData.provider !== 'ollama' && !formData.api_key.trim()) {
      toast.error('Please enter an API key');
      return;
    }
    setFormLoading(true);
    try {
      await authService.addAPIKey(
        formData.provider,
        formData.model_name,
        formData.api_key
      );
      toast.success('API key saved!');
      await loadAPIKeys();
      setFormData({ provider: 'openai', model_name: 'gpt-4', api_key: '' });
      setModelOptions([]);
      setShowForm(false);
    } catch (error) {
      toast.error(error.response?.data?.detail || error.message || 'Failed to add API key');
      console.error('Add error:', error);
    } finally {
      setFormLoading(false);
    }
  };

  const handleDelete = async (keyId) => {
    if (!window.confirm('Delete this API key?')) return;
    try {
      await authService.deleteAPIKey(keyId);
      toast.success('API key deleted');
      await loadAPIKeys();
    } catch (error) {
      toast.error('Failed to delete API key');
      console.error('Delete error:', error);
    }
  };

  const currentProvider = PROVIDERS.find((p) => p.value === formData.provider);
  const currentProviderModels =
    modelOptions.length
      ? modelOptions
      : currentProvider?.fallbackModels || [];

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h1>API Keys</h1>
          <p className="page-subtitle">
            Connect your provider accounts. Keys are encrypted and only the masked form is shown back.
          </p>
        </div>
        <button
          type="button"
          className="btn btn-primary btn-icon"
          onClick={() => setShowForm((v) => !v)}
        >
          {showForm ? <FiX /> : <FiPlus />}
          <span>{showForm ? 'Cancel' : 'Add API Key'}</span>
        </button>
      </div>

      {showForm && (
        <div className="card">
          <h2 className="card-title">Add or update an API key</h2>
          <form onSubmit={handleSubmit} className="api-key-form">
            <div className="form-row">
              <div className="form-group">
                <label htmlFor="provider">Provider</label>
                <select
                  id="provider"
                  name="provider"
                  value={formData.provider}
                  onChange={handleProviderChange}
                  disabled={formLoading}
                >
                  {PROVIDERS.map((p) => (
                    <option key={p.value} value={p.value}>
                      {p.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label htmlFor="model_name">Default model</label>
                <select
                  id="model_name"
                  name="model_name"
                  value={formData.model_name}
                  onChange={handleChange}
                  disabled={formLoading}
                >
                  {currentProviderModels.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="form-group">
              <label htmlFor="api_key">
                API key{' '}
                {formData.provider === 'ollama' && (
                  <span className="muted">(optional for local AI)</span>
                )}
              </label>
              <div className="input-with-action">
                <input
                  type="password"
                  id="api_key"
                  name="api_key"
                  value={formData.api_key}
                  onChange={handleChange}
                  placeholder={
                    formData.provider === 'ollama'
                      ? 'Leave empty for the local AI'
                      : 'sk-…'
                  }
                  disabled={formLoading}
                />
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() =>
                    fetchModels(formData.provider, formData.api_key)
                  }
                  disabled={formLoading}
                >
                  Fetch models
                </button>
              </div>
            </div>

            <button
              type="submit"
              className="btn btn-primary"
              disabled={formLoading}
            >
              {formLoading ? 'Saving…' : 'Save API key'}
            </button>
          </form>
        </div>
      )}

      <div className="card">
        <h2 className="card-title">Saved keys</h2>
        {loading ? (
          <div className="card-empty">Loading API keys…</div>
        ) : apiKeys.length === 0 ? (
          <div className="card-empty">
            <FiKey className="empty-icon" />
            <p>No API keys configured yet.</p>
            <p className="hint">Add a key to enable advanced model routing.</p>
          </div>
        ) : (
          <ul className="api-key-list">
            {apiKeys.map((key) => (
              <li key={key.id} className="api-key-row">
                <div className="api-key-meta">
                  <div className="api-key-provider">
                    {providerLabel(key.provider)}
                  </div>
                  <div className="api-key-model">{key.model_name}</div>
                  <div className="api-key-masked">
                    {key.masked_key || '••••••'}
                  </div>
                </div>
                <button
                  type="button"
                  className="btn btn-danger btn-icon btn-sm"
                  onClick={() => handleDelete(key.id)}
                >
                  <FiTrash2 />
                  <span>Delete</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="card info-card">
        <h2 className="card-title">
          <FiInfo /> Where to get keys
        </h2>
        <ul className="info-list">
          {PROVIDERS.filter((p) => p.value !== 'ollama').map((p) => (
            <li key={p.value}>
              <strong>{p.label}:</strong>{' '}
              <a href={p.helpUrl} target="_blank" rel="noreferrer">
                {p.helpUrl}
              </a>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export default ApiKeysPage;
