/* ============================================================
   AstroWebEngine - Frontend (fleets_attack.js)
   Fleet attack preview/confirm/submit and piracy flows
   Split from fleets.js for easier maintenance
   ============================================================ */
function renderFleetAttack(f) {
  if (f.is_moving) return '<div class="text-dim" style="padding:12px;">Fleet must arrive before attacking.</div>';
  if (!f.base_id && !f.location_planet_id) {
    return '<div class="text-dim" style="padding:12px;">Fleet must be parked at a location before attacking.</div>';
  }
  return `<div id="attack-tab-content-${f.id}" style="padding:12px;">
    <h4 style="margin:0 0 8px;">Attack</h4>
    <div id="attack-enemies-${f.id}"><span class="text-dim">Loading...</span></div>
  </div>`;
}

async function loadAttackEnemies(fleetId) {
  const container = document.getElementById(`attack-enemies-${fleetId}`);
  if (!container) return;
  try {
    const res = await apiFetch(`/api/fleets/${fleetId}/attack-preview`);
    if (!res || !res.ok) {
      const data = await res?.json().catch(() => ({}));
      container.innerHTML = `<span class="text-danger">${typeof data.detail === 'string' ? escStr(data.detail) : 'Cannot attack here'}</span>`;
      return;
    }
    const d = await res.json();
    const targets = d.targets || [];
    if (!targets.length) {
      container.innerHTML = '<div class="text-dim">No hostile targets at this location.</div>';
      return;
    }
    const rowTargets = targets.filter(t => t.list_section !== 'action');
    const actionTargets = targets.filter(t => t.list_section === 'action');
    let rows = '';
    for (const t of rowTargets) {
      const playerText = t.level ? `${escStr(t.player)} <span class="text-dim">lv ${t.level}</span>` : escStr(t.player);
      const warnings = (t.warnings || []).map(w => `<div class="text-danger" style="font-size:10px;margin-top:2px;">${escStr(w)}</div>`).join('');
      let actionHtml = '';
      if (t.can_attack === false) {
        actionHtml = `<span class="text-dim">${escStr(t.reason || 'Cannot attack')}</span>`;
      } else {
        const targetUserId = Number.isFinite(t.player_id) ? t.player_id : 'null';
        const targetFleetId = Number.isFinite(t.fleet_id) ? t.fleet_id : 'null';
        const attackMode = t.attack_mode ? `'${escStr(t.attack_mode)}'` : 'null';
        actionHtml = `<button class="btn btn-danger btn-sm" onclick="showAttackConfirm(${fleetId}, ${targetUserId}, ${targetFleetId}, ${attackMode})">${escStr(t.attack_label || 'Attack')}</button>`;
      }
      rows += `<tr>
        <td>
          <div>${escStr(t.fleet_name)}</div>
          ${t.defense_pct != null ? `<div class="text-dim" style="font-size:10px;">Defenses: ${t.defense_pct}%</div>` : ''}
        </td>
        <td>${playerText}${warnings}</td>
        <td>${fmtNum(t.size || 0)}</td>
        <td>${actionHtml}</td>
      </tr>`;
    }
    let actionRows = '';
    if (actionTargets.length) {
      actionRows += '<tr><th colspan="4">&nbsp;</th></tr>';
      for (const t of actionTargets) {
        const warnings = (t.warnings || []).map(w => `<div class="text-danger" style="font-size:10px;margin-top:4px;">${escStr(w)}</div>`).join('');
        let actionHtml = '';
        if (t.can_attack === false) {
          actionHtml = `<span class="text-dim">${escStr(t.reason || 'Cannot attack')}</span>`;
        } else {
          const targetUserId = Number.isFinite(t.player_id) ? t.player_id : 'null';
          const targetFleetId = Number.isFinite(t.fleet_id) ? t.fleet_id : 'null';
          const attackMode = t.attack_mode ? `'${escStr(t.attack_mode)}'` : 'null';
          actionHtml = `<button class="btn btn-danger btn-sm" onclick="showAttackConfirm(${fleetId}, ${targetUserId}, ${targetFleetId}, ${attackMode})">${escStr(t.attack_label || 'Attack')}</button>`;
        }
        actionRows += `<tr><th colspan="4" style="text-align:center;">${actionHtml}${warnings}</th></tr>`;
      }
    }
    container.innerHTML = `<table class="data-table" style="width:100%;font-size:12px;margin-bottom:12px;">
      <thead><tr><th>Fleet</th><th>Player</th><th>Size</th><th>Attack</th></tr></thead>
      <tbody>${rows}${actionRows}</tbody>
    </table>`;
  } catch(e) { container.innerHTML = '<span class="text-danger">Error loading attack info</span>'; console.error(e); }
}

function _fleetSize(f) {
  let total = 0;
  if (f.ships) for (const c of Object.values(f.ships)) total += c;
  return total;
}

async function showAttackConfirm(fleetId, targetUserId = null, targetFleetId = null, attackMode = null) {
  const container = document.getElementById(`attack-tab-content-${fleetId}`);
  if (!container) return;
  container.innerHTML = '<span class="text-dim">Loading battle preview...</span>';
  let d;
  try {
    const params = new URLSearchParams();
    if (targetUserId != null) params.set('target_user_id', targetUserId);
    if (targetFleetId != null) params.set('target_fleet_id', targetFleetId);
    if (attackMode != null) params.set('attack_mode', attackMode);
    const qs = params.toString();
    const res = await apiFetch(`/api/fleets/${fleetId}/attack-preview${qs ? `?${qs}` : ''}`);
    if (!res || !res.ok) {
      const data = await res?.json().catch(() => ({}));
      container.innerHTML = `<span class="text-danger">${typeof data.detail === 'string' ? escStr(data.detail) : 'Failed to load preview'}</span>`;
      return;
    }
    d = await res.json();
  } catch (e) {
    container.innerHTML = '<span class="text-danger">Error loading preview</span>';
    return;
  }

  const fmtUnit = (list) => {
    if (!list || !list.length) return '<tr><td colspan="6" class="text-dim">None</td></tr>';
    return list.map(u => `<tr><td>${escStr(u.unit)}</td><td>${escStr(u.count)}</td><td>?</td><td>${escStr(u.attack)}</td><td>${escStr(u.armour)}</td><td>${escStr(u.shield)}</td></tr>`).join('');
  };

  let warningHtml = '';
  if (d.warnings && d.warnings.length) {
    warningHtml = d.warnings.map(w => `<div style="color:#f44;font-weight:bold;margin-bottom:6px;">${escStr(w)}</div>`).join('');
  }

  const defenderInfoRows = [];
  if (d.defender?.base_name) defenderInfoRows.push(`<tr><td>Base</td><td>${escStr(d.defender.base_name)}</td></tr>`);
  if (d.defender?.defense_pct != null) defenderInfoRows.push(`<tr><td>Start Defenses</td><td>${escStr(d.defender.defense_pct)}%</td></tr>`);
  if (d.defender?.defense_pct != null) defenderInfoRows.push('<tr><td>End Defenses</td><td>?</td></tr>');
  if (d.defender?.command_centers != null) defenderInfoRows.push(`<tr><td>Command Centers</td><td>${escStr(d.defender.command_centers)}</td></tr>`);

  container.innerHTML = `
    ${warningHtml}
    <h4 style="text-align:center;margin:8px 0;">Confirm Attack</h4>
    <table class="data-table" style="width:80%;margin:0 auto 12px;font-size:12px;">
      <tbody>
        <tr><td colspan="2" style="text-align:center;font-weight:bold;">Battle Report</td></tr>
        <tr><td>Location</td><td>${escStr(d.location)}${d.coords ? ` (${coordLink(d.coords)})` : ''}</td></tr>
        <tr><td>Server</td><td>${escStr(d.server || '')}</td></tr>
        <tr><td colspan="2" style="text-align:center;font-weight:bold;">Attack Force</td></tr>
        <tr><td>Player</td><td>${escStr(d.attacker.name)} &nbsp; lv ${escStr(d.attacker.level)}</td></tr>
        <tr><td>Fleet Name</td><td>${escStr(d.attacker.fleet_name)}</td></tr>
        <tr><td colspan="2" style="text-align:center;font-weight:bold;">Defensive Force</td></tr>
        <tr><td>Player</td><td>${escStr(d.defender.name)} &nbsp; lv ${escStr(d.defender.level)}</td></tr>
        <tr><td>Fleet Name</td><td>${escStr(d.defender.fleet_name)}</td></tr>
        ${defenderInfoRows.join('')}
      </tbody>
    </table>
    <table class="data-table" style="width:100%;font-size:12px;margin-bottom:8px;">
      <thead><tr><th colspan="6" style="text-align:center;">Attack Force</th></tr>
      <tr><th>Unit</th><th>Start Quant.</th><th>End Quant.</th><th>Attack</th><th>Armour</th><th>Shield</th></tr></thead>
      <tbody>${fmtUnit(d.attacker_forces)}</tbody>
    </table>
    <table class="data-table" style="width:100%;font-size:12px;margin-bottom:12px;">
      <thead><tr><th colspan="6" style="text-align:center;">Defensive Force</th></tr>
      <tr><th>Unit</th><th>Start Quant.</th><th>End Quant.</th><th>Attack</th><th>Armour</th><th>Shield</th></tr></thead>
      <tbody>${fmtUnit([...(d.defender_forces || []), ...(d.defender_defenses || [])])}</tbody>
    </table>
    <div style="text-align:center;">
      <button class="btn btn-danger btn-sm" onclick="attackFromFleet(${fleetId}, ${targetUserId == null ? 'null' : targetUserId}, ${targetFleetId == null ? 'null' : targetFleetId}, ${attackMode == null ? 'null' : `'${escStr(attackMode)}'`})" style="margin-right:16px;">Start Attack</button>
      <button class="btn btn-ghost btn-sm" onclick="switchFleetTab('attack')">Cancel Attack</button>
    </div>
  `;
}

// â”€â”€ Piracy â”€â”€
function renderFleetPiracy(f) {
  if (f.is_moving) return '<div class="text-dim" style="padding:12px;">Fleet must arrive before pirating.</div>';
  if (!f.base_id || f.base_is_mine) {
    return '<div class="text-dim" style="padding:12px;">Fleet must be at an enemy base to pirate trade routes.</div>';
  }
  return `<div style="padding:12px;">
    <h4 style="margin:0 0 8px;">Plunder Trade Routes</h4>
    <div id="piracy-routes-${f.id}"><span class="text-dim">Loading trade routes...</span></div>
  </div>`;
}

async function loadPiracyRoutes(fleetId, baseId) {
  const container = document.getElementById(`piracy-routes-${fleetId}`);
  if (!container) return;
  try {
    const res = await apiFetch(`/api/piracy/${baseId}`);
    if (!res || !res.ok) { container.innerHTML = '<span class="text-danger">Failed to load routes</span>'; return; }
    const data = await res.json();
    if (data.error) { container.innerHTML = `<span class="text-dim">${escStr(data.error)}</span>`; return; }
    const routes = data.routes || [];
    if (!routes.length) { container.innerHTML = '<div class="text-dim">No trade routes at this base.</div>'; return; }
    let html = `<table class="data-table" style="width:100%;font-size:12px;">
      <thead><tr><th>Linked to</th><th>Player</th><th>Distance</th><th>Status</th><th></th></tr></thead><tbody>`;
    for (const r of routes) {
      const plunderValue = Number.isFinite(r.plunder_value) ? fmtNum(r.plunder_value) : '0';
      const action = r.can_pirate
        ? `<a href="#" onclick="event.preventDefault();plunderTradeRoute(${r.id},${fleetId})" style="color:var(--danger,#c44);font-size:11px;">Plunder</a> <span style="font-size:11px;">(get ${plunderValue} cred.)*</span>`
        : `<span class="text-dim" style="font-size:11px;">you can't plunder this route</span>${r.reason ? `<div class="text-dim" style="font-size:10px;margin-top:2px;">${escStr(r.reason)}</div>` : ''}`;
      html += `<tr>
        <td>${escStr(r.linked_base)} <span class="text-dim">(${maybeCoordLink(r.linked_coords, 'text-dim')})</span></td>
        <td>${escStr(r.player)}</td>
        <td>${r.distance}</td>
        <td>Active</td>
        <td>${action}</td>
      </tr>`;
    }
    html += `</tbody></table>
      <div class="text-dim" style="font-size:11px;text-align:center;margin-top:8px;">
        * you must destroy trading players fleets and his guilds fleets before you can plunder trade routes.
      </div>`;
    container.innerHTML = html;
  } catch(e) { container.innerHTML = '<span class="text-danger">Error loading routes</span>'; }
}

async function plunderTradeRoute(routeId, fleetId) {
  if (!confirm('Plunder this trade route? It will be destroyed.')) return;
  try {
    const res = await apiFetch('/api/trade-routes/plunder', {
      method: 'POST', body: JSON.stringify({ trade_route_id: routeId })
    });
    const data = await res.json();
    if (data.success) {
      showSnack(`Plundered trade route â€” gained ${data.plunder} credits`);
      const fleet = _allFleets.find(f => f.id === fleetId);
      if (fleet) loadPiracyRoutes(fleetId, fleet.base_id);
    } else {
      showSnack(typeof data.detail === 'string' ? data.detail : 'Plunder failed');
    }
  } catch(e) { console.error(e); }
}

// â”€â”€ Disband â”€â”€

async function attackFromFleet(fleetId, targetUserId = null, targetFleetId = null, attackMode = null) {
  try {
    const res = await apiFetch('/api/fleets/attack', {
      method: 'POST',
      body: JSON.stringify({
        fleet_id: fleetId,
        target_user_id: targetUserId,
        target_fleet_id: targetFleetId,
        attack_mode: attackMode
      })
    });
    const data = await res.json();
    if (data.success) {
      const r = data.report;
      const txt = r.result === 'attacker_wins' ? 'Victory!' : (r.result === 'defender_wins' ? 'Defeat!' : 'Draw');
      let extra = '';
      if (r.debris) extra += ` Debris: ${fmtNum(r.debris)} cr`;
      if (r.pillage) extra += ` Pillaged: ${fmtNum(r.pillage)} cr`;
      if (r.occupied) extra += ' - Base Occupied!';
      showSnack(`${txt}${extra}`);
      await loadFleets(); await updateHUD();
    } else showSnack(data.detail || 'Attack failed');
  } catch (e) { console.error(e); }
}

