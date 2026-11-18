/* ============================================================
   星海优选 · 商城前台
   ============================================================ */
const API = "/api/v1";
const $ = (id) => document.getElementById(id);

const state = {
  token: localStorage.getItem("cs_token") || "",
  user: JSON.parse(localStorage.getItem("cs_user") || "null"),
  products: [],
  categories: [],
  category: "全部商品",
  keyword: "",
  sort: "recommend",
  cart: { items: [], total: 0, count: 0 },
  productIndex: {},
  order: null,
};

function toast(msg, kind = "") {
  const el = document.createElement("div");
  el.className = "toast " + kind;
  el.textContent = msg;
  $("toastWrap").appendChild(el);
  setTimeout(() => el.remove(), 3000);
}

function esc(t) {
  return String(t ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function money(n) {
  return Number(n).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
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
    localStorage.removeItem("cs_token");
    location.href = "/";
    throw new Error("请先登录");
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
    state.user = me;
    $("shopAvatar").textContent = (me.full_name || me.username).slice(0, 1);
    if (me.is_admin) $("adminLink").style.display = "";
  } catch (e) {
    return;
  }
  await loadCategories();
  await loadProducts();
  await loadCart();
})();

$("logoutBtn").addEventListener("click", () => {
  localStorage.removeItem("cs_token");
  localStorage.removeItem("cs_user");
  location.href = "/";
});

/* ---------------- 视图切换 ---------------- */
function switchView(view) {
  const isShop = view === "shop";
  $("viewProducts").classList.toggle("hidden", !isShop);
  $("viewOrders").classList.toggle("hidden", isShop);
  $("navShop").classList.toggle("active", isShop);
  $("navOrders").classList.toggle("active", !isShop);
  if (!isShop) loadOrders();
}
$("navShop").addEventListener("click", () => switchView("shop"));
$("navOrders").addEventListener("click", () => switchView("orders"));
$("goShopping").addEventListener("click", () => switchView("shop"));

/* ---------------- 商品 ---------------- */
async function loadCategories() {
  try {
    state.categories = await api("/mall/categories");
    renderCategories();
  } catch (e) {}
}

function renderCategories() {
  $("catChips").innerHTML = state.categories
    .map(
      (c) =>
        `<button class="cat-chip ${c.name === state.category ? "active" : ""}" data-cat="${esc(c.name)}">${esc(
          c.name
        )}<span class="n">${c.count}</span></button>`
    )
    .join("");
  $("catChips").querySelectorAll(".cat-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.category = btn.dataset.cat;
      renderCategories();
      loadProducts();
    });
  });
}

async function loadProducts() {
  const params = new URLSearchParams();
  if (state.category && state.category !== "全部商品") params.set("category", state.category);
  if (state.keyword) params.set("q", state.keyword);
  params.set("sort", state.sort);
  try {
    state.products = await api("/mall/products?" + params.toString());
    if (!state.keyword && state.category === "全部商品") {
      state.productIndex = Object.fromEntries(state.products.map((p) => [p.id, p]));
    }
    renderProducts();
  } catch (e) {
    toast(e.message, "err");
  }
}

function stockBadge(p) {
  if (p.stock === 0) return `<span class="pc-badge" style="color:#64748b;">暂时缺货</span>`;
  if (p.original_price && p.original_price > p.price)
    return `<span class="pc-badge">省 ¥${money(p.original_price - p.price)}</span>`;
  if (p.sales > 1500) return `<span class="pc-badge">热销</span>`;
  return "";
}

function renderProducts() {
  const grid = $("productGrid");
  const empty = $("productEmpty");
  $("resultHint").textContent = state.products.length ? `${state.products.length} 件商品` : "";

  if (!state.products.length) {
    grid.innerHTML = "";
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");

  grid.innerHTML = state.products
    .map(
      (p) => `
      <article class="product-card" data-id="${p.id}">
        <div class="pc-tile" style="background:${esc(p.gradient)}">
          ${stockBadge(p)}
          <button class="pc-fav" data-fav="${p.id}" title="收藏">♡</button>
          <span class="emoji">${p.emoji}</span>
        </div>
        <div class="pc-body">
          <div class="pc-name">${esc(p.name)}</div>
          <div class="pc-summary">${esc(p.summary || p.category)}</div>
          <div class="pc-tags">${(p.tags || []).slice(0, 2).map((t) => `<span>${esc(t)}</span>`).join("")}</div>
          <div class="pc-foot">
            <span class="price"><span class="cur">¥</span>${money(p.price)}</span>
            ${p.original_price ? `<span class="price-old">¥${money(p.original_price)}</span>` : ""}
            <span class="pc-sales">已售 ${p.sales}</span>
          </div>
          <button class="add-cart" data-add="${p.id}" ${p.stock === 0 ? "disabled" : ""}>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M12 5v14M5 12h14"/></svg>
            ${p.stock === 0 ? "暂时缺货" : "加入购物车"}
          </button>
        </div>
      </article>`
    )
    .join("");

  grid.querySelectorAll(".product-card").forEach((card) => {
    card.addEventListener("click", (e) => {
      if (e.target.closest("[data-add]") || e.target.closest("[data-fav]")) return;
      openProduct(Number(card.dataset.id));
    });
  });
  grid.querySelectorAll("[data-add]").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      await addToCart(Number(btn.dataset.add), 1);
    });
  });
  grid.querySelectorAll("[data-fav]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      btn.textContent = btn.textContent === "♡" ? "♥" : "♡";
      btn.style.color = btn.textContent === "♥" ? "#e11d48" : "";
    });
  });
}

$("sortSelect").addEventListener("change", (e) => {
  state.sort = e.target.value;
  loadProducts();
});

let searchTimer = null;
$("searchInput").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.keyword = e.target.value.trim();
    loadProducts();
  }, 260);
});
$("searchInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    state.keyword = e.target.value.trim();
    loadProducts();
  }
});
$("searchBtn").addEventListener("click", () => {
  state.keyword = $("searchInput").value.trim();
  loadProducts();
});
$("resetFilter").addEventListener("click", () => {
  state.keyword = "";
  state.category = "全部商品";
  $("searchInput").value = "";
  renderCategories();
  loadProducts();
});

/* ---------------- 商品详情 ---------------- */
function openProduct(id) {
  const p = state.products.find((x) => x.id === id);
  if (!p) return;
  $("pdModal").innerHTML = `
    <button class="modal-close" id="pdClose">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 6l12 12M18 6L6 18"/></svg>
    </button>
    <div class="pd-wrap">
      <div class="pd-tile" style="background:${esc(p.gradient)}">${p.emoji}</div>
      <div class="pd-info">
        <h2>${esc(p.name)}</h2>
        <div class="pd-summary">${esc(p.category)} · 已售 ${p.sales} · 评分 ${p.rating}</div>
        <div class="pd-price">
          <span class="price"><span class="cur">¥</span>${money(p.price)}</span>
          ${p.original_price ? `<span class="price-old">¥${money(p.original_price)}</span>` : ""}
          <span class="chip ${p.stock > 0 ? "green" : "gray"}">${p.stock > 0 ? "现货 " + p.stock + " 件" : "缺货"}</span>
        </div>
        <div class="pd-desc">${esc(p.description || p.summary)}</div>
        <div class="pd-tags">${(p.tags || []).map((t) => `<span>${esc(t)}</span>`).join("")}</div>
        <div class="pd-actions">
          <div style="display:flex;align-items:center;gap:6px;">
            <button class="qty-btn" id="pdMinus">−</button>
            <span class="qty-num" id="pdQty">1</span>
            <button class="qty-btn" id="pdPlus">+</button>
          </div>
          <button class="btn btn-primary" id="pdAdd" style="flex:1;" ${p.stock === 0 ? "disabled" : ""}>加入购物车</button>
          <button class="btn btn-ghost" id="pdAsk">问客服</button>
        </div>
      </div>
    </div>`;
  $("pdMask").classList.add("show");

  let qty = 1;
  $("pdMinus").addEventListener("click", () => {
    qty = Math.max(1, qty - 1);
    $("pdQty").textContent = qty;
  });
  $("pdPlus").addEventListener("click", () => {
    qty = Math.min(p.stock || 1, qty + 1);
    $("pdQty").textContent = qty;
  });
  $("pdAdd").addEventListener("click", async () => {
    await addToCart(p.id, qty);
    closeModal($("pdMask"));
  });
  $("pdAsk").addEventListener("click", () => ask(`我想咨询「${p.name}」，这款还有货吗？适合什么场景？`));
  $("pdClose").addEventListener("click", () => closeModal($("pdMask")));
}

function closeModal(mask) {
  mask.classList.remove("show");
}
document.querySelectorAll(".modal-mask").forEach((mask) => {
  mask.addEventListener("click", (e) => {
    if (e.target === mask) closeModal(mask);
  });
});

/* ---------------- 购物车 ---------------- */
async function loadCart() {
  try {
    state.cart = await api("/mall/cart");
    renderCart();
  } catch (e) {}
}

function renderCart() {
  const count = state.cart.count || 0;
  const badge = $("cartCount");
  badge.style.display = count ? "" : "none";
  badge.textContent = count;
  $("cartHint").textContent = count + " 件";
  $("cartTotal").textContent = "¥" + money(state.cart.total);
  $("checkoutBtn").disabled = !count;

  const body = $("cartBody");
  if (!count) {
    body.innerHTML = `<div class="shop-empty" style="padding:60px 10px;">
      <div class="ico">🛒</div><p>购物车还是空的</p>
      <button class="btn btn-ghost btn-sm" onclick="document.getElementById('cartClose').click()">去挑点东西</button>
    </div>`;
    return;
  }

  body.innerHTML = state.cart.items
    .map(
      (row) => `
      <div class="cart-row">
        <div class="cart-thumb" style="background:${esc(row.product.gradient)}">${row.product.emoji}</div>
        <div class="cart-info">
          <div class="cart-name">${esc(row.product.name)}</div>
          <div class="cart-price">¥${money(row.product.price)}</div>
          <div class="cart-ops">
            <button class="qty-btn" data-minus="${row.id}">−</button>
            <span class="qty-num">${row.qty}</span>
            <button class="qty-btn" data-plus="${row.id}">+</button>
            <button class="cart-del" data-del="${row.id}">移除</button>
          </div>
        </div>
      </div>`
    )
    .join("");

  body.querySelectorAll("[data-plus]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const row = state.cart.items.find((i) => i.id === Number(btn.dataset.plus));
      if (row) changeQty(row.id, row.qty + 1);
    });
  });
  body.querySelectorAll("[data-minus]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const row = state.cart.items.find((i) => i.id === Number(btn.dataset.minus));
      if (row) changeQty(row.id, Math.max(1, row.qty - 1));
    });
  });
  body.querySelectorAll("[data-del]").forEach((btn) => {
    btn.addEventListener("click", () => removeItem(Number(btn.dataset.del)));
  });
}

async function addToCart(productId, qty) {
  try {
    state.cart = await api("/mall/cart", { method: "POST", body: { product_id: productId, qty } });
    renderCart();
    toast("已加入购物车", "ok");
    openCart();
  } catch (e) {
    toast(e.message, "err");
  }
}

async function changeQty(itemId, qty) {
  try {
    state.cart = await api(`/mall/cart/${itemId}`, { method: "PATCH", body: { qty } });
    renderCart();
  } catch (e) {
    toast(e.message, "err");
  }
}

async function removeItem(itemId) {
  try {
    state.cart = await api(`/mall/cart/${itemId}`, { method: "DELETE" });
    renderCart();
  } catch (e) {
    toast(e.message, "err");
  }
}

function openCart() {
  $("cartMask").classList.add("show");
  $("cartDrawer").classList.add("show");
}
function closeCart() {
  $("cartMask").classList.remove("show");
  $("cartDrawer").classList.remove("show");
}
$("cartBtn").addEventListener("click", openCart);
$("cartClose").addEventListener("click", closeCart);
$("cartMask").addEventListener("click", closeCart);

/* ---------------- 结算 ---------------- */
$("checkoutBtn").addEventListener("click", () => {
  if (!state.cart.count) return;
  const saved = localStorage.getItem("cs_address") || "江苏省苏州市虎丘区科锐路 1 号 苏州科技大学 学生公寓 6 号楼";
  $("coAddress").value = saved;
  $("coCount").textContent = `共 ${state.cart.count} 件`;
  $("coTotal").textContent = "¥" + money(state.cart.total);
  closeCart();
  $("coMask").classList.add("show");
});
$("coClose").addEventListener("click", () => closeModal($("coMask")));

$("coSubmit").addEventListener("click", async () => {
  const address = $("coAddress").value.trim();
  const btn = $("coSubmit");
  btn.disabled = true;
  btn.textContent = "提交中…";
  try {
    const res = await api("/mall/checkout", { method: "POST", body: { address } });
    localStorage.setItem("cs_address", address);
    state.order = res;
    closeModal($("coMask"));
    $("okSn").textContent = res.order_sn;
    $("okMask").classList.add("show");
    await loadCart();
    await loadProducts();
  } catch (e) {
    toast(e.message, "err");
  } finally {
    btn.disabled = false;
    btn.textContent = "提交订单";
  }
});

$("okPay").addEventListener("click", async () => {
  if (!state.order) return;
  try {
    await api(`/mall/orders/${state.order.order_sn}/pay`, { method: "POST" });
    toast("支付成功（模拟）", "ok");
    closeModal($("okMask"));
    switchView("orders");
  } catch (e) {
    toast(e.message, "err");
  }
});

$("okAsk").addEventListener("click", () => {
  if (!state.order) return;
  ask(`我刚下单了，订单号 ${state.order.order_sn}，帮我确认下信息和发货时间`);
});

/* ---------------- 我的订单 ---------------- */
async function loadOrders() {
  try {
    const orders = await api("/mall/orders");
    $("orderHint").textContent = orders.length ? `共 ${orders.length} 笔` : "";
    const list = $("orderList");
    const empty = $("orderEmpty");
    if (!orders.length) {
      list.innerHTML = "";
      empty.classList.remove("hidden");
      return;
    }
    empty.classList.add("hidden");

    const statusChip = (o) => {
      const map = {
        PENDING: ["amber", "待付款"],
        PAID: ["", "已付款"],
        SHIPPED: ["", "已发货"],
        DELIVERED: ["green", "已签收"],
        CANCELLED: ["gray", "已取消"],
      };
      const [cls, label] = map[o.status] || ["gray", o.status_text];
      return `<span class="st chip ${cls}">${label}</span>`;
    };

    list.innerHTML = orders
      .map(
        (o) => `
      <div class="order-card">
        <div class="order-head">
          <span class="sn">${esc(o.order_sn)}</span>
          <span class="time">${esc(o.created_at)}</span>
          ${statusChip(o)}
        </div>
        <div class="order-items">
          ${o.items
            .map((it) => {
              const p = (state.productIndex || {})[it.product_id];
              const emoji = p ? p.emoji : "📦";
              const bg = p ? p.gradient : "#f4f5fb";
              return `
            <div class="oi-row">
              <div class="oi-thumb" style="background:${bg};font-size:20px;">${emoji}</div>
              <div>
                <div class="oi-name">${esc(it.name)}</div>
                <div class="oi-meta">¥${money(it.price)} × ${it.qty}</div>
              </div>
              <div class="oi-price">¥${money(it.price * it.qty)}</div>
            </div>`;
            })
            .join("")}
        </div>
        <div class="order-foot">
          ${o.tracking_number ? `<span>${esc(o.carrier || "快递")} ${esc(o.tracking_number)}</span>` : `<span>${esc(o.address)}</span>`}
          <span class="total">实付 <b>¥${money(o.total_amount)}</b></span>
          ${
            o.status === "PENDING"
              ? `<button class="btn btn-primary btn-sm" data-pay="${esc(o.order_sn)}">立即支付</button>`
              : ""
          }
          ${
            o.status === "DELIVERED"
              ? `<button class="btn btn-ghost btn-sm" data-refund="${esc(o.order_sn)}">申请退货</button>`
              : ""
          }
          <button class="btn btn-ghost btn-sm" data-ask="${esc(o.order_sn)}">咨询客服</button>
        </div>
      </div>`
      )
      .join("");

    list.querySelectorAll("[data-pay]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await api(`/mall/orders/${btn.dataset.pay}/pay`, { method: "POST" });
          toast("支付成功（模拟）", "ok");
          loadOrders();
        } catch (e) {
          toast(e.message, "err");
        }
      });
    });
    list.querySelectorAll("[data-refund]").forEach((btn) => {
      btn.addEventListener("click", () => ask(`我要退货，订单号 ${btn.dataset.refund}，商品有问题`));
    });
    list.querySelectorAll("[data-ask]").forEach((btn) => {
      btn.addEventListener("click", () => ask(`帮我查下订单 ${btn.dataset.ask} 的物流进度`));
    });
  } catch (e) {
    toast(e.message, "err");
  }
}

/* ---------------- 跳转客服 ---------------- */
function ask(question) {
  location.href = "/?ask=" + encodeURIComponent(question);
}
