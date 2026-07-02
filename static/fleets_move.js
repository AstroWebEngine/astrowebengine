/* ============================================================
   AstroWebEngine - Frontend (fleets_move.js)
   Fleet move tab, travel estimation, and send flow
   Split from fleets.js for easier maintenance
   ============================================================ */
function renderFleetMove(f, specs) {
  if (f.is_moving) {
    const remaining = f.arrival_time ? Math.max(0, (serverDate(f.arrival_time) - Date.now()) / 1000) : 0;
    const destDisplay = f.destination_coords ? coordLink(f.destination_coords) : escStr(f.destination_name);
    const autoscoutBtn = f.is_autoscout && f.autoscout_ship
      ? `<button class="btn btn-ghost btn-sm" onclick="toggleAutoscout(${f.id})">Auto Scout: ON</button>`
      : '';
    return `<div class="text-warn" style="padding:12px;">
      Fleet is in transit to ${destDisplay} â€” <span class="countdown" data-end="${f.arrival_time}">${fmtTime(remaining)}</span>
      <div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap;">
        <button class="btn btn-ghost btn-sm" onclick="recallFleet(${f.id})">Recall</button>
        ${autoscoutBtn}
      </div>
    </div>`;
  }

  const locCoords = f.location_coords || 'â€”';

  // â”€â”€ Header: Location | Destination | Distance | Speed | Duration â”€â”€
  const headerHtml = `
    <table style="width:100%;font-size:12px;margin-bottom:10px;border-collapse:collapse;">
      <thead><tr style="border-bottom:1px solid var(--border);">
        <th style="text-align:left;padding:4px 8px;color:var(--text-dim);font-weight:normal;">Location</th>
        <th style="text-align:left;padding:4px 8px;color:var(--text-dim);font-weight:normal;">Destination</th>
        <th style="text-align:center;padding:4px 8px;color:var(--text-dim);font-weight:normal;">Distance</th>
        <th style="text-align:center;padding:4px 8px;color:var(--text-dim);font-weight:normal;">Speed</th>
        <th style="text-align:right;padding:4px 8px;color:var(--text-dim);font-weight:normal;">Duration</th>
      </tr></thead>
      <tbody><tr>
        <td style="padding:4px 8px;">${locCoords !== 'â€”' ? coordLink(locCoords) : 'â€”'}</td>
        <td style="padding:4px 8px;">
          <input type="text" id="move-dest-coords" placeholder="A01:23:05:02" value="${escStr(window._prefillMoveCoords || '')}"
            class="fleet-move-dest-input"
            style="background:var(--bg-dark);border:1px solid var(--border);border-radius:3px;color:var(--text-warn);padding:3px 6px;font-size:12px;font-family:monospace;"
            oninput="estimateTravel(${f.id})" />
        </td>
        <td style="text-align:center;padding:4px 8px;" id="move-hdr-distance" class="font-mono text-bright">â€”</td>
        <td style="text-align:center;padding:4px 8px;" id="move-hdr-speed" class="font-mono text-bright">â€”</td>
        <td style="text-align:right;padding:4px 8px;" id="move-hdr-duration" class="font-mono text-bright">â€”</td>
      </tr></tbody>
    </table>`;

  // â”€â”€ Ship table: Units | Speed | Available | [shortcuts] | Quantity | Hangar | Size â”€â”€
  const shipEntries = Object.entries(f.ships).filter(([_, c]) => c > 0);
  let shipRows = '';
  let totalHangar = 0, totalSize = 0;
  for (const [type, count] of shipEntries) {
    const s = specs[type] || {};
    const unitSize = s.cost || 0;  // "Size" = cost value
    const sizeVal = unitSize * count;
    // Hangar per unit: positive = provides slots, negative = consumes slots
    const hangarPerUnit = s.hangar || 0;
    const hangarVal = hangarPerUnit * count;
    const hangarColor = hangarVal < 0 ? 'color:var(--danger);' : '';
    const hangarDisplay = hangarVal !== 0 ? fmtNum(hangarVal) : '';
    totalHangar += hangarVal;
    totalSize += sizeVal;

    shipRows += `<tr>
      <td class="text-bright">${tName(s.name || type)}</td>
      <td class="font-mono" style="text-align:center;" id="move-spd-${type}">${s.speed || 0}</td>
      <td class="font-mono" style="text-align:center;">${fmtNum(count)}</td>
      <td style="text-align:center;">
        <a href="#" class="text-warn" style="text-decoration:none;font-size:10px;" onclick="setMoveQtyMax('${type}');return false;">Max</a>${hangarPerUnit !== 0 ? ` - <a href="#" class="text-warn" style="text-decoration:none;font-size:10px;" onclick="setMoveQtyHangar('${type}');return false;">Hangar</a>` : ''}
        <input type="number" id="move-qty-${type}" min="0" max="${count}" value="${count}"
          class="font-mono fleet-move-qty-input" data-ship="${type}" data-max="${count}" data-hangar="${hangarPerUnit}"
          style="background:var(--bg-dark);border:1px solid var(--border);border-radius:3px;color:var(--text-warn);padding:2px 4px;font-size:11px;text-align:center;"
          oninput="updateMoveQty(${f.id})" />
      </td>
      <td class="font-mono" style="text-align:center;${hangarColor}" id="move-hangar-${type}">${hangarDisplay}</td>
      <td class="font-mono" style="text-align:center;">${fmtNum(sizeVal)}</td>
    </tr>`;
  }

  const shipTableHtml = `
    <table class="data-table" style="font-size:11px;margin-bottom:6px;">
      <thead><tr>
        <th style="text-align:left;">Units</th>
        <th style="text-align:center;">Speed</th>
        <th style="text-align:center;">Available</th>
        <th style="text-align:center;font-size:10px;">
          <span class="text-dim">Quantity</span><br>
          <a href="#" class="text-warn" onclick="setAllMoveQty('all');return false;" style="text-decoration:none;font-size:10px;">All</a> -
          <a href="#" class="text-warn" onclick="setAllMoveQty('zero');return false;" style="text-decoration:none;font-size:10px;">None</a>
        </th>
        <th style="text-align:center;">Hangar</th>
        <th style="text-align:center;">Size</th>
      </tr></thead>
      <tbody>${shipRows}</tbody>
      <tfoot><tr style="border-top:1px solid var(--border);">
        <td colspan="4" style="text-align:right;padding-right:8px;" class="text-dim">Total</td>
        <td class="font-mono" style="text-align:center;${totalHangar < 0 ? 'color:var(--danger);' : ''}" id="move-total-hangar">${fmtNum(totalHangar)}</td>
        <td class="font-mono" style="text-align:center;" id="move-total-size">${fmtNum(totalSize)}</td>
      </tr></tfoot>
    </table>`;

  // â”€â”€ Split + Speed selector + Detected + Move button â”€â”€
  const moveControls = `
    <div style="display:flex;align-items:center;gap:12px;margin:8px 0;flex-wrap:wrap;">
      <span class="text-dim" style="font-size:11px;">
        <b>Detected in</b> before arrival: <span id="move-detected" class="text-warn">â€”</span>
      </span>
    </div>
    <div style="display:flex;align-items:center;gap:12px;margin:8px 0;flex-wrap:wrap;">
      <span class="text-dim" style="font-size:11px;">Split:</span>
      <select id="split-count-${f.id}" style="background:var(--bg-dark);border:1px solid var(--border);border-radius:3px;color:var(--text-bright);padding:2px 4px;font-size:11px;">
        <option value="1">1</option>
        ${(() => { const avail = (window._maxFleetCount || 5) - (window._fleetCount || 0); const maxSplit = Math.max(1, avail + 1); const opts = []; for (let n = 2; n <= maxSplit; n++) opts.push(`<option value="${n}">${n}</option>`); return opts.join(''); })()}
      </select>
      <span class="text-dim" style="font-size:11px;">Speed:</span>
      <select id="move-drive-sel" style="background:var(--bg-dark);border:1px solid var(--border);border-radius:3px;color:var(--text-bright);padding:2px 6px;font-size:11px;"
        onchange="estimateTravel(${f.id})">
        <option value="">Auto</option>
      </select>
      <span id="move-jg-option" style="display:none;">
        <label style="font-size:11px;cursor:pointer;color:var(--text-dim);">
          <input type="checkbox" id="move-use-jg" onchange="estimateTravel(${f.id})" style="vertical-align:middle;"/>
          <span id="move-jg-label">Jump Gate</span>
        </label>
      </span>
      <span id="move-wh-option" style="display:none;">
        <label style="font-size:11px;cursor:pointer;color:var(--text-dim);">
          <input type="checkbox" id="move-use-wh" onchange="estimateTravel(${f.id})" style="vertical-align:middle;"/>
          <span id="move-wh-label">Wormhole</span>
        </label>
      </span>
      <button class="btn btn-primary btn-sm" onclick="doMoveFleet(${f.id})">Move</button>
    </div>
    <div id="move-error" class="text-danger" style="font-size:11px;display:none;"></div>`;

  // â”€â”€ Side panel: Fast Destination (bases), Occupations, Bookmarks â”€â”€
  // Bases
  let basesHtml = '';
  if (_allBases.length) {
    const baseLinks = _allBases.map(b =>
      `<a href="#" class="text-warn" style="font-size:11px;text-decoration:none;"
        onclick="setMoveCoords('${escStr(b.coords || '')}');return false;">${escStr(b.name)} (${escStr(b.coords || '')})</a>`
    ).join('<br>');
    basesHtml = `<div style="margin-bottom:8px;">
      <div class="text-bright" style="font-size:11px;margin-bottom:4px;">Fast<br>Destination</div>
      ${baseLinks}
    </div>`;
  }

  // Occupations (enemy bases you're occupying â€” fleet at enemy base)
  let occupHtml = '';
  const occupiedBases = _allFleets
    .filter(fl => !fl.is_moving && fl.base_id && !fl.base_is_mine && fl.base_owner)
    .map(fl => ({ name: fl.base_owner, coords: fl.location_coords }));
  // Deduplicate by coords
  const seenOccup = new Set();
  const uniqueOccup = occupiedBases.filter(o => {
    if (seenOccup.has(o.coords)) return false;
    seenOccup.add(o.coords);
    return true;
  });
  if (uniqueOccup.length) {
    const occupLinks = uniqueOccup.map(o =>
      `<a href="#" class="text-danger" style="font-size:11px;text-decoration:none;"
        onclick="setMoveCoords('${escStr(o.coords)}');return false;">${escStr(o.name)} (${escStr(o.coords)})</a>`
    ).join('<br>');
    occupHtml = `<div style="margin-bottom:8px;">
      <div class="text-bright" style="font-size:11px;margin-bottom:4px;">Occupations</div>
      ${occupLinks}
    </div>`;
  }

  // Bookmarks
  let bookmarkHtml = '';
  if (_allBookmarks.length) {
    const bmLinks = _allBookmarks.map(bm =>
      `<span style="font-size:11px;">
        <a href="#" class="text-warn" style="text-decoration:none;"
          onclick="setMoveCoords('${escStr(bm.coords)}');return false;">${escStr(bm.name)} (${escStr(bm.coords)})</a>
        <a href="#" class="text-danger" style="font-size:9px;text-decoration:none;" onclick="deleteBookmark(${bm.id});return false;">&times;</a>
      </span>`
    ).join('<br>');
    bookmarkHtml = `<div style="margin-bottom:8px;">
      <div class="text-bright" style="font-size:11px;margin-bottom:4px;">Bookmarks</div>
      ${bmLinks}
    </div>`;
  }

  const addBmHtml = `<div style="margin-top:6px;">
    <input type="text" id="bm-name" placeholder="Bookmark name" style="width:100%;background:var(--bg-dark);border:1px solid var(--border);border-radius:3px;color:var(--text-bright);padding:3px 6px;font-size:10px;margin-bottom:4px;" />
    <button class="btn btn-ghost btn-sm" onclick="addBookmarkFromCoords()" style="font-size:10px;">+ Bookmark Dest</button>
  </div>`;

  return `
    <div style="text-align:center;font-size:14px;margin-bottom:6px;color:var(--text-bright);"><b>M</b>ove</div>
    ${headerHtml}
    <div class="fleet-move-layout">
      <div class="fleet-move-main">
        ${shipTableHtml}
        ${moveControls}
      </div>
      <div class="fleet-move-side">
        ${basesHtml}
        ${occupHtml}
        ${bookmarkHtml}
        ${addBmHtml}
      </div>
    </div>`;
}

function setMoveCoords(coords) {
  const input = document.getElementById('move-dest-coords');
  if (input) {
    input.value = coords;
    if (_openFleetId) estimateTravel(_openFleetId);
  }
}

// â”€â”€ Quantity helpers: Max, All, None, per-row Max/Hangar â”€â”€
function setAllMoveQty(mode) {
  const fleet = _allFleets.find(f => f.id === _openFleetId);
  if (!fleet) return;
  for (const [type, count] of Object.entries(fleet.ships)) {
    if (count <= 0) continue;
    const el = document.getElementById(`move-qty-${type}`);
    if (!el) continue;
    if (mode === 'all') el.value = count;
    else if (mode === 'zero') el.value = 0;
  }
  updateMoveQty(_openFleetId);
}

// Per-row "Max" â€” set this ship type to its max available
function setMoveQtyMax(type) {
  const el = document.getElementById(`move-qty-${type}`);
  if (el) el.value = el.getAttribute('data-max') || 0;
  if (_openFleetId) updateMoveQty(_openFleetId);
}

// Per-row "Hangar" â€” smart fill based on hangar role:
//   Consumers (hangar < 0): set to max that fits in available hangar from other ships
//   Providers (hangar > 0): set to just enough to cover the current hangar deficit
function setMoveQtyHangar(type) {
  const el = document.getElementById(`move-qty-${type}`);
  if (!el) return;
  const hangarPerUnit = parseInt(el.getAttribute('data-hangar')) || 0;
  const maxAvail = parseInt(el.getAttribute('data-max')) || 0;
  if (hangarPerUnit === 0) return;

  // Calculate net hangar from all OTHER ship types (excluding this one)
  const fleet = _allFleets.find(f => f.id === _openFleetId);
  if (!fleet) return;
  const specs = _shipSpecs || {};
  let otherHangar = 0;
  for (const [t, count] of Object.entries(fleet.ships)) {
    if (count <= 0 || t === type) continue;
    const qEl = document.getElementById(`move-qty-${t}`);
    if (!qEl) continue;
    const qty = parseInt(qEl.value) || 0;
    const s = specs[t] || {};
    otherHangar += (s.hangar || 0) * qty;
  }

  if (hangarPerUnit < 0) {
    // Consumer: how many fit in available hangar?
    const canFit = Math.max(0, Math.floor(otherHangar / Math.abs(hangarPerUnit)));
    el.value = Math.min(canFit, maxAvail);
  } else {
    // Provider: how many needed to cover the deficit?
    // otherHangar is negative if there's a deficit
    if (otherHangar >= 0) {
      // No deficit â€” don't need any of this provider
      el.value = 0;
    } else {
      const needed = Math.ceil(Math.abs(otherHangar) / hangarPerUnit);
      el.value = Math.min(needed, maxAvail);
    }
  }
  updateMoveQty(_openFleetId);
}

function updateMoveQty(fleetId) {
  // Recalc totals and per-row hangar when user changes a quantity
  const fleet = _allFleets.find(f => f.id === fleetId);
  if (!fleet) return;
  const specs = _shipSpecs || {};
  let totalHangar = 0, totalSize = 0;
  for (const [type, count] of Object.entries(fleet.ships)) {
    if (count <= 0) continue;
    const el = document.getElementById(`move-qty-${type}`);
    if (!el) continue;
    const qty = parseInt(el.value) || 0;
    const s = specs[type] || {};
    const hangarPerUnit = s.hangar || 0;
    const rowHangar = hangarPerUnit * qty;
    totalHangar += rowHangar;
    totalSize += (s.cost || 0) * qty;

    // Update per-row hangar cell
    const hCell = document.getElementById(`move-hangar-${type}`);
    if (hCell) {
      hCell.textContent = rowHangar !== 0 ? fmtNum(rowHangar) : '';
      hCell.style.color = rowHangar < 0 ? 'var(--danger)' : '';
    }
  }
  const hEl = document.getElementById('move-total-hangar');
  const sEl = document.getElementById('move-total-size');
  if (hEl) {
    hEl.textContent = fmtNum(totalHangar);
    hEl.style.color = totalHangar < 0 ? 'var(--danger)' : '';
  }
  if (sEl) sEl.textContent = fmtNum(totalSize);
  // Also re-estimate travel (speed may change with different ship selection)
  estimateTravel(fleetId);
}

let _estimateTimer = null;
let _lastEstimateData = null;  // cache for drive selector population

async function estimateTravel(fleetId) {
  clearTimeout(_estimateTimer);
  const coords = document.getElementById('move-dest-coords')?.value.trim();
  if (!coords || coords.length < 5) {
    // Clear header fields
    _setEstimateHeader(null);
    return;
  }
  _estimateTimer = setTimeout(async () => {
    try {
      // Check for drive override
      const driveSel = document.getElementById('move-drive-sel');
      let driveParam = '';
      if (driveSel && driveSel.value) driveParam = `&drive_override=${driveSel.value}`;
      // Jump Gate opt-in
      const jgCheck = document.getElementById('move-use-jg');
      const jgParam = jgCheck && jgCheck.checked ? '&use_jump_gate=true' : '';
      // Wormhole opt-in
      const whCheck = document.getElementById('move-use-wh');
      const whParam = whCheck && whCheck.checked ? '&use_wormhole=true' : '';

      const res = await apiFetch(`/api/fleets/${fleetId}/estimate?coords=${encodeURIComponent(coords)}${driveParam}${jgParam}${whParam}`);
      if (!res) return;
      const data = await res.json();
      if (data.detail) {
        _setEstimateHeader(null);
        const errEl = document.getElementById('move-hdr-duration');
        if (errEl) errEl.innerHTML = `<span class="text-danger">${escStr(data.detail)}</span>`;
        return;
      }
      _lastEstimateData = data;
      _setEstimateHeader(data);
      _populateDriveSelector(data);
      _updateShipSpeeds(data);
    } catch (e) { _setEstimateHeader(null); }
  }, 400);
}

function _setEstimateHeader(data) {
  const distEl = document.getElementById('move-hdr-distance');
  const spdEl = document.getElementById('move-hdr-speed');
  const durEl = document.getElementById('move-hdr-duration');
  const detEl = document.getElementById('move-detected');
  const jgOpt = document.getElementById('move-jg-option');
  const jgLabel = document.getElementById('move-jg-label');
  const whOpt = document.getElementById('move-wh-option');
  const whLabel = document.getElementById('move-wh-label');
  if (!data) {
    if (distEl) distEl.textContent = 'â€”';
    if (spdEl) spdEl.textContent = 'â€”';
    if (durEl) durEl.textContent = 'â€”';
    if (detEl) detEl.textContent = 'â€”';
    if (jgOpt) jgOpt.style.display = 'none';
    if (whOpt) whOpt.style.display = 'none';
    return;
  }
  if (distEl) distEl.textContent = data.distance;
  if (spdEl) spdEl.textContent = data.speed;
  if (durEl) durEl.textContent = fmtTime(data.travel_time);
  if (detEl) detEl.textContent = fmtTime(data.detected_in || 0);
  // Show/hide Jump Gate option
  if (jgOpt) {
    if (data.jg_available) {
      jgOpt.style.display = '';
      if (jgLabel) jgLabel.textContent = `Jump Gate (Lv ${data.jg_level})`;
    } else {
      jgOpt.style.display = 'none';
    }
  }
  // Show/hide Wormhole option
  if (whOpt) {
    if (data.wh_available) {
      whOpt.style.display = '';
      if (whLabel) whLabel.textContent = 'Wormhole';
    } else {
      whOpt.style.display = 'none';
    }
  }
}

function _populateDriveSelector(data) {
  const sel = document.getElementById('move-drive-sel');
  if (!sel) return;
  const currentVal = sel.value;
  const drives = data.drive_types || [];
  let opts = '<option value="">Auto</option>';
  for (const d of drives) {
    const techName = d === 'warp' ? 'Warp' : 'Stellar';
    const maxLvl = d === 'warp' ? data.warp_level : data.stellar_level;
    for (let lvl = maxLvl; lvl >= 0; lvl--) {
      const selected = currentVal === String(lvl) ? 'selected' : '';
      opts += `<option value="${lvl}" ${selected}>${techName} lvl ${lvl}</option>`;
    }
  }
  sel.innerHTML = opts;
  // Restore selection
  if (currentVal) sel.value = currentVal;
}

function _updateShipSpeeds(data) {
  // Update the Speed column in the ship table with tech-adjusted speeds
  if (!data.ship_speeds) return;
  for (const [type, speed] of Object.entries(data.ship_speeds)) {
    // The speed is shown in the ship table, but those cells don't have IDs yet.
    // We'll add IDs to the speed cells via the renderFleetMove function.
    const el = document.getElementById(`move-spd-${type}`);
    if (el) el.textContent = speed;
  }
}

// â”€â”€ Collect selected ship quantities â”€â”€
function _getMoveShips() {
  const fleet = _allFleets.find(f => f.id === _openFleetId);
  if (!fleet) return null;
  const ships = {};
  let anySelected = false;
  for (const [type, count] of Object.entries(fleet.ships)) {
    if (count <= 0) continue;
    const el = document.getElementById(`move-qty-${type}`);
    const qty = el ? (parseInt(el.value) || 0) : count;
    if (qty > 0) { ships[type] = qty; anySelected = true; }
  }
  return anySelected ? ships : null;
}

async function doMoveFleet(fleetId) {
  const coords = document.getElementById('move-dest-coords')?.value.trim();
  const errEl = document.getElementById('move-error');
  if (!coords) { errEl.textContent = 'Enter destination coordinates'; errEl.style.display = 'block'; return; }
  errEl.style.display = 'none';

  const ships = _getMoveShips();
  if (!ships) { errEl.textContent = 'Select at least one ship to send'; errEl.style.display = 'block'; return; }

  // Split first if split > 1
  const splitSel = document.getElementById(`split-count-${fleetId}`);
  const splitInto = parseInt(splitSel?.value) || 1;
  let fleetIds = [fleetId];

  if (splitInto > 1) {
    try {
      const splitRes = await apiFetch(`/api/fleets/split?fleet_id=${fleetId}&split_into=${splitInto}`, { method: 'POST' });
      const splitData = await splitRes.json();
      if (!splitData.success) {
        errEl.textContent = splitData.detail || 'Split failed';
        errEl.style.display = 'block';
        return;
      }
      // All fleet IDs to send: original + new ones
      fleetIds = [fleetId, ...splitData.new_fleet_ids];
    } catch (e) {
      errEl.textContent = 'Split failed';
      errEl.style.display = 'block';
      return;
    }
  }

  // Send all fleets to the same destination
  try {
    const jgCheck = document.getElementById('move-use-jg');
    const useJG = jgCheck && jgCheck.checked;
    const whCheck = document.getElementById('move-use-wh');
    const useWH = whCheck && whCheck.checked;
    let lastData = null;
    for (const fid of fleetIds) {
      // For split fleets send all ships; for single fleet use selected ships
      const sendBody = splitInto > 1
        ? { fleet_id: fid, destination_coords: coords, use_jump_gate: useJG, use_wormhole: useWH }
        : { fleet_id: fid, destination_coords: coords, ships, use_jump_gate: useJG, use_wormhole: useWH };
      const res = await apiFetch('/api/fleets/send', {
        method: 'POST',
        body: JSON.stringify(sendBody)
      });
      lastData = await res.json();
      if (!lastData.success) {
        errEl.textContent = lastData.detail || 'Move failed';
        errEl.style.display = 'block';
        await loadFleets();
        return;
      }
    }
    const msg = splitInto > 1
      ? `${splitInto} fleets sent to ${lastData.destination} (${fmtTime(lastData.travel_time)})`
      : `Fleet sent to ${lastData.destination} (${fmtTime(lastData.travel_time)})`;
    showSnack(msg);
    _openFleetId = null;
    _activeFleetTab = 'overview';
    await loadFleets();
  } catch (e) { errEl.textContent = 'Error'; errEl.style.display = 'block'; }
}

// â”€â”€ Build Base tab â”€â”€

