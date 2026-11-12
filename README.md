# BigWin Gaming

The full BigWin Gaming platform:
- a black-and-gold **website** (home page, login/sign-up, members app)
- a Python **server** that creates players' **Game IDs** automatically on each game's agent portal
- an **admin panel** at `/admin`

The server and admin panel come from the Gameroom platform, rebranded for BigWin.

---

## Folder structure

```
bigwin-gaming/
├── index.html            Home: live ticker, hero, stats, featured games, CTA
├── auth.html             Welcome / Login / Create account  (?tab=login | ?tab=signup)
├── guide.html, support.html, privacy.html, terms.html, 404.html
│
├── app/                  Members area (sign-in required)
│   ├── chats.html        Support chat & groups          (sample data for now)
│   ├── payments.html     Load / Cashout                 (sample data for now)
│   └── game-id.html      ★ LIVE: player's Game IDs, get a new Game ID
│
├── admin/                Admin panel, served at /admin
│   ├── index.html
│   ├── admin.js
│   └── admin.css
│
├── server/               Python (Flask) backend
│   ├── app.py            All API routes (/api/…) and serves the website
│   ├── database.py       SQLite locally, PostgreSQL in production
│   ├── game_apis/        One module per game agent portal (Juwa, Fire Kirin, Orion Stars…)
│   ├── mailer.py         Email codes (password reset, verification)
│   └── telegram_notify.py
│
├── assets/
│   ├── css/              style.css (theme) + one file per page type
│   ├── js/
│   │   ├── config.js     ★ Editable content: games, stats, ticker, sample data
│   │   ├── api.js        Talks to the server (sessions, sign-in, Game IDs)
│   │   ├── auth.js       Login / sign-up
│   │   ├── app.js        Members app
│   │   ├── firebase.js + firebase-config.js   Google sign-in
│   │   └── main.js, home.js, icons.js
│   └── images/           logo, favicon, games/ (game covers)
│
├── requirements.txt      Python packages
├── Procfile              Start command for Railway / Render / Heroku
└── .env.example          Settings template (copy to .env)
```

---

## Run locally

```bash
cd bigwin-gaming
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env            # then edit .env and set ADMIN_PASSWORD
.venv/bin/python server/app.py
```

Open **http://localhost:8000** for the website and **http://localhost:8000/admin** for the admin panel.

The members app needs this server. Opening the HTML files directly, or with `python3 -m http.server`, shows the pages, but sign-in and Game IDs will not work.

---

## How Game IDs work

1. **Admin → Backend Attachments**: choose a game (for example Fire Kirin) and enter **your agent account** username and password for that game's agent portal. Click **Test** to confirm it connects.
2. That game then appears for players under **Game ID → Get a new Game ID**.
3. When a player clicks **Get Game ID**, the server logs into that game's agent portal, **creates the player's account**, saves it, and shows the player their username and password.
4. The player can come back any time and tap **Show** to see their password again.
5. In the admin panel you can see every player's game accounts, check balances, and load or redeem credits.

Supported games (see `server/game_apis/__init__.py`): Juwa, Juwa 2.0, Game Vault, Vegas Sweeps, Ultra Panda, VBlink, Milky Way, Orion Stars, Fire Kirin, Panda Master, Gameroom, Cash Frenzy, Cash Machine, Mafia, Mr. All In One, Yolo, Riversweeps.
**Noble** is shown on the home page but has no server integration yet, so players can't get a Noble Game ID.

---

## Settings (`.env` locally, environment variables on the host)

| Name | Required | What it is |
|---|---|---|
| `ADMIN_PASSWORD` | **Yes** | Admin panel password. Admin login stays **disabled** until it's set. |
| `SECRET_KEY` | Recommended | Long random string used to sign logins: `python3 -c "import secrets;print(secrets.token_hex(32))"` |
| `DATABASE_URL` | Production | PostgreSQL URL. If empty, the server uses `server/casino.db` (SQLite, local only). |
| `SITE_URL` | Yes | Your live address, used in emails (for example `https://bigwingaming.com`) |
| `FIREBASE_PROJECT_ID` | For Google sign-in | Same as `projectId` in `assets/js/firebase-config.js` |
| `ALLOWED_ORIGIN` | Optional | Restrict which site can call the API (default `*`) |

Email, SMS, Telegram and payment-gateway keys are entered in the admin panel, not in `.env`.

---

## Deploy (Railway recommended)

1. Go to https://railway.app → **New Project → Deploy from GitHub repo →** `bigwin-gaming`.
2. Add a **PostgreSQL** database to the project. Railway sets `DATABASE_URL` for you.
3. Under **Variables**, add `ADMIN_PASSWORD`, `SECRET_KEY`, `SITE_URL` and `FIREBASE_PROJECT_ID`.
4. Railway reads the `Procfile` and starts the server. Under **Settings → Networking**, add your domain.
5. In Firebase → Authentication → Settings → **Authorized domains**, add the same domain.

Some game portals only accept requests from approved IP addresses. If **Test** fails on the live server, open the admin panel's server IP page (`/api/server-ip`) and give that IP to the game provider.

---

## Google sign-in (Firebase)

1. https://console.firebase.google.com → **Add project**.
2. **Authentication → Sign-in method → Google → Enable**.
3. **Project settings → Your apps → Web (`</>`)**: copy the config into `assets/js/firebase-config.js`.
4. Set `FIREBASE_PROJECT_ID` on the server.
5. Add your domain under **Authentication → Settings → Authorized domains** (`localhost` is already allowed).

The server verifies every Google sign-in with Google's public keys before creating or opening an account. New players must enter **Referred by**.

---

## Common edits

| What to change | Where |
|---|---|
| Games, stats, ticker, payment methods | `assets/js/config.js` (a game's `key` must match `server/game_apis/__init__.py`) |
| Website colours | `:root` in `assets/css/style.css` |
| Game cover images | `assets/images/games/` + `image:` in `config.js` |
| Logo | `assets/images/logo.svg`, `logo.png` (emails), `favicon.svg` |
| Legal text | `privacy.html`, `terms.html` (**have a lawyer review these before launch**) |

## Still to connect

- **Chats** (`app/chats.html`) → the server already has `/api/support/messages`.
- **Payments** (`app/payments.html`) → the server already has `/api/deposits` and `/api/withdrawals`.
- **Phone sign-in** → the server already has `/api/verify/phone/*` (needs an SMS provider set in admin).

## Before going live

- Set a strong `ADMIN_PASSWORD` and `SECRET_KEY`, and use PostgreSQL.
- Replace the sample **live ticker** winners in `config.js` with real payouts, or set `ticker.enabled: false`.
- Make sure the home page **stats** are accurate.
- Confirm that the service is legal where you operate, and keep the 18+ and responsible-play notices.
