import React, { useCallback, useEffect, useMemo, useState } from 'react';
import toast from 'react-hot-toast';
import {
  FiRefreshCw,
  FiExternalLink,
  FiInfo,
  FiSearch,
  FiServer,
  FiClock,
  FiKey,
  FiCheckCircle,
  FiAlertCircle,
  FiLink,
  FiPlus,
  FiUpload,
} from 'react-icons/fi';
import Modal from '../components/Modal';
import { dynamicAgentService } from '../services/api';

// "5 minutes ago" / "yesterday" / "Mar 12, 2026" — keeps the card chrome
// compact while staying readable. Pure relative time gets confusing past a
// week so we fall back to an absolute date.
function formatRelative(iso) {
  if (!iso) return 'never';
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return 'unknown';
  const diffMs = Date.now() - then.getTime();
  const diffSec = Math.round(diffMs / 1000);
  if (diffSec < 60) return 'just now';
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin} min ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr} hr ago`;
  const diffDay = Math.round(diffHr / 24);
  if (diffDay === 1) return 'yesterday';
  if (diffDay < 7) return `${diffDay} days ago`;
  return then.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

const SOURCE_LABEL = {
  seed: 'Built-in',
  llm: 'Auto-fetched',
  scraped: 'Scraped',
};

// Map backend pipeline step → user-friendly progress label. Anything not in
// the map falls back to a humanized version of the step name itself, so new
// steps the backend adds will still render reasonably without a frontend
// change.
const REFRESH_STEP_LABEL = {
  starting: 'Starting…',
  cache_hit: 'Using cached docs',
  applying_seed: 'Applying built-in defaults…',
  introspecting: 'Introspecting local SDK…',
  introspected: 'SDK introspection done',
  searching_web: 'Searching the web…',
  web_results: 'Reviewing search results…',
  guessing_urls: 'Asking the LLM where this API’s docs live…',
  url_hints: 'Got URL hints from the LLM',
  openapi_parsed: 'Parsing OpenAPI spec…',
  enriching: 'Fetching documentation pages…',
  prompt_built: 'Preparing for the LLM…',
  llm_extracting: 'Extracting structured docs with the LLM…',
  llm_failed: 'LLM extraction failed',
  merging: 'Merging sources…',
  merged: 'Merge complete',
  saved: 'Saving…',
  error: 'Error',
};

function humanizeStep(step) {
  if (!step) return '';
  if (REFRESH_STEP_LABEL[step]) return REFRESH_STEP_LABEL[step];
  return step.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase()) + '…';
}

function statusMessage(evt) {
  const label = humanizeStep(evt?.step);
  if (evt?.step === 'web_results') {
    const engines = (evt.engines || []).join(', ') || 'no engine';
    return `${label} (${evt.count ?? 0} results via ${engines})`;
  }
  if (evt?.step === 'openapi_parsed') {
    return `${label} (${evt.endpoints ?? 0} endpoints)`;
  }
  if (evt?.step === 'url_hints') {
    return `LLM suggested ${evt.spec_urls ?? 0} spec URL(s)`;
  }
  if (evt?.step === 'introspected') {
    return `SDK introspection: ${evt.added ?? 0} new endpoints`;
  }
  if (evt?.step === 'merged') {
    return `Merge: +${evt.endpoints_added_from_web ?? 0} from web, ${evt.examples ?? 0} examples`;
  }
  if (evt?.step === 'saved') {
    return `Saved · ${evt.endpoint_count ?? 0} endpoints`;
  }
  return label;
}

function SourceBadge({ source }) {
  const cls =
    source === 'seed'
      ? 'tool-badge tool-badge-success'
      : 'tool-badge tool-badge-info';
  return <span className={cls}>{SOURCE_LABEL[source] || source || 'unknown'}</span>;
}

function AuthBadge({ authType }) {
  if (!authType) return null;
  return <span className="tool-badge tool-badge-neutral">{authType}</span>;
}

function ToolCard({ tool, onRefresh, onOpen, onConnect, refreshing, stage, connected }) {
  const initial = (tool.display_name || tool.name || '?').charAt(0).toUpperCase();
  return (
    <div className={`tool-card ${refreshing ? 'tool-card-busy' : ''}`}>
      <div className="tool-card-header">
        <div className="tool-card-avatar">{initial}</div>
        <div className="tool-card-titles">
          <div className="tool-card-name">{tool.display_name || tool.name}</div>
          <div className="tool-card-sub">{tool.base_url || '—'}</div>
        </div>
        {connected ? (
          <span className="tool-badge tool-badge-success tool-card-connected">
            <FiCheckCircle /> Connected
          </span>
        ) : null}
      </div>

      {refreshing && stage ? (
        <div className="tool-card-stage">
          <FiRefreshCw className="spin" /> {stage}
        </div>
      ) : null}

      <div className="tool-card-badges">
        <AuthBadge authType={tool.auth_type} />
        <SourceBadge source={tool.source} />
        <span className="tool-badge tool-badge-neutral">
          {tool.endpoint_count ?? 0} endpoints
        </span>
      </div>

      <div className="tool-card-meta">
        <span className="tool-card-meta-item">
          <FiClock /> Updated {formatRelative(tool.last_fetched_at)}
        </span>
        {tool.docs_url ? (
          <a
            href={tool.docs_url}
            target="_blank"
            rel="noreferrer"
            className="tool-card-meta-item tool-card-link"
          >
            <FiExternalLink /> Docs
          </a>
        ) : null}
      </div>

      <div className="tool-card-actions">
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={() => onOpen(tool.name)}
        >
          <FiInfo /> Details
        </button>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={() => onRefresh(tool.name)}
          disabled={refreshing}
        >
          <FiRefreshCw className={refreshing ? 'spin' : ''} />
          {refreshing ? 'Refreshing…' : 'Refresh'}
        </button>
        <button
          type="button"
          className="btn btn-primary btn-sm"
          onClick={() => onConnect(tool.name)}
        >
          <FiLink /> {connected ? 'Reconnect' : 'Connect'}
        </button>
      </div>
    </div>
  );
}

// Shared credential-entry form, used by both the card "Connect" button and
// the details modal. Mirrors the agent's needs_credentials flow but is
// triggered manually from the Cached Tools page.
function CredentialForm({ credModal, credValues, setCredValues, saving, onSubmit, onCancel }) {
  const fields = credModal.fields || [];
  return (
    <form onSubmit={onSubmit} className="tool-cred-form">
      <p className="tool-cred-intro">
        Enter your <strong>{credModal.display_name}</strong> credentials. They’re
        encrypted at rest and only ever sent to {credModal.display_name}.
      </p>
      <div className="tool-cred-meta">
        <span className="tool-badge tool-badge-neutral">{credModal.auth_type || 'API_KEY'}</span>
        {credModal.docs_url ? (
          <a href={credModal.docs_url} target="_blank" rel="noreferrer" className="tool-card-link">
            <FiExternalLink /> Where do I find these?
          </a>
        ) : null}
      </div>

      {fields.length === 0 ? (
        <div className="tool-detail-empty">
          This tool doesn’t expose any credential fields to enter here.
        </div>
      ) : (
        fields.map((f) => (
          <label key={f.name} className="tool-cred-field">
            <span className="tool-cred-field-label">
              {f.label || f.name}
              {f.required ? ' *' : ''}
            </span>
            <input
              type={f.type === 'password' || f.secret ? 'password' : 'text'}
              placeholder={f.placeholder || ''}
              value={credValues[f.name] || ''}
              onChange={(e) =>
                setCredValues((prev) => ({ ...prev, [f.name]: e.target.value }))
              }
              autoComplete="off"
            />
            {f.description ? (
              <span className="tool-cred-field-hint">{f.description}</span>
            ) : null}
          </label>
        ))
      )}

      <div className="tool-cred-actions">
        <button type="button" className="btn btn-secondary" onClick={onCancel} disabled={saving}>
          Cancel
        </button>
        <button type="submit" className="btn btn-primary" disabled={saving || fields.length === 0}>
          <FiLink className={saving ? 'spin' : ''} />
          {saving ? 'Connecting…' : 'Save & Connect'}
        </button>
      </div>
    </form>
  );
}

function EndpointRow({ name, ep }) {
  return (
    <div className="endpoint-row">
      <div className="endpoint-row-head">
        <span className={`http-method http-${(ep.method || 'GET').toLowerCase()}`}>
          {ep.method || 'GET'}
        </span>
        <span className="endpoint-name">{name}</span>
        <code className="endpoint-path">{ep.path || ''}</code>
      </div>
      {ep.description ? (
        <div className="endpoint-desc">{ep.description}</div>
      ) : null}
    </div>
  );
}

function ToolDetails({ detail }) {
  if (!detail) {
    return <div className="tool-detail-empty">Loading tool details…</div>;
  }

  const endpoints = detail.endpoints || {};
  const endpointKeys = Object.keys(endpoints);
  const examples = Array.isArray(detail.examples) ? detail.examples : [];
  const rateLimits = detail.rate_limits;

  return (
    <div className="tool-detail">
      <section className="tool-detail-section">
        <h4>Overview</h4>
        <div className="tool-detail-grid">
          <div>
            <div className="tool-detail-key">Base URL</div>
            <div className="tool-detail-val">
              <code>{detail.base_url || '—'}</code>
            </div>
          </div>
          <div>
            <div className="tool-detail-key">Auth</div>
            <div className="tool-detail-val">{detail.auth_type || '—'}</div>
          </div>
          <div>
            <div className="tool-detail-key">Source</div>
            <div className="tool-detail-val">
              <SourceBadge source={detail.source} />
            </div>
          </div>
          <div>
            <div className="tool-detail-key">Last refreshed</div>
            <div className="tool-detail-val">
              {formatRelative(detail.last_fetched_at)}
            </div>
          </div>
        </div>
      </section>

      <section className="tool-detail-section">
        <h4>
          Endpoints{' '}
          <span className="tool-detail-count">{endpointKeys.length}</span>
        </h4>
        {endpointKeys.length === 0 ? (
          <div className="tool-detail-empty">No endpoints cached.</div>
        ) : (
          <div className="endpoint-list">
            {endpointKeys.slice(0, 30).map((k) => (
              <EndpointRow key={k} name={k} ep={endpoints[k] || {}} />
            ))}
            {endpointKeys.length > 30 ? (
              <div className="tool-detail-empty">
                + {endpointKeys.length - 30} more
              </div>
            ) : null}
          </div>
        )}
      </section>

      <section className="tool-detail-section">
        <h4>Rate limits</h4>
        {rateLimits && typeof rateLimits === 'object' ? (
          <ul className="tool-detail-list">
            {rateLimits.requests_per_minute ? (
              <li>
                <strong>{rateLimits.requests_per_minute}</strong> requests / minute
              </li>
            ) : null}
            {rateLimits.requests_per_hour ? (
              <li>
                <strong>{rateLimits.requests_per_hour}</strong> requests / hour
              </li>
            ) : null}
            {rateLimits.requests_per_day ? (
              <li>
                <strong>{rateLimits.requests_per_day}</strong> requests / day
              </li>
            ) : null}
            {rateLimits.notes ? <li>{rateLimits.notes}</li> : null}
          </ul>
        ) : (
          <div className="tool-detail-empty">
            Not documented in the cached docs.
          </div>
        )}
      </section>

      <section className="tool-detail-section">
        <h4>
          Examples{' '}
          {examples.length ? (
            <span className="tool-detail-count">{examples.length}</span>
          ) : null}
        </h4>
        {examples.length === 0 ? (
          <div className="tool-detail-empty">
            No code samples were captured from the docs.
          </div>
        ) : (
          examples.slice(0, 4).map((ex, idx) => (
            <div className="tool-detail-example" key={idx}>
              <div className="tool-detail-example-head">
                <span className="tool-badge tool-badge-neutral">
                  {ex.language || 'code'}
                </span>
                {ex.title ? <span>{ex.title}</span> : null}
              </div>
              <pre className="tool-detail-code">
                <code>{ex.code || ''}</code>
              </pre>
            </div>
          ))
        )}
      </section>
    </div>
  );
}

function ToolsPage() {
  const [tools, setTools] = useState([]);
  const [connections, setConnections] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState({}); // {toolName: bool}
  const [query, setQuery] = useState('');
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);

  // Connect / credentials modal
  const [credModal, setCredModal] = useState(null); // {tool, display_name, auth_type, fields, docs_url}
  const [credValues, setCredValues] = useState({});
  const [savingCreds, setSavingCreds] = useState(false);

  // Import-from-source modal (OpenAPI spec URL or uploaded file)
  const [importOpen, setImportOpen] = useState(false);
  const [importName, setImportName] = useState('');
  const [importUrl, setImportUrl] = useState('');
  const [importFile, setImportFile] = useState(null);
  const [importing, setImporting] = useState(false);

  const loadTools = useCallback(async () => {
    setLoading(true);
    try {
      const [data, conns] = await Promise.all([
        dynamicAgentService.listTools(),
        dynamicAgentService.listConnections().catch(() => []),
      ]);
      setTools(Array.isArray(data) ? data : []);
      setConnections(Array.isArray(conns) ? conns : []);
    } catch (err) {
      toast.error(
        err?.response?.data?.detail ||
          err?.message ||
          'Failed to load cached tools'
      );
    } finally {
      setLoading(false);
    }
  }, []);

  const connectedSet = useMemo(
    () => new Set(connections.map((c) => c.tool)),
    [connections]
  );

  const handleConnect = useCallback(async (name) => {
    try {
      const t = await dynamicAgentService.getTool(name);
      const fields = t.credential_fields || [];
      const defaults = {};
      fields.forEach((f) => {
        defaults[f.name] = '';
      });
      setCredValues(defaults);
      setCredModal({
        tool: t.name,
        display_name: t.display_name || t.name,
        auth_type: t.auth_type,
        fields,
        docs_url: t.docs_url,
      });
    } catch (err) {
      toast.error(
        err?.response?.data?.detail || err?.message || 'Failed to load tool'
      );
    }
  }, []);

  const handleSubmitCreds = useCallback(
    async (e) => {
      e?.preventDefault?.();
      if (!credModal) return;
      const missing = (credModal.fields || [])
        .filter((f) => f.required && !credValues[f.name]?.trim())
        .map((f) => f.label || f.name);
      if (missing.length) {
        toast.error('Required: ' + missing.join(', '));
        return;
      }
      try {
        setSavingCreds(true);
        const sent = Object.fromEntries(
          Object.entries(credValues).filter(([, v]) => v && v.trim())
        );
        const res = await dynamicAgentService.submitCredentials(
          credModal.tool,
          sent
        );
        if (res?.test_status === 'failed') {
          toast.error('Smoke test failed: ' + (res.test_detail || ''));
        } else {
          toast.success(`Connected to ${res?.display_name || credModal.display_name} ✓`);
        }
        setCredModal(null);
        setCredValues({});
        await loadTools();
      } catch (err) {
        toast.error(
          err?.response?.data?.detail || err?.message || 'Failed to save credentials'
        );
      } finally {
        setSavingCreds(false);
      }
    },
    [credModal, credValues, loadTools]
  );

  const resetImport = useCallback(() => {
    setImportOpen(false);
    setImportName('');
    setImportUrl('');
    setImportFile(null);
  }, []);

  const handleImport = useCallback(
    async (e) => {
      e?.preventDefault?.();
      const name = importName.trim().toLowerCase();
      if (!name) {
        toast.error('Tool name is required');
        return;
      }
      if (!importUrl.trim() && !importFile) {
        toast.error('Provide a spec/doc URL or upload a file');
        return;
      }
      setImporting(true);
      const t = toast.loading(`Importing ${name}…`);
      try {
        const res = await dynamicAgentService.importTool({
          tool: name,
          specUrl: importUrl.trim(),
          file: importFile,
        });
        toast.success(
          `Imported ${res.name} · ${res.endpoint_count} endpoints (${res.source})`,
          { id: t }
        );
        resetImport();
        await loadTools();
      } catch (err) {
        toast.error(
          err?.response?.data?.detail || err?.message || 'Import failed',
          { id: t }
        );
      } finally {
        setImporting(false);
      }
    },
    [importName, importUrl, importFile, loadTools, resetImport]
  );

  useEffect(() => {
    loadTools();
  }, [loadTools]);

  // Per-tool current stage label, e.g. {github: "Extracting with LLM…"}.
  // Drives the inline status under the card title while a refresh is mid-flight.
  const [refreshStage, setRefreshStage] = useState({});

  const handleRefresh = useCallback(
    async (name) => {
      setRefreshing((s) => ({ ...s, [name]: true }));
      setRefreshStage((s) => ({ ...s, [name]: 'Starting…' }));
      const t = toast.loading(`Refreshing ${name}…`);
      try {
        await dynamicAgentService.streamRefreshTool({
          tool: name,
          onStatus: (evt) => {
            const msg = statusMessage(evt);
            setRefreshStage((s) => ({ ...s, [name]: msg }));
            toast.loading(`${name}: ${msg}`, { id: t });
          },
          onDone: (res) => {
            toast.success(
              `Refreshed ${name} · ${res?.endpoint_count ?? 0} endpoints`,
              { id: t }
            );
          },
          onError: (err) => {
            toast.error(err.message || `Failed to refresh ${name}`, { id: t });
          },
        });
        await loadTools();
        // If the details modal was open for this tool, re-pull it too.
        if (detailOpen && detail?.name === name) {
          try {
            const fresh = await dynamicAgentService.getTool(name);
            setDetail(fresh);
          } catch {
            /* non-fatal */
          }
        }
      } catch (err) {
        // onError already toasted; just log for the console.
        // eslint-disable-next-line no-console
        console.warn(`refresh ${name} failed:`, err);
      } finally {
        setRefreshing((s) => {
          const next = { ...s };
          delete next[name];
          return next;
        });
        setRefreshStage((s) => {
          const next = { ...s };
          delete next[name];
          return next;
        });
      }
    },
    [detail, detailOpen, loadTools]
  );

  const handleOpen = useCallback(async (name) => {
    setDetailOpen(true);
    setDetail(null);
    setDetailLoading(true);
    try {
      const data = await dynamicAgentService.getTool(name);
      setDetail(data);
    } catch (err) {
      toast.error(
        err?.response?.data?.detail || err?.message || 'Failed to load tool'
      );
      setDetailOpen(false);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return tools;
    return tools.filter((t) =>
      [t.name, t.display_name, t.base_url, t.auth_type]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(q))
    );
  }, [tools, query]);

  const stats = useMemo(() => {
    const seeds = tools.filter((t) => t.source === 'seed').length;
    const fetched = tools.length - seeds;
    return { total: tools.length, seeds, fetched };
  }, [tools]);

  return (
    <div className="page-container tools-page">
      <header className="page-header">
        <div>
          <h1>Cached Tools</h1>
          <p className="page-subtitle">
            Every API the Dynamic Agent has docs for — seeded or auto-fetched
            from the web. Refresh any tool to re-pull the latest endpoints,
            auth, rate limits, and examples.
          </p>
        </div>
        <div className="tools-header-actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => setImportOpen(true)}
          >
            <FiPlus /> Import tool
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={loadTools}
            disabled={loading}
          >
            <FiRefreshCw className={loading ? 'spin' : ''} /> Reload
          </button>
        </div>
      </header>

      <div className="tools-toolbar">
        <div className="tools-search">
          <FiSearch />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by name, URL, or auth type…"
          />
        </div>
        <div className="tools-stats">
          <span className="tool-stat">
            <FiServer /> {stats.total} total
          </span>
          <span className="tool-stat">
            <FiCheckCircle /> {stats.seeds} built-in
          </span>
          <span className="tool-stat">
            <FiKey /> {stats.fetched} auto-fetched
          </span>
        </div>
      </div>

      {loading ? (
        <div className="tools-empty">
          <div className="spinner" />
          <p>Loading cached tools…</p>
        </div>
      ) : tools.length === 0 ? (
        <div className="tools-empty">
          <FiAlertCircle />
          <p>No tools cached yet. Ask the Dynamic Agent to use one to seed it.</p>
        </div>
      ) : filtered.length === 0 ? (
        <div className="tools-empty">
          <FiSearch />
          <p>No tools match "{query}".</p>
        </div>
      ) : (
        <div className="tool-grid">
          {filtered.map((t) => (
            <ToolCard
              key={t.name}
              tool={t}
              onRefresh={handleRefresh}
              onOpen={handleOpen}
              onConnect={handleConnect}
              refreshing={!!refreshing[t.name]}
              stage={refreshStage[t.name]}
              connected={connectedSet.has(t.name)}
            />
          ))}
        </div>
      )}

      <Modal
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        title={detail ? `${detail.display_name || detail.name}` : 'Tool details'}
        size="lg"
      >
        {detailLoading ? (
          <div className="tool-detail-empty">
            <div className="spinner" />
            <p>Loading…</p>
          </div>
        ) : (
          <ToolDetails detail={detail} />
        )}
        {detail ? (
          <div className="tool-detail-footer">
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => handleConnect(detail.name)}
            >
              <FiLink /> {connectedSet.has(detail.name) ? 'Reconnect' : 'Connect'}
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => handleRefresh(detail.name)}
              disabled={!!refreshing[detail.name]}
            >
              <FiRefreshCw className={refreshing[detail.name] ? 'spin' : ''} />
              {refreshing[detail.name] ? 'Refreshing…' : 'Refresh docs'}
            </button>
            {detail.docs_url ? (
              <a
                href={detail.docs_url}
                target="_blank"
                rel="noreferrer"
                className="btn btn-secondary"
              >
                <FiExternalLink /> Open docs
              </a>
            ) : null}
          </div>
        ) : null}
      </Modal>

      <Modal
        open={importOpen}
        onClose={() => {
          if (!importing) resetImport();
        }}
        title="Import a tool from its docs"
      >
        <form onSubmit={handleImport} className="tool-cred-form">
          <p className="tool-cred-intro">
            The most accurate way to add a tool: give Adaptora its{' '}
            <strong>OpenAPI/Swagger spec</strong> (JSON/YAML) and every endpoint
            is parsed exactly — no web guessing. You can also paste a docs URL or
            upload any doc file (the LLM extracts endpoints from it).
          </p>

          <label className="tool-cred-field">
            <span className="tool-cred-field-label">Tool name *</span>
            <input
              type="text"
              placeholder="e.g. linkedin, stripe, myapi"
              value={importName}
              onChange={(e) => setImportName(e.target.value)}
              autoComplete="off"
            />
          </label>

          <label className="tool-cred-field">
            <span className="tool-cred-field-label">Spec / docs URL</span>
            <input
              type="url"
              placeholder="https://api.example.com/openapi.json"
              value={importUrl}
              onChange={(e) => setImportUrl(e.target.value)}
              disabled={!!importFile}
              autoComplete="off"
            />
            <span className="tool-cred-field-hint">
              An OpenAPI/Swagger spec URL gives the best result.
            </span>
          </label>

          <label className="tool-cred-field">
            <span className="tool-cred-field-label">
              <FiUpload /> …or upload a file
            </span>
            <input
              type="file"
              accept=".json,.yaml,.yml,.md,.txt,.html,.htm"
              onChange={(e) => setImportFile(e.target.files?.[0] || null)}
              disabled={!!importUrl.trim()}
            />
            <span className="tool-cred-field-hint">
              OpenAPI JSON/YAML (most accurate), or a Markdown/HTML/text doc.
            </span>
          </label>

          <div className="tool-cred-actions">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={resetImport}
              disabled={importing}
            >
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={importing}>
              <FiPlus className={importing ? 'spin' : ''} />
              {importing ? 'Importing…' : 'Import'}
            </button>
          </div>
        </form>
      </Modal>

      <Modal
        open={!!credModal}
        onClose={() => {
          if (!savingCreds) {
            setCredModal(null);
            setCredValues({});
          }
        }}
        title={credModal ? `Connect to ${credModal.display_name}` : 'Connect'}
      >
        {credModal ? (
          <CredentialForm
            credModal={credModal}
            credValues={credValues}
            setCredValues={setCredValues}
            saving={savingCreds}
            onSubmit={handleSubmitCreds}
            onCancel={() => {
              setCredModal(null);
              setCredValues({});
            }}
          />
        ) : null}
      </Modal>
    </div>
  );
}

export default ToolsPage;
