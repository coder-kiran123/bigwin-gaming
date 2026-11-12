/* ==========================================================================
   BigWin Gaming — Home page script (index.html)
   Renders the live ticker, stats, games grid and the game sign-up modal.
   ========================================================================== */

(function () {
  "use strict";
  const S = window.SITE;
  const I = window.ICONS;
  const $ = (s, c = document) => c.querySelector(s);

  const initials = (name) =>
    name.replace(/[^A-Za-z0-9 ]/g, "").split(" ").filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();

  function renderTicker() {
    const bar = $(".ticker");
    if (!bar) return;
    if (!S.ticker.enabled || !S.ticker.items.length) { bar.remove(); return; }
    const html = S.ticker.items
      .map((t) => `<span class="ticker__item"><strong>${esc(t.who)}</strong> ${esc(t.action)} <span class="amt">+$${t.amount}</span> on <span class="game">${esc(t.game)}</span></span>`)
      .join("");
    // Duplicate the list so the CSS loop (-50%) is seamless
    $(".ticker__track", bar).innerHTML = html + html;
  }

  function renderStats() {
    const el = $("#stats");
    if (!el) return;
    el.innerHTML = S.stats
      .map((s) => `<div class="stat">${I[s.icon] || ""}<div class="stat__value">${esc(s.value)}</div><div class="stat__label">${esc(s.label)}</div></div>`)
      .join("");
  }

  function renderGames() {
    const grid = $("#games-grid");
    if (!grid) return;
    $("#games-count").textContent = `${S.games.length} Games`;
    grid.innerHTML = S.games
      .map((g, i) => {
        const art = g.image
          ? `<img src="${esc(g.image)}" alt="" loading="lazy">`
          : `<div class="game-tile__art"><span>${esc(initials(g.name))}</span></div>`;
        return `<button class="game-tile" data-index="${i}" aria-label="Play ${esc(g.name)}">
          ${art}<span class="game-tile__play">PLAY</span><span class="game-tile__name">${esc(g.name)}</span>
        </button>`;
      })
      .join("");
  }

  function initModal() {
    const modal = $("#game-modal");
    const grid = $("#games-grid");
    if (!modal || !grid) return;
    let lastFocus = null;

    const open = (game) => {
      lastFocus = document.activeElement;
      $("#modal-title").textContent = game.name;
      $("#modal-play").href = `auth.html?tab=signup&game=${encodeURIComponent(game.name)}`;
      modal.hidden = false;
      document.body.style.overflow = "hidden";
      $(".modal__close", modal).focus();
    };
    const close = () => {
      modal.hidden = true;
      document.body.style.overflow = "";
      if (lastFocus) lastFocus.focus();
    };

    grid.addEventListener("click", (e) => {
      const tile = e.target.closest(".game-tile");
      if (tile) open(S.games[+tile.dataset.index]);
    });
    $(".modal__close", modal).addEventListener("click", close);
    modal.addEventListener("click", (e) => { if (e.target === modal) close(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !modal.hidden) close(); });
  }

  document.addEventListener("DOMContentLoaded", () => {
    renderTicker();
    renderStats();
    renderGames();
    initModal();
  });
})();
