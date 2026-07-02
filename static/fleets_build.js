/* ============================================================
   AstroWebEngine - Frontend (fleets_build.js)
   Fleet base colonization and ship build/queue flows
   Split from fleets.js for easier maintenance
   ============================================================ */
function renderFleetBuildBase(f) {
  if (f.is_moving) return '<div class="text-dim" style="padding:12px;">Fleet must be stationary to build a base.</div>';
  if (!f.has_outpost) return '<div class="text-dim" style="padding:12px;">Fleet needs a colony ship to colonize.</div>';

  // Only colonize uncolonized planets â€” fleet must be at one
  if (!f.location_planet_id) {
    return '<div class="text-dim" style="padding:12px;">Fleet must be at an uncolonized astro to build a base. Land at a nearby uninhabited astro first.</div>';
  }

  return `<div style="padding:12px;">
    <p class="text-dim" style="font-size:12px;margin-bottom:10px;">
      Colonize the astro at ${f.location_coords ? coordLink(f.location_coords) : escStr(f.location_name)}.
      This will consume one ${escStr(shipName(f.colonizer_ship, 'colony ship'))}.
    </p>
    <button class="btn btn-primary btn-sm" onclick="doColonizeFromFleet(${f.id}, ${f.location_planet_id})">Build Base</button>
  </div>`;
}

async function doColonizeFromFleet(fleetId, planetId) {
  try {
    const res = await apiFetch('/api/colonize', {
      method: 'POST',
      body: JSON.stringify({ fleet_id: fleetId, planet_id: planetId })
    });
    const data = await res.json();
    if (data.success) {
      showSnack('Base established!');
      await loadFleets(); await updateHUD();
    } else showSnack(data.detail || 'Colonize failed');
  } catch (e) { console.error(e); }
}

// â”€â”€ Attack tab â”€â”€
// Attack and piracy flows moved to fleets_attack.js.

async function buildShips() {
  const baseId = parseInt(document.getElementById('build-base-sel').value);
  const shipType = document.getElementById('build-ship-sel').value;
  const count = parseInt(document.getElementById('build-count').value) || 1;
  const errEl = document.getElementById('build-error');
  errEl.style.display = 'none';
  try {
    const res = await apiFetch('/api/fleets/build', {
      method: 'POST', body: JSON.stringify({ base_id: baseId, ship_type: shipType, count })
    });
    const data = await res.json();
    if (data.success) {
      const timeStr = data.total_time ? ` (${fmtTime(data.total_time)})` : '';
      showSnack(`Queued ${count} ${shipType}${timeStr}`);
      await updateHUD(); await loadFleets(); await loadShipQueue();
    } else { errEl.textContent = data.detail || 'Build failed'; errEl.style.display = 'block'; }
  } catch (e) { errEl.textContent = 'Error'; errEl.style.display = 'block'; }
}

async function loadShipQueue() {
  try {
    const res = await apiFetch('/api/ship-queue');
    if (!res) return;
    const queues = await res.json();
    const container = document.getElementById('ship-queue-container');
    if (!container) return;
    if (!queues.length) { container.innerHTML = ''; return; }
    container.innerHTML = queues.map(q => {
      const isActive = q.position === 0;
      const timeHtml = q.next_complete
        ? `<span class="text-warn">Complete: <span class="countdown" data-end="${q.next_complete}">${fmtTime(Math.max(0, (serverDate(q.next_complete) - Date.now()) / 1000))}</span></span>`
        : '<span class="text-dim">queued</span>';
      return `<div class="ship-queue-item" style="display:flex;align-items:center;gap:8px;padding:6px 8px;background:var(--bg-dark);border:1px solid var(--border);border-radius:4px;font-size:11px;margin-bottom:4px;">
        <span class="text-dim">#${q.position + 1}</span>
        <span class="text-accent">${escStr(q.base_name)}</span>
        <span class="text-bright">${tName(q.ship_name)}</span>
        <span class="text-dim">${isActive ? q.built + '/' : ''}${q.count}</span>
        ${timeHtml}
        <button class="btn btn-ghost btn-sm" style="margin-left:auto;font-size:10px;" onclick="cancelShipQueue(${q.id})">Cancel</button>
      </div>`;
    }).join('');
  } catch (e) { console.error(e); }
}

async function cancelShipQueue(queueId) {
  if (!confirm('Cancel ship production?')) return;
  try {
    const res = await apiFetch(`/api/ship-queue/${queueId}`, { method: 'DELETE' });
    const data = await res.json();
    if (data.success) {
      const msg = data.refunded > 0 ? `Cancelled â€” refunded ${fmtNum(data.refunded)} cr` : 'Cancelled queued production';
      showSnack(msg);
      await updateHUD(); await loadShipQueue(); await loadFleets();
      if (document.getElementById('tab-bases')?.classList.contains('active')) await loadBases();
    }
  } catch (e) { console.error(e); }
}

// ============================================================
// FLEET ACTIONS (recall, attack, recycle)
// ============================================================
