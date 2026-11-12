/* ==========================================================================
   BigWin Gaming — API client
   Talks to the Flask server in server/. Every call returns the server's
   JSON ({ success, msg, data }) or throws an Error with a readable message.
   ========================================================================== */

window.BW = (function () {
  "use strict";
  const BASE = ((window.SITE && window.SITE.apiBase) || "") + "/api";
  const KEY = "bw-session";

  /* ---------- Session (player id + signed token) ---------- */
  const session = {
    get() {
      try { return JSON.parse(localStorage.getItem(KEY)) || null; } catch (e) { return null; }
    },
    set(p) {
      const s = {
        id: p.id || p.player_id,
        username: p.username,
        email: p.email || "",
        firstName: p.first_name || "",
        lastName: p.last_name || "",
        token: p.token,
      };
      try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) {}
      return s;
    },
    clear() {
      try { localStorage.removeItem(KEY); localStorage.removeItem("bw-photo"); } catch (e) {}
    },
  };

  /* ---------- Request helper ---------- */
  async function request(path, { method = "GET", body, auth = false } = {}) {
    const headers = { "Content-Type": "application/json" };
    if (auth) {
      const s = session.get();
      if (s && s.token) headers["X-Player-Token"] = s.token;
    }
    let res, json;
    try {
      res = await fetch(BASE + path, { method, headers, body: body ? JSON.stringify(body) : undefined });
    } catch (e) {
      throw new Error("Can't reach the server. Check your connection and try again.");
    }
    try { json = await res.json(); } catch (e) {
      throw new Error(res.status === 404 ? "Server not running — start it with: python3 server/app.py" : `Server error (${res.status})`);
    }
    if (res.status === 401 && auth) {
      session.clear();
      const inApp = location.pathname.includes("/app/");
      location.href = (inApp ? "../" : "") + "auth.html?tab=login&expired=1";
      throw new Error(json.msg || "Please sign in again.");
    }
    if (!json.success) {
      const e = new Error(json.msg || "Something went wrong. Please try again.");
      e.code = json.code;
      throw e;
    }
    return json;
  }

  const pid = () => (session.get() || {}).id;

  return {
    session,
    // Auth
    register: (body) => request("/auth/register", { method: "POST", body }),
    login: (username, password) => request("/auth/login", { method: "POST", body: { username, password } }),
    google: (id_token, referred_by) => request("/auth/google", { method: "POST", body: { id_token, referred_by } }),
    // Games
    gamesStatus: () => request("/games/status"),
    gameAccounts: () => request(`/players/${pid()}/game-accounts`, { auth: true }),
    gameLogin: (game) => request(`/players/${pid()}/game-login?game=${encodeURIComponent(game)}`, { auth: true }),
    createGameAccount: (game) => request(`/players/${pid()}/create-game-account`, { method: "POST", body: { game }, auth: true }),
  };
})();
