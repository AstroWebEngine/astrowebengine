/* â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
   AstroWebEngine â€” Frontend (core.js)
   Global constants, utilities, modal management, HUD
   â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â• */

const API = '';

// Admin impersonation: #impersonate=TOKEN&username=NAME sets session for this tab
(function() {
  const hash = window.location.hash.substring(1);
  if (hash && hash.startsWith('impersonate=')) {
    const params = new URLSearchParams(hash);
    sessionStorage.setItem('awe_impersonate_token', params.get('impersonate'));
    sessionStorage.setItem('awe_impersonate_username', params.get('username') || 'Unknown');
    // Clean URL
    window.location.hash = '';
  }
})();

const _impersonating = !!sessionStorage.getItem('awe_impersonate_token');
const TOKEN = sessionStorage.getItem('awe_impersonate_token') || localStorage.getItem('awe_token');
const USERNAME = sessionStorage.getItem('awe_impersonate_username') || localStorage.getItem('awe_username');
const IS_ADMIN = _impersonating ? false : localStorage.getItem('awe_is_admin') === 'true';

if (!TOKEN) window.location.href = '/';

// â”€â”€ UTC date helper: server sends naive UTC datetimes without 'Z' suffix â”€â”€
function serverDate(s) {
  if (!s) return null;
  if (!s.endsWith('Z') && !s.includes('+') && !/\d{2}-\d{2}:\d{2}$/.test(s)) s += 'Z';
  return new Date(s);
}

// â”€â”€ Skin system: apply saved skin immediately on load â”€â”€
const AVAILABLE_SKINS = [
  { id: 'blue-nova',   name: 'Blue Nova',   swatch: 'skin-swatch-blue-nova' },
  { id: 'amber-grid',  name: 'Amber Grid',  swatch: 'skin-swatch-amber-grid' },
  { id: 'dark-astros', name: 'Dark Astros', swatch: 'skin-swatch-dark-astros' },
];

function normalizeSkinId(skinId) {
  return skinId;
}

function applySkin(skinId) {
  skinId = normalizeSkinId(skinId);
  if (!skinId || skinId === 'blue-nova') {
    document.documentElement.removeAttribute('data-skin');
  } else {
    document.documentElement.setAttribute('data-skin', skinId);
  }
  localStorage.setItem('engine_skin', skinId || 'blue-nova');
  // Update selector if visible
  document.querySelectorAll('.skin-option').forEach(el => {
    el.classList.toggle('active', el.dataset.skin === (skinId || 'blue-nova'));
  });
}
// Apply immediately (backup â€” head script also does this before first paint)
(function() {
  const saved = normalizeSkinId(localStorage.getItem('engine_skin'));
  if (saved && saved !== 'blue-nova') {
    document.documentElement.setAttribute('data-skin', saved);
  }
})();

function setDateFormat(fmt) {
  if (!['MDY', 'DMY', 'YMD'].includes(fmt)) return;
  window._dateFormat = fmt;
  localStorage.setItem('awe_date_format', fmt);
  apiFetch('/api/account/settings', { method: 'POST', body: JSON.stringify({ date_format: fmt }) });
}

function setBBCodeImages(enabled) {
  window._showBBCodeImages = !!enabled;
  localStorage.setItem('awe_show_bbcode_images', enabled ? '1' : '0');
  apiFetch('/api/account/settings', { method: 'POST', body: JSON.stringify({ show_bbcode_images: !!enabled }) });
}

function headers() {
  return { 'Content-Type': 'application/json', 'Authorization': `Bearer ${TOKEN}` };
}

async function apiFetch(url, opts = {}) {
  opts.headers = { ...headers(), ...(opts.headers || {}) };
  const res = await fetch(`${API}${url}`, opts);
  if (res.status === 401) { localStorage.clear(); sessionStorage.removeItem('awe_impersonate_token'); sessionStorage.removeItem('awe_impersonate_username'); window.location.href = '/'; return null; }
  return res;
}

// â”€â”€ String & Number formatting utilities â”€â”€
function escStr(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
function escAttr(s) { return String(s || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'"); }
function fmtType(t) { return (t || '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()); }
function fmtNum(n) { return (n || 0).toLocaleString(undefined, { maximumFractionDigits: 0 }); }
function fmtTime(seconds) {
  if (seconds <= 0) return 'Done';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

// â”€â”€ Date formatting (user preference: MDY, DMY, YMD) â”€â”€
window._dateFormat = localStorage.getItem('awe_date_format') || 'MDY';
window._showBBCodeImages = localStorage.getItem('awe_show_bbcode_images') === '1';
function fmtDate(dateStr) {
  if (!dateStr) return '';
  const d = serverDate(dateStr);
  if (!d) return '';
  const dd = String(d.getDate()).padStart(2, '0');
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const yyyy = d.getFullYear();
  if (window._dateFormat === 'DMY') return `${dd}/${mm}/${yyyy}`;
  if (window._dateFormat === 'YMD') return `${yyyy}-${mm}-${dd}`;
  return `${mm}/${dd}/${yyyy}`;
}
function fmtDateTime(dateStr) {
  if (!dateStr) return '';
  const d = serverDate(dateStr);
  if (!d) return '';
  const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const dd = String(d.getDate()).padStart(2, '0');
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const yyyy = d.getFullYear();
  if (window._dateFormat === 'DMY') return `${dd}/${mm}/${yyyy} ${time}`;
  if (window._dateFormat === 'YMD') return `${yyyy}-${mm}-${dd} ${time}`;
  return `${mm}/${dd}/${yyyy} ${time}`;
}

// â”€â”€ Shield icon for level-based protection â”€â”€
// Shield only shows if YOU can't attack THEM (they're too low for you to hit)
const NEWBIE_PROTECTION_LEVEL = 10;
function shieldIcon(targetLevel, protectionBroken) {
  if (!targetLevel && targetLevel !== 0) return '';
  const myLevel = window._playerLevel || 0;
  // Under protection level â€” shield unless broken
  if (targetLevel < NEWBIE_PROTECTION_LEVEL) {
    if (protectionBroken) return '<span title="Protection lost" style="font-size:11px;opacity:0.6;">ðŸ›¡ï¸</span> ';
    return '<span title="Protected" style="font-size:11px;">ðŸ›¡ï¸</span> ';
  }
  // Above protection level â€” shield only if target is too LOW for you to attack
  if (myLevel > 0 && targetLevel > 0) {
    const lo = myLevel * 2 / 3;
    if (targetLevel < lo) return '<span title="Out of range" style="font-size:11px;">ðŸ›¡ï¸</span> ';
  }
  return '';
}

// â”€â”€ Clickable coordinate links â”€â”€
// Returns an HTML string wrapping a coord in a clickable link that navigates to the map
function looksLikeCoords(value) {
  return /^[A-Z]\d{2}(?::\d{2}){1,3}$/i.test(String(value || '').trim());
}

function coordLink(coords, extraClass) {
  if (!coords) return '';
  const cls = extraClass ? `coord-link ${extraClass}` : 'coord-link';
  return `<a class="${cls}" href="#" onclick="coordToMap('${escStr(coords)}');return false;" title="Navigate to ${escStr(coords)}">${escStr(coords)}</a>`;
}

function maybeCoordLink(value, extraClass) {
  if (!value) return '';
  const text = String(value).trim();
  return looksLikeCoords(text) ? coordLink(text, extraClass) : escStr(text);
}

// Navigate the galaxy map to a given coordinate string (e.g. 'A12:43:96:20')
async function coordToMap(coords) {
  if (!coords || coords.length < 5) return;
  try {
    const res = await apiFetch(`/api/resolve-coords?coords=${encodeURIComponent(coords)}`);
    if (!res || !res.ok) { console.warn('Could not resolve coords:', coords); return; }
    const loc = await res.json();
    // Switch to galaxy tab
    switchTab('galaxy');
    // Wait a tick for loadGalaxy to finish if it hasn't loaded yet
    await new Promise(r => setTimeout(r, 100));
    // Drill down: galaxy â†’ region â†’ system
    if (loc.galaxy_id && typeof selectGalaxy === 'function') {
      await selectGalaxy(loc.galaxy_id);
    }
    if (loc.region_id && typeof selectRegion === 'function') {
      await selectRegion(loc.region_id, loc.region_name);
    }
    if (loc.system_id && typeof selectSystem === 'function') {
      selectSystem(loc.system_id, loc.system_name);
    }
  } catch (e) { console.error('coordToMap error:', e); }
}

// â”€â”€ Modal management â”€â”€
// â”€â”€ Player tech level cache (shared across modules) â”€â”€
let _playerTechLevels = null;
async function getPlayerTechLevels() {
  if (_playerTechLevels) return _playerTechLevels;
  try {
    const res = await apiFetch('/api/research');
    const techs = await res.json();
    _playerTechLevels = {};
    for (const tech of techs) _playerTechLevels[tech.tech_type] = tech.level || 0;
  } catch (e) {}
  return _playerTechLevels || {};
}
function meetsShipTechReqs(spec, techLevels) {
  for (const [tech, lvl] of Object.entries(spec.req || {})) {
    if ((techLevels[tech] || 0) < lvl) return false;
  }
  return true;
}

function closeModal(id) { document.getElementById(id).classList.remove('active'); }
function openModal(id) { document.getElementById(id).classList.add('active'); }
function doLogout() { localStorage.clear(); window.location.href = '/'; }

// â”€â”€ Navigate to a specific base + subtab â”€â”€
function _goToBase(baseId, subtab) {
  _selectedBaseId = baseId;
  _baseSubtab = subtab || 'structures';
  switchTab('bases');
}

// â”€â”€ Tab switching â”€â”€
// Tabs accessible from Empire sub-tabs keep Empire button highlighted
const _empireChildTabs = new Set(['trade', 'battles', 'research']);
function switchTab(tab) {
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.awe-nav-btn').forEach(b => b.classList.remove('active'));
  const panel = document.getElementById(`tab-${tab}`);
  if (panel) panel.classList.add('active');
  // Highlight the correct nav button (Empire stays highlighted for child tabs)
  if (_empireChildTabs.has(tab)) {
    const empBtn = document.querySelector('.awe-nav-btn[data-tab="empire"]');
    if (empBtn) empBtn.classList.add('active');
  } else {
    const btn = document.querySelector(`.awe-nav-btn[data-tab="${tab}"]`);
    if (btn) btn.classList.add('active');
  }
  // Sync mobile bottom nav
  document.querySelectorAll('.mobile-nav-btn').forEach(b => b.classList.remove('active'));
  const mobileTab = _empireChildTabs.has(tab) ? 'empire' : tab;
  const mBtn = document.querySelector(`.mobile-nav-btn[data-tab="${mobileTab}"]`);
  if (mBtn) mBtn.classList.add('active');
  closeMobileMore();
  // Persist active tab across page refresh
  localStorage.setItem('awe_active_tab', tab);
  if (tab === 'bases') loadBases();
  else if (tab === 'galaxy') loadGalaxy();
  else if (tab === 'research') loadResearch();
  else if (tab === 'fleets') loadFleets();
  else if (tab === 'battles') loadBattles();
  else if (tab === 'rankings') loadRankings();
  else if (tab === 'trade') loadTradeRoutes();
  else if (tab === 'empire') loadEmpireTab();
  else if (tab === 'messages') loadMessages();
  else if (tab === 'board') { if (typeof loadGuild === 'function') loadGuild(); }
  else if (tab === 'commanders') { if (typeof loadCommanders === 'function') loadCommanders(); }
  else if (tab === 'account') loadAccount();
  else if (tab === 'guild') loadGuild();
  else if (tab === 'tutorial') { if (typeof loadTutorialTab === 'function') loadTutorialTab(); }
}

// â”€â”€ Empire tab sub-tabs â”€â”€
// Empire tab logic moved to core_empire.js.

// ── Tools dropdown (neutral shell): folded utility links ──
function toggleToolsMenu(e) {
  if (e) e.stopPropagation();
  const m = document.getElementById('awe-tools-menu');
  if (m) m.style.display = (m.style.display === 'none' || !m.style.display) ? 'flex' : 'none';
}
function closeToolsMenu() {
  const m = document.getElementById('awe-tools-menu');
  if (m) m.style.display = 'none';
}
document.addEventListener('click', (e) => {
  // Only relevant under the neutral shell (the dropdown is CSS-hidden elsewhere).
  if (document.documentElement.getAttribute('data-shell') !== 'neutral') return;
  const wrap = document.getElementById('awe-tools');
  const m = document.getElementById('awe-tools-menu');
  if (m && wrap && !wrap.contains(e.target)) m.style.display = 'none';
});

function updateServerTime() {
  const el = document.getElementById('server-time');
  if (el) {
    const now = new Date();
    // title attribute for server time display
    const y = now.getFullYear();
    const mo = String(now.getMonth() + 1).padStart(2, '0');
    const dy = String(now.getDate()).padStart(2, '0');
    const hh = String(now.getHours()).padStart(2, '0');
    const mm = String(now.getMinutes()).padStart(2, '0');
    const ss = String(now.getSeconds()).padStart(2, '0');
    el.setAttribute('title', `${y}/${mo}/${dy} ${hh}:${mm}:${ss}`);
    // Display text
    const time = `${hh}:${mm}:${ss}`;
    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    const monStr = months[now.getMonth()];
    if (window._dateFormat === 'YMD') el.textContent = `${y}-${mo}-${dy}, ${time}`;
    else if (window._dateFormat === 'MDY') el.textContent = `${monStr} ${now.getDate()}, ${y}, ${time}`;
    else el.textContent = `${now.getDate()} ${monStr} ${y}, ${time}`;
    // Mirror into any secondary clock slots (e.g. the Tools dropdown).
    document.querySelectorAll('.js-server-time').forEach(s => { s.textContent = el.textContent; });
  }
  // Also update mobile server time element
  const mobEl = document.getElementById('hud-server-time-mobile');
  if (mobEl) {
    const now2 = new Date();
    const hh2 = String(now2.getHours()).padStart(2, '0');
    const mm2 = String(now2.getMinutes()).padStart(2, '0');
    mobEl.textContent = `${hh2}:${mm2}`;
  }
}

// â”€â”€ Live countdown timer updates (title=seconds, auto-refresh on complete) â”€â”€
let _countdownAutoRefreshPending = false;

function updateCountdowns() {
  let anyCompleted = false;
  document.querySelectorAll('.countdown[data-end]').forEach(el => {
    const end = serverDate(el.dataset.end);
    const remaining = Math.max(0, (end - Date.now()) / 1000);
    const secs = Math.floor(remaining);
    // Store seconds in title attribute
    el.setAttribute('title', secs);
    {
      el.textContent = fmtTime(secs);
      if (secs <= 0) {
        el.textContent = 'Complete!';
        el.classList.add('countdown-done');
        el.removeAttribute('data-end');
        anyCompleted = true;
      }
    }
  });
  // When a timer completes, refresh the active tab's data (not on a poll â€” only on completion)
  if (anyCompleted && !_countdownAutoRefreshPending) {
    _countdownAutoRefreshPending = true;
    setTimeout(() => {
      _countdownAutoRefreshPending = false;
      if (typeof updateHUD === 'function') updateHUD();
      const activePanel = document.querySelector('.tab-panel.active');
      const activeTab = activePanel ? activePanel.id.replace('tab-', '') : '';
      if (activeTab === 'bases' && !(typeof _baseProdInteracting !== 'undefined' && _baseProdInteracting) && typeof loadBases === 'function') loadBases();
      else if (activeTab === 'empire' && !_empProdInteracting && typeof loadEmpireTab === 'function') loadEmpireTab();
      else if (activeTab === 'fleets' && typeof loadFleets === 'function') loadFleets();
      else if (activeTab === 'research' && typeof loadResearch === 'function') loadResearch();
    }, 2000);
  }
}

// ============================================================
// HUD & WIN CHECK
// ============================================================

async function updateHUD() {
  try {
    const res = await apiFetch('/api/player/stats');
    if (!res) return;
    const d = await res.json();
    // Store resources globally for affordability checks
    window._playerResources = d.resources || {};
    // Update resource display (single or multi)
    const credEl = document.getElementById('hud-credits');
    if (credEl) {
      if (getResourceModel() === 'multi' && d.resources) {
        const parts = [];
        for (const rt of getResourceTypes()) {
          const val = d.resources[rt] || 0;
          const label = RESOURCE_LABELS[rt] || rt.charAt(0).toUpperCase();
          const color = RESOURCE_COLORS[rt] || 'inherit';
          parts.push(`<span style="color:${color}" title="${rt}">${label}: ${fmtNum(val)}</span>`);
        }
        credEl.innerHTML = parts.join(' <span class="text-dim">|</span> ');
        const sfx = document.getElementById('hud-credits-suffix');
        if (sfx) sfx.style.display = 'none';
      } else {
        credEl.textContent = fmtNum(d.credits);
        const sfx = document.getElementById('hud-credits-suffix');
        if (sfx) sfx.style.display = '';
      }
    }
    const lvEl = document.getElementById('hud-level');
    if (lvEl) lvEl.textContent = d.level || 0;
    const econEl = document.getElementById('hud-econ');
    if (econEl) econEl.textContent = fmtNum(d.economy || 0);
    const flEl = document.getElementById('hud-fleet');
    if (flEl) flEl.textContent = `${fmtNum(d.fleet_size)}/${fmtNum(d.max_fleet_size)}`;
    const techEl = document.getElementById('hud-tech');
    if (techEl) techEl.textContent = fmtNum(d.technology || 0);
    const expEl = document.getElementById('hud-exp');
    if (expEl) expEl.textContent = fmtNum(d.experience);
    // Level-based protection indicator
    const nbEl = document.getElementById('hud-newbie');
    if (nbEl) {
      if (d.level_protected) {
        nbEl.textContent = '\u{1f6e1}\ufe0f Protected';
        nbEl.style.display = 'inline';
        nbEl.className = 'hstat text-success';
      } else {
        nbEl.style.display = 'none';
      }
    }
    // Store player level and fleet info globally
    window._playerLevel = d.level || 0;
    window._fleetCount = d.fleet_count || 0;
    window._maxFleetCount = d.max_fleet_count || 5;
    // Sync display preferences from server
    if (d.date_format) { window._dateFormat = d.date_format; localStorage.setItem('awe_date_format', d.date_format); }
    if (d.show_bbcode_images !== undefined) { window._showBBCodeImages = d.show_bbcode_images; localStorage.setItem('awe_show_bbcode_images', d.show_bbcode_images ? '1' : '0'); }
    updateServerTime();
  } catch (e) { console.error(e); }
}

async function checkWinCondition() {
  try {
    const res = await apiFetch('/api/game/check-win');
    if (!res) return;
    const d = await res.json();
    if (d.winner) {
      const banner = document.getElementById('win-banner');
      banner.textContent = `${d.winner} has won the game!`;
      banner.style.display = 'block';
    }
  } catch (e) {}
}

// â”€â”€ Snack notification â”€â”€
function showSnack(msg) {
  const el = document.getElementById('send-snack');
  el.textContent = msg;
  el.style.display = 'block';
  setTimeout(() => { el.style.display = 'none'; }, 4000);
}

// â”€â”€ Slide panels (notes/bookmarks) â”€â”€
function openNotesPanel() {
  closeSlidePanel('bookmarks-panel');
  const panel = document.getElementById('notes-panel');
  const ta = document.getElementById('player-notes');
  ta.value = localStorage.getItem('awe_notes_' + USERNAME) || '';
  panel.style.display = 'flex';
}
function openBookmarksPanel() {
  closeSlidePanel('notes-panel');
  const panel = document.getElementById('bookmarks-panel');
  panel.style.display = 'flex';
  renderBookmarks();
}
function closeSlidePanel(id) {
  const el = document.getElementById(id);
  if (el) el.style.display = 'none';
}
function saveNotes() {
  const ta = document.getElementById('player-notes');
  localStorage.setItem('awe_notes_' + USERNAME, ta.value);
  showSnack('Notes saved');
}

// â”€â”€ Bookmarks (stored in localStorage, will be upgraded to API later) â”€â”€
function getBookmarks() {
  try { return JSON.parse(localStorage.getItem('awe_bookmarks_' + USERNAME) || '[]'); }
  catch { return []; }
}
function saveBookmarks(bms) {
  localStorage.setItem('awe_bookmarks_' + USERNAME, JSON.stringify(bms));
  updateBookmarkCount();
}
function addBookmark(name, coords, planetId) {
  const bms = getBookmarks();
  if (bms.length >= 20) { showSnack('Max 20 bookmarks'); return false; }
  if (bms.some(b => b.coords === coords)) { showSnack('Already bookmarked'); return false; }
  bms.push({ name: name || coords, coords, planetId, ts: Date.now() });
  saveBookmarks(bms);
  showSnack('Bookmark added');
  return true;
}
function removeBookmark(coords) {
  let bms = getBookmarks();
  bms = bms.filter(b => b.coords !== coords);
  saveBookmarks(bms);
  renderBookmarks();
}
function updateBookmarkCount() {
  const bms = getBookmarks();
  const el = document.getElementById('bookmark-count');
  if (el) {
    if (bms.length > 0) { el.textContent = bms.length; el.style.display = 'inline-block'; }
    else { el.style.display = 'none'; }
  }
}
function renderBookmarks() {
  const container = document.getElementById('bookmarks-list');
  if (!container) return;
  const bms = getBookmarks();
  if (bms.length === 0) {
    container.innerHTML = '<p class="text-dim" style="font-size:11px;">No bookmarks yet. Visit a system or planet and click &#x2605; to bookmark it.</p>';
    return;
  }
  let html = '';
  bms.forEach(b => {
    html += `<div class="bookmark-item">
      <span class="bookmark-name" onclick="navigateToCoords('${b.coords}')">${b.name}</span>
      <span class="bookmark-coords">${coordLink(b.coords)}</span>
      <span class="bookmark-del" onclick="removeBookmark('${b.coords}')">&#x2717;</span>
    </div>`;
  });
  container.innerHTML = html;
}
function navigateToCoords(coords) {
  // Parse coords like A01:23:05:02 and navigate through the map
  closeSlidePanel('bookmarks-panel');
  switchTab('galaxy');
  // Try to navigate to the system containing this planet
  if (typeof drillToCoords === 'function') {
    drillToCoords(coords);
  }
}

// â”€â”€ Timer System â”€â”€
// Countdown seconds stored in title attribute: <span id=”timer1” title=”179530”>49:51:52</span>
// We replicate this: each timer span has title=seconds, display=HH:MM:SS, auto-decrements.
const _aeTimers = {};
let _aeTimerInterval = null;

function registerTimer(id, totalSeconds, onComplete) {
  _aeTimers[id] = { seconds: Math.max(0, totalSeconds), onComplete: onComplete || null };
  _updateTimerDisplay(id);
  if (!_aeTimerInterval) {
    _aeTimerInterval = setInterval(_tickAllTimers, 1000);
  }
}

function removeTimer(id) {
  delete _aeTimers[id];
  if (Object.keys(_aeTimers).length === 0 && _aeTimerInterval) {
    clearInterval(_aeTimerInterval);
    _aeTimerInterval = null;
  }
}

function _tickAllTimers() {
  for (const id in _aeTimers) {
    const t = _aeTimers[id];
    if (t.seconds > 0) {
      t.seconds--;
      _updateTimerDisplay(id);
      if (t.seconds <= 0 && t.onComplete) {
        t.onComplete();
      }
    }
  }
}

function _updateTimerDisplay(id) {
  const el = document.getElementById(id);
  if (!el) return;
  const t = _aeTimers[id];
  if (!t) return;
  el.setAttribute('title', t.seconds);
  el.textContent = formatCountdown(t.seconds);
}

function formatCountdown(totalSec) {
  if (totalSec <= 0) return 'Done';
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) return `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
  return `${m}:${String(s).padStart(2,'0')}`;
}

// â”€â”€ Bug Report System â”€â”€
function openBugReportModal() {
  document.getElementById('bug-title').value = '';
  document.getElementById('bug-description').value = '';
  document.getElementById('bug-category').value = 'bug';
  document.getElementById('bug-report-status').textContent = '';
  openModal('bug-report-modal');
}

async function submitBugReport() {
  const title = document.getElementById('bug-title').value.trim();
  const description = document.getElementById('bug-description').value.trim();
  const category = document.getElementById('bug-category').value;
  const statusEl = document.getElementById('bug-report-status');

  if (!title || title.length < 3) {
    statusEl.innerHTML = '<span class="text-danger">Title is required (min 3 characters)</span>';
    return;
  }

  try {
    const res = await apiFetch('/api/bug-report', {
      method: 'POST',
      body: JSON.stringify({ title, description, category, page: _baseSubtab || '' })
    });
    const data = await res.json();
    if (data.success) {
      closeModal('bug-report-modal');
      showSnack('Report submitted. Thank you!');
    } else {
      statusEl.innerHTML = `<span class="text-danger">${data.detail || 'Failed to submit'}</span>`;
    }
  } catch (e) {
    statusEl.innerHTML = '<span class="text-danger">Error submitting report</span>';
  }
}

// â”€â”€ Empire Production Submit â”€â”€
// Empire production helpers moved to core_empire.js.

function toggleMobileMore() {
  const menu = document.getElementById('mobile-more-menu');
  if (!menu) return;
  menu.style.display = menu.style.display === 'none' ? 'flex' : 'none';
}
function closeMobileMore() {
  const menu = document.getElementById('mobile-more-menu');
  if (menu) menu.style.display = 'none';
}

// Initialize bookmark count on load
document.addEventListener('DOMContentLoaded', () => { updateBookmarkCount(); });

// â”€â”€ Engine Config: game definition engine flags for frontend adaptation â”€â”€
// Loaded once at startup; other modules read window.AWE_CONFIG
window.STATE = window.STATE || {};
window.AWE_CONFIG = null;
async function loadEngineConfig() {
  try {
    const r = await fetch(API + '/api/engine-config');
    if (r.ok) window.AWE_CONFIG = await r.json();
    // Re-apply static translations now that any ruleset ui.labels overrides
    // (e.g. nav tab names) are available.
    if (typeof applyStaticTranslations === 'function') applyStaticTranslations();
    applyRulesetShell();
  } catch(e) { console.warn('Failed to load engine config:', e); }
}
loadEngineConfig();

/** Apply the active ruleset's theme/shell (engine ui.theme / ui.shell), unless
 *  the user has chosen an explicit override. Caches the applied values so the
 *  pre-paint script in game.html can match them early on the next load. */
function applyRulesetShell() {
  const ui = (window.AWE_CONFIG && window.AWE_CONFIG.ui) || {};
  const root = document.documentElement;
  const resolve = (overrideKey, defVal) => localStorage.getItem(overrideKey) || defVal || '';
  const theme = resolve('awe_theme', ui.theme);
  const shell = resolve('awe_shell', ui.shell);
  if (theme) { root.setAttribute('data-theme', theme); localStorage.setItem('awe_theme_applied', theme); }
  else { root.removeAttribute('data-theme'); localStorage.removeItem('awe_theme_applied'); }
  if (shell) { root.setAttribute('data-shell', shell); localStorage.setItem('awe_shell_applied', shell); }
  else { root.removeAttribute('data-shell'); localStorage.removeItem('awe_shell_applied'); }
}

/** Helper: get an engine config value with a default fallback */
function getEngineFlag(key, defaultVal) {
  if (!window.AWE_CONFIG) return defaultVal;
  const eng = window.AWE_CONFIG.engine || {};
  return key in eng ? eng[key] : defaultVal;
}

/** Resource model helpers */
function getResourceModel() { return getEngineFlag('resource_model', 'single'); }
function getResourceTypes() { return getEngineFlag('resource_types', ['credits']); }

/** Short labels for resource types */
const RESOURCE_LABELS = {
  credits: 'cr', metal: 'M', crystal: 'C', deuterium: 'D', energy: 'E',
};
const RESOURCE_COLORS = {
  credits: 'var(--accent)', metal: '#aab', crystal: '#7cf', deuterium: '#6d8',
};

/**
 * Format a cost for display (works with both scalar and dict costs).
 * Single-resource: "1,234"
 * Multi-resource: "M: 1,234 C: 567 D: 89"
 */
function formatResourceCost(cost) {
  if (cost == null) return '0';
  if (typeof cost === 'number') return fmtNum(cost);
  if (typeof cost === 'object') {
    const parts = [];
    for (const [k, v] of Object.entries(cost)) {
      if (v > 0) {
        const label = RESOURCE_LABELS[k] || k.charAt(0).toUpperCase();
        parts.push(`<span style="color:${RESOURCE_COLORS[k] || 'inherit'}">${label}:${fmtNum(v)}</span>`);
      }
    }
    return parts.length ? parts.join(' ') : '0';
  }
  return '0';
}

/** Plain-text variant of formatResourceCost (for snackbars/tooltips that set textContent). */
function formatResourceCostText(cost) {
  if (cost == null) return '0';
  if (typeof cost === 'number') return fmtNum(cost);
  if (typeof cost === 'object') {
    const parts = [];
    for (const [k, v] of Object.entries(cost)) {
      if (v > 0) parts.push(`${RESOURCE_LABELS[k] || k}: ${fmtNum(v)}`);
    }
    return parts.length ? parts.join(', ') : '0';
  }
  return '0';
}

/**
 * Scale a cost (scalar or dict) by a multiplier.
 */
function scaleCost(cost, mult) {
  if (typeof cost === 'number') return cost * mult;
  if (typeof cost === 'object') {
    const r = {};
    for (const [k, v] of Object.entries(cost)) r[k] = v * mult;
    return r;
  }
  return cost;
}

/**
 * Get total value of a cost (sum of all resources). Used for time calculations.
 */
function costValue(cost) {
  if (typeof cost === 'number') return cost;
  if (typeof cost === 'object') return Object.values(cost).reduce((a, b) => a + b, 0);
  return 0;
}

/**
 * Check if user can afford a cost based on current resources.
 * @param {object} resources - user's resources dict from API
 * @param {number|object} cost - scalar or dict cost
 */
function canAffordClient(resources, cost) {
  if (typeof cost === 'number') {
    const primary = getResourceTypes()[0] || 'credits';
    return (resources[primary] || 0) >= cost;
  }
  if (typeof cost === 'object') {
    for (const [k, v] of Object.entries(cost)) {
      if (v > 0 && (resources[k] || 0) < v) return false;
    }
    return true;
  }
  return true;
}

// â”€â”€ Normalized Client Catalog â”€â”€
// Stable internal keys resolve through this cache so game definitions can rename
// ships/buildings/research/astros without hard-coding display text in modules.
STATE.catalog = STATE.catalog || {
  loadedAt: 0,
  schemaVersion: 0,
  meta: {},
  engine: {},
  specs: {
    ships: {}, defenses: {}, buildings: {}, research: {},
    astros: {}, weapons: {}, commanders: {}, goods: {},
  },
  players: {},
  world: { galaxies: {}, regions: {}, systems: {}, planets: {}, colonies: {} },
};
let _catalogPromise = null;
let _catalogRefreshTimer = null;

function _mergeCatalog(payload) {
  if (!payload) return STATE.catalog;
  STATE.catalog.schemaVersion = payload.schema_version || STATE.catalog.schemaVersion || 1;
  STATE.catalog.meta = payload.meta || STATE.catalog.meta || {};
  STATE.catalog.engine = payload.engine || STATE.catalog.engine || {};
  STATE.catalog.specs = { ...(STATE.catalog.specs || {}), ...(payload.specs || {}) };
  STATE.catalog.players = payload.players || STATE.catalog.players || {};
  STATE.catalog.world = { ...(STATE.catalog.world || {}), ...(payload.world || {}) };
  STATE.catalog.loadedAt = Date.now();
  window.AWE_CONFIG = { meta: STATE.catalog.meta, engine: STATE.catalog.engine };
  return STATE.catalog;
}

async function fetchCatalog(opts = {}) {
  const force = !!opts.force;
  if (!force && STATE.catalog.loadedAt) return STATE.catalog;
  if (_catalogPromise && !force) return _catalogPromise;
  _catalogPromise = (async () => {
    try {
      const res = await apiFetch('/api/catalog/visible');
      if (!res || !res.ok) return STATE.catalog;
      return _mergeCatalog(await res.json());
    } catch (e) {
      console.warn('Failed to load catalog:', e);
      return STATE.catalog;
    } finally {
      _catalogPromise = null;
    }
  })();
  return _catalogPromise;
}

function scheduleCatalogRefresh() {
  clearTimeout(_catalogRefreshTimer);
  _catalogRefreshTimer = setTimeout(() => fetchCatalog({ force: true }), 250);
}

function invalidateCatalog(kinds) {
  const kindSet = new Set(kinds || ['specs', 'players', 'world']);
  if (kindSet.has('specs')) {
    STATE.catalog.specs = {
      ships: {}, defenses: {}, buildings: {}, research: {},
      astros: {}, weapons: {}, commanders: {}, goods: {},
    };
    try { if (typeof _shipSpecs !== 'undefined') _shipSpecs = null; } catch (_) {}
    window._empShipSpecs = null;
  }
  if (kindSet.has('players')) STATE.catalog.players = {};
  if (kindSet.has('world')) {
    STATE.catalog.world = { galaxies: {}, regions: {}, systems: {}, planets: {}, colonies: {} };
  }
  STATE.catalog.loadedAt = 0;
  scheduleCatalogRefresh();
}

function applyCatalogDelta(msg) {
  if (!msg || !msg.kind || msg.id == null) return;
  const id = String(msg.id);
  const maps = {
    ship: STATE.catalog.specs.ships,
    defense: STATE.catalog.specs.defenses,
    building: STATE.catalog.specs.buildings,
    research: STATE.catalog.specs.research,
    astro: STATE.catalog.specs.astros,
    player: STATE.catalog.players,
    galaxy: STATE.catalog.world.galaxies,
    region: STATE.catalog.world.regions,
    system: STATE.catalog.world.systems,
    planet: STATE.catalog.world.planets,
    colony: STATE.catalog.world.colonies,
  };
  const target = maps[msg.kind];
  if (!target) return;
  if (msg.op === 'remove') delete target[id];
  else target[id] = { ...(target[id] || {}), ...(msg.fields || {}), key: msg.id };
  STATE.catalog.loadedAt = Date.now();
}

async function getCatalogSpecs(kind) {
  await fetchCatalog();
  return (STATE.catalog.specs && STATE.catalog.specs[kind]) || {};
}

function catalogSpec(kind, key) {
  return ((STATE.catalog.specs || {})[kind] || {})[key] || null;
}

function catalogName(kind, key, fallback) {
  const spec = catalogSpec(kind, key);
  return (spec && spec.name) || fallback || fmtType(key);
}

function shipName(key, fallback) { return catalogName('ships', key, fallback); }
function defenseName(key, fallback) { return catalogName('defenses', key, fallback); }
function buildingName(key, fallback) { return catalogName('buildings', key, fallback); }
function researchName(key, fallback) { return catalogName('research', key, fallback); }
function astroName(key, fallback) { return catalogName('astros', key, fallback); }

fetchCatalog();
setInterval(() => fetchCatalog({ force: true }), 5 * 60 * 1000);
window.addEventListener('focus', () => {
  if (!STATE.catalog.loadedAt || Date.now() - STATE.catalog.loadedAt > 10 * 60 * 1000) {
    fetchCatalog({ force: true });
  }
});

// â”€â”€ Event polling (fallback for when WebSocket is unavailable) â”€â”€
let _lastEventId = 0;
let _eventPollInterval = null;

async function pollNewEvents() {
  try {
    const res = await apiFetch('/api/events');
    if (!res) return;
    const events = await res.json();
    if (!Array.isArray(events) || events.length === 0) return;

    const newEvents = events.filter(e => e.id > _lastEventId);
    if (_lastEventId === 0) {
      // First load â€” just set the watermark, don't spam snacks
      _lastEventId = events[0].id;
      return;
    }

    for (const evt of newEvents.slice(0, 3)) {
      showSnack(evt.message);
    }
    if (newEvents.length > 0) {
      _lastEventId = Math.max(...newEvents.map(e => e.id));
    }
  } catch (e) { /* silent */ }
}

function startEventPolling() {
  if (_eventPollInterval) return;
  pollNewEvents(); // initial watermark
  // Poll at a slow rate â€” WebSocket handles real-time delivery
  _eventPollInterval = setInterval(pollNewEvents, 120000);
}

// â”€â”€ WebSocket real-time connection â”€â”€
let _ws = null;
let _wsReconnectDelay = 1000;

function connectWebSocket() {
  if (!TOKEN) return;
  if (_ws && _ws.readyState <= WebSocket.OPEN) return;

  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url = `${proto}//${location.host}/ws?token=${TOKEN}`;
  _ws = new WebSocket(url);

  _ws.onopen = () => {
    // connected
    _wsReconnectDelay = 1000;
    // Keepalive ping every 30s
    _ws._pingInterval = setInterval(() => {
      if (_ws.readyState === WebSocket.OPEN) _ws.send('ping');
    }, 30000);
  };

  _ws.onmessage = (evt) => {
    if (evt.data === 'pong') return;
    try {
      const msg = JSON.parse(evt.data);
      handleWsMessage(msg);
    } catch (_) {}
  };

  _ws.onclose = () => {
    if (_ws && _ws._pingInterval) clearInterval(_ws._pingInterval);
    _ws = null;
    setTimeout(() => {
      _wsReconnectDelay = Math.min(_wsReconnectDelay * 2, 30000);
      connectWebSocket();
    }, _wsReconnectDelay);
  };

  _ws.onerror = () => {}; // onclose handles reconnect
}

const WS_TAB_MAP = {
  construction: 'bases', research: 'research', fleet: 'fleets',
  combat: 'fleets', attack: 'fleets', colonize: 'bases',
  trade: 'trade', guild: 'board',
};

function handleWsMessage(msg) {
  if (msg.type === 'catalog.invalidate') {
    invalidateCatalog(msg.kinds);
    return;
  }
  if (msg.type === 'catalog.update') {
    applyCatalogDelta(msg);
    return;
  }
  if (msg.type !== 'event') return;

  // Show snack notification
  showSnack(msg.message);

  // Browser notification for important events when tab isn't focused
  const notifyTypes = ['combat', 'attack', 'construction', 'research', 'colonize'];
  if (notifyTypes.includes(msg.event_type) && !document.hasFocus()) {
    const titles = {
      combat: 'Combat Report', attack: 'Under Attack!',
      construction: 'Construction Complete', research: 'Research Complete',
      colonize: 'Colony Update',
    };
    const title = titles[msg.event_type] || 'AstroWebEngine';
    try {
      if ('Notification' in window && Notification.permission === 'granted') {
        new Notification(title, { body: msg.message });
      }
    } catch (_) {}
  }

  // Auto-refresh the relevant tab if it is currently active
  const relevantTab = WS_TAB_MAP[msg.event_type];
  if (relevantTab) {
    const activePanel = document.querySelector('.tab-panel.active');
    const activeTab = activePanel ? activePanel.id.replace('tab-', '') : '';
    if (activeTab === relevantTab) {
      if (relevantTab === 'bases' && !(typeof _baseProdInteracting !== 'undefined' && _baseProdInteracting) && typeof loadBases === 'function') loadBases();
      else if (relevantTab === 'research' && typeof loadResearch === 'function') loadResearch();
      else if (relevantTab === 'fleets' && typeof loadFleets === 'function') loadFleets();
      else if (relevantTab === 'trade' && typeof loadTradeRoutes === 'function') loadTradeRoutes();
      else if ((relevantTab === 'guild' || relevantTab === 'board') && typeof loadGuild === 'function') loadGuild();
    }
  }

  // Always refresh HUD stats
  if (typeof updateHUD === 'function') updateHUD();
}

window.addEventListener('beforeunload', () => {
  if (_ws) { _ws.onclose = null; _ws.close(); }
});
