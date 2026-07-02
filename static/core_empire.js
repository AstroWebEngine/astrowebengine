/* AstroWebEngine frontend (core_empire.js)
   Empire tab rendering, subtab state, and production bulk actions. */

// Empire tab sub-tabs
let _empireSubtab = 'events';
let _empProdInteracting = false;
function switchEmpireSubtab(sub) {
  _empProdInteracting = false;
  _empireSubtab = sub;
  localStorage.setItem('awe_empire_subtab', sub);
  document.querySelectorAll('#empire-tab-row1 a, #empire-tab-row2 a').forEach(a => {
    a.classList.toggle('active', a.textContent.trim().toLowerCase() === sub);
  });
  loadEmpireTab();
}

async function loadEmpireTab() {
  const container = document.getElementById('empire-content');
  if (!container) return;
  // Sync subtab highlight
  document.querySelectorAll('#empire-tab-row1 a, #empire-tab-row2 a').forEach(a => {
    a.classList.toggle('active', a.textContent.trim().toLowerCase() === _empireSubtab);
  });

  // Sub-tabs that render their own content inside empire-content
  if (_empireSubtab === 'trade') {
    renderEmpireTrade(container); return;
  } else if (_empireSubtab === 'reports') {
    container.innerHTML = '<div id="scanners-container"></div>';
    if (typeof loadScanners === 'function') loadScanners();
    return;
  } else if (_empireSubtab === 'technologies') {
    renderEmpireTechnologies(container); return;
  } else if (_empireSubtab === 'credits') {
    if (typeof loadCreditHistory === 'function') loadCreditHistory();
    return;
  }

  try {
    const [basesRes, fleetsRes, researchRes, statsRes] = await Promise.all([
      apiFetch('/api/bases'), apiFetch('/api/fleets'),
      apiFetch('/api/research'), apiFetch('/api/player/stats')
    ]);
    const bases = basesRes ? await basesRes.json() : [];
    const fleets = fleetsRes ? await fleetsRes.json() : [];
    const techs = researchRes ? await researchRes.json() : [];
    const stats = statsRes ? await statsRes.json() : {};

    if (_empireSubtab === 'events') {
      // Base events table with construction/production/research queues
      let html = `<div style="text-align:center;font-size:14px;margin-bottom:8px;color:var(--text-bright);"><b>B</b>ases Events</div>`;
      html += `<table class="data-table"><thead><tr>
        <th>Base</th><th class="mobile-hide">Location</th><th class="mobile-hide">Economy</th><th class="mobile-hide">Occupier</th>
        <th>Construction</th><th>Production</th><th>Research</th>
      </tr></thead><tbody>`;
      for (const b of bases) {
        const eventLink = (content, subtab, dim = false) =>
          `<a href="#" onclick="_goToBase(${b.id},'${subtab}');return false;" style="${dim ? 'color:var(--text-dim);' : 'color:var(--text-bright);'}text-decoration:none;">${content}</a>`;
        // Construction queue
        const constr = b.buildings ? b.buildings.find(bl => bl.is_constructing) : null;
        let constrCell = eventLink('(0)', 'structures', true);
        if (constr) {
          const constrTime = constr.construction_end
            ? `<br><span class="countdown" data-end="${constr.construction_end}">${fmtTime(Math.max(0, (serverDate(constr.construction_end) - Date.now()) / 1000))}</span>` : '';
          const queueCount = b.construction_queue_count || 1;
          constrCell = eventLink(`${escStr(constr.name)} (${queueCount})${constrTime}`, 'structures');
        }
        // Production (ship queue)
        let prodCell = eventLink('(0)', 'production', true);
        if (b.ship_queue && b.ship_queue.length) {
          const sq = b.ship_queue[0];
          const prodTime = sq.next_complete
            ? `<br><span class="countdown" data-end="${sq.next_complete}">${fmtTime(Math.max(0, (serverDate(sq.next_complete) - Date.now()) / 1000))}</span>` : '';
          prodCell = eventLink(`${escStr(tName(sq.ship_name || sq.ship_type))} x${sq.count}${prodTime}`, 'production');
        }
        // Research queue
        let researchCell = eventLink('(0)', 'research', true);
        if (b.research_queue) {
          const rq = b.research_queue;
          const rTime = rq.end_time
            ? `<br><span class="countdown" data-end="${rq.end_time}">${fmtTime(Math.max(0, (serverDate(rq.end_time) - Date.now()) / 1000))}</span>` : '';
          researchCell = eventLink(`${escStr(tName(rq.name))} (${rq.target_level})${rTime}`, 'research');
        }
        const occupier = b.occupied_by ? `<span class="text-danger">${escStr(b.occupied_by)}</span>` : '';
        html += `<tr style="text-align:center;">
          <td class="text-accent">${escStr(b.name)}</td>
          <td class="mobile-hide">${coordLink(b.coords)}</td>
          <td class="mobile-hide">${b.economy} / ${b.economy_max || b.economy}</td>
          <td class="mobile-hide">${occupier}</td>
          <td>${constrCell}</td>
          <td>${prodCell}</td>
          <td>${researchCell}</td>
        </tr>`;
      }
      html += '</tbody></table>';
      html += `<div class="text-dim" style="font-size:10px;margin-top:4px;">Note: (x) is equal to queue quantity.</div>`;
      container.innerHTML = html;
    } else if (_empireSubtab === 'production') {
      // Build ship specs options for dropdown
      let shipSpecs = {};
      try { shipSpecs = await getShipSpecs(); } catch(e) {}
      window._empShipSpecs = shipSpecs;
      const techLevels = await getPlayerTechLevels().catch(() => ({}));

      // Build ship options available to ALL bases (union, for master input)
      let allShipOptions = '';
      for (const [type, sp] of Object.entries(shipSpecs)) {
        if (sp.disabled) continue;
        if (!meetsShipTechReqs(sp, techLevels)) continue;
        allShipOptions += `<option value="${type}">${escStr(tName(sp.name || type))}</option>`;
      }

      // Single unified production table
      let html = `<div style="text-align:center;font-size:14px;margin-bottom:8px;color:var(--text-bright);"><b>B</b>ases Production</div>`;
      html += `<table class="data-table" style="width:100%;font-size:12px;"><thead><tr>
        <th style="text-align:left;">Base</th><th>Location</th><th>Production <span class="text-dim">(Shipyards)</span></th>
        <th>Unit</th><th>Quantity</th><th>Credits</th><th>Time</th><th style="text-align:right;">Total time</th>
      </tr></thead><tbody>`;
      let totalProd = 0;
      for (const b of bases) {
        totalProd += b.production || 0;

        let shipOptions = '';
        for (const [type, sp] of Object.entries(shipSpecs)) {
          if (sp.disabled) continue;
          if (b.shipyard_level < (sp.shipyard || sp.shipyard_req || 0)) continue;
          if (!meetsShipTechReqs(sp, techLevels)) continue;
          shipOptions += `<option value="${type}">${escStr(tName(sp.name || type))}</option>`;
        }

        let queueRemainSec = 0;
        const sqFirst = Array.isArray(b.ship_queue) && b.ship_queue.length ? b.ship_queue[0] : null;
        if (sqFirst && sqFirst.next_complete) {
          queueRemainSec = Math.max(0, (serverDate(sqFirst.next_complete) - Date.now()) / 1000);
        }

        let unitCell, qtyCell, credCell = '', timeCell = '', totalTimeCell = '-';
        if (sqFirst) {
          const remainStr = queueRemainSec > 0
            ? `<span class="countdown" data-end="${sqFirst.next_complete}">${fmtTime(queueRemainSec)}</span>` : '';
          unitCell = `<span>${escStr(tName(sqFirst.ship_name || sqFirst.ship_type || 'Unit'))}</span>
            <select style="font-size:11px;margin-left:4px;" id="emp-prod-unit-${b.id}" data-prod="${b.production||0}" data-queue-remain="${Math.round(queueRemainSec)}" onchange="empProdRecalcRow(${b.id})">${shipOptions}</select>`;
          qtyCell = `<span class="text-dim">${sqFirst.built || 0}/${sqFirst.count || 0}</span>
            <input type="text" style="width:60px;font-size:11px;margin-left:4px;" id="emp-prod-qty-${b.id}" onchange="empProdRecalcRow(${b.id})" oninput="empProdRecalcRow(${b.id})" />`;
          timeCell = remainStr;
        } else {
          unitCell = `<select style="font-size:11px;" id="emp-prod-unit-${b.id}" data-prod="${b.production||0}" data-queue-remain="0" onchange="empProdRecalcRow(${b.id})">${shipOptions}</select>`;
          qtyCell = `<input type="text" style="width:60px;font-size:11px;" id="emp-prod-qty-${b.id}" onchange="empProdRecalcRow(${b.id})" oninput="empProdRecalcRow(${b.id})" />`;
        }

        html += `<tr id="emp-prod-row-${b.id}">
          <td class="text-accent">${escStr(b.name)}</td>
          <td>${coordLink(b.coords)}</td>
          <td style="text-align:center;">${b.production} (${b.shipyard_level || 0}/0)</td>
          <td>${unitCell}</td>
          <td style="text-align:center;">${qtyCell}</td>
          <td style="text-align:center;" class="emp-prod-cred">${credCell}</td>
          <td style="text-align:center;" class="emp-prod-time">${timeCell}</td>
          <td style="text-align:right;" class="emp-prod-total">${totalTimeCell}</td>
        </tr>`;
      }
      // Total + Master input row
      html += `<tr style="border-top:1px solid var(--border);font-weight:bold;">
        <td colspan="2" style="text-align:right;">Total</td>
        <td style="text-align:center;">${totalProd} [${totalProd}]</td>
        <td><span class="text-dim" style="font-size:10px;font-weight:normal;">Master input</span>
          <select style="font-size:11px;font-weight:normal;" id="emp-prod-master-unit" onchange="empProdMasterSync('unit')">${allShipOptions}</select></td>
        <td style="text-align:center;"><input type="text" style="width:60px;font-size:11px;font-weight:normal;" id="emp-prod-master-qty" placeholder="" oninput="empProdMasterSync('qty')" onchange="empProdMasterSync('qty')" /></td>
        <td style="text-align:center;" id="emp-prod-total-credits">0</td>
        <td></td><td></td>
      </tr>`;
      html += '</tbody></table>';
      html += `<div style="margin-top:6px;font-size:11px;">
        <label><input type="checkbox" id="emp-prod-fast"> Fast Production (pay +40% to build units in half the time)</label>
      </div>`;
      html += `<div style="text-align:center;margin-top:8px;">
        <button class="input-button" onclick="empireProductionSubmit()">Submit</button>
      </div>`;
      html += `<div style="font-size:10px;color:var(--text-dim);margin-top:8px;">
        <div>[x] is the value calculated with the commander effect.</div>
        <div>Tip: It's possible to use the m,h,d keywords (minutes, hours, days) in the quantity field, e.g. 8h.</div>
      </div>`;
      container.innerHTML = html;
    } else if (_empireSubtab === 'economy') {
      try {
        const econRes = await apiFetch('/api/empire/economy');
        const econ = econRes ? await econRes.json() : {};
        const eb = econ.bases || [];
        const occ = econ.occupied_bases || [];
        const s = econ.summary || {};

        // Bases Economy table
        let html = `<div style="text-align:center;font-size:14px;margin-bottom:8px;color:var(--text-bright);"><b>B</b>ases Economy</div>`;
        html += `<table class="data-table" style="width:100%;font-size:12px;">
          <thead><tr>
            <th style="text-align:left;">Base</th>
            <th style="text-align:left;">Location</th>
            <th style="text-align:center;">Economy</th>
            <th style="text-align:center;">Pillage</th>
            <th style="text-align:center;">Occupier</th>
            <th style="text-align:right;">Income</th>
          </tr></thead><tbody>`;
        for (const b of eb) {
          const econDisplay = b.economy === b.economy_max ? `${b.economy}` : `${b.economy} / ${b.economy_max}`;
          const occupier = b.occupier ? `<span class="text-danger">${escStr(b.occupier)}</span>` : '';
          const pillage = b.pillage ? `<span class="text-dim">${escStr(b.pillage)}</span>` : '';
          html += `<tr>
            <td class="text-accent">${escStr(b.name)}</td>
            <td>${coordLink(b.coords)}</td>
            <td style="text-align:center;">${econDisplay}</td>
            <td style="text-align:center;">${pillage}</td>
            <td style="text-align:center;">${occupier}</td>
            <td style="text-align:right;" class="font-mono">${b.income}</td>
          </tr>`;
        }
        html += '</tbody></table>';

        // Occupied Bases section
        html += `<div style="text-align:center;font-size:14px;margin:16px 0 8px;color:var(--text-bright);"><b>O</b>ccupied Bases</div>`;
        if (occ.length) {
          html += `<table class="data-table" style="width:100%;font-size:12px;">
            <thead><tr>
              <th style="text-align:left;">Base</th>
              <th style="text-align:left;">Location</th>
              <th style="text-align:left;">Owner</th>
              <th style="text-align:center;">Economy</th>
              <th style="text-align:right;">Income</th>
            </tr></thead><tbody>`;
          for (const o of occ) {
            html += `<tr>
              <td class="text-accent">${escStr(o.name)}</td>
              <td>${coordLink(o.coords)}</td>
              <td>${escStr(o.owner)}</td>
              <td style="text-align:center;">${o.economy === o.economy_max ? o.economy : o.economy + ' / ' + o.economy_max}</td>
              <td style="text-align:right;" class="font-mono">${o.income}</td>
            </tr>`;
          }
          html += '</tbody></table>';
        } else {
          html += `<div class="text-dim" style="text-align:center;font-size:12px;">You don't have any occupied bases.</div>`;
        }

        // Summary table
        html += `<div style="margin-top:16px;">
          <table style="width:auto;margin:0 auto;font-size:12px;border-collapse:collapse;">
            <thead><tr>
              <th colspan="3" style="text-align:center;padding-bottom:6px;font-weight:bold;color:var(--text-bright);">Summary</th>
            </tr><tr style="border-bottom:1px solid var(--border);">
              <th style="text-align:left;padding:4px 16px;"></th>
              <th style="text-align:center;padding:4px 16px;color:var(--text-dim);">Quantity</th>
              <th style="text-align:right;padding:4px 16px;color:var(--text-dim);">Income</th>
            </tr></thead>
            <tbody>
              <tr>
                <td style="padding:4px 16px;">Bases</td>
                <td style="text-align:center;padding:4px 16px;">${s.base_count}</td>
                <td style="text-align:right;padding:4px 16px;" class="font-mono">${s.base_income}</td>
              </tr>
              <tr>
                <td style="padding:4px 16px;">Occupied Bases</td>
                <td style="text-align:center;padding:4px 16px;">${s.occupied_count} (max. ${s.max_occupied})</td>
                <td style="text-align:right;padding:4px 16px;" class="font-mono">${s.occupied_income}</td>
              </tr>
              <tr>
                <td style="padding:4px 16px;">Trade Routes</td>
                <td style="text-align:center;padding:4px 16px;">${s.trade_count}</td>
                <td style="text-align:right;padding:4px 16px;" class="font-mono">${s.trade_income}</td>
              </tr>
              <tr style="border-top:1px solid var(--border);">
                <td style="padding:6px 16px;font-weight:bold;color:var(--text-bright);">Economy</td>
                <td></td>
                <td style="text-align:right;padding:6px 16px;font-weight:bold;color:var(--text-bright);" class="font-mono">${s.total_economy}</td>
              </tr>
              <tr>
                <td style="padding:4px 16px;font-weight:bold;color:var(--text-bright);">Empire Income${s.capital_penalty ? ' <span class="text-warn" style="font-weight:normal;font-size:10px;">(-' + s.capital_penalty_pct + '% Capital occupied)</span>' : ''}</td>
                <td></td>
                <td style="text-align:right;padding:4px 16px;font-weight:bold;color:${s.capital_penalty ? 'var(--text-warn)' : 'var(--text-bright)'};" class="font-mono">${s.empire_income}</td>
              </tr>
            </tbody>
          </table>
        </div>`;
        container.innerHTML = html;
      } catch (e) { container.innerHTML = '<span class="text-danger">Error loading economy</span>'; console.error(e); }
    } else if (_empireSubtab === 'capacities') {
      let html = `<div style="text-align:center;font-size:14px;margin-bottom:8px;color:var(--text-bright);"><b>B</b>ases Processing Capacities</div>`;
      html += `<table class="data-table" style="width:100%;font-size:12px;"><thead><tr>
        <th>Name</th><th class="mobile-hide">Location</th><th class="mobile-hide">Type</th><th>Economy</th>
        <th>Construction</th><th>Production (Shipyards)</th><th>Research (Labs)</th><th class="mobile-hide">Commander</th>
      </tr></thead><tbody>`;
      let sumEcon = 0, sumConstr = 0, sumProd = 0, sumResearch = 0;
      for (const b of bases) {
        const econStr = b.economy === (b.economy_max || b.economy) ? `${b.economy}` : `${b.economy} / ${b.economy_max}`;
        const prodStr = `${b.production} (${b.shipyard_level || 0})`;
        const researchStr = `${b.research_capacity || 0} (${b.research_lab_level || 0})`;
        const cmdr = b.commander_name || 'â€”';
        sumEcon += b.economy || 0;
        sumConstr += b.construction || 0;
        sumProd += b.production || 0;
        sumResearch += b.research_capacity || 0;
        html += `<tr>
          <td class="text-accent">${escStr(b.name)}</td>
          <td class="mobile-hide">${coordLink(b.coords)}</td>
          <td class="mobile-hide">${astroName(b.planet_type || 'rocky')}</td>
          <td>${econStr}</td>
          <td>${b.construction}</td>
          <td>${prodStr}</td>
          <td>${researchStr}</td>
          <td class="mobile-hide text-dim">${escStr(cmdr)}</td>
        </tr>`;
      }
      html += `<tr style="border-top:1px solid var(--border);font-weight:bold;">
        <td style="text-align:right;">Sum</td><td class="mobile-hide"></td><td class="mobile-hide"></td>
        <td>${sumEcon}</td><td>${sumConstr}</td><td>${sumProd}</td><td>${sumResearch}</td><td class="mobile-hide"></td>
      </tr>`;
      html += '</tbody></table>';
      html += `<div class="text-dim" style="text-align:center;font-size:10px;margin-top:4px;">Occupied bases have capacities reduced and are shown in red.</div>`;
      container.innerHTML = html;
    } else if (_empireSubtab === 'structures') {
      const structureColumns = [
        { kind: 'building', name: 'Urban Structures' },
        { kind: 'building', name: 'Solar Plants' },
        { kind: 'building', name: 'Gas Plants' },
        { kind: 'building', name: 'Fusion Plants' },
        { kind: 'building', name: 'Antimatter Plants' },
        { kind: 'building', name: 'Orbital Plants' },
        { kind: 'building', name: 'Research Labs' },
        { kind: 'building', name: 'Metal Refineries' },
        { kind: 'building', name: 'Crystal Mines' },
        { kind: 'building', name: 'Robotic Factories' },
        { kind: 'building', name: 'Shipyard' },
        { kind: 'building', name: 'Orbital Shipyard' },
        { kind: 'building', name: 'Spaceports' },
        { kind: 'building', name: 'Command Centers' },
        { kind: 'building', name: 'Nanite Factories' },
        { kind: 'building', name: 'Android Factories' },
        { kind: 'building', name: 'Economic Centers' },
        { kind: 'building', name: 'Terraform' },
        { kind: 'building', name: 'Multi-Level Platforms' },
        { kind: 'building', name: 'Orbital Base' },
        { kind: 'building', name: 'Biosphere Modification' },
        { kind: 'building', name: 'Capital' },
        { kind: 'building', name: 'Jump Gate' },
        { kind: 'defense', name: 'Barracks' },
        { kind: 'defense', name: 'Laser Turrets' },
        { kind: 'defense', name: 'Missile Turrets' },
        { kind: 'defense', name: 'Plasma Turrets' },
        { kind: 'defense', name: 'Ion Turrets' },
        { kind: 'defense', name: 'Photon Turrets' },
        { kind: 'defense', name: 'Disruptor Turrets' },
        { kind: 'defense', name: 'Deflection Shields' },
        { kind: 'defense', name: 'Planetary Shield' },
        { kind: 'defense', name: 'Planetary Ring' },
      ];
      const fmtDefenseUnits = (value) => {
        const num = Number(value || 0);
        if (!Number.isFinite(num) || num <= 0) return '';
        const rounded = Math.round(num * 100) / 100;
        if (Math.abs(rounded - Math.round(rounded)) < 0.001) return String(Math.round(rounded));
        if (Math.abs((rounded * 10) - Math.round(rounded * 10)) < 0.001) return rounded.toFixed(1).replace(/\.0$/, '');
        return rounded.toFixed(2).replace(/0$/, '').replace(/\.$/, '');
      };
      const getStructureCellValue = (base, column) => {
        const items = column.kind === 'building' ? (base.buildings || []) : (base.defenses || []);
        const item = items.find(x => x.name === column.name);
        if (!item) return '';
        if (column.kind === 'building') {
          return item.level > 0 ? String(item.level) : '';
        }
        const totalUnits = Math.max(0, Number(item.quantity ?? ((item.level || 0) * 5)) || 0);
        if (totalUnits <= 0) return '';
        const effectiveness = Math.max(0, Math.min(1, Number(base.defense_effectiveness ?? 1) || 0));
        const currentUnits = Math.min(totalUnits, totalUnits * effectiveness);
        const currentText = fmtDefenseUnits(currentUnits);
        const totalText = fmtDefenseUnits(totalUnits);
        return currentText && totalText && currentText !== totalText ? `${currentText}/${totalText}` : totalText;
      };
      let html = `<div style="text-align:center;font-size:14px;margin-bottom:8px;color:var(--text-bright);"><b>S</b>tructures</div>`;
      html += `<div class="empire-structures-wrap"><table class="data-table empire-structures-grid"><thead><tr><th class="empire-structures-base-head">Base</th>`;
      for (const column of structureColumns) {
        html += `<th class="empire-vertical-header"><span class="empire-vertical-label">${escStr(column.name)}</span></th>`;
      }
      html += '</tr></thead><tbody>';
      for (const b of bases) {
        html += `<tr><td class="text-accent empire-structures-base-cell">${escStr(b.name)}</td>`;
        for (const column of structureColumns) {
          html += `<td class="empire-structures-value-cell">${getStructureCellValue(b, column)}</td>`;
        }
        html += '</tr>';
      }
      html += '</tbody></table></div>';
      container.innerHTML = html;
    } else if (_empireSubtab === 'fleets') {
      // Roster-driven columns (data-driven): every ship in the active catalog,
      // so custom / ships_extra ships are never hidden here.
      const _fSpecs = await getShipSpecs();
      const shipCols = Object.keys(_fSpecs).filter(k => k !== 'goods');  // ships only (getShipSpecs merges in goods)
      const _colAbbrev = (key) => {
        const m = key.match(/^(.)\w*_ship_(\d+)$/);   // legacy small_ship_1 -> S1, medium_ship_3 -> M3
        if (m) return m[1].toUpperCase() + m[2];
        return (_fSpecs[key]?.name || key).replace(/[^A-Za-z0-9]/g, '').slice(0, 2).toUpperCase();
      };
      let html = `<div style="text-align:center;font-size:14px;margin-bottom:8px;color:var(--text-bright);"><b>F</b>leets</div>`;
      html += `<table class="data-table" style="width:100%;font-size:10px;"><thead><tr>
        <th>Fleet</th><th>Location</th>`;
      for (const sc of shipCols) html += `<th title="${escStr(_fSpecs[sc]?.name || sc)}" style="padding:2px 3px;">${_colAbbrev(sc)}</th>`;
      html += `<th>Size</th></tr></thead><tbody>`;
      for (const f of fleets) {
        const loc = f.location_name || f.base_name || '?';
        html += `<tr><td class="text-accent" style="white-space:nowrap;">${escStr(f.name)}</td>
          <td style="white-space:nowrap;">${escStr(loc)}</td>`;
        for (const sc of shipCols) {
          const count = (f.ships && f.ships[sc]) || 0;
          html += `<td style="text-align:center;padding:2px 3px;${count ? 'color:var(--text-bright)' : 'color:var(--border)'}">${count || ''}</td>`;
        }
        html += `<td style="text-align:right;">${fmtNum(f.total_ships || 0)}</td></tr>`;
      }
      if (!fleets.length) html += `<tr><td colspan="${shipCols.length + 3}" class="text-dim">No fleets</td></tr>`;
      html += '</tbody></table>';
      container.innerHTML = html;
    } else if (_empireSubtab === 'units') {
      const shipTotals = {};
      let totalSize = 0;
      for (const f of fleets) {
        for (const [type, count] of Object.entries(f.ships || {})) {
          if (count > 0) shipTotals[type] = (shipTotals[type] || 0) + count;
        }
      }
      const specs = await getShipSpecs();
      // Units table (ships)
      let html = `<div style="text-align:center;font-size:14px;margin-bottom:8px;color:var(--text-bright);"><b>U</b>nits</div>`;
      html += `<table class="data-table" style="width:100%;font-size:12px;"><thead><tr>
        <th>Unit</th><th>Quantity</th><th>Unit Cost</th><th>Total Cost</th><th>Quant. in prod.</th>
        <th>Mod. Speed</th><th>Weapons</th><th>Mod. Attack/Armour (Shield)</th>
      </tr></thead><tbody>`;
      let grandTotal = 0;
      for (const [type, count] of Object.entries(shipTotals)) {
        const sp = specs[type];
        if (!sp) continue;
        const cost = sp.cost || 0;
        // cost may be a per-resource dict (multi-resource rulesets): display via
        // formatResourceCost; totals aggregate the summed scalar value.
        const total = count * costValue(cost);
        grandTotal += total;
        const atkStr = `${sp.attack || 0} / ${sp.armour || 0}${sp.shield ? ' ('+sp.shield+')' : ''}`;
        html += `<tr>
          <td class="text-bright">${tName(sp.name || type)}</td>
          <td style="text-align:center;">${fmtNum(count)}</td>
          <td style="text-align:right;">${formatResourceCost(cost)}</td>
          <td style="text-align:right;">${fmtNum(total)}</td>
          <td style="text-align:center;">0</td>
          <td style="text-align:center;">${sp.speed || 0}</td>
          <td>${sp.weapon_type || 'Laser'}</td>
          <td>${atkStr}</td>
        </tr>`;
      }
      html += `<tr style="border-top:1px solid var(--border);font-weight:bold;">
        <td>Total</td><td></td><td></td><td style="text-align:right;">${fmtNum(grandTotal)}</td>
        <td colspan="4"></td></tr>`;
      html += '</tbody></table>';

      // Summary stats at bottom
      html += `<div style="margin-top:16px;text-align:center;">
        <table class="awe-field-table" style="display:inline-table;">
          <tr><td>Number of Bases</td><td>${bases.length}</td></tr>
          <tr><td>Number of Occupied Bases</td><td>${stats.occupied_count || 0}</td></tr>
          <tr><td>Computer Technology Level</td><td>${stats.computer_tech || 0}</td></tr>
          <tr><td style="font-weight:bold;">Maximum Number of Fleets</td><td style="font-weight:bold;">${stats.max_fleet_count || 5}</td></tr>
          <tr><td>Number of Fleets</td><td>${stats.fleet_count || 0}</td></tr>
          <tr><td colspan="2" style="padding-top:6px;"></td></tr>
          <tr><td>Fleet Size</td><td>${fmtNum(stats.fleet_size || 0)}</td></tr>
          <tr><td>Fleet Limit</td><td>${fmtNum(stats.max_fleet_size || 0)}</td></tr>
        </table>
      </div>`;
      container.innerHTML = html;
    }
  } catch (e) { container.innerHTML = `<div class="text-dim">Error loading empire data</div>`; console.error(e); }
}

async function renderEmpireTrade(container) {
  try {
    const [basesRes, routesRes] = await Promise.all([apiFetch('/api/bases'), apiFetch('/api/trade-routes')]);
    const bases = basesRes ? await basesRes.json() : [];
    const routeData = routesRes ? await routesRes.json() : {};
    const routes = routeData.routes || [];
    const numPlayers = routeData.num_players || 0;

    // Bases table with economy and trade route counts
    let html = `<div style="text-align:center;font-size:14px;margin-bottom:8px;color:var(--text-bright);"><b>B</b>ases</div>`;
    html += `<table class="data-table" style="width:100%;font-size:12px;"><thead><tr>
      <th>Name</th><th>Location</th><th>Economy</th><th>Trade Routes</th>
    </tr></thead><tbody>`;
    let totalRoutes = 0;
    for (const b of bases) {
      const econStr = b.economy === (b.economy_max || b.economy) ? `${b.economy}` : `${b.economy} / ${b.economy_max}`;
      const rc = b.trade_route_count || 0;
      const maxR = b.max_trade_routes || 4;
      totalRoutes += rc;
      html += `<tr>
        <td class="text-accent">${escStr(b.name)}</td>
        <td>${coordLink(b.coords)}</td>
        <td>${econStr}</td>
        <td>${rc} / ${maxR}</td>
      </tr>`;
    }
    html += `<tr style="border-top:1px solid var(--border);font-weight:bold;">
      <td colspan="3" style="text-align:right;">Total</td><td>${totalRoutes}</td></tr>`;
    html += '</tbody></table>';

    // Trade routes detail
    html += `<div style="text-align:center;font-size:14px;margin:16px 0 8px;color:var(--text-bright);"><b>T</b>rade Routes</div>`;
    if (routes.length) {
      html += `<table class="data-table" style="width:100%;font-size:12px;"><thead><tr>
        <th>Base/Player 1</th><th>Base/Player 2</th><th>Base 1 Econ.</th><th>Base 2 Econ.</th>
        <th>Distance</th><th>Status</th><th>Income</th>
      </tr></thead><tbody>`;
      let totalIncome = 0;
      for (const r of routes) {
        if (r.is_closing) continue;
        const baseA = typeof r.base_a === 'object' ? r.base_a.name : r.base_a;
        const baseB = typeof r.base_b === 'object' ? r.base_b.name : r.base_b;
        const status = r.is_pending ? 'Pending' : 'Active';
        const inc = Math.ceil(r.income || 0);
        totalIncome += inc;
        html += `<tr>
          <td>${escStr(baseA || '?')}</td><td>${escStr(baseB || '?')}</td>
          <td style="text-align:center;">${r.base_a_econ || ''}</td>
          <td style="text-align:center;">${r.base_b_econ || ''}</td>
          <td style="text-align:center;">${r.distance || ''}</td>
          <td>${status}</td>
          <td style="text-align:right;">${inc}</td>
        </tr>`;
      }
      html += `<tr style="border-top:1px solid var(--border);font-weight:bold;">
        <td colspan="6" style="text-align:right;">Total</td><td style="text-align:right;">${totalIncome}</td></tr>`;
      html += '</tbody></table>';
    } else {
      html += '<div class="text-dim" style="text-align:center;font-size:12px;">No trade routes.</div>';
    }

    // Trade formula
    html += `<div style="margin-top:12px;text-align:center;font-size:11px;color:var(--text-dim);border-top:1px solid var(--border-dim,#333);padding-top:8px;">
      <strong>Trade Formula</strong><br>
      Trade Income = &radic;(Lowest base's income) &times; [ 1 + &radic;(2&times;Distance)/75 + &radic;(Players)/10 ]<br>
      Players = Total players involved in trading = ${numPlayers}
    </div>`;

    container.innerHTML = html;
  } catch (e) { container.innerHTML = '<div class="text-danger">Error loading trade data</div>'; console.error(e); }
}

async function renderEmpireTechnologies(container) {
  try {
    const [researchRes, basesRes] = await Promise.all([apiFetch('/api/research'), apiFetch('/api/bases')]);
    const techs = researchRes ? await researchRes.json() : [];
    const bases = basesRes ? await basesRes.json() : [];

    let html = `<div style="text-align:center;font-size:14px;margin-bottom:8px;color:var(--text-bright);"><b>T</b>echnologies</div>`;
    html += `<table class="data-table" style="width:100%;font-size:12px;"><thead><tr>
      <th style="text-align:left;">Technology</th><th>Research Cost</th><th>Labs Required</th>
      <th>Technologies Required</th><th>Actual Level</th><th>Bonus</th>
    </tr></thead><tbody>`;
    for (const tech of techs) {
      const bonus = tech.level > 0 ? `+${tech.level * 5}%` : '+0%';
      const status = tech.is_researching ? `<span class="countdown" data-end="${tech.end_time}">${fmtTime(Math.max(0,(serverDate(tech.end_time)-Date.now())/1000))}</span>` : (tech.level > 0 ? 'working' : '');
      html += `<tr>
        <td><span class="text-bright" style="font-weight:bold;">${escStr(tName(tech.name))}</span> (Level ${tech.level})
          <br><span class="text-dim" style="font-size:10px;">${escStr(tech.description || '')}</span></td>
        <td style="text-align:right;">${tech.next_cost ? formatResourceCost(tech.next_cost) : ''}</td>
        <td style="text-align:center;">${tech.lab_req || ''}</td>
        <td class="text-dim" style="font-size:10px;">${escStr(tech.prereqs_text || '')}</td>
        <td style="text-align:center;">${tech.level}</td>
        <td style="text-align:center;">${bonus}</td>
      </tr>`;
    }
    html += '</tbody></table>';

    // Base research queues at bottom
    const researchBases = bases.filter(b => b.research_queue);
    if (researchBases.length) {
      html += `<div style="margin-top:16px;text-align:center;font-size:14px;color:var(--text-bright);"><b>B</b>ases Research</div>`;
      html += `<table class="data-table" style="width:100%;font-size:12px;"><thead><tr>
        <th>Base</th><th>Location</th><th>Capacity cred./h (Labs)</th><th>Research</th><th>Time</th>
      </tr></thead><tbody>`;
      for (const b of researchBases) {
        const rq = b.research_queue;
        const timeStr = rq.end_time ? `<span class="countdown" data-end="${rq.end_time}">${fmtTime(Math.max(0,(serverDate(rq.end_time)-Date.now())/1000))}</span>` : '';
        html += `<tr>
          <td class="text-accent">${escStr(b.name)}</td>
          <td>${coordLink(b.coords)}</td>
          <td>${b.research_capacity || 0} (${b.research_lab_level || 0})</td>
          <td>${escStr(rq.name)} (${rq.target_level})</td>
          <td>${timeStr}</td>
        </tr>`;
      }
      html += '</tbody></table>';
    }

    container.innerHTML = html;
  } catch (e) { container.innerHTML = '<div class="text-danger">Error loading technologies</div>'; console.error(e); }
}

// â”€â”€ Server time display (title=”YYYY/MM/DD HH:MM:SS”, text=”D Mon YYYY, HH:MM:SS”) â”€â”€

// Empire production submit helpers
function _parseQtyField(raw, prodRate, shipCost) {
  // Support m,h,d keywords: "8h" = build for 8 hours worth of production
  if (!raw) return 0;
  raw = raw.toString().trim().toLowerCase();
  const timeMatch = raw.match(/^(\d+(?:\.\d+)?)\s*(m|h|d)$/);
  if (timeMatch && prodRate > 0 && shipCost > 0) {
    const val = parseFloat(timeMatch[1]);
    const unit = timeMatch[2];
    let seconds = 0;
    if (unit === 'm') seconds = val * 60;
    else if (unit === 'h') seconds = val * 3600;
    else if (unit === 'd') seconds = val * 86400;
    // time_per_ship = shipCost / prodRate * 3600 (in seconds)
    const timePerShip = shipCost / prodRate * 3600;
    return Math.max(1, Math.floor(seconds / timePerShip));
  }
  return parseInt(raw) || 0;
}

function _empProdTouch() { _empProdInteracting = true; }

function empProdMasterSync(field) {
  _empProdTouch();
  const masterUnit = document.getElementById('emp-prod-master-unit');
  const masterQty = document.getElementById('emp-prod-master-qty');
  if (!masterUnit || !masterQty) { console.warn('Master inputs not found'); return; }
  // Copy master value to all base rows
  const baseSelects = document.querySelectorAll('select[id^="emp-prod-unit-"]');
  baseSelects.forEach(sel => {
    if (sel.id === 'emp-prod-master-unit') return; // skip master itself
    const baseId = sel.id.replace('emp-prod-unit-', '');
    if (field === 'unit') {
      sel.value = masterUnit.value;
    }
    if (field === 'qty') {
      const qtyInput = document.getElementById(`emp-prod-qty-${baseId}`);
      if (qtyInput) qtyInput.value = masterQty.value;
    }
    empProdRecalcRow(parseInt(baseId));
  });
}

function empProdRecalcRow(baseId) {
  _empProdTouch();
  const sel = document.getElementById(`emp-prod-unit-${baseId}`);
  const qtyInput = document.getElementById(`emp-prod-qty-${baseId}`);
  const row = document.getElementById(`emp-prod-row-${baseId}`);
  if (!sel || !qtyInput || !row) return;
  const prodRate = parseFloat(sel.dataset.prod || '0');
  const shipType = sel.value;
  const sp = window._empShipSpecs?.[shipType];
  if (!sp) return;
  const fast = document.getElementById('emp-prod-fast')?.checked;
  const costMult = fast ? 1.4 : 1;
  const timeMult = fast ? 0.5 : 1;
  const count = _parseQtyField(qtyInput.value, prodRate, costValue(sp.cost));
  const credCell = row.querySelector('.emp-prod-cred');
  const timeCell = row.querySelector('.emp-prod-time');
  const totalCell = row.querySelector('.emp-prod-total');
  const queueRemain = parseFloat(sel.dataset.queueRemain || '0');
  if (count > 0) {
    // sp.cost may be a per-resource dict (multi-resource rulesets): arithmetic
    // uses the scalar value; the cell displays the real per-resource cost and
    // carries the scalar in data-value for the grand-total summer.
    const unitValue = costValue(sp.cost);
    const costScalar = unitValue * count * costMult;
    const timePerShip = prodRate > 0 ? (unitValue / prodRate * 3600 * timeMult) : 0;
    const buildTime = timePerShip * count;
    const totalTime = queueRemain + buildTime;
    if (credCell) {
      credCell.innerHTML = formatResourceCost(scaleCost(sp.cost, count * costMult));
      credCell.dataset.value = String(Math.round(costScalar));
    }
    if (timeCell) timeCell.textContent = fmtTime(timePerShip);
    if (totalCell) totalCell.textContent = fmtTime(totalTime);
  } else {
    if (credCell) { credCell.textContent = ''; delete credCell.dataset.value; }
    if (timeCell) timeCell.textContent = '';
    if (totalCell) totalCell.textContent = queueRemain > 0 ? fmtTime(queueRemain) : '-';
  }
  _empProdUpdateTotalCredits();
}

function _empProdUpdateTotalCredits() {
  let total = 0;
  document.querySelectorAll('.emp-prod-cred').forEach(td => {
    // data-value carries the scalar cost (the cell may render per-resource HTML)
    const v = parseFloat(td.dataset.value || (td.textContent || '0').replace(/,/g, ''));
    if (v > 0) total += v;
  });
  const el = document.getElementById('emp-prod-total-credits');
  if (el) el.textContent = fmtNum(Math.round(total));
}

async function empireProductionSubmit() {
  const selects = document.querySelectorAll('[id^="emp-prod-unit-"]');
  const masterUnit = document.getElementById('emp-prod-master-unit');
  const masterQtyEl = document.getElementById('emp-prod-master-qty');
  const masterRaw = masterQtyEl?.value?.trim() || '';
  const fast = document.getElementById('emp-prod-fast')?.checked || false;

  let built = 0;
  for (const sel of selects) {
    const baseId = sel.id.replace('emp-prod-unit-', '');
    const qtyInput = document.getElementById(`emp-prod-qty-${baseId}`);
    const prodRate = parseFloat(sel.dataset.prod || '0');
    let shipType, rawQty;

    if (masterRaw) {
      // Master input: copy unit + quantity to all bases
      shipType = masterUnit.value;
      rawQty = masterRaw;
    } else {
      shipType = sel.value;
      rawQty = qtyInput?.value || '0';
    }

    const sp = window._empShipSpecs?.[shipType];
    const shipCost = sp ? costValue(sp.cost) : 1;  // scalar for time math (dict in multi-resource)
    const count = _parseQtyField(rawQty, prodRate, shipCost);
    if (!count || count < 1) continue;

    try {
      const res = await apiFetch('/api/fleets/build', {
        method: 'POST',
        body: JSON.stringify({ base_id: parseInt(baseId), ship_type: shipType, count, fast_production: fast })
      });
      const data = await res.json();
      if (data.success) built++;
      else console.warn(`Base ${baseId}:`, data.detail);
    } catch (e) { console.error(e); }
  }
  if (built > 0) {
    showSnack(`Production started on ${built} base(s)`);
    await updateHUD();
    loadEmpireTab();
  } else {
    showSnack('No production orders submitted');
  }
}

// â”€â”€ Mobile navigation helpers â”€â”€
