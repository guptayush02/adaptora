import React, { useState, useEffect, useCallback, useRef } from 'react';
import toast from 'react-hot-toast';
import {
  FiRefreshCw,
  FiList,
  FiChevronRight,
  FiChevronDown,
  FiAlertTriangle,
  FiCheck,
  FiLoader,
} from 'react-icons/fi';
import { dynamicAgentService } from '../services/api';

// Friendly labels for each pipeline step the agent emits.
const STEP_LABELS = {
  received: 'Request received',
  identifying_tool: 'Identifying tool',
  tool_identified: 'Tool identified',
  looking_up_docs: 'Loading docs',
  docs_loaded: 'Docs loaded',
  checking_connection: 'Checking connection',
  connection_found: 'Connection found',
  connection_missing: 'Connection missing',
  planning_action: 'Planning request',
  action_planned: 'Request planned',
  executing: 'Executing',
  executed: 'Executed',
  summarizing: 'Summarizing',
  done: 'Done',
  error: 'Error',
};

// Small contextual suffix for a step (the tool name, HTTP status, …).
function stepDetail(s) {
  const d = s.data || {};
  if (d.tool) return d.tool;
  if (d.http_status) return `HTTP ${d.http_status}`;
  if (d.status) return d.status;
  return '';
}

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

// An in-flight run rendered as a live table row. Sits at the top of the log
// table and updates step-by-step as SSE events arrive; expand it to see the
// full live trace. When the run finishes it's briefly retired and the polled
// completed row takes its place.
function LiveLogRow({ run }) {
  const [open, setOpen] = useState(true);
  const isError = run.status === 'error';
  const lastStep = run.steps[run.steps.length - 1];
  const currentLabel = lastStep
    ? STEP_LABELS[lastStep.step] || lastStep.step
    : 'Starting…';

  return (
    <>
      <tr
        className={`log-row log-row-live ${open ? 'log-row-open' : ''}`}
        onClick={() => setOpen((v) => !v)}
      >
        <td className="log-chevron">
          {open ? <FiChevronDown /> : <FiChevronRight />}
        </td>
        <td>
          <span className="live-now">
            <span className="log-live-dot log-live-dot-on" /> now
          </span>
        </td>
        <td>{run.tool || 'Resolving…'}</td>
        <td>
          {run.source === 'api' ? (
            <span className="log-badge" title="Developer key">
              {run.key_label || 'API'}
            </span>
          ) : (
            <span className="log-badge log-badge-muted">UI</span>
          )}
        </td>
        <td>
          {run.done ? (
            <span className={`log-badge ${STATUS_CLASS[run.status] || ''}`}>
              {isError && <FiAlertTriangle />}
              {run.status}
            </span>
          ) : (
            <span className="log-badge log-badge-running">
              <FiLoader className="live-spin" /> {currentLabel}
            </span>
          )}
        </td>
        <td className="log-prompt" title={run.prompt}>
          {run.prompt || '—'}
        </td>
        <td>
          {run.done ? '' : <FiLoader className="live-spin" />}
        </td>
      </tr>
      {open && (
        <tr className="log-detail-row">
          <td colSpan={7}>
            <ol className="live-steps">
              {run.steps.map((s, i) => {
                const last = i === run.steps.length - 1;
                const pending = last && !run.done;
                const detail = stepDetail(s);
                return (
                  <li
                    key={`${s.step}-${i}`}
                    className={pending ? 'live-step-active' : 'live-step-done'}
                  >
                    <span className="live-step-icon">
                      {pending ? <FiLoader className="live-spin" /> : <FiCheck />}
                    </span>
                    <span>
                      {STEP_LABELS[s.step] || s.step}
                      {detail && (
                        <span className="live-step-detail"> · {detail}</span>
                      )}
                    </span>
                  </li>
                );
              })}
            </ol>
          </td>
        </tr>
      )}
    </>
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

// Rows fetched per page (initial load, live-poll window, and each "Load more").
const PAGE_SIZE = 50;

// Combine row sets into one newest-first list, deduped by id. Lets a live poll
// merge the freshest page into already-loaded older pages without dropping them
// or showing a row twice.
function mergeRows(existing, incoming) {
  const byId = new Map(existing.map((r) => [r.id, r]));
  incoming.forEach((r) => byId.set(r.id, r));
  return Array.from(byId.values()).sort(
    (a, b) => new Date(b.created_at) - new Date(a.created_at)
  );
}

function LogsPage() {
  const [logs, setLogs] = useState([]);
  const [tools, setTools] = useState([]);
  const [tool, setTool] = useState('');
  const [source, setSource] = useState('');
  const [status, setStatus] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  // Whether the last page came back full — i.e. there may be older rows.
  const [hasMore, setHasMore] = useState(false);
  const [live, setLive] = useState(true);
  const [flashIds, setFlashIds] = useState(() => new Set());
  // In-flight runs keyed by run_uid, streamed step-by-step over SSE.
  const [liveRuns, setLiveRuns] = useState(() => new Map());
  // Prevents overlapping polls if a request is slow.
  const inFlight = useRef(false);
  // Run ids we've already shown, so a live poll can flag genuinely new ones.
  const seenIds = useRef(new Set());
  // Current loaded count, read when paging so "Load more" knows its offset
  // without making loadLogs depend on (and churn with) the logs array.
  const logsLenRef = useRef(0);
  // Latest loadLogs, so the (stable) step handler can refresh without
  // forcing the SSE connection to reconnect on every filter change.
  const loadLogsRef = useRef(null);

  useEffect(() => {
    logsLenRef.current = logs.length;
  }, [logs]);

  // Three modes:
  //   • initial / filter change — replace the list with the newest page.
  //   • silent (live poll, every 4 s) — fetch the newest page and merge it in,
  //     keeping any older pages already loaded; flag genuinely new rows and
  //     skip the spinner so the table doesn't flicker.
  //   • append ("Load more") — fetch the next older page and merge it in.
  const loadLogs = useCallback(
    async ({ silent = false, append = false } = {}) => {
      if (inFlight.current) return;
      inFlight.current = true;
      if (append) setLoadingMore(true);
      else if (!silent) setLoading(true);
      try {
        const offset = append ? logsLenRef.current : 0;
        const data = await dynamicAgentService.listLogs({
          limit: PAGE_SIZE,
          offset,
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
        if (silent) {
          setLogs((prev) => mergeRows(prev, rows));
        } else if (append) {
          setLogs((prev) => mergeRows(prev, rows));
          setHasMore(rows.length === PAGE_SIZE);
        } else {
          setLogs(rows);
          setHasMore(rows.length === PAGE_SIZE);
        }
      } catch (err) {
        if (!silent) toast.error('Failed to load logs');
        console.error(err);
      } finally {
        inFlight.current = false;
        if (append) setLoadingMore(false);
        else if (!silent) setLoading(false);
      }
    },
    [tool, source, status]
  );

  useEffect(() => {
    loadLogsRef.current = loadLogs;
  }, [loadLogs]);

  // Re-fetch whenever filters change (with spinner).
  useEffect(() => {
    loadLogs();
  }, [loadLogs]);

  // Apply one streamed step event to the live-runs map. Stable identity so the
  // SSE connection below isn't torn down on every render / filter change.
  const handleStep = useCallback((evt) => {
    if (!evt || !evt.run_uid) return;
    const { run_uid, step, data = {}, key_label, source: src } = evt;
    const finished = step === 'done' || step === 'error';
    setLiveRuns((prev) => {
      const next = new Map(prev);
      const cur =
        next.get(run_uid) || {
          run_uid,
          key_label,
          source: src,
          steps: [],
          tool: null,
          status: null,
          prompt: '',
          started_at: Date.now(),
          done: false,
        };
      const updated = {
        ...cur,
        steps: [...cur.steps, { step, data }],
        tool: data.tool || cur.tool,
        prompt: data.prompt || cur.prompt,
        done: finished || cur.done,
        status: step === 'error' ? 'error' : data.status || cur.status,
      };
      next.set(run_uid, updated);
      return next;
    });
    if (finished) {
      // Pull the completed row (with its full trace) into the table, then
      // retire the live card after a brief moment on screen.
      loadLogsRef.current?.({ silent: true });
      setTimeout(() => {
        setLiveRuns((prev) => {
          const next = new Map(prev);
          next.delete(run_uid);
          return next;
        });
      }, 6000);
    }
  }, []);

  // Live execution feed: subscribe to the per-user step channel over SSE while
  // live mode is on. Auto-reconnects if the stream drops. When Redis isn't
  // configured the stream just heartbeats and the polling tail covers updates.
  useEffect(() => {
    if (!live) {
      setLiveRuns(new Map());
      return undefined;
    }
    const controller = new AbortController();
    let cancelled = false;
    (async function connect() {
      while (!cancelled) {
        try {
          await dynamicAgentService.streamLogs({
            signal: controller.signal,
            onStep: handleStep,
          });
        } catch (err) {
          if (controller.signal.aborted) return;
          console.error('log stream error', err);
        }
        if (cancelled) return;
        await new Promise((r) => setTimeout(r, 2000)); // back off, then retry
      }
    })();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [live, handleStep]);

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
        ) : logs.length === 0 && liveRuns.size === 0 ? (
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
                {Array.from(liveRuns.values()).map((run) => (
                  <LiveLogRow key={run.run_uid} run={run} />
                ))}
                {logs.map((r) => (
                  <LogRow key={r.id} log={r} flash={flashIds.has(r.id)} />
                ))}
              </tbody>
            </table>
            {hasMore && (
              <div className="log-load-more">
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => loadLogs({ append: true })}
                  disabled={loadingMore}
                >
                  {loadingMore ? (
                    <>
                      <FiLoader className="live-spin" /> Loading…
                    </>
                  ) : (
                    'Load more'
                  )}
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default LogsPage;
