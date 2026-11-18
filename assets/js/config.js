/* ==========================================================================
   BigWin Gaming — Site Content & Settings
   --------------------------------------------------------------------------
   Edit THIS file to change names, games, stats and sample data.
   No HTML changes needed. Loaded before every other script.
   ========================================================================== */

window.SITE = {
  // Backend API. "" = same server that serves the website (Flask in server/).
  apiBase: "",

  brand: {
    name: "BigWin Gaming",
    initials: "BW",
    tagline: "Premium Social Gaming Entertainment",
    supportAgent: "Brody",          // name shown in the live-chat bubble
    year: new Date().getFullYear(),
  },

  // "Message us" buttons. Paste your Facebook page username (facebook.com/THIS) and
  // Telegram username (t.me/THIS) — full links work too. Leave "" to hide a button.
  social: {
    facebook: "",   // e.g. "BigWinGaming"  -> opens Messenger chat with your page
    telegram: "",   // e.g. "BigWinSupport" -> opens Telegram chat
  },

  // Home page stats row
  stats: [
    { icon: "users", value: "18,000+", label: "Members" },
    { icon: "coins", value: "$2.4M+", label: "Paid Out" },
    { icon: "gamepad", value: "20+", label: "Games" },
    { icon: "bolt", value: "Instant", label: "Cashouts" },
  ],

  // Featured games grid. `key` must match the game key on the server (server/game_apis/__init__.py).
  // `image`: put a file in assets/images/games/ and set e.g. "assets/images/games/juwa.webp".
  // Leave it empty and a styled tile with the game's initials is shown instead.
  games: [
    { key: "juwa", name: "Juwa", image: "assets/images/games/juwa.jpg" },
    { key: "gameroom", name: "Gameroom", image: "assets/images/games/gameroom.webp" },
    { key: "vegassweeps", name: "Vegas Sweeps", image: "assets/images/games/vegassweeps.jpg" },
    { key: "gamevault", name: "Game Vault", image: "assets/images/games/gamevault.jpg" },
    { key: "orionstars", name: "Orion Stars", image: "assets/images/games/orionstars.jpg" },
    { key: "cashmachine", name: "Cash Machine", image: "assets/images/games/cashmachine.webp" },
    { key: "yolo", name: "Yolo", image: "assets/images/games/yolo.webp" },
    { key: "milkyway", name: "Milky Way", image: "assets/images/games/milkyway.jpg" },
    { key: "firekirin", name: "Fire Kirin", image: "assets/images/games/firekirin.webp" },
    { key: "pandamaster", name: "Panda Master", image: "assets/images/games/pandamaster.webp" },
    { key: "riversweeps", name: "Riversweeps", image: "assets/images/games/riversweeps.webp" },
    { key: "ultrapanda", name: "Ultra Panda", image: "assets/images/games/ultrapanda.jpg" },
    { key: "cashfrenzy", name: "Cash Frenzy", image: "assets/images/games/cashfrenzy.webp" },
    { key: "mafia", name: "Mafia", image: "assets/images/games/mafia.webp" },
    { key: "mrallinone", name: "Mr. All In One", image: "assets/images/games/mrallinone.webp" },
    { key: "noble", name: "Noble", image: "assets/images/games/noble.webp" },
    { key: "vblink", name: "VBlink", image: "assets/images/games/vblink.webp" },
    { key: "juwa2", name: "Juwa 2.0", image: "assets/images/games/juwa2.webp" },
  ],

  // Scrolling "LIVE" bar at the top of the home page.
  // IMPORTANT: replace these samples with real, recent payouts (or set enabled: false).
  ticker: {
    enabled: true,
    items: [
      { who: "Mike T.", action: "won", amount: 450, game: "Juwa" },
      { who: "Sarah M.", action: "cashed out", amount: 320, game: "Fire Kirin" },
      { who: "Jordan L.", action: "won", amount: 180, game: "Vegas Sweeps" },
      { who: "Chris R.", action: "won", amount: 740, game: "Game Vault" },
      { who: "Emma W.", action: "cashed out", amount: 260, game: "Orion Stars" },
      { who: "David K.", action: "won", amount: 920, game: "Milky Way" },
      { who: "Lisa P.", action: "won", amount: 510, game: "Panda Master" },
      { who: "Ryan H.", action: "cashed out", amount: 380, game: "VBlink" },
    ],
  },

  /* ------------------------------------------------------------------------
     Member app sample data (app/ pages). Replace with your backend API.
     ------------------------------------------------------------------------ */
  channels: [
    { initials: "BW", name: "BigWin" },
    { initials: "PR", name: "Promos" },
  ],

  chats: [
    {
      id: "support", initials: "BG", name: "BigWin Gaming", pinned: true, online: true, gold: true,
      preview: "Got it. Sending the details now.", time: "2m", unread: 1,
      messages: [
        { from: "me", text: "Hi, I want to load $50 on Juwa." },
        { from: "them", text: "Hey! Sure, which payment method are you using?" },
        { from: "me", text: "Cash App." },
        { from: "them", text: "Got it. Sending the details now." },
      ],
    },
  ],

  groups: [
    {
      id: "g1", initials: "JM", name: "Josh Miller & Tara Flecher",
      preview: "Josh: Anyone playing tonight?", time: "15m", unread: 3,
      messages: [
        { from: "Tara", text: "Fire Kirin was on fire yesterday 🔥" },
        { from: "Josh", text: "Anyone playing tonight?" },
      ],
    },
    {
      id: "g2", initials: "DD", name: "Danya, Don & Oliver",
      preview: "Oliver: See you Saturday", time: "3h", unread: 0,
      messages: [{ from: "Oliver", text: "See you Saturday" }],
    },
    {
      id: "g3", initials: "NM", name: "New Members",
      preview: "Welcome, Jay!", time: "1d", unread: 0,
      messages: [{ from: "BigWin", text: "Welcome, Jay!" }],
    },
  ],

  paymentMethods: ["Cash App", "Chime", "PayPal", "Venmo", "Bitcoin"],

  payments: [
    { type: "Load", game: "Juwa", amount: 50, method: "Cash App", status: "Completed", date: "Today, 2:14 PM" },
    { type: "Cashout", game: "Fire Kirin", amount: 120, method: "Chime", status: "Pending", date: "Yesterday, 9:40 PM" },
    { type: "Load", game: "Orion Stars", amount: 25, method: "PayPal", status: "Completed", date: "Mon, 6:02 PM" },
  ],


};
