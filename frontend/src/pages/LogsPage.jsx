import React, { useState, useEffect, useCallback } from 'react';
import toast from 'react-hot-toast';
import { FiRefreshCw, FiList } from 'react-icons/fi';
import { dynamicAgentService } from '../services/api';

const SOURCES = [
  { value: '', label: 'All sources' },
  { value: 'api', label: 'API (developer key)' },
  { value: 'ui', label: 'Web UI / MCP' },
];

const STATUS_CLASS = {
  success: 'badge-success',
  error: 'badge-danger',
  needs_credentials: 'badge-warning',
  needs_tool_setup: 'badge-warning',
};

function LogsPage() {
  const [logs, setLogs] = useState([]);
  const [tools, setTools] = useState([]);
  const [tool, setTool] = useState('');
  const [source, setSource] = useState('');
  const [loading, setLoading] = useState(true);

  const loadLogs = useCallback(async () => {
    try {
      setLoading(true);
      const data = await dynamicAgentService.listLogs({ limit: 100, tool, source });
      setLogs(data || []);
    } catch (err) {
      toast.error('Failed to load logs');
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [tool, source]);

  useEffect(() => {
    loadLogs();
  }, [loadLogs]);

  useEffect(() => {
    dynamicAgentService
      .listLogTools()
      .then((t) => setTools(t || []))
      .catch((err) => console.error(err));
  }, []);

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h1>Logs</h1>
          <p className="page-subtitle">
            Every agent run on your account. Filter by tool or by where the
            request came from.
          </p>
        </div>
        <button
          type="button"
          className="btn btn-ghost btn-icon"
          onClick={loadLogs}
          disabled={loading}
        >
          <FiRefreshCw />
          <span>Refresh</span>
        </button>
      </div>

      <div className="card">
        <div className="form-row">
          <div className="form-group">
            <label htmlFor="tool-filter">Tool</label>
            <select
              id="tool-filter"
              value={tool}
              onChange={(e) => setTool(e.target.value)}
            >
              <option value="">All tools</option>
              {tools.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>
          <div className="form-group">
            <label htmlFor="source-filter">Source</label>
            <select
              id="source-filter"
              value={source}
              onChange={(e) => setSource(e.target.value)}
            >
              {SOURCES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      <div className="card">
        {loading ? (
          <div className="card-empty">Loading logs…</div>
        ) : logs.length === 0 ? (
          <div className="card-empty">
            <FiList className="empty-icon" />
            <p>No logs match these filters.</p>
          </div>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Tool</th>
                  <th>Source</th>
                  <th>Status</th>
                  <th>Prompt</th>
                  <th>Duration</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((r) => (
                  <tr key={r.id}>
                    <td>{new Date(r.created_at).toLocaleString()}</td>
                    <td>{r.tool || '—'}</td>
                    <td>
                      {r.source === 'api' ? (
                        <span className="badge" title="Developer key">
                          {r.key_label || 'API'}
                        </span>
                      ) : (
                        <span className="badge muted">UI</span>
                      )}
                    </td>
                    <td>
                      <span className={`badge ${STATUS_CLASS[r.status] || ''}`}>
                        {r.status}
                      </span>
                    </td>
                    <td className="truncate" title={r.prompt}>
                      {r.prompt}
                    </td>
                    <td>{Math.round(r.duration_ms)} ms</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

export default LogsPage;
