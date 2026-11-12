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

  /* ---------- Data layer: swap these for API calls ---------- */
  const api = {
    user: () => store.get("bw-user", S.demoUser),
    chats: () => S.chats,
    groups: () => S.groups,
    payments: () => store.get("bw-payments", S.payments),
    savePayment(p) { const list = [p, ...api.payments()]; store.set("bw-payments", list); return list; },
    gameIds: () => S.gameIds,
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
    const name = [user.firstName, user.lastName].filter(Boolean).join(" ");
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
        store.remove("bw-user");
        store.remove("bw-photo");
        location.href = "../auth.html";
      })
    );
  }

  /* ---------- Chats page ---------- */
  function chatRow(c, pinned) {
    const cls = ["chat-row", pinned ? "chat-row--pinned" : "", c.unread ? "chat-row--unread" : ""].join(" ");
    return `<button class="${cls}" data-chat="${esc(c.id)}">
      <div class="avatar ${c.gold ? "avatar--gold" : ""}">${esc(c.initials)}${c.online ? '<span class="status"></span>' : ""}</div>
      <div class="chat-row__body">
        <div class="chat-row__name">${esc(c.name)}${pinned ? '<span class="pin">Pinned</span>' : ""}</div>
        <div class="chat-row__preview">${esc(c.preview)}</div>
      </div>
      <div class="chat-row__meta">${esc(c.time)}${c.unread ? `<span class="unread">${c.unread}</span>` : ""}</div>
    </button>`;
  }

  function initChats() {
    $("#channels").innerHTML = S.channels
      .map((c) => `<button class="channel" type="button"><div class="avatar avatar--gold">${esc(c.initials)}</div>${esc(c.name)}</button>`)
      .join("");
    $("#pinned").innerHTML = api.chats().map((c) => chatRow(c, true)).join("");
    $("#groups").innerHTML = api.groups().map((c) => chatRow(c, false)).join("");

    const all = [...api.chats(), ...api.groups()];
    const convo = $("#convo");
    const msgs = $("#convo-msgs");
    let current = null;

    const renderMsgs = () => {
      msgs.innerHTML = current.messages
        .map((m) => {
          const mine = m.from === "me";
          const from = !mine && m.from !== "them" ? `<span class="msg__from">${esc(m.from)}</span>` : "";
          return `<div class="msg ${mine ? "msg--me" : "msg--them"}">${from}${esc(m.text)}</div>`;
        })
        .join("");
      msgs.scrollTop = msgs.scrollHeight;
    };

    const open = (id, push = true) => {
      current = all.find((c) => c.id === id);
      if (!current) return;
      $("#convo-name").textContent = current.name;
      $("#convo-status").textContent = current.online ? "Online" : "";
      const av = $("#convo-avatar");
      av.textContent = current.initials;
      av.classList.toggle("avatar--gold", !!current.gold);
      current.unread = 0;
      const row = $(`[data-chat="${CSS.escape(id)}"]`);
      if (row) { row.classList.remove("chat-row--unread"); const u = $(".unread", row); if (u) u.remove(); }
      renderMsgs();
      convo.hidden = false;
      document.body.style.overflow = "hidden";
      if (push) history.pushState({ chat: id }, "", `?chat=${encodeURIComponent(id)}`);
      $("#convo-input").focus();
    };
    const close = () => { convo.hidden = true; document.body.style.overflow = ""; current = null; };

    document.addEventListener("click", (e) => {
      const row = e.target.closest("[data-chat]");
      if (row) open(row.dataset.chat);
    });
    $("#convo-back").addEventListener("click", () => history.back());
    window.addEventListener("popstate", () => {
      const id = new URLSearchParams(location.search).get("chat");
      id ? open(id, false) : close();
    });

    $("#convo-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const input = $("#convo-input");
      const text = input.value.trim();
      if (!text || !current) return;
      // TODO: send via your chat backend / websocket.
      current.messages.push({ from: "me", text });
      input.value = "";
      renderMsgs();
    });

    const startId = new URLSearchParams(location.search).get("chat");
    if (startId) open(startId, false);
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

  /* ---------- Game ID page ---------- */
  function initGameIds() {
    const wrap = $("#cred-list");
    const ids = api.gameIds();
    wrap.innerHTML = ids.length
      ? ids.map((c) => `<div class="cred">
          <div class="cred__head"><div class="avatar avatar--gold avatar--sm">${esc(c.game.slice(0, 2).toUpperCase())}</div><strong>${esc(c.game)}</strong></div>
          <div class="cred__row"><span>Username</span><code>${esc(c.username)}</code><button class="copy-btn" data-copy="${esc(c.username)}">Copy</button></div>
          <div class="cred__row"><span>Password</span><code>${esc(c.password)}</code><button class="copy-btn" data-reveal>Request</button></div>
        </div>`).join("")
      : '<p class="empty">No Game IDs yet. Request one below.</p>';

    wrap.addEventListener("click", async (e) => {
      const copy = e.target.closest("[data-copy]");
      if (copy) {
        try { await navigator.clipboard.writeText(copy.dataset.copy); toast("Copied to clipboard."); }
        catch (err) { toast("Couldn't copy — please copy it manually."); }
      }
      if (e.target.closest("[data-reveal]")) toast("For security, support will send your password in Chats.");
    });

    const sel = $("#gid-game");
    sel.innerHTML = '<option value="">Select a game</option>' + S.games.map((g) => `<option>${esc(g.name)}</option>`).join("");
    $("#gid-form").addEventListener("submit", (e) => {
      e.preventDefault();
      if (!sel.value) return toast("Please choose a game.");
      // TODO: POST to /api/game-ids
      toast(`Game ID requested for ${sel.value}. We'll message you in Chats.`);
      e.target.reset();
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    initHeader();
    const page = document.body.dataset.page;
    if (page === "chats") initChats();
    if (page === "payments") initPayments();
    if (page === "game-id") initGameIds();
  });
})();
