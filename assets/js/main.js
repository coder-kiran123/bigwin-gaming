/* ==========================================================================
   BigWin Gaming — Shared Script (every public page)
   Mobile menu, active nav link, footer year, live chat widget.
   ========================================================================== */

(function () {
  "use strict";
  const S = window.SITE;
  const $ = (s, c = document) => c.querySelector(s);
  const $$ = (s, c = document) => Array.from(c.querySelectorAll(s));

  // Escape text before inserting into HTML (all dynamic content goes through this)
  window.esc = (str) =>
    String(str).replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));

  function initMenu() {
    const toggle = $(".menu-toggle");
    const panel = $(".nav-panel");
    if (!toggle || !panel) return;
    toggle.addEventListener("click", () => {
      const open = toggle.getAttribute("aria-expanded") === "true";
      toggle.setAttribute("aria-expanded", String(!open));
      panel.classList.toggle("open", !open);
    });
    $$("a", panel).forEach((a) =>
      a.addEventListener("click", () => {
        toggle.setAttribute("aria-expanded", "false");
        panel.classList.remove("open");
      })
    );
  }

  function initActiveNav() {
    const page = location.pathname.split("/").pop() || "index.html";
    $$(".nav a").forEach((a) => {
      if (a.getAttribute("href") === page) a.classList.add("active");
    });
  }

  function initBrandText() {
    $$("[data-brand]").forEach((el) => (el.textContent = S.brand.name));
    $$("[data-year]").forEach((el) => (el.textContent = S.brand.year));
    $$("[data-agent]").forEach((el) => (el.textContent = S.brand.supportAgent));
  }

  function initChatWidget() {
    const card = $(".chat-card");
    const fab = $(".chat-fab");
    if (!card || !fab) return;
    const close = $(".chat-card__close", card);
    const setOpen = (open) => {
      card.hidden = !open;
      fab.setAttribute("aria-expanded", String(open));
      try { sessionStorage.setItem("bw-chat-dismissed", open ? "0" : "1"); } catch (e) {}
    };
    fab.addEventListener("click", () => setOpen(card.hidden));
    close.addEventListener("click", () => setOpen(false));

    // Pop the greeting once per visit after a short delay
    let dismissed = false;
    try { dismissed = sessionStorage.getItem("bw-chat-dismissed") === "1"; } catch (e) {}
    if (!dismissed) setTimeout(() => setOpen(true), 2500);
  }

  /* "Message us on Facebook / Telegram" buttons — any element with [data-social] */
  const SOCIAL_ICONS = {
    facebook: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2C6.5 2 2 6.1 2 11.3c0 2.9 1.4 5.5 3.7 7.2V22l3.4-1.9c.9.3 1.9.4 2.9.4 5.5 0 10-4.1 10-9.2S17.5 2 12 2zm1 12.4-2.6-2.7-5 2.7 5.5-5.8 2.6 2.7 5-2.7-5.5 5.8z"/></svg>',
    telegram: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M21.9 4.3 18.7 19.4c-.2 1-.9 1.3-1.7.8l-4.8-3.5-2.3 2.2c-.3.3-.5.5-1 .5l.3-4.9 8.9-8c.4-.3-.1-.5-.6-.2L6.5 13.2 1.8 11.7c-1-.3-1-1 .2-1.5L20.6 3c.9-.3 1.6.2 1.3 1.3z"/></svg>',
  };
  // Accepts "BigWin", "@BigWin" or a full facebook.com / m.me / t.me link
  function socialLink(kind, value) {
    let v = String(value || "").trim();
    if (!v) return "";
    if (/^https?:\/\//i.test(v)) {
      try {
        const u = new URL(v);
        const seg = u.pathname.split("/").filter(Boolean);
        if (kind === "facebook" && /(^|\.)(facebook\.com|fb\.com|m\.me)$/i.test(u.hostname)) v = seg[0] === "profile.php" ? u.searchParams.get("id") || "" : seg[0] || "";
        else if (kind === "telegram" && /(^|\.)(t\.me|telegram\.me)$/i.test(u.hostname)) v = seg[0] || "";
        else return "";
      } catch (e) { return ""; }
    }
    v = v.replace(/^@/, "");
    if (!/^[A-Za-z0-9._-]{2,64}$/.test(v)) return "";
    return kind === "facebook" ? `https://m.me/${v}` : `https://t.me/${v}`;
  }
  function initSocial() {
    renderSocial(S.social || {});
    // Links saved in the admin panel take priority over config.js
    if (location.protocol.startsWith("http")) {
      fetch(`${S.apiBase || ""}/api/site/social`)
        .then((r) => r.json())
        .then((j) => {
          if (!j || !j.success || !j.data) return;
          const d = j.data, cfg = S.social || {};
          renderSocial({ facebook: d.facebook || cfg.facebook, telegram: d.telegram || cfg.telegram });
        })
        .catch(() => {});
    }
  }
  function renderSocial(cfg) {
    const links = [
      ["facebook", "Messenger", socialLink("facebook", cfg.facebook)],
      ["telegram", "Telegram", socialLink("telegram", cfg.telegram)],
    ];
    // Both buttons always show; one without a link (set in Admin → Contact Links) is greyed out as "soon"
    $$("[data-social]").forEach((box) => {
      box.innerHTML = links
        .map(([k, label, href]) => href
          ? `<a class="social-btn social-btn--${k}" href="${esc(href)}" target="_blank" rel="noopener">${SOCIAL_ICONS[k]}<span>${esc(label)}</span></a>`
          : `<span class="social-btn social-btn--${k} social-btn--off" aria-disabled="true" title="Coming soon">${SOCIAL_ICONS[k]}<span>${esc(label)}</span></span>`)
        .join("");
      box.hidden = false;
    });
    $$("[data-social-wrap]").forEach((w) => (w.hidden = false));
  }

  document.addEventListener("DOMContentLoaded", () => {
    initSocial();
    initMenu();
    initActiveNav();
    initBrandText();
    initChatWidget();
  });
})();
