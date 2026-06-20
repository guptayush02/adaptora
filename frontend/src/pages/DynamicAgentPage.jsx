import React, { useEffect, useMemo, useRef, useState } from 'react';
import toast from 'react-hot-toast';
import {
  FiCpu,
  FiSend,
  FiKey,
  FiLink2,
  FiTrash2,
  FiCheckCircle,
  FiAlertCircle,
  FiBookOpen,
  FiGlobe,
  FiSliders,
  FiX,
} from 'react-icons/fi';
import { dynamicAgentService } from '../services/api';
import { useAuth } from '../hooks/useAuth';

const LANGUAGES = [
  { value: 'en', label: 'English' },
  { value: 'hinglish', label: 'Hinglish' },
];

// Bare URL → clickable link inside step lists and bubble bodies.
const URL_REGEX = /(https?:\/\/[^\s)]+)/g;
function renderTextWithLinks(text) {
  if (!text) return null;
  const parts = String(text).split(URL_REGEX);
  return parts.map((part, i) => {
    if (URL_REGEX.test(part)) {
      URL_REGEX.lastIndex = 0;
      return (
        <a key={i} href={part} target="_blank" rel="noreferrer noopener">
          {part}
        </a>
      );
    }
    URL_REGEX.lastIndex = 0;
    return <React.Fragment key={i}>{part}</React.Fragment>;
  });
}

function formatJson(value) {
  if (value == null) return '';
  if (typeof value === 'string') {
    try {
      return JSON.stringify(JSON.parse(value), null, 2);
    } catch {
      return value;
    }
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

// Pull a "click here" URL out of a response body (Razorpay short_url,
// Stripe url, GitHub html_url, etc.) so the chat bubble can surface it
// as a button instead of forcing the user to read JSON.
const URL_FIELDS = ['short_url', 'url', 'html_url', 'web_url', 'link', 'permalink', 'public_url'];
function extractCanonicalUrl(response) {
  if (!response) return null;
  let data = response;
  if (typeof data === 'string') {
    try {
      data = JSON.parse(data);
    } catch {
      return null;
    }
  }
  if (typeof data !== 'object' || Array.isArray(data)) return null;
  for (const key of URL_FIELDS) {
    const v = data[key];
    if (typeof v === 'string' && /^https?:\/\//i.test(v)) return v;
  }
  return null;
}

// Map the backend's pipeline step names to user-facing labels.
// Hinglish + English variants so the language toggle works for status too.
// Whatever the step is, we just show its label — no need for icons.
const STEP_LABELS = {
  en: {
    starting: 'Starting…',
    identifying_tool: 'Identifying the tool…',
    tool_identified: (d) =>
      d?.tool ? `Tool: ${d.tool}` : 'Tool identified',
    looking_up_docs: (d) =>
      d?.tool ? `Loading ${d.tool} docs…` : 'Loading docs…',
    docs_loaded: (d) =>
      d?.tool ? `Docs ready (${d.endpoint_count || 0} endpoints)` : 'Docs ready',
    checking_connection: 'Checking your connection…',
    connection_found: (d) =>
      d?.tool ? `Connected to ${d.tool}` : 'Connection found',
    connection_missing: 'Need credentials — opening form…',
    refreshing_oauth_token: 'Refreshing OAuth token…',
    planning_action: 'Planning the API call…',
    action_planned: (d) =>
      d?.method && d?.endpoint ? `Plan: ${d.method} ${d.endpoint}` : 'Plan ready',
    executing: (d) =>
      d?.method && d?.endpoint
        ? `Calling ${d.method} ${d.endpoint}…`
        : 'Running…',
    executed: (d) =>
      d?.http_status != null ? `HTTP ${d.http_status} — preparing reply…` : 'Got response',
    summarizing: 'Writing the answer…',
  },
  hinglish: {
    starting: 'Shuru kar raha hoon…',
    identifying_tool: 'Tool identify kar raha hoon…',
    tool_identified: (d) =>
      d?.tool ? `Tool mil gaya: ${d.tool}` : 'Tool identify ho gaya',
    looking_up_docs: (d) =>
      d?.tool ? `${d.tool} ke docs load kar raha hoon…` : 'Docs load kar raha hoon…',
    docs_loaded: (d) =>
      d?.tool ? `Docs ready (${d.endpoint_count || 0} endpoints)` : 'Docs ready',
    checking_connection: 'Connection check kar raha hoon…',
    connection_found: (d) =>
      d?.tool ? `${d.tool} se connected` : 'Connection mil gaya',
    connection_missing: 'Credentials chahiye — form khol raha hoon…',
    refreshing_oauth_token: 'OAuth token refresh kar raha hoon…',
    planning_action: 'API call plan kar raha hoon…',
    action_planned: (d) =>
      d?.method && d?.endpoint ? `Plan: ${d.method} ${d.endpoint}` : 'Plan tayar',
    executing: (d) =>
      d?.method && d?.endpoint
        ? `Call kar raha hoon: ${d.method} ${d.endpoint}…`
        : 'Run ho raha hai…',
    executed: (d) =>
      d?.http_status != null ? `HTTP ${d.http_status} — reply ban raha hai…` : 'Response mil gaya',
    summarizing: 'Jawab likh raha hoon…',
  },
};

function resolveStepLabel(step, data, language) {
  const map = STEP_LABELS[language] || STEP_LABELS.en;
  const entry = map[step];
  if (typeof entry === 'function') return entry(data || {});
  if (typeof entry === 'string') return entry;
  // Unknown step → humanize the snake_case identifier
  if (step) return step.replace(/_/g, ' ');
  return language === 'hinglish' ? 'Soch raha hoon…' : 'Thinking…';
}

function StatusChip({ status }) {
  if (!status) return null;
  const map = {
    success: { cls: 'hit', icon: FiCheckCircle, label: 'ok' },
    error: { cls: 'complexity-difficult', icon: FiAlertCircle, label: 'failed' },
    needs_credentials: { cls: 'complexity-medium', icon: FiKey, label: 'creds needed' },
    needs_tool_setup: { cls: 'complexity-medium', icon: FiAlertCircle, label: 'no docs' },
  };
  const m = map[status] || { cls: '', icon: FiAlertCircle, label: status };
  const Icon = m.icon;
  return (
    <span className={`chat-meta-chip ${m.cls}`}>
      <Icon /> {m.label}
    </span>
  );
}

function DynamicAgentPage() {
  // ----------------------------------------------------------------- state
  const { user } = useAuth();
  // Chat history and connections are per-user. Scope all persisted state by
  // the logged-in user's id so that switching accounts on the same browser
  // never shows one user another user's chat. `user` loads asynchronously
  // (token verification), so fall back to 'anon' until it resolves.
  const userScope = user?.id != null ? String(user.id) : 'anon';
  const messagesKey = `dynamicAgentMessages:${userScope}`;

  const [language, setLanguage] = useState(
    () => localStorage.getItem('dynamicAgentLanguage') || 'en'
  );
  // messages: [{ role: 'user'|'agent', id, prompt? , turn?, ts }]
  // Loaded from per-user storage by the effect below (not in the initializer,
  // because `user` isn't known yet on the first render).
  const [messages, setMessages] = useState([]);
  // Tracks which user the currently-held `messages` were persisted for, so the
  // persist effect never writes one user's chat under another user's key.
  const persistScope = useRef(null);
  const [prompt, setPrompt] = useState('');
  const [running, setRunning] = useState(false);
  // The most recent `status` event emitted by the SSE pipeline. We use it
  // to swap the typing dots out for a concrete step label
  // ("Identifying tool…", "Calling POST /v1/payment_links…", etc.).
  const [currentStep, setCurrentStep] = useState(null);

  // Sidebar drawer state (Connected tools + Known tools)
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [connections, setConnections] = useState([]);
  const [tools, setTools] = useState([]);
  const [inspectedTool, setInspectedTool] = useState(null);

  // Credential modal
  const [credPrompt, setCredPrompt] = useState(null);
  const [credValues, setCredValues] = useState({});
  const [savingCreds, setSavingCreds] = useState(false);

  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    localStorage.setItem('dynamicAgentLanguage', language);
  }, [language]);

  // One-time cleanup: remove the legacy un-scoped key that was shared across
  // every account on this browser (the source of the cross-user chat leak).
  useEffect(() => {
    localStorage.removeItem('dynamicAgentMessages');
  }, []);

  // Load this user's chat whenever the logged-in account changes. Declared
  // BEFORE the persist effect so, on a user switch, this runs first and the
  // persist effect below sees the scope change and skips that commit.
  useEffect(() => {
    try {
      const cached = localStorage.getItem(messagesKey);
      setMessages(cached ? JSON.parse(cached) : []);
    } catch {
      setMessages([]);
    }
  }, [messagesKey]);

  useEffect(() => {
    // On a scope change the load effect above is repopulating `messages` for
    // the new user; skip this run so we don't persist the previous user's chat
    // under the new user's key.
    if (persistScope.current !== userScope) {
      persistScope.current = userScope;
      return;
    }
    // Cap stored history at the last 60 turns (~120 messages) so localStorage
    // doesn't blow up after a long session.
    try {
      const trimmed = messages.slice(-120);
      localStorage.setItem(messagesKey, JSON.stringify(trimmed));
    } catch {
      // localStorage quota / serialization issues are not fatal — silently
      // skip persistence rather than breaking the page.
    }
  }, [messages, messagesKey, userScope]);

  useEffect(() => {
    // Auto-scroll to the newest message
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, running]);

  // ---------------------------------------------------------- bootstrap
  const refreshSidebar = async () => {
    try {
      const [conns, ts] = await Promise.all([
        dynamicAgentService.listConnections(),
        dynamicAgentService.listTools(),
      ]);
      setConnections(conns || []);
      setTools(ts || []);
    } catch (err) {
      console.error('refreshSidebar', err);
    }
  };

  // Reload connected tools/known tools when the account changes — connections
  // and their secrets are per-user, so a switch must not keep the prior user's.
  useEffect(() => {
    setConnections([]);
    setTools([]);
    refreshSidebar();
  }, [userScope]);

  // Handle OAuth2 callback redirect (?oauth_success=1&tool=spotify or ?oauth_error=...)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const oauthSuccess = params.get('oauth_success');
    const oauthError = params.get('oauth_error');
    const tool = params.get('tool');
    if (oauthSuccess) {
      // Clean URL without reload
      window.history.replaceState({}, '', window.location.pathname);
      refreshSidebar().then(() => setDrawerOpen(true));
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: tool
            ? `✓ ${tool.charAt(0).toUpperCase() + tool.slice(1)} successfully authorized! You can now use it.`
            : '✓ Tool successfully authorized!',
          ts: Date.now(),
        },
      ]);
    } else if (oauthError) {
      window.history.replaceState({}, '', window.location.pathname);
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: `OAuth authorization failed: ${decodeURIComponent(oauthError)}. Please try again.`,
          ts: Date.now(),
        },
      ]);
    }
  }, []);

  // ---------------------------------------------------------- turn
  const runTurn = async (text) => {
    const p = (text ?? prompt).trim();
    if (!p) return;
    setPrompt('');
    const ts = Date.now();
    setMessages((prev) => [...prev, { role: 'user', id: `u-${ts}`, prompt: p, ts }]);
    setRunning(true);
    setCurrentStep({ step: 'starting', data: {} });
    try {
      // Streaming endpoint: keeps proxies (ALB / nginx / CloudFront) happy
      // on slow Ollama calls AND drives the per-step label in the UI.
      const result = await dynamicAgentService.streamTurn({
        prompt: p,
        language,
        onStatus: (evt) => {
          // The backend sends {step, ...data}. Stash both so the bubble
          // and the typing indicator can pull the right label.
          if (evt?.step) {
            setCurrentStep({ step: evt.step, data: evt });
          }
        },
      });
      setMessages((prev) => [
        ...prev,
        { role: 'agent', id: `a-${result.log_id || Date.now()}`, turn: result, ts: Date.now() },
      ]);

      if (result.status === 'needs_credentials') {
        const fields = result.action_input?.credential_fields || [];
        const defaults = {};
        fields.forEach((f) => {
          defaults[f.name] = '';
        });
        setCredValues(defaults);
        setCredPrompt({
          tool: result.tool,
          display_name: result.action_input?.display_name || result.tool,
          auth_type: result.action_input?.auth_type,
          fields,
          docs_url: result.action_input?.docs_url,
          pat_create_url: result.action_input?.pat_create_url,
          setup: result.action_input?.setup_instructions || null,
          original_prompt: p,
        });
      } else if (result.status === 'success') {
        // Quietly succeed — the bubble itself is the toast.
      } else if (result.status === 'error') {
        toast.error(result.summary || result.error || 'Agent error', {
          duration: 4000,
        });
      } else if (result.status === 'needs_tool_setup') {
        toast(
          language === 'hinglish'
            ? `${result.tool} ke docs nahi mile`
            : `Couldn't load docs for ${result.tool}`,
          { icon: '📚' }
        );
      }

      refreshSidebar();
    } catch (err) {
      console.error(err);
      const detail = err?.response?.data?.detail || err?.message || 'Agent turn failed';
      toast.error(detail);
      setMessages((prev) => [
        ...prev,
        {
          role: 'agent',
          id: `a-${Date.now()}`,
          ts: Date.now(),
          turn: {
            status: 'error',
            summary: detail,
            error: detail,
          },
        },
      ]);
    } finally {
      setRunning(false);
      setCurrentStep(null);
      inputRef.current?.focus();
    }
  };

  const handleSubmit = (e) => {
    e?.preventDefault?.();
    if (!running) runTurn();
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const clearChat = () => {
    if (!messages.length) return;
    const ok = window.confirm(
      language === 'hinglish' ? 'Saari chat clear karni hai?' : 'Clear the entire chat?'
    );
    if (!ok) return;
    setMessages([]);
  };

  // ---------------------------------------------------------- credentials
  const handleSubmitCreds = async (e) => {
    e?.preventDefault?.();
    if (!credPrompt) return;
    const missing = credPrompt.fields
      .filter((f) => f.required && !credValues[f.name]?.trim())
      .map((f) => f.label);
    if (missing.length) {
      toast.error('Required: ' + missing.join(', '));
      return;
    }
    try {
      setSavingCreds(true);
      const sent = Object.fromEntries(
        Object.entries(credValues).filter(([, v]) => v && v.trim())
      );
      const res = await dynamicAgentService.submitCredentials(credPrompt.tool, sent);
      if (res.test_status === 'failed') {
        toast.error(
          (language === 'hinglish' ? 'Test fail: ' : 'Smoke test failed: ') +
            (res.test_detail || '')
        );
      } else {
        toast.success(
          language === 'hinglish'
            ? `${res.display_name} connected ✓`
            : `Connected to ${res.display_name} ✓`
        );
      }
      const original = credPrompt.original_prompt;
      setCredPrompt(null);
      setCredValues({});
      await refreshSidebar();
      if (original) {
        // Auto-replay the original prompt so the user picks up where they left off
        setTimeout(() => runTurn(original), 50);
      }
    } catch (err) {
      console.error(err);
      toast.error(err?.response?.data?.detail || 'Failed to save credentials');
    } finally {
      setSavingCreds(false);
    }
  };

  // ---------------------------------------------------------- sidebar actions
  const handleDeleteConnection = async (id) => {
    const sure = window.confirm(
      language === 'hinglish' ? 'Disconnect karna hai?' : 'Disconnect this tool?'
    );
    if (!sure) return;
    try {
      await dynamicAgentService.deleteConnection(id);
      toast.success(language === 'hinglish' ? 'Disconnect ho gaya' : 'Disconnected');
      refreshSidebar();
    } catch (err) {
      console.error(err);
      toast.error('Failed to disconnect');
    }
  };

  const handleInspectTool = async (name) => {
    try {
      const data = await dynamicAgentService.getTool(name);
      setInspectedTool(data);
    } catch (err) {
      console.error(err);
      toast.error('Failed to load tool docs');
    }
  };

  // ---------------------------------------------------------- empty state
  const sampleSuggestions = useMemo(() => {
    if (language === 'hinglish') {
      return [
        'GitHub se connect karna hai',
        'Mere last 5 GitHub repos dikhao',
        'Razorpay pe 500 INR ka payment link banao',
        'Slack pe #general me hello bhejo',
      ];
    }
    return [
      'Connect with GitHub',
      'List my last 5 GitHub repos',
      'Create a Razorpay payment link for 500 INR',
      'Post "hello" to Slack #general',
    ];
  }, [language]);

  // ---------------------------------------------------------- render
  return (
    <div className="agent-shell">
      {/* ====================== main chat column ====================== */}
      <div className="chat-main agent-chat-main">
        <div className="chat-main-header">
          <button
            type="button"
            className="chat-open-sidebar"
            onClick={() => setDrawerOpen(true)}
            aria-label="Open tools panel"
          >
            <FiSliders />
          </button>
          <div className="chat-avatar">
            <FiCpu />
          </div>
          <div className="chat-main-title">
            <h2>Dynamic Agent</h2>
            <div className="chat-main-sub">
              {language === 'hinglish'
                ? 'Bata kya karna hai — agent tool identify karke action chala dega.'
                : 'Just say what you want — the agent finds the tool and runs the action.'}
            </div>
          </div>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 6, alignItems: 'center' }}>
            {LANGUAGES.map((lng) => (
              <button
                key={lng.value}
                type="button"
                className={`btn btn-sm ${
                  language === lng.value ? 'btn-primary' : 'btn-ghost'
                }`}
                onClick={() => setLanguage(lng.value)}
              >
                {lng.label}
              </button>
            ))}
            {messages.length > 0 && (
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={clearChat}
                title={language === 'hinglish' ? 'Chat clear karo' : 'Clear chat'}
                aria-label="Clear chat"
              >
                <FiTrash2 />
              </button>
            )}
          </div>
        </div>

        {/* messages */}
        <div className="chat-messages">
          {messages.length === 0 ? (
            <div className="chat-empty-state">
              <FiCpu className="empty-icon" />
              <h3>
                {language === 'hinglish' ? 'Kuch bhi pucho' : 'Ask me anything'}
              </h3>
              <p>
                {language === 'hinglish'
                  ? 'Local LLM tool identify karega, docs fetch karega, aur action execute karega.'
                  : 'I pick the tool, fetch its docs, and run the action — no setup required.'}
              </p>
              <div className="chat-suggestions">
                {sampleSuggestions.map((s) => (
                  <button
                    key={s}
                    type="button"
                    className="chat-suggestion"
                    onClick={() => runTurn(s)}
                    disabled={running}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((m) =>
              m.role === 'user' ? (
                <UserBubble key={m.id} prompt={m.prompt} />
              ) : (
                <AgentBubble key={m.id} turn={m.turn} />
              )
            )
          )}
          {running && (
            <div className="chat-message chat-msg-assistant">
              <div className="chat-avatar">
                <FiCpu />
              </div>
              <div className="chat-bubble">
                <div className="chat-status-label">
                  {resolveStepLabel(
                    currentStep?.step,
                    currentStep?.data,
                    language
                  )}
                </div>
                <div className="chat-typing">
                  <span />
                  <span />
                  <span />
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* composer */}
        <form className="chat-composer" onSubmit={handleSubmit}>
          <div className="chat-input-row">
            <textarea
              ref={inputRef}
              placeholder={
                language === 'hinglish'
                  ? 'Type karo… (Enter bhejne ke liye, Shift+Enter new line)'
                  : 'Type a message… (Enter to send, Shift+Enter for newline)'
              }
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={1}
              disabled={running}
            />
            <button
              type="submit"
              className="btn btn-primary chat-send-btn"
              disabled={running || !prompt.trim()}
              aria-label="Send"
            >
              <FiSend />
            </button>
          </div>
        </form>
      </div>

      {/* ====================== sidebar drawer (mobile + opt-in desktop) === */}
      {drawerOpen && (
        <>
          <div
            className="agent-drawer-backdrop"
            onClick={() => setDrawerOpen(false)}
          />
          <aside className="agent-drawer">
            <div className="agent-drawer-header">
              <strong>{language === 'hinglish' ? 'Tools & connections' : 'Tools & connections'}</strong>
              <button
                type="button"
                className="btn btn-ghost btn-sm btn-icon"
                onClick={() => setDrawerOpen(false)}
                aria-label="Close panel"
              >
                <FiX />
              </button>
            </div>

            <section className="agent-drawer-section">
              <div className="agent-drawer-section-title">
                <FiLink2 />
                <span>{language === 'hinglish' ? 'Connected' : 'Connected'}</span>
                {connections.length > 0 && (
                  <span className="chat-meta-chip hit">{connections.length}</span>
                )}
              </div>
              {connections.length === 0 ? (
                <div className="agent-drawer-empty">
                  {language === 'hinglish'
                    ? 'Abhi koi connection nahi'
                    : 'No connections yet'}
                </div>
              ) : (
                <ul className="agent-drawer-list">
                  {connections.map((c) => (
                    <li key={c.id} className="agent-drawer-item" style={{
                      flexDirection: 'column',
                      alignItems: 'stretch',
                      gap: 6,
                      padding: '10px 12px',
                      border: !c.is_authorized ? '1px solid #f59e0b33' : '1px solid transparent',
                      borderRadius: 8,
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <div>
                          <div className="agent-drawer-item-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            {c.display_name || c.tool}
                            {c.is_authorized
                              ? <span style={{ fontSize: '0.65rem', color: '#22c55e', background: '#22c55e18', borderRadius: 4, padding: '1px 6px' }}>● Active</span>
                              : <span style={{ fontSize: '0.65rem', color: '#f59e0b', background: '#f59e0b18', borderRadius: 4, padding: '1px 6px' }}>⚠ Needs auth</span>
                            }
                          </div>
                          <div className="agent-drawer-item-sub">{c.auth_type}</div>
                        </div>
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          style={{ fontSize: '0.7rem', color: '#ef4444', display: 'flex', alignItems: 'center', gap: 3 }}
                          onClick={() => handleDeleteConnection(c.id)}
                          title="Disconnect"
                        >
                          <FiTrash2 size={12} /> Disconnect
                        </button>
                      </div>
                      {!c.is_authorized && (
                        <div style={{ background: '#f59e0b12', border: '1px solid #f59e0b33', borderRadius: 6, padding: '8px 10px', fontSize: '0.78rem', color: '#92400e' }}>
                          <div style={{ fontWeight: 600, marginBottom: 4 }}>⚠ Authorization required</div>
                          <div style={{ marginBottom: 6, color: '#78350f' }}>
                            Paste an <strong>Access Token</strong> directly while reconnecting, or use the Authorize button if OAuth is set up.
                          </div>
                          <a
                            href={dynamicAgentService.getOAuthAuthorizeUrl(c.tool)}
                            className="btn btn-sm"
                            style={{ fontSize: '0.72rem', padding: '3px 10px', background: '#f59e0b', color: '#fff', borderRadius: 5, textDecoration: 'none' }}
                          >
                            Authorize via OAuth →
                          </a>
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="agent-drawer-section">
              <div className="agent-drawer-section-title">
                <FiBookOpen />
                <span>{language === 'hinglish' ? 'Cached tools' : 'Cached tools'}</span>
                {tools.length > 0 && (
                  <span className="chat-meta-chip">{tools.length}</span>
                )}
              </div>
              {tools.length === 0 ? (
                <div className="agent-drawer-empty">
                  {language === 'hinglish'
                    ? 'Abhi koi tool cached nahi'
                    : 'No tool docs cached'}
                </div>
              ) : (
                <ul className="agent-drawer-list">
                  {tools.map((t) => (
                    <li key={t.name} className="agent-drawer-item">
                      <div>
                        <div className="agent-drawer-item-title">
                          {t.display_name}
                        </div>
                        <div className="agent-drawer-item-sub">
                          {t.auth_type} · {t.endpoint_count} endpoints
                        </div>
                      </div>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm btn-icon"
                        onClick={() => handleInspectTool(t.name)}
                        aria-label="Inspect"
                      >
                        <FiBookOpen />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </aside>
        </>
      )}

      {/* ====================== credentials modal ====================== */}
      {credPrompt && (
        <CredentialModal
          credPrompt={credPrompt}
          credValues={credValues}
          setCredValues={setCredValues}
          savingCreds={savingCreds}
          onSubmit={handleSubmitCreds}
          onCancel={() => !savingCreds && setCredPrompt(null)}
          language={language}
        />
      )}

      {/* ====================== tool inspector ====================== */}
      {inspectedTool && (
        <ToolInspector
          tool={inspectedTool}
          onClose={() => setInspectedTool(null)}
        />
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────── components

function UserBubble({ prompt }) {
  return (
    <div className="chat-message chat-msg-user">
      <div className="chat-avatar">You</div>
      <div className="chat-bubble">
        <div className="chat-bubble-body">{prompt}</div>
      </div>
    </div>
  );
}

function AgentBubble({ turn }) {
  if (!turn) return null;
  const url = extractCanonicalUrl(turn.response);
  const showDetails = turn.status !== 'success' || turn.action !== 'execute_action';

  return (
    <div className="chat-message chat-msg-assistant">
      <div className="chat-avatar">
        <FiCpu />
      </div>
      <div className="chat-bubble" style={{ minWidth: 240 }}>
        <div className="chat-bubble-body">
          {renderTextWithLinks(turn.summary || turn.error || '(no summary)')}
        </div>

        {url && (
          <div style={{ marginTop: 10 }}>
            <a
              href={url}
              target="_blank"
              rel="noreferrer noopener"
              className="btn btn-primary btn-sm"
            >
              Open ↗
            </a>
          </div>
        )}

        <div className="chat-bubble-meta">
          <StatusChip status={turn.status} />
          {turn.tool && <span className="chat-meta-chip">{turn.tool}</span>}
          {turn.http_status != null && (
            <span className="chat-meta-chip">HTTP {turn.http_status}</span>
          )}
          {turn.duration_ms != null && (
            <span className="chat-meta-chip">{Math.round(turn.duration_ms)}ms</span>
          )}
        </div>

        {(turn.thought || turn.action_input || turn.response || turn.error) && (
          <details style={{ marginTop: 10, fontSize: '0.85em' }} open={showDetails && !!turn.error}>
            <summary
              style={{
                cursor: 'pointer',
                userSelect: 'none',
                color: 'var(--color-text-muted)',
              }}
            >
              Details
            </summary>
            <div style={{ marginTop: 8, display: 'grid', gap: 8 }}>
              {turn.thought && (
                <div>
                  <div className="agent-detail-label">Thought</div>
                  <div className="agent-detail-body">{turn.thought}</div>
                </div>
              )}
              {turn.action_input && (
                <div>
                  <div className="agent-detail-label">
                    Action {turn.action ? `(${turn.action})` : ''}
                  </div>
                  <pre className="agent-code">{formatJson(turn.action_input)}</pre>
                </div>
              )}
              {turn.response != null && (
                <div>
                  <div className="agent-detail-label">Response</div>
                  <pre className="agent-code">{formatJson(turn.response)}</pre>
                </div>
              )}
              {turn.error && (
                <div>
                  <div className="agent-detail-label" style={{ color: 'var(--color-danger)' }}>
                    Error
                  </div>
                  <pre className="agent-code">{turn.error}</pre>
                </div>
              )}
            </div>
          </details>
        )}
      </div>
    </div>
  );
}

function CredentialModal({
  credPrompt,
  credValues,
  setCredValues,
  savingCreds,
  onSubmit,
  onCancel,
  language,
}) {
  return (
    <div className="agent-modal-backdrop" onClick={onCancel}>
      <div className="agent-modal" onClick={(e) => e.stopPropagation()}>
        <div className="agent-modal-header">
          <h3>
            {language === 'hinglish'
              ? `${credPrompt.display_name} ke credentials`
              : `Connect to ${credPrompt.display_name}`}
          </h3>
          <button
            type="button"
            className="btn btn-ghost btn-sm btn-icon"
            onClick={onCancel}
            disabled={savingCreds}
            aria-label="Close"
          >
            <FiX />
          </button>
        </div>
        <div className="agent-modal-sub">Auth type: {credPrompt.auth_type}</div>

        {credPrompt.setup &&
          (credPrompt.setup.intro || credPrompt.setup.steps?.length > 0) && (
            <div className="agent-setup-card">
              <div className="agent-setup-title">
                {language === 'hinglish'
                  ? `${credPrompt.display_name} ke credentials kaise milenge`
                  : `How to get your ${credPrompt.display_name} credentials`}
              </div>
              {credPrompt.setup.intro && (
                <div className="agent-setup-intro">{credPrompt.setup.intro}</div>
              )}
              {credPrompt.setup.steps?.length > 0 && (
                <ol className="agent-setup-steps">
                  {credPrompt.setup.steps.map((s, i) => (
                    <li key={i}>{renderTextWithLinks(s)}</li>
                  ))}
                </ol>
              )}
              {credPrompt.docs_url && (
                <div className="agent-setup-footer">
                  {language === 'hinglish' ? 'Full docs: ' : 'Full docs: '}
                  <a href={credPrompt.docs_url} target="_blank" rel="noreferrer noopener">
                    {credPrompt.docs_url}
                  </a>
                </div>
              )}
            </div>
          )}

        <form onSubmit={onSubmit} className="agent-modal-form">
          {credPrompt.fields.map((f) => (
            <label key={f.name} className="agent-modal-field">
              <span className="agent-modal-field-label">
                {f.label}
                {f.required ? ' *' : ''}
              </span>
              <input
                type={f.type === 'password' ? 'password' : 'text'}
                placeholder={f.placeholder || ''}
                value={credValues[f.name] || ''}
                onChange={(e) =>
                  setCredValues((prev) => ({ ...prev, [f.name]: e.target.value }))
                }
                autoComplete="off"
              />
            </label>
          ))}
          <div className="agent-modal-actions">
            <button
              type="button"
              className="btn btn-ghost"
              onClick={onCancel}
              disabled={savingCreds}
            >
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={savingCreds}>
              {savingCreds
                ? language === 'hinglish'
                  ? 'Save ho raha…'
                  : 'Saving…'
                : language === 'hinglish'
                ? 'Save & Connect'
                : 'Save & Connect'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function ToolInspector({ tool, onClose }) {
  return (
    <div className="agent-modal-backdrop" onClick={onClose}>
      <div className="agent-modal agent-modal-wide" onClick={(e) => e.stopPropagation()}>
        <div className="agent-modal-header">
          <h3>
            {tool.display_name} <span className="chat-meta-chip">{tool.auth_type}</span>
          </h3>
          <button
            type="button"
            className="btn btn-ghost btn-sm btn-icon"
            onClick={onClose}
            aria-label="Close"
          >
            <FiX />
          </button>
        </div>
        <div className="agent-modal-sub">
          <strong>Base URL:</strong> <code>{tool.base_url}</code>
          {tool.docs_url && (
            <>
              {' · '}
              <a href={tool.docs_url} target="_blank" rel="noreferrer noopener">
                Docs ↗
              </a>
            </>
          )}
        </div>
        <h4 style={{ marginBottom: 6 }}>Endpoints</h4>
        <pre className="agent-code">{formatJson(tool.endpoints)}</pre>
        <h4 style={{ marginBottom: 6 }}>Auth config</h4>
        <pre className="agent-code">{formatJson(tool.auth_config)}</pre>
        <div className="agent-modal-actions">
          <button className="btn btn-primary" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

export default DynamicAgentPage;
