# BigWin Gaming — Website

A responsive website for **BigWin Gaming** with a black-and-gold theme. It has a public home page, login and sign-up pages, and a members-only app (Chats, Payments, Game ID).

It is plain HTML, CSS and JavaScript. There is no build step and nothing to install, so it can be hosted anywhere.

---

## Folder structure

```
gaming-website/
├── index.html            Home: live ticker, hero, stats, featured games, CTA
├── auth.html             Welcome / Login / Create account  (?tab=login | ?tab=signup)
├── guide.html            How to Play
├── support.html          Support: FAQ + contact form
├── privacy.html          Privacy Policy (template)
├── terms.html            Terms & Conditions (template)
├── 404.html              Page-not-found
│
├── app/                  Members area (after login)
│   ├── chats.html        Channels, pinned support chat, groups, conversation view
│   ├── payments.html     Load / Cashout requests + history
│   └── game-id.html      Game logins, request new Game ID, log out
│
└── assets/
    ├── css/
    │   ├── style.css     Shared: theme colours, buttons, forms, header, footer
    │   ├── home.css      Home page only
    │   ├── auth.css      Login / sign-up only
    │   ├── app.css       Member app only
    │   └── pages.css     Support, guide, legal, 404
    ├── js/
    │   ├── config.js     ★ ALL editable content: name, games, stats, ticker, sample data
    │   ├── icons.js      SVG icon set
    │   ├── main.js       Shared: mobile menu, live-chat bubble, footer year
    │   ├── home.js       Home page: ticker, stats, games grid, game pop-up
    │   ├── auth.js       Login / sign-up views + validation
    │   └── app.js        Member app: chats, payments, game IDs, profile image
    └── images/
        ├── logo.svg
        ├── favicon.svg
        └── games/        Put game cover images here
```

## Common edits

| What to change | Where |
|---|---|
| Games list, stats, ticker, payment methods, support agent name | `assets/js/config.js` |
| Colours (gold, background, etc.) | `:root` at the top of `assets/css/style.css` |
| Game cover images | Add files to `assets/images/games/`, then set `image: "assets/images/games/juwa.webp"` in `config.js` (square, about 400×400 px) |
| Logo | Replace `assets/images/logo.svg` and `favicon.svg` |
| Legal text | `privacy.html`, `terms.html` (**have a lawyer review these before launch**) |

## Run locally

Open `index.html` in a browser. For the most accurate result, serve the folder:

```bash
cd gaming-website
python3 -m http.server 8080
# then open http://localhost:8080
```

## Deploy

Upload the whole folder to any static host, such as Netlify, Vercel, GitHub Pages, Cloudflare Pages or cPanel `public_html`. `404.html` is picked up automatically by most hosts.

---

## Google sign-up (Firebase)

The Google buttons on `auth.html` already contain working code (`assets/js/firebase.js`). To turn them on:

1. Go to https://console.firebase.google.com → **Add project** (Google Analytics is optional).
2. **Build → Authentication → Get started → Sign-in method → Google → Enable**, choose a support email, then **Save**.
3. **Project settings (⚙) → General → Your apps → Web (`</>`)**: register an app (no hosting needed) and copy the `firebaseConfig` values.
4. Paste them into `assets/js/firebase-config.js` (`apiKey`, `authDomain`, `projectId`, `appId`).
5. **Authentication → Settings → Authorized domains**: add your live domain (for example `bigwingaming.com`). `localhost` is already allowed.
6. Test with a local server (`python3 -m http.server 8080`). It does **not** work when you open the file directly (`file://`).

Sign-up flow: the member types who referred them and clicks **Sign up with Google**. After choosing their Google account, they land in `app/chats.html` with their Google name and photo.
To keep the referral name on the server, save it to a database such as Firestore (see the `TODO` in `googleAuth()` in `auth.js`).

## ⚠️ Before going live: connect a backend

The front end is complete. Accounts, chat and payments currently run in **demo mode**: data is stored only in the visitor's browser (`localStorage`) or comes from the sample data in `config.js`. To make it live, connect a backend (for example Firebase, Supabase or your own API). Every place that needs it is marked `// TODO` in the code:

| Feature | File · function |
|---|---|
| Login / sign-up | `assets/js/auth.js` · `submitLogin`, `submitSignup` |
| Google / phone sign-in | `assets/js/auth.js` · `[data-oauth]` handler |
| Chat messages (real-time) | `assets/js/app.js` · `initChats` → `convo-form` submit |
| Load / cashout requests | `assets/js/app.js` · `initPayments` → `pay-form` submit |
| Game ID requests | `assets/js/app.js` · `initGameIds` → `gid-form` submit |
| Profile image upload | `assets/js/app.js` · `initHeader` → `upload-input` |
| Support form | `support.html` · inline script |
| Protect `app/` pages | Add a session check that redirects logged-out users to `auth.html` |

Also before launch:
- Replace the **live ticker** sample winners in `config.js` with real payouts, or set `ticker.enabled: false`.
- Make sure the **stats** (members, paid out) are accurate.
- Confirm that running the service is legal in the regions you serve, and keep the 18+ and responsible-play notices.
