import React, { useState } from 'react';
import {
  FiZap,
  FiCpu,
  FiDatabase,
  FiActivity,
  FiKey,
  FiTrendingDown,
  FiLogIn,
  FiCheck,
  FiGlobe,
  FiRefreshCw,
  FiLayers,
  FiBox,
  FiServer,
  FiCode,
} from 'react-icons/fi';
import Modal from '../components/Modal';
import LoginForm from '../components/LoginForm';
import RegisterForm from '../components/RegisterForm';

const APP_NAME = import.meta.env.VITE_APP_NAME || 'Adaptora';

const FEATURES = [
  {
    icon: FiGlobe,
    title: 'Dynamic Agent — any API, zero setup',
    body:
      'Type "connect Jira" or "send a Slack message" — Adaptora identifies the tool, fetches its live docs from the internet, extracts every endpoint, and sets it up automatically. No hardcoded integrations.',
  },
  {
    icon: FiBox,
    title: 'Cached tools library',
    body:
      'Every tool you connect gets its full API definition stored locally. Next time you ask about GitHub issues or Stripe payments, the agent already knows every endpoint — no re-fetching needed.',
  },
  {
    icon: FiRefreshCw,
    title: 'Always up-to-date docs',
    body:
      'Hit Refresh on any tool and Adaptora re-crawls the official docs, follows pagination and menu links, parses the OpenAPI spec, and updates the local cache — so your agent always has the latest endpoints.',
  },
  {
    icon: FiActivity,
    title: 'Smart prompt routing',
    body:
      'Every prompt is scored for complexity. Simple and medium prompts run on a free local model; only difficult ones hit your paid subscription — typically saving 70–90% of tokens.',
  },
  {
    icon: FiTrendingDown,
    title: 'Automatic prompt optimization',
    body:
      'Verbose prompts get rewritten to be shorter and clearer before they hit the LLM. Real measured reduction, tracked on your dashboard.',
  },
  {
    icon: FiDatabase,
    title: 'Response caching',
    body:
      'Identical prompts return cached answers instantly — no token spend, no LLM round-trip. Cache hit rate is visible on your home dashboard.',
  },
  {
    icon: FiKey,
    title: 'Bring your own keys',
    body:
      'Plug in your OpenAI or Anthropic key and pick from the models your account has access to. Keys are encrypted at rest and only shown masked.',
  },
  {
    icon: FiCpu,
    title: 'Auto model selection',
    body:
      'In "Auto" mode, the local model picks which of your saved providers is best suited for each prompt — visible in real time as your response streams.',
  },
  {
    icon: FiZap,
    title: 'Live pipeline status',
    body:
      'Watch each step happen — cache check, complexity score, prompt optimization, model selection, generation — as it runs. No black-box spinner.',
  },
  {
    icon: FiServer,
    title: 'MCP Server — Claude Desktop integration',
    body:
      'Connect to Claude Desktop, Claude Code, Cursor, or any MCP client. Every API endpoint becomes a typed tool your AI assistant can call directly. New tools appear automatically.',
  },
  {
    icon: FiCode,
    title: '100% open source & self-hosted',
    body:
      'Deploy locally with Docker. Read every line of code. BUSL-1.1 licensed — free for non-commercial use, converts to Apache 2.0 in 2030. No vendor lock-in, full control.',
  },
];

const AGENT_STEPS = [
  { label: 'Name it — or just describe it', detail: '"Jira" · or · "create a ticket in my project tracker"' },
  { label: 'Agent identifies the tool', detail: 'Jira · confidence 97%' },
  { label: 'Docs fetched & cached', detail: 'Crawls official docs + OpenAPI spec → 240 endpoints stored' },
  { label: 'Action planned', detail: 'POST /rest/api/3/issue · project: MY · summary: Fix login bug' },
  { label: 'Executed with your saved credentials', detail: 'HTTP 201 · issue created ✓' },
];

const CACHED_TOOLS = [
  'Slack', 'GitHub', 'Jira', 'Notion', 'Stripe', 'Razorpay',
  'Gmail', 'Linear', 'Trello', 'Figma', 'HubSpot', 'Asana',
  'Twilio', 'Shopify', 'SendGrid', 'AWS', 'OpenAI', '+ any REST API',
];

const LLM_STEPS = [
  'You send a prompt from the chat',
  'Adaptora checks the cache and scores complexity',
  'Verbose prompts are rewritten to be more concise',
  'Easy/medium → free local model · Difficult → your paid subscription',
  'You get the answer plus a breakdown of cost and tokens saved',
];

function LandingPage() {
  const [showLogin, setShowLogin] = useState(false);
  const [showRegister, setShowRegister] = useState(false);

  const openLogin = () => { setShowRegister(false); setShowLogin(true); };
  const openRegister = () => { setShowLogin(false); setShowRegister(true); };
  const closeAll = () => { setShowLogin(false); setShowRegister(false); };

  return (
    <div className="landing-root">
      <header className="landing-nav">
        <div className="landing-brand">
          <FiZap className="landing-brand-icon" />
          <span>{APP_NAME}</span>
        </div>
        <nav className="landing-nav-actions">
          <button type="button" className="btn btn-ghost btn-icon" onClick={openLogin}>
            <FiLogIn />
            <span>Sign in</span>
          </button>
          <button type="button" className="btn btn-primary btn-icon" onClick={openRegister}>
            <FiZap />
            <span>Start free</span>
          </button>
        </nav>
      </header>

      {/* ── Hero ── */}
      <section className="landing-hero">
        <div className="landing-hero-content">
          <span className="landing-eyebrow">AI Integration Platform</span>
          <h1>
            Connect any tool.<br />
            <span className="landing-hero-accent">Automate with AI — for less.</span>
          </h1>
          <p className="landing-hero-sub">
            {APP_NAME} connects your apps, APIs, and AI models in one place.
            Send Slack messages, query GitHub, hit any REST API — all from a
            single chat. Plus it cuts your LLM bill by 70–90% by routing
            simple prompts to a free local model.
          </p>
          <div className="landing-cta">
            <button type="button" className="btn btn-primary btn-icon btn-lg" onClick={openRegister}>
              <FiZap />
              <span>Start free</span>
            </button>
            <button type="button" className="btn btn-secondary btn-icon btn-lg" onClick={openLogin}>
              <FiLogIn />
              <span>Sign in</span>
            </button>
          </div>
          <ul className="landing-hero-bullets">
            <li><FiCheck /> Connect Slack, GitHub, Jira and 100+ APIs instantly</li>
            <li><FiCheck /> Local model handles ~80% of prompts for free</li>
            <li><FiCheck /> Works with Claude Desktop via MCP</li>
          </ul>
        </div>
        <div className="landing-hero-card">
          <div className="landing-card-row">
            <span className="landing-pill landing-pill-muted">User prompt</span>
            <span className="landing-pill landing-pill-original">87 tokens</span>
          </div>
          <p className="landing-card-prompt">
            "Could you please write a very detailed and thorough explanation of
            how machine learning works, including various techniques used today?"
          </p>
          <div className="landing-arrow">↓ optimized</div>
          <div className="landing-card-row">
            <span className="landing-pill landing-pill-accent">Sent to model</span>
            <span className="landing-pill landing-pill-optimized">23 tokens</span>
          </div>
          <p className="landing-card-prompt">
            "Explain how machine learning works in detail, with main techniques."
          </p>
          <div className="landing-card-footer">
            <span><FiTrendingDown /> 73% prompt savings</span>
            <span><FiCpu /> Local AI handled this</span>
          </div>
        </div>
      </section>

      {/* ── Dynamic Agent ── */}
      <section className="landing-agent">
        <div className="landing-section-head">
          <span className="landing-eyebrow">Dynamic Agent</span>
          <h2>Just name it. Adaptora sets it up.</h2>
          <p>
            Type the tool name — or a natural language prompt. Either way, {APP_NAME}
            figures out which tool you mean, fetches its complete API docs from the
            internet, and executes the action with your saved credentials. No manual
            configuration. No hardcoded integrations.
          </p>
        </div>
        <div className="landing-agent-flow">
          {AGENT_STEPS.map((step, i) => (
            <div key={step.label} className="landing-agent-step">
              <div className="landing-agent-step-num">{i + 1}</div>
              <div className="landing-agent-step-body">
                <div className="landing-agent-step-label">{step.label}</div>
                <div className="landing-agent-step-detail">{step.detail}</div>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ── Cached Tools ── */}
      <section className="landing-cached">
        <div className="landing-section-head">
          <span className="landing-eyebrow">Cached Tools Library</span>
          <h2>Every API — learned once, ready forever.</h2>
          <p>
            When you connect a tool, {APP_NAME} crawls its official docs, follows every
            menu link, parses the OpenAPI spec, and stores the full endpoint library
            locally. Future requests are instant — no re-fetching, no delays.
            Hit <strong>Refresh</strong> anytime to pull the latest from the live docs.
          </p>
        </div>
        <div className="landing-tools-grid">
          {CACHED_TOOLS.map((tool) => (
            <div key={tool} className="landing-tool-chip">
              <FiLayers />
              <span>{tool}</span>
            </div>
          ))}
        </div>
        <p className="landing-tools-hint">
          Don't see your tool? Just type its name — {APP_NAME} will find it.
        </p>
      </section>

      {/* ── MCP + Open Source Quick Start ── */}
      <section className="landing-mcp-section">
        <div className="landing-section-head">
          <span className="landing-eyebrow">100% Open Source</span>
          <h2>Run Adaptora locally. Integrate with MCP.</h2>
          <p>
            Deploy to your own infrastructure in minutes using Docker. Connect it to Claude Desktop, Claude Code, Cursor, or any MCP client.
            Your credentials stay encrypted on your server. BUSL-1.1 licensed — free for non-commercial use.
          </p>
        </div>
        <div className="landing-mcp-steps">
          <div className="landing-mcp-step-card">
            <div className="landing-mcp-step-num">1</div>
            <h3>Clone & Deploy</h3>
            <p className="landing-mcp-code-label">docker compose up --build</p>
            <p>Full stack: app, database, cache, Ollama LLM. That's it.</p>
          </div>
          <div className="landing-mcp-step-card">
            <div className="landing-mcp-step-num">2</div>
            <h3>Connect to Claude Desktop</h3>
            <p className="landing-mcp-code-label">Edit ~/.claude/claude_desktop_config.json</p>
            <p>Add adaptora MCP server config (3 lines). Restart.</p>
          </div>
          <div className="landing-mcp-step-card">
            <div className="landing-mcp-step-num">3</div>
            <h3>Use from Claude</h3>
            <p className="landing-mcp-code-label">"List my GitHub issues"</p>
            <p>Natural language. Every API endpoint is a tool.</p>
          </div>
        </div>
      </section>

      {/* ── All Features ── */}
      <section className="landing-features">
        <div className="landing-section-head">
          <h2>Everything in the box</h2>
          <p>Eleven capabilities, one platform.</p>
        </div>
        <div className="landing-feature-grid">
          {FEATURES.map(({ icon: Icon, title, body }) => (
            <div key={title} className="landing-feature">
              <div className="landing-feature-icon"><Icon /></div>
              <h3>{title}</h3>
              <p>{body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── LLM Flow ── */}
      <section className="landing-flow">
        <div className="landing-section-head">
          <h2>How a prompt flows through {APP_NAME}</h2>
          <p>Each step is visible in real time when you chat.</p>
        </div>
        <ol className="landing-flow-steps">
          {LLM_STEPS.map((step, i) => (
            <li key={step}>
              <span className="landing-step-num">{i + 1}</span>
              <span>{step}</span>
            </li>
          ))}
        </ol>
      </section>

      {/* ── CTA band ── */}
      <section className="landing-cta-band">
        <h2>Your AI hub for every tool, every API, every workflow.</h2>
        <button type="button" className="btn btn-primary btn-icon btn-lg" onClick={openRegister}>
          <FiZap />
          <span>Start free with {APP_NAME}</span>
        </button>
      </section>

      <footer className="landing-footer">
        <span>© {new Date().getFullYear()} {APP_NAME}</span>
        <span>Self-hosted · MIT licensed</span>
      </footer>

      <Modal open={showLogin} onClose={closeAll} title="Sign in">
        <LoginForm onSuccess={closeAll} onSwitchToRegister={openRegister} />
      </Modal>
      <Modal open={showRegister} onClose={closeAll} title="Join Adaptora — it's free">
        <RegisterForm onSuccess={closeAll} onSwitchToLogin={openLogin} />
      </Modal>
    </div>
  );
}

export default LandingPage;
