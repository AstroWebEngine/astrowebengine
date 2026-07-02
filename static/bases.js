/* ═══════════════════════════════════════════════════
   AstroWebEngine — Frontend (bases.js)
   Bases tab: base detail with sub-tabs
   Structures | Defenses | Trade | Production | Research
   ═══════════════════════════════════════════════════ */

let _allBases = [];
let _selectedBaseId = null;
let _baseSubtab = localStorage.getItem('awe_base_subtab') || 'overview';
let _tradeFormOpen = false;
let _baseProdInteracting = false;
let _baseProdInteractionTimer = null;

function _clearBaseProdInteraction() {
  _baseProdInteracting = false;
  if (_baseProdInteractionTimer) {
    clearTimeout(_baseProdInteractionTimer);
    _baseProdInteractionTimer = null;
  }
}

function _baseProdTouch() {
  _baseProdInteracting = true;
  if (_baseProdInteractionTimer) clearTimeout(_baseProdInteractionTimer);
  _baseProdInteractionTimer = setTimeout(() => {
    _baseProdInteracting = false;
    _baseProdInteractionTimer = null;
  }, 45000);
}

function fmtDefenseUnitCount(value) {
  const num = Number(value || 0);
  if (!Number.isFinite(num)) return '0';
  const rounded = Math.round(num * 100) / 100;
  if (Math.abs(rounded - Math.round(rounded)) < 0.001) return String(Math.round(rounded));
  if (Math.abs((rounded * 10) - Math.round(rounded * 10)) < 0.001) return rounded.toFixed(1).replace(/\.0$/, '');
  return rounded.toFixed(2).replace(/0$/, '').replace(/\.$/, '');
}

function getDefenseUnitDisplay(defense, base) {
  const totalUnits = Math.max(0, Number(defense?.quantity ?? ((defense?.level || 0) * 5)) || 0);
  const effectiveness = Math.max(0, Math.min(1, Number(base?.defense_effectiveness ?? 1) || 0));
  const currentUnits = Math.min(totalUnits, totalUnits * effectiveness);
  return `${fmtDefenseUnitCount(currentUnits)} / ${fmtDefenseUnitCount(totalUnits)}`;
}

function openBasesHome() {
  _selectedBaseId = null;
  _tradeFormOpen = false;
  _clearBaseProdInteraction();
  switchTab('bases');
}

async function loadBases() {
  try {
    // Skip re-render if a trade form is open (user may be typing)
    if (_tradeFormOpen) return;
    if (_baseSubtab === 'production' && _baseProdInteracting) return;
    const res = await apiFetch('/api/bases');
    if (!res) return;
    _allBases = await res.json();
    if (_selectedBaseId && !_allBases.some(b => b.id === _selectedBaseId)) {
      _selectedBaseId = null;
    }
    document.getElementById('bases-loading').style.display = 'none';
    document.getElementById('bases-container').style.display = 'block';
    const scrollY = window.scrollY;
    renderBasesTab();
    window.scrollTo(0, scrollY);
  } catch (e) { console.error(e); }
}

function renderBasesTab() {
  const container = document.getElementById('bases-container');
  if (!_allBases.length) {
    container.innerHTML = '<div class="empty-state"><p>No bases yet. Colonize a planet from the Galaxy Map!</p></div>';
    return;
  }

  const base = _allBases.find(b => b.id === _selectedBaseId);
  if (!base) { _selectedBaseId = null; container.innerHTML = renderBaseListView(); return; }

  container.innerHTML = renderBaseDetailView(base);
}

function renderBaseListView() {
  let html = `<div style="text-align:center;font-size:14px;margin-bottom:6px;color:var(--text-bright);"><b>B</b>ases</div>`;
  html += `<table class="data-table base-list-table" style="width:100%;font-size:12px;margin-bottom:4px;">
    <thead><tr>
      <th style="text-align:center;">Base</th>
      <th style="text-align:center;">Location</th>
      <th style="text-align:center;" class="mobile-hide">Occupier</th>
      <th style="text-align:center;">Economy</th>
      <th style="text-align:center;" class="mobile-hide">Comment</th>
    </tr></thead><tbody>`;
  for (const b of _allBases) {
    const econStr = b.economy === (b.economy_max || b.economy) ? `${b.economy}` : `${b.economy} / ${b.economy_max}`;
    const occupier = b.occupied_by ? `<span class="text-danger">${escStr(b.occupied_by_name || '?')}</span>` : '';
    html += `<tr style="cursor:pointer;" onclick="_selectedBaseId=${b.id};renderBasesTab();">
      <td style="text-align:center;" class="text-accent">${b.is_home_base ? '&#9733; ' : ''}${escStr(b.name)}</td>
      <td style="text-align:center;">${coordLink(b.coords)}</td>
      <td style="text-align:center;" class="mobile-hide">${occupier}</td>
      <td style="text-align:center;">${econStr}</td>
      <td style="text-align:center;" class="mobile-hide"><a href="#" class="text-dim" onclick="event.stopPropagation();openRenameModal(${b.id},'${escAttr(b.name)}');return false;" style="font-size:10px;">Edit</a></td>
    </tr>`;
  }
  html += '</tbody></table>';
  html += `<div class="text-dim" style="text-align:right;font-size:10px;margin-bottom:8px;">
    <a href="#" onclick="openChangeHomeModal();return false;">Change Home Planet</a> · <a href="#" onclick="openReorderModal();return false;">Change bases order</a></div>`;
  return html;
}

function renderBaseDetailView(base) {
  const subtabs = [
    { id: 'overview', label: t('base.overview') },
    { id: 'structures', label: t('base.structures') },
    { id: 'defenses', label: t('base.defenses') },
    { id: 'production', label: t('base.production') },
    { id: 'research', label: t('base.research') },
    { id: 'trade', label: t('base.trade') },
  ];

  // Base selector dropdown
  let baseOptions = _allBases.map(b =>
    `<option value="${b.id}" ${b.id === _selectedBaseId ? 'selected' : ''}>${b.is_home_base ? '\u2733 ' : ''}${escStr(b.name)}</option>`
  ).join('');

  let html = `<div class="base-page-shell"><div class="base-local-shell">
    <div class="base-local-top">
      <div class="base-local-cell base-local-selector">
        <div class="base-local-select-row">
          <select onchange="_selectedBaseId=parseInt(this.value);renderBasesTab();" class="base-local-select">${baseOptions}</select>
          <a href="#" class="base-local-icon-link" onclick="openRenameModal(${base.id},'${escAttr(base.name)}');return false;" title="Rename">Rename</a>
          <a href="#" class="base-local-icon-link" onclick="abandonBase(${base.id},'${escAttr(base.name)}');return false;" title="Disband">Disband</a>
        </div>
      </div>
      <div class="base-local-cell">
        <div class="base-mini-label">Location</div>
        <div class="base-mini-value">${coordLink(base.coords)}</div>
      </div>
      <div class="base-local-cell">
        <div class="base-mini-stat"><span>Population</span><strong>${base.pop_used || 0}<small>/${base.population || 0}</small></strong></div>
        <div class="base-mini-stat"><span>Energy</span><strong>${base.energy_used || 0}<small>/${base.energy || 0}</small></strong></div>
        <div class="base-mini-stat"><span>Area</span><strong>${base.area_used || 0}<small>/${base.area || 0}</small></strong></div>
      </div>
      <div class="base-local-cell">
        <div class="base-mini-stat"><span>Economy</span><strong>${base.economy || 0}</strong></div>
        <div class="base-mini-stat"><span>Construction</span><strong>${base.construction || 0}</strong></div>
        <div class="base-mini-stat"><span>Production</span><strong>${base.production || 0}</strong></div>
        <div class="base-mini-stat"><span>Research</span><strong>${base.research_capacity || 0}</strong></div>
      </div>
      <div class="base-local-cell">
        <div class="base-mini-stat"><span>Trade Routes</span><strong>${base.trade_route_count || 0}<small>/${base.max_trade_routes || 0}</small></strong></div>
      </div>
    </div>
    <div class="awe-tab-bar base-local-menu" id="base-subtab-bar">`;
  for (const st of subtabs) {
    html += `<a href="#" class="${_baseSubtab === st.id ? 'active' : ''}" onclick="switchBaseSubtab('${st.id}');return false;">${st.label}</a>`;
  }
  html += `</div></div>`;

  if (base.occupied_by) {
    const unrestPct = Math.round((base.unrest || 0) * 100);
    const defPct = Math.round((base.defense_effectiveness || 0) * 100);
    html += `<div class="occupy-banner">
      <span>Occupied by <strong>${escStr(base.occupied_by_name || 'Unknown')}</strong></span>
      <span>Unrest: <strong class="text-warn">${unrestPct}%</strong></span>
      <span>Defense: <strong class="text-danger">${defPct}%</strong></span>
      ${unrestPct >= 100 ? `<button class="btn btn-danger btn-sm" onclick="doRevolt(${base.id})">REVOLT!</button>` : ''}
    </div>`;
  }

  if (_baseSubtab === 'overview') {
    html += `<div class="base-main-panel">${renderBaseOverview(base)}</div>`;
  } else {
    html += `<div class="base-main-panel"><div class="base-detail-layout">`;
    html += `<div class="base-detail-left">${renderBaseSubtabContent(base)}</div>`;
    html += `<div class="base-detail-right">${renderBaseRightPanel(base)}</div>`;
    html += `</div></div>`;
  }

  return `${html}</div>`;
}

function switchBaseSubtab(tab) {
  _baseSubtab = tab;
  localStorage.setItem('awe_base_subtab', tab);
  _tradeFormOpen = false;
  _clearBaseProdInteraction();
  renderBasesTab();
}

function renderBaseSubtabContent(base) {
  switch (_baseSubtab) {
    case 'overview': return renderBaseOverview(base);
    case 'structures': return renderStructuresTab(base);
    case 'defenses': return renderDefensesTab(base);
    case 'trade': return renderBaseTradeTab(base);
    case 'production': return renderProductionTab(base);
    case 'research': return renderBaseResearchTab(base);
    default: return '';
  }
}

function renderBaseOverview(base) {
  const stats = base.planet_stats || {};
  const bodyType = fmtType(base.body_type || 'Planet');
  let html = `<div class="base-overview-shell">
    <div class="base-overview-top">
      <div class="base-overview-col base-overview-specs">
        <div class="base-overview-kicker">${coordLink(base.coords)}</div>
        <table class="awe-field-table base-overview-table">
          <tr><td>${t('base.astroType')}</td><td>${bodyType}</td></tr>
          <tr><td>${t('stat.terrain')}</td><td>${astroName(base.planet_type || 'rocky')}</td></tr>
          <tr><td>${t('stat.area')}</td><td>${stats.area || base.area || 0}</td></tr>
          <tr><td>${t('stat.energy')}</td><td>${stats.solar || 0}</td></tr>
          <tr><td>${t('stat.fertility')}</td><td>${stats.fertility || 0}</td></tr>
        </table>
        <div class="base-overview-box-title">${t('base.resources')}</div>
        <table class="base-overview-resource-table">
          <tr><td>Metal</td><td>${stats.metal || 0}</td></tr>
          <tr><td>Gas</td><td>${stats.gas || 0}</td></tr>
          <tr><td>Crystals</td><td>${stats.crystal || 0}</td></tr>
        </table>
      </div>
      <div class="base-overview-col base-overview-planet">
        <img src="/static/astros/${base.planet_type}.jpg" class="base-overview-planet-img" alt="${astroName(base.planet_type)}">
      </div>
      <div class="base-overview-col base-overview-info">
        <div class="base-overview-box-title">${t('base.baseInfo')}</div>
        <table class="awe-field-table base-overview-table">
          <tr><td>${t('base.owner')}</td><td class="text-bright">${escStr(base.owner_name || 'You')}</td></tr>
          <tr><td>${t('stat.economy')}</td><td>${base.economy}</td></tr>
          <tr><td>${t('stat.construction')}</td><td>${base.construction}</td></tr>
          <tr><td>${t('stat.production')}</td><td>${base.production}</td></tr>
          <tr><td>${t('stat.research')}</td><td>${base.research_capacity || 0}</td></tr>
          <tr><td>${t('base.trade')}</td><td>${base.trade_route_count || 0}/${base.max_trade_routes || 0}</td></tr>
        </table>
        ${base.commander_name ? `<div class="base-overview-note">Base Commander: <span class="text-accent">${escStr(base.commander_name)}</span></div>` : ''}
      </div>
    </div>`;

  // Events section
  const constr = base.buildings ? base.buildings.find(bl => bl.is_constructing) : null;
  const sqList = base.ship_queue || [];
  const sqActive = sqList.find(s => s.position === 0);
  const rq = base.research_queue;
  if (constr || sqActive || rq) {
    html += `<div class="base-overview-section">
      <div class="base-overview-section-title">${t('empire.events')}</div>`;
    if (constr) {
      const ct = constr.construction_end ? `<span class="countdown" data-end="${constr.construction_end}">${fmtTime(Math.max(0,(serverDate(constr.construction_end)-Date.now())/1000))}</span>` : '';
      html += `<div class="base-overview-line">${ct} ${t('stat.construction')}: ${escStr(tName(constr.name))}</div>`;
    }
    if (sqActive) {
      const st = sqActive.next_complete ? `<span class="countdown" data-end="${sqActive.next_complete}">${fmtTime(Math.max(0,(serverDate(sqActive.next_complete)-Date.now())/1000))}</span>` : '';
      html += `<div class="base-overview-line">${st} ${t('stat.production')}: ${escStr(tName(sqActive.ship_name || sqActive.ship_type))} ${sqActive.built}/${sqActive.count}${sqList.length > 1 ? ` (+${sqList.length - 1})` : ''}</div>`;
    }
    if (rq) {
      const rt = rq.end_time ? `<span class="countdown" data-end="${rq.end_time}">${fmtTime(Math.max(0,(serverDate(rq.end_time)-Date.now())/1000))}</span>` : '';
      html += `<div class="base-overview-line">${rt} ${t('stat.research')}: ${escStr(tName(rq.name))}</div>`;
    }
    html += `</div>`;
  }

  // Structures summary
  const builtBlds = (base.buildings || []).filter(bl => bl.level > 0);
  const builtDefs = (base.defenses || []).filter(d => d.level > 0);
  if (builtBlds.length || builtDefs.length) {
    html += `<div class="base-overview-grid">`;
    if (builtBlds.length) {
      html += `<table class="data-table base-overview-mini-table"><thead><tr><th>${t('base.structures')}</th><th>${t('general.level')}</th></tr></thead><tbody>`;
      for (const bl of builtBlds) {
        html += `<tr><td>${escStr(tName(bl.name))}</td><td style="text-align:center;">${bl.level}</td></tr>`;
      }
      html += '</tbody></table>';
    }
    if (builtDefs.length) {
      html += `<table class="data-table base-overview-mini-table"><thead><tr><th>${t('base.defenses')} (${Math.round((base.defense_effectiveness||1)*100)}%)</th><th>${t('base.units')}</th></tr></thead><tbody>`;
      for (const d of builtDefs) {
        html += `<tr><td>${escStr(tName(d.name))}</td><td style="text-align:center;">${getDefenseUnitDisplay(d, base)}</td></tr>`;
      }
      html += '</tbody></table>';
    }
    html += `</div>`;
  }

  // Fleets at this base
  const fleets = base.fleets || [];
  const incoming = base.incoming_fleets || [];
  if (fleets.length > 0 || incoming.length > 0) {
    html += `<div class="base-overview-section">
      <div class="base-overview-section-title">Fleets</div>
      <table class="data-table" style="width:100%;font-size:11px;">
      <thead><tr><th style="text-align:left;">Fleet</th><th style="text-align:left;">Player</th><th style="text-align:center;">Arrival</th><th style="text-align:right;">Size</th></tr></thead><tbody>`;
    for (const f of fleets) {
      const pClass = f.is_mine ? 'text-success' : 'text-danger';
      const playerDisplay = f.guild_tag ? `[${escStr(f.guild_tag)}] ${escStr(f.player)}` : escStr(f.player);
      html += `<tr><td>${escStr(f.name)}</td><td class="${pClass}">${playerDisplay}</td><td></td><td style="text-align:right;">${fmtNum(f.size)}</td></tr>`;
    }
    for (const f of incoming) {
      const pClass = f.is_mine ? 'text-success' : 'text-danger';
      const playerDisplay = f.guild_tag ? `[${escStr(f.guild_tag)}] ${escStr(f.player)}` : escStr(f.player);
      const arrivalStr = f.arrival ? `<span class="countdown" data-end="${f.arrival}">${fmtTime(Math.max(0, (serverDate(f.arrival) - Date.now()) / 1000))}</span>` : '';
      html += `<tr><td>${escStr(f.name)}</td><td class="${pClass}">${playerDisplay}</td><td style="text-align:center;">${arrivalStr}</td><td style="text-align:right;">${fmtNum(f.size)}</td></tr>`;
    }
    html += '</tbody></table></div>';
  }

  html += `<div class="base-overview-actions">
    <a href="#" class="base-overview-link" onclick="event.preventDefault();window._prefillMoveCoords='${escAttr(base.coords || '')}';switchTab('fleets');return false;">Move fleet here</a>
    <span class="text-dim">·</span>
    <a href="#" class="base-overview-link" onclick="event.preventDefault();switchBaseSubtab('trade');return false;">Trade here</a>
  </div></div>`;

  return html;
}

// ── STRUCTURES TAB ──
function renderStructuresTab(base) {
  const visibleBlds = base.buildings.filter(bl => bl.level > 0 || bl.is_constructing || bl.can_build !== false);
  const queueFull = (base.construction_queue || []).length >= 5;

  let html = `<table class="data-table awe-struct-table mobile-cards" style="width:100%;font-size:11px;">
    <thead><tr><th style="text-align:left;">${t('base.structures')}</th><th>${t('general.cost')}</th><th>${t('stat.energy')}</th><th>${t('general.time')}</th><th></th></tr></thead><tbody>`;
  for (const bl of visibleBlds) {
    html += renderBuildingRow(bl, base.id, queueFull);
  }
  html += `</tbody></table>`;
  return html;
}

function renderBuildingRow(bl, baseId, queueFull) {
  const isMaxed = bl.is_maxed === true || (bl.max_level > 0 && (bl.effective_level || bl.level) >= bl.max_level);
  const effLevel = bl.effective_level || bl.level;
  const hasQueued = effLevel > bl.level;
  const showLevel = bl.level > 0 || bl.is_constructing || hasQueued;

  const nameStr = escStr(tName(bl.name));
  let levelStr = showLevel ? ` (${t('general.level')} ${bl.level})` : '';
  if (hasQueued) levelStr += ` <span class="text-warn" style="font-size:10px;">→${effLevel}</span>`;

  const descStr = bl.desc ? `<div class="text-dim" style="font-size:10px;">${escStr(bl.desc)}</div>` : '';
  const techReqs = Object.entries(bl.tech_req || {}).map(([tk, l]) => `${tName(fmtType(tk))} ${l}`).join(', ');
  const reqNote = techReqs ? `<div style="font-size:9px;color:var(--text-warn);">Requires: ${techReqs}</div>` : '';

  const energyReq = bl.energy_req || 0;
  const energyStr = energyReq ? `<span style="color:var(--danger);">-${energyReq}</span>` : '';

  let actionHtml = '';
  if (isMaxed) {
    actionHtml = `<span class="text-dim">MAX</span>`;
  } else if (!bl.can_build && bl.cannot_reason) {
    actionHtml = `<span class="text-danger" style="font-size:10px;">${escStr(bl.cannot_reason)}</span>`;
  } else if (queueFull) {
    actionHtml = `<span class="text-dim">${t('queue.full')}</span>`;
  } else {
    actionHtml = `<a href="#" class="text-accent" style="font-weight:bold;" onclick="upgradeBuilding(${baseId},'${bl.type}',this);return false;">${t('btn.build')}</a>`;
  }

  const rowStyle = !bl.can_build && bl.level === 0 && !bl.is_constructing ? 'opacity:0.55;' : '';

  // Click the name to view per-level costs and disband a level (only when built).
  const nameHtml = bl.level > 0
    ? `<a href="#" class="text-bright struct-disband-link" style="font-weight:bold;text-decoration:none;" title="View levels / disband" onclick="showStructureLevels(${baseId},'building','${bl.type}');return false;">${nameStr}</a>`
    : `<span class="text-bright" style="font-weight:bold;">${nameStr}</span>`;

  return `<tr style="${rowStyle}">
    <td data-cell="name" style="text-align:left;">${nameHtml}${levelStr}${descStr}${reqNote}</td>
    <td data-label="${t('general.cost')}" style="text-align:right;white-space:nowrap;">${formatResourceCost(bl.next_cost)}</td>
    <td data-label="${t('stat.energy')}" style="text-align:center;">${energyStr}</td>
    <td data-label="${t('general.time')}" style="text-align:right;white-space:nowrap;">${fmtTime(bl.next_time)}</td>
    <td data-cell="action" style="text-align:right;white-space:nowrap;">${actionHtml}</td>
  </tr>`;
}

// ── DEFENSES TAB ──
function renderDefensesTab(base) {
  const visibleDefs = base.defenses.filter(d => d.level > 0 || d.is_constructing || d.can_build !== false);
  const queueFull = (base.construction_queue || []).length >= 5;

  let html = `<table class="data-table awe-struct-table mobile-cards" style="width:100%;font-size:11px;">
    <thead><tr><th style="text-align:left;">${t('base.defenses')}</th><th>${t('general.cost')}</th><th>Attack/Armour (Shield)</th><th>${t('stat.energy')}</th><th>${t('general.time')}</th><th></th></tr></thead><tbody>`;
  for (const d of visibleDefs) {
    html += renderDefenseRow(d, base.id, queueFull);
  }
  if (!visibleDefs.length) {
    html += `<tr><td colspan="6" class="text-dim" style="padding:20px;text-align:center;">No defenses available</td></tr>`;
  }
  html += `</tbody></table>`;
  return html;
}

function renderDefenseRow(d, baseId, queueFull) {
  const defModel = getEngineFlag('defense_model', 'level');
  const effLevel = d.effective_level || d.level;
  const isMaxed = defModel === 'level' && (d.is_maxed || effLevel >= d.max_level);
  const hasQueued = effLevel > d.level;
  const showLevel = d.level > 0 || d.is_constructing || hasQueued;

  const nameStr = escStr(tName(d.name));
  let levelStr;
  if (defModel === 'count') {
    levelStr = showLevel ? ` (×${d.level})` : '';
    if (hasQueued) levelStr += ` <span class="text-warn" style="font-size:10px;">→×${effLevel}</span>`;
  } else {
    levelStr = showLevel ? ` (${t('general.level')} ${d.level})` : '';
    if (hasQueued) levelStr += ` <span class="text-warn" style="font-size:10px;">→${effLevel}</span>`;
  }

  // Description line
  const descParts = [];
  if (d.desc) descParts.push(escStr(d.desc));
  const descStr = descParts.length ? `<div class="text-dim" style="font-size:10px;">${descParts.join('')}</div>` : '';

  // Attack/Armour (Shield)
  const shieldStr = d.shield ? ` (${d.shield})` : '';
  const statsStr = `${d.attack}/${d.armour}${shieldStr}`;

  const energyReq = d.energy_req || 0;
  const energyStr = energyReq ? `<span style="color:var(--danger);">-${energyReq}</span>` : '';

  // Build time — check if next_time is available
  const timeStr = d.next_time ? fmtTime(d.next_time) : '';

  let actionHtml = '';
  if (isMaxed) {
    actionHtml = `<span class="text-dim">MAX</span>`;
  } else if (!d.can_build && d.cannot_reason) {
    actionHtml = `<span class="text-danger" style="font-size:10px;">${escStr(d.cannot_reason)}</span>`;
  } else if (queueFull) {
    actionHtml = `<span class="text-dim">${t('queue.full')}</span>`;
  } else if (defModel === 'count') {
    // Count model: show quantity input + build button
    actionHtml = `<input type="number" min="1" value="1" style="width:40px;text-align:center;font-size:11px;" id="def-qty-${d.type}-${baseId}">
      <a href="#" class="text-accent" style="font-weight:bold;margin-left:4px;" onclick="buildDefense(${baseId},'${d.type}',document.getElementById('def-qty-${d.type}-${baseId}').value);return false;">${t('btn.build')}</a>`;
  } else {
    actionHtml = `<a href="#" class="text-accent" style="font-weight:bold;" onclick="buildDefense(${baseId},'${d.type}');return false;">${t('btn.build')}</a>`;
  }

  const rowStyle = !d.can_build && d.level === 0 && !d.is_constructing ? 'opacity:0.55;' : '';

  // Disband UI is only meaningful for the level model (count model uses flat per-unit cost).
  const nameHtml = (d.level > 0 && defModel === 'level')
    ? `<a href="#" class="text-bright struct-disband-link" style="font-weight:bold;text-decoration:none;" title="View levels / disband" onclick="showStructureLevels(${baseId},'defense','${d.type}');return false;">${nameStr}</a>`
    : `<span class="text-bright" style="font-weight:bold;">${nameStr}</span>`;

  return `<tr style="${rowStyle}">
    <td data-cell="name" style="text-align:left;">${nameHtml}${levelStr}${descStr}</td>
    <td data-label="${t('general.cost')}" style="text-align:right;white-space:nowrap;">${formatResourceCost(d.next_cost)}</td>
    <td data-label="Atk/Arm" style="text-align:center;">${statsStr}</td>
    <td data-label="${t('stat.energy')}" style="text-align:center;">${energyStr}</td>
    <td data-label="${t('general.time')}" style="text-align:right;white-space:nowrap;">${timeStr}</td>
    <td data-cell="action" style="text-align:right;white-space:nowrap;">${actionHtml}</td>
  </tr>`;
}

// ── TRADE TAB ──
function renderBaseTradeTab(base) {
  let html = `<div style="padding:12px;">`;

  // Title
  html += `<h3 style="text-align:center;margin:0 0 12px">${t('base.trade')}</h3>`;

  // Existing routes for this base
  html += `<div id="base-trade-routes-${base.id}"><span class="text-dim">Loading routes...</span></div>`;

  // Action links
  html += `<div style="text-align:center;margin:16px 0;">
    <a href="#" onclick="event.preventDefault();_showNewTradeForm(${base.id})" style="color:var(--accent);margin-right:24px;">Set a new Trade Route</a>
    <a href="#" onclick="event.preventDefault();_showTradeSearch(${base.id})" style="color:var(--accent);">Search Trade Routes</a>
  </div>`;

  // New trade route form (hidden initially)
  html += `<div id="trade-new-form-${base.id}" style="display:none;">
    <h3 style="text-align:center;margin:0 0 12px">New Trade Route</h3>
    <table class="data-table" style="width:100%;margin-bottom:8px;">
      <thead><tr><th>Origin</th><th>Destination</th><th>Distance</th><th>Route Cost</th></tr></thead>
      <tbody><tr>
        <td>${maybeCoordLink(base.coords) || '?'}</td>
        <td><input type="text" id="trade-dest-${base.id}" placeholder="Enter coordinates" style="width:160px;" oninput="_previewTradeCost(${base.id})" /></td>
        <td id="trade-preview-dist-${base.id}">0</td>
        <td id="trade-preview-cost-${base.id}">0 Credits</td>
      </tr></tbody>
    </table>
    <div style="text-align:center;margin:12px 0;">
      <button class="btn btn-ghost btn-sm" onclick="_previewTradeCost(${base.id})" style="margin-right:12px;">Calculate Profit</button>
      <button class="btn btn-primary btn-sm" onclick="_createTradeFromBase(${base.id})">Start Trade Route</button>
    </div>
    <div id="trade-base-error-${base.id}" class="alert alert-error mt-8" style="display:none;"></div>
    <div style="margin-top:12px;">
      <strong>Fast Destination Select</strong><br>
      <div style="margin-top:4px;" id="trade-fast-select-${base.id}">`;

  // Own bases as clickable coords
  for (const b of _allBases) {
    if (b.id === base.id) continue;
    html += `<a href="#" onclick="event.preventDefault();document.getElementById('trade-dest-${base.id}').value='${b.coords||''}';_previewTradeCost(${base.id})" style="color:var(--accent);margin-right:16px;display:inline-block;margin-bottom:4px;">${b.numeral || ''} (${b.coords || ''})</a>`;
  }

  html += `</div></div></div>`;

  // Trade search (hidden initially)
  html += `<div id="trade-search-${base.id}" style="display:none;">
    <div id="trade-search-results-${base.id}"><span class="text-dim">Loading...</span></div>
    <div style="text-align:center;margin-top:12px;">
      <a href="#" onclick="event.preventDefault();_addBaseToTradeFinder(${base.id})" style="color:var(--accent);">Add this base to this list for 48 hours</a>
    </div>
  </div>`;

  html += `</div>`;

  // Load routes for this base async
  setTimeout(() => _loadBaseTradeRoutes(base.id), 0);

  return html;
}

async function _loadBaseTradeRoutes(baseId) {
  const container = document.getElementById(`base-trade-routes-${baseId}`);
  if (!container) return;
  try {
    const res = await apiFetch('/api/trade-routes');
    if (!res || !res.ok) return;
    const data = await res.json();
    const routes = (data.routes || []).filter(r =>
      r.base_a?.id === baseId || r.base_b?.id === baseId
    );
    if (!routes.length) {
      container.innerHTML = '<div class="text-dim" style="font-size:12px;">No trade routes from this base.</div>';
      return;
    }
    let html = `<table class="data-table" style="width:100%;font-size:12px;">
      <thead><tr><th>Route</th><th>Distance</th><th>Income</th><th>Status</th><th></th></tr></thead><tbody>`;
    for (const r of routes) {
      const other = r.base_a?.id === baseId ? r.base_b : r.base_a;
      const status = r.is_incoming ? 'Incoming' : (r.is_closing ? 'Closing' : (r.is_pending ? 'Pending' : 'Active'));
      let actions = '';
      if (r.is_incoming) {
        actions = `<a href="#" onclick="event.preventDefault();acceptTradeRoute(${r.id})" style="color:var(--accent);font-size:11px;margin-right:8px;">Accept</a><a href="#" onclick="event.preventDefault();rejectTradeRoute(${r.id})" style="color:var(--danger,#c44);font-size:11px;">Reject</a>`;
      } else if (!r.is_closing) {
        actions = `<a href="#" onclick="event.preventDefault();_cancelTradeFromBase(${r.id},${baseId})" style="color:var(--danger,#c44);font-size:11px;">Cancel</a>`;
      }
      html += `<tr>
        <td>${escStr(other?.name || '?')} <span class="text-dim">(${maybeCoordLink(other?.coords, 'text-dim')})</span></td>
        <td>${r.distance}</td>
        <td>${Math.ceil(r.income)} cr/hr</td>
        <td>${status}</td>
        <td>${actions}</td>
      </tr>`;
    }
    html += '</tbody></table>';
    const totalIncome = routes.filter(r => !r.is_closing && !r.is_pending).reduce((sum, r) => sum + r.income, 0);
    html += `<div style="text-align:right;font-size:12px;margin-top:4px;" class="text-dim">Trade income from this base: ${Math.ceil(totalIncome)} cr/hr</div>`;
    html += `<div style="margin-top:12px;font-size:11px;padding:8px;border-top:1px solid var(--border-dim, #333);" class="text-dim">
      <strong>Trade Formula</strong><br>
      Trade Income = &radic;(Lowest base economy) &times; [ 1 + &radic;(2&times;Distance)/75 + &radic;(Players)/10 ]<br>
      Players = total unique players in your trade network (currently: ${data.num_players || 0})
    </div>`;
    container.innerHTML = html;
  } catch(e) {
    container.innerHTML = '<span class="text-danger">Error loading routes</span>';
  }
}

function _showNewTradeForm(baseId) {
  const form = document.getElementById(`trade-new-form-${baseId}`);
  const search = document.getElementById(`trade-search-${baseId}`);
  if (form) {
    const show = form.style.display === 'none';
    form.style.display = show ? 'block' : 'none';
    _tradeFormOpen = show;
  }
  if (search) search.style.display = 'none';
}

function _showTradeSearch(baseId) {
  const form = document.getElementById(`trade-new-form-${baseId}`);
  const search = document.getElementById(`trade-search-${baseId}`);
  if (search) {
    const show = search.style.display === 'none';
    search.style.display = show ? 'block' : 'none';
    _tradeFormOpen = show;
  }
  if (form) form.style.display = 'none';
  _loadTradeSearchResults(baseId);
}

async function _previewTradeCost(baseId) {
  const coords = document.getElementById(`trade-dest-${baseId}`)?.value.trim();
  const distEl = document.getElementById(`trade-preview-dist-${baseId}`);
  const costEl = document.getElementById(`trade-preview-cost-${baseId}`);
  if (!coords) { distEl.textContent = '0'; costEl.textContent = '0 Credits'; return; }
  try {
    const res = await apiFetch(`/api/trade-preview?base_id=${baseId}&coords=${encodeURIComponent(coords)}`);
    if (!res || !res.ok) { distEl.textContent = '?'; costEl.textContent = '?'; return; }
    const data = await res.json();
    distEl.textContent = Math.round(data.distance);
    costEl.textContent = `${Math.round(data.cost)} Credits`;
  } catch(e) { distEl.textContent = '?'; costEl.textContent = '?'; }
}

async function _createTradeFromBase(baseId) {
  const errEl = document.getElementById(`trade-base-error-${baseId}`);
  errEl.style.display = 'none';
  const coords = document.getElementById(`trade-dest-${baseId}`)?.value.trim();

  if (!coords) {
    errEl.textContent = 'Enter destination coordinates';
    errEl.style.display = 'block';
    return;
  }

  // Resolve coordinates
  let targetBaseId;
  try {
    const res = await apiFetch(`/api/resolve-coords?coords=${encodeURIComponent(coords)}`);
    if (!res || !res.ok) {
      const data = await res?.json().catch(() => ({}));
      const msg = typeof data?.detail === 'string' ? data.detail : 'Could not find base at those coordinates';
      errEl.textContent = msg;
      errEl.style.display = 'block';
      return;
    }
    const data = await res.json();
    targetBaseId = data.base_id || data.colony_id;
  } catch(e) {
    errEl.textContent = 'Error resolving coordinates';
    errEl.style.display = 'block';
    return;
  }

  try {
    const res = await apiFetch('/api/trade-routes', {
      method: 'POST',
      body: JSON.stringify({ base_a_id: baseId, base_b_id: targetBaseId })
    });
    const data = await res.json();
    if (data.success) {
      showSnack('Trade route established!');
      _tradeFormOpen = false;
      _loadBaseTradeRoutes(baseId);
      document.getElementById(`trade-new-form-${baseId}`).style.display = 'none';
      if (typeof updateHUD === 'function') updateHUD();
    } else {
      const msg = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail) || 'Failed to create route';
      errEl.textContent = msg;
      errEl.style.display = 'block';
    }
  } catch(e) {
    errEl.textContent = 'Error creating trade route';
    errEl.style.display = 'block';
  }
}

async function _loadTradeSearchResults(baseId) {
  const container = document.getElementById(`trade-search-results-${baseId}`);
  if (!container) return;
  try {
    const res = await apiFetch(`/api/trade-finder?base_id=${baseId}`);
    if (!res || !res.ok) return;
    const data = await res.json();
    if (!data.trades || !data.trades.length) {
      container.innerHTML = '<div class="text-dim" style="text-align:center;">No trades available.</div>';
      return;
    }
    let html = `<div style="text-align:center;margin-bottom:8px;" class="text-dim">Public list of bases with available trade routes</div>`;
    html += `<table class="data-table" style="width:100%;font-size:12px;">
      <thead><tr><th>Base</th><th>Player</th><th>Economy</th><th>Distance</th><th></th></tr></thead><tbody>`;
    for (const tr of data.trades) {
      html += `<tr>
        <td>${escStr(tr.base_name || tr.base_a?.name || '?')}</td>
        <td>${escStr(tr.owner || '?')}</td>
        <td>${tr.economy || '?'}</td>
        <td>${tr.distance || '?'}</td>
        <td><a href="#" onclick="event.preventDefault();document.getElementById('trade-dest-${baseId}').value='${escStr(tr.coords || '')}';_showNewTradeForm(${baseId});_previewTradeCost(${baseId})" style="color:var(--accent)">Start</a></td>
      </tr>`;
    }
    html += '</tbody></table>';
    container.innerHTML = html;
  } catch(e) {
    container.innerHTML = '<span class="text-danger">Error loading trade finder</span>';
  }
}

async function _addBaseToTradeFinder(baseId) {
  try {
    const res = await apiFetch(`/api/trade-finder/list-base`, {
      method: 'POST',
      body: JSON.stringify({ colony_id: baseId })
    });
    if (!res || !res.ok) {
      const data = await res?.json().catch(() => ({}));
      showSnack(data?.detail || 'Failed');
      return;
    }
    showSnack('Base listed on trade finder for 48 hours');
  } catch(e) { showSnack('Failed to list base on trade finder'); }
}

async function _cancelTradeFromBase(routeId, baseId) {
  if (!confirm('Cancel this trade route? You\'ll get a partial refund.')) return;
  try {
    const res = await apiFetch(`/api/trade-routes/${routeId}`, { method: 'DELETE' });
    const data = await res.json();
    if (data.success) {
      showSnack('Trade route cancelled');
      _loadBaseTradeRoutes(baseId);
      if (typeof updateHUD === 'function') updateHUD();
    } else showSnack(data.detail || 'Failed');
  } catch(e) { console.error(e); }
}

// ── PRODUCTION TAB ──
function renderProductionTab(base) {
  _clearBaseProdInteraction();
  let html = `<div style="text-align:center;font-size:14px;margin-bottom:8px;color:var(--text-bright);"><b>${t('base.production').charAt(0)}</b>${t('base.production').slice(1)}</div>`;

  html += `<div id="base-ship-list-${base.id}">Loading ship types...</div>`;
  html += `<div style="font-size:11px;margin-top:8px;">
    <label><input type="checkbox" id="fast-prod-${base.id}" onchange="loadShipListForBase(_allBases.find(b=>b.id===${base.id}))"> ${t('prod.fast')}</label>
  </div>`;

  const sqList = base.ship_queue || [];
  if (sqList.length > 0) {
    html += `<div style="font-size:11px;padding:4px 8px;margin-top:8px;border:1px solid var(--border);background:var(--bg-panel);">`;
    html += `<div style="font-weight:bold;margin-bottom:4px;">${t('queue.production')} (${sqList.length}/12)</div>`;
    let cumEnd = null;
    for (const sq of sqList) {
      let timeStr;
      if (sq.next_complete) {
        cumEnd = serverDate(sq.next_complete);
        timeStr = `<span class="countdown" data-end="${sq.next_complete}">${fmtTime(Math.max(0, (cumEnd - Date.now()) / 1000))}</span>`;
      } else if (sq.total_time && cumEnd) {
        cumEnd = new Date(cumEnd.getTime() + sq.total_time * 1000);
        const iso = cumEnd.toISOString();
        timeStr = `<span class="countdown" data-end="${iso}">${fmtTime(Math.max(0, (cumEnd - Date.now()) / 1000))}</span>`;
      } else {
        timeStr = '<span class="text-dim">queued</span>';
      }
      const cancelBtn = `<a href="#" class="text-danger" style="font-size:10px;margin-left:6px;" onclick="cancelShipQueue(${sq.id});return false;">[x]</a>`;
      html += `<div><span class="text-bright">${escStr(tName(sq.ship_name || sq.ship_type))}</span>
        <span class="text-dim">${sq.position === 0 ? sq.built + '/' : ''}${sq.count}</span> ${timeStr} ${cancelBtn}</div>`;
    }
    html += `</div>`;
  }
  setTimeout(() => loadShipListForBase(base), 50);
  return html;
}

async function loadShipListForBase(base) {
  const container = document.getElementById(`base-ship-list-${base.id}`);
  if (!container) return;
  try {
    const [specs, techLevels, fleetsRes] = await Promise.all([
      getShipSpecs(), getPlayerTechLevels(), apiFetch('/api/fleets')
    ]);
    // Count ships stationed at this base
    const fleets = fleetsRes ? await fleetsRes.json() : [];
    const baseShips = {};
    for (const f of fleets) {
      if (f.base_id === base.id && !f.is_moving) {
        for (const [st, cnt] of Object.entries(f.ships || {})) {
          if (cnt > 0) baseShips[st] = (baseShips[st] || 0) + cnt;
        }
      }
    }

    const fastProd = document.getElementById(`fast-prod-${base.id}`)?.checked || false;
    const costMult = fastProd ? 1.4 : 1;
    const timeMult = fastProd ? 0.5 : 1;

    let html = `<div class="base-production-panel"><table class="data-table awe-struct-table base-production-table mobile-cards" style="width:100%;font-size:11px;">
      <thead><tr>
        <th style="text-align:left;">${t('base.units')}</th><th>${t('general.cost')}</th><th>Attack/Armour (Shield)</th><th>${t('general.time')}</th><th>${t('base.quantity')}</th><th>Status</th>
      </tr></thead><tbody>`;

    for (const [type, sp] of Object.entries(specs)) {
      if (sp.disabled) continue;
      const canBuild = base.shipyard_level >= (sp.shipyard || sp.shipyard_req || 0);
      if (!canBuild) continue;
      if (!meetsShipTechReqs(sp, techLevels)) continue;

      const available = baseShips[type] || 0;
      const availStr = available > 0 ? ` <span class="text-dim">(${available} ${t('general.available')})</span>` : '';
      const nameStr = escStr(tName(sp.name || type));
      const unitCost = scaleCost(sp.cost, costMult);
      const descStr = sp.is_goods
        ? `<div class="text-dim" style="font-size:10px;">Goods auto sell at ${sp.sell_price} credits each when production finishes.</div>`
        : `<div class="text-dim" style="font-size:10px;">${sp.desc || ''}</div>`;

      const shieldStr = sp.shield ? ` (${sp.shield})` : '';
      const statsStr = sp.is_goods ? '' : `${sp.attack}/${sp.armour}${shieldStr}`;

      // Time per unit based on base production rate
      const prodRate = base.production || 1;
      const timePerUnit = costValue(sp.cost) / prodRate * 3600 * timeMult;

      const res = window._playerResources || {};
      const statusHtml = !canAffordClient(res, unitCost)
        ? `<span class="text-danger" style="font-size:10px;">out ${getResourceModel() === 'multi' ? 'res.' : 'cred.'}</span>`
        : `<span class="text-dim" style="font-size:10px;">ready</span>`;

      html += `<tr id="base-prod-row-${base.id}-${type}">
        <td data-cell="name" style="text-align:left;"><span class="text-bright" style="font-weight:bold;">${nameStr}</span>${availStr}${descStr}</td>
        <td data-label="${t('general.cost')}" style="text-align:right;white-space:nowrap;">${formatResourceCost(unitCost)}</td>
        <td data-label="Atk/Arm" style="text-align:center;">${statsStr}</td>
        <td data-label="${t('general.time')}" style="text-align:right;white-space:nowrap;">${fmtTime(timePerUnit)}</td>
        <td data-cell="action" data-label="${t('base.quantity')}" style="text-align:center;"><input type="number" class="ship-count-input" id="ship-count-${base.id}-${type}" min="1" style="width:60px;" onfocus="_baseProdInputChanged(${base.id},'${type}')" oninput="_baseProdInputChanged(${base.id},'${type}')"></td>
        <td data-label="Status" style="text-align:right;white-space:nowrap;">${statusHtml}</td>
      </tr>`;
    }

    html += `</tbody></table>
      <div class="base-production-actions">
        <button class="btn btn-primary btn-sm" onclick="buildShipsFromBase(${base.id});return false;">${t('btn.build')}</button>
      </div>
      <div class="base-production-help text-dim">Enter a quantity for one unit type, then use Build.</div>
    </div>`;
    container.innerHTML = html;
  } catch (e) {
    container.innerHTML = '<div class="text-dim">Error loading ships</div>';
  }
}

function _baseProdInputChanged(baseId, shipType) {
  _baseProdTouch();
  document.querySelectorAll(`[id^="base-prod-row-${baseId}-"]`).forEach(row => row.classList.remove('base-prod-active-row'));
  const row = document.getElementById(`base-prod-row-${baseId}-${shipType}`);
  const input = document.getElementById(`ship-count-${baseId}-${shipType}`);
  if (row && input && String(input.value || '').trim()) row.classList.add('base-prod-active-row');
}

function _getBaseProductionSelection(baseId, explicitShipType = null) {
  if (explicitShipType) {
    const input = document.getElementById(`ship-count-${baseId}-${explicitShipType}`);
    const count = parseInt(input?.value || '0');
    if (count > 0) return { shipType: explicitShipType, count };
    return null;
  }
  const matches = [];
  document.querySelectorAll(`input[id^="ship-count-${baseId}-"]`).forEach(input => {
    const count = parseInt(input.value || '0');
    if (count > 0) {
      matches.push({
        shipType: input.id.replace(`ship-count-${baseId}-`, ''),
        count
      });
    }
  });
  if (matches.length === 0) return null;
  if (matches.length > 1) return { error: 'Enter quantity for only one unit type at a time.' };
  return matches[0];
}

async function buildShipsFromBase(baseId, shipType = null) {
  const selection = _getBaseProductionSelection(baseId, shipType);
  if (!selection) {
    showSnack('Enter a quantity first');
    return;
  }
  if (selection.error) {
    showSnack(selection.error);
    return;
  }
  const { shipType: selectedShipType, count } = selection;
  const fastProd = document.getElementById(`fast-prod-${baseId}`)?.checked || false;
  _clearBaseProdInteraction();
  try {
    const res = await apiFetch('/api/fleets/build', {
      method: 'POST',
      body: JSON.stringify({ base_id: baseId, ship_type: selectedShipType, count, fast_production: fastProd })
    });
    const data = await res.json();
    if (data.success) {
      showSnack(`Building ${count}x ${selectedShipType} — ${fmtTime(data.total_time || 0)}`);
      await updateHUD(); await loadBases();
    } else {
      showSnack(data.detail || 'Build failed');
    }
  } catch (e) { console.error(e); }
}

// ── RESEARCH TAB (embedded in bases) ──
function renderBaseResearchTab(base) {
  const labLv = (base.buildings.find(b => b.type === 'research_labs') || {}).level || 0;
  let html = `<div style="text-align:center;font-size:14px;margin-bottom:8px;color:var(--text-bright);"><b>${t('base.research').charAt(0)}</b>${t('base.research').slice(1)}</div>`;
  html += `<div id="base-research-tree" class="text-dim" style="font-size:11px;">Loading research...</div>`;
  setTimeout(() => _loadBaseResearchTree(base.id), 50);
  return html;
}

async function _loadBaseResearchTree(baseId) {
  const container = document.getElementById('base-research-tree');
  if (!container) return;
  try {
    const res = await apiFetch(`/api/research?base_id=${baseId}`);
    if (!res) return;
    const techs = await res.json();

    let html = `<table class="data-table awe-struct-table base-research-table" style="width:100%;font-size:11px;">
      <thead><tr><th class="base-research-name-col" style="text-align:left;">${t('base.research')}</th><th class="base-research-cost-col">${t('general.cost')}</th><th class="base-research-time-col">${t('general.time')}</th><th class="base-research-action-col"></th></tr></thead><tbody>`;

    for (const tech of techs) {
      const locked = !tech.prereqs_met || !tech.lab_met;
      const hasQueued = tech.effective_level > tech.level;
      let levelStr = `(${t('general.level')} ${tech.level})`;
      if (hasQueued) levelStr += ` <span class="text-warn" style="font-size:10px;">\u2192${tech.effective_level}</span>`;
      const nameStr = `<span class="text-bright" style="font-weight:bold;">${escStr(tName(tech.name))}</span> ${levelStr}`;
      let descBits = [];
      if (tech.bonus) descBits.push(`<span class="text-dim">${escStr(tech.bonus)}</span>`);
      if (!tech.prereqs_met && tech.prereq_text) descBits.push(`<span class="text-warn">Requires: ${escStr(tech.prereq_text)}</span>`);
      if (!tech.lab_met) descBits.push(`<span class="text-warn">Needs Research Labs ${tech.lab_req}</span>`);
      const descStr = descBits.length ? `<div style="font-size:10px;">${descBits.join('<br>')}</div>` : '';

      let actionHtml = '';
      let timeStr = fmtTime(tech.next_time);
      if (tech.is_researching && tech.research_end) {
        const remaining = Math.max(0, (serverDate(tech.research_end) - Date.now()) / 1000);
        timeStr = `<span class="countdown" data-end="${tech.research_end}">${fmtTime(remaining)}</span>`;
      }
      if (locked) {
        actionHtml = `<span class="text-dim base-research-status" style="font-size:10px;">Locked</span>`;
      } else if (tech.conflict) {
        actionHtml = '<span class="text-warn base-research-status" style="font-size:10px;">researching elsewhere</span>';
      } else {
        actionHtml = `<a href="#" class="text-accent base-research-action" style="font-weight:bold;" onclick="doResearchFromBase('${tech.tech_type}',${baseId});return false;">${t('btn.research')}</a>`;
      }

      const rowStyle = locked ? 'opacity:0.55;' : '';
      html += `<tr style="${rowStyle}">
        <td class="base-research-name-cell" style="text-align:left;">${nameStr}${descStr}</td>
        <td class="base-research-cost-cell" style="text-align:right;white-space:nowrap;">${formatResourceCost(tech.next_cost)}</td>
        <td class="base-research-time-cell" style="text-align:right;white-space:nowrap;">${timeStr}</td>
        <td class="base-research-action-cell" style="text-align:right;white-space:nowrap;">${actionHtml}</td>
      </tr>`;
    }

    html += '</tbody></table>';
    container.innerHTML = html;
    updateCountdowns();
  } catch (e) { console.error('Research load error:', e); container.innerHTML = '<span class="text-danger">Failed to load research</span>'; }
}

async function doResearchFromBase(techType, baseId) {
  try {
    const res = await apiFetch('/api/research', {
      method: 'POST', body: JSON.stringify({ tech_type: techType, base_id: baseId })
    });
    if (!res) return;
    const data = await res.json();
    if (res.ok && data.success) {
      showSnack(data.queued ? `Research queued (position ${data.queue_position})` : 'Research started!');
      await updateHUD();
      await loadBases();
    } else {
      showSnack(data.detail || 'Research failed');
    }
  } catch (e) { console.error('Research error:', e); showSnack('Research request failed'); }
}

// ── RIGHT PANEL: Planet Image + Stats + Construction Queue ──
function renderBaseRightPanel(base) {
  const ps = base.planet_stats;
  const enUsed = base.energy_used || 0, enMax = base.energy || 0;
  const popUsed = base.pop_used || 0, popMax = base.population || 0;
  const areaUsed = base.area_used || 0, areaMax = base.area || 0;
  const queue = base.construction_queue || [];

  let html = `
    <div class="base-planet-img-wrap">
      <img src="/static/astros/${base.planet_type}.jpg" class="base-planet-img" alt="${astroName(base.planet_type)}">
    </div>
    <div class="base-stats-panel">
      <table class="base-stats-table">
        <tr><td class="text-dim">${t('stat.economy')}</td><td class="text-warn">${base.economy}/hr</td></tr>
        <tr><td class="text-dim">${t('stat.construction')}</td><td>${base.construction}</td></tr>
        <tr><td class="text-dim">${t('stat.production')}</td><td>${base.production}</td></tr>
        <tr><td class="text-dim">${t('stat.research')}</td><td>${base.research_capacity || 0}</td></tr>
      </table>
      <table class="base-stats-table" style="margin-top:6px;">
        <tr><td class="text-dim">${t('stat.energy')}</td><td>${enUsed}/${enMax}</td></tr>
        <tr><td class="text-dim">${t('stat.population')}</td><td>${popUsed}/${popMax}</td></tr>
        <tr><td class="text-dim">${t('stat.area')}</td><td>${areaUsed}/${areaMax}</td></tr>
      </table>
      <div class="text-dim" style="font-size:9px;margin-top:6px;">
        Sol:${ps.solar} Gas:${ps.gas} Fer:${ps.fertility} Met:${ps.metal} Cry:${ps.crystal}
      </div>
    </div>
    <div class="base-queue-panel">
      <div class="base-queue-title">${t('queue.building')} (${queue.length}/6)</div>
  `;

  if (queue.length === 0) {
    html += `<div class="text-dim" style="font-size:11px;padding:8px;">${t('queue.empty')}</div>`;
  } else {
    for (let i = 0; i < queue.length; i++) {
      const q = queue[i];
      const isActive = i === 0 && q.finish_at;
      const colorClass = q.category === 'building' ? 'ev-structures' : 'ev-defenses';
      let timeHtml = '';
      if (isActive && q.finish_at) {
        const remaining = Math.max(0, (serverDate(q.finish_at) - Date.now()) / 1000);
        timeHtml = `<span class="countdown" data-end="${q.finish_at}">${fmtTime(remaining)}</span>`;
      } else {
        timeHtml = `<span class="text-dim" style="font-size:10px;">Queued</span>`;
      }
      html += `<div class="base-queue-item ${isActive ? 'base-queue-active' : ''}">
        <span class="${colorClass}">${escStr(tName(q.name))} Lv${q.target_level}</span>
        <span style="margin-left:auto;display:flex;align-items:center;gap:6px;">${timeHtml}
          <a href="#" onclick="cancelQueueItem(${base.id},${q.id});return false;" title="Cancel" style="color:var(--danger);font-size:13px;font-weight:bold;text-decoration:none;">✕</a>
        </span>
      </div>`;
    }
  }

  // Ship production queue
  const sqItems = base.ship_queue || [];
  let sqCumEnd = null;
  for (const sq of sqItems) {
    const isActive = sq.position === 0;
    let timeStr;
    if (sq.next_complete) {
      sqCumEnd = serverDate(sq.next_complete);
      timeStr = `<span class="countdown" data-end="${sq.next_complete}">${fmtTime(Math.max(0, (sqCumEnd - Date.now()) / 1000))}</span>`;
    } else if (sq.total_time && sqCumEnd) {
      sqCumEnd = new Date(sqCumEnd.getTime() + sq.total_time * 1000);
      const iso = sqCumEnd.toISOString();
      timeStr = `<span class="countdown" data-end="${iso}">${fmtTime(Math.max(0, (sqCumEnd - Date.now()) / 1000))}</span>`;
    } else {
      timeStr = '<span class="text-dim">queued</span>';
    }
    html += `<div class="base-queue-item ${isActive ? 'base-queue-active' : ''}">
      <span class="ev-production">${escStr(tName(sq.ship_name || sq.ship_type))} ${isActive ? sq.built + '/' : ''}${sq.count}</span>
      <span style="margin-left:auto;display:flex;align-items:center;gap:6px;">${timeStr}
        <a href="#" onclick="cancelShipQueue(${sq.id});return false;" title="Cancel" style="color:var(--danger);font-size:13px;font-weight:bold;text-decoration:none;">✕</a>
      </span>
    </div>`;
  }

  // Research queue (loaded async)
  html += `<div class="base-queue-title" style="margin-top:8px;">${t('queue.research')} <span id="research-queue-count"></span></div>`;
  html += `<div id="research-queue-list"><div class="text-dim" style="font-size:11px;padding:8px;">Loading...</div></div>`;

  html += `</div>`;
  setTimeout(() => _loadResearchQueue(base.id), 50);
  return html;
}

async function _loadResearchQueue(baseId) {
  const container = document.getElementById('research-queue-list');
  const countEl = document.getElementById('research-queue-count');
  if (!container) return;
  try {
    const res = await apiFetch(`/api/research-queue?base_id=${baseId}`);
    if (!res) return;
    const queue = await res.json();
    if (countEl) countEl.textContent = `(${queue.length}/6)`;
    if (queue.length === 0) {
      container.innerHTML = '<div class="text-dim" style="font-size:11px;padding:8px;">Queue empty</div>';
      return;
    }
    container.innerHTML = queue.map((q, i) => {
      const isActive = i === 0 && q.finish_at;
      let timeHtml = '';
      if (isActive) {
        const remaining = Math.max(0, (serverDate(q.finish_at) - Date.now()) / 1000);
        timeHtml = `<span class="countdown" data-end="${q.finish_at}">${fmtTime(remaining)}</span>`;
      } else {
        timeHtml = `<span class="text-dim" style="font-size:10px;">Queued</span>`;
      }
      return `<div class="base-queue-item ${isActive ? 'base-queue-active' : ''}">
        <span class="ev-research">${escStr(q.name)} Lv${q.target_level}</span>
        <span style="margin-left:auto;display:flex;align-items:center;gap:6px;">${timeHtml}
          <a href="#" onclick="cancelResearchQueue(${q.id});return false;" title="Cancel" style="color:var(--danger);font-size:13px;font-weight:bold;text-decoration:none;">✕</a>
        </span>
      </div>`;
    }).join('');
    updateCountdowns();
  } catch (e) { console.error('Research queue error:', e); }
}

async function cancelResearchQueue(queueId) {
  try {
    const res = await apiFetch(`/api/research-queue/${queueId}`, { method: 'DELETE' });
    const data = await res.json();
    if (data.success) {
      showSnack(`Research cancelled (${formatResourceCostText(data.refunded)} refunded)`);
      await updateHUD();
      await loadBases();
    } else {
      showSnack(data.detail || 'Cancel failed');
    }
  } catch (e) { console.error(e); }
}

// ── ACTIONS ──

async function upgradeBuilding(baseId, buildingType, btn) {
  if (btn) btn.disabled = true;
  try {
    const res = await apiFetch('/api/bases/upgrade', {
      method: 'POST', body: JSON.stringify({ base_id: baseId, building_type: buildingType })
    });
    const data = await res.json();
    if (data.success) {
      const msg = data.queued
        ? `Queued upgrade (position ${data.queue_position})`
        : `Upgrading — ${fmtTime(data.time)}`;
      showSnack(msg);
      await updateHUD(); await loadBases();
    }
    else { showSnack(data.detail || 'Upgrade failed'); if (btn) btn.disabled = false; }
  } catch (e) { if (btn) btn.disabled = false; }
}

async function buildDefense(baseId, defenseType, count) {
  try {
    const body = { base_id: baseId, defense_type: defenseType };
    if (count) body.count = parseInt(count) || 1;
    const res = await apiFetch('/api/bases/build-defense', {
      method: 'POST', body: JSON.stringify(body)
    });
    const data = await res.json();
    if (data.success) {
      const defModel = data.defense_model || 'level';
      let msg;
      if (defModel === 'count') {
        msg = data.queued
          ? `Queued ${defenseType} ×${body.count || 1} (position ${data.queue_position})`
          : `Building ${defenseType} ×${body.count || 1}`;
      } else {
        msg = data.queued
          ? `Queued ${defenseType} Lv${data.new_level} (position ${data.queue_position})`
          : `Upgrading ${defenseType} to Lv${data.new_level}`;
      }
      showSnack(msg);
      await updateHUD(); await loadBases();
    }
    else showSnack(data.detail || 'Build failed');
  } catch (e) { console.error(e); }
}

// ── DISBAND STRUCTURE LEVEL (→ base reserve) ──
async function showStructureLevels(baseId, kind, type) {
  try {
    const res = await apiFetch(`/api/bases/downgrade-preview?base_id=${baseId}&kind=${kind}&type_key=${encodeURIComponent(type)}`);
    if (!res) return;
    const d = await res.json();
    const pct = Math.round((d.refund_percent || 0.5) * 100);

    let rows = '';
    for (const lv of d.levels) {
      const isTop = lv.level === d.level;
      rows += `<tr${isTop ? ' style="color:var(--text-warn);"' : ''}>
        <td style="text-align:left;">${t('general.level')} ${lv.level}${isTop ? ' ◀' : ''}</td>
        <td style="text-align:right;">${formatResourceCost(lv.build_cost)}</td>
        <td style="text-align:right;">+${formatResourceCost(lv.refund)}</td>
      </tr>`;
    }

    let actions;
    if (d.blocked) {
      actions = `<div class="text-danger" style="font-size:11px;margin-top:8px;">Finish or cancel construction on this structure before disbanding levels.</div>`;
    } else if (d.level <= 0) {
      actions = `<div class="text-dim" style="font-size:11px;margin-top:8px;">Nothing built to disband.</div>`;
    } else {
      const fullBtn = d.level > 1
        ? `<button class="btn btn-ghost" style="margin-left:6px;" onclick="doDowngradeStructure(${baseId},'${kind}','${type}',${d.level})">Disband all ${d.level} (+${d.full_refund})</button>`
        : '';
      actions = `<div style="margin-top:10px;">
        <button class="btn btn-primary" onclick="doDowngradeStructure(${baseId},'${kind}','${type}',1)">Disband one level (+${d.one_level_refund})</button>
        ${fullBtn}
      </div>`;
    }

    const html = `
      <p style="font-size:11px;color:var(--text-dim);margin:0 0 8px;">
        Disbanding a level returns <strong>${pct}%</strong> of its cost to your
        <strong>base reserve</strong> (a discount toward your next base). Current reserve:
        <strong>${formatResourceCost(d.base_reserve)}</strong>.
      </p>
      <table class="data-table" style="width:100%;font-size:11px;">
        <thead><tr><th style="text-align:left;">Level</th><th style="text-align:right;">Built for</th><th style="text-align:right;">Disband refund</th></tr></thead>
        <tbody>${rows || `<tr><td colspan="3" class="text-dim" style="text-align:center;padding:10px;">No levels built</td></tr>`}</tbody>
      </table>
      ${actions}`;

    document.getElementById('generic-modal-title').textContent = d.name;
    document.getElementById('generic-modal-body').innerHTML = html;
    openModal('generic-modal');
  } catch (e) { console.error(e); showSnack('Could not load structure levels'); }
}

async function doDowngradeStructure(baseId, kind, type, levels) {
  try {
    const res = await apiFetch('/api/bases/downgrade', {
      method: 'POST', body: JSON.stringify({ base_id: baseId, kind, type_key: type, levels })
    });
    const data = await res.json();
    if (data.success) {
      closeModal('generic-modal');
      showSnack(`Disbanded — +${data.reserve_gain} to base reserve (now ${data.base_reserve})`);
      await updateHUD(); await loadBases();
    } else {
      showSnack(data.detail || 'Disband failed');
    }
  } catch (e) { console.error(e); showSnack('Disband failed'); }
}

function openRenameModal(baseId, currentName) {
  document.getElementById('rename-base-id').value = baseId;
  document.getElementById('rename-base-input').value = currentName;
  document.getElementById('rename-error').style.display = 'none';
  openModal('rename-modal');
}

async function doRenameBase() {
  const baseId = document.getElementById('rename-base-id').value;
  const name = document.getElementById('rename-base-input').value.trim();
  if (!name) return;
  try {
    const res = await apiFetch(`/api/bases/${baseId}/rename`, {
      method: 'POST', body: JSON.stringify({ name })
    });
    const data = await res.json();
    if (data.success) { closeModal('rename-modal'); loadBases(); }
    else { document.getElementById('rename-error').textContent = data.detail || 'Failed'; document.getElementById('rename-error').style.display = 'block'; }
  } catch (e) {}
}

function openChangeHomeModal() {
  if (!_allBases || _allBases.length < 2) { showSnack('Need at least 2 bases'); return; }
  let html = '<div style="font-size:12px;margin-bottom:8px;">Select your new home planet:</div>';
  for (const b of _allBases) {
    const isHome = b.is_home_base ? ' (current)' : '';
    const cls = b.is_home_base ? 'btn btn-ghost btn-sm' : 'btn btn-primary btn-sm';
    html += `<div style="margin:4px 0;display:flex;justify-content:space-between;align-items:center;">
      <span>${escStr(b.name)} <span class="text-dim">${maybeCoordLink(b.coords, 'text-dim')}</span>${isHome}</span>
      ${b.is_home_base ? '' : `<button class="${cls}" onclick="doSetHome(${b.id})">Set Home</button>`}
    </div>`;
  }
  document.getElementById('generic-modal-title').textContent = 'Change Home Planet';
  document.getElementById('generic-modal-body').innerHTML = html;
  openModal('generic-modal');
}

async function doSetHome(baseId) {
  try {
    const res = await apiFetch('/api/bases/set-home', { method: 'POST', body: JSON.stringify({ base_id: baseId }) });
    const data = await res.json();
    if (data.success) { closeModal('generic-modal'); showSnack('Home planet changed'); loadBases(); }
    else showSnack(data.detail || 'Failed');
  } catch (e) { showSnack('Error changing home'); }
}

function openReorderModal() {
  if (!_allBases || _allBases.length < 2) { showSnack('Need at least 2 bases'); return; }
  let html = '<div style="font-size:12px;margin-bottom:8px;">Drag to reorder or use arrows:</div>';
  html += '<div id="reorder-list">';
  for (let i = 0; i < _allBases.length; i++) {
    const b = _allBases[i];
    html += `<div class="reorder-item" data-id="${b.id}" style="display:flex;justify-content:space-between;align-items:center;padding:4px 8px;margin:2px 0;border:1px solid var(--border);background:var(--bg-panel);font-size:12px;">
      <span>${b.is_home_base ? '&#9733; ' : ''}${escStr(b.name)} <span class="text-dim">${maybeCoordLink(b.coords, 'text-dim')}</span></span>
      <span>
        <button class="btn btn-ghost btn-sm" onclick="reorderMove(${b.id},-1)" style="padding:0 6px;">&uarr;</button>
        <button class="btn btn-ghost btn-sm" onclick="reorderMove(${b.id},1)" style="padding:0 6px;">&darr;</button>
      </span>
    </div>`;
  }
  html += '</div><div style="margin-top:8px;text-align:right;"><button class="btn btn-primary btn-sm" onclick="doReorder()">Save Order</button></div>';
  document.getElementById('generic-modal-title').textContent = 'Change Base Order';
  document.getElementById('generic-modal-body').innerHTML = html;
  openModal('generic-modal');
}

function reorderMove(baseId, direction) {
  const list = document.getElementById('reorder-list');
  const items = [...list.querySelectorAll('.reorder-item')];
  const idx = items.findIndex(el => parseInt(el.dataset.id) === baseId);
  if (idx < 0) return;
  const newIdx = idx + direction;
  if (newIdx < 0 || newIdx >= items.length) return;
  if (direction < 0) list.insertBefore(items[idx], items[newIdx]);
  else list.insertBefore(items[newIdx], items[idx]);
}

async function doReorder() {
  const items = [...document.querySelectorAll('#reorder-list .reorder-item')];
  const base_ids = items.map(el => parseInt(el.dataset.id));
  try {
    const res = await apiFetch('/api/bases/reorder', { method: 'POST', body: JSON.stringify({ base_ids }) });
    const data = await res.json();
    if (data.success) { closeModal('generic-modal'); showSnack('Base order saved'); loadBases(); }
    else showSnack(data.detail || 'Failed');
  } catch (e) { showSnack('Error saving order'); }
}

async function doRevolt(baseId) {
  if (!confirm('Revolt against the occupier? Your base must be at 100% unrest.')) return;
  try {
    const res = await apiFetch('/api/bases/revolt', {
      method: 'POST', body: JSON.stringify({ base_id: baseId })
    });
    const data = await res.json();
    if (data.success) {
      showSnack(data.message || 'Base freed!');
      await loadBases(); await updateHUD();
    } else showSnack(data.detail || 'Revolt failed');
  } catch (e) { console.error(e); }
}

async function cancelQueueItem(baseId, queueId) {
  try {
    const res = await apiFetch(`/api/bases/${baseId}/construction-queue/${queueId}`, { method: 'DELETE' });
    const data = await res.json();
    if (data.success) { showSnack('Cancelled — resources refunded'); await loadBases(); }
    else showSnack(data.detail || 'Failed to cancel');
  } catch (e) { console.error(e); }
}

async function abandonBase(baseId, baseName) {
  if (!confirm(`Abandon "${baseName}"? This will destroy all buildings, defenses, and trade routes at this base. This cannot be undone.`)) return;
  if (!confirm(`Are you SURE? This will permanently delete this base.`)) return;
  try {
    const res = await apiFetch(`/api/bases/${baseId}/abandon`, { method: 'POST' });
    const data = await res.json();
    if (data.success) { showSnack('Base abandoned'); _selectedBaseId = null; await updateHUD(); await loadBases(); }
    else showSnack(data.detail || 'Failed');
  } catch (e) { console.error(e); }
}
