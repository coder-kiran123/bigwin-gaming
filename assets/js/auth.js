/* ==========================================================================
   BigWin Gaming — Auth page script (auth.html)
   Switches between welcome / login / signup views and validates forms.

   BACKEND: The `submitLogin` / `submitSignup` functions are where you call
   your real API (Firebase, Supabase, your own server…). Right now they run
   in DEMO mode: they store the name locally and open the member app.
   ========================================================================== */

(function () {
  "use strict";
  const $ = (s, c = document) => c.querySelector(s);
  const $$ = (s, c = document) => Array.from(c.querySelectorAll(s));
  const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
  const APP_URL = "app/chats.html";

  /* ---------- Views ---------- */
  const titles = { welcome: "Members", login: "Login", signup: "Create account" };
  function show(view, push = true) {
    if (!titles[view]) view = "welcome";
    $$(".view").forEach((v) => (v.hidden = v.dataset.view !== view));
    document.title = `${titles[view]} – ${window.SITE.brand.name}`;
    if (push) history.replaceState(null, "", view === "welcome" ? "auth.html" : `auth.html?tab=${view}`);
    const first = $(`[data-view="${view}"] input`);
    if (first) first.focus({ preventScroll: true });
    window.scrollTo(0, 0);
  }
  $$("[data-goto]").forEach((b) => b.addEventListener("click", () => show(b.dataset.goto)));

  /* ---------- Show / hide password ---------- */
  $$("[data-toggle-password]").forEach((btn) =>
    btn.addEventListener("click", () => {
      const input = btn.previousElementSibling;
      const hidden = input.type === "password";
      input.type = hidden ? "text" : "password";
      btn.textContent = hidden ? "Hide" : "Show";
    })
  );

  /* ---------- Validation ---------- */
  const rules = {
    firstName: (v) => (v ? "" : "Enter your first name."),
    lastName: (v) => (v ? "" : "Enter your surname."),
    email: (v) => (EMAIL_RE.test(v) ? "" : "Enter a valid email address."),
    password: (v) => (v.length >= 8 ? "" : "Password must be at least 8 characters."),
    referredBy: (v) => (v ? "" : "Tell us who referred you."),
  };
  function validate(input) {
    const rule = rules[input.name];
    if (!rule) return true;
    const msg = rule(input.value.trim());
    const field = input.closest(".field");
    field.classList.toggle("invalid", !!msg);
    $(".error", field).textContent = msg;
    return !msg;
  }
  function validateForm(form) {
    const inputs = $$("input", form);
    const ok = inputs.map(validate).every(Boolean);
    if (!ok) $(".invalid input", form).focus();
    return ok;
  }
  $$("form input").forEach((i) => {
    i.addEventListener("blur", () => i.value && validate(i));
    i.addEventListener("input", () => i.closest(".field").classList.contains("invalid") && validate(i));
  });

  const data = (form) => Object.fromEntries(new FormData(form).entries());
  const notice = (id, text) => { const a = $(id); a.textContent = text; a.hidden = false; };

  function startSession(user) {
    try { localStorage.setItem("bw-user", JSON.stringify(user)); } catch (e) {}
    location.href = APP_URL;
  }

  /* ---------- Submit handlers (replace with real API calls) ---------- */
  async function submitLogin(values) {
    // TODO: const res = await fetch("/api/login", { method: "POST", body: JSON.stringify(values) });
    startSession({ firstName: values.email.split("@")[0], lastName: "" });
  }
  async function submitSignup(values) {
    // TODO: const res = await fetch("/api/signup", { method: "POST", body: JSON.stringify(values) });
    startSession({ firstName: values.firstName, lastName: values.lastName });
  }

  $("#login-form").addEventListener("submit", (e) => {
    e.preventDefault();
    if (validateForm(e.target)) submitLogin(data(e.target));
  });
  $("#signup-form").addEventListener("submit", (e) => {
    e.preventDefault();
    if (validateForm(e.target)) submitSignup(data(e.target));
  });

  /* ---------- Google sign-in / sign-up (Firebase, see firebase.js) ---------- */
  async function googleAuth(form, alertId, btn) {
    const isSignup = form.id === "signup-form";

    // Sign-up is referral-only: require "Referred by" before continuing with Google
    let referredBy = "";
    if (isSignup) {
      const ref = $("#referred-by");
      if (!validate(ref)) { ref.focus(); return; }
      referredBy = ref.value.trim();
    }

    if (typeof window.bwGoogleSignIn !== "function") {
      notice(alertId, "Google sign-in isn't set up yet. Add your Firebase settings in assets/js/firebase-config.js.");
      return;
    }

    const label = btn.innerHTML;
    btn.disabled = true;
    btn.textContent = "Connecting to Google…";
    try {
      const user = await window.bwGoogleSignIn();
      // TODO: save { uid, email, referredBy } to your database (e.g. Firestore) for new members.
      try { if (user.photo) localStorage.setItem("bw-photo", JSON.stringify(user.photo)); } catch (e) {}
      startSession({ uid: user.uid, firstName: user.firstName, lastName: user.lastName, email: user.email, referredBy, provider: "google" });
    } catch (err) {
      const quiet = ["auth/popup-closed-by-user", "auth/cancelled-popup-request"];
      if (!quiet.includes(err.code)) {
        const msgs = {
          "auth/popup-blocked": "Your browser blocked the Google pop-up. Allow pop-ups for this site and try again.",
          "auth/unauthorized-domain": "This website's domain isn't authorised in Firebase yet (Authentication → Settings → Authorized domains).",
          "auth/operation-not-allowed": "Google sign-in is not enabled in Firebase (Authentication → Sign-in method → Google).",
          "auth/network-request-failed": "Network error. Check your connection and try again.",
        };
        notice(alertId, msgs[err.code] || "Google sign-in failed. Please try again.");
        console.error(err);
      }
    } finally {
      btn.disabled = false;
      btn.innerHTML = label;
    }
  }

  $$("[data-oauth]").forEach((b) =>
    b.addEventListener("click", () => {
      const form = b.closest("form");
      const alertId = form.id === "login-form" ? "#login-alert" : "#signup-alert";
      if (b.dataset.oauth === "google") return googleAuth(form, alertId, b);
      // TODO: phone sign-in (Firebase also supports SMS codes via signInWithPhoneNumber).
      notice(alertId, "Phone verification will be available once the backend is connected.");
    })
  );

  /* ---------- Initial view from ?tab= ---------- */
  const params = new URLSearchParams(location.search);
  show(params.get("tab") || "welcome", false);
  const game = params.get("game");
  if (game) notice("#signup-alert", `Create your free account to get your ${game} Game ID.`);
})();
