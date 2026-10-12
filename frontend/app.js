const API_BASE = window.location.origin;
const WS_BASE = API_BASE.replace(/^http/, "ws");
const CONFIG = window.__KEFU_CONFIG__ || { wsPath: "/api/v1/ws/chat" };
const API_KEY_STORAGE = "kefu_api_key";
// 安全：服务端不再通过 /config.js 下发 API Key，
// 改由用户在本机手动填写并保存到 localStorage，避免密钥暴露给站点访问者。
function getApiKey() {
  return localStorage.getItem(API_KEY_STORAGE) || CONFIG.apiKey || "";
}
function setApiKey(key) {
  localStorage.setItem(API_KEY_STORAGE, key);
}

const SESSION_STORAGE_KEY = "kefu_session_id";
const CS_PROFILE_KEY = "kefu_profile_id";
let currentProfile = localStorage.getItem(CS_PROFILE_KEY) || "c1";

const CS_PROFILE_META = {
  c1: {
    welcome: "您好，有什么可以帮您？",
    subtitle: "标准客服 · 跨境购物 · 物流查询 · 退换货",
  },
  c2: {
    welcome: "你好呀～我是您的专属导购",
    subtitle: "热情导购 · 帮您挑好商品 · 多语言支持",
  },
  c3: {
    welcome: "您好，售后专线为您服务",
    subtitle: "严谨专员 · 退换货政策 · 质保咨询",
  },
};

function applyProfileUI() {
  const meta = CS_PROFILE_META[currentProfile] || CS_PROFILE_META.c1;
  const w = document.getElementById("chatWelcome");
  const s = document.getElementById("chatSubtitle");
  if (w) w.textContent = meta.welcome;
  if (s) s.textContent = meta.subtitle;
  document.querySelectorAll(".cs-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.profile === currentProfile);
  });
}

function initProfileSwitcher() {
  document.querySelectorAll(".cs-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      currentProfile = btn.dataset.profile || "c1";
      localStorage.setItem(CS_PROFILE_KEY, currentProfile);
      applyProfileUI();
    });
  });
  applyProfileUI();
}

const HISTORY_STORAGE_KEY = "kefu_session_history";
const MAX_HISTORY = 30;

let sessionId = localStorage.getItem(SESSION_STORAGE_KEY);
let ws = null;
let isConnected = false;
let connState = "connecting";
let authToken = localStorage.getItem("kefu_token") || "";
let currentUser = null;
let lastUserMessage = "";

const messagesEl = document.getElementById("messages");
const inputEl = document.getElementById("input");
const sendBtn = document.getElementById("send");
const newSessionBtn = document.getElementById("newSession");
const sessionInfoEl = document.getElementById("sessionInfo");
const sessionListEl = document.getElementById("sessionList");
const authStatusEl = document.getElementById("authStatus");
const loginEmailEl = document.getElementById("loginEmail");
const loginBtn = document.getElementById("loginBtn");
const logoutBtn = document.getElementById("logoutBtn");
const ordersPanelEl = document.getElementById("ordersPanel");
const ordersListEl = document.getElementById("ordersList");
const connStatusEl = document.getElementById("connStatus");
const quickPromptsEl = document.getElementById("quickPrompts");

function formatToolLabel(name) {
  return typeof getToolLabel === "function" ? getToolLabel(name) : name;
}

function refreshHandoffBannerI18n() {
  const banner = document.getElementById("handoffBanner");
  if (!banner) return;
  const status = banner.dataset.status || "waiting";
  banner.textContent =
    status === "active" ? t("handoffActive") : t("handoffWaiting");
}

function refreshVisibleChromeI18n() {
  document.querySelectorAll(".agent-tag").forEach((el) => {
    el.textContent = t("agentLabel");
  });
  document.querySelectorAll(".tools-badge[data-tools]").forEach((wrap) => {
    let tools = [];
    try {
      tools = JSON.parse(wrap.dataset.tools || "[]");
    } catch {
      tools = [];
    }
    wrap.textContent = `${t("toolsUsed")}: `;
    tools.forEach((name) => {
      const tag = document.createElement("span");
      tag.className = "tool-tag";
      tag.textContent = formatToolLabel(name);
      wrap.appendChild(tag);
    });
  });
  document.querySelectorAll(".citations li").forEach((li) => {
    const raw = li.dataset.citation || li.textContent.replace(/^[^:]+:\s*/, "");
    li.dataset.citation = raw;
    li.textContent = `${t("ref")}: ${raw}`;
  });
  document.querySelectorAll(".thinking-indicator").forEach((el) => {
    const phase = el.closest(".message")?.dataset.thinkingPhase || "thinking";
    const label = el.querySelector(".thinking-label");
    if (label) {
      label.textContent = phase === "searching" ? t("thinkingSearch") : t("thinking");
    }
  });
}

const HANDOFF_POLL_MS = 2500;
let handoffPollTimer = null;
let lastMessageId = null;
let humanMode = false;

function authHeaders() {
  const headers = { "Content-Type": "application/json" };
  const key = getApiKey(); if (key) headers["X-API-Key"] = key;
  if (authToken) headers["Authorization"] = `Bearer ${authToken}`;
  return headers;
}

function updateConnStatus() {
  if (!connStatusEl) return;
  const labels = {
    connected: t("connConnected"),
    connecting: t("connConnecting"),
    disconnected: t("connDisconnected"),
  };
  connStatusEl.textContent = labels[connState] || connState;
  connStatusEl.dataset.state = connState;
}

function getSessionHistory() {
  try {
    const raw = localStorage.getItem(HISTORY_STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveSessionHistory(history) {
  localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(history.slice(0, MAX_HISTORY)));
}

function upsertSessionHistory(id, title) {
  if (!id) return;
  const preview = (title || "").trim().slice(0, 40) || id.slice(0, 8);
  const history = getSessionHistory().filter((item) => item.id !== id);
  history.unshift({ id, title: preview, updatedAt: Date.now() });
  saveSessionHistory(history);
  renderSessionList();
}

function persistSessionId(id) {
  sessionId = id;
  if (id) {
    localStorage.setItem(SESSION_STORAGE_KEY, id);
  } else {
    localStorage.removeItem(SESSION_STORAGE_KEY);
  }
  if (sessionInfoEl) {
    sessionInfoEl.textContent = id ? `${t("session")}: ${id}` : "";
  }
  renderSessionList();
}

function removeSessionFromHistory(id) {
  const history = getSessionHistory().filter((item) => item.id !== id);
  saveSessionHistory(history);
  if (sessionId === id) {
    persistSessionId(null);
    clearMessages();
  }
  renderSessionList();
}

async function deleteSession(id, event) {
  if (event) {
    event.stopPropagation();
    event.preventDefault();
  }
  if (!window.confirm(t("confirmDeleteSession"))) return;

  try {
    const resp = await fetch(`${API_BASE}/api/v1/sessions/${id}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      throw new Error(data.detail || resp.statusText);
    }
  } catch (e) {
    console.warn("deleteSession failed", e);
  }
  removeSessionFromHistory(id);
}

function renderSessionList() {
  if (!sessionListEl) return;
  const history = getSessionHistory();
  sessionListEl.innerHTML = "";

  if (history.length === 0) {
    const empty = document.createElement("li");
    empty.className = "session-list-empty";
    empty.textContent = t("noHistory");
    sessionListEl.appendChild(empty);
    return;
  }

  history.forEach((item) => {
    const li = document.createElement("li");
    li.className = "session-list-item";

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `session-open-btn${item.id === sessionId ? " active" : ""}`;
    btn.innerHTML = `
      <span class="session-preview">${escapeHtml(item.title)}</span>
      <span class="session-id">${escapeHtml(item.id.slice(0, 8))}…</span>
    `;
    btn.addEventListener("click", () => loadSession(item.id));

    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "session-delete-btn";
    delBtn.title = t("deleteSession");
    delBtn.setAttribute("aria-label", t("deleteSession"));
    delBtn.textContent = "×";
    delBtn.addEventListener("click", (e) => deleteSession(item.id, e));

    li.appendChild(btn);
    li.appendChild(delBtn);
    sessionListEl.appendChild(li);
  });
}

function renderQuickPrompts() {
  if (!quickPromptsEl) return;
  quickPromptsEl.innerHTML = "";
  const label = document.createElement("span");
  label.className = "quick-label";
  label.textContent = t("quickPrompts");
  quickPromptsEl.appendChild(label);

  getPrompts().forEach((p) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "quick-btn";
    btn.textContent = p.label;
    btn.title = p.text;
    btn.addEventListener("click", () => {
      if (inputEl) {
        inputEl.value = p.text;
        inputEl.focus();
      }
    });
    quickPromptsEl.appendChild(btn);
  });
}

async function loadOrders() {
  if (!ordersPanelEl || !ordersListEl) return;
  if (!currentUser || !authToken) {
    ordersPanelEl.hidden = true;
    return;
  }
  ordersPanelEl.hidden = false;
  ordersListEl.innerHTML = `<li class="orders-loading">…</li>`;
  try {
    const resp = await fetch(`${API_BASE}/api/v1/users/me/orders`, {
      headers: authHeaders(),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || resp.statusText);
    const orders = data.data?.orders || [];
    ordersListEl.innerHTML = "";
    if (orders.length === 0) {
      ordersListEl.innerHTML = `<li class="orders-empty">${t("noOrders")}</li>`;
      return;
    }
    orders.forEach((o) => {
      const li = document.createElement("li");
      li.className = "order-item";
      li.innerHTML = `
        <span class="order-id">${escapeHtml(o.order_id || "")}</span>
        <span class="order-status">${escapeHtml(o.status || "")}</span>
        <span class="order-meta">${escapeHtml(o.carrier || "")} ${escapeHtml(o.tracking_number || "")}</span>
      `;
      li.addEventListener("click", () => {
        if (inputEl) {
          inputEl.value = `查询订单 ${o.order_id} 的物流信息`;
          inputEl.focus();
        }
      });
      ordersListEl.appendChild(li);
    });
  } catch {
    ordersListEl.innerHTML = `<li class="orders-empty">${t("ordersLoadFailed")}</li>`;
  }
}

function clearMessages() {
  if (messagesEl) messagesEl.innerHTML = "";
}

function stopHandoffPoll() {
  if (handoffPollTimer) {
    clearInterval(handoffPollTimer);
    handoffPollTimer = null;
  }
}

function setHandoffBanner(status) {
  let banner = document.getElementById("handoffBanner");
  if (!status) {
    if (banner) banner.remove();
    return;
  }
  if (!banner) {
    banner = document.createElement("div");
    banner.id = "handoffBanner";
    banner.className = "handoff-banner";
    const header = document.querySelector(".chat-header");
    if (header) header.insertAdjacentElement("afterend", banner);
    else messagesEl?.parentElement?.insertBefore(banner, messagesEl);
  }
  banner.dataset.status = status;
  banner.textContent =
    status === "active" ? t("handoffActive") : t("handoffWaiting");
}

function startHandoffPoll() {
  if (!sessionId || handoffPollTimer) return;
  humanMode = true;
  setHandoffBanner("waiting");
  handoffPollTimer = setInterval(pollHandoff, HANDOFF_POLL_MS);
  pollHandoff();
}

async function pollHandoff() {
  if (!sessionId) return;
  try {
    const qs = lastMessageId
      ? `?after_message_id=${encodeURIComponent(lastMessageId)}`
      : "";
    const resp = await fetch(
      `${API_BASE}/api/v1/handoffs/session/${sessionId}${qs}`,
      { headers: authHeaders() }
    );
    if (!resp.ok) return;
    const data = await resp.json();
    humanMode = !!data.human_mode;
    if (data.handoff?.status === "active") {
      setHandoffBanner("active");
    } else if (data.human_mode) {
      setHandoffBanner("waiting");
    }

    const msgs = data.agent_messages || [];
    msgs.forEach((m) => {
      if (!m.content) return;
      appendMessage("agent", m.content);
      lastMessageId = m.id;
    });

    if (!data.human_mode) {
      stopHandoffPoll();
      setHandoffBanner(null);
    }
  } catch (e) {
    console.warn("handoff poll failed", e);
  }
}

function trackLastMessageId(messages) {
  if (!messages || !messages.length) return;
  lastMessageId = messages[messages.length - 1].id || lastMessageId;
}

function renderMessages(messages) {
  clearMessages();
  messages.forEach((m) => {
    if (m.role === "user" || m.role === "assistant" || m.role === "agent") {
      appendMessage(m.role, m.content || "", m.citations || [], m.tools_used || []);
    }
  });
  trackLastMessageId(messages);
}

async function loadSession(id) {
  if (!id) return;
  stopHandoffPoll();
  setHandoffBanner(null);
  humanMode = false;
  try {
    const resp = await fetch(`${API_BASE}/api/v1/sessions/${id}`, {
      headers: authHeaders(),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || resp.statusText);
    persistSessionId(id);
    renderMessages(data.messages || []);
    const firstUser = (data.messages || []).find((m) => m.role === "user");
    upsertSessionHistory(id, firstUser?.content || id);
    if (data.handoff || data.status === "waiting_human" || data.status === "human_active") {
      startHandoffPoll();
      if (data.status === "human_active") setHandoffBanner("active");
    }
  } catch (e) {
    removeSessionFromHistory(id);
    renderSessionList();
    console.warn("loadSession failed", e);
  }
}

function updateAuthUI() {
  if (!authStatusEl) return;
  if (currentUser) {
    authStatusEl.textContent = `${t("loggedInAs")}: ${currentUser.email}`;
    if (loginBtn) loginBtn.hidden = true;
    if (logoutBtn) logoutBtn.hidden = false;
    if (loginEmailEl) loginEmailEl.hidden = true;
  } else {
    authStatusEl.textContent = t("notLoggedIn");
    if (loginBtn) loginBtn.hidden = false;
    if (logoutBtn) logoutBtn.hidden = true;
    if (loginEmailEl) loginEmailEl.hidden = false;
    if (ordersPanelEl) ordersPanelEl.hidden = true;
  }
}

async function fetchMe() {
  try {
    const resp = await fetch(`${API_BASE}/api/v1/auth/me`, { headers: authHeaders() });
    const data = await resp.json();
    currentUser = data.authenticated ? data.user : null;
  } catch {
    currentUser = null;
  }
  updateAuthUI();
  await loadOrders();
}

async function login() {
  const email = (loginEmailEl?.value || "").trim();
  if (!email) return;
  try {
    const resp = await fetch(`${API_BASE}/api/v1/auth/login`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ email, name: email.split("@")[0] }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || resp.statusText);
    authToken = data.access_token;
    localStorage.setItem("kefu_token", authToken);
    currentUser = data.user;
    updateAuthUI();
    await loadOrders();
    if (ws) {
      ws.close();
      ws = null;
    }
    connectWebSocket();
  } catch (e) {
    alert(`${t("error")}: ${e.message}`);
  }
}

async function logout() {
  try {
    await fetch(`${API_BASE}/api/v1/auth/logout`, { method: "POST", headers: authHeaders() });
  } catch {
    /* ignore */
  }
  authToken = "";
  localStorage.removeItem("kefu_token");
  currentUser = null;
  updateAuthUI();
  if (ws) {
    ws.close();
    ws = null;
  }
  connectWebSocket();
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function sanitizeAssistantContent(text) {
  if (!text) return "";
  let s = String(text);
  s = s.replace(/`[\s\S]*?`/gi, "");
  s = s.replace(/`[\s\S]*?`/gi, "");
  s = s.replace(/<think>[\s\S]*?<\/redacted_thinking>/gi, "");
  s = s.replace(/<think[\s\S]*?<\/redacted_thinking>/gi, "");
  s = s.replace(/<think[\s\S]*?<\/think>/gi, "");
  s = s.replace(/`[\s\S]*$/i, "");
  s = s.replace(/<think>[\s\S]*$/i, "");
  s = s.replace(/<think[\s\S]*$/i, "");
  const leak = s.search(/\n(?:user|assistant)\s*(?:\n|$)/i);
  if (leak >= 0) s = s.slice(0, leak);
  const chatml = s.search(/<\|im_start\|>(?:user|assistant)\b/i);
  if (chatml >= 0) s = s.slice(0, chatml);
  // Strip common Markdown so chat shows plain text
  s = s.replace(/```[\w+-]*\n?([\s\S]*?)```/g, "$1");
  s = s.replace(/`([^`]+)`/g, "$1");
  s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, "$1");
  s = s.replace(/^\s{0,3}#{1,6}\s+/gm, "");
  s = s.replace(/(\*\*|__)(.+?)\1/g, "$2");
  s = s.replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, "$1");
  s = s.replace(/^\s{0,3}(?:[-*+]|\d+\.)\s+/gm, "");
  return s.trim();
}

function formatMessageContent(text, role = "user") {
  const clean = role === "assistant" ? sanitizeAssistantContent(text) : text;
  return escapeHtml(clean).replace(/\n/g, "<br>");
}

function buildWsUrl() {
  const base = `${WS_BASE}${CONFIG.wsPath}`;
  const params = new URLSearchParams();
  const key = getApiKey(); if (key) params.set("api_key", key);
  if (authToken) params.set("token", authToken);
  const qs = params.toString();
  return qs ? `${base}?${qs}` : base;
}

function connectWebSocket() {
  if (ws && ws.readyState === WebSocket.OPEN) return;
  if (ws && ws.readyState === WebSocket.CONNECTING) return;

  connState = "connecting";
  updateConnStatus();
  ws = new WebSocket(buildWsUrl());

  ws.onopen = () => {
    isConnected = true;
    connState = "connected";
    updateConnStatus();
    if (sendBtn) sendBtn.disabled = false;
  };

  ws.onmessage = (event) => {
    handleWsMessage(JSON.parse(event.data));
  };

  ws.onclose = () => {
    isConnected = false;
    connState = "disconnected";
    updateConnStatus();
    if (sendBtn && !pendingAssistantEl) sendBtn.disabled = false;
    setTimeout(connectWebSocket, 3000);
  };

  ws.onerror = () => {
    isConnected = false;
    connState = "disconnected";
    updateConnStatus();
  };
}

function appendToolsBadge(parent, tools) {
  if (!tools || tools.length === 0) return;
  const wrap = document.createElement("div");
  wrap.className = "tools-badge";
  wrap.dataset.tools = JSON.stringify(tools);
  wrap.textContent = `${t("toolsUsed")}: `;
  tools.forEach((name) => {
    const tag = document.createElement("span");
    tag.className = "tool-tag";
    tag.textContent = formatToolLabel(name);
    wrap.appendChild(tag);
  });
  parent.appendChild(wrap);
}

function appendCitations(parent, citations) {
  if (!citations || citations.length === 0) return;
  const ul = document.createElement("ul");
  ul.className = "citations";
  citations.forEach((c) => {
    const li = document.createElement("li");
    li.dataset.citation = c;
    li.textContent = `${t("ref")}: ${c}`;
    ul.appendChild(li);
  });
  parent.appendChild(ul);
}

function appendMessage(role, content, citations = [], toolsUsed = []) {
  const div = document.createElement("div");
  const displayRole = role === "agent" ? "assistant agent" : role;
  div.className = `message ${displayRole}`;

  if (role === "agent") {
    const tag = document.createElement("div");
    tag.className = "agent-tag";
    tag.textContent = t("agentLabel");
    div.appendChild(tag);
  }

  const body = document.createElement("div");
  body.className = "message-body";
  body.innerHTML = formatMessageContent(content, role === "agent" ? "assistant" : role);
  div.appendChild(body);
  if (role === "assistant") appendToolsBadge(div, toolsUsed);
  appendCitations(div, citations);

  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return div;
}

let pendingAssistantEl = null;

function buildThinkingHtml(phase = "thinking") {
  const label = phase === "searching" ? t("thinkingSearch") : t("thinking");
  return (
    `<div class="thinking-indicator" role="status" aria-live="polite">` +
    `<span class="thinking-spinner" aria-hidden="true"></span>` +
    `<span class="thinking-label">${escapeHtml(label)}</span>` +
    `<span class="thinking-dots" aria-hidden="true"><span></span><span></span><span></span></span>` +
    `</div>`
  );
}

function showThinkingIndicator(el, phase = "thinking") {
  if (!el) return;
  el.classList.add("typing", "is-thinking");
  el.dataset.thinkingPhase = phase;
  const body = el.querySelector(".message-body");
  if (body) body.innerHTML = buildThinkingHtml(phase);
}

function clearThinkingIndicator(el) {
  if (!el) return;
  el.classList.remove("is-thinking");
  delete el.dataset.thinkingPhase;
}

function handleWsMessage(data) {
  if (data.type === "session") {
    persistSessionId(data.session_id);
    upsertSessionHistory(data.session_id, lastUserMessage);
  } else if (data.type === "handoff") {
    startHandoffPoll();
    if (data.session_status === "human_active") setHandoffBanner("active");
  } else if (data.type === "status" && pendingAssistantEl) {
    showThinkingIndicator(pendingAssistantEl, data.phase || "thinking");
  } else if (data.type === "chunk" && pendingAssistantEl) {
    clearThinkingIndicator(pendingAssistantEl);
    const current = pendingAssistantEl.dataset.full || "";
    const full = current + data.content;
    pendingAssistantEl.dataset.full = full;
    const body = pendingAssistantEl.querySelector(".message-body");
    if (body) {
      body.innerHTML = formatMessageContent(full, "assistant");
    }
    messagesEl.scrollTop = messagesEl.scrollHeight;
  } else if (data.type === "done") {
    persistSessionId(data.session_id);
    upsertSessionHistory(data.session_id, lastUserMessage);
    if (data.handoff || (data.tools_used || []).includes("request_human_agent")) {
      startHandoffPoll();
    }
    if (data.silent && pendingAssistantEl) {
      pendingAssistantEl.remove();
      pendingAssistantEl = null;
      if (sendBtn) sendBtn.disabled = false;
      return;
    }
    if (pendingAssistantEl) {
      pendingAssistantEl.classList.remove("typing");
      clearThinkingIndicator(pendingAssistantEl);
      const body = pendingAssistantEl.querySelector(".message-body");
      if (body) {
        body.innerHTML = formatMessageContent(data.answer || "", "assistant");
      }
      const tools = data.tools_used?.length
        ? data.tools_used
        : data.tool_name
          ? [data.tool_name]
          : [];
      appendToolsBadge(pendingAssistantEl, tools);
      appendCitations(pendingAssistantEl, data.citations);
      pendingAssistantEl = null;
    }
    if (sendBtn) sendBtn.disabled = false;
  } else if (data.type === "error" && pendingAssistantEl) {
    pendingAssistantEl.classList.remove("typing");
    clearThinkingIndicator(pendingAssistantEl);
    const body = pendingAssistantEl.querySelector(".message-body");
    if (body) {
      body.textContent = `${t("error")}: ${data.error || "Unknown error"}`;
    }
    pendingAssistantEl = null;
    if (sendBtn) sendBtn.disabled = false;
  }
}

async function sendMessage() {
  const message = inputEl.value.trim();
  if (!message) return;

  lastUserMessage = message;
  inputEl.value = "";
  sendBtn.disabled = true;
  appendMessage("user", message);

  pendingAssistantEl = appendMessage("assistant", "");
  showThinkingIndicator(pendingAssistantEl, "thinking");
  pendingAssistantEl.dataset.full = "";

  if (isConnected && ws) {
    ws.send(JSON.stringify({ message, session_id: sessionId, profile_id: currentProfile }));
  } else {
    try {
      const resp = await fetch(`${API_BASE}/api/v1/chat`, {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({ message, session_id: sessionId, profile_id: currentProfile }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || resp.statusText);
      persistSessionId(data.session_id);
      upsertSessionHistory(data.session_id, message);
      if (data.handoff || (data.tools_used || []).includes("request_human_agent")) {
        startHandoffPoll();
      }
      if (data.silent) {
        if (pendingAssistantEl) {
          pendingAssistantEl.remove();
          pendingAssistantEl = null;
        }
        sendBtn.disabled = false;
        return;
      }
      if (pendingAssistantEl) {
        pendingAssistantEl.classList.remove("typing");
        clearThinkingIndicator(pendingAssistantEl);
        pendingAssistantEl.remove();
        pendingAssistantEl = null;
      }
      const tools = data.tools_used?.length
        ? data.tools_used
        : data.tool_name
          ? [data.tool_name]
          : [];
      appendMessage("assistant", data.answer, data.citations, tools);
    } catch (e) {
      if (pendingAssistantEl) {
        pendingAssistantEl.classList.remove("typing");
        clearThinkingIndicator(pendingAssistantEl);
        const body = pendingAssistantEl.querySelector(".message-body");
        if (body) {
          body.textContent = `${t("requestFailed")}: ${e.message}`;
        }
        pendingAssistantEl = null;
      }
    }
    sendBtn.disabled = false;
  }
}

function startNewSession() {
  stopHandoffPoll();
  setHandoffBanner(null);
  humanMode = false;
  lastMessageId = null;
  persistSessionId(null);
  clearMessages();
  lastUserMessage = "";
  if (ws) {
    ws.close();
    ws = null;
  }
  connectWebSocket();
}

if (newSessionBtn) {
  newSessionBtn.addEventListener("click", startNewSession);
}

if (loginBtn) loginBtn.addEventListener("click", login);
if (logoutBtn) logoutBtn.addEventListener("click", logout);
if (loginEmailEl) {
  loginEmailEl.value = "demo@gulf.ae";
  loginEmailEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter") login();
  });
}

if (sendBtn) {
  sendBtn.addEventListener("click", sendMessage);
}
if (inputEl) {
  inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
}

async function initApp() {
  renderSessionList();
  renderQuickPrompts();
  updateConnStatus();
  initProfileSwitcher();
  await fetchMe();
  if (sessionId) {
    await loadSession(sessionId);
  }
  connectWebSocket();
}

// API Key 本地配置（安全改造：不再从服务端下发）
(function initApiKeyInput() {
  const input = document.getElementById("apiKeyInput");
  const btn = document.getElementById("saveKeyBtn");
  if (!input || !btn) return;
  input.value = getApiKey();
  btn.addEventListener("click", () => {
    setApiKey((input.value || "").trim());
    if (ws) { ws.close(); ws = null; }
    connectWebSocket();
  });
})();

initLanguageSwitcher();
initApp();
