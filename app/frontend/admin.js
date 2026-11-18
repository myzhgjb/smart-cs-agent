/* ============================================================
   管理台
   ============================================================ */
const API = "/api/v1";

const SHARE = new URLSearchParams(location.search).get("sharecode") || "";

/** 云端发布后网关要求每个请求带 sharecode，这里统一透传 */
function apiUrl(path) {
  if (!SHARE) return API + path;
  return API + path + (path.includes("?") ? "&" : "?") + "sharecode=" + encodeURIComponent(SHARE);
}

const $ = (id) => document.getElementById(id);

const state = {
  token: localStorage.getItem("cs_token") || "",
  user: JSON.parse(localStorage.getItem("cs_user") || "null"),
  audits: [],
  activeAudit: null,
  sessions: [],
  activeSession: null,
  products: [],
  orders: [],
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
  if (state.token) headers["X-Auth-Token"] = state.token;
  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    if (typeof options.body !== "string") options.body = JSON.stringify(options.body);
  }
  const res = await fetch(apiUrl(path), { ...options, headers });
  if (res.status === 401 || res.status === 403) {
    localStorage.removeItem("cs_token");
    location.href = rootUrl("/");
    throw new Error("无权限访问");
  }
  if (!res.ok) {
    let detail = "请求失败";
    try { detail = (await res.json()).detail || detail; } catch (e) {}
    throw new Error(detail);
  }
  return res.json();
}


/** 云端分享链接：内部跳转、静态资源地址统一带上 sharecode */
function rootUrl(path) {
  if (!SHARE) return path;
  return path + (path.includes("?") ? "&" : "?") + "sharecode=" + encodeURIComponent(SHARE);
}

document.querySelectorAll('a[href^="/"]').forEach((a) => {
  const href = a.getAttribute("href");
  if (href && !href.includes("sharecode")) a.setAttribute("href", rootUrl(href));
});

/* ---------------- 初始化 ---------------- */
(async function init() {
  if (!state.token) {
    location.href = rootUrl("/");
    return;
  }
  try {
    const me = await api("/auth/me");
    if (!me.is_admin) {
      toast("该账号无管理权限", "err");
      setTimeout(() => (location.href = rootUrl("/")), 900);
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
  loadProducts();
  loadOrders();
  connectWs();
})();

$("adminLogout").addEventListener("click", () => {
  localStorage.removeItem("cs_token");
  localStorage.removeItem("cs_user");
  location.href = rootUrl("/");
});

/* ---------------- Tabs ---------------- */
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    ["audits", "sessions", "kb", "products", "orders"].forEach((name) => {
      $("tab-" + name).classList.toggle("hidden", name !== tab.dataset.tab);
    });
    if (tab.dataset.tab === "products") loadProducts();
    if (tab.dataset.tab === "orders") loadOrders();
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
    state.ws = new WebSocket(`${proto}://${location.host}${apiUrl(`/ws?token=${encodeURIComponent(state.token)}`)}`);
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


/* ============================================================
   商品管理
   ============================================================ */
const CATEGORIES = ["数码影音", "家用电器", "家居生活", "服饰鞋包", "其他"];
const GRADIENTS = [
  "linear-gradient(135deg,#eef2ff,#c7d2fe)",
  "linear-gradient(135deg,#ecfeff,#a5f3fc)",
  "linear-gradient(135deg,#fffbeb,#fde68a)",
  "linear-gradient(135deg,#fff1f2,#fecdd3)",
  "linear-gradient(135deg,#ecfdf5,#a7f3d0)",
];

async function loadProducts() {
  try {
    state.products = await api("/admin/products");
    $("pCount").textContent = state.products.length + " 个商品";
    const body = $("pBody");
    if (!state.products.length) {
      body.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-3);padding:30px;">暂无商品</td></tr>';
      return;
    }
    body.innerHTML = state.products
      .map(
        (p) => `
      <tr>
        <td>
          <div class="p-cell">
            <div class="p-thumb" style="background:${esc(p.gradient)}">${p.emoji}</div>
            <div><div class="nm">${esc(p.name)}</div><div class="sk">${esc(p.sku)}</div></div>
          </div>
        </td>
        <td><span class="chip gray">${esc(p.category)}</span></td>
        <td class="mono">¥${Number(p.price).toFixed(2)}</td>
        <td class="mono" style="${p.stock < 20 ? "color:var(--red);" : ""}">${p.stock}</td>
        <td class="mono">${p.sales}</td>
        <td>${p.is_active ? '<span class="chip green">在售</span>' : '<span class="chip gray">已下架</span>'}</td>
        <td>
          <div class="ops">
            <button class="row-link" data-edit="${p.id}">编辑</button>
            <button class="row-link" data-toggle="${p.id}" style="color:${p.is_active ? "var(--red)" : "var(--brand)"};">${p.is_active ? "下架" : "上架"}</button>
          </div>
        </td>
      </tr>`
      )
      .join("");

    body.querySelectorAll("[data-edit]").forEach((btn) =>
      btn.addEventListener("click", () => openProductForm(Number(btn.dataset.edit)))
    );
    body.querySelectorAll("[data-toggle]").forEach((btn) =>
      btn.addEventListener("click", () => toggleProduct(Number(btn.dataset.toggle)))
    );
  } catch (e) {
    toast(e.message, "err");
  }
}

async function toggleProduct(id) {
  const p = state.products.find((x) => x.id === id);
  if (!p) return;
  try {
    await api(`/admin/products/${id}`, { method: "PATCH", body: { is_active: !p.is_active } });
    toast(p.is_active ? "已下架" : "已上架", "ok");
    loadProducts();
  } catch (e) {
    toast(e.message, "err");
  }
}

function openProductForm(id) {
  const p = id ? state.products.find((x) => x.id === id) : null;
  const isEdit = Boolean(p);
  const data = p || {
    name: "",
    category: "数码影音",
    price: "",
    original_price: "",
    stock: 100,
    emoji: "📦",
    summary: "",
    description: "",
    tags: [],
    is_active: true,
  };

  $("pModalBox").innerHTML = `
    <button class="modal-close" id="pClose">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 6l12 12M18 6L6 18"/></svg>
    </button>
    <div class="modal-head"><h3>${isEdit ? "编辑商品" : "新增商品"}</h3>${isEdit ? `<span class="chip gray">${esc(p.sku)}</span>` : ""}</div>
    <div class="modal-body">
      <div class="form-grid">
        <div class="field full"><label>商品名称</label><input id="fName" value="${esc(data.name)}" placeholder="例如：星海 无线降噪耳机" /></div>
        <div class="field"><label>分类</label>
          <select id="fCategory">${CATEGORIES.map((c) => `<option ${c === data.category ? "selected" : ""}>${c}</option>`).join("")}</select>
        </div>
        <div class="field"><label>图标（emoji）</label><input id="fEmoji" value="${esc(data.emoji)}" maxlength="4" /></div>
        <div class="field"><label>售价（元）</label><input id="fPrice" type="number" step="0.01" value="${data.price}" /></div>
        <div class="field"><label>划线价（选填）</label><input id="fOriginal" type="number" step="0.01" value="${data.original_price ?? ""}" /></div>
        <div class="field"><label>库存</label><input id="fStock" type="number" value="${data.stock}" /></div>
        <div class="field"><label>上架状态</label>
          <select id="fActive"><option value="1" ${data.is_active ? "selected" : ""}>在售</option><option value="0" ${!data.is_active ? "selected" : ""}>下架</option></select>
        </div>
        <div class="field full"><label>一句话卖点</label><input id="fSummary" value="${esc(data.summary || "")}" placeholder="42dB 主动降噪 · 续航 9 小时" /></div>
        <div class="field full"><label>详情描述</label><textarea id="fDesc" placeholder="材质、参数、适用场景…">${esc(data.description || "")}</textarea></div>
        <div class="field full"><label>标签（用逗号分隔）</label><input id="fTags" value="${esc((data.tags || []).join(","))}" placeholder="主动降噪,一年质保" /></div>
      </div>
    </div>
    <div class="modal-foot">
      <button class="btn btn-ghost" id="pCancel">取消</button>
      <button class="btn btn-primary" id="pSave">${isEdit ? "保存修改" : "创建商品"}</button>
    </div>`;

  $("pModal").classList.add("show");
  const close = () => $("pModal").classList.remove("show");
  $("pClose").addEventListener("click", close);
  $("pCancel").addEventListener("click", close);

  $("pSave").addEventListener("click", async () => {
    const payload = {
      name: $("fName").value.trim(),
      category: $("fCategory").value,
      emoji: $("fEmoji").value.trim() || "📦",
      price: Number($("fPrice").value),
      original_price: $("fOriginal").value ? Number($("fOriginal").value) : null,
      stock: Number($("fStock").value),
      summary: $("fSummary").value.trim(),
      description: $("fDesc").value.trim(),
      tags: $("fTags").value.split(/[，,]/).map((t) => t.trim()).filter(Boolean),
      is_active: $("fActive").value === "1",
    };
    if (!payload.name || !(payload.price > 0)) {
      toast("请填写商品名称和有效售价", "err");
      return;
    }
    try {
      if (isEdit) {
        await api(`/admin/products/${p.id}`, { method: "PATCH", body: payload });
        toast("商品已更新", "ok");
      } else {
        await api("/admin/products", {
          method: "POST",
          body: { ...payload, gradient: GRADIENTS[Math.floor(Math.random() * GRADIENTS.length)] },
        });
        toast("商品已创建", "ok");
      }
      close();
      loadProducts();
      loadStats();
    } catch (e) {
      toast(e.message, "err");
    }
  });
}

/* ============================================================
   订单管理
   ============================================================ */
async function loadOrders() {
  const status = $("oStatus").value;
  const kw = $("oKw").value.trim();
  try {
    state.orders = await api(`/admin/orders?status=${status}&kw=${encodeURIComponent(kw)}`);
    $("oCount").textContent = state.orders.length + " 笔订单";
    const body = $("oBody");
    if (!state.orders.length) {
      body.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-3);padding:30px;">暂无订单</td></tr>';
      return;
    }
    const chip = (s) => {
      const map = { PENDING: ["amber", "待付款"], PAID: ["", "已付款"], SHIPPED: ["", "已发货"], DELIVERED: ["green", "已签收"], CANCELLED: ["gray", "已取消"] };
      const [cls, label] = map[s] || ["gray", s];
      return `<span class="chip ${cls}">${label}</span>`;
    };
    body.innerHTML = state.orders
      .map(
        (o) => `
      <tr>
        <td class="mono" style="color:var(--text);">${esc(o.order_sn)}</td>
        <td>${esc(o.user ? o.user.name : "—")}</td>
        <td style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(o.items.map((i) => i.name + "×" + i.qty).join("、"))}</td>
        <td class="mono">¥${Number(o.total_amount).toFixed(2)}</td>
        <td>${chip(o.status)}</td>
        <td class="mono" style="font-size:11.5px;">${o.tracking_number ? esc(o.carrier + " " + o.tracking_number) : "—"}</td>
        <td style="font-size:11.5px;color:var(--text-3);">${esc(o.created_at)}</td>
        <td>
          <div class="ops">
            ${o.status === "PAID" ? `<button class="row-link" data-ship="${o.id}">发货</button>` : ""}
            ${o.status === "SHIPPED" ? `<button class="row-link" data-deliver="${o.id}">确认签收</button>` : ""}
            ${o.status === "PENDING" ? `<span style="font-size:11.5px;color:var(--text-3);">待买家支付</span>` : ""}
            ${o.status === "DELIVERED" ? `<span style="font-size:11.5px;color:var(--text-3);">已完成</span>` : ""}
          </div>
        </td>
      </tr>`
      )
      .join("");

    body.querySelectorAll("[data-ship]").forEach((btn) =>
      btn.addEventListener("click", () => shipOrder(Number(btn.dataset.ship)))
    );
    body.querySelectorAll("[data-deliver]").forEach((btn) =>
      btn.addEventListener("click", () => deliverOrder(Number(btn.dataset.deliver)))
    );
  } catch (e) {
    toast(e.message, "err");
  }
}

async function shipOrder(id) {
  try {
    const res = await api(`/admin/orders/${id}/ship`, { method: "POST", body: { carrier: "顺丰速运" } });
    toast(`已发货：${res.carrier} ${res.tracking_number}`, "ok");
    loadOrders();
    loadStats();
  } catch (e) {
    toast(e.message, "err");
  }
}

async function deliverOrder(id) {
  try {
    await api(`/admin/orders/${id}/deliver`, { method: "POST" });
    toast("已标记签收", "ok");
    loadOrders();
  } catch (e) {
    toast(e.message, "err");
  }
}

let orderTimer = null;
document.addEventListener("DOMContentLoaded", () => {});
$("oStatus").addEventListener("change", loadOrders);
$("oKw").addEventListener("input", () => {
  clearTimeout(orderTimer);
  orderTimer = setTimeout(loadOrders, 300);
});
$("pNew").addEventListener("click", () => openProductForm(null));
