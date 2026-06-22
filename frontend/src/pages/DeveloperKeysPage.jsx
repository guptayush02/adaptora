import React, { useState, useEffect } from 'react';
import toast from 'react-hot-toast';
import { FiPlus, FiTrash2, FiKey, FiX, FiCopy, FiInfo } from 'react-icons/fi';
import { authService } from '../services/api';

function DeveloperKeysPage() {
  const [keys, setKeys] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [label, setLabel] = useState('');
  const [formLoading, setFormLoading] = useState(false);
  // The raw secret is only ever returned once, at creation. We hold it in
  // state so the user can copy it, then it's gone forever.
  const [newSecret, setNewSecret] = useState(null);

  const apiBase = import.meta.env.VITE_API_BASE_URL || window.location.origin;

  useEffect(() => {
    loadKeys();
  }, []);

  const loadKeys = async () => {
    try {
      setLoading(true);
      const data = await authService.listDeveloperKeys();
      setKeys(data || []);
    } catch (err) {
      toast.error('Failed to load developer keys');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async (e) => {
    e.preventDefault();
    if (!label.trim()) {
      toast.error('Give the key a name');
      return;
    }
    setFormLoading(true);
    try {
      const created = await authService.createDeveloperKey(label.trim());
      setNewSecret(created);
      setLabel('');
      setShowForm(false);
      await loadKeys();
      toast.success('Key created — copy it now, it won’t be shown again');
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to create key');
      console.error(err);
    } finally {
      setFormLoading(false);
    }
  };

  const handleRevoke = async (keyId) => {
    if (!window.confirm('Revoke this key? Projects using it will stop working.'))
      return;
    try {
      await authService.revokeDeveloperKey(keyId);
      toast.success('Key revoked');
      await loadKeys();
    } catch (err) {
      toast.error('Failed to revoke key');
      console.error(err);
    }
  };

  const copy = (text) => {
    navigator.clipboard?.writeText(text);
    toast.success('Copied to clipboard');
  };

  const handleCopyExisting = async (keyId) => {
    try {
      const { secret_key } = await authService.revealDeveloperKey(keyId);
      copy(secret_key);
    } catch (err) {
      toast.error(
        err.response?.data?.detail || 'Could not reveal this key'
      );
      console.error(err);
    }
  };

  const curlSnippet = (secret) =>
    `curl -X POST ${apiBase}/api/v1/run \\\n` +
    `  -H "Authorization: Bearer ${secret}" \\\n` +
    `  -H "Content-Type: application/json" \\\n` +
    `  -d '{"prompt": "list my github repos"}'`;

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h1>Developer Keys</h1>
          <p className="page-subtitle">
            Secret keys to call Adaptora from your own project via the REST API.
            Each call runs against your saved tool connections and is logged.
          </p>
        </div>
        <button
          type="button"
          className="btn btn-primary btn-icon"
          onClick={() => setShowForm((v) => !v)}
        >
          {showForm ? <FiX /> : <FiPlus />}
          <span>{showForm ? 'Cancel' : 'New key'}</span>
        </button>
      </div>

      {newSecret && (
        <div className="card" style={{ borderColor: 'var(--color-primary, #6366f1)' }}>
          <h2 className="card-title">Your new secret key</h2>
          <p className="muted">
            Copy this now — for security it is shown <strong>only once</strong>.
          </p>
          <div className="input-with-action">
            <input type="text" readOnly value={newSecret.secret_key} />
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => copy(newSecret.secret_key)}
            >
              <FiCopy /> Copy
            </button>
          </div>
          <h3 className="card-title" style={{ marginTop: '1rem' }}>
            Use it
          </h3>
          <pre className="code-block" style={{ whiteSpace: 'pre-wrap' }}>
            {curlSnippet(newSecret.secret_key)}
          </pre>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => setNewSecret(null)}
          >
            Done
          </button>
        </div>
      )}

      {showForm && (
        <div className="card">
          <h2 className="card-title">Create a developer key</h2>
          <form onSubmit={handleCreate} className="api-key-form">
            <div className="form-group">
              <label htmlFor="label">Name</label>
              <input
                id="label"
                type="text"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="e.g. production-backend"
                disabled={formLoading}
              />
            </div>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={formLoading}
              style={{ marginTop: '1rem' }}
            >
              {formLoading ? 'Creating…' : 'Create key'}
            </button>
          </form>
        </div>
      )}

      <div className="card">
        <h2 className="card-title">Your keys</h2>
        {loading ? (
          <div className="card-empty">Loading keys…</div>
        ) : keys.length === 0 ? (
          <div className="card-empty">
            <FiKey className="empty-icon" />
            <p>No developer keys yet.</p>
            <p className="hint">Create one to call Adaptora from your project.</p>
          </div>
        ) : (
          <ul className="api-key-list">
            {keys.map((k) => (
              <li key={k.id} className="api-key-row">
                <div className="api-key-meta">
                  <div className="api-key-provider">{k.label}</div>
                  <div className="api-key-masked">
                    {k.key_prefix}…{k.last_four}
                  </div>
                  <div className="api-key-model">
                    {k.is_active ? (
                      <span>
                        Active
                        {k.last_used_at
                          ? ` · last used ${new Date(
                              k.last_used_at
                            ).toLocaleString()}`
                          : ' · never used'}
                      </span>
                    ) : (
                      <span className="muted">Revoked</span>
                    )}
                  </div>
                </div>
                {k.is_active && (
                  <div style={{ display: 'flex', gap: '0.5rem' }}>
                    <button
                      type="button"
                      className="btn btn-ghost btn-icon btn-sm"
                      onClick={() => handleCopyExisting(k.id)}
                    >
                      <FiCopy />
                      <span>Copy</span>
                    </button>
                    <button
                      type="button"
                      className="btn btn-danger btn-icon btn-sm"
                      onClick={() => handleRevoke(k.id)}
                    >
                      <FiTrash2 />
                      <span>Revoke</span>
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="card">
        <h2 className="card-title">cURL integration example</h2>
        <p className="muted">
          Replace <code>adp_live_YOUR_KEY</code> with one of your keys (use the{' '}
          <strong>Copy</strong> button above), then call the agent from anywhere:
        </p>
        <div className="input-with-action" style={{ alignItems: 'flex-start' }}>
          <pre className="code-block" style={{ whiteSpace: 'pre-wrap', flex: 1, margin: 0 }}>
            {curlSnippet('adp_live_YOUR_KEY')}
          </pre>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => copy(curlSnippet('adp_live_YOUR_KEY'))}
          >
            <FiCopy /> Copy
          </button>
        </div>
      </div>

      <div className="card info-card">
        <h2 className="card-title">
          <FiInfo /> How it works
        </h2>
        <ul className="info-list">
          <li>
            Send <code>Authorization: Bearer &lt;your-key&gt;</code> to{' '}
            <code>POST {apiBase}/api/v1/run</code> with a JSON body{' '}
            <code>{'{ "prompt": "…" }'}</code>.
          </li>
          <li>The agent runs against the tools you’ve connected in this account.</li>
          <li>
            Every call appears under <strong>Logs</strong>, tagged with this key
            and filterable by tool.
          </li>
        </ul>
      </div>
    </div>
  );
}

export default DeveloperKeysPage;
