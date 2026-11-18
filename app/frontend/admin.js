/* ============================================================
   管理台
   ============================================================ */
const API = "/api/v1";
const $ = (id) => document.getElementById(id);

const state = {
  token: localStorage.getItem("cs_token") || "",
  user: JSON.parse(localStorage.getItem("cs_user") || "null"),
  audits: [],
  activeAudit: null,
  sessions: [],
  activeSession: null,
  ws: null,
};

function toast(msg, kind = "") {
  const el = document.createElement("div");
  el.className = "toast " + kind;
  el.textContent = msg;
  $("toastWrap").appendChild(el);
  setTimeout(() => el.remove(), 3200);
}

function esc(t) {
  return String(t ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function api(path, options = {}) {
  const headers = Object.assign({}, options.headers || {});
  if (state.token) headers["Authorization"] = "Bearer " + state.token;
  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    if (typeof options.body !== "string") options.body = JSON.stringify(options.body);
  }
  const res = await fetch(API + path, { ...options, headers });
  if (res.status === 401 || res.status === 403) {
    localStorage.removeItem("cs_token");
    location.href = "/";
    throw new Error("无权限访问");
  }
  if (!res.ok) {
    let detail = "请求失败";
    try { detail = (await res.json()).detail || detail; } catch (e) {}
    throw new Error(detail);
  }
  return res.json();
}

/* ---------------- 初始化 ---------------- */
(async function init() {
  if (!state.token) {
    location.href = "/";
    return;
  }
  try {
    const me = await api("/auth/me");
    if (!me.is_admin) {
      toast("该账号无管理权限", "err");
      setTimeout(() => (location.href = "/"), 900);
      return;
    }
    state.user = me;
    $("adminName").textContent = me.full_name;
    $("adminAvatar").textContent = me.full_name.slice(0, 1);
  } catch (e) {
    return;
  }
  loadStats();
  loadAudits();
  loadDocs();
  loadSessions();
  connectWs();
})();

$("adminLogout").addEventListener("click", () => {
  localStorage.removeItem("cs_token");
  localStorage.removeItem("cs_user");
  location.href = "/";
});

/* ---------------- Tabs ---------------- */
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    ["audits", "sessions", "kb"].forEach((name) => {
      $("tab-" + name).classList.toggle("hidden", name !== tab.dataset.tab);
    });
  });
});

/* ---------------- 概览 ---------------- */
async function loadStats() {
  try {
    const s = await api("/admin/stats");
    $("statPending").textContent = s.pending_audits;
    $("statToday").textContent = s.today_conversations;
    $("statChunks").textContent = s.kb_chunks;
    $("statRefund").textContent = "¥" + Number(s.refund_amount).toLocaleString("zh-CN", { maximumFractionDigits: 0 });
    const dot = $("pendingDot");
    if (s.pending_audits > 0) {
      dot.style.display = "";
      dot.textContent = s.pending_audits;
    } else {
      dot.style.display = "none";
    }
  } catch (e) {}
}

/* ---------------- 审核 ---------------- */
$("auditFilter").addEventListener("change", loadAudits);

async function loadAudits() {
  const filter = $("auditFilter").value;
  try {
    state.audits = await api("/admin/audits?status=" + filter);
    renderAudits();
  } catch (e) {
    toast(e.message, "err");
  }
}

function riskChip(level) {
  const map = { HIGH: ["red", "高风险"], MEDIUM: ["amber", "中风险"], LOW: ["green", "低风险"] };
  const [cls, label] = map[level] || ["gray", level];
  return `<span class="chip ${cls}">${label}</span>`;
}

function actionChip(action) {
  const map = { PENDING: ["amber", "待处理"], APPROVED: ["green", "已通过"], REJECTED: ["red", "已驳回"] };
  const [cls, label] = map[action] || ["gray", action];
  return `<span class="chip ${cls}">${label}</span>`;
}

function renderAudits() {
  const box = $("auditList");
  if (!state.audits.length) {
    box.innerHTML = '<div class="detail-empty">暂无工单，退款风控触发后会出现在这里</div>';
    return;
  }
  box.innerHTML = state.audits
    .map(
      (a) => `
      <div class="audit-item ${state.activeAudit === a.id ? "active" : ""}" data-id="${a.id}">
        <div class="ah">
          <span class="ac">${esc(a.code)}</span>
          ${riskChip(a.risk_level)}
          <span class="ar">${actionChip(a.action)}</span>
        </div>
        <div class="am">${esc(a.order ? a.order.order_sn : "—")} · 退款 ¥${a.refund ? Number(a.refund.amount).toLocaleString("zh-CN") : "-"}</div>
        <div class="af"><span>${esc(a.user ? a.user.name : "未知用户")}</span><span>${esc(a.created_at)}</span></div>
      </div>`
    )
    .join("");
  box.querySelectorAll(".audit-item").forEach((el) => {
    el.addEventListener("click", () => showAudit(Number(el.dataset.id)));
  });
}

function showAudit(id) {
  const a = state.audits.find((x) => x.id === id);
  if (!a) return;
  state.activeAudit = id;
  renderAudits();

  const snap = a.snapshot || {};
  const pending = a.action === "PENDING";
  $("auditDetail").innerHTML = `
    <div class="detail-title">
      <span class="mono">${esc(a.code)}</span>
      ${riskChip(a.risk_level)}
      ${actionChip(a.action)}
      <span style="margin-left:auto;font-size:12px;color:var(--text-3);">${esc(a.created_at)}</span>
    </div>
    <div class="kv-grid" style="margin-top:14px;">
      <div class="kv"><div class="k">申请用户</div><div class="v">${esc(a.user ? a.user.name + "（" + a.user.username + "）" : "—")}</div></div>
      <div class="kv"><div class="k">订单号</div><div class="v mono">${esc(a.order ? a.order.order_sn : "—")}</div></div>
      <div class="kv"><div class="k">订单金额</div><div class="v">¥${a.order ? Number(a.order.amount).toLocaleString("zh-CN", { minimumFractionDigits: 2 }) : "-"}</div></div>
      <div class="kv"><div class="k">退款金额</div><div class="v" style="color:var(--red);">¥${a.refund ? Number(a.refund.amount).toLocaleString("zh-CN", { minimumFractionDigits: 2 }) : "-"}</div></div>
      <div class="kv"><div class="k">退款原因</div><div class="v">${esc(snap.reason || (a.refund ? a.refund.reason : "—"))}</div></div>
      <div class="kv"><div class="k">原因分类</div><div class="v">${esc(a.refund ? a.refund.category : "—")}</div></div>
    </div>
    <div style="font-size:11.5px;color:var(--text-3);margin-bottom:6px;">触发规则</div>
    <div class="snap">${esc(a.trigger_reason)}</div>
    <div style="font-size:11.5px;color:var(--text-3);margin:14px 0 6px;">用户诉求原文</div>
    <div class="snap">${esc(snap.question || "—")}</div>
    ${
      a.admin_note
        ? `<div style="font-size:11.5px;color:var(--text-3);margin:14px 0 6px;">审核备注</div><div class="snap">${esc(a.admin_note)}<br/><span style="color:var(--text-3);">处理时间：${esc(a.handled_at || "—")}</span></div>`
        : ""
    }
    ${
      pending
        ? `<div class="decide-area">
             <div style="font-size:12.5px;font-weight:500;margin-bottom:7px;">审核意见</div>
             <textarea id="auditNote" placeholder="填写处理说明，会同步到用户会话中（选填）"></textarea>
             <div class="decide-btns">
               <button class="btn btn-success" id="approveBtn">通过并退款</button>
               <button class="btn btn-danger" id="rejectBtn">驳回申请</button>
             </div>
           </div>`
        : ""
    }`;

  if (pending) {
    $("approveBtn").addEventListener("click", () => decide(a.id, true));
    $("rejectBtn").addEventListener("click", () => decide(a.id, false));
  }
}

async function decide(id, approve) {
  const note = ($("auditNote")?.value || "").trim();
  const btns = document.querySelectorAll(".decide-btns .btn");
  btns.forEach((b) => (b.disabled = true));
  try {
    const res = await api(`/admin/audits/${id}/decide`, {
      method: "POST",
      body: { approve, note },
    });
    toast(res.message, "ok");
    await loadAudits();
    await loadStats();
    showAudit(id);
  } catch (e) {
    toast(e.message, "err");
    btns.forEach((b) => (b.disabled = false));
  }
}

/* ---------------- 会话回放 ---------------- */
async function loadSessions() {
  try {
    state.sessions = await api("/admin/threads");
    $("sessionCount").textContent = state.sessions.length + " 个会话";
    const box = $("sessionList");
    if (!state.sessions.length) {
      box.innerHTML = '<div class="detail-empty">暂无会话记录</div>';
      return;
    }
    box.innerHTML = state.sessions
      .map(
        (s) => `
      <div class="audit-item ${state.activeSession === s.thread_id ? "active" : ""}" data-id="${esc(s.thread_id)}">
        <div class="ah">
          <span class="ac" style="font-size:12px;">${esc(s.user_name)}</span>
          <span class="ar" style="font-size:11px;color:var(--text-3);">${esc(s.updated_at)}</span>
        </div>
        <div class="am">${esc(s.title)}</div>
        <div class="af"><span>${s.count} 条消息</span><span>${s.intents.map((i) => esc(i)).join(" / ")}</span></div>
      </div>`
      )
      .join("");
    box.querySelectorAll(".audit-item").forEach((el) => {
      el.addEventListener("click", () => openSession(el.dataset.id));
    });
  } catch (e) {}
}

async function openSession(threadId) {
  state.activeSession = threadId;
  loadSessions();
  $("replayMeta").textContent = threadId;
  try {
    const msgs = await api(`/admin/threads/${encodeURIComponent(threadId)}`);
    $("transcript").innerHTML = msgs
      .map((m) => {
        const who = m.role === "user" ? "用户" : m.role === "assistant" ? "小星" : "系统";
        const initial = m.role === "user" ? "用" : m.role === "assistant" ? "星" : "系";
        const intent = m.intent ? `<span class="chip gray">${esc(m.intent)}</span>` : "";
        const srcCount = m.sources && m.sources.length ? `<span class="chip">引用 ${m.sources.length}</span>` : "";
        return `
          <div class="tmsg ${esc(m.role)}">
            <div class="who">${initial}</div>
            <div class="body">
              <div class="meta"><span>${who}</span>${intent}${srcCount}<span>${esc(m.created_at)}</span></div>
              <div class="txt">${esc(m.content)}</div>
            </div>
          </div>`;
      })
      .join("");
  } catch (e) {
    toast(e.message, "err");
  }
}

/* ---------------- 知识库 ---------------- */
async function loadDocs() {
  try {
    const docs = await api("/admin/kb/docs");
    $("docCount").textContent = docs.length + " 篇";
    const body = $("docBody");
    if (!docs.length) {
      body.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-3);padding:30px;">暂无文档</td></tr>';
      return;
    }
    body.innerHTML = docs
      .map(
        (d) => `
      <tr>
        <td style="color:var(--text);font-weight:500;">${esc(d.title)}</td>
        <td><span class="chip gray">${esc(d.category)}</span></td>
        <td>${esc(d.source)}</td>
        <td class="mono">${d.chunk_count}</td>
        <td class="mono">${d.char_count.toLocaleString()}</td>
        <td><button class="row-link" data-del="${d.id}">删除</button></td>
      </tr>`
      )
      .join("");
    body.querySelectorAll("[data-del]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!confirm("确定删除这篇文档并更新索引？")) return;
        try {
          await api("/admin/kb/docs/" + btn.dataset.del, { method: "DELETE" });
          toast("已删除并重建索引", "ok");
          loadDocs();
          loadStats();
        } catch (e) {
          toast(e.message, "err");
        }
      });
    });
  } catch (e) {}
}

const zone = $("uploadZone");
zone.addEventListener("click", () => $("fileInput").click());
zone.addEventListener("dragover", (e) => {
  e.preventDefault();
  zone.classList.add("drag");
});
zone.addEventListener("dragleave", () => zone.classList.remove("drag"));
zone.addEventListener("drop", (e) => {
  e.preventDefault();
  zone.classList.remove("drag");
  uploadFiles(e.dataTransfer.files);
});
$("fileInput").addEventListener("change", (e) => uploadFiles(e.target.files));

async function uploadFiles(files) {
  if (!files || !files.length) return;
  const category = $("kbCategory").value.trim() || "上传知识";
  for (const file of files) {
    const form = new FormData();
    form.append("file", file);
    form.append("category", category);
    try {
      const res = await api("/admin/kb/upload", { method: "POST", body: form });
      toast(`《${res.title}》解析完成，切分 ${res.chunks} 个片段`, "ok");
    } catch (e) {
      toast(`${file.name}：${e.message}`, "err");
    }
  }
  $("fileInput").value = "";
  loadDocs();
  loadStats();
}

$("reindexBtn").addEventListener("click", async () => {
  try {
    const res = await api("/admin/kb/reindex", { method: "POST" });
    toast(`索引已重建，共 ${res.chunks} 个片段`, "ok");
  } catch (e) {
    toast(e.message, "err");
  }
});

$("kbSearchBtn").addEventListener("click", doSearch);
$("kbSearch").addEventListener("keydown", (e) => {
  if (e.key === "Enter") doSearch();
});

async function doSearch() {
  const q = $("kbSearch").value.trim();
  if (!q) return;
  const box = $("kbHits");
  box.innerHTML = '<div style="font-size:12px;color:var(--text-3);">检索中…</div>';
  try {
    const hits = await api("/admin/kb/search?q=" + encodeURIComponent(q));
    if (!hits.length) {
      box.innerHTML = '<div class="hit">未命中任何片段，可调低阈值或补充知识文档</div>';
      return;
    }
    box.innerHTML = hits
      .map(
        (h) => `
      <div class="hit">
        <div class="hh"><span>[${h.chunk_id}]</span><span>${esc(h.title)}</span>
          <span class="hs">score ${h.score} · 覆盖 ${(h.coverage * 100).toFixed(0)}%</span></div>
        <div>${esc(h.content.replace(/\n/g, " ").slice(0, 160))}…</div>
      </div>`
      )
      .join("");
  } catch (e) {
    box.innerHTML = `<div class="hit">${esc(e.message)}</div>`;
  }
}

/* ---------------- WebSocket ---------------- */
function connectWs() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  try {
    state.ws = new WebSocket(`${proto}://${location.host}${API}/ws?token=${encodeURIComponent(state.token)}`);
    state.ws.onmessage = (e) => {
      let data;
      try { data = JSON.parse(e.data); } catch (err) { return; }
      if (data.type === "audit:new") {
        toast(`新工单 ${data.order_sn} · ¥${data.amount}`, "");
        loadAudits();
        loadStats();
      }
      if (data.type === "handoff") {
        toast(`${data.user_name} 请求转人工：${data.question}`, "");
        loadSessions();
      }
    };
    state.ws.onclose = () => setTimeout(() => { if (state.token) connectWs(); }, 4000);
  } catch (e) {}
}
