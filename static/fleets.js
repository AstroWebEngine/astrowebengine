/* â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
   AstroWebEngine â€” Frontend (fleets.js)
   Research, ship building, fleets, split/merge,
   recall, attack, recycling, fleet rename,
   fleet detail view with sub-tabs, bookmarks
   â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â• */

// ============================================================
// RESEARCH TAB
// ============================================================

async function loadResearch() {
  _playerTechLevels = null;  // invalidate tech cache
  try {
    const res = await apiFetch('/api/research');
    if (!res) return;
    const techs = await res.json();
    renderResearch(techs);
  } catch (e) { console.error(e); }
}

function renderResearch(techs) {
  const container = document.getElementById('research-container');
  container.innerHTML = '<p class="text-dim" style="font-size:11px;margin-bottom:8px;">Research is per-base. Use a base\'s Research subtab to queue research.</p>' +
  techs.map(tech => {
    const locked = !tech.prereqs_met || !tech.lab_met;
    const hasQueued = tech.effective_level > tech.level;
    const queuedStr = hasQueued ? ` <span class="text-warn">\u2192${tech.effective_level}</span>` : '';
    let statusHtml = '';
    if (tech.is_researching && tech.research_end) {
      const remaining = Math.max(0, (serverDate(tech.research_end) - Date.now()) / 1000);
      statusHtml = `<div class="text-success countdown" data-end="${tech.research_end}" style="font-size:11px;">${t('btn.research')}... ${fmtTime(remaining)}</div>`;
    }
    if (locked) {
      let reasons = [];
      if (!tech.prereqs_met && tech.prereq_text) reasons.push(`${t('general.required')}: ${tech.prereq_text}`);
      if (!tech.lab_met) reasons.push(`${t('general.required')}: Lab Lv${tech.lab_req}`);
      statusHtml += `<div class="text-danger" style="font-size:10px;">${reasons.join(' Â· ')}</div>`;
    }
    return `<div class="research-card ${locked ? 'locked' : ''}">
      <div style="display:flex;align-items:center;gap:8px;">
        <span style="font-size:20px;">${tech.icon}</span>
        <div>
          <div class="text-bright">${escStr(tName(tech.name))} <span class="text-accent">Lv${tech.level}</span>${queuedStr}</div>
          <div class="text-dim" style="font-size:10px;">${escStr(tech.bonus)}</div>
        </div>
      </div>
      <div style="margin-top:6px;">${statusHtml}</div>
    </div>`;
  }).join('');
}

// ============================================================
// FLEETS TAB â€” with build cost preview
// ============================================================

let _shipSpecs = null;
async function getShipSpecs() {
  if (_shipSpecs) return _shipSpecs;
  try {
    if (typeof getCatalogSpecs === 'function') {
      const [ships, goods] = await Promise.all([
        getCatalogSpecs('ships'),
        getCatalogSpecs('goods'),
      ]);
      _shipSpecs = { ...(goods || {}), ...(ships || {}) };
    } else {
      const res = await apiFetch('/api/ship-specs');
      if (res) _shipSpecs = await res.json();
    }
  } catch (e) {}
  return _shipSpecs || {};
}

// â”€â”€ State â”€â”€
let _allFleets = [];
// _allBases declared in bases.js (loaded first)
let _allBookmarks = [];
let _openFleetId = null;    // currently open fleet detail, null = list view
let _activeFleetTab = 'overview';  // overview | move | build_base | attack | piracy

async function loadFleets() {
  try {
    const [fleetsRes, basesRes, bmRes] = await Promise.all([
      apiFetch('/api/fleets'),
      apiFetch('/api/bases'),
      apiFetch('/api/bookmarks')
    ]);
    if (!fleetsRes || !basesRes) return;
    _allFleets = await fleetsRes.json();
    _allBases = await basesRes.json();
    _allBookmarks = bmRes ? await bmRes.json() : [];
    const specs = await getShipSpecs();

    if (_openFleetId) {
      const fleet = _allFleets.find(f => f.id === _openFleetId);
      if (fleet) { renderFleetDetail(fleet, specs); }
      else { _openFleetId = null; renderFleetList(_allFleets, specs); }
    } else {
      renderFleetList(_allFleets, specs);
    }
    loadShipQueue();
  } catch (e) { console.error(e); }
}

// ============================================================
// FLEET LIST VIEW â€” flat table
// ============================================================

// Ship type abbreviations
const _shipAbbrev = {
  small_ship_1:'s1', small_ship_2:'s2', small_ship_3:'s3', small_ship_4:'s4',
  small_ship_5:'s5', small_ship_6:'s6', small_ship_7:'s7', small_ship_8:'s8',
  medium_ship_1:'m1', medium_ship_2:'m2', medium_ship_3:'m3',
  medium_ship_4:'m4', medium_ship_5:'m5', medium_ship_6:'m6',
  large_ship_1:'l1', large_ship_2:'l2', large_ship_3:'l3', large_ship_4:'l4',
  capital_ship_1:'c1', capital_ship_2:'c2'
};

function _fleetShipAbbrevs(ships, specs) {
  return Object.entries(ships).filter(([_, c]) => c > 0)
    .map(([t, _]) => _shipAbbrev[t] || (specs[t]?.name || t).substring(0, 2).toLowerCase())
    .join(' ');
}

function renderFleetList(fleets, specs) {
  const container = document.getElementById('fleets-container');
  if (!fleets.length) {
    container.innerHTML = `<div class="empty-state"><p>${t('fleet.noFleets')}</p></div>`;
    return;
  }

  let rows = '';
  for (const f of fleets) {
    const nameDisplay = `<a href="#" class="text-bright" style="text-decoration:none;" onclick="event.preventDefault();openFleetDetail(${f.id})">${escStr(f.name)}</a>`;

    // Location column
    let locHtml = '';
    if (f.location_coords) {
      const locName = f.location_name || f.base_name || '';
      locHtml = locName ? `${escStr(locName)} (${coordLink(f.location_coords)})` : `(${coordLink(f.location_coords)})`;
    } else {
      locHtml = escStr(f.location_name || f.base_name || '?');
    }

    // Destination + Arrival columns
    let destHtml = '', arrivalHtml = '';
    if (f.is_moving) {
      destHtml = f.destination_coords ? `(${coordLink(f.destination_coords)})` : escStr(f.destination_name || '');
      const remaining = f.arrival_time ? Math.max(0, (serverDate(f.arrival_time) - Date.now()) / 1000) : 0;
      arrivalHtml = `<span class="countdown" data-end="${f.arrival_time}">${fmtTime(remaining)}</span>`;
    }

    const sizeVal = fmtNum(f.value);
    const commentEdit = `<a href="#" class="text-dim" style="font-size:11px;text-decoration:none;" onclick="event.preventDefault();openFleetRenameModal(${f.id},'${escAttr(f.name)}')">Edit</a>`;

    rows += `<tr style="cursor:pointer;" onclick="openFleetDetail(${f.id})">
      <td style="white-space:nowrap;">${nameDisplay}</td>
      <td>${locHtml}</td>
      <td class="mobile-hide">${destHtml}</td>
      <td style="text-align:center;">${arrivalHtml}</td>
      <td style="text-align:right;" class="font-mono">${sizeVal}</td>
      <td style="text-align:center;white-space:nowrap;" class="mobile-hide" onclick="event.stopPropagation();">${commentEdit}</td>
    </tr>`;
  }

  const reorderLink = fleets.length >= 2 ? `<div style="text-align:center;font-size:11px;margin-bottom:4px;"><a href="#" onclick="openFleetReorderModal();return false;">Change fleet order</a></div>` : '';
  container.innerHTML = `
    <div style="text-align:center;font-size:14px;margin-bottom:8px;color:var(--text-bright);"><b>${t('nav.fleets').charAt(0)}</b>${t('nav.fleets').slice(1)}</div>
    ${reorderLink}
    <table class="data-table" style="width:100%;font-size:12px;">
      <thead><tr>
        <th style="text-align:left;">${t('nav.fleets')}</th>
        <th style="text-align:left;">${t('fleet.location')}</th>
        <th style="text-align:left;" class="mobile-hide">${t('fleet.destination')}</th>
        <th style="text-align:center;">${t('fleet.arriving')}</th>
        <th style="text-align:right;">${t('fleet.size')}</th>
        <th style="text-align:center;" class="mobile-hide"></th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

// ============================================================
// FLEET REORDER
// ============================================================

function openFleetReorderModal() {
  if (!_allFleets || _allFleets.length < 2) { showSnack('Need at least 2 fleets'); return; }
  let html = '<div style="font-size:12px;margin-bottom:8px;">Use arrows to reorder:</div>';
  html += '<div id="fleet-reorder-list">';
  for (const f of _allFleets) {
    html += `<div class="reorder-item" data-id="${f.id}" style="display:flex;justify-content:space-between;align-items:center;padding:4px 8px;margin:2px 0;border:1px solid var(--border);background:var(--bg-panel);font-size:12px;">
      <span>${escStr(f.name)}</span>
      <span>
        <button class="btn btn-ghost btn-sm" onclick="fleetReorderMove(${f.id},-1)" style="padding:0 6px;">&uarr;</button>
        <button class="btn btn-ghost btn-sm" onclick="fleetReorderMove(${f.id},1)" style="padding:0 6px;">&darr;</button>
      </span>
    </div>`;
  }
  html += '</div><div style="margin-top:8px;text-align:right;"><button class="btn btn-primary btn-sm" onclick="doFleetReorder()">Save Order</button></div>';
  document.getElementById('generic-modal-title').textContent = 'Change Fleet Order';
  document.getElementById('generic-modal-body').innerHTML = html;
  openModal('generic-modal');
}

function fleetReorderMove(fleetId, direction) {
  const list = document.getElementById('fleet-reorder-list');
  const items = [...list.querySelectorAll('.reorder-item')];
  const idx = items.findIndex(el => parseInt(el.dataset.id) === fleetId);
  if (idx < 0) return;
  const newIdx = idx + direction;
  if (newIdx < 0 || newIdx >= items.length) return;
  if (direction < 0) list.insertBefore(items[idx], items[newIdx]);
  else list.insertBefore(items[newIdx], items[idx]);
}

async function doFleetReorder() {
  const items = [...document.querySelectorAll('#fleet-reorder-list .reorder-item')];
  const fleet_ids = items.map(el => parseInt(el.dataset.id));
  try {
    const res = await apiFetch('/api/fleets/reorder', { method: 'POST', body: JSON.stringify({ fleet_ids }) });
    const data = await res.json();
    if (data.success) { closeModal('generic-modal'); showSnack('Fleet order saved'); loadFleets(); }
    else showSnack(data.detail || 'Failed');
  } catch (e) { showSnack('Error saving order'); }
}

// ============================================================
// FLEET DETAIL VIEW â€” with sub-tabs
// ============================================================

// Fleet detail shell moved to fleets_detail.js.

// Fleet move flow moved to fleets_move.js.

// Fleet build-base flow moved to fleets_build.js.

async function disbandFleet(fleetId) {
  if (!confirm('Disband this fleet? All ships will be lost.')) return;
  try {
    const res = await apiFetch('/api/fleets/disband', {
      method: 'POST', body: JSON.stringify({ fleet_id: fleetId })
    });
    const data = await res.json();
    if (data.success) {
      showSnack('Fleet disbanded');
      _openFleetId = null;
      await loadFleets();
    } else showSnack(data.detail || 'Disband failed');
  } catch (e) { console.error(e); }
}

async function repairFleet(fleetId) {
  try {
    const res = await apiFetch('/api/fleets/repair', {
      method: 'POST', body: JSON.stringify({ fleet_id: fleetId })
    });
    const data = await res.json();
    if (data.success) {
      showSnack(data.message || 'Fleet repaired');
      await loadFleets();
      if (_openFleetId === fleetId) {
        const fleet = _allFleets.find(f => f.id === fleetId);
        if (fleet) renderFleetDetail(fleet, _shipSpecs || {});
      }
    } else showSnack(data.detail || 'Repair failed');
  } catch (e) { console.error(e); }
}

// â”€â”€ Bookmarks â”€â”€
async function addBookmarkFromCoords() {
  const name = document.getElementById('bm-name')?.value.trim();
  const coords = document.getElementById('move-dest-coords')?.value.trim();
  if (!name || !coords) { showSnack('Enter a name and destination coords first'); return; }
  try {
    // Need to resolve coords to planet_id first
    const estRes = await apiFetch(`/api/fleets/${_openFleetId}/estimate?coords=${encodeURIComponent(coords)}`);
    if (!estRes) return;
    const estData = await estRes.json();
    if (estData.detail) { showSnack(estData.detail); return; }
    // We need planet_id â€” let's look it up. The estimate doesn't return it, so we'll
    // search for the planet by name. Use a simple approach: post bookmark with coords as name
    // Actually, we need the planet_id. Let's add it to the estimate response or do a separate lookup.
    // For now, use a workaround: post coords and let backend resolve
    const res = await apiFetch('/api/bookmarks/by-coords', {
      method: 'POST',
      body: JSON.stringify({ name, coords })
    });
    if (!res) return;
    const data = await res.json();
    if (data.id) {
      showSnack('Bookmark added');
      _allBookmarks.push(data);
      const fleet = _allFleets.find(f => f.id === _openFleetId);
      if (fleet) renderFleetDetail(fleet, _shipSpecs || {});
    } else {
      showSnack(data.detail || 'Failed to add bookmark');
    }
  } catch (e) { console.error(e); }
}

async function deleteBookmark(bmId) {
  try {
    const res = await apiFetch(`/api/bookmarks/${bmId}`, { method: 'DELETE' });
    const data = await res.json();
    if (data.success) {
      _allBookmarks = _allBookmarks.filter(b => b.id !== bmId);
      showSnack('Bookmark removed');
      const fleet = _allFleets.find(f => f.id === _openFleetId);
      if (fleet) renderFleetDetail(fleet, _shipSpecs || {});
    }
  } catch (e) { console.error(e); }
}

// â”€â”€ Roman numeral helper â”€â”€
function toRoman(num) {
  const vals = [1000,900,500,400,100,90,50,40,10,9,5,4,1];
  const syms = ['M','CM','D','CD','C','XC','L','XL','X','IX','V','IV','I'];
  let result = '';
  for (let i = 0; i < vals.length; i++) {
    while (num >= vals[i]) { result += syms[i]; num -= vals[i]; }
  }
  return result;
}

// ============================================================
// SHIP SPECS MODAL
// ============================================================

async function openShipSpecsModal() {
  await switchTablesTab('ships');
  openModal('ship-specs-modal');
}

async function switchTablesTab(tab, btn) {
  // Update tab button active state
  const tabBar = document.querySelector('#ship-specs-modal .modal > div:nth-child(2)');
  if (tabBar) tabBar.querySelectorAll('.awe-nav-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  else if (tabBar) {
    const labels = {ships:0,defenses:1,buildings:2,research:3,commanders:4,mechanics:5};
    const idx = labels[tab] ?? 0;
    const buttons = tabBar.querySelectorAll('.awe-nav-btn');
    if (buttons[idx]) buttons[idx].classList.add('active');
  }

  const el = document.getElementById('ship-specs-content');
  el.innerHTML = '<p class="text-dim">Loading...</p>';

  if (tab === 'ships') {
    const specs = await getShipSpecs();
    let html = '<table class="data-table" style="font-size:11px;"><thead><tr>' +
      '<th>Ship</th><th>Cost</th><th>Atk</th><th>Arm</th><th>Shd</th><th>Spd</th><th>SY</th><th>Hng</th><th>Requirements</th>' +
      '</tr></thead><tbody>';
    for (const [key, s] of Object.entries(specs)) {
      if (s.is_goods) continue;
      const reqs = Object.entries(s.req || {}).map(([t, l]) => `${t} ${l}`).join(', ');
      const hangarNote = s.hangar < 0 ? `<span class="text-warn">${s.hangar}</span>` : (s.hangar > 0 ? `<span class="text-success">+${s.hangar}</span>` : '0');
      html += `<tr>
        <td class="text-bright">${tName(s.name)}</td>
        <td class="text-warn font-mono">${formatResourceCost(s.cost)}</td>
        <td class="font-mono">${s.attack||0}</td>
        <td class="font-mono">${s.armour||0}</td>
        <td class="font-mono">${s.shield||0}</td>
        <td class="font-mono">${s.speed||0}</td>
        <td class="font-mono">${s.shipyard||0}</td>
        <td>${hangarNote}</td>
        <td class="text-dim" style="font-size:10px;">${reqs || 'none'}</td>
      </tr>`;
    }
    html += '</tbody></table>';
    el.innerHTML = html;

  } else if (tab === 'defenses') {
    try {
      const specs = typeof getCatalogSpecs === 'function'
        ? await getCatalogSpecs('defenses')
        : await (await apiFetch('/api/defense-specs')).json();
      let html = '<table class="data-table" style="font-size:11px;"><thead><tr>' +
        '<th>Defense</th><th>Cost</th><th>Atk</th><th>Arm</th><th>Shd</th><th>Weapon</th><th>Requirements</th>' +
        '</tr></thead><tbody>';
      for (const [key, s] of Object.entries(specs)) {
        const reqs = Object.entries(s.req || {}).map(([t, l]) => `${t} ${l}`).join(', ');
        html += `<tr>
          <td class="text-bright">${tName(s.name)}</td>
          <td class="text-warn font-mono">${formatResourceCost(s.cost)}</td>
          <td class="font-mono">${s.attack||0}</td>
          <td class="font-mono">${s.armour||0}</td>
          <td class="font-mono">${s.shield||0}</td>
          <td class="font-mono">${s.weapon||'-'}</td>
          <td class="text-dim" style="font-size:10px;">${reqs || 'none'}</td>
        </tr>`;
      }
      html += '</tbody></table>';
      el.innerHTML = html;
    } catch(e) { el.innerHTML = '<p class="text-warn">Failed to load defense specs</p>'; }

  } else if (tab === 'buildings') {
    try {
      const specs = typeof getCatalogSpecs === 'function'
        ? await getCatalogSpecs('buildings')
        : await (await apiFetch('/api/building-specs')).json();
      let html = '<table class="data-table" style="font-size:11px;"><thead><tr>' +
        '<th>Building</th><th>Type</th><th>Base Cost</th><th>Energy</th><th>Pop</th><th>Area</th><th>Max Lv</th><th>Description</th><th>Requirements</th>' +
        '</tr></thead><tbody>';
      for (const [key, s] of Object.entries(specs)) {
        const reqs = Object.entries(s.tech_req || {}).map(([t, l]) => `${t} ${l}`).join(', ');
        const btype = s.advanced ? '<span class="text-accent">Advanced</span>' : 'Basic';
        html += `<tr>
          <td class="text-bright">${tName(s.name)}</td>
          <td>${btype}</td>
          <td class="text-warn font-mono">${formatResourceCost(s.base_cost)}</td>
          <td class="font-mono">${s.energy_req||0}</td>
          <td class="font-mono">${s.pop_req||0}</td>
          <td class="font-mono">${s.area_req||0}</td>
          <td class="font-mono">${s.max_level > 0 ? s.max_level : 'âˆž'}</td>
          <td class="text-dim" style="font-size:10px;">${s.desc||''}</td>
          <td class="text-dim" style="font-size:10px;">${reqs || 'none'}</td>
        </tr>`;
      }
      html += '</tbody></table>';
      el.innerHTML = html;
    } catch(e) { el.innerHTML = '<p class="text-warn">Failed to load building specs</p>'; }

  } else if (tab === 'research') {
    try {
      const specs = typeof getCatalogSpecs === 'function'
        ? await getCatalogSpecs('research')
        : await (await apiFetch('/api/research-specs')).json();
      let html = '<table class="data-table" style="font-size:11px;"><thead><tr>' +
        '<th>Technology</th><th>Base Cost</th><th>Lab Req</th><th>Bonus</th><th>Prerequisites</th>' +
        '</tr></thead><tbody>';
      for (const [key, s] of Object.entries(specs)) {
        const prereqs = Object.entries(s.prereqs || {}).map(([t, l]) => `${t} ${l}`).join(', ');
        html += `<tr>
          <td class="text-bright">${s.icon||''} ${tName(s.name)}</td>
          <td class="text-warn font-mono">${formatResourceCost(s.base_cost)}</td>
          <td class="font-mono">${s.lab_req||0}</td>
          <td class="text-dim" style="font-size:10px;">${s.bonus||''}</td>
          <td class="text-dim" style="font-size:10px;">${prereqs || 'none'}</td>
        </tr>`;
      }
      html += '</tbody></table>';
      el.innerHTML = html;
    } catch(e) { el.innerHTML = '<p class="text-warn">Failed to load research specs</p>'; }

  } else if (tab === 'commanders') {
    try {
      let html = '<p class="text-dim" style="font-size:11px;margin-bottom:8px;">Commanders are special officers that provide bonuses when assigned to a base. Each skill type provides a unique benefit that scales with the commander\'s level.</p>';
      html += '<table class="data-table" style="font-size:11px;"><thead><tr>' +
        '<th>Skill Type</th><th>Bonus</th><th>Scope</th><th>What It Does</th>' +
        '</tr></thead><tbody>';
      const cmdrData = Object.values(
        typeof getCatalogSpecs === 'function' ? await getCatalogSpecs('commanders') : {}
      );
      for (const c of cmdrData) {
        const bonus = c.bonus_per_level != null ? `${Math.round(c.bonus_per_level * 100)}%/lv` : '-';
        html += `<tr><td class="text-bright">${c.name}</td><td class="font-mono text-warn">${bonus}</td><td class="text-dim">${c.scope || '-'}</td><td class="text-dim">${c.desc || ''}</td></tr>`;
      }
      html += '</tbody></table>';
      html += '<div style="margin-top:12px;"><div class="text-accent" style="font-size:12px;font-weight:700;margin-bottom:4px;">Commander Rules</div>';
      html += '<table class="data-table" style="font-size:11px;"><tbody>';
      html += '<tr><td class="text-bright" style="white-space:nowrap;">Recruit Cost</td><td class="text-dim">20 XP or 40 credits</td></tr>';
      html += '<tr><td class="text-bright" style="white-space:nowrap;">Capacity</td><td class="text-dim">Computer tech level = max commanders</td></tr>';
      html += '<tr><td class="text-bright" style="white-space:nowrap;">Training Time</td><td class="text-dim">1 hour per target level (max 8 hours)</td></tr>';
      html += '<tr><td class="text-bright" style="white-space:nowrap;">Training Cost</td><td class="text-dim">20 x 1.5^level XP (or 2x credits up to level 8)</td></tr>';
      html += '<tr><td class="text-bright" style="white-space:nowrap;">Max Level</td><td class="text-dim">20</td></tr>';
      html += '<tr><td class="text-bright" style="white-space:nowrap;">XP Only Above</td><td class="text-dim">Level 8+ requires XP (no credit training)</td></tr>';
      html += '<tr><td class="text-bright" style="white-space:nowrap;">XP Gain</td><td class="text-dim">Earned from combat, spent on commander upgrades</td></tr>';
      html += '<tr><td class="text-bright" style="white-space:nowrap;">Assignment</td><td class="text-dim">1 commander per base</td></tr>';
      html += '</tbody></table></div>';
      el.innerHTML = html;
    } catch(e) { el.innerHTML = '<p class="text-warn">Failed to load commander info</p>'; }

  } else if (tab === 'mechanics') {
    try {
      const res = await apiFetch('/api/game-mechanics');
      const data = await res.json();
      let html = '';
      const sectionNames = {combat:'Combat',economy:'Economy & Production',base:'Base Stats',fleet:'Fleet & Movement',other:'Other'};
      for (const [section, items] of Object.entries(data)) {
        html += `<div style="margin-bottom:12px;"><div class="text-accent" style="font-size:12px;font-weight:700;margin-bottom:4px;border-bottom:1px solid var(--border);padding-bottom:2px;">${sectionNames[section]||section}</div>`;
        html += '<table class="data-table" style="font-size:11px;"><tbody>';
        for (const [name, desc] of Object.entries(items)) {
          html += `<tr><td class="text-bright" style="white-space:nowrap;padding-right:16px;">${name}</td><td class="text-dim">${desc}</td></tr>`;
        }
        html += '</tbody></table></div>';
      }
      el.innerHTML = html;
    } catch(e) { el.innerHTML = '<p class="text-warn">Failed to load game mechanics</p>'; }
  }
}

// ============================================================
// BUILD / QUEUE
// ============================================================

// Fleet ship-build queue moved to fleets_build.js.

async function recallFleet(fleetId) {
  try {
    const res = await apiFetch(`/api/fleets/recall?fleet_id=${fleetId}`, { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      showSnack('Fleet recalled');
      await loadFleets();
    }
    else showSnack(data.detail || 'Recall failed');
  } catch (e) { showSnack('Recall failed'); }
}

// Attack submit flow moved to fleets_attack.js.

async function toggleRecycle(fleetId) {
  try {
    const res = await apiFetch(`/api/fleets/recycle?fleet_id=${fleetId}`, { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      showSnack(data.message);
      await loadFleets();
    } else showSnack(data.detail || 'Toggle failed');
  } catch (e) { console.error(e); }
}

// ============================================================
// GUILD FLEET HIDING
// ============================================================

async function guildHideFleet(fleetId) {
  try {
    const res = await apiFetch(`/api/fleets/${fleetId}/guild-hide`, { method: 'POST' });
    const data = await res.json();
    if (data.success) { showSnack('Fleet hidden from guild for 24h'); await loadFleets(); }
    else showSnack(data.detail || 'Failed');
  } catch (e) { console.error(e); }
}

async function guildHideReset(fleetId) {
  try {
    const res = await apiFetch(`/api/fleets/${fleetId}/guild-hide-reset`, { method: 'POST' });
    const data = await res.json();
    if (data.success) { showSnack('Hide timer reset to 24h'); await loadFleets(); }
    else showSnack(data.detail || 'Failed');
  } catch (e) { console.error(e); }
}

async function guildHideCancel(fleetId) {
  try {
    const res = await apiFetch(`/api/fleets/${fleetId}/guild-hide-cancel`, { method: 'POST' });
    const data = await res.json();
    if (data.success) { showSnack('Fleet visible to guild again'); await loadFleets(); }
    else showSnack(data.detail || 'Failed');
  } catch (e) { console.error(e); }
}

// ============================================================
// AUTOSCOUT TOGGLE
// ============================================================

async function toggleAutoscout(fleetId) {
  try {
    const res = await apiFetch(`/api/fleets/${fleetId}/autoscout`, { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      if (data.is_autoscout) {
        showSnack(`Autoscout enabled in galaxy ${data.galaxy}`);
        if (data.scout_fleet_id) {
          _openFleetId = data.scout_fleet_id;
          _activeFleetTab = 'overview';
        }
      } else {
        showSnack('Autoscout disabled');
      }
      await loadFleets();
    } else showSnack(data.detail || 'Failed');
  } catch (e) { console.error(e); }
}

// ============================================================
// FLEET SPLIT (split into N identical fleets)
// ============================================================

async function doSplitFleet(fleetId) {
  const sel = document.getElementById(`split-count-${fleetId}`);
  const splitInto = parseInt(sel?.value) || 2;
  try {
    const res = await apiFetch(`/api/fleets/split?fleet_id=${fleetId}&split_into=${splitInto}`, { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      showSnack(`Fleet split into ${data.split_into} fleets!`);
      _openFleetId = null;  // go back to fleet list to see all new fleets
      await loadFleets();
    } else showSnack(data.detail || 'Split failed');
  } catch (e) { console.error(e); }
}

// ============================================================
// FLEET MERGE
// ============================================================

let _mergeSourceId = null;
async function openMergeModal(fleetId) {
  _mergeSourceId = fleetId;
  try {
    const res = await apiFetch('/api/fleets');
    if (!res) return;
    const fleets = await res.json();
    const source = fleets.find(f => f.id === fleetId);
    if (!source) return;
    const eligible = fleets.filter(f =>
      f.id !== fleetId && !f.is_moving &&
      f.base_id === source.base_id &&
      f.location_planet_id === source.location_planet_id
    );
    const sel = document.getElementById('merge-target-sel');
    if (eligible.length > 0) {
      sel.innerHTML = eligible.map(f =>
        `<option value="${f.id}">${escStr(f.name)} (${fmtNum(f.total_ships)} ships)</option>`
      ).join('');
      document.getElementById('merge-btn').disabled = false;
    } else {
      sel.innerHTML = '<option disabled>No fleets at same location</option>';
      document.getElementById('merge-btn').disabled = true;
    }
    document.getElementById('merge-source-label').textContent = `Merge "${source.name}" into:`;
    document.getElementById('merge-error').style.display = 'none';
    openModal('merge-fleet-modal');
  } catch (e) { console.error(e); }
}

async function doMergeFleets() {
  if (!_mergeSourceId) return;
  const targetId = parseInt(document.getElementById('merge-target-sel').value);
  if (!targetId) return;
  try {
    const res = await apiFetch('/api/fleets/merge', {
      method: 'POST', body: JSON.stringify({ source_fleet_id: _mergeSourceId, target_fleet_id: targetId })
    });
    const data = await res.json();
    if (data.success) { closeModal('merge-fleet-modal'); showSnack('Fleets merged!'); await loadFleets(); }
    else { document.getElementById('merge-error').textContent = data.detail || 'Merge failed'; document.getElementById('merge-error').style.display = 'block'; }
  } catch (e) { console.error(e); }
}

// ============================================================
// FLEET RENAME
// ============================================================

function openFleetRenameModal(fleetId, currentName) {
  document.getElementById('fleet-rename-id').value = fleetId;
  document.getElementById('fleet-rename-input').value = currentName;
  openModal('fleet-rename-modal');
}

async function doRenameFleet() {
  const fleetId = parseInt(document.getElementById('fleet-rename-id').value);
  const name = document.getElementById('fleet-rename-input').value.trim();
  if (!name) return;
  try {
    const res = await apiFetch('/api/fleets/rename', { method: 'POST', body: JSON.stringify({ fleet_id: fleetId, name }) });
    const data = await res.json();
    if (data.success) { closeModal('fleet-rename-modal'); loadFleets(); }
    else showSnack(data.detail || 'Failed');
  } catch (e) {}
}
