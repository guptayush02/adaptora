import React, { useState, useEffect, useRef, useCallback } from 'react';
import toast from 'react-hot-toast';
import { useNavigate } from 'react-router-dom';
import {
  FiSend,
  FiPlus,
  FiKey,
  FiTrash2,
  FiMessageSquare,
  FiClock,
  FiCpu,
  FiZap,
  FiCheckCircle,
  FiChevronLeft,
  FiMenu,
  FiEdit3,
  FiExternalLink,
} from 'react-icons/fi';
import {
  queryService,
  authService,
  conversationsService,
  StreamIncompleteError,
} from '../services/api';
import { useAuth } from '../hooks/useAuth';

// User-facing label for the internal "ollama" model name. We hide the engine
// detail in the UI and present it as the project's local model offering.
const LOCAL_MODEL_LABEL = 'Local AI';
function displayModelName(model) {
  if (!model) return '';
  const m = String(model).toLowerCase();
  if (m === 'ollama' || m === 'mistral' || m === 'llama2' || m === 'neural-chat') {
    return LOCAL_MODEL_LABEL;
  }
  return model;
}

function formatRelative(dateString) {
  if (!dateString) return '';
  const date = new Date(dateString);
  const diffMs = Date.now() - date.getTime();
  const mins = Math.round(diffMs / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days}d ago`;
  return date.toLocaleDateString();
}

function ConversationListItem({ convo, active, onSelect, onDelete }) {
  return (
    <li
      className={`chat-conv-item ${active ? 'chat-conv-item-active' : ''}`}
      onClick={() => onSelect(convo.id)}
    >
      <div className="chat-conv-icon">
        <FiMessageSquare />
      </div>
      <div className="chat-conv-meta">
        <div className="chat-conv-title">{convo.title || 'Untitled'}</div>
        <div className="chat-conv-preview">
          {convo.last_message_preview || 'No messages yet'}
        </div>
        <div className="chat-conv-time">{formatRelative(convo.updated_at)}</div>
      </div>
      <button
        type="button"
        className="chat-conv-delete"
        onClick={(e) => {
          e.stopPropagation();
          onDelete(convo.id);
        }}
        aria-label="Delete conversation"
      >
        <FiTrash2 />
      </button>
    </li>
  );
}

// ── Tiny markdown renderer for assistant messages ────────────────────────
// Handles link / bold / bullet rendering for our summarizer output. When the
// caller supplies a `sources` array (the structured web_sources we capture
// from SSE), inline `[N]` citations like "[1]" and "[2]" become small
// clickable links pointing at sources[N-1].url — so the URLs the user asked
// for are reachable directly from the body text, not only from the cards.
//
// Inline tokenizer alternatives (priority order):
//   1. [text](url)         → full markdown link
//   2. **bold**            → <strong>
//   3. bare https URL      → linkified
//   4. [N] where N≤len     → citation link to sources[N-1].url
// Explicit inline styles for every markdown-link / bare-URL we render
// inside a chat bubble. The app-wide `a { text-decoration: none }` rule
// in styles/index.css would otherwise make these anchors render exactly
// like surrounding plain text — which was the "nothing is clickable" bug.
const INLINE_LINK_STYLE = {
  color: '#2563eb',
  textDecoration: 'underline',
  textDecorationStyle: 'solid',
  textUnderlineOffset: '2px',
  cursor: 'pointer',
  wordBreak: 'break-word',
};

function renderInlineTokens(text, sources = null) {
  if (!text) return null;
  const out = [];
  // Combined regex; alternatives are mutually exclusive. The `[N]` branch
  // is gated by a (?!\() lookahead so it doesn't match the `[…](url)` link
  // form above.
  const rx =
    /(\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\))|(\*\*([^*\n]+)\*\*)|(https?:\/\/[^\s)]+)|\[(\d{1,2})\](?!\()/g;
  let last = 0;
  let m;
  let k = 0;
  while ((m = rx.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    if (m[1]) {
      // [text](url)
      out.push(
        <a
          key={`l-${k++}`}
          href={m[3]}
          target="_blank"
          rel="noopener noreferrer"
          style={INLINE_LINK_STYLE}
        >
          {m[2]}
        </a>
      );
    } else if (m[4]) {
      // **bold**
      out.push(<strong key={`b-${k++}`}>{m[5]}</strong>);
    } else if (m[6]) {
      // bare URL
      out.push(
        <a
          key={`u-${k++}`}
          href={m[6]}
          target="_blank"
          rel="noopener noreferrer"
          style={INLINE_LINK_STYLE}
        >
          {m[6]}
        </a>
      );
    } else if (m[7]) {
      // [N] citation — link to sources[N-1] when available, else plain text.
      const n = parseInt(m[7], 10);
      const src = Array.isArray(sources) && sources[n - 1];
      if (src && src.url) {
        out.push(
          <a
            key={`c-${k++}`}
            href={src.url}
            target="_blank"
            rel="noopener noreferrer"
            title={src.title || src.url}
            style={{
              fontSize: '0.85em',
              fontWeight: 700,
              padding: '1px 5px',
              margin: '0 1px',
              borderRadius: 3,
              background: 'rgba(37,99,235,0.12)',
              color: '#2563eb',
              textDecoration: 'none',
              cursor: 'pointer',
            }}
          >
            [{n}]
          </a>
        );
      } else {
        // No matching source — render bare brackets so we don't lose the
        // citation visually.
        out.push(`[${n}]`);
      }
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

// Map markdown `#` count → heading tag. Capped at h4 to keep visual
// hierarchy under control in a chat bubble.
const HEADING_TAGS = { 1: 'h3', 2: 'h4', 3: 'h5', 4: 'h6' };

// Pattern for a source-line bullet emitted by our summarizer prompt:
//   "**[1]** [Title](https://url) — short summary"
// Accepts a few near-misses: optional ** around [N], optional [N] entirely,
// em-dash / en-dash / hyphen / colon as the title→summary separator.
const SOURCE_LINE_RX =
  /^\s*(?:\*\*\s*\[(\d+)\]\s*\*\*|\[(\d+)\])?\s*\[([^\]\n]+)\]\((https?:\/\/[^)\s]+)\)\s*(?:[—–\-:]\s*(.+))?$/;

function SourceCard({ index, title, url, summary }) {
  let host = '';
  try {
    host = new URL(url).hostname.replace(/^www\./, '');
  } catch {
    /* invalid URL — fall through with empty host */
  }
  // Truncate the full URL for display; the click still goes to the full URL.
  const MAX_URL_CHARS = 80;
  const displayUrl =
    url && url.length > MAX_URL_CHARS
      ? `${url.slice(0, MAX_URL_CHARS - 1)}…`
      : url;

  // Hover state: gives the title an underline so the card visibly reads as
  // a hyperlink rather than a passive panel. Inline-styles only so this
  // works without modifying the shared stylesheet.
  const [hovered, setHovered] = useState(false);
  const LINK_COLOR = '#2563eb'; // Tailwind blue-600 — works on light & dark

  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="chat-source-card"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: 'block',
        padding: '12px 14px',
        margin: '8px 0',
        borderRadius: 8,
        border: hovered
          ? `1px solid ${LINK_COLOR}`
          : '1px solid rgba(0,0,0,0.15)',
        textDecoration: 'none',
        color: 'inherit',
        background: hovered ? 'rgba(37,99,235,0.04)' : 'rgba(0,0,0,0.02)',
        transition: 'border-color 120ms ease, background 120ms ease',
      }}
    >
      {/* Title row — clearly link-styled (blue, underline on hover, external
          arrow at the end) so the user immediately sees this is a link. */}
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          gap: 6,
          marginBottom: 4,
        }}
      >
        {index && (
          <span
            style={{
              fontSize: 11,
              fontWeight: 700,
              opacity: 0.7,
              minWidth: 22,
              flexShrink: 0,
            }}
          >
            [{index}]
          </span>
        )}
        <span
          style={{
            fontWeight: 600,
            fontSize: 14,
            color: LINK_COLOR,
            textDecoration: hovered ? 'underline' : 'none',
            flex: 1,
            wordBreak: 'break-word',
          }}
        >
          {title || url}
        </span>
        <FiExternalLink
          aria-hidden
          style={{
            fontSize: 13,
            color: LINK_COLOR,
            opacity: 0.85,
            flexShrink: 0,
          }}
        />
      </div>
      {/* Host pill — small, secondary. */}
      {host && (
        <div
          style={{
            fontSize: 11,
            opacity: 0.7,
            marginLeft: index ? 28 : 0,
            marginBottom: 4,
          }}
        >
          {host}
        </div>
      )}
      {/* Full URL — monospace, dimmer; lets the user see exactly where the
          card goes without hovering. Tooltip carries the un-truncated URL. */}
      {displayUrl && (
        <div
          title={url}
          style={{
            fontSize: 11,
            opacity: 0.55,
            marginLeft: index ? 28 : 0,
            fontFamily:
              'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
            wordBreak: 'break-all',
            lineHeight: 1.3,
          }}
        >
          {displayUrl}
        </div>
      )}
      {/* Summarized content — the 'summarize the content' piece. */}
      {summary && (
        <div
          style={{
            fontSize: 13,
            marginTop: 8,
            marginLeft: index ? 28 : 0,
            opacity: 0.92,
            lineHeight: 1.45,
            color: 'inherit',
          }}
        >
          {summary}
        </div>
      )}
    </a>
  );
}

function MarkdownContent({ text, sources = null }) {
  if (!text) return null;
  // Walk blocks linearly with a `inSources` flag. When we see a `## Sources`
  // heading, the NEXT bullet block is rendered as <SourceCard /> cards
  // instead of a plain <ul>. Anything else renders as before.
  const blocks = text.split(/\n{2,}/);
  const rendered = [];
  let inSources = false;

  blocks.forEach((block, idx) => {
    const lines = block.split('\n');
    const nonEmpty = lines.filter((l) => l.trim());
    if (nonEmpty.length === 0) return;

    // ── Horizontal rule ─────────────────────────────────────────────────
    // A standalone "---" block (the backend uses it as a visual divider
    // right before the appended Sources section).
    if (nonEmpty.length === 1 && /^\s*---+\s*$/.test(nonEmpty[0])) {
      rendered.push(
        <hr
          key={`hr-${idx}`}
          style={{
            border: 'none',
            borderTop: '1px solid rgba(0,0,0,0.12)',
            margin: '14px 0 10px',
          }}
        />
      );
      return;
    }

    // ── Heading ──────────────────────────────────────────────────────────
    const headingMatch = nonEmpty[0].match(/^\s*(#{1,4})\s+(.+?)\s*$/);
    if (headingMatch) {
      const Tag = HEADING_TAGS[headingMatch[1].length] || 'h4';
      const headingText = headingMatch[2];
      // Flip the "next bullet block is sources" flag on `## Sources` /
      // `### Sources` / `## 🔗 Sources` etc. Strip non-letter chars
      // (emojis, leading whitespace) before testing so the appended
      // verified-sources heading is recognised.
      const headingPlain = headingText
        .replace(/[^a-z0-9 ]+/gi, ' ')
        .trim()
        .toLowerCase();
      inSources = headingPlain === 'sources';
      rendered.push(
        <Tag key={`h-${idx}`} className="chat-md-heading">
          {renderInlineTokens(headingText, sources)}
        </Tag>
      );
      // Any content after the heading on the same block. If those lines
      // form a bullet list (every non-empty line starts with `-` or `*`),
      // promote them to a real <ul> (or to SourceCards when inSources is
      // set) — otherwise render as a paragraph. Was the bug: previously
      // any post-heading content was always rendered as a <p>, which
      // turned the Sources bullets into plain text.
      const restLines = lines.slice(lines.indexOf(nonEmpty[0]) + 1);
      const restNonEmpty = restLines.filter((l) => l.trim());
      if (restNonEmpty.length > 0) {
        const restAllBullets = restNonEmpty.every((l) =>
          /^\s*[-*]\s+/.test(l)
        );
        if (restAllBullets) {
          if (inSources) {
            rendered.push(
              <div key={`src-${idx}`} className="chat-source-list">
                {restNonEmpty.map((line, i) => {
                  const bare = line.replace(/^\s*[-*]\s+/, '');
                  const m = bare.match(SOURCE_LINE_RX);
                  if (m) {
                    return (
                      <SourceCard
                        key={i}
                        index={m[1] || m[2] || ''}
                        title={m[3]}
                        url={m[4]}
                        summary={(m[5] || '').trim()}
                      />
                    );
                  }
                  return (
                    <div key={i} className="chat-source-fallback">
                      • {renderInlineTokens(bare, sources)}
                    </div>
                  );
                })}
              </div>
            );
            inSources = false;
          } else {
            rendered.push(
              <ul key={`ul-${idx}`} className="chat-md-list">
                {restNonEmpty.map((line, i) => (
                  <li key={i}>
                    {renderInlineTokens(
                      line.replace(/^\s*[-*]\s+/, ''),
                      sources
                    )}
                  </li>
                ))}
              </ul>
            );
          }
        } else {
          rendered.push(
            <p key={`p-${idx}-rest`} className="chat-md-para">
              {restLines.map((line, i, arr) => (
                <React.Fragment key={i}>
                  {renderInlineTokens(line, sources)}
                  {i < arr.length - 1 && <br />}
                </React.Fragment>
              ))}
            </p>
          );
        }
      }
      return;
    }

    // ── Bullet list ──────────────────────────────────────────────────────
    const allBullets = nonEmpty.every((l) => /^\s*[-*]\s+/.test(l));
    if (allBullets) {
      if (inSources) {
        // Each bullet should be a source line; render as cards. Reset the
        // flag — only the first bullet block after `## Sources` counts.
        rendered.push(
          <div key={`src-${idx}`} className="chat-source-list">
            {nonEmpty.map((line, i) => {
              const bare = line.replace(/^\s*[-*]\s+/, '');
              const m = bare.match(SOURCE_LINE_RX);
              if (m) {
                const index = m[1] || m[2] || '';
                const title = m[3];
                const url = m[4];
                const summary = (m[5] || '').trim();
                return (
                  <SourceCard
                    key={i}
                    index={index}
                    title={title}
                    url={url}
                    summary={summary}
                  />
                );
              }
              // Couldn't parse — fall back to a normal bullet so the user
              // still sees the content.
              return (
                <div key={i} className="chat-source-fallback">
                  • {renderInlineTokens(bare, sources)}
                </div>
              );
            })}
          </div>
        );
        inSources = false;
        return;
      }
      rendered.push(
        <ul key={`ul-${idx}`} className="chat-md-list">
          {nonEmpty.map((line, i) => (
            <li key={i}>
              {renderInlineTokens(line.replace(/^\s*[-*]\s+/, ''), sources)}
            </li>
          ))}
        </ul>
      );
      return;
    }

    // ── Plain paragraph ──────────────────────────────────────────────────
    rendered.push(
      <p key={`p-${idx}`} className="chat-md-para">
        {lines.map((line, i) => (
          <React.Fragment key={i}>
            {renderInlineTokens(line, sources)}
            {i < lines.length - 1 && <br />}
          </React.Fragment>
        ))}
      </p>
    );
  });

  return <>{rendered}</>;
}

function MessageBubble({ message }) {
  const isUser = message.role === 'user';
  const sources = !isUser && Array.isArray(message.web_sources)
    ? message.web_sources
    : [];
  return (
    <div className={`chat-message ${isUser ? 'chat-msg-user' : 'chat-msg-assistant'}`}>
      <div className="chat-avatar">{isUser ? 'You' : 'AI'}</div>
      <div className="chat-bubble">
        <div className="chat-bubble-body">
          {isUser ? (
            // User input — render as plain text so no markdown is parsed
            // from what they typed (avoids surprises if they paste links).
            message.content
          ) : (
            <MarkdownContent text={message.content} sources={sources} />
          )}
        </div>
        {/* NOTE: a separate `chat-web-sources` block used to live here, but
            it duplicated the `## 🔗 Sources` cards rendered inside the
            markdown body. The body version uses the same SourceCard
            component (via MarkdownContent's inSources branch), so dropping
            this block leaves exactly one set of cards on screen. The
            `sources` array is still passed to MarkdownContent above so the
            inline `[N]` citation pills can keep linking to sources[N-1]. */}
        {!isUser && (message.model_used || message.complexity_level) && (
          <div className="chat-bubble-meta">
            {message.model_used && (
              <span className="chat-meta-chip">
                <FiCpu /> {displayModelName(message.model_used)}
              </span>
            )}
            {message.complexity_level && (
              <span className={`chat-meta-chip complexity-${message.complexity_level}`}>
                <FiZap /> {message.complexity_level}
              </span>
            )}
            {message.total_tokens > 0 && (
              <span className="chat-meta-chip">
                <FiCpu /> {message.total_tokens} tokens
              </span>
            )}
            {message.cache_hit && (
              <span className="chat-meta-chip hit">
                <FiCheckCircle /> cache hit
              </span>
            )}
            {message.processing_time_ms > 0 && (
              <span className="chat-meta-chip">
                <FiClock /> {Math.round(message.processing_time_ms)}ms
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function PromptsPage() {
  const { user } = useAuth();
  const navigate = useNavigate();

  const [conversations, setConversations] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [loadingConvos, setLoadingConvos] = useState(true);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [sending, setSending] = useState(false);

  const [prompt, setPrompt] = useState('');
  const [temperature, setTemperature] = useState(
    parseFloat(import.meta.env.VITE_DEFAULT_TEMPERATURE) || 0.7
  );
  const [apiKeys, setApiKeys] = useState([]);
  const [providerModels, setProviderModels] = useState({});
  const [selectedAdvancedModel, setSelectedAdvancedModel] = useState(
    import.meta.env.VITE_DEFAULT_MODEL || 'auto'
  );
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [statusStep, setStatusStep] = useState(null);

  // Preview-optimized-prompt flow. When enabled, clicking Send first calls
  // /api/optimize/stream, shows the optimized prompt in an editable inline
  // card, and submits the (possibly edited) text only after Continue. The
  // streaming endpoint lets us narrate each pre-check stage in the UI rather
  // than showing a blank spinner — important on non-English prompts where
  // the translate-then-optimize pipeline can take several seconds.
  const [previewOptimized, setPreviewOptimized] = useState(false);
  const [optimizePreview, setOptimizePreview] = useState(null);
  // { original, optimized, editable, tokensSaved, percentage, reason } | null
  const [optimizing, setOptimizing] = useState(false);
  const [optimizeStatus, setOptimizeStatus] = useState(null);  // current SSE step

  const messagesEndRef = useRef(null);
  const textareaRef = useRef(null);

  useEffect(() => {
    loadConversations();
    loadAPIKeys();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, sending]);

  const loadConversations = useCallback(async () => {
    try {
      setLoadingConvos(true);
      const list = await conversationsService.list();
      setConversations(list || []);
    } catch (err) {
      console.error('Load conversations error:', err);
      toast.error('Failed to load conversations');
    } finally {
      setLoadingConvos(false);
    }
  }, []);

  const loadAPIKeys = async () => {
    try {
      const keys = await authService.getAPIKeys();
      setApiKeys(keys || []);

      const uniqueProviders = [
        ...new Set(
          (keys || [])
            .filter((k) => k.provider !== 'ollama')
            .map((k) => k.provider)
        ),
      ];
      const fetched = {};
      await Promise.all(
        uniqueProviders.map(async (provider) => {
          try {
            const res = await authService.getModels(provider);
            fetched[provider] = res?.models || [];
          } catch (err) {
            console.error(`Failed to fetch models for ${provider}:`, err);
            fetched[provider] = [];
          }
        })
      );
      setProviderModels(fetched);
    } catch (err) {
      console.error('Load API keys error:', err);
    }
  };

  const selectConversation = async (id) => {
    setActiveId(id);
    setSidebarOpen(false);
    try {
      setLoadingMessages(true);
      const data = await conversationsService.get(id);
      setMessages(data?.messages || []);
    } catch (err) {
      console.error('Load conversation error:', err);
      toast.error('Failed to load conversation');
      setMessages([]);
    } finally {
      setLoadingMessages(false);
    }
  };

  const startNewConversation = () => {
    setActiveId(null);
    setMessages([]);
    setPrompt('');
    setSidebarOpen(false);
    // Defer focus until React has flushed the empty state
    setTimeout(() => textareaRef.current?.focus(), 0);
  };

  const deleteConversation = async (id) => {
    if (!window.confirm('Delete this conversation?')) return;
    try {
      await conversationsService.remove(id);
      toast.success('Conversation deleted');
      if (activeId === id) {
        startNewConversation();
      }
      loadConversations();
    } catch (err) {
      console.error('Delete error:', err);
      toast.error('Failed to delete conversation');
    }
  };

  const advancedKeys = apiKeys.filter((k) => k.provider !== 'ollama');
  const advancedModelOptions = advancedKeys.flatMap((key) => {
    const models = providerModels[key.provider] || [key.model_name];
    return models.map((model) => ({
      value: `${key.provider}:${model}`,
      label: `${key.provider.toUpperCase()} – ${model}`,
    }));
  });
  const modelOptions = [
    { value: 'auto', label: `Auto (${LOCAL_MODEL_LABEL} picks for difficult prompts)` },
    ...advancedModelOptions,
  ];

  const sendMessage = async (e) => {
    e?.preventDefault();
    const trimmed = prompt.trim();
    if (!trimmed) {
      toast.error('Please enter a prompt');
      return;
    }

    // When the preview toggle is on, intercept Send: /api/optimize now runs
    // ALL pre-checks (bypass + complexity + optimization + internet-needed)
    // and returns the results. We show them to the user, let them edit, then
    // pass the precomputed decisions back on Continue so the streaming
    // endpoint can skip every pre-check.
    if (previewOptimized) {
      try {
        setOptimizing(true);
        setOptimizeStatus({ step: 'optimize_starting' });
        const result = await queryService.streamOptimizePrompt({
          prompt: trimmed,
          onStatus: (evt) => setOptimizeStatus(evt),
        });
        setOptimizePreview({
          original: trimmed,
          editable: result.optimized_prompt || trimmed,
          tokensSaved: result.tokens_saved || 0,
          percentage: result.optimization_percentage || 0,
          reason: result.optimization_reason || '',
          complexityLevel: result.complexity_level || 'medium',
          complexityScore: result.complexity_score || 0,
          bypass: !!result.bypass,
          needsInternet: !!result.needs_internet,
        });
      } catch (err) {
        console.error('Optimize preview error:', err);
        toast.error(
          err.response?.data?.detail || err.message || 'Failed to optimize prompt'
        );
      } finally {
        setOptimizing(false);
        setOptimizeStatus(null);
      }
      return;
    }

    await deliverPrompt({ promptText: trimmed, skipOptimization: false });
  };

  /**
   * Push a prompt through the streaming pipeline. Shared between the direct
   * Send path and the "Continue" button on the optimize-preview modal.
   * When `precomputed` is supplied (preview-Continue path), those decisions
   * are passed through so the backend skips re-running them.
   */
  const deliverPrompt = async ({
    promptText,
    skipOptimization,
    precomputed = null,
    // `originalPrompt` is the raw text the user TYPED, before /api/optimize
    // translated/shortened it. We send it as `pre_original_prompt` so the
    // backend can use it for the dashboard's "before vs after" chart —
    // otherwise both bars get computed on the already-optimized text and
    // look identical (the Hindi → English equal-bars bug).
    originalPrompt = null,
  }) => {
    // Optimistic user bubble
    const tempUserMsg = {
      id: `local-${Date.now()}`,
      role: 'user',
      content: promptText,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tempUserMsg]);
    setPrompt('');
    setSending(true);
    setStatusStep({ step: 'starting' });

    // Track the most recent conversation_id we've seen — either the one the
    // user already had open or the one announced via `conversation_started`.
    // Used by the recovery path if the SSE stream dies before `done`.
    let pendingConvoId = activeId;

    // Captured from the `web_sources` SSE event that the backend emits after
    // it scrapes the top search-result URLs. Used as `message.web_sources`
    // on the assistant bubble so each result becomes a clickable card.
    let pendingWebSources = null;

    const appendFromResponse = (result) => {
      setMessages((prev) => {
        const withoutTemp = prev.filter((m) => m.id !== tempUserMsg.id);
        return [
          ...withoutTemp,
          {
            id: result.user_message_id ?? tempUserMsg.id,
            role: 'user',
            content: promptText,
            created_at: tempUserMsg.created_at,
          },
          {
            id: result.assistant_message_id ?? `assistant-${Date.now()}`,
            role: 'assistant',
            content: result.response,
            model_used: result.model_used,
            complexity_level: result.complexity_level,
            total_tokens:
              result.tokens_used?.total_tokens ?? result.tokens_used ?? 0,
            cache_hit: result.cache_hit,
            processing_time_ms: result.processing_time_ms,
            created_at: new Date().toISOString(),
            // Attach the structured per-source data we captured from SSE so
            // the bubble renders them as cards. Will be null on non-web turns.
            web_sources: pendingWebSources,
          },
        ];
      });
      if (!activeId && result.conversation_id) {
        setActiveId(result.conversation_id);
      }
      loadConversations();
    };

    try {
      const result = await queryService.streamProcessPrompt({
        prompt: promptText,
        model: selectedAdvancedModel,
        temperature,
        userId: user?.id,
        conversationId: activeId,
        skipOptimization,
        // Hand the precomputed routing decisions back to the backend so
        // /api/process/stream can skip bypass / complexity / optimization /
        // YES-NO-internet — they were already run by /api/optimize.
        preComplexityLevel: precomputed?.complexityLevel ?? null,
        preBypass: precomputed?.bypass ?? null,
        preNeedsInternet: precomputed?.needsInternet ?? null,
        // The user's pre-optimization text, used by the dashboard chart so
        // the "original vs optimized" bars reflect real user input rather
        // than two readings of the same already-optimized text.
        preOriginalPrompt: originalPrompt,
        onStatus: (evt) => {
          if (evt?.conversation_id) pendingConvoId = evt.conversation_id;
          // The backend emits the structured source list right after web
          // scraping. Stash it for `appendFromResponse` to attach to the
          // assistant message once it arrives.
          if (evt?.step === 'web_sources' && Array.isArray(evt.sources)) {
            pendingWebSources = evt.sources;
          }
          setStatusStep(evt);
        },
      });

      appendFromResponse(result);
    } catch (err) {
      console.error('Send error:', err);

      // Stream died before `done` — backend almost certainly finished and
      // saved the assistant message. Poll the conversation a few times to
      // recover it so the user doesn't have to refresh manually.
      if (err instanceof StreamIncompleteError) {
        const convoId = err.conversationId || pendingConvoId;
        const recovered = convoId
          ? await recoverConversationMessage(convoId, tempUserMsg.id)
          : null;
        if (recovered) {
          appendFromResponse(recovered);
          toast.success('Response recovered after the connection dropped.');
        } else {
          toast.error(
            'Connection dropped. Refresh the page if the response doesn\'t appear.'
          );
          setMessages((prev) => prev.filter((m) => m.id !== tempUserMsg.id));
        }
      } else {
        toast.error(
          err.response?.data?.detail || err.message || 'Failed to send prompt'
        );
        setMessages((prev) => prev.filter((m) => m.id !== tempUserMsg.id));
      }
    } finally {
      setSending(false);
      setStatusStep(null);
    }
  };

  /**
   * Poll the conversation a few times to recover the assistant message that
   * the backend likely saved even though the SSE stream was killed. Returns
   * a PromptResponse-shaped object or null if recovery fails.
   */
  async function recoverConversationMessage(convoId, tempUserId) {
    const RETRIES = 6;
    const DELAY_MS = 1500;
    for (let i = 0; i < RETRIES; i++) {
      try {
        const data = await conversationsService.get(convoId);
        const msgs = data?.messages || [];
        // Find the latest assistant message — it should be the one our
        // (still-pending) user prompt triggered.
        const lastAssistant = [...msgs]
          .reverse()
          .find((m) => m.role === 'assistant');
        if (lastAssistant) {
          // Match the shape that appendFromResponse expects.
          return {
            response: lastAssistant.content,
            model_used: lastAssistant.model_used,
            complexity_level: lastAssistant.complexity_level,
            tokens_used: { total_tokens: lastAssistant.total_tokens || 0 },
            cache_hit: !!lastAssistant.cache_hit,
            processing_time_ms: lastAssistant.processing_time_ms || 0,
            conversation_id: convoId,
            assistant_message_id: lastAssistant.id,
            // user_message_id we don't know precisely — replacing the optimistic
            // bubble with the temp id keeps the UI consistent.
            user_message_id: tempUserId,
          };
        }
      } catch (e) {
        console.error('Recovery fetch failed:', e);
      }
      await new Promise((r) => setTimeout(r, DELAY_MS));
    }
    return null;
  }

  // Map raw step names from the SSE stream to user-facing labels.
  const statusLabel = (() => {
    if (!statusStep) return null;
    const {
      step,
      level,
      score,
      tokens_saved,
      target,
      provider,
      model: pickedModel,
      query: searchQuery,
      result_count,
      city,
      timezone: tzName,
      engine: searchEngine,
    } = statusStep;
    // Friendly label for the SSE-reported search engine name.
    const engineLabel = {
      tavily: 'Tavily',
      ollama_web: 'Ollama Web Search',
      google: 'Google',
      duckduckgo: 'DuckDuckGo',
    }[searchEngine] || 'the web';
    // Truncate long search queries so the status line stays one row tall.
    const shortQuery =
      typeof searchQuery === 'string' && searchQuery.length > 60
        ? `${searchQuery.slice(0, 57)}…`
        : searchQuery;
    const map = {
      starting: 'Starting…',
      cache_check: 'Checking cache…',
      cache_hit: 'Cache hit — preparing response',
      cache_miss: 'Cache miss — continuing',
      bypass_check: 'Checking bypass keywords…',
      bypass_hit: 'Bypass keyword found — routing to advanced model',
      complexity_analyzing: 'Analyzing prompt complexity…',
      complexity_done:
        level && score !== undefined
          ? `Complexity: ${level} (score ${Number(score).toFixed(0)})`
          : 'Complexity analyzed',
      optimizing: 'Optimizing prompt…',
      searching_internet: shortQuery
        ? `Searching ${engineLabel} for "${shortQuery}"…`
        : `Searching ${engineLabel}…`,
      search_complete:
        typeof result_count === 'number'
          ? result_count > 0
            ? `Got ${result_count} ${engineLabel} result${result_count === 1 ? '' : 's'}`
            : `No ${engineLabel} results found — answering with what we have`
          : 'Web search complete',
      fetching_pages:
        typeof statusStep.count === 'number'
          ? `Fetching content from ${statusStep.count} page${statusStep.count === 1 ? '' : 's'}…`
          : 'Fetching page content…',
      pages_fetched: 'Page content extracted',
      summarizing_results: 'Summarizing search results…',
      time_lookup: city
        ? `Looking up current time in ${city.replace(/\b\w/g, (c) => c.toUpperCase())}${
            tzName ? ` (${tzName})` : ''
          }…`
        : 'Looking up local time…',
      optimized:
        tokens_saved > 0
          ? `Prompt optimized — saved ${tokens_saved} tokens`
          : 'Prompt optimized',
      optimization_skipped: 'Using your edited prompt as-is',
      preview_continue: 'Using your reviewed prompt — skipping pre-checks',
      selecting_advanced_model: 'Choosing the best advanced model…',
      selected_advanced_model:
        provider && pickedModel
          ? `Selected ${provider.toUpperCase()} – ${pickedModel}`
          : 'Advanced model selected',
      routing:
        target === 'advanced'
          ? 'Routing to advanced model…'
          : `Routing to ${LOCAL_MODEL_LABEL}…`,
      thinking:
        target === 'advanced'
          ? pickedModel
            ? `${pickedModel} is thinking…`
            : 'Advanced model is thinking…'
          : `${LOCAL_MODEL_LABEL} is thinking…`,
      done: 'Finalizing…',
    };
    return map[step] || step;
  })();

  // Derived label for the /api/optimize/stream pre-check pipeline. Shown in
  // the inline "Optimizing your prompt…" card so the user sees WHICH step
  // is running (especially useful on non-English prompts where the
  // translate-then-optimize sequence can take several seconds).
  const optimizeStatusLabel = (() => {
    if (!optimizeStatus) return null;
    const { step, level, score, tokens_saved, is_non_english, needs_internet } =
      optimizeStatus;
    const map = {
      optimize_starting: 'Starting optimization…',
      optimize_bypass_check: 'Checking bypass keywords…',
      optimize_bypass_done: 'Bypass checked',
      optimize_complexity_analyzing: 'Analyzing complexity…',
      optimize_complexity_done:
        level && score !== undefined
          ? `Complexity: ${level} (score ${Number(score).toFixed(0)})`
          : 'Complexity analyzed',
      language_detected: is_non_english
        ? 'Non-English prompt detected'
        : 'English prompt detected',
      optimize_optimizing: 'Optimizing prompt with Ollama…',
      translating: 'Translating to English…',
      translated: 'Translated to English',
      translation_failed:
        'Translation failed — using original prompt',
      optimizing: 'Optimizing prompt…',
      optimize_optimization_done:
        tokens_saved > 0
          ? `Optimized — saved ${tokens_saved} tokens`
          : 'Optimization complete',
      optimize_internet_check: 'Checking if internet is needed…',
      optimize_internet_done:
        typeof needs_internet === 'boolean'
          ? `Internet needed: ${needs_internet ? 'yes' : 'no'}`
          : 'Internet check complete',
    };
    return map[step] || step;
  })();

  const handleTextareaKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const activeConvo = conversations.find((c) => c.id === activeId);

  return (
    <div className="chat-layout">
      <aside className={`chat-sidebar ${sidebarOpen ? 'chat-sidebar-open' : ''}`}>
        <div className="chat-sidebar-header">
          <button
            type="button"
            className="btn btn-primary btn-icon chat-new-btn"
            onClick={startNewConversation}
          >
            <FiPlus />
            <span>New chat</span>
          </button>
          <button
            type="button"
            className="chat-sidebar-close"
            onClick={() => setSidebarOpen(false)}
            aria-label="Close conversations"
          >
            <FiChevronLeft />
          </button>
        </div>

        <div className="chat-sidebar-body">
          {loadingConvos ? (
            <div className="chat-sidebar-empty">Loading…</div>
          ) : conversations.length === 0 ? (
            <div className="chat-sidebar-empty">
              <FiMessageSquare className="empty-icon" />
              <p>No conversations yet.</p>
              <p className="hint">Start typing below to begin a new one.</p>
            </div>
          ) : (
            <ul className="chat-conv-list">
              {conversations.map((c) => (
                <ConversationListItem
                  key={c.id}
                  convo={c}
                  active={c.id === activeId}
                  onSelect={selectConversation}
                  onDelete={deleteConversation}
                />
              ))}
            </ul>
          )}
        </div>

        <div className="chat-sidebar-footer">
          <button
            type="button"
            className="btn btn-ghost btn-icon btn-sm"
            onClick={() => navigate('/keys')}
          >
            <FiKey />
            <span>API Keys</span>
          </button>
        </div>
      </aside>

      {sidebarOpen && (
        <div
          className="chat-sidebar-backdrop"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      <section className="chat-main">
        <header className="chat-main-header">
          <button
            type="button"
            className="chat-open-sidebar"
            onClick={() => setSidebarOpen(true)}
            aria-label="Open conversations"
          >
            <FiMenu />
          </button>
          <div className="chat-main-title">
            <h2>{activeConvo?.title || 'New chat'}</h2>
            <p className="chat-main-sub">
              {activeId
                ? `${messages.length} message${messages.length === 1 ? '' : 's'}`
                : 'Type below to start a conversation'}
            </p>
          </div>
        </header>

        <div className="chat-messages">
          {loadingMessages ? (
            <div className="chat-loading">
              <div className="spinner small"></div>
              <p>Loading messages…</p>
            </div>
          ) : messages.length === 0 ? (
            <div className="chat-empty-state">
              <FiMessageSquare className="empty-icon" />
              <h3>Start a new conversation</h3>
              <p>
                Adaptora routes easy/medium prompts to {LOCAL_MODEL_LABEL}{' '}
                and difficult ones to your configured advanced model.
              </p>
              <div className="chat-suggestions">
                {[
                  'Summarize the differences between SQL and NoSQL.',
                  'Write a Python script to merge two sorted lists.',
                  'Draft a polite email asking for a project update.',
                ].map((s) => (
                  <button
                    key={s}
                    type="button"
                    className="chat-suggestion"
                    onClick={() => {
                      setPrompt(s);
                      setTimeout(() => textareaRef.current?.focus(), 0);
                    }}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((m) => <MessageBubble key={m.id} message={m} />)
          )}

          {sending && (
            <div className="chat-message chat-msg-assistant">
              <div className="chat-avatar">AI</div>
              <div className="chat-bubble chat-status">
                <div className="chat-typing">
                  <span />
                  <span />
                  <span />
                </div>
                {statusLabel && (
                  <div className="chat-status-label">{statusLabel}</div>
                )}
              </div>
            </div>
          )}

          {optimizing && !optimizePreview && (
            <div className="chat-message chat-msg-assistant">
              <div className="chat-avatar">AI</div>
              <div className="chat-bubble chat-status">
                <div className="chat-typing">
                  <span />
                  <span />
                  <span />
                </div>
                <div className="chat-status-label">
                  {optimizeStatusLabel || 'Optimizing your prompt…'}
                </div>
              </div>
            </div>
          )}

          {optimizePreview && (
            <div className="chat-message chat-msg-assistant">
              <div className="chat-avatar">
                <FiEdit3 />
              </div>
              <div
                className="chat-bubble"
                style={{ width: '100%', maxWidth: 'unset' }}
              >
                <div
                  style={{
                    fontWeight: 600,
                    marginBottom: 6,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                  }}
                >
                  <FiEdit3 /> Review optimized prompt
                </div>
                <div style={{ fontSize: 13, opacity: 0.85, marginBottom: 12 }}>
                  Your prompt was rewritten to use fewer tokens. Edit if needed,
                  then press <strong>Continue</strong> to send it through the
                  routing pipeline.
                </div>

                <div style={{ marginBottom: 10 }}>
                  <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 4 }}>
                    Original
                  </div>
                  <div
                    style={{
                      background: 'rgba(0,0,0,0.05)',
                      padding: 8,
                      borderRadius: 6,
                      whiteSpace: 'pre-wrap',
                      fontSize: 13,
                      maxHeight: 120,
                      overflow: 'auto',
                    }}
                  >
                    {optimizePreview.original}
                  </div>
                </div>

                <div style={{ marginBottom: 10 }}>
                  <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 4 }}>
                    Optimized (editable)
                  </div>
                  <textarea
                    value={optimizePreview.editable}
                    onChange={(e) =>
                      setOptimizePreview((prev) =>
                        prev ? { ...prev, editable: e.target.value } : prev
                      )
                    }
                    rows={5}
                    disabled={sending}
                    style={{
                      width: '100%',
                      fontFamily: 'inherit',
                      fontSize: 14,
                      padding: 10,
                      borderRadius: 6,
                      border: '1px solid rgba(0,0,0,0.15)',
                      resize: 'vertical',
                      boxSizing: 'border-box',
                    }}
                  />
                </div>

                <div
                  style={{
                    display: 'flex',
                    flexWrap: 'wrap',
                    gap: 8,
                    fontSize: 12,
                    marginBottom: 12,
                  }}
                >
                  <span
                    className={`chat-meta-chip complexity-${optimizePreview.complexityLevel}`}
                    title="Complexity decided by the analyzer"
                  >
                    Complexity: <strong>{optimizePreview.complexityLevel}</strong>
                    {optimizePreview.complexityScore > 0 &&
                      ` (${Math.round(optimizePreview.complexityScore)})`}
                  </span>
                  <span
                    className="chat-meta-chip"
                    title="Whether the YES/NO internet classifier said the prompt needs fresh web data"
                  >
                    Internet: <strong>{optimizePreview.needsInternet ? 'yes' : 'no'}</strong>
                  </span>
                  {optimizePreview.bypass && (
                    <span
                      className="chat-meta-chip"
                      title="A bypass keyword matched — request will be routed to the advanced model"
                    >
                      Bypass keyword matched
                    </span>
                  )}
                  {optimizePreview.tokensSaved > 0 && (
                    <span className="chat-meta-chip">
                      Saved ~{optimizePreview.tokensSaved} tokens (
                      {optimizePreview.percentage.toFixed(1)}%)
                    </span>
                  )}
                  {optimizePreview.reason && (
                    <span style={{ opacity: 0.7, alignSelf: 'center' }}>
                      · {optimizePreview.reason}
                    </span>
                  )}
                </div>

                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={() => {
                      if (sending) return;
                      setPrompt(optimizePreview.original);
                      setOptimizePreview(null);
                      setTimeout(() => textareaRef.current?.focus(), 0);
                    }}
                    disabled={sending}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="btn btn-primary"
                    disabled={sending || !optimizePreview.editable.trim()}
                    onClick={async () => {
                      const finalText = optimizePreview.editable.trim();
                      if (!finalText) return;
                      // Capture the precomputed decisions BEFORE clearing the
                      // preview state — otherwise we'd lose them between
                      // setOptimizePreview(null) and the deliverPrompt call.
                      const precomputed = {
                        complexityLevel: optimizePreview.complexityLevel,
                        bypass: optimizePreview.bypass,
                        needsInternet: optimizePreview.needsInternet,
                      };
                      // Capture the user's original prompt (Hindi / verbose
                      // English / whatever they typed) BEFORE clearing the
                      // preview state — the dashboard needs it to compute
                      // an honest before/after token comparison.
                      const originalPrompt = optimizePreview.original;
                      setOptimizePreview(null);
                      await deliverPrompt({
                        promptText: finalText,
                        skipOptimization: true,
                        precomputed,
                        originalPrompt,
                      });
                    }}
                  >
                    Continue
                  </button>
                </div>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        <form onSubmit={sendMessage} className="chat-composer">
          <div className="chat-composer-controls">
            <div className="chat-composer-control">
              <label>Model</label>
              <select
                value={selectedAdvancedModel}
                onChange={(e) => setSelectedAdvancedModel(e.target.value)}
                disabled={sending}
              >
                {modelOptions.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="chat-composer-control">
              <label>
                Temperature <span className="value-pill">{temperature}</span>
              </label>
              <input
                type="range"
                min="0"
                max="1"
                step="0.1"
                value={temperature}
                onChange={(e) => setTemperature(parseFloat(e.target.value))}
                disabled={sending}
              />
            </div>
            <div className="chat-composer-control">
              <label
                htmlFor="preview-optimized-toggle"
                style={{ display: 'flex', alignItems: 'center', gap: 6 }}
              >
                <FiEdit3 />
                Preview optimized prompt
              </label>
              <label
                className="toggle-switch"
                style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}
              >
                <input
                  id="preview-optimized-toggle"
                  type="checkbox"
                  checked={previewOptimized}
                  onChange={(e) => setPreviewOptimized(e.target.checked)}
                  disabled={sending}
                />
                <span style={{ fontSize: 12, opacity: 0.75 }}>
                  {previewOptimized ? 'On — edit before sending' : 'Off'}
                </span>
              </label>
            </div>
          </div>

          <div className="chat-input-row">
            <textarea
              ref={textareaRef}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={handleTextareaKeyDown}
              placeholder="Tip: type urgent before your prompt for direct routing. Ask anything… (Enter to send, Shift+Enter for newline)"
              rows={2}
              disabled={sending}
              autoFocus
            />
            <button
              type="submit"
              className="btn btn-primary btn-icon chat-send-btn"
              disabled={sending || !prompt.trim()}
            >
              <FiSend />
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

export default PromptsPage;
