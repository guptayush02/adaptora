import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Add token to requests
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Handle response errors
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export const authService = {
  register: (username, email, password) =>
    api.post('/api/auth/register', { username, email, password }),
  login: (email, password) => api.post('/api/auth/login', { email, password }),
  getCurrentUser: () => api.get('/api/auth/me').then((response) => response.data),
  addAPIKey: (provider, model_name, api_key) =>
    api.post('/api/auth/api-keys', { provider, api_key, model_name }).then((response) => response.data),
  getAPIKeys: () => api.get('/api/auth/api-keys').then((response) => response.data),
  deleteAPIKey: (keyId) =>
    api.delete(`/api/auth/api-keys/${keyId}`).then((response) => response.data),
  getModels: (provider, api_key) =>
    api.post('/api/auth/models', { provider, api_key }).then((response) => response.data),
};

// Custom error so the caller can distinguish a dropped SSE stream from other
// failures and attempt recovery by polling the conversation.
export class StreamIncompleteError extends Error {
  constructor(message, { conversationId } = {}) {
    super(message);
    this.name = 'StreamIncompleteError';
    this.conversationId = conversationId;
  }
}

// Server-Sent Events client for /api/process/stream. EventSource doesn't
// support POST bodies, so we use fetch with a streaming reader and parse the
// SSE framing manually.
async function streamProcessPrompt({
  prompt,
  model,
  temperature,
  userId,
  conversationId = null,
  skipOptimization = false,
  // When the preview pipeline ran the pre-checks already, pass the decisions
  // back so the streaming endpoint can skip them.
  preComplexityLevel = null,
  preBypass = null,
  preNeedsInternet = null,
  // The text the user ACTUALLY typed before /api/optimize translated /
  // shortened it. The backend uses this for the dashboard's "before vs
  // after" chart so the comparison reflects real user input, not the
  // already-optimized prompt the LLM call uses.
  preOriginalPrompt = null,
  onStatus,
  onDone,
  onError,
}) {
  const token = localStorage.getItem('token');
  const response = await fetch(`${API_BASE_URL}/api/process/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({
      prompt,
      model,
      temperature,
      user_id: userId,
      conversation_id: conversationId,
      skip_optimization: skipOptimization,
      pre_complexity_level: preComplexityLevel,
      pre_bypass: preBypass,
      pre_needs_internet: preNeedsInternet,
      pre_original_prompt: preOriginalPrompt,
    }),
  });

  if (!response.ok || !response.body) {
    const text = await response.text().catch(() => '');
    throw new Error(text || `HTTP ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  // Track the conversation_id we learn from status events, so if the stream
  // is killed by a proxy mid-flight we can still recover the saved assistant
  // message by polling the conversation endpoint.
  let observedConvoId = conversationId;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE messages are separated by blank lines
    let sep;
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const raw = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      let event = 'message';
      const dataLines = [];
      for (const line of raw.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
      }
      if (!dataLines.length) continue;
      let payload;
      try {
        payload = JSON.parse(dataLines.join('\n'));
      } catch {
        payload = dataLines.join('\n');
      }
      if (event === 'status') {
        if (payload?.conversation_id) observedConvoId = payload.conversation_id;
        onStatus?.(payload);
      } else if (event === 'done') {
        onDone?.(payload);
        return payload;
      } else if (event === 'error') {
        const err = new Error(payload?.error || 'pipeline error');
        onError?.(err);
        throw err;
      }
    }
  }

  // Stream closed without a `done` event — likely a proxy / load balancer
  // timed out before the model finished. The backend probably still completed
  // and saved the assistant message; the caller should poll the conversation
  // to recover it.
  throw new StreamIncompleteError(
    'The connection closed before the response finished arriving.',
    { conversationId: observedConvoId }
  );
}

// SSE client for /api/optimize/stream. Yields the same `status` / `done` /
// `error` shape as streamProcessPrompt — the UI uses these events to display
// the pre-check stages (bypass / complexity / translating / optimizing /
// internet-needed) instead of a generic spinner.
async function streamOptimizePrompt({ prompt, onStatus, onDone, onError }) {
  const token = localStorage.getItem('token');
  const response = await fetch(`${API_BASE_URL}/api/optimize/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ prompt }),
  });

  if (!response.ok || !response.body) {
    const text = await response.text().catch(() => '');
    throw new Error(text || `HTTP ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let sep;
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const raw = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      let event = 'message';
      const dataLines = [];
      for (const line of raw.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
      }
      if (!dataLines.length) continue;
      let payload;
      try {
        payload = JSON.parse(dataLines.join('\n'));
      } catch {
        payload = dataLines.join('\n');
      }
      if (event === 'status') {
        onStatus?.(payload);
      } else if (event === 'done') {
        onDone?.(payload);
        return payload;
      } else if (event === 'error') {
        const err = new Error(payload?.error || 'optimize pipeline error');
        onError?.(err);
        throw err;
      }
    }
  }

  throw new Error('Optimize stream closed before completion');
}

export const queryService = {
  processPrompt: (prompt, model, temperature, userId, conversationId = null) =>
    api
      .post('/api/process', {
        prompt,
        model,
        temperature,
        user_id: userId,
        conversation_id: conversationId,
      })
      .then((response) => response.data),
  optimizePrompt: (prompt) =>
    api.post('/api/optimize', { prompt }).then((response) => response.data),
  streamOptimizePrompt,
  streamProcessPrompt,
  getUserStats: (userId, filters = {}) =>
    api
      .get(`/api/stats/${userId}`, { params: filters })
      .then((response) => response.data),
  clearCache: () => api.post('/api/cache/clear').then((response) => response.data),
  healthCheck: () => api.get('/api/health').then((response) => response.data),
};

export const conversationsService = {
  list: () =>
    api.get('/api/conversations').then((response) => response.data),
  create: (title) =>
    api
      .post('/api/conversations', { title })
      .then((response) => response.data),
  get: (id) =>
    api.get(`/api/conversations/${id}`).then((response) => response.data),
  remove: (id) =>
    api.delete(`/api/conversations/${id}`).then((response) => response.data),
};

// SSE client for /api/dynamic-agent/turn/stream. Each pipeline step the
// backend emits arrives as a `status` event so the UI can replace the
// generic "Thinking…" with a real label ("Identifying tool…", "Loading
// github docs…", "Running action…"). Also fixes 504s on deploys behind
// ALB / CloudFront / nginx: the per-step bytes + 15-s keepalive comments
// keep the proxy from dropping the connection mid-Ollama-call.
async function streamDynamicAgentTurn({
  prompt,
  language = 'en',
  onStatus,
  onDone,
  onError,
}) {
  const token = localStorage.getItem('token');
  const response = await fetch(`${API_BASE_URL}/api/dynamic-agent/turn/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ prompt, language }),
  });

  if (!response.ok || !response.body) {
    const text = await response.text().catch(() => '');
    throw new Error(text || `HTTP ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let sep;
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const raw = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      // SSE comment lines (heartbeats) start with ":" and have no `data:`
      // payload — they exist purely to keep the proxy connection alive.
      if (!raw || raw.startsWith(':')) continue;
      let event = 'message';
      const dataLines = [];
      for (const line of raw.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
      }
      if (!dataLines.length) continue;
      let payload;
      try {
        payload = JSON.parse(dataLines.join('\n'));
      } catch {
        payload = dataLines.join('\n');
      }
      if (event === 'status') {
        onStatus?.(payload);
      } else if (event === 'done') {
        onDone?.(payload);
        return payload;
      } else if (event === 'error') {
        const err = new Error(payload?.error || 'agent pipeline error');
        onError?.(err);
        throw err;
      }
    }
  }
  throw new Error('Agent stream closed before completion');
}

// SSE client for /api/dynamic-agent/tools/refresh/stream. Emits `status`
// events per pipeline stage (searching_web, web_results, openapi_parsed,
// enriching, llm_extracting, saved) so the user sees what's happening
// during a slow web extraction. Calls `onStatus({step, ...data})` for each
// status event, `onDone(toolSummary)` on success, `onError(err)` on failure.
async function streamRefreshTool({ tool, onStatus, onDone, onError }) {
  const token = localStorage.getItem('token');
  const response = await fetch(
    `${API_BASE_URL}/api/dynamic-agent/tools/refresh/stream`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ tool }),
    }
  );

  if (!response.ok || !response.body) {
    const text = await response.text().catch(() => '');
    throw new Error(text || `HTTP ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let sep;
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const raw = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      // SSE comment lines (heartbeats) start with ":" — ignore.
      if (!raw || raw.startsWith(':')) continue;
      let event = 'message';
      const dataLines = [];
      for (const line of raw.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
      }
      if (!dataLines.length) continue;
      let payload;
      try {
        payload = JSON.parse(dataLines.join('\n'));
      } catch {
        payload = dataLines.join('\n');
      }
      if (event === 'status') {
        onStatus?.(payload);
      } else if (event === 'done') {
        onDone?.(payload);
        return payload;
      } else if (event === 'error') {
        const err = new Error(payload?.error || 'refresh pipeline error');
        onError?.(err);
        throw err;
      }
    }
  }
  throw new Error('Refresh stream closed before completion');
}

// Dynamic Agent — Nango-free, runs entirely on the local LLM + raw HTTP.
export const dynamicAgentService = {
  turn: (prompt, language = 'en') =>
    api
      .post('/api/dynamic-agent/turn', { prompt, language })
      .then((r) => r.data),
  streamTurn: streamDynamicAgentTurn,
  submitCredentials: (tool, credentials) =>
    api
      .post('/api/dynamic-agent/credentials', { tool, credentials })
      .then((r) => r.data),
  listConnections: () =>
    api.get('/api/dynamic-agent/connections').then((r) => r.data),
  deleteConnection: (id) =>
    api.delete(`/api/dynamic-agent/connections/${id}`).then((r) => r.data),
  listTools: () => api.get('/api/dynamic-agent/tools').then((r) => r.data),
  getTool: (name) =>
    api.get(`/api/dynamic-agent/tools/${name}`).then((r) => r.data),
  refreshTool: (tool) =>
    api
      .post('/api/dynamic-agent/tools/refresh', { tool })
      .then((r) => r.data),
  streamRefreshTool: streamRefreshTool,
  listLogs: (limit = 50) =>
    api
      .get('/api/dynamic-agent/logs', { params: { limit } })
      .then((r) => r.data),
  getSavings: () =>
    api.get('/api/dynamic-agent/savings').then((r) => r.data),
  getOAuthAuthorizeUrl: (toolName) => {
    const token = localStorage.getItem('token');
    const base = `${API_BASE_URL}/api/dynamic-agent/oauth/authorize/${encodeURIComponent(toolName)}`;
    return token ? `${base}?token=${encodeURIComponent(token)}` : base;
  },
};
