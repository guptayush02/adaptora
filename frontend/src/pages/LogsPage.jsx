import React, { useState, useEffect, useCallback, useRef } from 'react';
import toast from 'react-hot-toast';
import {
  FiRefreshCw,
  FiList,
  FiChevronRight,
  FiChevronDown,
  FiAlertTriangle,
} from 'react-icons/fi';
import { dynamicAgentService } from '../services/api';

const SOURCES = [
  { value: '', label: 'All sources' },
  { value: 'api', label: 'API (developer key)' },
  { value: 'ui', label: 'Web UI / MCP' },
];

const STATUSES = [
  { value: '', label: 'All statuses' },
  { value: 'error', label: 'Errors only' },
  { value: 'success', label: 'Success' },
  { value: 'needs_credentials', label: 'Needs credentials' },
  { value: 'needs_tool_setup', label: 'Needs tool setup' },
];

const STATUS_CLASS = {
  success: 'log-badge-success',
  error: 'log-badge-danger',
  needs_credentials: 'log-badge-warning',
  needs_tool_setup: 'log-badge-warning',
};

// Pretty-print a value that may be a JSON string, an object, or plain text.
function pretty(value) {
  if (value === null || value === undefined || value === '') return null;
  if (typeof value === 'object') return JSON.stringify(value, null, 2);
  if (typeof value === 'string') {
    const t = value.trim();
    if (t.startsWith('{') || t.startsWith('[')) {
      try {
        return JSON.stringify(JSON.parse(t), null, 2);
      } catch {
        return value;
      }
    }
  }
  return String(value);
}

// One labelled block in the expanded detail panel. Skips itself if empty.
function DetailBlock({ label, value, mono = false, tone }) {
  const text = mono ? pretty(value) : value;
  if (text === null || text === undefined || text === '') return null;
  return (
    <div className="log-detail-block">
      <div className="log-detail-label">{label}</div>
      {mono ? (
        <pre className={`agent-code ${tone === 'danger' ? 'log-code-danger' : ''}`}>
          {text}
        </pre>
      ) : (
        <div className="log-detail-body">{text}</div>
      )}
    </div>
  );
}

function LogRow({ log, flash }) {
  const [open, setOpen] = useState(false);
  const isError = log.status === 'error' || !!log.error;

  return (
    <>
      <tr
        className={`log-row ${open ? 'log-row-open' : ''} ${flash ? 'log-row-new' : ''}`}
        onClick={() => setOpen((v) => !v)}
      >
        <td className="log-chevron">
          {open ? <FiChevronDown /> : <FiChevronRight />}
        </td>
        <td>{new Date(log.created_at).toLocaleString()}</td>
        <td>{log.tool || '—'}</td>
        <td>
          {log.source === 'api' ? (
            <span className="log-badge" title="Developer key">
              {log.key_label || 'API'}
            </span>
          ) : (
            <span className="log-badge log-badge-muted">UI</span>
          )}
        </td>
        <td>
          <span className={`log-badge ${STATUS_CLASS[log.status] || ''}`}>
            {isError && <FiAlertTriangle />}
            {log.status}
          </span>
        </td>
        <td className="log-prompt" title={log.prompt}>
          {log.prompt}
        </td>
        <td>{Math.round(log.duration_ms)} ms</td>
      </tr>
      {open && (
        <tr className="log-detail-row">
          <td colSpan={7}>
            <div className="log-detail">
              {isError && (
                <DetailBlock
                  label="Error"
                  value={log.error || log.response_body || 'Run failed'}
                  mono
                  tone="danger"
                />
              )}
              <div className="log-detail-meta">
                <span>
                  <strong>Run #</strong>
                  {log.id}
                </span>
                <span>
                  <strong>HTTP</strong> {log.http_status ?? '—'}
                </span>
                <span>
                  <strong>Duration</strong> {Math.round(log.duration_ms)} ms
                </span>
                <span>
                  <strong>Lang</strong> {log.language}
                </span>
              </div>
              <DetailBlock label="Prompt" value={log.prompt} mono />
              <DetailBlock label="Thought (reasoning)" value={log.thought} />
              <DetailBlock label="Action" value={log.action} mono />
              <DetailBlock
                label="Planned request (action input)"
                value={log.action_input}
                mono
              />
              <DetailBlock
                label="Raw response body"
                value={log.response_body}
                mono
              />
              <DetailBlock label="Summary" value={log.summary} />
              <DetailBlock label="Final answer" value={log.final_answer} />
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function LogsPage() {
  const [logs, setLogs] = useState([]);
  const [tools, setTools] = useState([]);
  const [tool, setTool] = useState('');
  const [source, setSource] = useState('');
  const [status, setStatus] = useState('');
  const [loading, setLoading] = useState(true);
  const [live, setLive] = useState(true);
  const [flashIds, setFlashIds] = useState(() => new Set());
  // Prevents overlapping polls if a request is slow.
  const inFlight = useRef(false);
  // Run ids we've already shown, so a live poll can flag genuinely new ones.
  const seenIds = useRef(new Set());

  // `silent` refreshes (the live poll) skip the loading spinner so the table
  // doesn't flicker, and surface a toast only on the very first failure. On a
  // silent poll we briefly highlight rows that weren't there before.
  const loadLogs = useCallback(
    async ({ silent = false } = {}) => {
      if (inFlight.current) return;
      inFlight.current = true;
      if (!silent) setLoading(true);
      try {
        const data = await dynamicAgentService.listLogs({
          limit: 100,
          tool,
          source,
          status,
        });
        const rows = data || [];
        if (silent) {
          const fresh = rows
            .filter((r) => !seenIds.current.has(r.id))
            .map((r) => r.id);
          if (fresh.length) setFlashIds(new Set(fresh));
        }
        rows.forEach((r) => seenIds.current.add(r.id));
        setLogs(rows);
      } catch (err) {
        if (!silent) toast.error('Failed to load logs');
        console.error(err);
      } finally {
        inFlight.current = false;
        if (!silent) setLoading(false);
      }
    },
    [tool, source, status]
  );

  // Re-fetch whenever filters change (with spinner).
  useEffect(() => {
    loadLogs();
  }, [loadLogs]);

  // Live tail: poll the shared DB every few seconds. Reads completed runs from
  // every source (web UI, public /api/v1, and the separate MCP server process),
  // which an in-process push could not. Pauses when the tab is hidden.
  useEffect(() => {
    if (!live) return undefined;
    const id = setInterval(() => {
      if (document.visibilityState === 'visible') loadLogs({ silent: true });
    }, 4000);
    return () => clearInterval(id);
  }, [live, loadLogs]);

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
            Every agent run on your account. Click a row to expand the full
            trace — reasoning, the planned request, the raw response, and any
            error — so you can debug failures step by step.
          </p>
        </div>
        <div className="log-header-actions">
          <button
            type="button"
            className={`btn btn-icon ${live ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => setLive((v) => !v)}
            title={live ? 'Live updates on — click to pause' : 'Click to resume live updates'}
          >
            <span className={`log-live-dot ${live ? 'log-live-dot-on' : ''}`} />
            <span>{live ? 'Live' : 'Paused'}</span>
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-icon"
            onClick={() => loadLogs()}
            disabled={loading}
          >
            <FiRefreshCw />
            <span>Refresh</span>
          </button>
        </div>
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
            <label htmlFor="status-filter">Status</label>
            <select
              id="status-filter"
              value={status}
              onChange={(e) => setStatus(e.target.value)}
            >
              {STATUSES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
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
            <table className="data-table log-table">
              <thead>
                <tr>
                  <th aria-label="expand" />
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
                  <LogRow key={r.id} log={r} flash={flashIds.has(r.id)} />
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
