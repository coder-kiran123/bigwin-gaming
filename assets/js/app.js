/* ==========================================================================
   BigWin Gaming — Member app script (app/*.html)
   One script for all three tabs; each page sets <body data-page="…">.

   BACKEND: data comes from window.SITE (config.js) as sample content.
   Replace the `api` object below with real fetch() calls to your server.
   ========================================================================== */

(function () {
  "use strict";
  const S = window.SITE;
  const I = window.ICONS;
  const $ = (s, c = document) => c.querySelector(s);
  const $$ = (s, c = document) => Array.from(c.querySelectorAll(s));

  /* ---------- Storage helpers (safe in private mode) ---------- */
  const store = {
    get(key, fallback) { try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch (e) { return fallback; } },
    set(key, val) { try { localStorage.setItem(key, JSON.stringify(val)); } catch (e) {} },
    remove(key) { try { localStorage.removeItem(key); } catch (e) {} },
  };

  /* ---------- Data layer ----------
     Signed-in player + Game IDs come from the server (api.js → server/app.py).
     Chats and Payments still use sample data from config.js (next step: connect
     /api/support/messages and /api/deposits, /api/withdrawals). */
  const api = {
    user: () => BW.session.get(),
    payments: () => store.get("bw-payments", S.payments),
    savePayment(p) { const list = [p, ...api.payments()]; store.set("bw-payments", list); return list; },
  };

  /* ---------- Toast ---------- */
  let toastTimer;
  function toast(text) {
    let el = $(".toast");
    if (!el) { el = document.createElement("div"); el.className = "toast"; el.setAttribute("role", "status"); document.body.appendChild(el); }
    el.textContent = text;
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 2600);
  }

  /* ---------- Header: welcome name + profile image ---------- */
  function initHeader() {
    const user = api.user();
    const name = [user.firstName, user.lastName].filter(Boolean).join(" ") || user.username;
    const welcome = $("#welcome-name");
    if (welcome) welcome.textContent = `Welcome, ${name}`;

    const avatar = $("#profile-avatar");
    const photo = store.get("bw-photo", null);
    const applyPhoto = (src) => {
      if (!avatar) return;
      avatar.style.backgroundImage = `url("${src}")`;
      avatar.firstChild.textContent = "";
    };
    if (photo) applyPhoto(photo);

    const input = $("#upload-input");
    const btn = $(".upload-btn");
    if (btn && input) {
      btn.addEventListener("click", () => input.click());
      input.addEventListener("change", () => {
        const file = input.files[0];
        if (!file) return;
        if (!file.type.startsWith("image/")) return toast("Please choose an image file.");
        if (file.size > 3 * 1024 * 1024) return toast("Image must be under 3 MB.");
        const reader = new FileReader();
        reader.onload = () => {
          // TODO: upload `file` to your server / storage bucket instead of saving locally.
          store.set("bw-photo", reader.result);
          applyPhoto(reader.result);
          toast("Profile image updated.");
        };
        reader.readAsDataURL(file);
      });
    }

    $$("[data-logout]").forEach((b) =>
      b.addEventListener("click", () => {
        BW.session.clear();
        location.href = "../auth.html";
      })
    );
  }

  /* ---------- Chats page (live support chat, server: /api/support/*) ---------- */
  const IMG_RE = /^data:image\/(png|jpe?g|webp|gif);base64,[A-Za-z0-9+/=]+$/;

  // "2026-11-18 09:30:00" (UTC from the server) -> Date
  function parseTime(t) {
    if (!t) return null;
    let s = String(t).replace(" ", "T");
    if (!/[zZ]|[+-]\d\d:?\d\d$/.test(s)) s += "Z";
    const d = new Date(s);
    return isNaN(d) ? null : d;
  }
  function ago(t) {
    const d = parseTime(t);
    if (!d) return "";
    const m = Math.max(0, Math.round((Date.now() - d) / 60000));
    if (m < 1) return "now";
    if (m < 60) return `${m}m`;
    if (m < 1440) return `${Math.round(m / 60)}h`;
    return `${Math.round(m / 1440)}d`;
  }
  const previewText = (m) => (!m ? "Tap to chat with support" : IMG_RE.test(m.message) ? "📷 Photo" : (m.sender === "player" ? "You: " : "") + m.message);

  function chatRow(c) {
    const cls = ["chat-row", "chat-row--pinned", c.unread ? "chat-row--unread" : ""].join(" ");
    const style = c.color ? ` style="background:${esc(c.color)};color:#fff"` : "";
    return `<button class="${cls}" data-chat="${esc(c.name)}">
      <div class="avatar ${c.color ? "" : "avatar--gold"}"${style}>${esc(c.icon || c.name.slice(0, 2).toUpperCase())}${c.is_online ? '<span class="status"></span>' : ""}</div>
      <div class="chat-row__body">
        <div class="chat-row__name">${esc(c.name)}<span class="pin">Support</span></div>
        <div class="chat-row__preview">${esc(previewText(c.last))}</div>
      </div>
      <div class="chat-row__meta">${esc(c.last ? ago(c.last.created_at) : "")}${c.unread ? `<span class="unread">${c.unread}</span>` : ""}</div>
    </button>`;
  }

  function initChats() {
    $("#channels").innerHTML = (S.channels || [])
      .map((c) => `<button class="channel" type="button"><div class="avatar avatar--gold">${esc(c.initials)}</div>${esc(c.name)}</button>`)
      .join("");
    // Sample group chats aren't real conversations — hide that section
    const gl = $(".list-label"); if (gl) gl.hidden = true;
    $("#groups").hidden = true;

    const pinned = $("#pinned");
    const convo = $("#convo");
    const msgs = $("#convo-msgs");
    const input = $("#convo-input");
    let agents = [];          // [{name, icon, color, is_online, last, unread, messages, lastId}]
    let current = null;
    let pollTimer = null, listTimer = null;

    const byName = (n) => agents.find((a) => a.name === n);

    async function loadList() {
      try {
        const res = await BW.supportAgents();
        const fresh = res.data && res.data.length ? res.data : [{ name: "BigWin Support", icon: "♛", is_online: true }];
        // Fetch a preview of each conversation without marking it read
        await Promise.all(fresh.map(async (a) => {
          const old = byName(a.name) || {};
          Object.assign(a, { messages: old.messages || [], lastId: old.lastId || 0 });
          try {
            const r = await BW.supportMessages(a.name, 0, true);
            const list = r.data || [];
            a.last = list[list.length - 1] || null;
            a.unread = list.filter((m) => m.sender === "agent" && !m.is_read).length;
          } catch (e) { a.last = null; a.unread = 0; }
        }));
        // Conversations with recent activity first, default agent otherwise
        fresh.sort((x, y) => (y.last ? y.last.id : 0) - (x.last ? x.last.id : 0));
        agents = fresh;
        pinned.innerHTML = agents.map(chatRow).join("");
      } catch (e) {
        pinned.innerHTML = `<p class="empty">${esc(e.message)}</p>`;
      }
    }

    function msgHtml(m) {
      const mine = m.sender === "player";
      const body = IMG_RE.test(m.message)
        ? `<img src="${m.message}" alt="Photo" style="border-radius:10px;max-height:260px">`
        : esc(m.message).replace(/\n/g, "<br>");
      const time = parseTime(m.created_at);
      const stamp = time ? `<small style="display:block;opacity:.6;font-size:.7rem;margin-top:4px;text-align:right">${time.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</small>` : "";
      return `<div class="msg ${mine ? "msg--me" : "msg--them"}${m.pending ? " msg--pending" : ""}"${m.pending ? ' style="opacity:.6"' : ""}>${body}${stamp}</div>`;
    }
    function renderMsgs() {
      const nearBottom = msgs.scrollHeight - msgs.scrollTop - msgs.clientHeight < 80;
      msgs.innerHTML = current.messages.length
        ? current.messages.map(msgHtml).join("")
        : `<p class="empty">Say hi 👋 — our team usually replies within a few minutes.</p>`;
      if (nearBottom || current.justOpened) msgs.scrollTop = msgs.scrollHeight;
      current.justOpened = false;
    }

    async function fetchNew() {
      if (!current) return;
      const c = current;
      try {
        const r = await BW.supportMessages(c.name, c.lastId);
        const list = r.data || [];
        if (c !== current) return;
        if (list.length) {
          c.messages = c.messages.filter((m) => !m.pending).concat(list);
          c.lastId = list[list.length - 1].id;
          c.last = list[list.length - 1];
          renderMsgs();
        }
      } catch (e) { /* network blip — try again on the next poll */ }
    }

    const open = async (name, push = true) => {
      current = byName(name);
      if (!current) return;
      $("#convo-name").textContent = current.name;
      $("#convo-status").textContent = current.is_online ? "Online" : "Usually replies in minutes";
      const av = $("#convo-avatar");
      av.textContent = current.icon || current.name.slice(0, 2).toUpperCase();
      av.style.background = current.color || "";
      av.style.color = current.color ? "#fff" : "";
      av.classList.toggle("avatar--gold", !current.color);
      current.unread = 0;
      const row = $(`[data-chat="${CSS.escape(name)}"]`);
      if (row) { row.classList.remove("chat-row--unread"); const u = $(".unread", row); if (u) u.remove(); }
      current.justOpened = true;
      convo.hidden = false;
      document.body.style.overflow = "hidden";
      if (push) history.pushState({ chat: name }, "", `?chat=${encodeURIComponent(name)}`);
      renderMsgs();
      await fetchNew();
      clearInterval(pollTimer);
      pollTimer = setInterval(fetchNew, 4000);
      // Don't pop the keyboard on phones just from opening the chat
      if (matchMedia("(hover: hover)").matches) input.focus();
    };
    const close = () => {
      convo.hidden = true; document.body.style.overflow = ""; current = null;
      clearInterval(pollTimer);
      loadList();
    };

    pinned.addEventListener("click", (e) => {
      const row = e.target.closest("[data-chat]");
      if (row) open(row.dataset.chat);
    });
    $("#convo-back").addEventListener("click", () => (history.state && history.state.chat ? history.back() : (history.replaceState(null, "", location.pathname), close())));
    window.addEventListener("popstate", () => {
      const id = new URLSearchParams(location.search).get("chat");
      id ? open(id, false) : close();
    });

    $("#convo-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text || !current) return;
      const c = current;
      input.value = "";
      const temp = { sender: "player", message: text, pending: true, created_at: new Date().toISOString() };
      c.messages.push(temp);
      c.justOpened = true; // scroll to the new message
      renderMsgs();
      try {
        await BW.sendSupportMessage(c.name, text);
        await fetchNew();
      } catch (err) {
        c.messages = c.messages.filter((m) => m !== temp);
        if (c === current) renderMsgs();
        input.value = text;
        toast(err.message);
      }
    });

    // Pause polling while the tab is in the background
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) { clearInterval(pollTimer); clearInterval(listTimer); return; }
      if (current) { fetchNew(); pollTimer = setInterval(fetchNew, 4000); }
      else loadList();
      listTimer = setInterval(() => !current && loadList(), 20000);
    });

    pinned.innerHTML = `<p class="empty">Loading chats…</p>`;
    loadList().then(() => {
      const startId = new URLSearchParams(location.search).get("chat");
      if (startId && byName(startId)) open(startId, false);
    });
    listTimer = setInterval(() => !current && loadList(), 20000);
  }

  /* ---------- Payments page ---------- */
  function txRow(p) {
    const isLoad = p.type === "Load";
    return `<div class="tx">
      <div class="tx__icon ${isLoad ? "tx__icon--in" : "tx__icon--out"}">${isLoad ? "↓" : "↑"}</div>
      <div class="tx__body"><strong>${esc(p.type)} · ${esc(p.game)}</strong><small>${esc(p.method)} · ${esc(p.date)}</small></div>
      <div class="tx__amt">$${Number(p.amount).toFixed(2)}<small class="status--${esc(p.status)}">${esc(p.status)}</small></div>
    </div>`;
  }

  function initPayments() {
    const gameSel = $("#pay-game");
    const methodSel = $("#pay-method");
    gameSel.innerHTML = '<option value="">Select a game</option>' + S.games.map((g) => `<option>${esc(g.name)}</option>`).join("");
    methodSel.innerHTML = '<option value="">Select a method</option>' + S.paymentMethods.map((m) => `<option>${esc(m)}</option>`).join("");

    const history = $("#pay-history");
    const renderHistory = (list) => (history.innerHTML = list.length ? list.map(txRow).join("") : '<p class="empty">No transactions yet.</p>');
    renderHistory(api.payments());

    // Load / Cashout toggle
    let type = "Load";
    const submit = $("#pay-submit");
    $$(".segmented button").forEach((b) =>
      b.addEventListener("click", () => {
        $$(".segmented button").forEach((x) => x.setAttribute("aria-pressed", "false"));
        b.setAttribute("aria-pressed", "true");
        type = b.dataset.type;
        submit.textContent = type === "Load" ? "Request load" : "Request cashout";
        $("#pay-method-label").firstChild.textContent = type === "Load" ? "Pay with " : "Receive to ";
      })
    );

    // Quick amounts
    const amount = $("#pay-amount");
    $$(".amounts button").forEach((b) =>
      b.addEventListener("click", () => {
        amount.value = b.dataset.amount;
        $$(".amounts button").forEach((x) => x.classList.toggle("active", x === b));
      })
    );
    amount.addEventListener("input", () => $$(".amounts button").forEach((x) => x.classList.remove("active")));

    $("#pay-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const value = parseFloat(amount.value);
      if (!gameSel.value) return toast("Please choose a game.");
      if (!value || value < 5) return toast("Minimum amount is $5.");
      if (!methodSel.value) return toast("Please choose a payment method.");
      // TODO: POST to /api/payments and show real status.
      const list = api.savePayment({ type, game: gameSel.value, amount: value, method: methodSel.value, status: "Pending", date: "Just now" });
      renderHistory(list);
      e.target.reset();
      $$(".amounts button").forEach((x) => x.classList.remove("active"));
      toast(`${type} request sent. Support will message you in Chats.`);
    });
  }

  /* ---------- Game ID page (live: server creates the account on the game's agent portal) ---------- */
  const gameInfo = (key) => S.games.find((g) => g.key === key) || { key, name: key, image: "" };

  function credCard(acc, password) {
    const g = gameInfo(acc.game);
    const icon = g.image
      ? `<div class="avatar avatar--sm" style="background:url('../${esc(g.image)}') center/cover"></div>`
      : `<div class="avatar avatar--gold avatar--sm">${esc(g.name.slice(0, 2).toUpperCase())}</div>`;
    const pw = password
      ? `<code>${esc(password)}</code><button class="copy-btn" data-copy="${esc(password)}">Copy</button>`
      : `<code>••••••••</code><button class="copy-btn" data-show="${esc(acc.game)}">Show</button>`;
    return `<div class="cred" data-game="${esc(acc.game)}">
      <div class="cred__head">${icon}<strong>${esc(g.name)}</strong></div>
      <div class="cred__row"><span>Username</span><code>${esc(acc.game_username)}</code><button class="copy-btn" data-copy="${esc(acc.game_username)}">Copy</button></div>
      <div class="cred__row" data-pw>${`<span>Password</span>`}${pw}</div>
    </div>`;
  }

  async function initGameIds() {
    const wrap = $("#cred-list");
    const sel = $("#gid-game");
    const form = $("#gid-form");
    const submit = $("button[type=submit]", form);
    let accounts = [];
    let active = [];

    const renderSelect = () => {
      const owned = new Set(accounts.map((a) => a.game));
      // Show games in the same order as the home page; only games the admin has connected
      const avail = S.games.filter((g) => active.includes(g.key) && !owned.has(g.key));
      sel.innerHTML = avail.length
        ? '<option value="">Select a game</option>' + avail.map((g) => `<option value="${esc(g.key)}">${esc(g.name)}</option>`).join("")
        : `<option value="">${active.length ? "You have every available game" : "No games available yet"}</option>`;
      sel.disabled = submit.disabled = !avail.length;
    };
    const renderList = (fresh = {}) => {
      wrap.innerHTML = accounts.length
        ? accounts.map((a) => credCard(a, fresh[a.game])).join("")
        : '<p class="empty">No Game IDs yet. Pick a game below to get one instantly.</p>';
    };

    wrap.innerHTML = '<p class="empty">Loading your Game IDs…</p>';
    try {
      const [st, acc] = await Promise.all([BW.gamesStatus(), BW.gameAccounts()]);
      active = st.data.active || [];
      accounts = acc.data || [];
    } catch (err) {
      wrap.innerHTML = `<p class="empty">${esc(err.message)}</p>`;
      sel.innerHTML = '<option value="">Unavailable</option>';
      sel.disabled = submit.disabled = true;
      return;
    }
    renderList();
    renderSelect();

    wrap.addEventListener("click", async (e) => {
      const copy = e.target.closest("[data-copy]");
      if (copy) {
        try { await navigator.clipboard.writeText(copy.dataset.copy); toast("Copied to clipboard."); }
        catch (err) { toast("Couldn't copy — please copy it manually."); }
        return;
      }
      const show = e.target.closest("[data-show]");
      if (show) {
        show.disabled = true;
        try {
          const res = await BW.gameLogin(show.dataset.show);
          const row = show.closest("[data-pw]");
          row.innerHTML = `<span>Password</span><code>${esc(res.data.password)}</code><button class="copy-btn" data-copy="${esc(res.data.password)}">Copy</button>`;
        } catch (err) {
          toast(err.message);
          show.disabled = false;
        }
      }
    });

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const key = sel.value;
      if (!key) return toast("Please choose a game.");
      const name = gameInfo(key).name;
      const label = submit.textContent;
      submit.disabled = sel.disabled = true;
      submit.textContent = `Creating your ${name} account…`;
      try {
        const res = await BW.createGameAccount(key);
        accounts.unshift({ game: key, game_username: res.data.username });
        renderList({ [key]: res.data.password });
        toast(`Your ${name} Game ID is ready!`);
        wrap.scrollIntoView({ behavior: "smooth", block: "start" });
      } catch (err) {
        toast(err.message);
      } finally {
        submit.textContent = label;
        renderSelect();
      }
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    // Members only: send signed-out visitors to the login screen
    const user = api.user();
    if (!user || !user.token) {
      location.replace("../auth.html?tab=login");
      return;
    }
    initHeader();
    const page = document.body.dataset.page;
    if (page === "chats") initChats();
    if (page === "payments") initPayments();
    if (page === "game-id") initGameIds();
  });
})();
