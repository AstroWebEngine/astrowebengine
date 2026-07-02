/* ============================================================
   AstroWebEngine - Frontend (social_commanders.js)
   Commander tab and commander management flows
   Split from social.js for easier maintenance
   ============================================================ */
async function loadCommanders() {
  const container = document.getElementById('commanders-container');
  if (!container) return;
  container.innerHTML = '<div class="loading">Loading commanders...</div>';

  try {
    const res = await apiFetch('/api/commanders');
    if (!res || !res.ok) throw new Error('Failed to load commanders');
    _commanderData = await res.json();
    _renderCommanders(container);
  } catch(e) {
    container.innerHTML = `<div class="text-danger">${e.message}</div>`;
  }

  // Silent refresh every 30s â€” only re-render if data actually changed
  if (_commanderRefreshTimer) clearInterval(_commanderRefreshTimer);
  _commanderRefreshTimer = setInterval(async () => {
    const panel = document.getElementById('tab-commanders');
    if (!panel || panel.style.display === 'none') {
      clearInterval(_commanderRefreshTimer);
      _commanderRefreshTimer = null;
      return;
    }
    try {
      const res = await apiFetch('/api/commanders');
      if (!res || !res.ok) return;
      const newData = await res.json();
      const oldJson = JSON.stringify(_commanderData?.commanders?.map(c => ({
        id: c.id, level: c.level, is_training: c.is_training, is_traveling: c.is_traveling,
        is_assigned: c.is_assigned, colony_id: c.colony_id, xp: c.xp
      })));
      const newJson = JSON.stringify(newData?.commanders?.map(c => ({
        id: c.id, level: c.level, is_training: c.is_training, is_traveling: c.is_traveling,
        is_assigned: c.is_assigned, colony_id: c.colony_id, xp: c.xp
      })));
      if (oldJson !== newJson || _commanderData?.current_count !== newData?.current_count) {
        _commanderData = newData;
        const cont = document.getElementById('commanders-container');
        if (cont) _renderCommanders(cont);
      }
    } catch(e) {}
  }, 30000);
}

function _renderCommanders(container) {
  const d = _commanderData;
  if (!d) return;

  let html = '';

  // Commander list table
  html += `<h3 style="text-align:center;margin:0 0 8px">Commanders</h3>`;
  html += `<table class="data-table" style="width:100%">
    <thead><tr>
      <th>Commander</th><th class="mobile-hide">Skill</th><th>Location</th>
      <th class="mobile-hide">Arrival</th><th>Train</th><th class="mobile-hide">Duty</th>
    </tr></thead><tbody>`;

  if (d.commanders.length === 0) {
    html += `<tr><td colspan="6" style="text-align:center;opacity:0.6">No commanders recruited yet. Research Computer tech to unlock slots.</td></tr>`;
  }

  for (const c of d.commanders) {
    const skillLabel = `${c.skill_name} ${c.level}`;
    let locLabel = '';
    if (c.colony_id) {
      locLabel = c.colony_numeral
        ? `${escStr(c.colony_numeral)} (${maybeCoordLink(c.colony_coords)})`
        : (maybeCoordLink(c.colony_coords) || 'At base');
    }
    let arrivalLabel = '';
    if (c.is_traveling && c.arrival_time) {
      arrivalLabel = `<span class="countdown" data-end="${c.arrival_time}"></span>`;
    }
    let trainLabel = '';
    if (c.is_training && c.training_complete_time) {
      trainLabel = `<span class="countdown" data-end="${c.training_complete_time}"></span>`;
    } else {
      trainLabel = `<a href="#" onclick="event.preventDefault();_showCommanderActions(${c.id})" style="color:inherit">${c.train_xp_cost} XP</a>`;
    }
    const dutyLabel = c.is_assigned ? 'Base Commander' : '';
    const rowStyle = c.is_assigned ? 'color:var(--accent)' : '';

    html += `<tr style="${rowStyle}">
      <td><a href="#" onclick="event.preventDefault();_showCommanderActions(${c.id})" style="color:inherit;text-decoration:underline">${c.name}</a><br class="mobile-show"><span class="mobile-show" style="font-size:10px;opacity:0.7">${skillLabel}</span></td>
      <td class="mobile-hide">${skillLabel}</td>
      <td>${locLabel}${dutyLabel ? `<br class="mobile-show"><span class="mobile-show" style="font-size:10px;opacity:0.7">${dutyLabel}</span>` : ''}</td>
      <td class="mobile-hide">${arrivalLabel}</td>
      <td>${trainLabel}</td>
      <td class="mobile-hide">${dutyLabel}</td>
    </tr>`;
  }

  html += '</tbody></table>';

  // Footer
  html += `<div style="text-align:right;margin-top:8px;font-size:13px;">
    Commanders: ${d.current_count}/${d.max_capacity}<br>
    XP: ${d.xp_pool}
  </div>`;

  // Recruit link
  html += `<div style="text-align:center;margin-top:12px;">
    <a href="#" onclick="event.preventDefault();_toggleRecruitPanel()" style="color:var(--accent)">Recruit a new Commander</a>
  </div>`;

  // Recruit panel (collapsible)
  html += `<div id="recruit-panel" style="display:${_showRecruitPanel ? 'block' : 'none'};margin-top:12px;">`;
  html += _renderRecruitPanel(d);
  html += '</div>';

  container.innerHTML = html;
  updateCountdowns();
}

function _renderRecruitPanel(d) {
  let html = `<table class="data-table" style="width:100%">
    <thead><tr><th>Skill</th><th>Description</th><th>Recruit - Pay:</th></tr></thead><tbody>`;

  const skills = d.skill_info || {};
  for (const [key, info] of Object.entries(skills)) {
    html += `<tr>
      <td>${info.name}</td>
      <td style="font-size:12px">${info.desc}</td>
      <td style="white-space:nowrap">
        <button class="btn btn-ghost btn-sm" onclick="_recruitCommander('${key}', false)" title="Pay with XP">20 XP</button>
        <span style="margin:0 4px">-</span>
        <button class="btn btn-ghost btn-sm" onclick="_recruitCommander('${key}', true)" title="Pay with Credits">40 cred.</button>
      </td>
    </tr>`;
  }
  html += '</tbody></table>';
  html += `<div style="text-align:right;margin-top:4px;font-size:12px;">
    You can recruit a new Commander using Experience Points, or by paying Credits.
    <br>XP: ${d.xp_pool}
  </div>`;
  return html;
}

function _toggleRecruitPanel() {
  _showRecruitPanel = !_showRecruitPanel;
  const panel = document.getElementById('recruit-panel');
  if (panel) panel.style.display = _showRecruitPanel ? 'block' : 'none';
}

async function _recruitCommander(skillType, useCredits) {
  try {
    const res = await apiFetch('/api/commanders/recruit', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({skill_type: skillType, use_credits: useCredits})
    });
    if (!res || !res.ok) { const err = await res?.json().catch(() => ({})); throw new Error(err?.detail || 'Recruit failed'); }
    loadCommanders();
    if (typeof updateHUD === 'function') updateHUD();
  } catch(e) {
    showSnack(e.message);
  }
}

async function _assignCommander(id) {
  try {
    const res = await apiFetch(`/api/commanders/${id}/assign`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({colony_id: _commanderData.commanders.find(c => c.id === id)?.colony_id})
    });
    if (!res || !res.ok) { const err = await res?.json().catch(() => ({})); throw new Error(err?.detail || 'Assign failed'); }
    loadCommanders();
  } catch(e) {
    showSnack(e.message);
  }
}

function _showCommanderActions(id) {
  const c = _commanderData?.commanders.find(x => x.id === id);
  if (!c) return;
  const skillDesc = _commanderData?.skill_info?.[c.skill_type]?.desc || '';

  // Inline detail row
  let html = `<table class="data-table" style="width:100%">
    <thead><tr>
      <th>Commander</th><th>Skill</th><th>Location</th>
      <th>Arrival</th><th>Train</th><th>Duty</th>
    </tr></thead><tbody>`;

  // Commander row with name as dropdown
  let locLabel = c.colony_id
    ? (c.colony_numeral
      ? `${escStr(c.colony_numeral)} (${maybeCoordLink(c.colony_coords)})`
      : (maybeCoordLink(c.colony_coords) || 'At base'))
    : '';
  let arrLabel = '';
  if (c.is_traveling && c.arrival_time) {
    const eta = new Date(c.arrival_time + 'Z') - Date.now();
    arrLabel = eta > 0 ? _formatEta(eta) : 'Arriving...';
  }
  let trainLabel = `${c.xp} XP`;
  if (c.is_training && c.training_complete_time) {
    const eta = new Date(c.training_complete_time + 'Z') - Date.now();
    trainLabel = eta > 0 ? _formatEta(eta) : 'Completing...';
  }
  const dutyLabel = c.is_assigned ? 'Base Commander' : '';
  const rowStyle = c.is_assigned ? 'color:var(--accent)' : '';

  html += `<tr style="${rowStyle}">
    <td><select id="cmdr-name-select" style="background:transparent;color:inherit;border:1px solid var(--border);font-size:13px;">
      <option selected>${c.name}</option></select><br>
      <span style="font-size:11px;">
        <a href="#" onclick="event.preventDefault();_dismissCommander(${c.id})" style="color:var(--danger,#c44)">Dismiss</a>
      </span>
    </td>
    <td>${c.skill_name} ${c.level}</td>
    <td>${locLabel}</td>
    <td>${arrLabel}</td>
    <td>${trainLabel}</td>
    <td>${dutyLabel}</td>
  </tr></tbody></table>`;

  // Skill description
  html += `<div style="font-size:12px;margin:8px 0;opacity:0.8">This commander ${skillDesc.toLowerCase()}</div>`;

  // Train section
  if (c.is_training && c.training_complete_time) {
    html += `<div style="margin-bottom:8px;font-size:13px">
      Training to Level ${c.level + 1}... <span class="countdown" data-end="${c.training_complete_time}"></span>
    </div>`;
  } else if (c.level < 20) {
    const xpCost = c.train_xp_cost;
    const credCost = c.train_credit_cost;
    html += `<div style="margin-bottom:8px;font-size:13px">
      You can train this Commander by using Experience Points, or paying Credits. (you have ${c.xp} XP)<br>
      The commander training will take ${Math.min(c.level, 8)} hour(s).<br><br>
      Spend:
      <a href="#" onclick="event.preventDefault();_trainCommander(${c.id}, false)"
        ${c.xp < xpCost ? 'style="opacity:0.4;pointer-events:none"' : 'style="color:var(--accent)"'}>${xpCost} XP</a>`;
    if (c.can_train_credits) {
      html += ` - <a href="#" onclick="event.preventDefault();_trainCommander(${c.id}, true)" style="color:var(--accent)">${credCost} cred.</a>`;
    } else {
      html += ` <span style="font-size:11px;opacity:0.6">(XP only above Lv${COMMANDER_XP_ONLY_ABOVE || 8})</span>`;
    }
    html += `</div>`;
  }

  // Move
  html += `<div style="margin-bottom:8px;text-align:center">
    <select id="cmdr-move-select" style="margin-right:4px">
      <option value="">-- Select base --</option>
    </select>
    <a href="#" onclick="event.preventDefault();_moveCommanderFromSelect(${c.id})" style="color:var(--accent)">Move</a>
  </div>`;

  // Assign / Unassign
  if (c.is_assigned) {
    html += `<div style="text-align:center;margin-bottom:8px">
      <a href="#" onclick="event.preventDefault();_unassignCommander(${c.id})" style="color:var(--accent)">Unassign from duty</a>
    </div>`;
  } else if (c.colony_id && !c.is_traveling) {
    html += `<div style="text-align:center;margin-bottom:8px">
      <a href="#" onclick="event.preventDefault();_assignCommander(${c.id})" style="color:var(--accent)">Assign as Base Commander</a>
    </div>`;
  }

  html += `<div style="text-align:right;margin-top:8px">
    <a href="#" onclick="event.preventDefault();loadCommanders()" style="color:var(--accent)">Back to list</a>
  </div>`;

  const container = document.getElementById('commanders-container');
  container.innerHTML = html;
  updateCountdowns();

  // Load bases into the move dropdown
  _loadBasesForCommanderMove();
}

async function _loadBasesForCommanderMove() {
  try {
    const res = await apiFetch('/api/bases');
    if (!res.ok) return;
    const bases = await res.json();
    const sel = document.getElementById('cmdr-move-select');
    if (!sel) return;
    const numerals = ['I','II','III','IV','V','VI','VII','VIII','IX','X','XI','XII','XIII','XIV','XV','XVI','XVII','XVIII','XIX','XX'];
    bases.forEach((b, i) => {
      const num = numerals[i] || (i+1);
      const opt = document.createElement('option');
      opt.value = b.id;
      opt.textContent = `${num} - ${b.name} (${b.coords || ''})`;
      sel.appendChild(opt);
    });
  } catch(e) { /* ignore */ }
}

async function _moveCommanderFromSelect(id) {
  const sel = document.getElementById('cmdr-move-select');
  if (!sel || !sel.value) { showSnack('Select a base'); return; }
  try {
    const res = await apiFetch(`/api/commanders/${id}/move`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({colony_id: parseInt(sel.value)})
    });
    if (!res || !res.ok) { const err = await res?.json().catch(() => ({})); throw new Error(err?.detail || 'Move failed'); }
    loadCommanders();
  } catch(e) {
    showSnack(e.message);
  }
}

async function _trainCommander(id, useCredits = false) {
  try {
    const res = await apiFetch(`/api/commanders/${id}/train?use_credits=${useCredits}`, {
      method: 'POST',
    });
    if (!res || !res.ok) { const err = await res?.json().catch(() => ({})); throw new Error(err?.detail || 'Train failed'); }
    loadCommanders();
  } catch(e) {
    showSnack(e.message);
  }
}

async function _unassignCommander(id) {
  try {
    const res = await apiFetch(`/api/commanders/${id}/assign`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({colony_id: null})
    });
    if (!res || !res.ok) { const err = await res?.json().catch(() => ({})); throw new Error(err?.detail || 'Unassign failed'); }
    loadCommanders();
  } catch(e) {
    showSnack(e.message);
  }
}

async function _dismissCommander(id) {
  const c = _commanderData?.commanders.find(x => x.id === id);
  if (!confirm(`Permanently dismiss ${c?.name || 'this commander'}?`)) return;
  try {
    const res = await apiFetch(`/api/commanders/${id}`, {
      method: 'DELETE',
    });
    if (!res || !res.ok) { const err = await res?.json().catch(() => ({})); throw new Error(err?.detail || 'Dismiss failed'); }
    loadCommanders();
  } catch(e) {
    showSnack(e.message);
  }
}

function _formatEta(ms) {
  if (ms <= 0) return '0:00:00';
  const s = Math.floor(ms / 1000);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return `${h}:${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`;
}

// SCANNERS (Empire > Reports â€” default tab)
// ============================================================

let _scannersTab = 'scanners';

