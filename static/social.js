/* AstroWebEngine frontend: trade, battles, rankings, BBCode helpers,
   event log, tutorial, commanders, credit history, changelog,
   and shared social UI glue.
   Messages, reports, account, and guild pages now live in dedicated social_* modules. */

// Messages and contacts moved to social_messages.js.

// Account pages moved to social_account.js.
// ============================================================
// TRADE ROUTES TAB
// ============================================================

async function loadTradeRoutes() {
  try {
    const [routesRes, basesRes] = await Promise.all([apiFetch('/api/trade-routes'), apiFetch('/api/bases')]);
    if (!routesRes || !basesRes) return;
    const routes = await routesRes.json();
    const bases = await basesRes.json();
    renderTradeRoutes(routes.routes || [], bases, routes.num_players || 0);
  } catch (e) { console.error(e); }
}

function renderTradeRoutes(routes, bases, numPlayers) {
  const container = document.getElementById('trade-routes-container');
  const baseOpts = bases.map(b => `<option value="${b.id}">${escStr(b.name)}</option>`).join('');
  document.getElementById('trade-base-a').innerHTML = baseOpts;
  document.getElementById('trade-base-b').innerHTML = baseOpts;
  if (!routes.length) {
    container.innerHTML = '<div class="empty-state"><p>No trade routes yet. Create one between two bases with Spaceports.</p></div>';
    return;
  }
  let html = '';
  for (const r of routes) {
    const closing = r.is_closing ? ' <span class="badge badge-warn">Closing</span>' : '';
    const incoming = r.is_incoming ? ' <span class="badge badge-info" style="background:var(--accent);color:#fff;padding:2px 6px;border-radius:3px;font-size:10px;">Incoming</span>' : '';
    const pending = !r.is_incoming && r.is_pending ? ' <span class="badge badge-warn" style="background:#a80;color:#fff;padding:2px 6px;border-radius:3px;font-size:10px;">Pending</span>' : '';
    const baseAName = typeof r.base_a === 'object' ? r.base_a.name : r.base_a;
    const baseBName = typeof r.base_b === 'object' ? r.base_b.name : r.base_b;
    html += `<div class="trade-route-card">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <div>
          <span class="text-bright">${escStr(baseAName || '?')}</span>
          <span class="text-dim"> â‡— </span>
          <span class="text-bright">${escStr(baseBName || '?')}</span>
          ${closing}${incoming}${pending}
        </div>
        <div style="display:flex;gap:6px;">
          ${r.is_incoming ? `<button class="btn btn-primary btn-sm" onclick="acceptTradeRoute(${r.id})">Accept</button><button class="btn btn-danger btn-sm" onclick="rejectTradeRoute(${r.id})">Reject</button>` : ''}
          ${!r.is_incoming && !r.is_closing && !r.is_pending ? `<button class="btn btn-ghost btn-sm" onclick="makeTradePublic(${r.id})">List Public</button>` : ''}
          ${!r.is_incoming && !r.is_closing ? `<button class="btn btn-danger btn-sm" onclick="cancelTradeRoute(${r.id})">Cancel</button>` : ''}
        </div>
      </div>
      <div style="display:flex;gap:16px;margin-top:6px;font-size:12px;">
        <span class="text-warn">${r.is_incoming ? `From: ${escStr(r.from_player || '?')}` : `Income: ${Math.ceil(r.income)} cr/hr`}</span>
        <span class="text-dim">Setup cost: ${fmtNum(r.cost)} cr</span>
        <span class="text-dim">Distance: ${r.distance}</span>
      </div>
    </div>`;
  }
  container.innerHTML = html;
  const totalIncome = routes.filter(r => !r.is_closing).reduce((sum, r) => sum + r.income, 0);
  document.getElementById('trade-total-income').textContent = `Total trade income: ${Math.ceil(totalIncome)} cr/hr`;
  // Trade formula
  let formulaEl = document.getElementById('trade-formula-panel');
  if (!formulaEl) {
    formulaEl = document.createElement('div');
    formulaEl.id = 'trade-formula-panel';
    formulaEl.className = 'text-dim';
    formulaEl.style.cssText = 'margin-top:12px;font-size:11px;padding:8px;border-top:1px solid var(--border-dim, #333);';
    container.parentNode.appendChild(formulaEl);
  }
  formulaEl.innerHTML = `<strong>Trade Formula</strong><br>
    Trade Income = &radic;(Lowest base economy) &times; [ 1 + &radic;(2&times;Distance)/75 + &radic;(Players)/10 ]<br>
    Players = total unique players in your trade network (currently: ${numPlayers})`;
}

async function createTradeRoute() {
  const baseA = parseInt(document.getElementById('trade-base-a').value);
  const coordsInput = document.getElementById('trade-coords-input')?.value.trim();
  const errEl = document.getElementById('trade-error');
  errEl.style.display = 'none';

  let baseB;
  if (coordsInput) {
    // Resolve coordinates to colony ID
    try {
      const res = await apiFetch(`/api/resolve-coords?coords=${encodeURIComponent(coordsInput)}`);
      if (!res || !res.ok) {
        const data = await res?.json().catch(() => ({}));
        const msg = typeof data?.detail === 'string' ? data.detail : 'Could not find base at those coordinates';
        errEl.textContent = msg;
        errEl.style.display = 'block';
        return;
      }
      const data = await res.json();
      baseB = data.base_id || data.colony_id;
    } catch(e) {
      errEl.textContent = 'Error resolving coordinates';
      errEl.style.display = 'block';
      return;
    }
  } else {
    baseB = parseInt(document.getElementById('trade-base-b').value);
  }

  if (!baseB || isNaN(baseB)) { errEl.textContent = 'Select a destination base or enter coordinates'; errEl.style.display = 'block'; return; }
  if (baseA === baseB) { errEl.textContent = 'Select two different bases'; errEl.style.display = 'block'; return; }
  try {
    const res = await apiFetch('/api/trade-routes', {
      method: 'POST', body: JSON.stringify({ base_a_id: baseA, base_b_id: baseB })
    });
    const data = await res.json();
    if (data.success || data.id) { showSnack('Trade route established!'); await loadTradeRoutes(); await updateHUD(); }
    else { const msg = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail) || 'Failed'; errEl.textContent = msg; errEl.style.display = 'block'; }
  } catch (e) { errEl.textContent = 'Error'; errEl.style.display = 'block'; }
}

async function acceptTradeRoute(routeId) {
  try {
    const res = await apiFetch(`/api/trade-routes/${routeId}/accept`, { method: 'POST' });
    const data = await res.json();
    if (data.success) { showSnack('Trade route accepted!'); await loadTradeRoutes(); await updateHUD(); }
    else { const msg = typeof data.detail === 'string' ? data.detail : 'Failed'; showSnack(msg); }
  } catch (e) { console.error(e); }
}

async function rejectTradeRoute(routeId) {
  if (!confirm('Reject this trade request?')) return;
  try {
    const res = await apiFetch(`/api/trade-routes/${routeId}/reject`, { method: 'POST' });
    const data = await res.json();
    if (data.success) { showSnack('Trade request rejected'); await loadTradeRoutes(); }
    else { const msg = typeof data.detail === 'string' ? data.detail : 'Failed'; showSnack(msg); }
  } catch (e) { console.error(e); }
}

async function cancelTradeRoute(routeId) {
  if (!confirm('Cancel this trade route? You\'ll get a 50% refund of the setup cost.')) return;
  try {
    const res = await apiFetch(`/api/trade-routes/${routeId}`, { method: 'DELETE' });
    const data = await res.json();
    if (data.success) { showSnack('Trade route cancelled'); await loadTradeRoutes(); await updateHUD(); }
    else showSnack(data.detail || 'Failed');
  } catch (e) { console.error(e); }
}

async function makeTradePublic(routeId) {
  try {
    const res = await apiFetch(`/api/trade-routes/${routeId}/make-public`, { method: 'POST' });
    const data = await res.json();
    if (data.success) { showSnack('Trade listed on public finder for 48 hours'); await loadTradeRoutes(); }
    else showSnack(data.detail || 'Failed');
  } catch (e) { console.error(e); }
}

async function loadTradeFinder() {
  try {
    const res = await apiFetch('/api/trade-finder');
    const data = await res.json();
    const el = document.getElementById('trade-finder-container');
    const allTrades = [...(data.trades || []), ...(data.guild_trades || [])];
    if (!allTrades.length) {
      el.innerHTML = '<div class="empty-state"><p>No bases listed. Guild bases with open slots appear automatically. Other players can list their bases publicly.</p></div>';
      return;
    }
    let html = `<table class="data-table" style="width:100%;font-size:12px;">
      <thead><tr><th>Base</th><th>Player</th><th>Economy</th><th>Coords</th><th>Source</th></tr></thead><tbody>`;
    for (const tr of allTrades) {
      const srcBadge = tr.source === 'guild' ? '<span class="badge badge-blue">Guild</span>' : '<span class="badge badge-warn">Public</span>';
      html += `<tr>
        <td>${escStr(tr.base_name || '?')}</td>
        <td>${escStr(tr.owner || '?')}</td>
        <td>${tr.economy || 0}</td>
        <td>${maybeCoordLink(tr.coords)}</td>
        <td>${srcBadge}</td>
      </tr>`;
    }
    html += '</tbody></table>';
    el.innerHTML = html;
  } catch (e) { console.error(e); }
}

// ============================================================
// BATTLES TAB
// ============================================================

async function loadBattles() {
  try {
    const res = await apiFetch('/api/battles');
    if (!res) return;
    const battles = await res.json();
    const container = document.getElementById('battles-container');
    if (!battles.length) {
      container.innerHTML = '<div class="empty-state"><p>No battles yet.</p></div>';
      return;
    }
    container.innerHTML = battles.map(b => {
      const r = b.report;
      const result = r.result === 'attacker_wins' ? '<span class="text-success">Attacker Won</span>' : (r.result === 'defender_wins' ? '<span class="text-danger">Defender Won</span>' : '<span class="text-warn">Draw</span>');
      const fmtShips = (obj) => Object.entries(obj || {}).map(([t, c]) => `${t.replace(/_/g,' ')}: ${c}`).join(', ') || 'none';
      const atkForces = fmtShips(r.attacker_forces);
      const defForces = fmtShips(r.defender_forces);
      const defTurrets = fmtShips(r.defender_turrets);
      const atkL = fmtShips(r.attacker_losses);
      const defL = fmtShips(r.defender_losses);
      const defD = fmtShips(r.defense_losses);
      return `<div class="battle-card">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <span class="text-bright">${escStr(r.attacker)} vs ${escStr(r.defender)}</span>
          <span>${result}</span>
        </div>
        <div class="text-dim" style="font-size:11px;">Base: ${escStr(r.base_name || '?')} Â· ${fmtDateTime(b.created_at)}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px;font-size:11px;">
          <div style="padding:6px;background:var(--bg-dark);border-radius:4px;">
            <div class="text-accent" style="font-weight:600;margin-bottom:3px;">Attacker: ${escStr(r.attacker)}</div>
            <div class="text-dim">Forces: ${atkForces}</div>
            <div class="text-danger">Losses: ${atkL}</div>
            <div class="text-warn">Value lost: ${fmtNum(r.attacker_value_lost || 0)} cr</div>
          </div>
          <div style="padding:6px;background:var(--bg-dark);border-radius:4px;">
            <div class="text-accent" style="font-weight:600;margin-bottom:3px;">Defender: ${escStr(r.defender)}</div>
            <div class="text-dim">Forces: ${defForces}</div>
            ${defTurrets !== 'none' ? `<div class="text-dim">Defenses: ${defTurrets}</div>` : ''}
            <div class="text-danger">Losses: ${defL}${defD !== 'none' ? ' | Def: ' + defD : ''}</div>
            <div class="text-warn">Value lost: ${fmtNum(r.defender_value_lost || 0)} cr</div>
          </div>
        </div>
        <div style="display:flex;gap:16px;margin-top:6px;font-size:11px;">
          <span class="text-accent2">Debris: ${fmtNum(r.debris)} cr</span>
          <span class="text-dim">Combat loot: ${fmtNum(r.combat_loot || 0)} cr each</span>
          ${r.pillage ? `<span class="text-warn">Pillage: ${fmtNum(r.pillage)} cr</span>` : ''}
          ${r.occupied ? '<span class="text-danger font-bold">BASE OCCUPIED</span>' : ''}
        </div>
      </div>`;
    }).join('');
  } catch (e) { console.error(e); }
}

// ============================================================
// RANKINGS TAB
// ============================================================

async function loadRankings() {
  try {
    const [lbRes, statusRes, guildsRes] = await Promise.all([apiFetch('/api/leaderboard'), apiFetch('/api/game/status'), apiFetch('/api/guilds')]);
    if (!lbRes || !statusRes) return;
    const board = await lbRes.json();
    const st = await statusRes.json();
    document.getElementById('rankings-tbody').innerHTML = board.map((p, i) => {
      const isMe = p.username === USERNAME;
      const rowStyle = isMe ? ' style="background:rgba(234,199,103,0.06);"' : '';
      return `<tr${rowStyle}><td class="text-dim">${i+1}</td>
        <td class="${isMe ? 'text-accent font-bold' : 'text-bright'}">${escStr(p.username)}</td>
        <td>${p.level || 0}</td><td>${p.bases}</td>
        <td class="text-warn font-mono">${fmtNum(p.economy || 0)}</td>
        <td class="font-mono">${fmtNum(p.fleet_value || 0)}</td>
        <td class="text-accent2 font-mono">${fmtNum(p.technology || 0)}</td>
        <td class="text-accent font-mono font-bold">${fmtNum(p.score)}</td></tr>`;
    }).join('');
    // Guild rankings
    if (guildsRes) {
      const guilds = await guildsRes.json();
      document.getElementById('guild-rankings-tbody').innerHTML = guilds.map((g, i) =>
        `<tr><td class="text-dim">${i+1}</td>
          <td class="text-accent font-bold">[${escStr(g.tag)}]</td>
          <td class="text-bright">${escStr(g.name)}</td>
          <td class="text-dim">${escStr(g.leader)}</td>
          <td class="font-mono">${g.members}</td>
          <td class="font-mono">${g.guild_level || '?'}</td>
          <td class="text-warn font-mono">${fmtNum(g.total_economy || 0)}</td>
          <td class="font-mono">${fmtNum(g.total_fleet || 0)}</td></tr>`
      ).join('') || '<tr><td colspan="8" class="text-dim" style="text-align:center;">No guilds yet</td></tr>';
    }
    document.getElementById('gameinfo-body').innerHTML = `<table class="data-table" style="font-size:12px;">
      <tr><td class="text-dim">Server</td><td class="text-bright">${escStr(st.game_name)}</td></tr>
      <tr><td class="text-dim">Status</td><td><span class="badge ${st.status === 'active' ? 'badge-green' : 'badge-warn'}">${st.status}</span></td></tr>
      <tr><td class="text-dim">Players</td><td class="font-mono">${st.total_players}</td></tr>
      <tr><td class="text-dim">Planets</td><td class="font-mono">${st.colonized_planets} / ${st.total_planets} colonized</td></tr>
      <tr><td class="text-dim">Colonize Cost</td><td class="text-warn font-mono">${fmtNum(st.colonize_cost)} cr</td></tr>
      <tr><td class="text-dim">Win Condition</td><td>${escStr(st.win_condition || 'domination')}</td></tr>
      <tr><td class="text-dim">Game Speed</td><td class="font-mono">${st.game_speed || 1}x</td></tr>
    </table>`;
  } catch (e) { console.error(e); }
}

// ============================================================
// BBCODE PARSER
// ============================================================

function parseBBCode(raw) {
  if (!raw) return '';
  let s = escStr(raw);
  s = s.replace(/\[b\]([\s\S]*?)\[\/b\]/gi, '<strong>$1</strong>');
  s = s.replace(/\[i\]([\s\S]*?)\[\/i\]/gi, '<em>$1</em>');
  s = s.replace(/\[u\]([\s\S]*?)\[\/u\]/gi, '<u>$1</u>');
  s = s.replace(/\[s\]([\s\S]*?)\[\/s\]/gi, '<s>$1</s>');
  s = s.replace(/\[color=([a-zA-Z#0-9]+)\]([\s\S]*?)\[\/color\]/gi, '<span style="color:$1">$2</span>');
  s = s.replace(/\[size=(\d+)\]([\s\S]*?)\[\/size\]/gi, (_, sz, txt) => {
    const px = Math.max(8, Math.min(36, parseInt(sz)));
    return `<span style="font-size:${px}px">${txt}</span>`;
  });
  s = s.replace(/\[url=([^\]]+)\]([\s\S]*?)\[\/url\]/gi, '<a href="$1" target="_blank" rel="noopener" class="text-accent">$2</a>');
  s = s.replace(/\[url\]([\s\S]*?)\[\/url\]/gi, '<a href="$1" target="_blank" rel="noopener" class="text-accent">$1</a>');
  if (window._showBBCodeImages) {
    s = s.replace(/\[img\]([\s\S]*?)\[\/img\]/gi, '<img src="$1" style="max-width:100%;max-height:200px;" alt="image">');
  } else {
    s = s.replace(/\[img\]([\s\S]*?)\[\/img\]/gi, '<span class="text-dim" style="font-size:10px;">[image hidden]</span>');
  }
  s = s.replace(/\[left\]([\s\S]*?)\[\/left\]/gi, '<div style="text-align:left">$1</div>');
  s = s.replace(/\[center\]([\s\S]*?)\[\/center\]/gi, '<div style="text-align:center">$1</div>');
  s = s.replace(/\[right\]([\s\S]*?)\[\/right\]/gi, '<div style="text-align:right">$1</div>');
  s = s.replace(/\[list=1\]([\s\S]*?)\[\/list\]/gi, '<ol class="bbcode-list">$1</ol>');
  s = s.replace(/\[list\]([\s\S]*?)\[\/list\]/gi, '<ul class="bbcode-list">$1</ul>');
  s = s.replace(/\[\*\](.*?)(?=\[\*\]|<\/[ou]l>|$)/gi, '<li>$1</li>');
  s = s.replace(/\[hr\]/gi, '<hr style="border-color:#1a3322;margin:6px 0;">');
  s = s.replace(/\n/g, '<br>');
  return s;
}

function bbcodeInsertTag(textareaId, tag, hasValue) {
  const ta = document.getElementById(textareaId);
  if (!ta) return;
  const start = ta.selectionStart;
  const end = ta.selectionEnd;
  const selected = ta.value.substring(start, end);
  let insert;
  if (hasValue) {
    const val = prompt(`Enter value for [${tag}=]:`, '');
    if (val === null) return;
    insert = `[${tag}=${val}]${selected}[/${tag}]`;
  } else if (tag === '*') {
    insert = `[*]${selected}`;
  } else if (tag === 'hr') {
    insert = `[hr]`;
  } else {
    insert = `[${tag}]${selected}[/${tag}]`;
  }
  ta.value = ta.value.substring(0, start) + insert + ta.value.substring(end);
  ta.focus();
  ta.selectionStart = ta.selectionEnd = start + insert.length;
}

function bbcodeInsertColorTag(textareaId, color) {
  const ta = document.getElementById(textareaId);
  if (!ta) return;
  const start = ta.selectionStart;
  const end = ta.selectionEnd;
  const selected = ta.value.substring(start, end);
  const insert = `[color=${color}]${selected}[/color]`;
  ta.value = ta.value.substring(0, start) + insert + ta.value.substring(end);
  ta.focus();
  ta.selectionStart = ta.selectionEnd = start + insert.length;
}

document.addEventListener('input', function(e) {
  if (e.target.id === 'guild-edit-desc') {
    const counter = document.getElementById('guild-edit-counter');
    if (counter) counter.textContent = 1200 - e.target.value.length;
  }
});

// Guild pages moved to social_guild.js.
// ============================================================
// EVENT LOG
// ============================================================

async function loadEventLog() {
  try {
    const res = await apiFetch('/api/events');
    if (!res) return '';
    const events = await res.json();
    if (!events.length) return '<div class="text-dim" style="padding:12px;">No events yet.</div>';
    let html = '<table class="data-table"><thead><tr><th>Time</th><th>Type</th><th>Event</th></tr></thead><tbody>';
    for (const e of events) {
      const typeColors = { construction: 'text-success', research: 'text-accent2', fleet: 'text-warn', attack: 'text-danger', colonize: 'text-accent', guild: 'text-bright', trade: 'text-warn' };
      const cls = typeColors[e.type] || 'text-dim';
      const time = fmtDateTime(e.created_at);
      html += `<tr><td class="text-dim" style="font-size:10px;white-space:nowrap;">${time}</td>
        <td class="${cls}" style="font-size:11px;text-transform:uppercase;">${e.type}</td>
        <td>${escStr(e.message)}</td></tr>`;
    }
    html += '</tbody></table>';
    return html;
  } catch (e) { return '<div class="text-dim">Error loading events</div>'; }
}

// ============================================================
// JUMP TO BASE + NOTIFICATIONS + NEWS TICKER + INIT
// ============================================================

async function jumpToMyBase(baseIdx) {
  try {
    const res = await apiFetch('/api/my-bases-coords');
    if (!res) return;
    const coords = await res.json();
    if (!coords.length) return;
    const t = coords[baseIdx || 0];
    if (!t) return;
    switchTab('galaxy');
    await selectGalaxy(t.galaxy_id);
    await selectRegion(t.region_id, t.region_name);
    const sys = _currentSystems.find(s => s.id === t.system_id);
    if (sys) selectSystem(t.system_id, t.system_name);
  } catch (e) {}
}

async function renderMyBasesJumpMenu() {
  try {
    const res = await apiFetch('/api/my-bases-coords');
    if (!res) return;
    const coords = await res.json();
    const c = document.getElementById('jump-to-base-menu');
    if (!c) return;
    if (!coords.length) {
      c.innerHTML = '';
      if (typeof setMapSidebarHighlightData === 'function') setMapSidebarHighlightData('bases', []);
      if (typeof syncMapSidebarCounts === 'function') syncMapSidebarCounts();
      return;
    }
    c.innerHTML = coords.map((b, i) =>
      `<button class="btn btn-ghost btn-sm" onclick="jumpToMyBase(${i})" title="${escStr(b.planet_name)}">${escStr(b.base_name)}</button>`
    ).join('');
    if (typeof setMapSidebarHighlightData === 'function') setMapSidebarHighlightData('bases', coords);
    if (typeof syncMapSidebarCounts === 'function') syncMapSidebarCounts();
  } catch (e) {}
}

async function loadNewsTicker() {
  try {
    const res = await apiFetch('/api/battles');
    if (!res) return;
    const battles = await res.json();
    const el = document.getElementById('ticker-content');
    if (!el) return;
    if (!battles.length) {
      // Use configured game name in welcome ticker
      try {
        const stRes = await apiFetch('/api/game/status');
        const st = stRes ? await stRes.json() : {};
        el.textContent = `Welcome to ${st.game_name || 'AstroWebEngine'}`;
      } catch (_) {
        el.textContent = t('ticker.welcome');
      }
      return;
    }
    const ticker = battles.slice(0, 5).map(b => {
      const r = b.report;
      return t('ticker.vs', r.attacker, r.defender, fmtNum(r.attacker_total_losses || 0), fmtNum(r.defender_total_losses || 0));
    }).join('    ');
    el.textContent = ticker;
  } catch (e) {}
}

async function init() {
  const unEl = document.getElementById('hud-username');
  if (unEl) unEl.textContent = USERNAME;

  if (IS_ADMIN) {
    const adminBtn = document.getElementById('btn-admin');
    const adminSep = document.getElementById('sep-admin');
    if (adminBtn) adminBtn.style.display = 'inline-block';
    if (adminSep) adminSep.style.display = 'inline-block';
    // Tools dropdown's Admin entry (neutral shell)
    document.querySelectorAll('.btn-admin-item').forEach(el => { el.style.display = 'block'; });
  }

  updateServerTime();
  setInterval(updateServerTime, 1000);
  setInterval(updateCountdowns, 1000);
  applyStaticTranslations();

  await updateHUD();
  await checkWinCondition();
  await loadBases();
  await loadGalaxy();
  await renderMyBasesJumpMenu();
  await updateUnreadCount();

  // Restore active tab from before page refresh
  const savedTab = localStorage.getItem('awe_active_tab');
  const savedEmpSub = localStorage.getItem('awe_empire_subtab');
  if (savedEmpSub) _empireSubtab = savedEmpSub;
  if (savedTab && savedTab !== 'bases') {
    switchTab(savedTab);
  }
  await loadNewsTicker();
  await checkChangelog();

  setInterval(updateHUD, 10000);
  setInterval(checkWinCondition, 30000);
  setInterval(updateUnreadCount, 20000);
  setInterval(loadNewsTicker, 60000);
  // Gentle background refresh every 30s â€” skip when user is typing in production inputs
  setInterval(() => {
    if (_empProdInteracting || (typeof _baseProdInteracting !== 'undefined' && _baseProdInteracting)) return;
    const a = document.querySelector('.tab-panel.active');
    if (!a) return;
    const t = a.id.replace('tab-', '');
    if (t === 'bases' && typeof loadBases === 'function') loadBases();
    else if (t === 'empire' && typeof loadEmpireTab === 'function' && !['reports','credits','technologies'].includes(_empireSubtab)) loadEmpireTab();
    else if (t === 'fleets' && typeof loadFleets === 'function') loadFleets();
    else if (t === 'research' && typeof loadResearch === 'function') loadResearch();
  }, 30000);
  // Fleets need a faster refresh so moving/auto-scouting fleets don't look stuck.
  setInterval(() => {
    const a = document.querySelector('.tab-panel.active');
    if (!a || a.id !== 'tab-fleets' || typeof loadFleets !== 'function') return;
    const activeEl = document.activeElement;
    const editing = activeEl && ['INPUT', 'TEXTAREA', 'SELECT'].includes(activeEl.tagName);
    if (editing || _empProdInteracting || (typeof _baseProdInteracting !== 'undefined' && _baseProdInteracting)) return;
    loadFleets();
  }, 5000);

  // Start event polling (slow fallback) + WebSocket for real-time events
  if (typeof startEventPolling === 'function') startEventPolling();
  if (typeof connectWebSocket === 'function') connectWebSocket();
}

// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
// TUTORIAL TAB (in-game)
// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

let _tutorialData = null;
let _tutCurrentStep = 0;

async function loadTutorialTab() {
  try {
    const res = await apiFetch('/api/tutorial/progress');
    if (!res) return;
    _tutorialData = await res.json();
    _tutCurrentStep = _tutorialData.current_step || 0;
    renderTutNav();
    renderTutStep(_tutCurrentStep);
  } catch (e) {
    console.error('loadTutorialTab error:', e);
    document.getElementById('tut-content').innerHTML =
      '<div class="text-dim" style="padding:20px;">Tutorial not available. Complete galaxy selection first.</div>';
  }
}

function renderTutNav() {
  const nav = document.getElementById('tut-nav');
  if (!nav || !_tutorialData) return;
  nav.innerHTML = _tutorialData.steps.map((s, i) => {
    const isActive = i === _tutCurrentStep;
    const isDone = s.is_completed;
    return `<div class="tut-nav-item ${isActive ? 'active' : ''} ${isDone ? 'completed' : ''}"
                 onclick="tutViewStep(${i})">
      <span class="tut-check ${isDone ? 'done' : 'pending'}">${isDone ? '&#10003;' : '&#9744;'}</span>
      <span>${escStr(s.title)}</span>
    </div>`;
  }).join('');
}

function tutViewStep(index) {
  _tutCurrentStep = index;
  renderTutNav();
  renderTutStep(index);
}

function renderTutStep(index) {
  if (!_tutorialData) return;
  const step = _tutorialData.steps[index];
  if (!step) return;
  const content = document.getElementById('tut-content');

  let html = `<h2>${escStr(step.title)}</h2>`;
  html += `<div class="tut-desc">${escStr(step.description)}</div>`;

  // Mission box
  if (step.mission) {
    const m = step.mission;
    const isDone = m.progress && m.progress.done;
    const progressText = m.progress ? `(${m.progress.current}/${m.progress.target})` : '';
    html += `<div class="tut-mission-box"><h4>Mission:</h4>`;
    html += `<div class="tut-mission-text ${isDone ? 'completed-text' : ''}">`;
    html += `&#8226; ${escStr(m.text)}`;
    if (isDone) html += ` <span class="tut-completed-tag">(Completed)</span>`;
    else html += ` <span class="tut-mission-progress">${progressText}</span>`;
    html += `</div>`;

    if (step.requirements && step.requirements.length > 0) {
      html += `<div class="tut-requirements"><h4>Requirements:</h4>`;
      step.requirements.forEach(r => {
        const icon = r.met ? '<span style="color:var(--success);">âœ“</span>' : '<span style="color:var(--danger);">âœ—</span>';
        const style = r.met ? 'color:var(--success);' : '';
        const progress = r.target ? ` <span class="text-dim">(${r.current}/${r.target})</span>` : '';
        html += `<div class="tut-req-item">${icon} <span style="${style}">${escStr(r.text)}</span>${progress}</div>`;
      });
      html += `</div>`;
    }
    html += `</div>`;
  }

  // Reward
  if (step.reward > 0) {
    html += `<div class="tut-reward-box"><h4>Reward:</h4>`;
    html += `<div class="tut-reward-amount">&#8226; ${step.reward} Credits</div>`;
    if (step.is_completed && !step.is_collected) {
      html += `<button class="tut-collect-btn" onclick="tutCollectReward(${index})">Collect ${step.reward} Credits</button>`;
    } else if (step.is_collected) {
      html += `<div style="color:var(--success);font-size:11px;margin-top:4px;">&#10003; Collected</div>`;
    }
    html += `</div>`;
  }

  // Actions
  html += `<div class="tut-actions">`;
  if (index === 0 && !step.is_completed) {
    html += `<button class="tut-start-btn" onclick="tutStart()">Start the Tutorial</button>`;
  } else if (step.id === 'end_tutorial') {
    html += `<button class="tut-finish-btn" onclick="tutFinish()">Complete Tutorial</button>`;
  } else if (!step.is_completed && step.mission) {
    html += `<button class="btn btn-primary" id="tut-check-btn" onclick="tutCheckStep(${index})">Check Mission</button>`;
    html += `<div style="font-size:11px;color:var(--text-dim);margin-top:6px;">Complete the mission in-game, then click Check Mission.</div>`;
  } else if (step.is_completed && step.is_collected && index < _tutorialData.steps.length - 1) {
    html += `<button class="btn btn-ghost" onclick="tutViewStep(${index + 1})">Next Step &#8594;</button>`;
  }
  html += `</div>`;

  content.innerHTML = html;
}

async function tutStart() {
  try {
    const res = await apiFetch('/api/tutorial/advance', { method: 'POST' });
    if (res && res.ok) await loadTutorialTab();
  } catch (e) { console.error(e); }
}

async function tutCheckStep(index) {
  try {
    const res = await apiFetch(`/api/tutorial/check/${index}`, { method: 'POST' });
    if (!res) return;
    const data = await res.json();
    if (data.completed) {
      await loadTutorialTab();
      tutViewStep(index);
    } else {
      const btn = document.getElementById('tut-check-btn');
      if (btn) {
        btn.textContent = 'Not completed yet...';
        btn.style.opacity = '0.6';
        setTimeout(() => { btn.textContent = 'Check Mission'; btn.style.opacity = '1'; }, 1500);
      }
    }
  } catch (e) { console.error(e); }
}

async function tutCollectReward(index) {
  try {
    const res = await apiFetch(`/api/tutorial/collect/${index}`, { method: 'POST' });
    if (!res || !res.ok) return;
    await loadTutorialTab();
    const nextStep = index + 1;
    if (nextStep < _tutorialData.steps.length) tutViewStep(nextStep);
    // Refresh HUD to show updated credits
    if (typeof updateHUD === 'function') updateHUD();
  } catch (e) { console.error(e); }
}

async function tutFinish() {
  try {
    await apiFetch('/api/tutorial/finish', { method: 'POST' });
    showSnack('Tutorial completed!');
    switchTab('bases');
  } catch (e) { switchTab('bases'); }
}

async function skipTutorialInGame() {
  if (!confirm('Skip the tutorial? You won\'t earn remaining tutorial rewards.')) return;
  try {
    await apiFetch('/api/tutorial/skip', { method: 'POST' });
    showSnack('Tutorial skipped');
    switchTab('bases');
  } catch (e) { switchTab('bases'); }
}

// ============================================================
// ============================================================
// COMMANDERS TAB
// ============================================================

let _commanderData = null;
let _showRecruitPanel = false;

let _commanderRefreshTimer = null;
// Commanders moved to social_commanders.js.

// Scanner hub moved to social_scanners.js.

// Report loaders moved to social_reports.js.

// ============================================================
// CREDIT HISTORY (click on Credits in HUD)
// ============================================================

async function loadCreditHistory() {
  // Switch to empire tab and render credit history
  if (typeof updateHUD === 'function') {
    try { await updateHUD(); } catch (_) {}
  }
  _empireSubtab = 'credits';
  localStorage.setItem('awe_empire_subtab', 'credits');
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  const panel = document.getElementById('tab-empire');
  if (panel) panel.classList.add('active');
  document.querySelectorAll('.awe-nav-btn').forEach(b => b.classList.remove('active'));
  const empBtn = document.querySelector('.awe-nav-btn[data-tab="empire"]');
  if (empBtn) empBtn.classList.add('active');
  document.querySelectorAll('.mobile-nav-btn').forEach(b => b.classList.remove('active'));
  const mobileEmpBtn = document.querySelector('.mobile-nav-btn[data-tab="empire"]');
  if (mobileEmpBtn) mobileEmpBtn.classList.add('active');
  document.querySelectorAll('#empire-tab-row1 a, #empire-tab-row2 a').forEach(a => a.classList.remove('active'));

  const container = document.getElementById('empire-content');
  if (!container) return;
  container.innerHTML = '<div class="loading">Loading credit history...</div>';

  try {
    const res = await apiFetch('/api/credits/history');
    if (!res) return;
    const data = await res.json();

    // Keep the header balance in sync even if the normal HUD refresh was stale.
    const credEl = document.getElementById('hud-credits');
    const credSuffix = document.getElementById('hud-credits-suffix');
    if (credEl && typeof data.current_balance === 'number' && getResourceModel() !== 'multi') {
      credEl.textContent = fmtNum(data.current_balance);
      if (credSuffix) credSuffix.style.display = '';
    }

    let html = '<h3>Credits History</h3>';

    // 24h summary
    const s = data.summary_24h || {};
    const cats = Object.keys(s);
    if (cats.length > 0) {
      html += '<div class="card mb-12" style="padding:8px 12px"><b>Last 24 Hours:</b><br>';
      const catLabels = { income: 'Income', construction: 'Construction', production: 'Production', research: 'Research', trade: 'Trade', combat: 'Combat', admin: 'Admin', other: 'Other' };
      for (const cat of cats) {
        const val = s[cat];
        const sign = val >= 0 ? '+' : '';
        const color = val >= 0 ? 'var(--clr-pos, #4f4)' : 'var(--clr-neg, #f44)';
        html += `<span style="margin-right:12px">${catLabels[cat] || cat}: <span style="color:${color}">${sign}${val.toLocaleString(undefined, {minimumFractionDigits:1, maximumFractionDigits:1})}</span></span>`;
      }
      html += '</div>';
    }

    // Ledger table
    const entries = data.entries || [];
    if (entries.length === 0) {
      html += '<div class="empty-state"><p>No credit history yet.</p></div>';
    } else {
      html += '<table class="data-table"><thead><tr><th>Date</th><th>Description</th><th>Credits</th><th>Balance</th></tr></thead><tbody>';
      for (const e of entries) {
        const dateStr = fmtDateTime(e.date);
        const sign = e.amount >= 0 ? '+' : '';
        const color = e.amount >= 0 ? 'var(--clr-pos, #4f4)' : 'var(--clr-neg, #f44)';
        html += `<tr>
          <td class="text-dim" style="white-space:nowrap">${dateStr}</td>
          <td>${escStr(e.description)}</td>
          <td style="color:${color};text-align:right">${sign}${e.amount.toLocaleString(undefined, {minimumFractionDigits:1, maximumFractionDigits:1})}</td>
          <td style="text-align:right">${e.balance.toLocaleString(undefined, {minimumFractionDigits:1, maximumFractionDigits:1})}</td>
        </tr>`;
      }
      html += '</tbody></table>';
    }

    container.innerHTML = html;
  } catch (e) {
    console.error(e);
    container.innerHTML = '<div class="empty-state"><p>Error loading credit history.</p></div>';
  }
}

// â•â•â•â•â•â•â•â•â•â• CHANGELOG POPUP â•â•â•â•â•â•â•â•â•â•
async function checkChangelog() {
  try {
    const res = await apiFetch('/api/changelogs/unseen');
    if (!res) return;
    const entries = await res.json();
    if (!entries || !entries.length) return;
    renderChangelogEntries(entries);
    document.getElementById('changelog-modal').style.display = 'flex';
  } catch (e) { console.error('Changelog check failed:', e); }
}

function renderChangelogEntries(entries) {
  const body = document.getElementById('changelog-modal-body');
  let html = '';
  for (const e of entries) {
    const lines = (e.body || '').split('\n').filter(l => l.trim());
    const bodyHtml = lines.map(l => `<div style="margin:2px 0;font-size:12px;color:var(--text);">${escStr(l)}</div>`).join('');
    html += `<div style="margin-bottom:14px;padding-bottom:14px;border-bottom:1px solid var(--border);">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
        <div>
          ${e.version ? `<span class="badge" style="background:var(--accent);color:#fff;margin-right:6px;font-size:10px;padding:2px 6px;border-radius:3px;">${escStr(e.version)}</span>` : ''}
          <strong style="color:var(--text-bright);">${escStr(e.title)}</strong>
        </div>
        <span class="text-dim" style="font-size:10px;">${new Date(e.created_at).toLocaleDateString()}</span>
      </div>
      ${bodyHtml}
    </div>`;
  }
  body.innerHTML = html;
}

function closeChangelogModal() {
  document.getElementById('changelog-modal').style.display = 'none';
  apiFetch('/api/changelogs/mark-seen', { method: 'POST' });
}

async function showFullChangelog() {
  try {
    const res = await apiFetch('/api/changelogs');
    if (!res) return;
    const entries = await res.json();
    if (!entries || !entries.length) {
      document.getElementById('changelog-modal-body').innerHTML = '<div class="text-dim">No changelog entries yet.</div>';
      return;
    }
    renderChangelogEntries(entries);
  } catch (e) { console.error(e); }
}

if (typeof applyStoredDisplayWidth === 'function') applyStoredDisplayWidth();
if (typeof applyStoredAccountCheckboxes === 'function') applyStoredAccountCheckboxes();
init();



