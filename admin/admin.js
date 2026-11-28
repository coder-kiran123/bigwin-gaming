// ── API CONFIG ──
const API = '/api';   // admin is served by the same server as the API

// ── ADMIN AUTH GATE ──
const ADMIN_TOKEN_KEY = 'bw_admin_token';

function getAdminToken() { return sessionStorage.getItem(ADMIN_TOKEN_KEY) || localStorage.getItem(ADMIN_TOKEN_KEY); }
function setAdminToken(t) { sessionStorage.setItem(ADMIN_TOKEN_KEY, t); localStorage.setItem(ADMIN_TOKEN_KEY, t); }
function clearAdminToken() { sessionStorage.removeItem(ADMIN_TOKEN_KEY); localStorage.removeItem(ADMIN_TOKEN_KEY); }

async function doAdminLogin() {
  const pw  = (document.getElementById('adminPwInput').value || '').trim();
  const err = document.getElementById('loginErr');
  const btn = document.getElementById('adminLoginBtn');
  err.textContent = '';
  if (!pw) { err.textContent = 'Enter your admin password'; return; }
  btn.textContent = 'Verifying…'; btn.disabled = true;
  try {
    const r = await fetch(API + '/admin/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({password: pw})
    });
    const d = await r.json();
    if (d.success) {
      setAdminToken(d.token);
      document.getElementById('adminLoginGate').style.display = 'none';
      initAdmin();
    } else {
      err.textContent = d.msg || 'Incorrect password';
    }
  } catch(e) {
    err.textContent = 'Network error — check your connection';
  }
  btn.textContent = 'Unlock Admin'; btn.disabled = false;
}

function toggleLoginEye(btn) {
  const inp = document.getElementById('adminPwInput');
  inp.type = inp.type === 'password' ? 'text' : 'password';
}

async function checkAdminAuth() {
  const token = getAdminToken();
  const gate  = document.getElementById('adminLoginGate');
  if (!token) { if (gate) gate.style.display = ''; return; } // gate stays visible
  try {
    const r = await fetch(API + '/admin/verify', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({token})
    });
    const d = await r.json();
    if (d.success) {
      if (gate) gate.style.display = 'none';
      initAdmin();
    } else {
      clearAdminToken();
      if (gate) gate.style.display = ''; // token rejected — show login again, don't touch dashboard
    }
  } catch(e) {
    // offline — let stored token be used optimistically rather than locking the admin out
    if (gate) gate.style.display = 'none';
    initAdmin();
  }
}

async function apiFetch(path, method='GET', body=null) {
  try {
    const token = getAdminToken();
    const opts = { method, headers: {'Content-Type': 'application/json'} };
    if (token) opts.headers['X-Admin-Token'] = token;
    if (body) opts.body = JSON.stringify(body);
    const r = await fetch(API + path, opts);
    if (r.status === 401) { clearAdminToken(); location.reload(); return {success:false}; }
    return await r.json();
  } catch(e) {
    return { success: false, msg: 'Backend offline — running in demo mode' };
  }
}

// ── SIDEBAR TOGGLE (mobile) ──
function toggleSidebar() {
  const sidebar = document.querySelector('.sidebar');
  const overlay = document.getElementById('sidebarOverlay');
  sidebar.classList.toggle('open');
  overlay.classList.toggle('visible');
}

function closeSidebar() {
  document.querySelector('.sidebar').classList.remove('open');
  document.getElementById('sidebarOverlay').classList.remove('visible');
}

// ── PAGE NAVIGATION ──
function showPage(pageId, clickedEl) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  const page = document.getElementById('page-' + pageId);
  if (page) page.classList.add('active');

  document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
  if (clickedEl) {
    const navItem = clickedEl.closest ? clickedEl.closest('.nav-item') : clickedEl;
    if (navItem) navItem.classList.add('active');
  }

  const titles = {
    'dashboard':          'Dashboard',
    'finance-overview':   'Finance Overview',
    'growth':             'Growth Insights',
    'ledgers':            'Ledgers',
    'players':            'Players',
    'player-analytics':   'Player Analytics',
    'transactions':       'Transactions',
    'deposits':           'Deposit Requests',
    'withdrawals':        'Withdrawal Requests',
    'payment-analytics':  'Payment Analytics',
    'provider-balance':   'Provider Balance',
    'game-records':       'Game Records',
    'game-analytics':     'Game Analytics',
    'roulette-admin':     'Roulette Wheel',
    'marketplace-admin':  'Marketplace',
    'games-list':         'Games',
    'payment-methods':    'Payment Methods',
    'cashout-rules':      'Cashout Rules',
    'support-chat':       'Live Support',
    'load-requests':      'Load Requests',
    'referrals':          'Referral Program',
  };
  document.getElementById('pageTitle').textContent = titles[pageId] || pageId;

  // close sidebar on mobile after navigation
  if (window.innerWidth <= 768) closeSidebar();

  if (pageId === 'provider-balance')   { renderProviders(); loadServerIP(); }
  if (pageId === 'players')            renderPlayers();
  if (pageId === 'transactions')       renderAllTxns();
  if (pageId === 'deposits')           { renderDeposits(); loadDepositSettings(); }
  if (pageId === 'withdrawals')        renderWithdrawals();
  if (pageId === 'backend-attach')     renderAttachedList();
  if (pageId === 'finance-overview')   renderFinance();
  if (pageId === 'growth')             renderGrowth();
  if (pageId === 'ledgers')            renderLedgers();
  if (pageId === 'player-analytics')   renderPlayerAnalytics();
  if (pageId === 'payment-analytics')  renderPaymentAnalytics();
  if (pageId === 'game-records')       renderGameRecords();
  if (pageId === 'game-analytics')     renderGameAnalytics();
  if (pageId === 'games-list')         renderGamesList();
  if (pageId === 'payment-methods')    { renderPaymentMethods(); renderKeyhubConfig(); renderSmsConfig(); renderTelegramConfig(); renderEmailConfig(); renderSocialLinks(); }
  if (pageId === 'cashout-rules')      renderCashoutRules();
  if (pageId === 'support-chat')        { loadConversations(); }
  if (pageId === 'load-requests')       renderLoadRequests();
  if (pageId === 'support-agents')      { renderSupportAgents(); }
  if (pageId === 'referrals')          { loadReferrals(); }
  if (pageId === 'roulette-admin')     { loadRoulettePrizes(); loadRouletteSpins(); }
  if (pageId === 'marketplace-admin')  { loadMarketplaceTiers(); loadMarketplaceRedemptions(); }
}

// ── MOCK DATA ──
const PLAYERS = [
  { id: 1, username: 'lilleydan092628', email: 'lilleydan@email.com', balance: '$14.95', fp: '26 BW', joined: 'Jun 10, 2026', status: 'active' },
  { id: 2, username: 'check1235460',    email: 'check123@email.com',  balance: '$175.00', fp: '0 BW', joined: 'Jun 11, 2026', status: 'active' },
  { id: 3, username: 'john_doe',        email: 'john@email.com',      balance: '$0.00',   fp: '0 BW', joined: 'Jun 9, 2026',  status: 'active' },
];

const TRANSACTIONS = [
  { user: 'lilleydan092628', type: 'Game_sale',                    amount: '$0.00',  status: 'pending',  time: '2 min ago' },
  { user: 'lilleydan092628', type: 'Update_notification_settings', amount: '$0.00',  status: 'approved', time: '5 min ago' },
  { user: 'check1235460',    type: 'Game_sale',                    amount: '$0.00',  status: 'pending',  time: '12 min ago' },
  { user: 'check1235460',    type: 'Game_sale',                    amount: '$0.00',  status: 'pending',  time: '18 min ago' },
  { user: 'lilleydan092628', type: 'Deposit',                      amount: '$4.95',  status: 'approved', time: '1 hr ago' },
  { user: 'check1235460',    type: 'Deposit',                      amount: '$175.00',status: 'approved', time: '2 hr ago' },
];

const DEPOSITS_DATA = [
  { user: 'lilleydan092628', amount: '$4.95',   method: 'CashApp',  time: '1 hr ago',  status: 'approved' },
  { user: 'check1235460',    amount: '$175.00', method: 'Bitcoin',  time: '2 hr ago',  status: 'approved' },
];

const WITHDRAWALS_DATA = [];

let PROVIDERS = [];   // loaded live from API

// ── RENDER RECENT TXNs (dashboard) ──
function renderRecentTxns() {
  const el = document.getElementById('recentTxnList');
  if (!el) return;
  el.innerHTML = TRANSACTIONS.slice(0, 5).map(t => `
    <div class="txn-row">
      <div class="txn-avatar">${t.user[0].toUpperCase()}</div>
      <div class="txn-info">
        <div class="txn-name">${t.user}</div>
        <div class="txn-type">${t.type}</div>
      </div>
      <div class="txn-right">
        <div class="txn-amt">${t.amount}</div>
        <div class="txn-badge badge-${t.status}">${t.status}</div>
      </div>
    </div>`).join('');
}

// ── SERVER IP ──
async function loadServerIP() {
  const el = document.getElementById('server-ip-val');
  if (!el) return;
  el.textContent = 'Loading...';
  el.style.color = '#94a3b8';
  const res = await apiFetch('/server-ip');
  if (res.success && res.data.ip && res.data.ip !== 'unavailable') {
    el.textContent = res.data.ip;
    el.style.color = '#34d399';
  } else {
    el.textContent = 'Unavailable';
    el.style.color = '#f87171';
  }
}

function copyServerIP(btn) {
  const ip = document.getElementById('server-ip-val')?.textContent;
  if (!ip || ip === 'Loading...' || ip === 'Unavailable') return;
  navigator.clipboard.writeText(ip).then(() => {
    const orig = btn.textContent;
    btn.textContent = 'Copied!';
    btn.style.color = '#34d399';
    setTimeout(() => { btn.textContent = orig; btn.style.color = ''; }, 1500);
  });
}

// ── RENDER PROVIDERS (live) ──
async function renderProviders() {
  const grid = document.getElementById('providerGrid');
  if (!grid) return;
  grid.innerHTML = '<div style="padding:30px;color:#6b7280;text-align:center">Loading live balances...</div>';

  const res = await apiFetch('/providers/balances');
  PROVIDERS = (res.data || []).map(p => ({
    id:        p.id,
    name:      p.name,
    game:      p.game,
    bal:       p.balance != null ? parseFloat(p.balance) : null,
    status:    p.status,
    checked:   p.last_tested ? new Date(p.last_tested).toLocaleTimeString() : 'never',
    healthy:   p.balance != null && parseFloat(p.balance) >= 100,
    hasBalance: p.balance != null,
    threshold:  100,
  }));

  if (PROVIDERS.length === 0) {
    grid.innerHTML = `<div style="padding:40px;text-align:center;color:#6b7280">
      <p style="font-size:30px">📡</p>
      <p style="margin-top:10px">No connected backends yet.</p>
      <p style="font-size:13px;margin-top:6px">Attach a backend in the Backend Attachments tab.</p>
    </div>`;
    return;
  }

  grid.innerHTML = PROVIDERS.map((p, i) => {
    const low      = p.hasBalance && p.bal < p.threshold;
    const balColor = !p.hasBalance ? 'gray' : p.bal < 50 ? 'red' : p.bal < 100 ? 'orange' : 'green';
    const balText  = p.hasBalance ? `$${p.bal.toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2})}` : 'N/A';
    const badge    = !p.hasBalance ? 'badge-neutral' : low ? 'badge-warning' : 'badge-verified';
    const badgeTxt = !p.hasBalance ? 'N/A' : low ? 'LOW' : 'OK';
    return `
    <div class="provider-card ${low ? 'low-alert' : 'healthy'}">
      <div class="pcard-top">
        <div>
          <div class="pcard-name-row">
            <span class="pcard-name">${p.name}</span>
            <span class="pcard-badge ${badge}">${badgeTxt}</span>
          </div>
          <div class="pcard-checked">Updated ${p.checked}</div>
        </div>
        <div>
          <div class="pcard-bal ${balColor}">${balText}</div>
        </div>
      </div>
      ${low ? `<div class="pcard-alert">⚠ Below $${p.threshold} threshold — top-up required</div>` : ''}
      ${!p.hasBalance ? `<div class="pcard-alert" style="background:#f3f4f6;color:#6b7280;border-color:#e5e7eb">Agent balance not available for this platform</div>` : ''}
      <div class="pcard-btns">
        <button class="btn-check-bal" onclick="checkBalance(${i}, this)" ${!p.hasBalance ? 'disabled style="opacity:0.4;cursor:not-allowed"' : ''}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
          Check Balance
        </button>
        <button class="btn-test-conn" onclick="testProviderConnection(${i}, this)">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12.55a11 11 0 0 1 14.08 0"/><path d="M1.42 9a16 16 0 0 1 21.16 0"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><line x1="12" y1="20" x2="12.01" y2="20"/></svg>
          Test Connection
        </button>
      </div>
    </div>`;
  }).join('');
}

async function checkBalance(idx, btn) {
  btn.textContent = 'Checking...';
  btn.disabled    = true;
  const p   = PROVIDERS[idx];
  const res = await apiFetch('/providers/balances');
  const updated = (res.data || []).find(x => x.id === p.id);
  if (updated) {
    p.bal = updated.balance != null ? parseFloat(updated.balance) : null;
    const card = btn.closest('.provider-card');
    const balText = p.bal != null ? `$${p.bal.toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2})}` : 'N/A';
    card.querySelector('.pcard-bal').textContent = balText;
    card.querySelector('.pcard-checked').textContent = `Updated ${new Date().toLocaleTimeString()}`;
  }
  const balDisplay = p.bal != null ? `$${p.bal.toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2})}` : 'N/A';
  btn.innerHTML = `✓ ${balDisplay}`;
  btn.style.color = '#22c55e';
  setTimeout(() => {
    btn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg> Check Balance`;
    btn.style.color = '';
    btn.disabled    = false;
  }, 2000);
}

async function testProviderConnection(idx, btn) {
  btn.textContent = 'Testing...';
  btn.disabled    = true;
  const p   = PROVIDERS[idx];
  const res = await apiFetch(`/backends/${p.id}/test`, 'POST');
  const ok  = res.data?.status === 'connected';
  btn.textContent  = ok ? '✓ Connected' : '✗ Failed';
  btn.style.background = ok ? '#16a34a' : '#dc2626';
  setTimeout(() => {
    btn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12.55a11 11 0 0 1 14.08 0"/><path d="M1.42 9a16 16 0 0 1 21.16 0"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><line x1="12" y1="20" x2="12.01" y2="20"/></svg> Test Connection`;
    btn.style.background = '';
    btn.disabled = false;
  }, 2500);
}

async function refreshProviders() {
  const btn = event.target.closest('button');
  btn.textContent = 'Refreshing...';
  btn.disabled    = true;
  await renderProviders();
  btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg> Refresh All (live)`;
  btn.disabled = false;
}

// ── RENDER PLAYERS (live) ──
async function renderPlayers() {
  const el = document.getElementById('playersTable');
  if (!el) return;
  el.innerHTML = '<div style="padding:20px;color:#6b7280">Loading...</div>';
  const res = await apiFetch('/players');
  const list = res.success ? res.data : [];
  const isActive = s => !s || s === 'active';
  el.innerHTML = `
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;flex-wrap:wrap">
      <input id="playerSearchInput" type="text" placeholder="Search username or email…" oninput="filterPlayerTable(this.value)"
        style="flex:1;min-width:180px;border:1.5px solid #e5e7eb;border-radius:8px;padding:8px 14px;font-size:13px;outline:none;color:#111">
      <div style="font-size:13px;color:#6b7280;white-space:nowrap" id="playerCountLbl">${list.length} player${list.length!==1?'s':''}</div>
      <button onclick="showCreatePlayerModal()" style="background:#852c2c;color:#fff;border:none;border-radius:8px;padding:8px 18px;font-size:13px;font-weight:700;cursor:pointer;white-space:nowrap">+ Create User</button>
    </div>
    <div style="overflow-x:auto">
    <table style="width:100%;border-collapse:collapse;font-size:13px;min-width:700px">
      <thead>
        <tr style="border-bottom:2px solid #e5e7eb">
          <th style="text-align:left;padding:10px 12px;color:#6b7280;font-weight:600">USERNAME</th>
          <th style="text-align:left;padding:10px 12px;color:#6b7280;font-weight:600">EMAIL</th>
          <th style="text-align:left;padding:10px 12px;color:#6b7280;font-weight:600">BALANCE</th>
          <th style="text-align:left;padding:10px 12px;color:#6b7280;font-weight:600">BW</th>
          <th style="text-align:left;padding:10px 12px;color:#6b7280;font-weight:600">JOINED</th>
          <th style="text-align:left;padding:10px 12px;color:#6b7280;font-weight:600">STATUS</th>
          <th style="padding:10px 12px"></th>
        </tr>
      </thead>
      <tbody>
        ${list.map(p => {
          const active = isActive(p.status);
          const statusBg = active ? '#dcfce7' : '#fee2e2';
          const statusClr = active ? '#166534' : '#991b1b';
          const toggleLbl = active ? 'Disable' : 'Enable';
          const toggleBg  = active ? '#fee2e2' : '#dcfce7';
          const toggleBd  = active ? '#fecaca' : '#bbf7d0';
          const toggleClr = active ? '#991b1b' : '#166534';
          return `
        <tr style="border-bottom:1px solid #f3f4f6">
          <td style="padding:12px"><strong>${escAdm(p.username)}</strong></td>
          <td style="padding:12px;color:#6b7280">${escAdm(p.email||'—')}</td>
          <td style="padding:12px;font-weight:700">$${Number(p.balance||0).toFixed(2)}</td>
          <td style="padding:12px;color:#ceb05d;font-weight:700">${Number(p.fp_credits||0)} BW</td>
          <td style="padding:12px;color:#6b7280">${(p.created_at||'').slice(0,10)}</td>
          <td style="padding:12px"><span style="background:${statusBg};color:${statusClr};font-size:10px;font-weight:700;padding:3px 10px;border-radius:20px">${p.status||'active'}</span></td>
          <td style="padding:12px">
            <div style="display:flex;gap:6px;flex-wrap:wrap">
              <button style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:6px;padding:6px 12px;font-size:12px;font-weight:700;color:#1d4ed8;cursor:pointer" onclick="viewPlayer(${p.id})">👁 View</button>
              <button style="background:#dcfce7;border:1px solid #bbf7d0;border-radius:6px;padding:6px 12px;font-size:12px;font-weight:700;color:#166534;cursor:pointer" onclick="creditPlayer(${p.id},'${escAdm(p.username)}')">+ Credit</button>
              <button style="background:#fee2e2;border:1px solid #fecaca;border-radius:6px;padding:6px 12px;font-size:12px;font-weight:700;color:#991b1b;cursor:pointer" onclick="redeemPlayer(${p.id},'${escAdm(p.username)}',${Number(p.balance||0).toFixed(2)})">− Redeem</button>
              <button style="background:#fef3c7;border:1px solid #fde68a;border-radius:6px;padding:6px 12px;font-size:12px;font-weight:700;color:#92400e;cursor:pointer" onclick="adminResetPw(${p.id},'${escAdm(p.username)}')">🔑 Reset PW</button>
              <button style="background:${toggleBg};border:1px solid ${toggleBd};border-radius:6px;padding:6px 12px;font-size:12px;font-weight:700;color:${toggleClr};cursor:pointer" onclick="togglePlayerStatus(${p.id},'${escAdm(p.username)}','${p.status||'active'}')">${toggleLbl}</button>
            </div>
          </td>
        </tr>`;}).join('')}
      </tbody>
    </table>
    </div>`;
}

function filterPlayerTable(q) {
  q = (q || '').toLowerCase();
  const rows = document.querySelectorAll('#playersTable tbody tr');
  let visible = 0;
  rows.forEach(row => {
    const text = row.textContent.toLowerCase();
    const show = !q || text.includes(q);
    row.style.display = show ? '' : 'none';
    if (show) visible++;
  });
  const lbl = document.getElementById('playerCountLbl');
  if (lbl) lbl.textContent = `${visible} player${visible !== 1 ? 's' : ''}`;
}

// ── Create Player Modal ──
function showCreatePlayerModal() {
  let modal = document.getElementById('createPlayerModal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'createPlayerModal';
    document.body.appendChild(modal);
  }
  modal.innerHTML = `
    <div onclick="closeCreatePlayer()" style="position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:1000"></div>
    <div style="position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:1001;background:#fff;border-radius:16px;padding:28px 28px 24px;width:min(96vw,440px);box-shadow:0 20px 60px rgba(0,0,0,.25)">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px">
        <h3 style="margin:0;font-size:18px;font-weight:700;color:#111">Create Player Account</h3>
        <button onclick="closeCreatePlayer()" style="background:none;border:none;font-size:22px;cursor:pointer;color:#6b7280;line-height:1">×</button>
      </div>
      <div id="createPlayerErr" style="display:none;background:#fee2e2;color:#991b1b;border-radius:8px;padding:10px 14px;margin-bottom:14px;font-size:13px"></div>
      <div style="display:flex;flex-direction:column;gap:12px">
        <div>
          <label style="font-size:12px;font-weight:700;color:#374151;display:block;margin-bottom:5px">USERNAME *</label>
          <input id="cpUsername" type="text" autocomplete="off" placeholder="e.g. john123"
            style="width:100%;box-sizing:border-box;border:1.5px solid #e5e7eb;border-radius:8px;padding:10px 12px;font-size:14px;outline:none">
        </div>
        <div>
          <label style="font-size:12px;font-weight:700;color:#374151;display:block;margin-bottom:5px">EMAIL (optional)</label>
          <input id="cpEmail" type="email" autocomplete="off" placeholder="player@email.com"
            style="width:100%;box-sizing:border-box;border:1.5px solid #e5e7eb;border-radius:8px;padding:10px 12px;font-size:14px;outline:none">
        </div>
        <div>
          <label style="font-size:12px;font-weight:700;color:#374151;display:block;margin-bottom:5px">PASSWORD *</label>
          <input id="cpPassword" type="text" autocomplete="off" placeholder="min 6 characters"
            style="width:100%;box-sizing:border-box;border:1.5px solid #e5e7eb;border-radius:8px;padding:10px 12px;font-size:14px;outline:none">
        </div>
        <div>
          <label style="font-size:12px;font-weight:700;color:#374151;display:block;margin-bottom:5px">STARTING BALANCE ($)</label>
          <input id="cpBalance" type="number" min="0" value="0" placeholder="0.00"
            style="width:100%;box-sizing:border-box;border:1.5px solid #e5e7eb;border-radius:8px;padding:10px 12px;font-size:14px;outline:none">
        </div>
      </div>
      <div style="display:flex;gap:10px;margin-top:20px">
        <button onclick="closeCreatePlayer()" style="flex:1;background:#f3f4f6;border:1px solid #e5e7eb;border-radius:8px;padding:11px;font-size:14px;font-weight:600;cursor:pointer;color:#374151">Cancel</button>
        <button id="cpSubmitBtn" onclick="submitCreatePlayer()" style="flex:2;background:#852c2c;border:none;border-radius:8px;padding:11px;font-size:14px;font-weight:700;cursor:pointer;color:#fff">Create Player</button>
      </div>
    </div>`;
}

function closeCreatePlayer() {
  const m = document.getElementById('createPlayerModal');
  if (m) m.innerHTML = '';
}

async function submitCreatePlayer() {
  const username = (document.getElementById('cpUsername').value || '').trim();
  const email    = (document.getElementById('cpEmail').value    || '').trim();
  const password = (document.getElementById('cpPassword').value || '').trim();
  const balance  = parseFloat(document.getElementById('cpBalance').value || 0) || 0;
  const errEl    = document.getElementById('createPlayerErr');
  const btn      = document.getElementById('cpSubmitBtn');

  errEl.style.display = 'none';
  if (!username) { errEl.textContent = 'Username is required'; errEl.style.display = 'block'; return; }
  if (!password || password.length < 6) { errEl.textContent = 'Password must be at least 6 characters'; errEl.style.display = 'block'; return; }

  btn.textContent = 'Creating…'; btn.disabled = true;
  const res = await apiFetch('/players/create', 'POST', { username, email: email||null, password, balance });
  btn.textContent = 'Create Player'; btn.disabled = false;

  if (res.success) {
    closeCreatePlayer();
    renderPlayers();
    alert(`✅ Player "${username}" created successfully!`);
  } else {
    errEl.textContent = res.msg || 'Could not create player';
    errEl.style.display = 'block';
  }
}

// ── Toggle Enable/Disable ──
async function togglePlayerStatus(id, username, currentStatus) {
  const isActive = !currentStatus || currentStatus === 'active';
  const action = isActive ? 'disable' : 'enable';
  if (!confirm(`${isActive ? 'Disable' : 'Enable'} account for ${username}?\n\nPlayer will ${isActive ? 'no longer be able to log in' : 'be able to log in again'}.`)) return;
  const res = await apiFetch(`/players/${id}/toggle-status`, 'POST', {});
  if (res.success) {
    renderPlayers();
  } else {
    alert('Error: ' + (res.msg || `Could not ${action} player`));
  }
}

// ── View Player Slide-over ──
async function viewPlayer(id) {
  let panel = document.getElementById('viewPlayerPanel');
  if (!panel) {
    panel = document.createElement('div');
    panel.id = 'viewPlayerPanel';
    document.body.appendChild(panel);
  }
  panel.innerHTML = `
    <div onclick="closeViewPlayer()" style="position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:1000"></div>
    <div style="position:fixed;top:0;right:0;bottom:0;z-index:1001;background:#fff;width:min(96vw,520px);overflow-y:auto;box-shadow:-8px 0 40px rgba(0,0,0,.2);display:flex;align-items:center;justify-content:center">
      <div style="color:#6b7280;font-size:14px">Loading…</div>
    </div>`;

  const res = await apiFetch(`/players/${id}`);
  if (!res.success) {
    panel.innerHTML = '';
    return alert('Error: ' + res.msg);
  }
  const p  = res.data;
  const ga = (p.game_accounts || []);
  const tx = (p.transactions  || []).slice(0, 10);
  const isActive = !p.status || p.status === 'active';

  const txTypeColor = t => ({ deposit:'#16a34a', credit:'#16a34a', tip:'#ceb05d', withdrawal:'#dc2626', redeem:'#dc2626' })[t] || '#6b7280';
  const txSign = t => (['deposit','credit'].includes(t) ? '+' : '−');

  panel.innerHTML = `
    <div onclick="closeViewPlayer()" style="position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:1000"></div>
    <div style="position:fixed;top:0;right:0;bottom:0;z-index:1001;background:#f9fafb;width:min(96vw,520px);overflow-y:auto;box-shadow:-8px 0 40px rgba(0,0,0,.2)">
      <!-- Header -->
      <div style="background:#fff;border-bottom:1px solid #e5e7eb;padding:16px 20px;display:flex;align-items:center;gap:12px;position:sticky;top:0;z-index:2">
        <button onclick="closeViewPlayer()" style="background:#f3f4f6;border:1px solid #e5e7eb;border-radius:8px;width:34px;height:34px;font-size:18px;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0">←</button>
        <div style="flex:1">
          <div style="font-size:17px;font-weight:700;color:#111">${escAdm(p.username)}</div>
          <div style="font-size:12px;color:#6b7280">${escAdm(p.email||'No email')}</div>
        </div>
        <span style="background:${isActive?'#dcfce7':'#fee2e2'};color:${isActive?'#166534':'#991b1b'};font-size:11px;font-weight:700;padding:4px 12px;border-radius:20px">${p.status||'active'}</span>
      </div>

      <div style="padding:16px">
        <!-- Stats row -->
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:16px">
          <div style="background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:14px;text-align:center">
            <div style="font-size:11px;font-weight:700;color:#6b7280;letter-spacing:1px;margin-bottom:4px">BALANCE</div>
            <div style="font-size:20px;font-weight:800;color:#111">$${Number(p.balance||0).toFixed(2)}</div>
          </div>
          <div style="background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:14px;text-align:center">
            <div style="font-size:11px;font-weight:700;color:#6b7280;letter-spacing:1px;margin-bottom:4px">BW</div>
            <div style="font-size:20px;font-weight:800;color:#ceb05d">${Number(p.fp_credits||0)}</div>
          </div>
          <div style="background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:14px;text-align:center">
            <div style="font-size:11px;font-weight:700;color:#6b7280;letter-spacing:1px;margin-bottom:4px">JOINED</div>
            <div style="font-size:12px;font-weight:700;color:#111">${(p.created_at||'').slice(0,10)||'—'}</div>
          </div>
        </div>

        <!-- Quick actions -->
        <div style="display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap">
          <button onclick="closeViewPlayer();creditPlayer(${p.id},'${escAdm(p.username)}')" style="flex:1;min-width:90px;background:#dcfce7;border:1px solid #bbf7d0;border-radius:8px;padding:9px 12px;font-size:12px;font-weight:700;color:#166534;cursor:pointer">+ Credit</button>
          <button onclick="closeViewPlayer();redeemPlayer(${p.id},'${escAdm(p.username)}',${Number(p.balance||0).toFixed(2)})" style="flex:1;min-width:90px;background:#fee2e2;border:1px solid #fecaca;border-radius:8px;padding:9px 12px;font-size:12px;font-weight:700;color:#991b1b;cursor:pointer">− Redeem</button>
          <button onclick="closeViewPlayer();adminResetPw(${p.id},'${escAdm(p.username)}')" style="flex:1;min-width:90px;background:#fef3c7;border:1px solid #fde68a;border-radius:8px;padding:9px 12px;font-size:12px;font-weight:700;color:#92400e;cursor:pointer">🔑 Reset PW</button>
          <button onclick="closeViewPlayer();togglePlayerStatus(${p.id},'${escAdm(p.username)}','${p.status||'active'}')" style="flex:1;min-width:90px;background:${isActive?'#fee2e2':'#dcfce7'};border:1px solid ${isActive?'#fecaca':'#bbf7d0'};border-radius:8px;padding:9px 12px;font-size:12px;font-weight:700;color:${isActive?'#991b1b':'#166534'};cursor:pointer">${isActive?'Disable':'Enable'}</button>
        </div>

        <!-- Game Accounts -->
        <div style="background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:16px;margin-bottom:14px">
          <div style="font-size:12px;font-weight:700;color:#6b7280;letter-spacing:1.5px;margin-bottom:12px">GAME ACCOUNTS (${ga.length})</div>
          ${ga.length === 0
            ? '<div style="color:#9ca3af;font-size:13px;text-align:center;padding:8px 0">No game accounts linked</div>'
            : ga.map(g => `
          <div style="border-bottom:1px solid #f3f4f6;padding:12px 0">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
              <span style="font-size:11px;font-weight:700;color:#852c2c;background:#eff6ff;padding:3px 10px;border-radius:20px">${escAdm(g.game||'Unknown Game')}</span>
              <span id="gbal_${g.id}" style="font-size:12px;font-weight:700;color:#111;background:#f3f4f6;padding:3px 10px;border-radius:20px">Balance: —</span>
            </div>
            <div style="display:grid;grid-template-columns:80px 1fr;gap:6px 12px;margin-bottom:10px;align-items:center">
              <div style="font-size:11px;color:#9ca3af;font-weight:600">USERNAME</div>
              <div style="font-size:13px;font-weight:700;color:#111;word-break:break-all">${escAdm(g.game_username||'—')}</div>
              <div style="font-size:11px;color:#9ca3af;font-weight:600">PASSWORD</div>
              <div style="display:flex;align-items:center;gap:8px">
                <span id="gpw_${g.id}" style="font-size:13px;font-weight:700;color:#111;letter-spacing:2px">••••••</span>
                <button onclick="toggleGamePw('${g.id}','${escAdm(g.game_password||'')}')" style="background:#f3f4f6;border:1px solid #e5e7eb;border-radius:5px;padding:3px 8px;font-size:11px;cursor:pointer;color:#374151">Show</button>
              </div>
            </div>
            <div style="display:flex;gap:6px;flex-wrap:wrap">
              <button onclick="adminCheckGameBal(${p.id},'${escAdm(g.game||'')}','${escAdm(g.game_username||'')}','${g.id}')" style="background:#f0f9ff;border:1px solid #bae6fd;border-radius:7px;padding:6px 12px;font-size:12px;font-weight:700;color:#0369a1;cursor:pointer">⟳ Balance</button>
              <button onclick="adminGameLoad(${p.id},'${escAdm(g.game||'')}','${escAdm(g.game_username||'')}','${g.id}')" style="background:#dcfce7;border:1px solid #bbf7d0;border-radius:7px;padding:6px 12px;font-size:12px;font-weight:700;color:#166534;cursor:pointer">↑ Load</button>
              <button onclick="adminGameRedeem(${p.id},'${escAdm(g.game||'')}','${escAdm(g.game_username||'')}','${g.id}')" style="background:#fee2e2;border:1px solid #fecaca;border-radius:7px;padding:6px 12px;font-size:12px;font-weight:700;color:#991b1b;cursor:pointer">↓ Redeem</button>
            </div>
          </div>`).join('')}
        </div>

        <!-- Recent Transactions -->
        <div style="background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:16px">
          <div style="font-size:12px;font-weight:700;color:#6b7280;letter-spacing:1.5px;margin-bottom:12px">RECENT TRANSACTIONS</div>
          ${tx.length === 0
            ? '<div style="color:#9ca3af;font-size:13px;text-align:center;padding:8px 0">No transactions yet</div>'
            : tx.map(t => `
          <div style="display:flex;align-items:center;gap:12px;padding:9px 0;border-bottom:1px solid #f9fafb">
            <div style="width:34px;height:34px;border-radius:50%;background:#f3f4f6;display:flex;align-items:center;justify-content:center;font-size:14px;flex-shrink:0">
              ${{deposit:'💰',credit:'➕',withdrawal:'💸',tip:'🎁',redeem:'🔴'}[t.type]||'📋'}
            </div>
            <div style="flex:1">
              <div style="font-size:13px;font-weight:600;color:#111;text-transform:capitalize">${escAdm(t.type)}</div>
              <div style="font-size:11px;color:#9ca3af">${(t.created_at||'').slice(0,16).replace('T',' ')} · ${escAdm(t.status||'')}</div>
              ${t.notes ? `<div style="font-size:11px;color:#6b7280;margin-top:2px">${escAdm(t.notes)}</div>` : ''}
            </div>
            <div style="font-size:14px;font-weight:700;color:${txTypeColor(t.type)}">${txSign(t.type)}$${Number(t.amount||0).toFixed(2)}</div>
          </div>`).join('')}
        </div>
      </div>
    </div>`;
}

function closeViewPlayer() {
  const p = document.getElementById('viewPlayerPanel');
  if (p) p.innerHTML = '';
}

function toggleGamePw(id, pw) {
  const el  = document.getElementById('gpw_' + id);
  const btn = el?.nextElementSibling;
  if (!el) return;
  if (el.textContent === '••••••') {
    el.textContent = pw || '(empty)';
    el.style.letterSpacing = '0';
    if (btn) btn.textContent = 'Hide';
  } else {
    el.textContent = '••••••';
    el.style.letterSpacing = '2px';
    if (btn) btn.textContent = 'Show';
  }
}

// ── Admin Game Account Actions ──
async function adminCheckGameBal(pid, game, gameUsername, gaId) {
  const el = document.getElementById('gbal_' + gaId);
  if (el) el.textContent = 'Checking…';
  const res = await apiFetch(`/players/${pid}/game-balance?game=${encodeURIComponent(game)}`);
  if (el) {
    el.textContent = res.success
      ? `Balance: $${Number(res.data.balance || 0).toFixed(2)}`
      : 'Error: ' + (res.msg || 'failed');
    el.style.color = res.success ? '#166534' : '#991b1b';
    el.style.background = res.success ? '#dcfce7' : '#fee2e2';
  }
}

async function adminGameLoad(pid, game, gameUsername, gaId) {
  const amtStr = prompt(`Load credits to ${gameUsername} (${game})\n\nEnter amount:`, '');
  if (!amtStr) return;
  const amount = parseFloat(amtStr);
  if (isNaN(amount) || amount <= 0) { alert('Enter a valid amount.'); return; }
  const res = await apiFetch(`/players/${pid}/add-credits`, 'POST', { game, amount, game_username: gameUsername });
  if (res.success) {
    alert(`✅ $${amount.toFixed(2)} loaded to ${gameUsername} (${game})`);
    adminCheckGameBal(pid, game, gameUsername, gaId);
  } else {
    alert('Error: ' + (res.msg || 'Could not load credits'));
  }
}

async function adminGameRedeem(pid, game, gameUsername, gaId) {
  const amtStr = prompt(`Redeem credits from ${gameUsername} (${game})\n\nEnter amount:`, '');
  if (!amtStr) return;
  const amount = parseFloat(amtStr);
  if (isNaN(amount) || amount <= 0) { alert('Enter a valid amount.'); return; }
  const res = await apiFetch(`/players/${pid}/withdraw-credits`, 'POST', { game, amount, game_username: gameUsername });
  if (res.success) {
    alert(`✅ $${amount.toFixed(2)} redeemed from ${gameUsername} (${game})`);
    adminCheckGameBal(pid, game, gameUsername, gaId);
  } else {
    alert('Error: ' + (res.msg || 'Could not redeem credits'));
  }
}

async function creditPlayer(id, username) {
  const amtStr = prompt(`Add wallet balance to ${username}\n\nEnter amount to credit (e.g. 50):`, '');
  if (!amtStr) return;
  const amount = parseFloat(amtStr);
  if (isNaN(amount) || amount <= 0) { alert('Enter a valid amount greater than 0.'); return; }
  const note = prompt('Note (optional):', 'Manual credit by admin') || 'Manual credit by admin';
  const res = await apiFetch(`/players/${id}/credit`, 'POST', { amount, note });
  if (res.success) {
    alert(`✅ $${amount.toFixed(2)} credited to ${username}\nNew balance: $${Number(res.data.new_balance).toFixed(2)}`);
    renderPlayers();
  } else {
    alert('Error: ' + (res.msg || 'Could not credit player'));
  }
}

async function redeemPlayer(id, username, currentBalance) {
  const amtStr = prompt(`Redeem (deduct) balance from ${username}\nCurrent balance: $${Number(currentBalance).toFixed(2)}\n\nEnter amount to redeem:`, '');
  if (!amtStr) return;
  const amount = parseFloat(amtStr);
  if (isNaN(amount) || amount <= 0) { alert('Enter a valid amount greater than 0.'); return; }
  if (amount > currentBalance) { alert(`Cannot redeem more than the player's balance ($${Number(currentBalance).toFixed(2)})`); return; }
  const note = prompt('Reason (optional):', 'Balance redeemed by admin') || 'Balance redeemed by admin';
  const res = await apiFetch(`/players/${id}/redeem`, 'POST', { amount, note });
  if (res.success) {
    alert(`✅ $${amount.toFixed(2)} redeemed from ${username}\nNew balance: $${Number(res.data.new_balance).toFixed(2)}`);
    renderPlayers();
  } else {
    alert('Error: ' + (res.msg || 'Could not redeem balance'));
  }
}

async function adminResetPw(id, username) {
  const newPw = prompt(`Reset password for ${username}\n\nEnter new password (min 6 chars):`, '');
  if (!newPw) return;
  if (newPw.length < 6) { alert('Password must be at least 6 characters.'); return; }
  const res = await apiFetch(`/players/${id}/admin-reset-password`, 'POST', { new_password: newPw });
  if (res.success) {
    alert(`✅ Password reset for ${username}`);
  } else {
    alert('Error: ' + (res.msg || 'Could not reset password'));
  }
}

// ── RENDER TRANSACTIONS (live) ──
async function renderAllTxns() {
  const el = document.getElementById('allTxnList');
  if (!el) return;
  const res  = await apiFetch('/transactions?limit=50');
  const list = res.success ? res.data : TRANSACTIONS.map(t => ({username: t.user, type: t.type, amount: t.amount.replace('$',''), status: t.status, created_at: t.time}));
  el.innerHTML = list.length === 0
    ? '<div style="text-align:center;padding:40px;color:#6b7280">No transactions yet</div>'
    : list.map(t => `
      <div class="txn-row">
        <div class="txn-avatar">${(t.username||'?')[0].toUpperCase()}</div>
        <div class="txn-info">
          <div class="txn-name">${t.username}</div>
          <div class="txn-type">${t.type} · ${(t.created_at||'').slice(0,16)}</div>
        </div>
        <div class="txn-right">
          <div class="txn-amt">$${Number(t.amount||0).toFixed(2)}</div>
          <div class="txn-badge badge-${t.status}">${t.status}</div>
        </div>
      </div>`).join('');
}

// ── RENDER DEPOSITS (live) ──
async function renderDeposits() {
  const el = document.getElementById('depositList');
  if (!el) return;
  const res  = await apiFetch('/deposits');
  const list = res.success ? res.data : [];
  el.innerHTML = list.length === 0
    ? '<div style="text-align:center;padding:40px;color:#6b7280">No deposit requests</div>'
    : list.map(d => `
      <div class="txn-row" style="flex-wrap:wrap;gap:8px;align-items:flex-start">
        <div class="txn-avatar">${(d.username||'?')[0].toUpperCase()}</div>
        <div class="txn-info" style="flex:1">
          <div class="txn-name">${d.username}</div>
          <div class="txn-type">${d.method} · $${Number(d.amount).toFixed(2)} · ${(d.created_at||'').slice(0,16)}</div>
          ${d.payment_url ? `<a href="${d.payment_url}" target="_blank" style="font-size:10px;color:#852c2c;text-decoration:underline">🔗 KeyHub payment link</a>` : ''}
          ${d.screenshot ? `
            <div style="margin-top:8px">
              <img src="${d.screenshot}" alt="Receipt" onclick="window.open(this.src,'_blank')"
                style="max-width:120px;max-height:100px;border-radius:8px;border:2px solid #bbf7d0;cursor:zoom-in;display:block">
              <span style="font-size:10px;color:#16a34a;font-weight:600">📸 Receipt attached — click to enlarge</span>
            </div>` : `<div style="margin-top:4px;font-size:10px;color:#f59e0b">⏳ No receipt yet</div>`}
        </div>
        <div class="txn-right">
          <div class="txn-amt" style="color:#22c55e">$${Number(d.amount).toFixed(2)}</div>
          <div style="display:flex;gap:4px;margin-top:4px;flex-wrap:wrap">
            ${d.status==='pending' ? `
              <button onclick="approveDeposit(${d.id})" style="background:#dcfce7;border:none;border-radius:4px;padding:3px 8px;font-size:10px;font-weight:700;color:#166534;cursor:pointer">✓ Approve</button>
              <button onclick="rejectDeposit(${d.id})" style="background:#fee2e2;border:none;border-radius:4px;padding:3px 8px;font-size:10px;font-weight:700;color:#991b1b;cursor:pointer">✗ Reject</button>
            ` : `<div class="txn-badge badge-${d.status}">${d.status}</div>`}
          </div>
        </div>
      </div>`).join('');
}

async function approveDeposit(id) {
  const res = await apiFetch(`/deposits/${id}/approve`, 'POST');
  alert(res.msg);
  renderDeposits();
  loadStats();
}
async function rejectDeposit(id) {
  const res = await apiFetch(`/deposits/${id}/reject`, 'POST');
  alert(res.msg);
  renderDeposits();
}

// ── DEPOSIT SETTINGS (screenshot required toggle) ──
async function loadDepositSettings() {
  const res = await apiFetch('/deposit-settings');
  if (!res.success) return;
  const required = !!res.data.screenshot_required;
  const toggle   = document.getElementById('screenshotReqToggle');
  const label    = document.getElementById('screenshotReqLabel');
  const track    = document.getElementById('screenshotToggleTrack');
  const thumb    = document.getElementById('screenshotToggleThumb');
  if (toggle) toggle.checked = required;
  if (label)  { label.textContent = required ? 'Required' : 'Optional'; label.style.background = required ? '#dcfce7' : '#fee2e2'; label.style.color = required ? '#166534' : '#991b1b'; }
  if (track)  track.style.background = required ? '#16a34a' : '#d1d5db';
  if (thumb)  thumb.style.left = required ? '22px' : '2px';
}

async function saveDepositSettings() {
  const required = document.getElementById('screenshotReqToggle')?.checked;
  const label    = document.getElementById('screenshotReqLabel');
  const track    = document.getElementById('screenshotToggleTrack');
  const thumb    = document.getElementById('screenshotToggleThumb');
  if (label)  { label.textContent = required ? 'Required' : 'Optional'; label.style.background = required ? '#dcfce7' : '#fee2e2'; label.style.color = required ? '#166534' : '#991b1b'; }
  if (track)  track.style.background = required ? '#16a34a' : '#d1d5db';
  if (thumb)  thumb.style.left = required ? '22px' : '2px';
  await apiFetch('/admin/deposit-settings', 'POST', { screenshot_required: required ? 1 : 0 });
}

// ── ADMIN MANUAL DEPOSIT MODAL ──
async function openAdminDepositModal() {
  // Populate method dropdown from payment methods
  const res = await apiFetch('/admin/payment-methods');
  const sel = document.getElementById('adm_dep_method');
  if (sel && res.success && res.data.length) {
    sel.innerHTML = res.data.map(m => `<option value="${m.key}">${m.icon || ''} ${m.name}</option>`).join('');
  }
  document.getElementById('adminDepositModal').style.display = 'flex';
}

function closeAdminDepositModal() {
  document.getElementById('adminDepositModal').style.display = 'none';
  ['adm_dep_username','adm_dep_amount'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
  document.getElementById('adm_dep_note').value = 'Manual deposit by admin';
  document.getElementById('adm_dep_screenshot_preview_wrap').style.display = 'none';
  document.getElementById('adm_dep_screenshot_input').value = '';
  document.getElementById('adm_dep_msg').textContent = '';
}

function previewAdminScreenshot(event) {
  const file = event.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = e => {
    document.getElementById('adm_dep_screenshot_preview').src = e.target.result;
    document.getElementById('adm_dep_screenshot_preview_wrap').style.display = 'block';
  };
  reader.readAsDataURL(file);
}

async function submitAdminDeposit() {
  const username = (document.getElementById('adm_dep_username')?.value || '').trim();
  const amount   = parseFloat(document.getElementById('adm_dep_amount')?.value || '0');
  const method   = document.getElementById('adm_dep_method')?.value || 'cashapp';
  const note     = (document.getElementById('adm_dep_note')?.value || 'Manual deposit by admin').trim();
  const screenshot = document.getElementById('adm_dep_screenshot_preview')?.src || '';
  const msgEl    = document.getElementById('adm_dep_msg');

  if (!username) { if (msgEl) { msgEl.textContent = 'Player username is required.'; msgEl.style.color = '#991b1b'; } return; }
  if (!amount || amount <= 0) { if (msgEl) { msgEl.textContent = 'Enter a valid amount.'; msgEl.style.color = '#991b1b'; } return; }

  // Look up player id by username
  const pRes = await apiFetch('/players');
  const player = (pRes.success ? pRes.data : []).find(p => p.username.toLowerCase() === username.toLowerCase());
  if (!player) { if (msgEl) { msgEl.textContent = `Player "${username}" not found.`; msgEl.style.color = '#991b1b'; } return; }

  // Create deposit request
  const dRes = await apiFetch('/deposits', 'POST', { player_id: player.id, username: player.username, amount, method });
  if (!dRes.success) { if (msgEl) { msgEl.textContent = dRes.msg || 'Failed to create deposit.'; msgEl.style.color = '#991b1b'; } return; }

  const depId = dRes.data.request_id;

  // Attach screenshot if provided
  if (screenshot && screenshot.startsWith('data:image')) {
    await apiFetch(`/deposits/${depId}/screenshot`, 'POST', { screenshot });
  }

  // Approve immediately
  const aRes = await apiFetch(`/deposits/${depId}/approve`, 'POST');
  if (msgEl) {
    msgEl.textContent = aRes.success ? `✅ $${amount.toFixed(2)} deposited & credited to ${player.username}` : (aRes.msg || 'Approval failed.');
    msgEl.style.color = aRes.success ? '#166534' : '#991b1b';
  }
  if (aRes.success) {
    setTimeout(() => { closeAdminDepositModal(); renderDeposits(); loadStats(); }, 1500);
  }
}

// ── RENDER WITHDRAWALS (live) ──
async function renderWithdrawals() {
  const el = document.getElementById('withdrawalList');
  if (!el) return;
  const res  = await apiFetch('/withdrawals');
  const list = res.success ? res.data : [];
  el.innerHTML = list.length === 0
    ? '<div style="text-align:center;padding:40px;color:#6b7280">No withdrawal requests</div>'
    : list.map(w => `
      <div class="txn-row" style="flex-wrap:wrap;gap:8px">
        <div class="txn-avatar">${(w.username||'?')[0].toUpperCase()}</div>
        <div class="txn-info">
          <div class="txn-name">${w.username}</div>
          <div class="txn-type">${w.method} · $${Number(w.amount).toFixed(2)} · ${(w.created_at||'').slice(0,16)}</div>
          ${w.address ? `<div style="font-size:11px;color:#9ca3af">To: ${w.address}</div>` : ''}
          ${w.payout_url ? `<a href="${w.payout_url}" target="_blank" style="font-size:10px;color:#22c55e;text-decoration:underline">🔗 KeyHub payout link</a>` : ''}
        </div>
        <div class="txn-right">
          <div class="txn-amt" style="color:#f97316">$${Number(w.amount).toFixed(2)}</div>
          <div style="display:flex;gap:4px;margin-top:4px">
            ${w.status==='pending' ? `
              <button onclick="approveWithdrawal(${w.id})" style="background:#dcfce7;border:none;border-radius:4px;padding:3px 8px;font-size:10px;font-weight:700;color:#166534;cursor:pointer">✓ Send</button>
              <button onclick="rejectWithdrawal(${w.id})" style="background:#fee2e2;border:none;border-radius:4px;padding:3px 8px;font-size:10px;font-weight:700;color:#991b1b;cursor:pointer">✗ Reject</button>
            ` : `<div class="txn-badge badge-${w.status}">${w.status}</div>`}
          </div>
        </div>
      </div>`).join('');
}

async function approveWithdrawal(id) {
  const res = await apiFetch(`/withdrawals/${id}/approve`, 'POST');
  if (res.data?.payout_url) {
    alert(`${res.msg}\n\nPayout link for player:\n${res.data.payout_url}`);
  } else {
    alert(res.msg || 'Approved');
  }
  renderWithdrawals();
  loadStats();
}
async function rejectWithdrawal(id) {
  if (!confirm('Reject this withdrawal? Balance will be refunded.')) return;
  const res = await apiFetch(`/withdrawals/${id}/reject`, 'POST');
  alert(res.msg || 'Rejected');
  renderWithdrawals();
}

// ── LOAD LIVE STATS ──
async function loadStats() {
  const res = await apiFetch('/stats');
  if (!res.success) return;
  const d = res.data;
  document.getElementById('stat-players')?.textContent    != null && (document.getElementById('stat-players').textContent = d.total_players);
  document.getElementById('stat-deposits')?.textContent   != null && (document.getElementById('stat-deposits').textContent = d.pending_deposits);
  document.getElementById('stat-withdrawals')?.textContent != null && (document.getElementById('stat-withdrawals').textContent = d.pending_withdrawals);
  document.getElementById('stat-accounts')?.textContent   != null && (document.getElementById('stat-accounts').textContent = d.total_games);
  document.getElementById('wallet-cash')?.textContent     != null && (document.getElementById('wallet-cash').textContent = '$' + d.total_balance);
  document.getElementById('wallet-fp')?.textContent       != null && (document.getElementById('wallet-fp').textContent = d.total_fp + ' BW');
  document.getElementById('wallet-total')?.textContent    != null && (document.getElementById('wallet-total').textContent = '$' + d.total_balance + ' + ' + d.total_fp + ' BW');
  document.getElementById('dep-today')?.textContent       != null && (document.getElementById('dep-today').textContent = '$' + d.deposits_today);
  document.getElementById('wd-today')?.textContent        != null && (document.getElementById('wd-today').textContent = '$' + d.withdrawals_today);
  [['dep-week', d.deposits_week], ['dep-month', d.deposits_month], ['wd-week', d.withdrawals_week], ['wd-month', d.withdrawals_month]]
    .forEach(([id, v]) => { const el = document.getElementById(id); if (el && v != null) el.textContent = '$' + Number(v).toFixed(2); });
}

// ── BACKEND ATTACHMENTS ──
const GAME_NAMES = {
  juwa:'Juwa', juwa2:'Juwa 2.0', gamevault:'Game Vault', milkyway:'Milky Way',
  orionstars:'Orion Stars', ultrapanda:'Ultra Panda', firekirin:'Fire Kirin',
  gameroom:'Gameroom', cashfrenzy:'Cash Frenzy', cashmachine:'Cash Machine',
  mafia:'Mafia', mrallinone:'Mr. All In One', vblink:'Vblink',
  pandamaster:'Panda Master', yolo:'Yolo', vegassweeps:'Vegas Sweeps',
  riversweeps:'Riversweeps', dragonfury:'Dragon Fury', ultrathunder:'Ultra Thunder',
};

const GAME_URLS = {
  juwa:        'https://ht.juwa777.com',
  juwa2:       'https://agent.juwa2.com',
  gamevault:   'https://agent.gamevault999.com',
  milkyway:    'https://milkywayapp.xyz:8781',
  orionstars:  'https://orionstars.vip:8781',
  firekirin:   'https://firekirin.xyz:8888',
  ultrapanda:  'https://ht.ultrapanda.mobi',
  vblink:      'https://gm.vblink777.club',
  pandamaster: 'https://pandamaster.vip',
  gameroom:    'https://agentserver1.gameroom777.com',
  cashfrenzy:  'https://agentserver.cashfrenzy777.com',
  cashmachine: 'https://agentserver.cashmachine777.com',
  mafia:       'https://agentserver.mafia77777.com',
  mrallinone:  'https://agentserver.mrallinone777.com',
  yolo:        'https://agent.yolo777.game',
  vegassweeps: 'https://agent.lasvegassweeps.com',
  riversweeps: 'https://river-pay.com',
  dragonfury:  'https://pccnz.dragonfury.club',
  ultrathunder:'https://fmubk.ultrathunder.mobi',
};

const GAME_ICONS = {
  juwa:'🎰', juwa2:'🎰', gamevault:'🏦', milkyway:'🌌', orionstars:'⭐', ultrapanda:'🐼',
  firekirin:'🔥', gameroom:'🎮', cashfrenzy:'💵', cashmachine:'🎰',
  mafia:'🎲', mrallinone:'👑', vblink:'⚡', pandamaster:'🐼',
  yolo:'🎯', vegassweeps:'🎪', riversweeps:'🌊', dragonfury:'🐉', ultrathunder:'⚡',
};

let attachedBackends = JSON.parse(localStorage.getItem('fpBackends') || '[]');

function autoFillName() {
  const game = document.getElementById('ab-game').value;
  const nameEl = document.getElementById('ab-name');
  if (game && !nameEl.value) {
    nameEl.value = (GAME_NAMES[game] || game) + ' Backend';
  }
}

const LOADSTAR_URL = 'https://www.loadstar.online';

function toggleLoadstar() {
  const on = document.getElementById('ab-loadstar').checked;
  document.getElementById('ab-user-label').textContent = on ? 'Label (any name)' : 'Backend username';
  document.getElementById('ab-pass-label').textContent = on ? 'Loadstar API key (ls_live_…)' : 'Backend password';
  document.getElementById('ab-user').placeholder = on ? 'loadstar' : 'BACKEND_USERNAME';
  document.getElementById('ab-pass').placeholder = on ? 'ls_live_…  (Loadstar → Settings → API keys)' : 'BACKEND_PASSWORD';
  if (on && !document.getElementById('ab-user').value) document.getElementById('ab-user').value = 'loadstar';
  document.getElementById('ab-loadstar-all').style.display = on ? '' : 'none';
  autoFillUrl();
}

function autoFillUrl() {
  const game  = document.getElementById('ab-game').value;
  const urlEl = document.getElementById('ab-url');
  if (document.getElementById('ab-loadstar')?.checked) {
    urlEl.value       = LOADSTAR_URL;
    urlEl.style.color = '#34d399';
  } else if (game && GAME_URLS[game]) {
    urlEl.value       = GAME_URLS[game];
    urlEl.style.color = '#34d399';
  } else {
    urlEl.value       = '';
    urlEl.style.color = '';
  }
}

function toggleField(id, btn) {
  const input = document.getElementById(id);
  if (input.type === 'password') {
    input.type = 'text';
    btn.style.color = '#852c2c';
  } else {
    input.type = 'password';
    btn.style.color = '';
  }
}

async function attachBackend() {
  const game     = document.getElementById('ab-game').value;
  const name     = document.getElementById('ab-name').value.trim();
  const username = document.getElementById('ab-user').value.trim();
  const password = document.getElementById('ab-pass').value.trim();
  const token    = document.getElementById('ab-token').value.trim();
  const base_url = document.getElementById('ab-url').value.trim();
  const testConn = document.getElementById('ab-test').checked;
  const btn      = document.querySelector('.btn-attach');

  if (!game)     return showResult('error', '⚠ Please select a game.');
  if (!name)     return showResult('error', '⚠ Attachment name is required.');
  if (!username) return showResult('error', '⚠ Backend username is required.');
  if (!password) return showResult('error', '⚠ Backend password is required.');
  if (document.getElementById('ab-loadstar').checked && !password.startsWith('ls_'))
    return showResult('error', '⚠ That is not a Loadstar API key — it starts with ls_live_. Make one in Loadstar → Settings → API keys.');

  btn.disabled    = true;
  btn.textContent = testConn ? 'Testing & Attaching...' : 'Attaching...';
  showResult('testing', '🔄 ' + (testConn ? 'Testing connection to ' + (GAME_NAMES[game]||game) + '...' : 'Saving backend...'));

  const res = await apiFetch('/backends/attach', 'POST', { game, name, username, password, token, base_url, test_connection: testConn });

  btn.disabled    = false;
  btn.textContent = 'Attach Backend';

  if (res.success) {
    showResult('success', `✅ ${name} attached! Status: ${res.data?.status} — ${res.msg}`);
    document.getElementById('ab-game').value  = '';
    document.getElementById('ab-name').value  = '';
    document.getElementById('ab-user').value  = '';
    document.getElementById('ab-pass').value  = '';
    document.getElementById('ab-token').value = '';
    await loadAttachedList();
  } else {
    showResult('error', '❌ ' + res.msg);
  }
}

async function attachAllLoadstar() {
  const api_key  = document.getElementById('ab-pass').value.trim();
  const base_url = document.getElementById('ab-url').value.trim();
  const username = document.getElementById('ab-user').value.trim();
  if (!api_key.startsWith('ls_'))
    return showResult('error', '⚠ Paste your Loadstar API key (ls_live_…) first.');
  const btn = document.getElementById('ab-loadstar-all');
  btn.disabled = true;
  showResult('testing', '🔄 Asking Loadstar which games you have...');
  const res = await apiFetch('/backends/attach-loadstar', 'POST', { api_key, base_url, username });
  btn.disabled = false;
  if (res.success) {
    showResult(res.data.added.length ? 'success' : 'error', (res.data.added.length ? '✅ ' : 'ℹ ') + res.msg);
    if (res.data.added.length) document.getElementById('ab-pass').value = '';
    await loadAttachedList();
  } else {
    showResult('error', '❌ ' + res.msg);
  }
}

function showResult(type, msg) {
  const el = document.getElementById('ab-result');
  el.className = 'ab-result ' + type;
  el.textContent = msg;
  el.classList.remove('hidden');
}

async function loadAttachedList() {
  const res = await apiFetch('/backends');
  if (res.success) {
    attachedBackends = res.data || [];
  }
  renderAttachedList();
}

function renderAttachedList() {
  const el    = document.getElementById('attachedList');
  const count = document.getElementById('attachedCount');
  if (!el) return;

  count.textContent = attachedBackends.length + ' attached';

  if (attachedBackends.length === 0) {
    el.innerHTML = '<div class="no-backends">No backends attached yet.<br>Use the form to connect your first game.</div>';
    return;
  }

  el.innerHTML = attachedBackends.map(b => {
    const enabled = b.enabled !== 0;
    return `
    <div class="backend-item ${enabled ? '' : 'bi-disabled'}" id="bi-${b.id}">
      <div class="bi-icon">${GAME_ICONS[b.game] || '🎮'}</div>
      <div class="bi-info">
        <div class="bi-name">${b.name}</div>
        <div class="bi-game">${GAME_NAMES[b.game] || b.game}</div>
        <div class="bi-user">User: ${b.username}</div>
        ${b.last_tested ? `<div class="bi-user">Tested: ${b.last_tested.slice(0,16)}</div>` : ''}
        ${b.is_loadstar ? `<div class="bi-user">Via Loadstar · new players go under:
          <select class="form-select" id="ls-under-${b.id}" style="margin-top:4px;font-size:12px;padding:4px 6px"
                  onchange="saveLoadstarUnder(${b.id}, this)"><option>Loading…</option></select></div>` : ''}
      </div>
      <span class="bi-status ${b.status}">${b.status}</span>
      <div class="bi-actions">
        <button class="btn-bi ${enabled ? 'btn-disable' : 'btn-enable'}" onclick="toggleBackend(${b.id})">${enabled ? 'Disable' : 'Enable'}</button>
        <button class="btn-bi" onclick="testBackend(${b.id})">Test</button>
        <button class="btn-bi danger" onclick="removeBackend(${b.id})">✕</button>
      </div>
    </div>`;
  }).join('');
  attachedBackends.filter(b => b.is_loadstar).forEach(b => loadLoadstarUnder(b.id));
}

async function loadLoadstarUnder(id) {
  const sel = document.getElementById(`ls-under-${id}`);
  if (!sel) return;
  const res = await apiFetch(`/backends/${id}/loadstar-accounts`);
  if (!res.success) {
    sel.innerHTML = `<option>⚠ ${res.msg}</option>`;
    sel.disabled = true;
    return;
  }
  const { under, accounts } = res.data;
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const opts = [
    ['', accounts.length ? 'Auto (my game account)' : 'Auto (Loadstar default)'],
    ...accounts.map(a => [a.id, `My account: ${a.name}${a.ready === false ? ' (not ready)' : ''}`]),
    ['admin', 'Loadstar admin (pay from wallet)'],
  ];
  sel.innerHTML = opts.map(([v, t]) => `<option value="${esc(v)}" ${v === under ? 'selected' : ''}>${esc(t)}</option>`).join('');
  if (accounts.length > 1 && !under) {
    sel.title = 'You have several accounts on this game — pick one, or set a default in Loadstar → Settings → New players';
  }
  sel.dataset.saved = under;
}

async function saveLoadstarUnder(id, sel) {
  sel.disabled = true;
  const res = await apiFetch(`/backends/${id}/loadstar-under`, 'POST', { under: sel.value });
  sel.disabled = false;
  if (res.success) {
    sel.dataset.saved = sel.value;
  } else {
    alert('Error: ' + res.msg);
    sel.value = sel.dataset.saved || '';
  }
}

async function toggleBackend(id) {
  const b = attachedBackends.find(x => x.id === id);
  if (b && b.enabled !== 0 && !confirm(
      `Turn off ${GAME_NAMES[b.game] || b.game}?\n\n` +
      `• Hidden from the games page and dashboard\n` +
      `• No new accounts and no new loads\n` +
      `• Players who already have it can still cash out\n\nYou can turn it back on any time.`)) return;
  const res = await apiFetch(`/backends/${id}/toggle`, 'POST');
  if (res.success) await loadAttachedList();
  else alert('Error: ' + res.msg);
}

async function testBackend(id) {
  const el = document.getElementById(`bi-${id}`);
  if (el) el.querySelector('.bi-status').textContent = 'testing...';
  const res = await apiFetch(`/backends/${id}/test`, 'POST');
  if (res.success) {
    alert(`${res.data.status.toUpperCase()}: ${res.data.message}`);
    await loadAttachedList();
  } else {
    alert('Error: ' + res.msg);
  }
}

async function removeBackend(id) {
  if (!confirm('Remove this backend attachment?')) return;
  const res = await apiFetch(`/backends/${id}`, 'DELETE');
  if (res.success) await loadAttachedList();
  else alert('Error: ' + res.msg);
}

function showNotifs() { alert('No new notifications'); }

function refreshDashboard() {
  renderRecentTxns();
  const btn = event.target.closest('button');
  btn.style.transform = 'rotate(360deg)';
  btn.style.transition = 'transform 0.5s';
  setTimeout(() => { btn.style.transform = ''; btn.style.transition = ''; }, 500);
}

// ── RECENT TXNS (live + fallback) ──
async function renderRecentTxns() {
  const el = document.getElementById('recentTxnList');
  if (!el) return;
  const res  = await apiFetch('/transactions?limit=5');
  const list = res.success && res.data.length > 0 ? res.data : TRANSACTIONS.slice(0,5).map(t => ({username:t.user, type:t.type, amount:t.amount.replace('$',''), status:t.status, created_at:t.time}));
  el.innerHTML = list.map(t => `
    <div class="txn-row">
      <div class="txn-avatar">${(t.username||'?')[0].toUpperCase()}</div>
      <div class="txn-info">
        <div class="txn-name">${t.username}</div>
        <div class="txn-type">${t.type}</div>
      </div>
      <div class="txn-right">
        <div class="txn-amt">$${Number(t.amount||0).toFixed(2)}</div>
        <div class="txn-badge badge-${t.status}">${t.status}</div>
      </div>
    </div>`).join('');
}

// ── FINANCE OVERVIEW ──
async function renderFinance() {
  const res = await apiFetch('/stats/finance');
  if (!res.success) return;
  const d = res.data;
  document.getElementById('financeStats').innerHTML = `
    <div class="stat-card"><div class="stat-label">Total Deposited</div><div class="stat-value">$${d.total_deposited.toFixed(2)}</div></div>
    <div class="stat-card"><div class="stat-label">Total Withdrawn</div><div class="stat-value">$${d.total_withdrawn.toFixed(2)}</div></div>
    <div class="stat-card"><div class="stat-label">Net</div><div class="stat-value" style="color:${d.net>=0?'#16a34a':'#ef4444'}">$${d.net.toFixed(2)}</div></div>
    <div class="stat-card"><div class="stat-label">Pending Deposits</div><div class="stat-value">$${d.pending_deposits.toFixed(2)}</div></div>
    <div class="stat-card"><div class="stat-label">Pending Withdrawals</div><div class="stat-value">$${d.pending_withdrawals.toFixed(2)}</div></div>`;
  document.getElementById('financeByMethod').innerHTML = d.by_method.length ? `
    <table class="data-table"><thead><tr><th>Method</th><th>Count</th><th>Total</th></tr></thead><tbody>
    ${d.by_method.map(m=>`<tr><td>${m.method}</td><td>${m.cnt}</td><td>$${Number(m.total).toFixed(2)}</td></tr>`).join('')}
    </tbody></table>` : '<p style="color:var(--muted)">No data yet</p>';
  document.getElementById('financeRecent').innerHTML = d.recent.length ? `
    <table class="data-table"><thead><tr><th>User</th><th>Type</th><th>Amount</th><th>Status</th><th>Date</th></tr></thead><tbody>
    ${d.recent.map(t=>`<tr><td>${t.username}</td><td>${t.type}</td><td>$${Number(t.amount||0).toFixed(2)}</td><td><span class="txn-badge badge-${t.status}">${t.status}</span></td><td>${(t.created_at||'').slice(0,16)}</td></tr>`).join('')}
    </tbody></table>` : '<p style="color:var(--muted)">No transactions yet</p>';
}

// ── GROWTH INSIGHTS ──
async function renderGrowth() {
  const res = await apiFetch('/stats/players');
  if (!res.success) return;
  const d = res.data;
  document.getElementById('growthStats').innerHTML = `
    <div class="stat-card"><div class="stat-label">Total Players</div><div class="stat-value">${d.total}</div></div>
    <div class="stat-card"><div class="stat-label">Active</div><div class="stat-value">${d.active}</div></div>
    <div class="stat-card"><div class="stat-label">With Balance</div><div class="stat-value">${d.with_balance}</div></div>`;
  document.getElementById('growthTop').innerHTML = d.top_players.length ? `
    <table class="data-table"><thead><tr><th>Player</th><th>Balance</th><th>BW Credits</th></tr></thead><tbody>
    ${d.top_players.map(p=>`<tr><td>${p.username}</td><td>$${Number(p.balance||0).toFixed(2)}</td><td>${Number(p.fp_credits||0).toFixed(1)}</td></tr>`).join('')}
    </tbody></table>` : '<p style="color:var(--muted)">No players yet</p>';
  document.getElementById('growthRecent').innerHTML = d.recent_players.length ? `
    <table class="data-table"><thead><tr><th>Player</th><th>Balance</th><th>Status</th><th>Joined</th></tr></thead><tbody>
    ${d.recent_players.map(p=>`<tr><td>${p.username}</td><td>$${Number(p.balance||0).toFixed(2)}</td><td>${p.status}</td><td>${(p.created_at||'').slice(0,10)}</td></tr>`).join('')}
    </tbody></table>` : '<p style="color:var(--muted)">No players yet</p>';
}

// ── LEDGERS ──
async function renderLedgers() {
  const res = await apiFetch('/transactions?limit=100');
  const list = res.success ? res.data : [];
  document.getElementById('ledgerList').innerHTML = list.length ? `
    <table class="data-table"><thead><tr><th>Date</th><th>Player</th><th>Type</th><th>Amount</th><th>Method</th><th>Status</th></tr></thead><tbody>
    ${list.map(t=>`<tr><td>${(t.created_at||'').slice(0,16)}</td><td>${t.username||''}</td><td>${t.type}</td><td>$${Number(t.amount||0).toFixed(2)}</td><td>${t.method||''}</td><td><span class="txn-badge badge-${t.status}">${t.status}</span></td></tr>`).join('')}
    </tbody></table>` : '<p style="color:var(--muted)">No transactions yet</p>';
}

// ── PLAYER ANALYTICS ──
async function renderPlayerAnalytics() {
  const res = await apiFetch('/stats/players');
  if (!res.success) return;
  const d = res.data;
  document.getElementById('playerAnalyticsStats').innerHTML = `
    <div class="stat-card"><div class="stat-label">Total Players</div><div class="stat-value">${d.total}</div></div>
    <div class="stat-card"><div class="stat-label">Active</div><div class="stat-value">${d.active}</div></div>
    <div class="stat-card"><div class="stat-label">With Balance</div><div class="stat-value">${d.with_balance}</div></div>`;
  document.getElementById('playersByGame').innerHTML = d.by_game.length ? `
    <table class="data-table"><thead><tr><th>Game</th><th>Players</th></tr></thead><tbody>
    ${d.by_game.map(g=>`<tr><td>${GAME_NAMES[g.game]||g.game}</td><td>${g.cnt}</td></tr>`).join('')}
    </tbody></table>` : '<p style="color:var(--muted)">No game accounts yet</p>';
  document.getElementById('topPlayers').innerHTML = d.top_players.length ? `
    <table class="data-table"><thead><tr><th>Player</th><th>Balance</th><th>BW Credits</th><th>Joined</th></tr></thead><tbody>
    ${d.top_players.map(p=>`<tr><td>${p.username}</td><td>$${Number(p.balance||0).toFixed(2)}</td><td>${Number(p.fp_credits||0).toFixed(1)}</td><td>${(p.created_at||'').slice(0,10)}</td></tr>`).join('')}
    </tbody></table>` : '<p style="color:var(--muted)">No players yet</p>';
}

// ── PAYMENT ANALYTICS ──
async function renderPaymentAnalytics() {
  const res = await apiFetch('/stats/payments');
  if (!res.success) return;
  const d = res.data;
  const methodTable = rows => rows.length ? `
    <table class="data-table"><thead><tr><th>Method</th><th>Count</th><th>Total</th></tr></thead><tbody>
    ${rows.map(r=>`<tr><td>${r.method||'—'}</td><td>${r.cnt}</td><td>$${Number(r.total||0).toFixed(2)}</td></tr>`).join('')}
    </tbody></table>` : '<p style="color:var(--muted)">No data yet</p>';
  document.getElementById('depByMethod').innerHTML = methodTable(d.deposits_by_method);
  document.getElementById('wdByMethod').innerHTML  = methodTable(d.withdrawals_by_method);
  const statusBadge = (label, rows) => `
    <div class="section-card" style="min-width:160px;padding:16px">
      <div style="font-size:12px;font-weight:700;color:var(--muted);margin-bottom:8px">${label}</div>
      ${rows.map(r=>`<div style="display:flex;justify-content:space-between;margin-bottom:4px"><span>${r.status}</span><strong>${r.cnt}</strong></div>`).join('')}
    </div>`;
  document.getElementById('paymentStatus').innerHTML =
    statusBadge('Deposits', d.deposit_status) + statusBadge('Withdrawals', d.withdrawal_status);
}

// ── GAME RECORDS ──
async function renderGameRecords() {
  const filter = document.getElementById('gameRecordFilter')?.value || '';
  const res = await apiFetch('/game-records' + (filter ? '?game=' + filter : ''));
  // populate filter dropdown once
  const sel = document.getElementById('gameRecordFilter');
  if (sel && sel.options.length <= 1) {
    Object.keys(GAME_NAMES).forEach(k => {
      const o = document.createElement('option');
      o.value = k; o.textContent = GAME_NAMES[k];
      sel.appendChild(o);
    });
    if (filter) sel.value = filter;
  }
  const list = res.success ? res.data : [];
  document.getElementById('gameRecordsList').innerHTML = list.length ? `
    <table class="data-table"><thead><tr><th>Player</th><th>Game</th><th>Game Username</th><th>Balance</th><th>Created</th></tr></thead><tbody>
    ${list.map(r=>`<tr><td>${r.player||r.player_id}</td><td>${GAME_NAMES[r.game]||r.game}</td><td>${r.game_username}</td><td>$${Number(r.balance||0).toFixed(2)}</td><td>${(r.created_at||'').slice(0,10)}</td></tr>`).join('')}
    </tbody></table>` : '<p style="color:var(--muted)">No game accounts yet</p>';
}

// ── GAME ANALYTICS ──
async function renderGameAnalytics() {
  const res = await apiFetch('/stats/games');
  const list = res.success ? res.data : [];
  document.getElementById('gameAnalyticsList').innerHTML = list.length ? `
    <table class="data-table"><thead><tr><th>Game</th><th>Status</th><th>Players</th><th>Players Balance</th><th>Agent Balance</th></tr></thead><tbody>
    ${list.map(r=>`<tr>
      <td>${r.name||GAME_NAMES[r.game]||r.game}</td>
      <td><span class="bi-status ${r.status}" style="font-size:11px;padding:2px 8px;border-radius:20px">${r.status}</span></td>
      <td>${r.player_count}</td>
      <td>$${Number(r.players_balance||0).toFixed(2)}</td>
      <td>${r.agent_balance!=null?'$'+Number(r.agent_balance).toFixed(2):'—'}</td>
    </tr>`).join('')}
    </tbody></table>` : '<p style="color:var(--muted)">No game data yet</p>';
}

// ── GAMES LIST ──
async function renderGamesList() {
  const res = await apiFetch('/backends');
  const list = res.success ? res.data : [];
  document.getElementById('gamesListGrid').innerHTML = list.length ? `
    <table class="data-table"><thead><tr><th>Game</th><th>Username</th><th>Status</th><th>Enabled</th><th>Actions</th></tr></thead><tbody>
    ${list.map(b=>`<tr>
      <td>${GAME_ICONS[b.game]||'🎮'} ${b.name}</td>
      <td>${b.username}</td>
      <td><span class="bi-status ${b.status}">${b.status}</span></td>
      <td>${b.enabled!==0?'✅':'❌'}</td>
      <td>
        <button class="btn-bi ${b.enabled!==0?'btn-disable':'btn-enable'}" onclick="toggleBackend(${b.id});setTimeout(renderGamesList,500)">${b.enabled!==0?'Disable':'Enable'}</button>
        <button class="btn-bi" onclick="testBackend(${b.id});setTimeout(renderGamesList,1500)">Test</button>
      </td>
    </tr>`).join('')}
    </tbody></table>` : '<p style="color:var(--muted)">No backends attached yet</p>';
}

// ── PAYMENT METHODS ──
function showAddPaymentMethodForm() {
  const form = document.getElementById('addPmForm');
  if (form) form.style.display = form.style.display === 'none' ? 'block' : 'none';
}

async function createPaymentMethod() {
  const val = id => (document.getElementById(id)?.value || '').trim();
  const key  = val('npm_key').toLowerCase().replace(/[^a-z0-9_]/g, '_');
  const name = val('npm_name');
  const msgEl = document.getElementById('npm_msg');
  if (!key || !name) {
    if (msgEl) { msgEl.textContent = 'Key and Name are required.'; msgEl.style.color = '#991b1b'; }
    return;
  }
  const data = {
    name,
    icon:         val('npm_icon') || '💳',
    address:      val('npm_address'),
    payment_link: val('npm_link'),
    qr_image:     '',
    instructions: (document.getElementById('npm_inst')?.value || '').trim(),
    enabled:      1,
  };
  const res = await apiFetch(`/admin/payment-methods/${key}`, 'POST', data);
  if (msgEl) {
    msgEl.textContent = res.success ? '✅ Created!' : ('Error: ' + (res.msg || 'failed'));
    msgEl.style.color = res.success ? '#166534' : '#991b1b';
  }
  if (res.success) {
    ['npm_key','npm_name','npm_icon','npm_address','npm_link','npm_inst'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.value = id === 'npm_icon' ? '💳' : '';
    });
    document.getElementById('addPmForm').style.display = 'none';
    renderPaymentMethods();
  }
}

async function renderPaymentMethods() {
  const el  = document.getElementById('paymentMethodsList');
  if (!el) return;
  el.innerHTML = '<div style="color:#6b7280;padding:16px">Loading…</div>';
  const res  = await apiFetch('/admin/payment-methods');
  const list = res.success ? res.data : [];

  if (!list.length) {
    el.innerHTML = '<p style="color:var(--muted)">No payment methods found — they seed automatically on server start.</p>';
    return;
  }

  el.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:16px">
      ${list.map(m => `
      <div style="background:#fff;border:1.5px solid ${m.enabled?'#bbf7d0':'#e5e7eb'};border-radius:14px;padding:20px">
        <!-- Header row -->
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px">
          <div style="display:flex;align-items:center;gap:10px">
            <span style="font-size:22px">${m.icon||'💳'}</span>
            <span style="font-size:15px;font-weight:700;color:#111">${escAdm(m.name)}</span>
            <span style="font-size:11px;font-weight:700;padding:2px 10px;border-radius:20px;background:${m.enabled?'#dcfce7':'#fee2e2'};color:${m.enabled?'#166534':'#991b1b'}">${m.enabled?'Enabled':'Disabled'}</span>
          </div>
          <button onclick="savePM('${m.key}')" style="background:#852c2c;color:#fff;border:none;border-radius:8px;padding:7px 16px;font-size:13px;font-weight:700;cursor:pointer">Save</button>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px">
          <div>
            <label style="font-size:11px;font-weight:700;color:#6b7280;display:block;margin-bottom:4px">DISPLAY NAME</label>
            <input id="pm_name_${m.key}" value="${escAdm(m.name)}" style="width:100%;box-sizing:border-box;border:1.5px solid #e5e7eb;border-radius:8px;padding:8px 10px;font-size:13px;outline:none">
          </div>
          <div>
            <label style="font-size:11px;font-weight:700;color:#6b7280;display:block;margin-bottom:4px">ICON (emoji)</label>
            <input id="pm_icon_${m.key}" value="${escAdm(m.icon||'')}" style="width:100%;box-sizing:border-box;border:1.5px solid #e5e7eb;border-radius:8px;padding:8px 10px;font-size:13px;outline:none">
          </div>
        </div>
        <div style="margin-bottom:10px">
          <label style="font-size:11px;font-weight:700;color:#6b7280;display:block;margin-bottom:4px">ADDRESS / CASHTAG / WALLET</label>
          <input id="pm_address_${m.key}" value="${escAdm(m.address||'')}" placeholder="e.g. $BigWinGaming or bc1q…" style="width:100%;box-sizing:border-box;border:1.5px solid #e5e7eb;border-radius:8px;padding:8px 10px;font-size:13px;outline:none">
        </div>
        <div style="margin-bottom:10px">
          <label style="font-size:11px;font-weight:700;color:#6b7280;display:block;margin-bottom:4px">PAYMENT LINK (URL player taps to pay)</label>
          <input id="pm_link_${m.key}" value="${escAdm(m.payment_link||'')}" placeholder="e.g. https://cash.app/$YourTag" style="width:100%;box-sizing:border-box;border:1.5px solid #e5e7eb;border-radius:8px;padding:8px 10px;font-size:13px;outline:none">
        </div>
        <div style="margin-bottom:10px">
          <label style="font-size:11px;font-weight:700;color:#6b7280;display:block;margin-bottom:4px">QR CODE IMAGE URL</label>
          <input id="pm_qr_${m.key}" value="${escAdm(m.qr_image||'')}" placeholder="https://… (paste image URL)" style="width:100%;box-sizing:border-box;border:1.5px solid #e5e7eb;border-radius:8px;padding:8px 10px;font-size:13px;outline:none">
          ${m.qr_image ? `<img src="${escAdm(m.qr_image)}" style="margin-top:8px;max-width:120px;max-height:120px;border-radius:8px;border:1px solid #e5e7eb" onerror="this.style.display='none'">` : ''}
        </div>
        <div style="margin-bottom:14px">
          <label style="font-size:11px;font-weight:700;color:#6b7280;display:block;margin-bottom:4px">INSTRUCTIONS (shown to player)</label>
          <textarea id="pm_inst_${m.key}" rows="2" placeholder="e.g. Send to $BigWinGaming and screenshot your receipt" style="width:100%;box-sizing:border-box;border:1.5px solid #e5e7eb;border-radius:8px;padding:8px 10px;font-size:13px;outline:none;resize:vertical">${escAdm(m.instructions||'')}</textarea>
        </div>
        <div style="display:flex;align-items:center;gap:10px">
          <label style="font-size:13px;font-weight:600;color:#374151">Enable this method</label>
          <input type="checkbox" id="pm_enabled_${m.key}" ${m.enabled?'checked':''} style="width:18px;height:18px;cursor:pointer">
        </div>
        <div id="pm_msg_${m.key}" style="display:none;margin-top:10px;font-size:13px;font-weight:600"></div>
      </div>`).join('')}
    </div>`;
}

async function savePM(key) {
  const val = id => (document.getElementById(id)?.value || '').trim();
  const data = {
    name:         val(`pm_name_${key}`),
    icon:         val(`pm_icon_${key}`),
    address:      val(`pm_address_${key}`),
    payment_link: val(`pm_link_${key}`),
    qr_image:     val(`pm_qr_${key}`),
    instructions: (document.getElementById(`pm_inst_${key}`)?.value || '').trim(),
    enabled:      document.getElementById(`pm_enabled_${key}`)?.checked ? 1 : 0,
  };
  const msgEl = document.getElementById(`pm_msg_${key}`);
  const res = await apiFetch(`/admin/payment-methods/${key}`, 'POST', data);
  if (msgEl) {
    msgEl.textContent  = res.success ? '✅ Saved!' : ('Error: ' + (res.msg || 'failed'));
    msgEl.style.color  = res.success ? '#166534' : '#991b1b';
    msgEl.style.display = 'block';
    setTimeout(() => { msgEl.style.display = 'none'; }, 3000);
  }
  if (res.success) renderPaymentMethods();
}

// ── SUPPORT AGENTS MANAGEMENT ──
async function renderSupportAgents() {
  const el  = document.getElementById('agentsList');
  if (!el) return;
  el.innerHTML = '<div style="color:#6b7280;padding:8px">Loading…</div>';
  const res  = await apiFetch('/admin/support-agents');
  const list = res.success ? res.data : [];
  if (!list.length) {
    el.innerHTML = '<div class="section-card" style="color:#6b7280;font-size:13px">No agents yet. Click + Add Agent to create one.</div>';
    return;
  }
  el.innerHTML = list.map(a => {
    const isProtected = a.name === "BigWin Support";
    return `
    <div class="section-card" style="margin-bottom:12px" id="agentCard-${a.id}">
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px">
        <div style="width:44px;height:44px;border-radius:50%;background:${escAdm(a.color||'#852c2c')};display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0">${escAdm(a.icon||'🎧')}</div>
        <div style="flex:1">
          <div style="display:flex;align-items:center;gap:6px">
            <span style="font-size:15px;font-weight:700;color:var(--text)">${escAdm(a.name)}</span>
            ${isProtected ? '<span style="font-size:10px;font-weight:700;padding:2px 7px;border-radius:99px;background:#1e3a5f;color:#60a5fa">DEFAULT</span>' : ''}
          </div>
          <span style="font-size:11px;font-weight:700;padding:2px 10px;border-radius:99px;background:${a.active?'#dcfce7':'#fee2e2'};color:${a.active?'#166534':'#991b1b'}">${a.active?'Active':'Inactive'}</span>
        </div>
        ${isProtected
          ? '<span style="font-size:11px;color:#6b7280;padding:5px 12px">🔒 Protected</span>'
          : `<button onclick="deleteAgent(${a.id},'${escAdm(a.name)}')" style="background:#fee2e2;border:1px solid #fecaca;color:#991b1b;border-radius:7px;padding:5px 12px;font-size:12px;font-weight:700;cursor:pointer">Delete</button>`
        }
      </div>
      <div style="display:grid;grid-template-columns:1fr 70px 110px;gap:8px;margin-bottom:8px">
        <div>
          <label style="font-size:11px;color:var(--muted);display:block;margin-bottom:3px">NAME</label>
          <input id="ae-name-${a.id}" value="${escAdm(a.name)}" ${isProtected?'readonly style="width:100%;box-sizing:border-box;border:1.5px solid var(--border);border-radius:7px;padding:7px 10px;font-size:13px;background:#1e293b;color:#64748b;outline:none;cursor:not-allowed"':'style="width:100%;box-sizing:border-box;border:1.5px solid var(--border);border-radius:7px;padding:7px 10px;font-size:13px;background:var(--bg);color:var(--text);outline:none"'}>
        </div>
        <div>
          <label style="font-size:11px;color:var(--muted);display:block;margin-bottom:3px">ICON</label>
          <input id="ae-icon-${a.id}" value="${escAdm(a.icon||'🎧')}" style="width:100%;box-sizing:border-box;border:1.5px solid var(--border);border-radius:7px;padding:7px 6px;font-size:16px;background:var(--bg);color:var(--text);outline:none;text-align:center">
        </div>
        <div>
          <label style="font-size:11px;color:var(--muted);display:block;margin-bottom:3px">COLOR</label>
          <input id="ae-color-${a.id}" type="color" value="${escAdm(a.color||'#852c2c')}" style="width:100%;height:34px;border:1.5px solid var(--border);border-radius:7px;cursor:pointer;background:var(--bg)">
        </div>
      </div>
      <div style="margin-bottom:10px">
        <label style="font-size:11px;color:var(--muted);display:block;margin-bottom:3px">NEW PASSWORD (leave blank to keep current)</label>
        <input id="ae-pw-${a.id}" type="text" placeholder="••••••••" style="width:100%;box-sizing:border-box;border:1.5px solid var(--border);border-radius:7px;padding:7px 10px;font-size:13px;background:var(--bg);color:var(--text);outline:none">
      </div>
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
        <label style="font-size:13px;font-weight:600;color:var(--text)">Active</label>
        <input type="checkbox" id="ae-active-${a.id}" ${a.active?'checked':''} ${isProtected?'disabled':''} style="width:18px;height:18px;cursor:${isProtected?'not-allowed':'pointer'}">
        ${isProtected ? '<span style="font-size:11px;color:#64748b">Always active</span>' : ''}
      </div>
      <div style="display:flex;align-items:center;gap:10px">
        <button onclick="saveAgent(${a.id})" style="background:#852c2c;color:#fff;border:none;border-radius:7px;padding:8px 20px;font-size:13px;font-weight:700;cursor:pointer">Save Changes</button>
        <span id="ae-msg-${a.id}" style="font-size:13px;font-weight:600"></span>
      </div>
    </div>`;
  }).join('');
}

function showCreateAgentForm() {
  document.getElementById('agentCreateForm').style.display = 'block';
  document.getElementById('na-name').focus();
}

async function submitCreateAgent() {
  const name     = (document.getElementById('na-name').value || '').trim();
  const icon     = (document.getElementById('na-icon').value || '🎧').trim();
  const color    = document.getElementById('na-color').value || '#852c2c';
  const password = (document.getElementById('na-password').value || '').trim();
  const errEl    = document.getElementById('na-err');
  errEl.style.display = 'none';
  if (!name) { errEl.textContent = 'Name is required'; errEl.style.display = 'block'; return; }
  if (!password || password.length < 4) { errEl.textContent = 'Password must be at least 4 characters'; errEl.style.display = 'block'; return; }
  const res = await apiFetch('/admin/support-agents', 'POST', { name, icon, color, password });
  if (res.success) {
    document.getElementById('agentCreateForm').style.display = 'none';
    document.getElementById('na-name').value = '';
    document.getElementById('na-password').value = '';
    renderSupportAgents();
    alert(`✅ Agent "${name}" created!\n\nShare this login with them:\nURL: /support-portal.html\nName: ${name}\nPassword: ${password}`);
  } else {
    errEl.textContent = res.msg || 'Failed to create agent';
    errEl.style.display = 'block';
  }
}

async function saveAgent(id) {
  const name     = (document.getElementById(`ae-name-${id}`)?.value || '').trim();
  const icon     = (document.getElementById(`ae-icon-${id}`)?.value || '').trim();
  const color    = document.getElementById(`ae-color-${id}`)?.value || '#852c2c';
  const password = (document.getElementById(`ae-pw-${id}`)?.value || '').trim();
  const active   = document.getElementById(`ae-active-${id}`)?.checked;
  const msgEl    = document.getElementById(`ae-msg-${id}`);
  const res = await apiFetch(`/admin/support-agents/${id}`, 'POST', { name, icon, color, password: password||undefined, active });
  if (msgEl) {
    msgEl.textContent = res.success ? '✅ Saved!' : ('❌ ' + (res.msg || 'Failed'));
    msgEl.style.color = res.success ? '#16a34a' : '#ef4444';
    if (res.success) { setTimeout(() => { msgEl.textContent=''; }, 3000); renderSupportAgents(); }
  }
}

async function deleteAgent(id, name) {
  if (!confirm(`Delete agent "${name}"?\n\nThis will not delete their chat history.`)) return;
  const res = await apiFetch(`/admin/support-agents/${id}`, 'DELETE', {});
  if (res.success) renderSupportAgents();
  else alert('Error: ' + (res.msg || 'Could not delete'));
}

// ── KEYHUB API CONFIG ──
async function renderKeyhubConfig() {
  const res = await apiFetch('/admin/keyhub-config');
  const el  = document.getElementById('keyhubStatus');
  const pre = document.getElementById('keyhubKeyPreview');
  const dis = document.getElementById('keyhubDisconnectBtn');
  if (!el) return;
  const connected = res.success && res.data.configured;
  if (connected) {
    el.textContent = 'Connected';
    el.style.background = '#dcfce7'; el.style.color = '#166534';
    pre.textContent = res.data.key_preview || '';
  } else {
    el.textContent = 'Not connected';
    el.style.background = '#fee2e2'; el.style.color = '#991b1b';
    pre.textContent = '';
  }
  if (dis) dis.style.display = connected ? '' : 'none';
}

async function disconnectKeyhub() {
  if (!confirm('Disconnect KeyHub? Automated payouts will stop working until you reconnect.')) return;
  const msg = document.getElementById('keyhubMsg');
  msg.style.color = 'var(--muted)'; msg.textContent = 'Disconnecting…';
  const res = await apiFetch('/admin/keyhub-disconnect', 'POST', {});
  if (res.success) {
    msg.style.color = '#16a34a'; msg.textContent = '✅ KeyHub disconnected';
    renderKeyhubConfig();
  } else {
    msg.style.color = '#ef4444'; msg.textContent = res.msg || 'Failed to disconnect';
  }
}

async function saveKeyhubKey() {
  const key = (document.getElementById('keyhubApiKey').value || '').trim();
  const msg = document.getElementById('keyhubMsg');
  if (!key) { msg.style.color = '#ef4444'; msg.textContent = 'Paste your KeyHub API key first'; return; }
  msg.style.color = 'var(--muted)'; msg.textContent = 'Saving…';
  const res = await apiFetch('/admin/keyhub-config', 'POST', { api_key: key });
  if (res.success) {
    msg.style.color = '#16a34a'; msg.textContent = '✅ API key saved and connected';
    document.getElementById('keyhubApiKey').value = '';
    renderKeyhubConfig();
  } else {
    msg.style.color = '#ef4444'; msg.textContent = res.msg || 'Save failed';
  }
}

async function testKeyhubConnection() {
  const msg = document.getElementById('keyhubMsg');
  msg.style.color = 'var(--muted)'; msg.textContent = 'Testing connection…';
  const res = await apiFetch('/admin/keyhub-test');
  if (res.success) {
    msg.style.color = '#16a34a'; msg.textContent = '✅ KeyHub connection OK — gateway is reachable';
  } else {
    msg.style.color = '#ef4444'; msg.textContent = '❌ ' + (res.msg || 'Connection failed — check your API key');
  }
}

// ── SMS / OTP CONFIG ──
let _smsTab = 'verify';

function switchSmsTab(tab) {
  _smsTab = tab;
  document.getElementById('smsPanelTwilio').style.display = tab === 'twilio' ? '' : 'none';
  document.getElementById('smsPanelTelnyx').style.display = tab === 'telnyx' ? '' : 'none';
  document.getElementById('smsPanelVerify').style.display = tab === 'verify' ? '' : 'none';
  const vBtn = document.getElementById('smsTabVerify');
  if (vBtn) { vBtn.style.background = tab==='verify'?'#16a34a':'none'; vBtn.style.color = tab==='verify'?'#fff':'var(--muted)'; vBtn.style.borderColor = tab==='verify'?'#16a34a':'var(--border)'; }
  const tBtn = document.getElementById('smsTabTwilio');
  const xBtn = document.getElementById('smsTabTelnyx');
  if (tBtn) { tBtn.style.background = tab==='twilio'?'#e2343e':'none'; tBtn.style.color = tab==='twilio'?'#fff':'var(--muted)'; tBtn.style.borderColor = tab==='twilio'?'#e2343e':'var(--border)'; }
  if (xBtn) { xBtn.style.background = tab==='telnyx'?'#852c2c':'none'; xBtn.style.color = tab==='telnyx'?'#fff':'var(--muted)'; xBtn.style.borderColor = tab==='telnyx'?'#852c2c':'var(--border)'; }
}

async function renderSmsConfig() {
  if (document.getElementById('smsPanelVerify')) switchSmsTab(_smsTab);
  const res = await apiFetch('/admin/sms-config');
  const el  = document.getElementById('smsStatus');
  const pv  = document.getElementById('smsProvider');
  const dis = document.getElementById('smsDisconnectBtn');
  if (!el) return;
  if (res.success && res.data.configured) {
    el.textContent = 'Active';
    el.style.background = '#dcfce7'; el.style.color = '#166534';
    pv.textContent = res.data.provider + ' · ' + (res.data.from_preview || '');
    if (dis) dis.style.display = '';
  } else {
    el.textContent = 'Not configured';
    el.style.background = '#fee2e2'; el.style.color = '#991b1b';
    pv.textContent = 'Demo mode — OTP shown on screen only';
    if (dis) dis.style.display = 'none';
  }
}

async function saveSmsConfig() {
  const msg = document.getElementById('smsMsg');
  let payload = {};
  if (_smsTab === 'verify') {
    const sid   = (document.getElementById('smsVerifySid').value     || '').trim();
    const token = (document.getElementById('smsVerifyToken').value   || '').trim();
    const svc   = (document.getElementById('smsVerifyService').value || '').trim();
    if (!sid.startsWith('AC')) { msg.style.color='#ef4444'; msg.textContent='Enter the Account SID (starts with AC)'; return; }
    if (!token)                { msg.style.color='#ef4444'; msg.textContent='Enter the Auth Token'; return; }
    if (!svc.startsWith('VA')) { msg.style.color='#ef4444'; msg.textContent='Enter the Verify Service SID (starts with VA)'; return; }
    payload = { provider: 'twilio_verify', twilio_sid: sid, twilio_token: token, verify_sid: svc };
  } else if (_smsTab === 'twilio') {
    const sid   = (document.getElementById('smsTwilioSid').value   || '').trim();
    const token = (document.getElementById('smsTwilioToken').value  || '').trim();
    const from  = (document.getElementById('smsTwilioFrom').value   || '').trim();
    if (!sid)   { msg.style.color='#ef4444'; msg.textContent='Enter Account SID'; return; }
    if (!token) { msg.style.color='#ef4444'; msg.textContent='Enter Auth Token'; return; }
    if (!from)  { msg.style.color='#ef4444'; msg.textContent='Enter From number'; return; }
    payload = { provider: 'twilio', twilio_sid: sid, twilio_token: token, twilio_from: from };
  } else {
    const key  = (document.getElementById('smsTelnyxKey').value  || '').trim();
    const from = (document.getElementById('smsTelnyxFrom').value || '').trim();
    if (!key)  { msg.style.color='#ef4444'; msg.textContent='Enter Telnyx API key'; return; }
    if (!from) { msg.style.color='#ef4444'; msg.textContent='Enter From number'; return; }
    payload = { provider: 'telnyx', telnyx_api_key: key, telnyx_from: from };
  }
  msg.style.color = 'var(--muted)'; msg.textContent = 'Saving…';
  const res = await apiFetch('/admin/sms-config', 'POST', payload);
  if (res.success) {
    msg.style.color = '#16a34a'; msg.textContent = '✅ SMS activated — real OTPs will now be sent';
    ['smsTwilioSid','smsTwilioToken','smsTwilioFrom','smsTelnyxKey','smsTelnyxFrom','smsVerifySid','smsVerifyToken','smsVerifyService'].forEach(id => {
      const el = document.getElementById(id); if (el) el.value = '';
    });
    renderSmsConfig();
  } else {
    msg.style.color = '#ef4444'; msg.textContent = res.msg || 'Save failed';
  }
}

async function disconnectSms() {
  if (!confirm('Remove SMS config? Phone OTP will revert to demo mode.')) return;
  const msg = document.getElementById('smsMsg');
  msg.style.color = 'var(--muted)'; msg.textContent = 'Removing…';
  const res = await apiFetch('/admin/sms-disconnect', 'POST', {});
  if (res.success) {
    msg.style.color = '#16a34a'; msg.textContent = '✅ SMS config removed';
    renderSmsConfig();
  } else {
    msg.style.color = '#ef4444'; msg.textContent = res.msg || 'Failed';
  }
}

// ── TELEGRAM NOTIFICATIONS ──
function _tgMsg(text, color) {
  const m = document.getElementById('tgMsg');
  m.style.color = color || 'var(--muted)'; m.textContent = text;
}

async function renderTelegramConfig() {
  const res = await apiFetch('/admin/telegram-config');
  const st  = document.getElementById('tgStatus');
  if (!st || !res.success) return;
  const d = res.data;
  st.textContent = d.configured ? 'Active' : 'Not configured';
  st.style.background = d.configured ? '#dcfce7' : '#fee2e2';
  st.style.color      = d.configured ? '#166534' : '#991b1b';
  document.getElementById('tgInfo').textContent = d.configured ? `Bot ${d.token_preview} → ${d.chat_id}` : '';
  document.getElementById('tgChat').value = d.chat_id || '';
  document.getElementById('tgTestBtn').style.display = d.configured ? '' : 'none';
  document.getElementById('tgOffBtn').style.display  = d.configured ? '' : 'none';
  const on = new Set(d.events);
  document.getElementById('tgEvents').innerHTML = d.categories.map(c => `
    <label style="display:flex;align-items:center;gap:10px;font-size:13px;color:var(--text);cursor:pointer">
      <input type="checkbox" class="tg-ev" value="${c.key}" ${on.has(c.key) ? 'checked' : ''} style="width:16px;height:16px">
      ${c.label}
    </label>`).join('');
}

async function saveTelegramConfig() {
  const bot_token = document.getElementById('tgToken').value.trim();
  const chat_id   = document.getElementById('tgChat').value.trim();
  const events    = [...document.querySelectorAll('.tg-ev:checked')].map(x => x.value);
  if (!chat_id) return _tgMsg('Enter a chat ID', '#ef4444');
  _tgMsg('Saving and sending a test message…');
  const res = await apiFetch('/admin/telegram-config', 'POST', { bot_token, chat_id, events });
  if (res.success) { document.getElementById('tgToken').value = ''; _tgMsg('✅ ' + res.msg, '#16a34a'); }
  else _tgMsg(res.msg || 'Save failed', '#ef4444');
  renderTelegramConfig();
}

async function testTelegram() {
  _tgMsg('Sending…');
  const res = await apiFetch('/admin/telegram-test', 'POST', {});
  _tgMsg(res.success ? '✅ ' + res.msg : (res.msg || 'Failed'), res.success ? '#16a34a' : '#ef4444');
}

async function disconnectTelegram() {
  if (!confirm('Turn off Telegram notifications?')) return;
  const res = await apiFetch('/admin/telegram-disconnect', 'POST', {});
  _tgMsg(res.success ? '✅ ' + res.msg : (res.msg || 'Failed'), res.success ? '#16a34a' : '#ef4444');
  renderTelegramConfig();
}

// ── LOAD REQUESTS (player paid → load the game by hand → tap Loaded) ──
let lrFilter = 'pending';
const lrEsc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const lrImg = s => /^data:image\/(png|jpe?g|webp|gif);base64,[A-Za-z0-9+/=]+$/.test(s || '');

function setLrFilter(f) { lrFilter = f; renderLoadRequests(); }

function lrBadge(n) {
  const b = document.getElementById('lrNavBadge');
  if (!b) return;
  b.textContent = n; b.style.display = n ? '' : 'none';
}

async function renderLoadRequests() {
  document.querySelectorAll('.lr-tab').forEach(t => t.classList.toggle('active', t.dataset.lr === lrFilter));
  const box = document.getElementById('lrList');
  if (!box) return;
  const res = await apiFetch('/staff/load-requests?status=' + lrFilter);
  if (!res.success) { box.innerHTML = `<p style="color:#ef4444">${lrEsc(res.msg || 'Could not load')}</p>`; return; }
  lrBadge(res.data.pending);
  const list = res.data.requests;
  if (!list.length) {
    box.innerHTML = `<p style="color:var(--muted);padding:24px 0;text-align:center">${lrFilter === 'pending' ? '🎉 No loads waiting.' : 'No load requests yet.'}</p>`;
    return;
  }
  box.innerHTML = list.map(r => {
    const when = new Date(String(r.created_at).replace(' ', 'T') + (/[zZ+]/.test(r.created_at) ? '' : 'Z'));
    const done = r.status !== 'pending';
    const chip = r.status === 'loaded' ? ['#dcfce7', '#166534', 'Loaded']
               : r.status === 'rejected' ? ['#fee2e2', '#991b1b', 'Rejected'] : ['#fef3c7', '#92400e', 'Waiting'];
    return `<div class="lr-card">
      <div class="lr-main">
        <div class="lr-amt">$${Number(r.amount).toFixed(2)}</div>
        <div>
          <div class="lr-line"><strong>${lrEsc(r.game_name)}</strong> ${r.game_username ? `· Game ID <code>${lrEsc(r.game_username)}</code> <button class="lr-copy" data-copy="${lrEsc(r.game_username)}" onclick="navigator.clipboard.writeText(this.dataset.copy)">copy</button>` : '<span style="color:#b45309">· no Game ID yet</span>'}</div>
          <div class="lr-sub">#${r.id} · ${lrEsc(r.username)} · ${lrEsc(r.method_name)} · ${isNaN(when) ? '' : when.toLocaleString()}</div>
          ${done ? `<div class="lr-sub">${chip[2]} by ${lrEsc(r.handled_by)}${r.note ? ' — ' + lrEsc(r.note) : ''}</div>` : ''}
        </div>
      </div>
      <div class="lr-side">
        ${lrImg(r.screenshot) ? `<a href="#" onclick="lrShowShot(${r.id});return false"><img class="lr-shot" src="${r.screenshot}" alt="Receipt"></a>` : ''}
        ${done ? `<span class="lr-chip" style="background:${chip[0]};color:${chip[1]}">${chip[2]}</span>`
               : `<button class="lr-btn lr-btn--ok" onclick="finishLoad(${r.id},'loaded',this)">✅ Loaded</button>
                  <button class="lr-btn lr-btn--no" onclick="finishLoad(${r.id},'reject',this)">Reject</button>`}
      </div>
    </div>`;
  }).join('');
  window._lrCache = Object.fromEntries(list.map(r => [r.id, r]));
}

function lrShowShot(id) {
  const r = (window._lrCache || {})[id];
  if (!r || !lrImg(r.screenshot)) return;
  const w = window.open('', '_blank');
  if (w) { w.document.title = 'Receipt #' + id; const img = w.document.createElement('img'); img.src = r.screenshot; img.style.maxWidth = '100%'; w.document.body.appendChild(img); }
}

async function finishLoad(id, action, btn) {
  let note = '';
  if (action === 'reject') {
    note = prompt('Reason (the player will see this):', "We couldn't find your payment.");
    if (note === null) return;
  }
  btn.disabled = true;
  const res = await apiFetch(`/staff/load-requests/${id}/${action}`, 'POST', { note });
  if (!res.success) alert(res.msg || 'Failed');
  renderLoadRequests();
}

// Keep the badge (and the open page) fresh
setInterval(() => {
  if (!getAdminToken()) return;
  const page = document.getElementById('page-load-requests');
  if (page && page.classList.contains('active')) renderLoadRequests();
  else apiFetch('/staff/load-requests?status=pending').then(r => r.success && lrBadge(r.data.pending));
}, 10000);
setTimeout(() => getAdminToken() && apiFetch('/staff/load-requests?status=pending').then(r => r.success && lrBadge(r.data.pending)), 1500);

// ── CONTACT LINKS (Facebook / Telegram buttons on the website) ──
function _socialPreview(d) {
  const parts = [];
  if (d.facebook) parts.push('m.me/' + d.facebook);
  if (d.telegram) parts.push('t.me/' + d.telegram);
  const el = document.getElementById('socialPreview');
  if (el) el.textContent = parts.length ? 'Live: ' + parts.join(' · ') : 'No buttons showing';
}

async function renderSocialLinks() {
  const res = await apiFetch('/admin/social-links');
  if (!res.success || !document.getElementById('socialFb')) return;
  document.getElementById('socialFb').value = res.data.facebook || '';
  document.getElementById('socialTg').value = res.data.telegram ? '@' + res.data.telegram : '';
  _socialPreview(res.data);
}

async function saveSocialLinks() {
  const m = document.getElementById('socialMsg');
  m.style.color = 'var(--muted)'; m.textContent = 'Saving…';
  const res = await apiFetch('/admin/social-links', 'POST', {
    facebook: document.getElementById('socialFb').value.trim(),
    telegram: document.getElementById('socialTg').value.trim(),
  });
  m.style.color = res.success ? '#16a34a' : '#ef4444';
  m.textContent = res.success ? '✅ ' + res.msg : (res.msg || 'Save failed');
  if (res.success) renderSocialLinks();
}

// ── EMAIL (GMAIL) ──
function _emMsg(text, color) {
  const m = document.getElementById('emMsg');
  m.style.color = color || 'var(--muted)'; m.textContent = text;
}

function pickEmailProvider() {
  const v = document.getElementById('emProvider').value;
  const host = document.getElementById('emHost'), port = document.getElementById('emPort');
  const custom = v === 'custom';
  host.readOnly = port.readOnly = !custom;
  if (!custom) { const [h, p] = v.split('|'); host.value = h; port.value = p; }
  else if (!host.value || host.value === 'smtp.gmail.com') { host.value = ''; port.value = 465; host.focus(); }
  document.getElementById('emPwLabel').textContent =
    v.startsWith('api.resend.com') ? 'Resend API key (re_…)' : v.startsWith('api.brevo.com') ? 'Brevo API key (xkeysib-…)' : v.startsWith('smtp.gmail.com') ? 'App Password' : 'Mailbox password';
}

async function renderEmailConfig() {
  const res = await apiFetch('/admin/email-config');
  const st  = document.getElementById('emStatus');
  if (!st || !res.success) return;
  const d = res.data;
  st.textContent = d.configured ? 'Active' : 'Not configured';
  st.style.background = d.configured ? '#dcfce7' : '#fee2e2';
  st.style.color      = d.configured ? '#166534' : '#991b1b';
  document.getElementById('emInfo').textContent = d.configured ? `${d.name} <${d.address}>` : 'Password reset by email is off';
  document.getElementById('emAddress').value = d.address || '';
  document.getElementById('emName').value    = d.configured ? d.name : '';
  document.getElementById('emOffBtn').style.display = d.configured ? '' : 'none';
  const sel = document.getElementById('emProvider');
  const match = [...sel.options].find(o => o.value === `${d.host}|${d.port}`);
  sel.value = match ? match.value : 'custom';
  pickEmailProvider();
  document.getElementById('emHost').value = d.host;
  document.getElementById('emPort').value = d.port;
}

async function saveEmailConfig() {
  const address      = document.getElementById('emAddress').value.trim();
  const app_password = document.getElementById('emPassword').value.trim();
  const name         = document.getElementById('emName').value.trim();
  const host         = document.getElementById('emHost').value.trim();
  const port         = parseInt(document.getElementById('emPort').value, 10);
  if (!address) return _emMsg('Enter the email address', '#ef4444');
  if (!host)    return _emMsg('Enter the mail server', '#ef4444');
  _emMsg(`Logging in to ${host} and sending a test email…`);
  const test_to      = document.getElementById('emTestTo').value.trim();
  const res = await apiFetch('/admin/email-config', 'POST', { address, app_password, name, host, port, test_to });
  if (res.success) { document.getElementById('emPassword').value = ''; _emMsg('✅ ' + res.msg, '#16a34a'); }
  else _emMsg(res.msg || 'Save failed', '#ef4444');
  renderEmailConfig();
}

async function disconnectEmail() {
  if (!confirm('Turn off email? Players will not be able to reset their password by email.')) return;
  const res = await apiFetch('/admin/email-disconnect', 'POST', {});
  _emMsg(res.success ? '✅ ' + res.msg : (res.msg || 'Failed'), res.success ? '#16a34a' : '#ef4444');
  renderEmailConfig();
}

// ── CASHOUT RULES ──
async function renderCashoutRules() {
  const res   = await apiFetch('/cashout-rules');
  const rules = res.success ? res.data : { min_cashout: 10, max_cashout: 500, daily_limit: 1000, wagering_multiplier: 1 };
  document.getElementById('cr-min').value   = rules.min_cashout;
  document.getElementById('cr-max').value   = rules.max_cashout;
  document.getElementById('cr-daily').value = rules.daily_limit;
  document.getElementById('cr-wager').value = rules.wagering_multiplier;
  updateCashoutSummary(rules);
}

function updateCashoutSummary(rules) {
  const el = document.getElementById('cashoutRulesSummary');
  if (!el) return;
  el.innerHTML =
    `💵 Min cashout: <strong style="color:#f0c040">$${rules.min_cashout}</strong><br>` +
    `💰 Max cashout: <strong style="color:#f0c040">$${rules.max_cashout}</strong><br>` +
    `📅 Daily limit: <strong style="color:#22c55e">$${rules.daily_limit}</strong> per player<br>` +
    `🎯 Wagering requirement: <strong style="color:#ceb05d">${rules.wagering_multiplier}×</strong> ` +
    (rules.wagering_multiplier <= 1 ? '<span style="color:#4b5563">(no requirement)</span>' : 'their balance');
}

async function saveCashoutRules() {
  const min   = parseFloat(document.getElementById('cr-min').value);
  const max   = parseFloat(document.getElementById('cr-max').value);
  const daily = parseFloat(document.getElementById('cr-daily').value);
  const wager = parseFloat(document.getElementById('cr-wager').value);
  const msg   = document.getElementById('cashoutRulesMsg');

  if (isNaN(min) || isNaN(max) || isNaN(daily) || isNaN(wager)) {
    msg.textContent = '⚠️ Please fill in all fields.';
    msg.style.color = '#ef4444'; msg.style.display = 'block'; return;
  }
  if (min < 0 || max <= 0 || daily <= 0 || wager < 1) {
    msg.textContent = '⚠️ Min must be ≥ 0, Max/Daily must be > 0, Wagering must be ≥ 1.';
    msg.style.color = '#ef4444'; msg.style.display = 'block'; return;
  }
  if (min > max) {
    msg.textContent = '⚠️ Minimum cashout cannot be greater than maximum.';
    msg.style.color = '#ef4444'; msg.style.display = 'block'; return;
  }

  const res = await apiFetch('/cashout-rules', 'POST', { min_cashout: min, max_cashout: max, daily_limit: daily, wagering_multiplier: wager });
  if (res.success) {
    msg.textContent = '✅ Cashout rules saved successfully.';
    msg.style.color = '#22c55e'; msg.style.display = 'block';
    updateCashoutSummary(res.data);
    setTimeout(() => { msg.style.display = 'none'; }, 3000);
  } else {
    msg.textContent = '❌ Failed to save. Try again.';
    msg.style.color = '#ef4444'; msg.style.display = 'block';
  }
}

// ── REFERRALS ADMIN ──
async function loadReferrals() {
  const res  = await apiFetch('/referral/list');
  const list = res.success ? res.data : [];

  const statsEl = document.getElementById('referralStats');
  const listEl  = document.getElementById('referralList');
  if (!statsEl || !listEl) return;

  const totalFP = list.reduce((s, r) => s + (r.fp_referrer || 10), 0);
  statsEl.innerHTML = `
    <div style="background:#0f172a;border:1px solid #1e293b;border-radius:12px;padding:16px;text-align:center">
      <div style="font-size:11px;color:#6b7280;letter-spacing:1px;margin-bottom:8px">TOTAL REFERRALS</div>
      <div style="font-size:28px;font-weight:900;color:#14b8a6">${list.length}</div>
    </div>
    <div style="background:#0f172a;border:1px solid #1e293b;border-radius:12px;padding:16px;text-align:center">
      <div style="font-size:11px;color:#6b7280;letter-spacing:1px;margin-bottom:8px">BW AWARDED</div>
      <div style="font-size:28px;font-weight:900;color:#f0c040">${totalFP} BW</div>
    </div>
    <div style="background:#0f172a;border:1px solid #1e293b;border-radius:12px;padding:16px;text-align:center">
      <div style="font-size:11px;color:#6b7280;letter-spacing:1px;margin-bottom:8px">THIS MONTH</div>
      <div style="font-size:28px;font-weight:900;color:#ceb05d">${
        list.filter(r => (r.created_at||'').slice(0,7) === new Date().toISOString().slice(0,7)).length
      }</div>
    </div>`;

  if (!list.length) {
    listEl.innerHTML = '<p style="color:#6b7280;font-size:13px">No referrals yet. Share your referral link to start earning!</p>';
    return;
  }
  listEl.innerHTML = `<table class="data-table">
    <thead><tr><th>Referrer</th><th>New Player</th><th>Referrer BW</th><th>Referred BW</th><th>Date</th></tr></thead>
    <tbody>
    ${list.map(r => `<tr>
      <td><strong>${escAdm(r.referrer_username)}</strong></td>
      <td>${escAdm(r.referred_username)}</td>
      <td style="color:#f0c040">+${r.fp_referrer} BW</td>
      <td style="color:#22c55e">+${r.fp_referred} BW</td>
      <td style="color:#6b7280;font-size:12px">${(r.created_at||'').slice(0,16)}</td>
    </tr>`).join('')}
    </tbody></table>`;
}

// ── MARKETPLACE ADMIN ──
let _marketplaceTiers = [];

async function loadMarketplaceTiers() {
  const res = await apiFetch('/marketplace/tiers');
  _marketplaceTiers = res.success ? res.data : [];
  renderMarketplaceTierEditor();
}

function renderMarketplaceTierEditor() {
  const el = document.getElementById('marketplaceTierEditor');
  if (!el) return;
  if (!_marketplaceTiers.length) {
    el.innerHTML = '<p style="color:#6b7280;font-size:13px">No tiers. Click "+ Add" to create one.</p>';
    return;
  }
  el.innerHTML = `<table class="data-table" style="font-size:12px">
    <thead><tr><th>Tier Label</th><th>Name</th><th>BW Cost</th><th>Cash</th><th>Badge</th><th></th></tr></thead>
    <tbody>
    ${_marketplaceTiers.map((t,i) => `<tr>
      <td><input type="text" value="${escAdm(t.tier_label)}" onchange="_marketplaceTiers[${i}].tier_label=this.value"
        style="background:#0f172a;border:1px solid #334155;border-radius:6px;padding:4px 7px;color:#e2e8f0;width:110px;font-size:12px"></td>
      <td><input type="text" value="${escAdm(t.name)}" onchange="_marketplaceTiers[${i}].name=this.value"
        style="background:#0f172a;border:1px solid #334155;border-radius:6px;padding:4px 7px;color:#e2e8f0;width:90px;font-size:12px"></td>
      <td><input type="number" value="${t.fp_cost}" min="1" onchange="_marketplaceTiers[${i}].fp_cost=parseInt(this.value)||1"
        style="background:#0f172a;border:1px solid #334155;border-radius:6px;padding:4px 7px;color:#e2e8f0;width:70px;font-size:12px"></td>
      <td><input type="text" value="${escAdm(t.cash_value)}" onchange="_marketplaceTiers[${i}].cash_value=this.value"
        style="background:#0f172a;border:1px solid #334155;border-radius:6px;padding:4px 7px;color:#e2e8f0;width:65px;font-size:12px" placeholder="$20"></td>
      <td><select onchange="_marketplaceTiers[${i}].badge=this.value"
        style="background:#0f172a;border:1px solid #334155;border-radius:6px;padding:4px;color:#e2e8f0;font-size:12px">
        <option value="" ${t.badge===''?'selected':''}>None</option>
        <option value="whale" ${t.badge==='whale'?'selected':''}>🐋 Whale</option>
      </select></td>
      <td><button onclick="_marketplaceTiers.splice(${i},1);renderMarketplaceTierEditor()"
        style="background:transparent;border:1px solid #ef4444;color:#ef4444;border-radius:6px;padding:3px 7px;cursor:pointer;font-size:12px">✕</button></td>
    </tr>`).join('')}
    </tbody></table>`;
}

function marketplaceAddTier() {
  _marketplaceTiers.push({ tier_label: 'STARTER · TIER', name: 'New Tier', fp_cost: 100, cash_value: '$20', badge: '', enabled: 1 });
  renderMarketplaceTierEditor();
}

async function marketplaceSaveTiers() {
  const res = await apiFetch('/marketplace/tiers', 'POST', _marketplaceTiers);
  alert(res.success ? '✅ Tiers saved!' : ('Error: ' + res.msg));
  if (res.success) loadMarketplaceTiers();
}

async function loadMarketplaceRedemptions() {
  const res = await apiFetch('/marketplace/redemptions');
  const el  = document.getElementById('marketplaceRedemptions');
  if (!el) return;
  const list = res.success ? res.data : [];
  if (!list.length) {
    el.innerHTML = '<p style="color:#6b7280;font-size:13px">No redemptions yet.</p>';
    return;
  }
  el.innerHTML = `<table class="data-table" style="font-size:12px">
    <thead><tr><th>Player</th><th>Tier</th><th>BW</th><th>Cash</th><th>Status</th><th>Actions</th></tr></thead>
    <tbody>
    ${list.map(r => `<tr>
      <td>${escAdm(r.username)}</td>
      <td>${escAdm(r.tier_name)}</td>
      <td style="color:#f59e0b">${r.fp_spent} BW</td>
      <td style="color:#22c55e;font-weight:700">${escAdm(r.cash_value)}</td>
      <td><span style="background:${r.status==='paid'?'#dcfce7':r.status==='rejected'?'#fee2e2':'#fef9c3'};color:${r.status==='paid'?'#166534':r.status==='rejected'?'#991b1b':'#854d0e'};font-size:10px;font-weight:700;padding:2px 8px;border-radius:20px">${r.status}</span></td>
      <td style="display:flex;gap:4px">
        ${r.status==='pending'?`
          <button onclick="approveRedemption(${r.id})" style="background:#dcfce7;border:none;border-radius:4px;padding:3px 7px;font-size:10px;font-weight:700;color:#166534;cursor:pointer">✓ Paid</button>
          <button onclick="rejectRedemption(${r.id})" style="background:#fee2e2;border:none;border-radius:4px;padding:3px 7px;font-size:10px;font-weight:700;color:#991b1b;cursor:pointer">✕ Reject</button>
        ` : `<span style="color:#6b7280;font-size:11px">${(r.created_at||'').slice(0,16)}</span>`}
      </td>
    </tr>`).join('')}
    </tbody></table>`;
}

async function approveRedemption(id) {
  const res = await apiFetch(`/marketplace/redemptions/${id}/approve`, 'POST');
  alert(res.success ? '✅ ' + res.msg : 'Error: ' + res.msg);
  loadMarketplaceRedemptions();
}

async function rejectRedemption(id) {
  if (!confirm('Reject this redemption? BW will be refunded to the player.')) return;
  const res = await apiFetch(`/marketplace/redemptions/${id}/reject`, 'POST');
  alert(res.success ? '✅ ' + res.msg : 'Error: ' + res.msg);
  loadMarketplaceRedemptions();
}

// ── ROULETTE ADMIN ──
let _roulettePrizes = [];

async function loadRoulettePrizes() {
  const res = await apiFetch('/roulette/prizes');
  _roulettePrizes = res.success ? res.data : [];
  renderPrizeEditor();
}

function renderPrizeEditor() {
  const el = document.getElementById('roulettePrizeEditor');
  if (!el) return;
  if (!_roulettePrizes.length) {
    el.innerHTML = '<p style="color:#6b7280;font-size:13px">No prizes. Click "+ Add" to create one.</p>';
    return;
  }
  el.innerHTML = `<table class="data-table">
    <thead><tr><th>Label</th><th>Color</th><th>Text</th><th>Weight</th><th></th></tr></thead>
    <tbody>
    ${_roulettePrizes.map((p,i) => `<tr>
      <td><input type="text" value="${escAdm(p.label)}" onchange="_roulettePrizes[${i}].label=this.value"
        style="background:#0f172a;border:1px solid #334155;border-radius:6px;padding:5px 8px;color:#e2e8f0;width:110px;font-size:13px"></td>
      <td><div style="display:flex;align-items:center;gap:6px">
        <input type="color" value="${p.color}" onchange="_roulettePrizes[${i}].color=this.value"
          style="width:32px;height:28px;border:none;background:none;cursor:pointer">
        <span style="font-size:11px;color:#6b7280">${p.color}</span>
      </div></td>
      <td><select onchange="_roulettePrizes[${i}].text_color=this.value"
        style="background:#0f172a;border:1px solid #334155;border-radius:6px;padding:5px;color:#e2e8f0;font-size:13px">
        <option value="#fff" ${p.text_color==='#fff'?'selected':''}>White</option>
        <option value="#111" ${p.text_color==='#111'?'selected':''}>Black</option>
      </select></td>
      <td><input type="number" value="${p.weight}" min="1" max="100"
        onchange="_roulettePrizes[${i}].weight=parseInt(this.value)||1"
        style="background:#0f172a;border:1px solid #334155;border-radius:6px;padding:5px 8px;color:#e2e8f0;width:60px;font-size:13px"></td>
      <td><button onclick="_roulettePrizes.splice(${i},1);renderPrizeEditor()"
        style="background:transparent;border:1px solid #ef4444;color:#ef4444;border-radius:6px;padding:3px 8px;cursor:pointer;font-size:12px">✕</button></td>
    </tr>`).join('')}
    </tbody></table>`;
}

function rouletteAddPrize() {
  _roulettePrizes.push({ label: 'New Prize', color: '#852c2c', text_color: '#fff', weight: 5 });
  renderPrizeEditor();
}

async function rouletteSavePrizes() {
  const res = await apiFetch('/roulette/prizes', 'POST', _roulettePrizes);
  alert(res.success ? '✅ Prizes saved!' : ('Error: ' + res.msg));
  if (res.success) loadRoulettePrizes();
}

async function loadRouletteSpins() {
  const res = await apiFetch('/roulette/spins');
  const el  = document.getElementById('rouletteSpinHistory');
  if (!el) return;
  const list = res.success ? res.data : [];
  if (!list.length) {
    el.innerHTML = '<p style="color:#6b7280;font-size:13px">No spins yet.</p>';
    return;
  }
  el.innerHTML = `<table class="data-table">
    <thead><tr><th>Player</th><th>Prize</th><th>Time</th><th>Action</th></tr></thead>
    <tbody>
    ${list.map(s => `<tr>
      <td>${escAdm(s.username)}</td>
      <td><strong style="color:#f0c040">${escAdm(s.prize_label)}</strong></td>
      <td style="color:#6b7280;font-size:12px">${(s.created_at||'').slice(0,16)}</td>
      <td><button onclick="resetSpin('${escAdm(s.username)}')" style="background:#7f1d1d;border:none;color:#fca5a5;border-radius:6px;padding:4px 10px;font-size:12px;cursor:pointer">Reset</button></td>
    </tr>`).join('')}
    </tbody></table>`;
}

async function resetSpin(username) {
  if (!confirm(`Reset spin for ${username}? They can spin again immediately.`)) return;
  const res = await apiFetch('/roulette/reset', 'POST', { username });
  if (res.success) {
    alert(`✅ Spin reset for ${username}`);
    loadRouletteSpins();
  } else {
    alert(res.msg || 'Error');
  }
}

// ── SUPPORT CHAT (admin) ──
let adminCurrentUser  = null;
let adminCurrentAgent = null;
let adminLastId       = 0;
let adminPollTimer    = null;
let _convList         = [];  // cached for search filter

// ── agent colours ──
const AGENT_COLORS = {
  "BigWin Support": { bg: '#c9a84c', light: '#f6efd9', text: '#a0863c' },
  'Nicky':           { bg: '#db2777', light: '#fce7f3', text: '#9d174d' },
  'Brody':           { bg: '#2563eb', light: '#dbeafe', text: '#1e40af' },
};
function agentColor(agent) { return (AGENT_COLORS[agent] || { bg:'#475569', light:'#f1f5f9', text:'#334155' }); }

// avatar colour from username string
function avatarColor(str) {
  const cols = ['#852c2c','#ec4899','#f59e0b','#10b981','#3b82f6','#ceb05d','#ef4444','#14b8a6'];
  let h = 0; for (let i=0; i<str.length; i++) h = (h*31+str.charCodeAt(i))&0xffff;
  return cols[h % cols.length];
}

function relTime(iso) {
  if (!iso) return '';
  const diff = (Date.now() - new Date(iso.replace(' ','T')+'Z').getTime()) / 1000;
  if (diff < 60)   return 'just now';
  if (diff < 3600) return Math.floor(diff/60) + 'm ago';
  if (diff < 86400)return Math.floor(diff/3600) + 'h ago';
  return iso.slice(0,10);
}

async function loadConversations() {
  try {
    const data = await apiFetch('/support/conversations');
    _convList  = data.success ? (data.data || []) : [];
    renderConvList(_convList);
    const totalUnread = _convList.reduce((s,c)=>s+(c.unread||0),0);
    const navBadge = document.getElementById('supportNavBadge');
    if (navBadge) { navBadge.textContent = totalUnread||''; navBadge.style.display = totalUnread>0?'':'none'; }
    const topBadge = document.getElementById('supportTotalBadge');
    if (topBadge) { topBadge.textContent = totalUnread||''; topBadge.style.display = totalUnread>0?'':'none'; }
  } catch(e) {}
}

function renderConvList(list) {
  const el = document.getElementById('convList');
  if (!el) return;
  if (!list.length) {
    el.innerHTML = '<p style="color:#475569;font-size:13px;padding:12px 8px">No conversations yet.</p>';
    return;
  }
  el.innerHTML = list.map(c => {
    const ac  = agentColor(c.agent);
    const av  = avatarColor(c.username);
    const ini = (c.username||'?')[0].toUpperCase();
    const preview = c.last_message
      ? ((c.last_sender==='agent'?'You: ':'')+c.last_message).slice(0,46)+(c.last_message.length>46?'…':'')
      : 'No messages yet';
    return `
    <div class="support-conv-item ${adminCurrentUser===c.username&&adminCurrentAgent===c.agent?'active':''}"
         onclick="openAdminChat('${escAdm(c.username)}','${escAdm(c.agent)}')">
      <div class="sc-avatar" style="background:${av}">${ini}</div>
      <div class="sc-body">
        <div class="sc-name">${escAdm(c.username)}</div>
        <div class="sc-preview">${escAdm(preview)}</div>
        <span class="sc-agent-tag" style="background:${ac.light};color:${ac.text};margin-top:3px;display:inline-block">${escAdm(c.agent)}</span>
      </div>
      <div class="sc-meta">
        <span class="sc-time">${relTime(c.last_time)}</span>
        ${c.unread>0?`<span class="sc-badge">${c.unread}</span>`:''}
      </div>
    </div>`;
  }).join('');
}

function filterConvs(q) {
  q = (q||'').toLowerCase();
  renderConvList(q ? _convList.filter(c =>
    (c.username||'').toLowerCase().includes(q) ||
    (c.agent||'').toLowerCase().includes(q) ||
    (c.last_message||'').toLowerCase().includes(q)
  ) : _convList);
}

async function openAdminChat(username, agent) {
  adminCurrentUser  = username;
  adminCurrentAgent = agent;
  adminLastId = 0;
  const av  = avatarColor(username);
  const ac  = agentColor(agent);
  const ini = (username||'?')[0].toUpperCase();
  document.getElementById('adminChatHeader').innerHTML = `
    <div class="sch-avatar" style="background:${av}">${ini}</div>
    <div class="sch-info">
      <div class="sch-name">${escAdm(username)}</div>
      <div class="sch-sub">
        <span style="background:${ac.light};color:${ac.text};font-size:11px;font-weight:700;padding:1px 8px;border-radius:99px">${escAdm(agent)}</span>
      </div>
    </div>
    <button onclick="loadConversations();loadAdminMessages(true)" style="background:none;border:1px solid #334155;color:#94a3b8;border-radius:8px;padding:5px 12px;font-size:12px;cursor:pointer">↻</button>`;
  document.getElementById('adminChatMessages').innerHTML = '';
  await loadAdminMessages(true);
  startAdminPolling();
  loadConversations();
}

let _lastDateSep = '';

async function loadAdminMessages(full=false) {
  if (!adminCurrentUser) return;
  try {
    const since = full ? 0 : adminLastId;
    const url = `${API}/support/conversations/${encodeURIComponent(adminCurrentUser)}?agent=${encodeURIComponent(adminCurrentAgent)}&since_id=${since}`;
    const r    = await fetch(url, { headers: { 'X-Admin-Token': getAdminToken() || '' } });
    const data = await r.json();
    const msgs = data.data || [];
    if (!msgs.length) return;
    const wrap = document.getElementById('adminChatMessages');
    if (full) { wrap.innerHTML = ''; adminLastId = 0; _lastDateSep = ''; }

    const ac  = agentColor(adminCurrentAgent);
    const avi = (adminCurrentUser||'?')[0].toUpperCase();
    const av  = avatarColor(adminCurrentUser);

    msgs.forEach(msg => {
      if (msg.id <= adminLastId) return;
      adminLastId = msg.id;
      const isPlayer = msg.sender === 'player';
      const ts       = msg.created_at || '';
      const dateStr  = ts.slice(0,10);
      const timeStr  = ts.slice(11,16);

      // date separator
      if (dateStr && dateStr !== _lastDateSep) {
        _lastDateSep = dateStr;
        const sep = document.createElement('div');
        sep.className   = 'support-date-sep';
        sep.textContent = dateStr === new Date().toISOString().slice(0,10) ? 'Today' : dateStr;
        wrap.appendChild(sep);
      }

      const row = document.createElement('div');
      row.className = 'support-msg-row' + (isPlayer ? '' : ' from-agent');

      row.innerHTML = `
        <div class="msg-avatar" style="background:${isPlayer?av:ac.bg}">
          ${isPlayer ? avi : (adminCurrentAgent||'A')[0].toUpperCase()}
        </div>
        <div class="msg-bubble ${isPlayer?'from-player':'from-agent'}" style="${isPlayer?'':'background:'+ac.bg}">
          ${escAdm(msg.message).replace(/\n/g,'<br>')}
          <span class="msg-time">${isPlayer?'Player':'You'} · ${timeStr}</span>
        </div>`;
      wrap.appendChild(row);
    });
    wrap.scrollTop = wrap.scrollHeight;
  } catch(e) {}
}

let _adminSending = false;
async function adminSendMsg() {
  if (!adminCurrentUser || _adminSending) return;
  const input = document.getElementById('adminMsgInput');
  const text  = (input.value || '').trim();
  if (!text) return;
  _adminSending = true;
  input.value = '';
  input.style.height = '';
  try {
    await fetch(API + '/support/messages', {
      method: 'POST',
      headers: {'Content-Type':'application/json', 'X-Admin-Token': getAdminToken() || ''},
      body: JSON.stringify({ username: adminCurrentUser, agent: adminCurrentAgent, sender: 'agent', message: text })
    });
    await loadAdminMessages();
  } catch(e) {}
  _adminSending = false;
}

function startAdminPolling() {
  if (adminPollTimer) clearInterval(adminPollTimer);
  adminPollTimer = setInterval(loadAdminMessages, 4000);
}

function escAdm(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// Refresh conversations every 15s (only while an admin session is active)
let convPollTimer = null;
function startConversationsPolling() {
  if (convPollTimer) clearInterval(convPollTimer);
  convPollTimer = setInterval(loadConversations, 15000);
}

// ── INIT ──
function initAdmin() {
  loadStats();
  renderRecentTxns();
  loadAttachedList();
  startConversationsPolling();
}
checkAdminAuth();
