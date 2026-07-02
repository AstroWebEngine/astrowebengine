/* ============================================================
   AstroWebEngine - Frontend (fleets_detail.js)
   Fleet detail page shell and overview rendering
   Split from fleets.js for easier maintenance
   ============================================================ */
function openFleetDetail(fleetId) {
  _openFleetId = fleetId;
  _activeFleetTab = 'overview';
  const fleet = _allFleets.find(f => f.id === fleetId);
  if (!fleet) return;
  renderFleetDetail(fleet, _shipSpecs || {});
}

function closeFleetDetail() {
  _openFleetId = null;
  renderFleetList(_allFleets, _shipSpecs || {});
}

function switchFleetTab(tab) {
  _activeFleetTab = tab;
  const fleet = _allFleets.find(f => f.id === _openFleetId);
  if (fleet) renderFleetDetail(fleet, _shipSpecs || {});
}

function switchFleetDropdown(sel) {
  const fid = parseInt(sel.value);
  _openFleetId = fid;
  _activeFleetTab = 'overview';
  const fleet = _allFleets.find(f => f.id === fid);
  if (fleet) renderFleetDetail(fleet, _shipSpecs || {});
}

function renderFleetDetail(fleet, specs) {
  const container = document.getElementById('fleets-container');
  const f = fleet;

  // Fleet selector dropdown
  const fleetOptions = _allFleets.map(fl =>
    `<option value="${fl.id}" ${fl.id === f.id ? 'selected' : ''}>${escStr(fl.name)}</option>`
  ).join('');

  // Location / Destination / Arrival for header table
  let locHtml = '';
  if (f.location_coords) {
    const locName = f.location_name || f.base_name || '';
    locHtml = locName ? `${escStr(locName)} (${coordLink(f.location_coords)})` : coordLink(f.location_coords);
  } else {
    locHtml = escStr(f.location_name || f.base_name || 'Unknown');
  }
  let destHtml = '', arrivalHtml = '';
  if (f.is_moving) {
    destHtml = f.destination_coords ? coordLink(f.destination_coords) : escStr(f.destination_name || '');
    const remaining = f.arrival_time ? Math.max(0, (serverDate(f.arrival_time) - Date.now()) / 1000) : 0;
    arrivalHtml = `<span class="countdown" data-end="${f.arrival_time}">${fmtTime(remaining)}</span>`;
  }

  // Tab buttons
  const tabs = [
    { key: 'overview', label: 'Overview' },
    { key: 'move', label: 'Move' },
    { key: 'build_base', label: 'Build Base' },
    { key: 'attack', label: 'Attack' },
    { key: 'piracy', label: 'Piracy' },
  ];
  const tabsHtml = tabs.map(tab => {
    const active = _activeFleetTab === tab.key;
    return `<a href="#" onclick="event.preventDefault();switchFleetTab('${tab.key}')"
      style="padding:4px 12px;font-size:12px;text-decoration:none;${active ? 'color:var(--text-bright);background:var(--accent,#446);' : 'color:var(--text-dim);'}">${tab.label}</a>`;
  }).join('');

  // Tab content
  let contentHtml = '';
  if (_activeFleetTab === 'overview') contentHtml = renderFleetOverview(f, specs);
  else if (_activeFleetTab === 'move') contentHtml = renderFleetMove(f, specs);
  else if (_activeFleetTab === 'build_base') contentHtml = renderFleetBuildBase(f);
  else if (_activeFleetTab === 'attack') contentHtml = renderFleetAttack(f);
  else if (_activeFleetTab === 'piracy') contentHtml = renderFleetPiracy(f);

  container.innerHTML = `
    <div style="margin-bottom:6px;">
      <button class="btn btn-ghost btn-sm" onclick="closeFleetDetail()" style="font-size:11px;">&larr; Fleet List</button>
    </div>
    <table style="width:100%;font-size:12px;margin-bottom:2px;border-collapse:collapse;">
      <thead><tr style="border-bottom:1px solid var(--border);">
        <th style="text-align:left;padding:4px 8px;font-weight:normal;color:var(--text-dim);width:1%;white-space:nowrap;"></th>
        <th style="text-align:left;padding:4px 8px;font-weight:normal;color:var(--text-dim);">Location</th>
        <th style="text-align:left;padding:4px 8px;font-weight:normal;color:var(--text-dim);">Destination</th>
        <th style="text-align:center;padding:4px 8px;font-weight:normal;color:var(--text-dim);">Arrival</th>
        <th style="text-align:right;padding:4px 8px;font-weight:normal;color:var(--text-dim);">Comment</th>
      </tr></thead>
      <tbody><tr>
        <td style="padding:4px 8px;white-space:nowrap;">
          <select onchange="switchFleetDropdown(this)" style="background:var(--bg-dark);border:1px solid var(--border);border-radius:3px;color:var(--text-bright);padding:3px 6px;font-size:12px;">
            ${fleetOptions}
          </select>
        </td>
        <td style="padding:4px 8px;">${locHtml}</td>
        <td style="padding:4px 8px;">${destHtml}</td>
        <td style="padding:4px 8px;text-align:center;">${arrivalHtml}</td>
        <td style="padding:4px 8px;text-align:right;">
          <a href="#" class="text-dim" style="font-size:11px;text-decoration:none;" onclick="event.preventDefault();openFleetRenameModal(${f.id},'${escAttr(f.name)}')">Edit</a>
        </td>
      </tr></tbody>
    </table>
    <div style="padding:2px 0 4px;">
      <span class="text-dim" style="font-size:11px;">
        <a href="#" class="text-accent" style="text-decoration:none;font-size:11px;" onclick="event.preventDefault();openFleetRenameModal(${f.id},'${escAttr(f.name)}')">Rename</a>
        - <a href="#" class="text-danger" style="text-decoration:none;font-size:11px;" onclick="event.preventDefault();disbandFleet(${f.id})">Disband</a>
      </span>
    </div>
    <div style="display:flex;gap:0px;margin-bottom:10px;border-bottom:1px solid var(--border);">${tabsHtml}</div>
    <div>${contentHtml}</div>
  `;
  // If destination was pre-filled from map, trigger estimate and clear
  if (window._prefillMoveCoords && _activeFleetTab === 'move') {
    setTimeout(() => { estimateTravel(f.id); }, 50);
    window._prefillMoveCoords = null;
  }
  // Load piracy routes async
  if (_activeFleetTab === 'piracy' && f.base_id && !f.base_is_mine && !f.is_moving) {
    setTimeout(() => loadPiracyRoutes(f.id, f.base_id), 0);
  }
  // Load attack enemies async
  if (_activeFleetTab === 'attack' && !f.is_moving && (f.base_id || f.location_planet_id)) {
    setTimeout(() => loadAttackEnemies(f.id), 0);
  }
}

// â”€â”€ Overview tab â”€â”€
function renderFleetOverview(f, specs) {
  const shipEntries = Object.entries(f.ships).filter(([_, c]) => c > 0);
  if (!shipEntries.length) return '<div class="text-dim" style="text-align:center;padding:20px;">No ships in this fleet.</div>';

  const dmg = f.ship_damage || {};
  let rows = '';
  for (const [type, count] of shipEntries) {
    const s = specs[type] || {};
    const isDamaged = dmg[type] && dmg[type] < 1;
    const dmgLabel = isDamaged ? ` <span class="text-danger" style="font-size:10px;">(1 at ${Math.round(dmg[type]*100)}%)</span>` : '';
    // Auto Scout link on the fleet's autoscout-capable ship row (capability-driven)
    let extraLink = '';
    if (type === f.autoscout_ship && !f.is_moving) {
      if (f.is_autoscout) {
        extraLink = `<a href="#" class="text-success" style="font-size:11px;text-decoration:none;margin-left:12px;" onclick="event.preventDefault();toggleAutoscout(${f.id})">Auto Scout</a>`;
      } else {
        extraLink = `<a href="#" class="text-dim" style="font-size:11px;text-decoration:none;margin-left:12px;" onclick="event.preventDefault();toggleAutoscout(${f.id})">Auto Scout</a>`;
      }
    }
    rows += `<tr>
      <td style="text-align:left;padding:2px 16px;" class="text-bright">${tName(s.name || type)}${dmgLabel}</td>
      <td style="text-align:right;padding:2px 16px;" class="font-mono">${fmtNum(count)}</td>
      <td style="text-align:left;padding:2px 8px;">${extraLink}</td>
    </tr>`;
  }

  // Detection time (based on fleet size)
  const detectionTime = f.detection_time || 0;
  const detectionStr = detectionTime > 0 ? fmtTime(detectionTime) : 'â€”';

  // Action links
  let linksHtml = '';
  if (f.is_moving) {
    const links = [
      `<a href="#" class="text-warn" style="text-decoration:none;" onclick="event.preventDefault();recallFleet(${f.id})">Recall</a>`
    ];
    if (f.is_autoscout && f.autoscout_ship) {
      links.push(`<a href="#" class="text-success" style="text-decoration:none;" onclick="event.preventDefault();toggleAutoscout(${f.id})">Auto Scout: ON</a>`);
    }
    linksHtml = links.join(' &nbsp; ');
  } else {
    const links = [];
    links.push(`<a href="#" class="text-accent" style="text-decoration:none;" onclick="event.preventDefault();openMergeModal(${f.id})">Merge</a>`);
    if (dmg && Object.keys(dmg).length > 0) {
      links.push(`<a href="#" class="text-warn" style="text-decoration:none;" onclick="event.preventDefault();repairFleet(${f.id})">Repair</a>`);
    }
    if (f.recycle_ship) {
      const recycleOn = f.auto_recycle;
      links.push(`<a href="#" style="text-decoration:none;color:${recycleOn ? 'var(--clr-pos,#4f4)' : 'var(--text-dim)'};" onclick="event.preventDefault();toggleRecycle(${f.id})">Recycle: ${recycleOn ? 'ON' : 'OFF'}</a>`);
    }
    linksHtml = links.join(' &nbsp; ');
  }

  // Hide link
  let hideHtml = '';
  if (f.guild_hidden_until) {
    const remaining = Math.max(0, (serverDate(f.guild_hidden_until) - Date.now()) / 1000);
    hideHtml = `<a href="#" class="text-dim" style="text-decoration:none;" onclick="event.preventDefault();guildHideCancel(${f.id})">Hidden <span class="countdown" data-end="${f.guild_hidden_until}">${fmtTime(remaining)}</span> â€” Unhide</a>`;
  } else {
    hideHtml = `<a href="#" class="text-dim" style="text-decoration:none;" onclick="event.preventDefault();guildHideFleet(${f.id})">Hide</a> (from guild shared data)`;
  }

  return `
    <div style="text-align:center;padding:12px;">
      <div style="text-align:center;font-size:14px;margin-bottom:10px;color:var(--text-bright);"><b>O</b>verview</div>
      <div style="display:inline-block;text-align:center;border:1px solid var(--border);padding:12px 24px;background:var(--bg-card,var(--bg-dark));">
        <table style="font-size:12px;margin:0 auto;">
          <thead><tr>
            <th colspan="2" style="text-align:center;padding-bottom:6px;font-weight:bold;color:var(--text-bright);">Units</th>
            <th></th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
        <div style="margin-top:12px;font-size:12px;">
          Fleet Size: <span class="font-mono text-bright">${fmtNum(f.value)}</span>
        </div>
        <div style="font-size:11px;color:var(--text-dim);margin-top:4px;">
          (Detection time: ${detectionStr})
        </div>
        ${linksHtml ? `<div style="margin-top:10px;font-size:11px;">${linksHtml}</div>` : ''}
        <div style="margin-top:8px;font-size:11px;">${hideHtml}</div>
      </div>
    </div>`;
}

// â”€â”€ Move tab â”€â”€
