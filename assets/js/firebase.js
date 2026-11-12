/* ==========================================================================
   BigWin Gaming — Firebase Authentication (Google sign-in / sign-up)
   Loaded as an ES module on auth.html. Exposes:
     window.bwGoogleSignIn()  → Promise<{ firstName, lastName, email, photo, uid }>
   ========================================================================== */

import { initializeApp } from "https://www.gstatic.com/firebasejs/10.12.2/firebase-app.js";
import {
  getAuth,
  GoogleAuthProvider,
  signInWithPopup,
} from "https://www.gstatic.com/firebasejs/10.12.2/firebase-auth.js";

const cfg = window.FIREBASE_CONFIG || {};
const configured = cfg.apiKey && !cfg.apiKey.startsWith("PASTE_");

if (configured) {
  const app = initializeApp(cfg);
  const auth = getAuth(app);
  const provider = new GoogleAuthProvider();
  provider.setCustomParameters({ prompt: "select_account" });

  window.bwGoogleSignIn = async () => {
    const { user } = await signInWithPopup(auth, provider);
    const [firstName = "", ...rest] = (user.displayName || "").split(" ");
    return {
      uid: user.uid,
      email: user.email,
      firstName: firstName || (user.email || "").split("@")[0],
      lastName: rest.join(" "),
      photo: user.photoURL || "",
    };
  };
} else {
  console.info("[BigWin] Firebase not configured — edit assets/js/firebase-config.js to enable Google sign-in.");
}
