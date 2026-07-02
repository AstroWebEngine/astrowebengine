/* AstroWebEngine frontend (social_account.js)
   Account pages and account display preferences. */

// ============================================================
// ACCOUNT
// ============================================================

let _accountData = null;
let _accountServerData = null;
let _accountSub = 'overview';
const ACCOUNT_NEWS_ITEMS = [
  { title: 'Account pages refreshed', kind: 'Engine', date: '16 Apr 2026' },
  { title: 'Guild graphs are now live', kind: 'Feature', date: '16 Apr 2026' },
  { title: 'Galaxy map tuned', kind: 'Map', date: '16 Apr 2026' }
];

function switchAccountSub(sub) {
  _accountSub = sub;
  document.querySelectorAll('#account-sidebar [data-account-sub]').forEach(a => {
    a.classList.toggle('active', a.dataset.accountSub === sub);
  });
  renderAccountContent();
}

async function loadAccount() {
  try {
    const [accountRes, statusRes] = await Promise.all([
      apiFetch('/api/account'),
      apiFetch('/api/game/status')
    ]);
    if (accountRes) _accountData = await accountRes.json();
    if (statusRes) _accountServerData = await statusRes.json();
  } catch (e) { console.error(e); }
  applyStoredDisplayWidth();
  applyStoredAccountCheckboxes();
  renderAccountContent();
}

function renderAccountContent() {
  const el = document.getElementById('account-content');
  if (!el) return;
  const d = _accountData;
  switch (_accountSub) {
    case 'overview': return renderAccountOverview(el, d);
    case 'profile': return renderAccountProfile(el, d);
    case 'private': return renderAccountPrivate(el, d);
    case 'display': return renderAccountDisplay(el);
    case 'vacation': return renderAccountVacation(el);
    case 'restart': return renderAccountRestart(el);
    case 'delete': return renderAccountDelete(el);
    case 'upgrade': return renderAccountUpgrade(el);
    case 'upgrades': return renderAccountUpgrades(el);
    case 'recruit': return renderAccountRecruit(el);
    case 'banners': return renderAccountBanners(el);
    default: el.innerHTML = '';
  }
}

function formatAccountNumber(n, decimals = 0) {
  return Number(n || 0).toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function formatAccountLevel(n) {
  const v = Number(n || 0);
  if (!Number.isFinite(v)) return '0';
  return v.toFixed(2).replace(/0+$/, '').replace(/\.$/, '');
}

function renderAccountBox(title, body, extraClass = '') {
  return `<div class="account-box ${extraClass}">
    ${title ? `<div class="account-box-title">${title}</div>` : ''}
    <div class="account-box-body">${body}</div>
  </div>`;
}

function renderAccountStatTable(rows, extraClass = '') {
  return `<table class="account-stat-table ${extraClass}"><tbody>${
    rows.map(([label, value, cls = '']) => `<tr><td>${label}</td><td class="${cls}">${value}</td></tr>`).join('')
  }</tbody></table>`;
}

function renderAccountPlaceholder(el, title, body, actions = '') {
  el.innerHTML = `<div class="account-placeholder">
    <div class="account-placeholder-title">${title}</div>
    <div class="account-placeholder-body">${body}</div>
    ${actions ? `<div class="account-placeholder-actions">${actions}</div>` : ''}
  </div>`;
}

function renderAccountOverview(el, d) {
  if (!d) { el.innerHTML = '<p class="text-dim">Loading...</p>'; return; }
  const server = _accountServerData || {};
  const profileBox = renderAccountBox('', renderAccountStatTable([
    ['Nick', escStr(d.username), 'text-bright font-bold'],
    ['Player Id', fmtNum(d.player_id), 'font-mono']
  ]), 'account-box-narrow');
  const upgradeBox = renderAccountBox('', renderAccountStatTable([
    ['Account Type', d.is_admin ? 'Administrator' : 'Standard', 'text-accent'],
    ['Upgrade Expires', 'â€”', 'text-dim']
  ]), 'account-box-narrow');
  const statsBox = renderAccountBox('', renderAccountStatTable([
    ['Level', `${formatAccountLevel(d.level)}${d.rank ? ` <span class="comment">(Rank ${fmtNum(d.rank)})</span>` : ''}`, 'text-bright'],
    ['Economy', formatAccountNumber(d.economy), 'text-warn'],
    ['Empire Income', `${formatAccountNumber(d.empire_income)} cred./h`, 'text-warn'],
    ['Fleet Size', formatAccountNumber(d.fleet_value), 'font-mono'],
    ['Fleet Limit', `${formatAccountNumber(d.fleet_limit)} <span class="account-inline-help">â“˜</span>`, 'font-mono comment'],
    ['Technology', formatAccountNumber(d.technology), 'text-accent2'],
    ['Combat Experience', `${formatAccountNumber(d.experience)}/${formatAccountNumber(d.experience)}`, 'font-mono']
  ]), 'account-box-narrow');
  const hasReserve = (d.base_reserve || 0) > 0;
  const reserveBelowPeak = (d.bases_founded_peak || 0) > (d.bases || 0);
  const nextBaseRows = [
    ['Cost of next base', `${formatAccountNumber(d.next_colony_cost)} Credits <span class="account-inline-help">â“˜</span>`, 'text-warn']
  ];
  if (hasReserve) {
    nextBaseRows.push(['Base reserve', `${formatAccountNumber(d.base_reserve)} Credits`, 'text-accent2']);
    nextBaseRows.push(['You pay', `${formatAccountNumber(d.next_colony_net)} Credits`, 'text-bright']);
  }
  if (reserveBelowPeak) {
    nextBaseRows.push(['Rebuild discount', `25% (below your peak of ${d.bases_founded_peak} bases)`, 'comment']);
  }
  const nextBaseBox = renderAccountBox('', renderAccountStatTable(nextBaseRows), 'account-box-narrow account-next-base-box');
  const newsBox = renderAccountBox('News / Blog', ACCOUNT_NEWS_ITEMS.map(item => `
      <div class="account-news-item">
        <div class="account-news-title">${escStr(item.title)}</div>
        <div class="account-news-meta">${escStr(item.kind)} - ${escStr(item.date)}</div>
      </div>
    `).join(''), 'account-side-box');
  const serverBox = renderAccountBox('Server', `
      <div class="account-server-stats">
        <div><strong>Players:</strong> ${fmtNum(server.total_players || 0)}</div>
        <div><strong>Online:</strong> ${fmtNum(server.online_players || 0)}</div>
      </div>
      <div class="account-server-foot">Version 5</div>
    `, 'account-server-box');
  el.innerHTML = `<div class="account-overview-layout">
    <div class="account-overview-main">
      ${profileBox}
      ${upgradeBox}
      ${statsBox}
      ${nextBaseBox}
    </div>
    <div class="account-overview-side">
      ${newsBox}
      ${serverBox}
    </div>
  </div>`;
}

function renderAccountProfile(el, d) {
  if (!d) { el.innerHTML = ''; return; }
  el.innerHTML = `<div class="account-profile-layout">
    <div class="account-profile-column">
      <div class="account-profile-row"><span>Nickname:</span><strong>${escStr(d.username)}</strong></div>
      <div class="account-profile-row"><span>Avatar:</span><span>No avatar uploaded</span></div>
      <div class="account-profile-row"><span>Homepage:</span><span class="text-dim"></span></div>
    </div>
    <div class="account-profile-column">
      <div class="account-profile-row"><span>Description:</span><span class="text-dim"></span></div>
      <div class="account-profile-row"><span>Languages:</span><span class="text-dim"></span></div>
    </div>
  </div>
  <div class="account-profile-actions">
    <button class="btn btn-primary btn-sm" onclick="showSnack('Profile editing is not available yet')">Edit profile</button>
    <button class="btn btn-primary btn-sm" onclick="switchTab('messages'); setTimeout(()=>showPlayerProfile(${d.player_id}), 0);">View As Another</button>
  </div>`;
}

function renderAccountPrivate(el, d) {
  if (!d) { el.innerHTML = ''; return; }
  const newsletterOptIn = localStorage.getItem('awe_newsletter_opt_in') !== '0';
  el.innerHTML = `<div class="account-private-layout">
    <div class="account-private-main">
      <div class="account-profile-row"><span>Real Name:</span><span>(empty)</span></div>
      <div class="account-profile-row"><span>E-mail:</span><strong>${escStr(d.email || '(empty)')}</strong></div>
      <div class="account-profile-row"><span>Country:</span><span>(empty)</span></div>
      <div class="account-profile-row"><span>Password:</span><span>******</span></div>
      <div class="account-profile-actions account-private-actions">
        <button class="btn btn-primary btn-sm" onclick="showSnack('Private info editing is not available yet')">Edit Information</button>
      </div>
    </div>
    <div class="account-private-notify">
      <div class="account-box-title">Notifications:</div>
      <label class="account-check-row">
        <input type="checkbox" id="newsletter-opt-in" ${newsletterOptIn ? 'checked' : ''}/>
        <span>Receive our newsletter with latest news and offers</span>
      </label>
      <div class="account-profile-actions account-private-actions">
        <button class="btn btn-primary btn-sm" onclick="saveAccountNewsletter()">Update</button>
      </div>
    </div>
  </div>
  <div class="account-password-box">
    <div class="account-box-title">Change Password</div>
    <div class="account-password-row">
      <div class="form-group" style="margin:0;"><label>CURRENT</label><input type="password" id="pw-old"/></div>
      <div class="form-group" style="margin:0;"><label>NEW</label><input type="password" id="pw-new"/></div>
      <div class="form-group" style="margin:0;"><label>CONFIRM</label><input type="password" id="pw-confirm"/></div>
      <button class="btn btn-primary btn-sm" onclick="changePassword()">Update</button>
    </div>
    <div id="pw-status" class="account-inline-status"></div>
  </div>`;
}

function renderAccountDisplay(el) {
  const currentSkin = localStorage.getItem('engine_skin') || 'blue-nova';
  const currentLang = localStorage.getItem('awe_lang') || 'en';
  const currentDateFmt = window._dateFormat || 'MDY';
  const displayWidth = localStorage.getItem('awe_display_width') || '';
  const mapMode = localStorage.getItem('awe_map_mode') || 'auto';
  const animatedServerTime = localStorage.getItem('awe_display_animated_server_time') !== '0';
  const animatedLocalTime = localStorage.getItem('awe_display_animated_local_time') === '1';
  const localEndTimes = localStorage.getItem('awe_display_local_end_times') === '1';
  const displayNotifications = localStorage.getItem('awe_display_notifications') !== '0';
  const bbcodeMode = window._showBBCodeImages ? 'on' : 'off';
  el.innerHTML = `<div class="account-display-layout">
    ${renderAccountBox('', `
      <div class="account-setting-grid">
        <div class="account-setting-row">
          <label>Language:</label>
          <select id="account-lang-select">${LANGUAGES.map(l => `<option value="${l.id}" ${l.id===currentLang?'selected':''}>${escStr(l.name)}</option>`).join('')}</select>
          <button class="btn btn-primary btn-sm" onclick="saveAccountLanguage()">Update</button>
        </div>
        <div class="account-setting-row">
          <label>Numbers format:</label>
          <select id="account-numfmt-select"><option value="us" selected>1,000.01</option></select>
          <button class="btn btn-primary btn-sm" onclick="showSnack('Number formatting follows your browser locale')">Update</button>
        </div>
        <div class="account-setting-row">
          <label>Date format:</label>
          <select id="account-date-format-select">
            <option value="MDY" ${currentDateFmt==='MDY'?'selected':''}>20 Jan 2010, 12:50:00</option>
            <option value="DMY" ${currentDateFmt==='DMY'?'selected':''}>20 Jan 2010, 12:50:00</option>
            <option value="YMD" ${currentDateFmt==='YMD'?'selected':''}>2010 Jan 20, 12:50:00</option>
          </select>
          <button class="btn btn-primary btn-sm" onclick="saveAccountDateFormat()">Update</button>
        </div>
        <div class="account-setting-row">
          <label>Skin:</label>
          <select id="account-skin-select">${AVAILABLE_SKINS.map(s => `<option value="${s.id}" ${s.id===currentSkin?'selected':''}>${escStr(s.name)}</option>`).join('')}</select>
          <button class="btn btn-primary btn-sm" onclick="saveAccountSkin()">Update</button>
        </div>
        <div class="account-setting-row">
          <label>Display width:</label>
          <input type="text" id="account-width-input" value="${escAttr(displayWidth)}" />
          <button class="btn btn-primary btn-sm" onclick="saveAccountDisplayWidth()">Update</button>
        </div>
        <div class="account-setting-hint">(empty)=Standard ; Minimum=650 ; Maximum=1050</div>
        <div class="account-setting-row">
          <label>Map:</label>
          <select id="account-map-select">
            <option value="auto" ${mapMode==='auto'?'selected':''}>(Auto)</option>
            <option value="interactive" ${mapMode==='interactive'?'selected':''}>Interactive</option>
            <option value="static" ${mapMode==='static'?'selected':''}>Static</option>
          </select>
          <button class="btn btn-primary btn-sm" onclick="saveAccountMapMode()">Update</button>
        </div>
      </div>
    `, 'account-display-top')}
    ${renderAccountBox('', `
      <label class="account-check-row"><input type="checkbox" id="account-animated-server-time" ${animatedServerTime ? 'checked' : ''}/> <span>Display animated server time.</span></label>
      <label class="account-check-row"><input type="checkbox" id="account-animated-local-time" ${animatedLocalTime ? 'checked' : ''}/> <span>Display animated local time.</span></label>
      <label class="account-check-row"><input type="checkbox" id="account-local-end-times" ${localEndTimes ? 'checked' : ''}/> <span>Display end times of events (in local time).</span></label>
      <label class="account-check-row"><input type="checkbox" id="account-display-notifications" ${displayNotifications ? 'checked' : ''}/> <span>Display notifications.</span></label>
      <div class="account-setting-inline">
        <span>BBCode images</span>
        <label>Inbox:</label>
        <select id="account-bbcode-inbox"><option value="on" ${bbcodeMode==='on'?'selected':''}>Display images</option><option value="off" ${bbcodeMode==='off'?'selected':''}>Hide</option></select>
      </div>
      <div class="account-setting-inline">
        <span></span>
        <label>Board:</label>
        <select id="account-bbcode-board"><option value="on" ${bbcodeMode==='on'?'selected':''}>Display images</option><option value="off" ${bbcodeMode==='off'?'selected':''}>Hide</option></select>
      </div>
      <div class="account-setting-inline">
        <span></span>
        <label>Advertising:</label>
        <select id="account-advertising"><option value="hide" selected>Hide</option></select>
      </div>
      <div class="account-profile-actions" style="justify-content:center;margin-top:10px;">
        <button class="btn btn-primary btn-sm" onclick="saveAccountDisplayOptions()">Update</button>
      </div>
    `, 'account-display-bottom')}
  </div>`;
}

function renderAccountVacation(el) {
  renderAccountPlaceholder(
    el,
    'Vacation Mode',
    'Vacation mode is not wired yet on this server. The page shell is in place and will be connected once the feature rules are finalized.'
  );
}

function renderAccountRestart(el) {
  renderAccountPlaceholder(
    el,
    'Restart Account',
    'Account restart is intentionally disabled right now. It should eventually use a gated confirmation flow instead of being a one-click reset.'
  );
}

function renderAccountDelete(el) {
  renderAccountPlaceholder(
    el,
    'Delete Account',
    `Are you sure that you want to <span class="text-danger font-bold">DELETE</span> this account forever?<br><br>
     Enter your account password to confirm:<br>
     <input type="password" id="delete-pw" class="account-delete-input"/>`,
    `<button class="btn btn-danger btn-sm" onclick="deleteAccount()">Delete</button>
     <button class="btn btn-ghost btn-sm" onclick="switchAccountSub('overview')">Cancel</button>
     <div id="delete-status" class="account-inline-status"></div>`
  );
}

async function deleteAccount() {
  const pw = document.getElementById('delete-pw')?.value;
  const st = document.getElementById('delete-status');
  if (!pw) { st.innerHTML = '<span class="text-danger">Password required</span>'; return; }
  st.innerHTML = '<span class="text-dim">Account deletion is not yet available on this server.</span>';
}

function renderAccountUpgrade(el) {
  renderAccountPlaceholder(
    el,
    'Upgrade',
    'Upgrade perks and purchase flow are not connected yet. The menu placement is in place so we can slot the real page in later without moving the rest of the account layout.'
  );
}

function renderAccountUpgrades(el) {
  renderAccountPlaceholder(
    el,
    'Upgrades History',
    'No upgrade history is available on this server yet.'
  );
}

function renderAccountRecruit(el) {
  renderAccountPlaceholder(
    el,
    'Recruit',
    'Recruit links and referral tracking are not implemented yet.'
  );
}

function renderAccountBanners(el) {
  renderAccountPlaceholder(
    el,
    'Banners',
    'Banner generation is not implemented yet.'
  );
}

function applyStoredDisplayWidth() {
  const raw = (localStorage.getItem('awe_display_width') || '').trim();
  const n = parseInt(raw, 10);
  if (!raw || Number.isNaN(n)) {
    document.documentElement.style.setProperty('--game-shell-width', '1050px');
    return;
  }
  const clamped = Math.max(650, Math.min(1050, n));
  document.documentElement.style.setProperty('--game-shell-width', `${clamped}px`);
}

function applyStoredAccountCheckboxes() {
  const serverTimeEl = document.getElementById('server-time');
  const mobileTimeEl = document.getElementById('hud-server-time-mobile');
  const showServerTime = localStorage.getItem('awe_display_animated_server_time') !== '0';
  if (serverTimeEl) serverTimeEl.style.display = showServerTime ? '' : 'none';
  if (mobileTimeEl) mobileTimeEl.style.display = showServerTime ? '' : 'none';
}

function saveAccountLanguage() {
  const sel = document.getElementById('account-lang-select');
  if (!sel) return;
  setLanguage(sel.value);
  showSnack('Language updated');
}

function saveAccountDateFormat() {
  const sel = document.getElementById('account-date-format-select');
  if (!sel) return;
  setDateFormat(sel.value);
  showSnack('Date format updated');
}

function saveAccountSkin() {
  const sel = document.getElementById('account-skin-select');
  if (!sel) return;
  applySkin(sel.value);
  showSnack('Skin updated');
}

function saveAccountDisplayWidth() {
  const input = document.getElementById('account-width-input');
  if (!input) return;
  const raw = input.value.trim();
  if (!raw) {
    localStorage.removeItem('awe_display_width');
    applyStoredDisplayWidth();
    showSnack('Display width reset');
    return;
  }
  const n = parseInt(raw, 10);
  if (Number.isNaN(n)) {
    showSnack('Display width must be a number');
    return;
  }
  const clamped = Math.max(650, Math.min(1050, n));
  localStorage.setItem('awe_display_width', String(clamped));
  input.value = String(clamped);
  applyStoredDisplayWidth();
  showSnack('Display width updated');
}

function saveAccountMapMode() {
  const sel = document.getElementById('account-map-select');
  if (!sel) return;
  localStorage.setItem('awe_map_mode', sel.value);
  showSnack('Map preference updated');
}

function saveAccountDisplayOptions() {
  const serverTime = !!document.getElementById('account-animated-server-time')?.checked;
  const localTime = !!document.getElementById('account-animated-local-time')?.checked;
  const localEndTimes = !!document.getElementById('account-local-end-times')?.checked;
  const notifications = !!document.getElementById('account-display-notifications')?.checked;
  localStorage.setItem('awe_display_animated_server_time', serverTime ? '1' : '0');
  localStorage.setItem('awe_display_animated_local_time', localTime ? '1' : '0');
  localStorage.setItem('awe_display_local_end_times', localEndTimes ? '1' : '0');
  localStorage.setItem('awe_display_notifications', notifications ? '1' : '0');
  const bbInbox = document.getElementById('account-bbcode-inbox')?.value === 'on';
  const bbBoard = document.getElementById('account-bbcode-board')?.value === 'on';
  setBBCodeImages(bbInbox || bbBoard);
  applyStoredAccountCheckboxes();
  showSnack('Display settings updated');
}

function saveAccountNewsletter() {
  const checked = !!document.getElementById('newsletter-opt-in')?.checked;
  localStorage.setItem('awe_newsletter_opt_in', checked ? '1' : '0');
  showSnack('Notification preference updated');
}

function renderSkinSelector() {
  // Legacy compat â€” no longer used directly but kept for safety
  const container = document.getElementById('skin-selector');
  if (!container) return;
  const currentSkin = localStorage.getItem('engine_skin') || 'blue-nova';
  container.innerHTML = AVAILABLE_SKINS.map(s => `
    <div class="skin-option ${s.id === currentSkin ? 'active' : ''}" data-skin="${s.id}"
         onclick="applySkin('${s.id}')">
      <div class="skin-swatch ${s.swatch}"></div>
      <span>${escStr(s.name)}</span>
    </div>
  `).join('');
}

async function changePassword() {
  const oldPw = document.getElementById('pw-old').value;
  const newPw = document.getElementById('pw-new').value;
  const confirmPw = document.getElementById('pw-confirm').value;
  const statusEl = document.getElementById('pw-status');
  if (!oldPw || !newPw) { statusEl.innerHTML = '<span class="text-danger">All fields required</span>'; return; }
  if (newPw !== confirmPw) { statusEl.innerHTML = '<span class="text-danger">Passwords do not match</span>'; return; }
  try {
    const res = await apiFetch('/api/account/change-password', {
      method: 'POST', body: JSON.stringify({ old_password: oldPw, new_password: newPw })
    });
    const data = await res.json();
    if (data.success) {
      statusEl.innerHTML = '<span class="text-success">Password updated!</span>';
      document.getElementById('pw-old').value = '';
      document.getElementById('pw-new').value = '';
      document.getElementById('pw-confirm').value = '';
    } else {
      statusEl.innerHTML = `<span class="text-danger">${data.detail || 'Failed'}</span>`;
    }
  } catch (e) { statusEl.innerHTML = '<span class="text-danger">Error</span>'; }
}

