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

  document.addEventListener("DOMContentLoaded", () => {
    initMenu();
    initActiveNav();
    initBrandText();
    initChatWidget();
  });
})();
