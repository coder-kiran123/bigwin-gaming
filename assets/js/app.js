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
    // Only our own image data or an https photo (Google sign-in) — nothing that could break out of url("")
    const okSrc = (src) => typeof src === "string" &&
      /^(data:image\/(png|jpe?g|webp|gif);base64,[A-Za-z0-9+/=]+|https:\/\/[^\s"'()\\]+)$/.test(src);
    const applyPhoto = (src) => {
      if (!avatar || !okSrc(src)) return;
      avatar.style.backgroundImage = `url("${src}")`;
      avatar.firstChild.textContent = "";
    };
    // Cached photo first (instant), then the one saved on the server (same on every device)
    applyPhoto(store.get("bw-photo", null));
    BW.getAvatar().then((r) => {
      const src = r.data && r.data.avatar;
      if (src) { store.set("bw-photo", src); applyPhoto(src); }
    }).catch(() => {});

    const input = $("#upload-input");
    const btn = $(".upload-btn");
    if (btn && input) {
      btn.addEventListener("click", () => input.click());
      input.addEventListener("change", async () => {
        const file = input.files[0];
        input.value = "";
        if (!file) return;
        try {
          const src = await shrinkImage(file, 400);
          await BW.setAvatar(src);
          store.set("bw-photo", src);
          applyPhoto(src);
          toast("Profile photo updated.");
        } catch (err) { toast(err.message); }
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

  const gameInfo = (key) => S.games.find((g) => g.key === key) || { key, name: key, image: "" };

  /* ---------- Payments page: pick game → amount → method → pay → support loads it by hand ----------
     Server: /api/players/<id>/load-requests. Support taps "Loaded" (admin or Telegram) and the
     player gets a message in Chats. */
  const money = (n) => "$" + Number(n || 0).toFixed(2);
  const LR_STATUS = { pending: ["Waiting", "Pending"], loaded: ["Loaded", "Completed"], rejected: ["Rejected", "Failed"] };

  function loadRow(r) {
    const g = gameInfo(r.game);
    const [label, cls] = LR_STATUS[r.status] || [r.status, ""];
    const when = parseTime(r.created_at);
    const icon = g.image
      ? `<div class="tx__icon" style="background:url('../${esc(g.image)}') center/cover"></div>`
      : `<div class="tx__icon tx__icon--in">${esc(g.name.slice(0, 2).toUpperCase())}</div>`;
    return `<div class="tx">${icon}
      <div class="tx__body"><strong>${esc(g.name)}</strong><small>${esc([r.method_name || r.method, when ? when.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : ""].filter(Boolean).join(" · "))}</small>${r.status === "rejected" && r.note ? `<small class="status--Failed">${esc(r.note)}</small>` : ""}</div>
      <div class="tx__amt">${money(r.amount)}<small class="status--${cls}">${esc(label)}</small></div>
    </div>`;
  }

  // Phone photos are often 5–10 MB: shrink to a JPEG well under the server's 3 MB limit
  function shrinkImage(file, maxSide = 1600) {
    return new Promise((resolve, reject) => {
      if (!file || !file.type.startsWith("image/")) return reject(new Error("Please choose an image file."));
      const img = new Image();
      const url = URL.createObjectURL(file);
      img.onload = () => {
        const k = Math.min(1, maxSide / Math.max(img.width, img.height));
        const c = document.createElement("canvas");
        c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
        c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
        URL.revokeObjectURL(url);
        resolve(c.toDataURL("image/jpeg", 0.82));
      };
      img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("Couldn't read that image — try another one.")); };
      img.src = url;
    });
  }

  async function busyBtn(btn, text, fn) {
    const label = btn.textContent;
    btn.disabled = true; btn.textContent = text;
    try { return await fn(); } finally { btn.disabled = false; btn.textContent = label; }
  }

  // Brand colour + symbol for well-known payment methods; anything else uses the icon set in admin
  const METHOD_BRAND = {
    cashapp: ["#00d64f", "$"], venmo: ["#008cff", "V"], paypal: ["#003087", "P"], zelle: ["#6d1ed4", "Z"],
    chime: ["#1ec677", "C"], bitcoin: ["#f7931a", "₿"], btc: ["#f7931a", "₿"], usdt: ["#26a17b", "₮"],
    applepay: ["#000000", ""], apple_pay: ["#000000", ""], googlepay: ["#4285f4", "G"], google_pay: ["#4285f4", "G"],
  };

  /* Tile pickers shared by Load and Cash out. Each returns { value(), set(v) }. */
  function gamePicker(grid, moreBtn, games, first = 8) {
    let value = "";
    grid.innerHTML = games.map((g, i) => `
      <button type="button" class="pick pick--game${i >= first ? " is-extra" : ""}" role="radio" aria-checked="false" data-pick="${esc(g.key)}">
        ${g.image ? `<img src="../${esc(g.image)}" alt="" loading="lazy">` : `<span class="pick__art">${esc(g.name.slice(0, 2).toUpperCase())}</span>`}
        <span class="pick__name">${esc(g.name)}</span>
      </button>`).join("");
    const showAll = (all) => {
      grid.classList.toggle("show-all", all);
      moreBtn.textContent = all ? "Show fewer games" : `Show all ${games.length} games`;
    };
    moreBtn.hidden = games.length <= first;
    if (!moreBtn.hidden) {
      showAll(false);
      moreBtn.onclick = () => showAll(!grid.classList.contains("show-all"));
    }
    const set = (v) => {
      value = v;
      $$("[data-pick]", grid).forEach((b) => b.setAttribute("aria-checked", String(b.dataset.pick === v)));
      if (v && games.findIndex((g) => g.key === v) >= first) showAll(true);
    };
    grid.addEventListener("click", (e) => { const b = e.target.closest("[data-pick]"); if (b) set(b.dataset.pick); });
    return { value: () => value, set };
  }

  function methodPicker(grid, methods) {
    let value = "";
    grid.innerHTML = methods.length
      ? methods.map((m) => {
          const [bg, sym] = METHOD_BRAND[String(m.key).toLowerCase()] || ["var(--surface-2)", m.icon || "💳"];
          return `<button type="button" class="pick pick--method" role="radio" aria-checked="false" data-pick="${esc(m.key)}">
            <span class="pick__icon" style="background:${bg}">${esc(sym)}</span><span class="pick__name">${esc(m.name)}</span></button>`;
        }).join("")
      : '<p class="empty">No payment methods yet — message support in Chats.</p>';
    const set = (v) => {
      value = v;
      $$("[data-pick]", grid).forEach((b) => b.setAttribute("aria-checked", String(b.dataset.pick === v)));
    };
    grid.addEventListener("click", (e) => { const b = e.target.closest("[data-pick]"); if (b) set(b.dataset.pick); });
    if (methods.length === 1) set(methods[0].key);
    return { value: () => value, set };
  }

  // $10 / $20 … buttons that fill an amount box
  function amountChips(box) {
    const input = $("#" + box.dataset.for);
    const clear = () => $$("button", box).forEach((x) => x.classList.remove("active"));
    box.addEventListener("click", (e) => {
      const b = e.target.closest("[data-amount]");
      if (!b) return;
      input.value = b.dataset.amount;
      $$("button", box).forEach((x) => x.classList.toggle("active", x === b));
    });
    input.addEventListener("input", clear);
    return { clear };
  }

  async function initPayments() {
    const form = $("#f-load"), coForm = $("#f-cashout"), box = $("#pay-box"), done = $("#pay-ok"), history = $("#pay-history");
    const amountIn = $("#load-amount");
    let methods = [], accounts = [];

    $$(".amounts[data-for]").forEach(amountChips);
    const chipsFor = (id) => ({ clear: () => $$(`.amounts[data-for="${id}"] button`).forEach((x) => x.classList.remove("active")) });

    /* --- Data --- */
    async function loadHistory() {
      try {
        const list = (await BW.loadRequests()).data || [];
        list.forEach((r) => (r.method_name = (methods.find((m) => m.key === r.method) || {}).name));
        history.innerHTML = list.length ? list.map(loadRow).join("") : '<p class="empty">No loads yet.</p>';
      } catch (err) { history.innerHTML = `<p class="empty">${esc(err.message)}</p>`; }
    }
    await Promise.all([
      BW.paymentMethods().then((r) => (methods = r.data || [])).catch(() => {}),
      BW.gameAccounts().then((r) => (accounts = r.data || [])).catch(() => {}),
    ]);
    loadHistory();
    document.addEventListener("visibilitychange", () => { if (!document.hidden) loadHistory(); });

    // Load: every game. Cash out: the player's own games (all games if they have none yet).
    const myGames = S.games.filter((g) => accounts.some((a) => a.game === g.key));
    const loadGame = gamePicker($("#pick-game"), $("#more-games"), S.games);
    const loadMethod = methodPicker($("#pick-method"), methods);
    const coGame = gamePicker($("#co-game"), $("#co-more"), myGames.length ? myGames : S.games);
    const coMethod = methodPicker($("#co-method"), methods);

    // Opened from a game tile elsewhere (?game=juwa) → preselect it
    const pre = new URLSearchParams(location.search).get("game");
    if (pre && S.games.some((g) => g.key === pre)) loadGame.set(pre);

    /* --- Screens --- */
    const showStep = (which) => {
      form.hidden = which !== "form"; coForm.hidden = which !== "cashout";
      box.hidden = which !== "pay"; done.hidden = which !== "done";
      window.scrollTo({ top: 0, behavior: "smooth" });
    };
    const setMode = (mode) => {
      $$("[data-mode]").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.mode === mode)));
      showStep(mode === "cashout" ? "cashout" : "form");
    };
    $$("[data-mode]").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));

    /* --- Load: show how to pay --- */
    let pending = null;   // { game, method, amount }
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const game = loadGame.value(), method = loadMethod.value(), amount = parseFloat(amountIn.value);
      if (!game) return toast("Choose a game first.");
      if (!method) return toast("Choose how you'll pay.");
      if (!amount || amount < 5) return toast("Minimum amount is $5.");
      const g = gameInfo(game);
      const m = methods.find((x) => x.key === method) || { name: method };
      const acc = accounts.find((a) => a.game === game);
      $("#pay-sum").innerHTML = `<strong>${money(amount)}</strong> → ${esc(g.name)}${acc ? ` <small>(${esc(acc.game_username)})</small>` : ""}
        <span>Pay with ${esc(m.name)}</span>`;
      const parts = [];
      if (m.address) parts.push(`<div class="cred__row"><span>Send to</span><code>${esc(m.address)}</code><button class="copy-btn" type="button" data-copy="${esc(m.address)}">Copy</button></div>`);
      const qr = m.qr_image ? (/^(data:image\/|https?:\/\/|\/)/i.test(m.qr_image) ? m.qr_image : "/" + m.qr_image) : "";
      if (qr && /^(data:image\/(png|jpe?g|webp|gif);base64,|https?:\/\/|\/)/i.test(qr)) parts.push(`<img class="pay-qr" src="${esc(qr)}" alt="${esc(m.name)} QR code">`);
      if (/^https?:\/\//i.test(m.payment_link || "")) parts.push(`<a class="btn btn--outline-gold btn--block mt-16" href="${esc(m.payment_link)}" target="_blank" rel="noopener">Open ${esc(m.name)}</a>`);
      if (m.instructions) parts.push(`<p class="hint mt-16">${esc(m.instructions).replace(/\n/g, "<br>")}</p>`);
      if (!parts.length) parts.push('<p class="hint">Tap the button below and support will send you the payment details in Chats.</p>');
      parts.unshift(`<p class="pay-step">Send exactly <strong>${money(amount)}</strong>:</p>`);
      $("#pay-details").innerHTML = parts.join("");
      $("#pay-shot").value = "";
      pending = { game, method, amount };
      showStep("pay");
    });
    $("#pay-back").addEventListener("click", () => showStep("form"));
    box.addEventListener("click", async (e) => {
      const c = e.target.closest("[data-copy]");
      if (!c) return;
      try { await navigator.clipboard.writeText(c.dataset.copy); toast("Copied."); } catch (err) { toast("Couldn't copy — please copy it manually."); }
    });

    /* --- "I've paid" → load request (support loads by hand, taps Loaded) --- */
    $("#pay-done").addEventListener("click", async (e) => {
      if (!pending) return;
      await busyBtn(e.currentTarget, "Sending…", async () => {
        try {
          const file = $("#pay-shot").files[0];
          const shot = file ? await shrinkImage(file) : "";
          const r = await BW.createLoadRequest(pending.game, pending.amount, pending.method, shot);
          $("#pay-ok-text").textContent = `We'll load ${money(pending.amount)} into ${gameInfo(pending.game).name} and message you in Chats as soon as it's done.`;
          form.reset(); chipsFor("load-amount").clear(); loadGame.set("");
          pending = null;
          showStep("done");
          loadHistory();
          if (r.msg) toast(r.msg);
        } catch (err) { toast(err.message); }
      });
    });

    /* --- Cash out → a message to support (handled by hand; also alerts Telegram) --- */
    coForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const game = coGame.value(), methodKey = coMethod.value();
      const amount = parseFloat($("#co-amount").value), address = $("#co-address").value.trim();
      if (!game) return toast("Choose the game to cash out from.");
      if (!methodKey) return toast("Choose how you want to receive it.");
      if (!amount || amount <= 0) return toast("Enter an amount.");
      if (!address) return toast("Enter where we should send it.");
      const m = methods.find((x) => x.key === methodKey) || { name: methodKey };
      const acc = accounts.find((a) => a.game === game);
      const text = `💸 Cashout request\nGame: ${gameInfo(game).name}${acc ? ` (${acc.game_username})` : ""}\n` +
                   `Amount: ${money(amount)}\nSend to: ${m.name} — ${address}`;
      await busyBtn($("button[type=submit]", coForm), "Sending…", async () => {
        try {
          const agents = (await BW.supportAgents()).data || [];
          await BW.sendSupportMessage((agents[0] && agents[0].name) || "BigWin Support", text);
          coForm.reset(); chipsFor("co-amount").clear(); coGame.set("");
          $("#pay-ok-text").textContent = `Support will cash out ${money(amount)} from ${gameInfo(game).name} and message you in Chats when it's sent.`;
          showStep("done");
        } catch (err) { toast(err.message); }
      });
    });

    $("#pay-again").addEventListener("click", () => setMode("load"));
  }

  /* ---------- Game ID page (live: server creates the account on the game's agent portal) ---------- */

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
