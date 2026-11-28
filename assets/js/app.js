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

  const gameInfo = (key) => S.games.find((g) => g.key === key) || { key, name: key, image: "" };

  /* ---------- Payments page (wallet: server /api/players/<id>/wallet, /api/deposits, /api/withdrawals) ---------- */
  const money = (n) => "$" + Number(n || 0).toFixed(2);
  const TX_LABELS = {
    deposit: ["Added money", "in"], withdrawal: ["Cashout", "out"], add_credits: ["Loaded game", "out"],
    withdraw_credits: ["Game → wallet", "in"], tip: ["Tip", "out"], bonus: ["Bonus", "in"],
    signup_bonus: ["Sign-up bonus", "in"], admin_credit: ["Credit from support", "in"],
  };
  const STATUS = { approved: "Completed", completed: "Completed", pending: "Pending", rejected: "Failed", failed: "Failed" };

  function txRow(t) {
    const [label, dir] = TX_LABELS[t.type] || [t.type.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()), "in"];
    const status = STATUS[t.status] || t.status || "";
    const when = parseTime(t.created_at);
    const sub = [t.notes || t.method || "", when ? when.toLocaleDateString([], { month: "short", day: "numeric" }) : ""].filter(Boolean).join(" · ");
    return `<div class="tx">
      <div class="tx__icon ${dir === "in" ? "tx__icon--in" : "tx__icon--out"}">${dir === "in" ? "↓" : "↑"}</div>
      <div class="tx__body"><strong>${esc(label)}</strong><small>${esc(sub)}</small></div>
      <div class="tx__amt">${money(t.amount)}<small class="status--${esc(status)}">${esc(status)}</small></div>
    </div>`;
  }
  function pendingDepRow(d, methodName) {
    const action = d.payment_url
      ? `<a class="copy-btn" href="${esc(d.payment_url)}" target="_blank" rel="noopener">Pay</a>`
      : d.has_screenshot ? "" : `<button class="copy-btn" type="button" data-receipt="${esc(d.id)}">Upload receipt</button>`;
    return `<div class="tx">
      <div class="tx__icon tx__icon--in">↓</div>
      <div class="tx__body"><strong>Add money · ${esc(methodName || d.method)}</strong><small>${d.has_screenshot ? "Receipt sent — waiting for approval" : "Waiting for your payment"}</small></div>
      <div class="tx__amt">${money(d.amount)}<small class="status--Pending">Pending</small>${action}</div>
    </div>`;
  }

  // Phone photos are often 5–10 MB: shrink to a JPEG that fits the server's 3 MB limit
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
  const safeUrl = (u) => (/^(https?:\/\/|\/|data:image\/(png|jpe?g|webp|gif);base64,)/i.test(u || "") ? u : "");

  async function busyBtn(btn, text, fn) {
    const label = btn.textContent;
    btn.disabled = true; btn.textContent = text;
    try { return await fn(); } finally { btn.disabled = false; btn.textContent = label; }
  }

  async function initPayments() {
    let wallet = { balance: 0, transactions: [], pending_deposits: [] };
    let methods = [], accounts = [], active = [];
    let payingDep = null;   // deposit waiting for a receipt

    /* --- Tabs --- */
    const showPane = (name) => {
      $$(".segmented [data-pane]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.pane === name)));
      $$(".pane").forEach((p) => (p.hidden = p.dataset.pane !== name));
      $("#dep-pay").hidden = true;
    };
    $$(".segmented [data-pane]").forEach((b) => b.addEventListener("click", () => showPane(b.dataset.pane)));

    /* --- Quick amount chips --- */
    $$(".amounts[data-for]").forEach((box) => {
      const input = $("#" + box.dataset.for);
      box.addEventListener("click", (e) => {
        const b = e.target.closest("[data-amount]");
        if (!b) return;
        input.value = b.dataset.amount === "all" ? Math.floor(wallet.balance) : b.dataset.amount;
        $$("button", box).forEach((x) => x.classList.toggle("active", x === b));
      });
      input.addEventListener("input", () => $$("button", box).forEach((x) => x.classList.remove("active")));
    });

    /* --- Data --- */
    const history = $("#pay-history");
    function renderWallet() {
      $("#wallet-balance").textContent = money(wallet.balance);
      const bonus = $("#wallet-bonus");
      bonus.hidden = !(wallet.bonus_credits > 0);
      bonus.textContent = `+ ${money(wallet.bonus_credits)} bonus credits`;
      const rows = wallet.pending_deposits.map((d) => pendingDepRow(d, (methods.find((m) => m.key === d.method) || {}).name)).concat(wallet.transactions.map(txRow));
      history.innerHTML = rows.length ? rows.join("") : '<p class="empty">No transactions yet.</p>';
    }
    async function loadWallet() {
      try { wallet = (await BW.wallet()).data; renderWallet(); }
      catch (err) { history.innerHTML = `<p class="empty">${esc(err.message)}</p>`; }
    }
    function renderSelects() {
      const opts = methods.length
        ? '<option value="">Select a method</option>' + methods.map((m) => `<option value="${esc(m.key)}">${esc(m.name)}</option>`).join("")
        : '<option value="">No payment methods yet — message support</option>';
      $("#dep-method").innerHTML = opts;
      $("#wd-method").innerHTML = methods.length
        ? '<option value="">Select a method</option>' + methods.map((m) => `<option value="${esc(m.key)}">${esc(m.name)}</option>`).join("")
        : (S.paymentMethods || []).map((m) => `<option>${esc(m)}</option>`).join("");
      const name = (k) => (gameInfo(k).name);
      const loadable = accounts.filter((a) => active.includes(a.game));
      $("#load-game").innerHTML = loadable.length
        ? '<option value="">Select a game</option>' + loadable.map((a) => `<option value="${esc(a.game)}">${esc(name(a.game))}</option>`).join("")
        : '<option value="">Get a Game ID first (Game ID tab)</option>';
      $("#g2w-game").innerHTML = accounts.length
        ? '<option value="">Select a game</option>' + accounts.map((a) => `<option value="${esc(a.game)}">${esc(name(a.game))}</option>`).join("")
        : '<option value="">No Game IDs yet</option>';
    }

    $("#wallet-refresh").addEventListener("click", loadWallet);
    await Promise.all([
      loadWallet(),
      BW.paymentMethods().then((r) => (methods = r.data || [])).catch(() => {}),
      BW.gameAccounts().then((r) => (accounts = r.data || [])).catch(() => {}),
      BW.gamesStatus().then((r) => (active = r.data.active || [])).catch(() => {}),
    ]);
    renderSelects();
    renderWallet();   // again, now that method names are known

    /* --- Add money --- */
    function showPayBox(dep) {
      payingDep = dep;
      const m = methods.find((x) => x.key === dep.method) || { name: dep.method };
      $("#dep-pay-title").textContent = `Send ${money(dep.amount)} with ${m.name}`;
      $("#dep-pay-sub").textContent = `Request #${dep.id}. Send the exact amount, then upload your receipt.`;
      const parts = [];
      if (m.address) parts.push(`<div class="cred__row"><span>Send to</span><code>${esc(m.address)}</code><button class="copy-btn" type="button" data-copy="${esc(m.address)}">Copy</button></div>`);
      const qr = safeUrl(m.qr_image && (m.qr_image.startsWith("data:") || m.qr_image.startsWith("http") || m.qr_image.startsWith("/") ? m.qr_image : "/" + m.qr_image));
      if (qr) parts.push(`<img class="pay-qr" src="${esc(qr)}" alt="${esc(m.name)} QR code">`);
      const link = /^https?:\/\//i.test(m.payment_link || "") ? m.payment_link : "";
      if (link) parts.push(`<a class="btn btn--outline-gold btn--block mt-16" href="${esc(link)}" target="_blank" rel="noopener">Open ${esc(m.name)}</a>`);
      if (m.instructions) parts.push(`<p class="hint mt-16">${esc(m.instructions).replace(/\n/g, "<br>")}</p>`);
      if (!parts.length) parts.push('<p class="hint">Support will send you the payment details in Chats.</p>');
      $("#dep-pay-details").innerHTML = parts.join("");
      $("#dep-shot").value = "";
      $$(".pane").forEach((p) => (p.hidden = true));
      $("#dep-pay").hidden = false;
      $("#dep-pay").scrollIntoView({ behavior: "smooth", block: "start" });
    }

    $("#f-deposit").addEventListener("submit", async (e) => {
      e.preventDefault();
      const amount = parseFloat($("#dep-amount").value);
      const method = $("#dep-method").value;
      if (!amount || amount < 5) return toast("Minimum amount is $5.");
      if (!method) return toast("Please choose a payment method.");
      await busyBtn($("button[type=submit]", e.target), "Creating request…", async () => {
        try {
          const r = (await BW.deposit(amount, method)).data;
          e.target.reset();
          $$(".amounts button").forEach((x) => x.classList.remove("active"));
          loadWallet();
          if (r.payment_url && /^https?:\/\//i.test(r.payment_url)) {
            toast("Opening the secure payment page…");
            location.href = r.payment_url;
          } else {
            showPayBox({ id: r.request_id, amount, method });
          }
        } catch (err) { toast(err.message); }
      });
    });

    $("#dep-shot-send").addEventListener("click", async (e) => {
      const file = $("#dep-shot").files[0];
      if (!payingDep) return;
      if (!file) return toast("Choose your payment screenshot first.");
      await busyBtn(e.currentTarget, "Uploading…", async () => {
        try {
          const img = await shrinkImage(file);
          await BW.depositScreenshot(payingDep.id, img);
          toast("Receipt sent! We'll add the money once it's checked.");
          payingDep = null;
          showPane("deposit");
          loadWallet();
        } catch (err) { toast(err.message); }
      });
    });
    $("#dep-pay-later").addEventListener("click", () => {
      toast("You can upload the receipt later from History.");
      payingDep = null; showPane("deposit");
    });
    history.addEventListener("click", (e) => {
      const b = e.target.closest("[data-receipt]");
      if (!b) return;
      const d = wallet.pending_deposits.find((x) => String(x.id) === b.dataset.receipt);
      if (d) showPayBox(d);
    });
    document.addEventListener("click", async (e) => {
      const c = e.target.closest("#dep-pay [data-copy]");
      if (!c) return;
      try { await navigator.clipboard.writeText(c.dataset.copy); toast("Copied."); } catch (err) { toast("Couldn't copy — please copy it manually."); }
    });

    /* --- Load game --- */
    $("#f-load").addEventListener("submit", async (e) => {
      e.preventDefault();
      const game = $("#load-game").value;
      const amount = parseFloat($("#load-amount").value);
      if (!game) return toast("Please choose a game.");
      if (!amount || amount <= 0) return toast("Enter an amount.");
      await busyBtn($("button[type=submit]", e.target), "Loading…", async () => {
        try {
          const r = await BW.loadGame(game, amount);
          toast(r.msg || "Game loaded!");
          e.target.reset();
          loadWallet();
        } catch (err) {
          if (err.data && err.data.insufficient) {
            toast(`Your wallet is ${money(err.data.shortfall)} short. Add money first.`);
            showPane("deposit");
            $("#dep-amount").value = Math.max(5, Math.ceil(err.data.shortfall));
          } else toast(err.message);
        }
      });
    });

    /* --- Cash out: game → wallet --- */
    $("#g2w-game").addEventListener("change", async (e) => {
      const game = e.target.value, out = $("#g2w-bal");
      out.textContent = "";
      if (!game) return;
      out.textContent = "Checking game balance…";
      try {
        const r = (await BW.gameBalance(game)).data;
        if ($("#g2w-game").value !== game) return;
        out.textContent = `Balance in game: ${money(r.balance)}`;
        $("#g2w-amount").value = r.balance > 0 ? Number(r.balance).toFixed(2) : "";
      } catch (err) { out.textContent = err.message; }
    });
    $("#f-g2w").addEventListener("submit", async (e) => {
      e.preventDefault();
      const game = $("#g2w-game").value;
      const amount = parseFloat($("#g2w-amount").value);
      if (!game) return toast("Please choose a game.");
      if (!amount || amount <= 0) return toast("Enter an amount.");
      await busyBtn($("button[type=submit]", e.target), "Moving…", async () => {
        try {
          const r = await BW.gameToWallet(game, amount);
          toast(r.msg || "Added to your wallet.");
          e.target.reset(); $("#g2w-bal").textContent = "";
          await loadWallet();
          $("#wd-amount").value = Number(wallet.balance).toFixed(2);
        } catch (err) { toast(err.message); }
      });
    });

    /* --- Cash out: wallet → player --- */
    $("#f-withdraw").addEventListener("submit", async (e) => {
      e.preventDefault();
      const amount = parseFloat($("#wd-amount").value);
      const method = $("#wd-method").value;
      const address = $("#wd-address").value.trim();
      if (!amount || amount <= 0) return toast("Enter an amount.");
      if (amount > wallet.balance + 0.001) return toast(`Your wallet has ${money(wallet.balance)}. Move winnings from a game first.`);
      if (!method) return toast("Please choose how to receive it.");
      if (!address) return toast("Enter where we should send it.");
      await busyBtn($("button[type=submit]", e.target), "Sending request…", async () => {
        try {
          const r = await BW.withdraw(amount, method, address);
          e.target.reset();
          loadWallet();
          if (r.data && r.data.payout_url && /^https?:\/\//i.test(r.data.payout_url)) {
            toast("Cashout ready — opening your payout page…");
            setTimeout(() => (location.href = r.data.payout_url), 900);
          } else toast("Cashout requested. We'll message you in Chats when it's sent.");
        } catch (err) { toast(err.message); }
      });
    });

    // Back from a card checkout (?paid=…) or a fresh visit: keep history current
    document.addEventListener("visibilitychange", () => { if (!document.hidden) loadWallet(); });
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
