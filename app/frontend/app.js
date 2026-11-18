/* ============================================================
   星海优选 · 智能客服前端
   ============================================================ */
const API = "/api/v1";
const TOKEN_KEY = "cs_token";
const USER_KEY = "cs_user";

const state = {
  token: localStorage.getItem(TOKEN_KEY) || "",
  user: JSON.parse(localStorage.getItem(USER_KEY) || "null"),
  threadId: "t_" + Date.now(),
  threads: [],
  streaming: false,
  ws: null,
};

const $ = (id) => document.getElementById(id);

const INTENT_LABELS = {
  ORDER: "订单查询",
  LOGISTICS: "物流跟踪",
  REFUND: "售后办理",
  REFUND_STATUS: "退款进度",
  INVOICE: "发票服务",
  POLICY: "政策咨询",
  PRODUCT: "商品咨询",
  HUMAN: "转人工",
  OTHER: "综合咨询",
};

/* ---------------- 基础工具 ---------------- */
function toast(message, kind = "") {
  const el = document.createElement("div");
  el.className = "toast " + kind;
  el.textContent = message;
  $("toastWrap").appendChild(el);
  setTimeout(() => el.remove(), 3200);
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderMarkdown(text) {
  let s = escapeHtml(text);
  s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
  s = s.replace(/^\s*[-·]\s+/gm, "· ");
  return s;
}

async function api(path, options = {}) {
  const headers = Object.assign({}, options.headers || {});
  if (state.token) headers["Authorization"] = "Bearer " + state.token;
  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    if (typeof options.body !== "string") options.body = JSON.stringify(options.body);
  }
  const res = await fetch(API + path, { ...options, headers });
  if (res.status === 401) {
    logout();
    throw new Error("登录已过期，请重新登录");
  }
  if (!res.ok) {
    let detail = "请求失败";
    try {
      const data = await res.json();
      detail = data.detail || detail;
    } catch (e) {}
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

/* ---------------- 登录 ---------------- */
$("loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = $("loginBtn");
  $("loginError").textContent = "";
  btn.disabled = true;
  btn.textContent = "登录中…";
  try {
    const data = await api("/auth/login", {
      method: "POST",
      body: {
        username: $("username").value.trim(),
        password: $("password").value,
      },
    });
    state.token = data.token;
    state.user = data.user;
    localStorage.setItem(TOKEN_KEY, data.token);
    localStorage.setItem(USER_KEY, JSON.stringify(data.user));
    enterApp();
  } catch (err) {
    $("loginError").textContent = err.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "进入工作台";
  }
});

document.querySelectorAll(".demo-chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    $("username").value = chip.dataset.u;
    $("password").value = chip.dataset.p;
    $("loginError").textContent = "";
  });
});

function logout() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  state.token = "";
  state.user = null;
  if (state.ws) {
    try { state.ws.close(); } catch (e) {}
    state.ws = null;
  }
  $("appView").classList.add("hidden");
  $("loginView").classList.remove("hidden");
}

$("logoutBtn").addEventListener("click", logout);

/* ---------------- 初始化 ---------------- */
function enterApp() {
  $("loginView").classList.add("hidden");
  $("appView").classList.remove("hidden");
  const u = state.user || {};
  $("userName").textContent = u.full_name || u.username || "客服";
  $("userMeta").textContent = u.member_level || "普通会员";
  $("userAvatar").textContent = (u.full_name || u.username || "客").slice(0, 1);
  $("adminLink").style.display = u.is_admin ? "" : "none";

  newThread(false);
  loadThreads();
  loadStats();
  connectWs();
}

async function loadStats() {
  try {
    const health = await fetch("/health").then((r) => r.json());
    $("kbCount").textContent = health.kb_chunks ?? "-";
    $("statChunks").textContent = health.kb_chunks ?? "-";
    $("modelChip").textContent = health.llm === "deepseek-v4-pro" ? "DeepSeek Pro" : "DeepSeek Flash";
    $("statDocs").textContent = health.kb_docs ?? "-";
  } catch (e) {}
}

/* ---------------- 会话列表 ---------------- */
async function loadThreads() {
  try {
    const list = await api("/chat/threads");
    state.threads = list;
    renderThreads();
  } catch (e) {}
}

function renderThreads() {
  const box = $("threadList");
  $("threadCount").textContent = state.threads.length ? state.threads.length + " 个" : "";
  if (!state.threads.length) {
    box.innerHTML = '<div class="thread-empty">还没有会话<br />点击上方按钮开始咨询</div>';
    return;
  }
  box.innerHTML = state.threads
    .map(
      (t) => `
      <div class="thread-item ${t.thread_id === state.threadId ? "active" : ""}" data-id="${escapeHtml(t.thread_id)}">
        <div class="tt">${escapeHtml(t.title || "新会话")}</div>
        <div class="tp">${escapeHtml(t.preview || t.updated_at)}</div>
      </div>`
    )
    .join("");
  box.querySelectorAll(".thread-item").forEach((el) => {
    el.addEventListener("click", () => openThread(el.dataset.id));
  });
}

function newThread(refresh = true) {
  state.threadId = "t_" + Date.now();
  $("messages").innerHTML = "";
  resetTrace();
  $("suggestRow").classList.add("hidden");
  showWelcome();
  if (refresh) {
    renderThreads();
    $("input").focus();
  }
}

$("newChatBtn").addEventListener("click", () => newThread());
$("clearBtn").addEventListener("click", () => newThread());

function showWelcome() {
  const wrap = document.createElement("div");
  wrap.className = "welcome";
  wrap.id = "welcome";
  wrap.innerHTML = `
    <div class="wm">星</div>
    <h2>你好，我是小星</h2>
    <p>可以帮你查订单、跟物流、办退货、开发票，也能解答平台的各项规则。想问点什么？</p>
    <div class="welcome-grid">
      <div class="wcard" data-q="查一下我的订单"><div class="wt">📦 订单查询</div><div class="wd">「查一下我的订单」直接读取你的最新订单</div></div>
      <div class="wcard" data-q="内衣拆封了还能退吗？"><div class="wt">📋 政策咨询</div><div class="wd">检索私有知识库，回答口径与平台政策一致</div></div>
      <div class="wcard" data-q="我要退货，订单号 SN20241115003，尺码不合适"><div class="wt">↩️ 售后办理</div><div class="wd">高额退款自动转人工，体验完整审核流</div></div>
      <div class="wcard" data-q="帮我查下发票开好了没"><div class="wt">🧾 发票服务</div><div class="wd">查询开票状态与可开票金额</div></div>
    </div>`;
  $("messages").appendChild(wrap);
  bindWelcomeCards(wrap);
}

function bindWelcomeCards(root) {
  root.querySelectorAll(".wcard").forEach((card) => {
    card.addEventListener("click", () => {
      $("input").value = card.dataset.q;
      send();
    });
  });
}

async function openThread(threadId) {
  if (state.streaming) return;
  state.threadId = threadId;
  renderThreads();
  $("messages").innerHTML = "";
  resetTrace();
  try {
    const msgs = await api(`/chat/threads/${encodeURIComponent(threadId)}/messages`);
    msgs.forEach((m) => {
      if (m.role === "user") {
        appendUser(m.content);
      } else if (m.role === "system") {
        appendSystem(m.content);
      } else {
        const node = appendAssistant(INTENT_LABELS[m.intent] || m.intent);
        setBubble(node, m.content);
        if (m.sources && m.sources.length) attachSources(node, m.sources);
        if (m.extra && m.extra.card) node.cards.appendChild(renderCard(m.extra.card));
        if (m.extra && m.extra.awaiting) updateTrace(m.intent, "等待订单号", true);
      }
    });
    scrollBottom();
    const lastIntent = [...msgs].reverse().find((m) => m.role === "assistant" && m.intent);
    if (lastIntent) updateTrace(INTENT_LABELS[lastIntent.intent] || lastIntent.intent, null, true);
  } catch (e) {
    toast(e.message, "err");
  }
}

/* ---------------- 消息渲染 ---------------- */
function clearEmptyState() {
  const w = $("welcome");
  if (w) w.remove();
}

function appendUser(text) {
  clearEmptyState();
  const row = document.createElement("div");
  row.className = "msg-row user";
  row.innerHTML = `
    <div class="msg-avatar me">${escapeHtml((state.user?.full_name || "我").slice(0, 1))}</div>
    <div class="msg-body">
      <div class="msg-meta"><span>${nowTime()}</span></div>
      <div class="bubble">${renderMarkdown(text)}</div>
    </div>`;
  $("messages").appendChild(row);
  scrollBottom();
  return row;
}

function appendAssistant(intentLabel) {
  const row = document.createElement("div");
  row.className = "msg-row";
  row.innerHTML = `
    <div class="msg-avatar ai">星</div>
    <div class="msg-body">
      <div class="msg-meta">${intentLabel ? `<span class="chip">${escapeHtml(intentLabel)}</span>` : ""}<span>小星</span></div>
      <div class="bubble"><span class="txt"></span></div>
      <div class="cards"></div>
      <div class="msg-foot hidden"><span class="foot-note"></span></div>
      <div class="sources hidden"></div>
    </div>`;
  row.cards = row.querySelector(".cards");
  row.bubble = row.querySelector(".bubble .txt");
  row.foot = row.querySelector(".msg-foot");
  row.sourcesBox = row.querySelector(".sources");
  $("messages").appendChild(row);
  scrollBottom();
  return row;
}

function appendSystem(text) {
  clearEmptyState();
  const row = document.createElement("div");
  row.className = "sys-row";
  row.innerHTML = `<div class="sys-bubble">${escapeHtml(text)}</div>`;
  $("messages").appendChild(row);
  scrollBottom();
}

function setBubble(node, text) {
  node.bubble.innerHTML = renderMarkdown(text);
}

function attachSources(node, sources) {
  node.foot.classList.remove("hidden");
  node.foot.querySelector(".foot-note").innerHTML = `<span class="src-toggle">📎 知识来源 ${sources.length} 条 · 点击展开</span>`;
  node.sourcesBox.innerHTML = sources
    .map(
      (s) => `
      <div class="source-card">
        <div class="sh"><span class="sn">[${s.index}]</span><span>${escapeHtml(s.title || "知识片段")}</span>
          <span class="chip gray" style="margin-left:auto;">${escapeHtml(s.category || "")}</span></div>
        <div>${escapeHtml(s.content || "")}</div>
      </div>`
    )
    .join("");
  node.foot.querySelector(".src-toggle").addEventListener("click", () => {
    node.sourcesBox.classList.toggle("hidden");
  });
}

function nowTime() {
  const d = new Date();
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function scrollBottom() {
  const box = $("messages");
  box.scrollTop = box.scrollHeight;
}

/* ---------------- 数据卡片 ---------------- */
function renderCard(card) {
  const el = document.createElement("div");
  el.className = "data-card";
  const badgeClass =
    card.status === "success" ? "green" : card.status === "danger" ? "red" : card.status === "pending" ? "amber" : "gray";

  let bodyHtml = "";
  if (card.type === "timeline") {
    bodyHtml = `
      <div class="dc-body">${(card.fields || [])
        .map((f) => `<div class="dc-row"><span class="k">${escapeHtml(f.label)}</span><span class="v">${escapeHtml(String(f.value))}</span></div>`)
        .join("")}</div>
      <div class="dc-steps">${(card.timeline || [])
        .map(
          (s) => `
        <div class="dc-step ${s.done ? "done" : ""}">
          <div class="rail"><div class="point"></div><div class="line"></div></div>
          <div class="st">${escapeHtml(s.label)}<span>${escapeHtml(s.time || "")}</span></div>
        </div>`
        )
        .join("")}</div>`;
  } else {
    bodyHtml = `<div class="dc-body">${(card.fields || [])
      .map((f) => `<div class="dc-row"><span class="k">${escapeHtml(f.label)}</span><span class="v">${escapeHtml(String(f.value))}</span></div>`)
      .join("")}</div>`;
  }

  el.innerHTML = `
    <div class="dc-head">
      <span class="dc-title">${escapeHtml(card.title || "业务数据")}</span>
      ${card.badge ? `<span class="dc-badge chip ${badgeClass}">${escapeHtml(card.badge)}</span>` : ""}
    </div>
    ${bodyHtml}`;
  return el;
}

/* ---------------- 链路追踪 ---------------- */
function resetTrace() {
  $("trace").innerHTML = `
    <div class="trace-item"><span class="trace-dot">1</span><span>意图识别 · 等待输入</span></div>
    <div class="trace-item"><span class="trace-dot">2</span><span>工具调用 / 知识检索</span></div>
    <div class="trace-item"><span class="trace-dot">3</span><span>生成结构化答复</span></div>`;
}

function updateTrace(intentLabel, step2, done) {
  const items = $("trace").querySelectorAll(".trace-item");
  if (!items.length) return;
  if (intentLabel) {
    items[0].classList.add("active");
    items[0].lastElementChild.textContent = "意图识别 · " + intentLabel;
  }
  if (step2) {
    items[1].classList.add("active");
    items[1].lastElementChild.textContent = step2;
  }
  if (done) {
    items[2].classList.add("active");
    items[2].lastElementChild.textContent = "答复已生成";
  }
}

/* ---------------- 发送 ---------------- */
const input = $("input");
input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 120) + "px";
  $("sendBtn").disabled = !input.value.trim() || state.streaming;
});
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});
$("sendBtn").addEventListener("click", send);

async function send() {
  const question = input.value.trim();
  if (!question || state.streaming) return;

  input.value = "";
  input.style.height = "auto";
  $("sendBtn").disabled = true;

  appendUser(question);
  state.streaming = true;

  const node = appendAssistant("分析中");
  node.bubble.innerHTML = '<span class="typing"><i></i><i></i><i></i></span>';
  let buffer = "";
  let intentLabel = "";
  let sources = [];
  let gotCard = false;

  updateTrace("分析中");

  try {
    const res = await fetch(`${API}/chat/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + state.token,
      },
      body: JSON.stringify({ question, thread_id: state.threadId }),
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || "对话服务异常");
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let pending = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      pending += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = pending.indexOf("\n\n")) >= 0) {
        const raw = pending.slice(0, idx).trim();
        pending = pending.slice(idx + 2);
        if (!raw.startsWith("data:")) continue;
        const payload = raw.slice(5).trim();
        if (payload === "[DONE]") continue;
        let evt;
        try {
          evt = JSON.parse(payload);
        } catch (e) {
          continue;
        }
        handleEvent(evt);
      }
    }

    function handleEvent(evt) {
      if (evt.type === "intent") {
        intentLabel = evt.label;
        node.querySelector(".msg-meta").innerHTML = `<span class="chip">${escapeHtml(evt.label)}</span><span>小星</span>`;
        updateTrace(evt.label);
      } else if (evt.type === "sources") {
        sources = evt.sources || [];
        updateTrace(null, `知识检索 · 命中 ${sources.length} 条`);
      } else if (evt.type === "card") {
        gotCard = true;
        node.cards.appendChild(renderCard(evt.card));
        updateTrace(null, "工具调用 · " + (evt.card.title || "业务数据"));
        scrollBottom();
      } else if (evt.type === "token") {
        if (buffer === "" && !gotCard) node.bubble.innerHTML = "";
        buffer += evt.text;
        setBubble(node, buffer);
        scrollBottom();
      } else if (evt.type === "done") {
        if (sources.length) attachSources(node, sources);
        updateTrace(null, null, true);
        renderSuggestions(evt.suggestions || []);
        if (evt.awaiting === "order_sn" || evt.awaiting === "refund") {
          toast("需要你补充订单号", "");
        }
      } else if (evt.type === "error") {
        buffer = "抱歉，" + evt.message;
        setBubble(node, buffer);
      }
    }
  } catch (err) {
    if (!buffer) {
      buffer = "抱歉，服务暂时不可用：" + err.message;
      setBubble(node, buffer);
    }
    toast(err.message, "err");
  } finally {
    state.streaming = false;
    if (!buffer) setBubble(node, "（未获取到回复，请重试）");
    $("sendBtn").disabled = !input.value.trim();
    loadThreads();
    renderThreads();
    scrollBottom();
  }
}

function renderSuggestions(items) {
  const row = $("suggestRow");
  if (!items || !items.length) {
    row.classList.add("hidden");
    return;
  }
  row.classList.remove("hidden");
  row.innerHTML = items.map((s) => `<button class="suggest">${escapeHtml(s)}</button>`).join("");
  row.querySelectorAll(".suggest").forEach((btn) => {
    btn.addEventListener("click", () => {
      $("input").value = btn.textContent;
      send();
    });
  });
}

/* ---------------- WebSocket ---------------- */
function connectWs() {
  if (!state.token) return;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  try {
    state.ws = new WebSocket(`${proto}://${location.host}${API}/ws?token=${encodeURIComponent(state.token)}`);
    state.ws.onmessage = (e) => {
      let data;
      try { data = JSON.parse(e.data); } catch (err) { return; }
      if (data.type === "audit:decided") {
        appendSystem(data.message);
        toast(data.approved ? "人工审核已通过" : "人工审核已驳回", data.approved ? "ok" : "err");
        loadThreads();
      }
    };
    state.ws.onclose = () => {
      setTimeout(() => { if (state.token) connectWs(); }, 4000);
    };
  } catch (e) {}
}

/* ---------------- 启动 ---------------- */
(async function boot() {
  bindWelcomeCards(document);
  if (!state.token) return;
  try {
    const me = await api("/auth/me");
    state.user = me;
    localStorage.setItem(USER_KEY, JSON.stringify(me));
    enterApp();
    const ask = new URLSearchParams(location.search).get("ask");
    if (ask) {
      history.replaceState(null, "", "/");
      input.value = ask;
      input.dispatchEvent(new Event("input"));
      setTimeout(() => send(), 260);
    }
  } catch (e) {
    logout();
  }
})();
