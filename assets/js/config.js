/* ==========================================================================
   BigWin Gaming — Site Content & Settings
   --------------------------------------------------------------------------
   Edit THIS file to change names, games, stats and sample data.
   No HTML changes needed. Loaded before every other script.
   ========================================================================== */

window.SITE = {
  brand: {
    name: "BigWin Gaming",
    initials: "BW",
    tagline: "Premium Social Gaming Entertainment",
    supportAgent: "Brody",          // name shown in the live-chat bubble
    year: new Date().getFullYear(),
  },

  // Home page stats row
  stats: [
    { icon: "users", value: "18,000+", label: "Members" },
    { icon: "coins", value: "$2.4M+", label: "Paid Out" },
    { icon: "gamepad", value: "20+", label: "Games" },
    { icon: "bolt", value: "Instant", label: "Cashouts" },
  ],

  // Featured games grid.
  // `image`: put a file in assets/images/games/ and set e.g. "assets/images/games/juwa.webp".
  // Leave it empty and a styled tile with the game's initials is shown instead.
  games: [
    { name: "Juwa", image: "assets/images/games/juwa.jpg" },
    { name: "Gameroom", image: "assets/images/games/gameroom.webp" },
    { name: "Vegas Sweeps", image: "assets/images/games/vegassweeps.jpg" },
    { name: "Game Vault", image: "assets/images/games/gamevault.jpg" },
    { name: "Orion Stars", image: "assets/images/games/orionstars.jpg" },
    { name: "Cash Machine", image: "assets/images/games/cashmachine.webp" },
    { name: "Yolo", image: "assets/images/games/yolo.webp" },
    { name: "Milky Way", image: "assets/images/games/milkyway.jpg" },
    { name: "Fire Kirin", image: "assets/images/games/firekirin.webp" },
    { name: "Panda Master", image: "assets/images/games/pandamaster.webp" },
    { name: "Riversweeps", image: "assets/images/games/riversweeps.webp" },
    { name: "Ultra Panda", image: "assets/images/games/ultrapanda.jpg" },
    { name: "Cash Frenzy", image: "assets/images/games/cashfrenzy.webp" },
    { name: "Mafia", image: "assets/images/games/mafia.webp" },
    { name: "Mr. All In One", image: "assets/images/games/mrallinone.webp" },
    { name: "Noble", image: "assets/images/games/noble.webp" },
    { name: "VBlink", image: "assets/images/games/vblink.webp" },
    { name: "Juwa 2.0", image: "assets/images/games/juwa2.webp" },
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

  gameIds: [
    { game: "Juwa", username: "jordan_bw01", password: "••••••••" },
    { game: "Fire Kirin", username: "jreyes_fk", password: "••••••••" },
  ],

  // Demo signed-in user (replaced by real session after backend is connected)
  demoUser: { firstName: "Jordan", lastName: "Reyes" },
};
