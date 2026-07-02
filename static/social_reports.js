/* ============================================================
   AstroWebEngine - Frontend (social_reports.js)
   Reports tabs and report-specific loaders
   Split from social.js for easier maintenance
   ============================================================ */
async function loadReportTrade() {
  const container = document.getElementById('report-trade-content');
  if (!container) return;

  try {
    const res = await apiFetch('/api/trade-routes');
    const data = await res.json();
    const routes = data.routes || [];

    if (!routes.length) {
      container.innerHTML = '<p class="text-dim" style="padding:12px;font-size:12px;">No trade routes established.</p>';
      return;
    }

    let html = `<div style="font-size:11px;padding:4px 8px;color:var(--text-dim);">Total trade income: <b style="color:var(--text-bright);">${data.total_income || 0}</b> credits/hr &mdash; ${data.num_players || 1} player(s) in network</div>`;
    html += '<table class="data-table" style="font-size:11px;"><thead><tr><th>Base A</th><th>Base B</th><th>Distance</th><th>Income</th><th>Status</th></tr></thead><tbody>';
    for (const r of routes) {
      const status = r.is_closing ? '<span style="color:var(--danger);">Closing</span>' : r.is_pending ? '<span style="color:orange;">Pending</span>' : '<span style="color:var(--success);">Active</span>';
      html += `<tr>
        <td>${escStr(r.base_a?.name || '?')}</td>
        <td>${escStr(r.base_b?.name || '?')}</td>
        <td>${r.distance || 'â€”'}</td>
        <td>${r.income ? r.income.toFixed(1) : '0'}</td>
        <td>${status}</td>
      </tr>`;
    }
    html += '</tbody></table>';

    container.innerHTML = html;
  } catch (e) {
    console.error('loadReportTrade error:', e);
    container.innerHTML = '<p class="text-dim" style="padding:12px;font-size:12px;">Error loading trade report.</p>';
  }
}

// ============================================================
// REPORT: WORMHOLES
// ============================================================
async function _loadWormholeReport() {
  const container = document.getElementById('wormhole-report-content');
  if (!container) return;
  try {
    const res = await apiFetch('/api/wormhole-report');
    const data = await res.json();
    if (!data.length) {
      container.innerHTML = '<p class="text-dim" style="padding:12px;font-size:12px;">No wormholes found.</p>';
      return;
    }
    let html = `<div style="font-weight:bold;margin-bottom:6px;font-size:12px;">Known Wormholes</div>
      <table class="data-table" style="font-size:11px;">
        <thead><tr>
          <th>Location</th>
          <th>Galaxy</th>
          <th>Type</th>
        </tr></thead><tbody>`;
    for (const wh of data) {
      html += `<tr>
        <td>${coordLink(wh.location)}</td>
        <td>${escStr(wh.galaxy)}</td>
        <td>${wh.wormhole_type}</td>
      </tr>`;
    }
    html += '</tbody></table>';
    container.innerHTML = html;
  } catch (e) {
    container.innerHTML = '<p class="text-danger" style="padding:12px;font-size:12px;">Failed to load wormhole report.</p>';
  }
}

// ============================================================
// REPORT: TOP SCOUTERS
// ============================================================

async function loadTopScouters() {
  const container = document.getElementById('top-scouters-content');
  if (!container) return;
  try {
    const res = await apiFetch('/api/top-scouters');
    const data = await res.json();
    if (!data.length) {
      container.innerHTML = '<p class="text-dim" style="padding:12px;font-size:12px;">No scouting data available.</p>';
      return;
    }
    let html = `<div style="font-weight:bold;margin-bottom:6px;font-size:12px;">Top Scouters</div>
      <table class="data-table" style="font-size:11px;">
        <thead><tr><th>#</th><th>Player</th><th>Bases Scouted</th></tr></thead><tbody>`;
    data.forEach((r, i) => {
      html += `<tr><td>${i + 1}</td><td>${escStr(r.player)}</td><td>${r.scouted_count}</td></tr>`;
    });
    html += '</tbody></table>';
    container.innerHTML = html;
  } catch (e) {
    console.error('loadTopScouters error:', e);
    container.innerHTML = '<p class="text-dim" style="padding:12px;font-size:12px;">Error loading top scouters.</p>';
  }
}

// ============================================================
// REPORT: TOP JUMP GATES
// ============================================================

async function loadTopJumpGates() {
  const container = document.getElementById('top-jump-gates-content');
  if (!container) return;
  try {
    const res = await apiFetch('/api/top-jump-gates');
    const data = await res.json();
    if (!data.length) {
      container.innerHTML = '<p class="text-dim" style="padding:12px;font-size:12px;">No jump gates built yet.</p>';
      return;
    }
    let html = `<div style="font-weight:bold;margin-bottom:6px;font-size:12px;">Top Jump Gates</div>
      <table class="data-table" style="font-size:11px;">
        <thead><tr><th>#</th><th>Player</th><th>Base</th><th>Location</th><th>Level</th></tr></thead><tbody>`;
    data.forEach((r, i) => {
      html += `<tr><td>${i + 1}</td><td>${escStr(r.player)}</td><td>${escStr(r.base)}</td><td>${coordLink(r.location)}</td><td>${r.level}</td></tr>`;
    });
    html += '</tbody></table>';
    container.innerHTML = html;
  } catch (e) {
    console.error('loadTopJumpGates error:', e);
    container.innerHTML = '<p class="text-dim" style="padding:12px;font-size:12px;">Error loading jump gates.</p>';
  }
}

// ============================================================
// REPORT: ASTROS
// ============================================================

let _astrosGalaxies = null;
let _astrosGalaxyId = '';
let _astrosTerrain = '';
let _astrosType = '';
let _astrosOrbit = '';

async function loadAstrosReport() {
  const container = document.getElementById('astros-report-content');
  if (!container) return;

  // Fetch galaxies list for dropdown
  if (!_astrosGalaxies) {
    try {
      const galRes = await apiFetch('/api/galaxies');
      _astrosGalaxies = await galRes.json();
    } catch (e) { _astrosGalaxies = []; }
  }

  // Terrain filter options come from the client catalog, so the report honors the
  // active ruleset's terrain names (and admin overrides) instead of a hardcoded list.
  const _astroSpecs = await getCatalogSpecs('astros');
  const _terrainEntries = Object.entries(_astroSpecs)
    .filter(([, spec]) => spec && spec.colonizable !== false)
    .map(([key, spec]) => [key, spec.name || fmtType(key)])
    .sort((a, b) => a[1].localeCompare(b[1]));

  let galOpts = '<option value="">-- Galaxy --</option>';
  for (const g of _astrosGalaxies) {
    galOpts += `<option value="${g.id}"${_astrosGalaxyId == g.id ? ' selected' : ''}>${escStr(g.name)}</option>`;
  }

  let terrainOpts = '<option value="">All Terrain</option>';
  for (const [key, name] of _terrainEntries) {
    terrainOpts += `<option value="${key}"${_astrosTerrain === key ? ' selected' : ''}>${escStr(name)}</option>`;
  }

  let typeOpts = `<option value="">All Types</option>
    <option value="Planet"${_astrosType === 'Planet' ? ' selected' : ''}>Planet</option>
    <option value="Moon"${_astrosType === 'Moon' ? ' selected' : ''}>Moon</option>
    <option value="Asteroid"${_astrosType === 'Asteroid' ? ' selected' : ''}>Asteroid</option>`;

  let orbitOpts = '<option value="">All Orbits</option>';
  for (let i = 1; i <= 5; i++) {
    orbitOpts += `<option value="${i}"${_astrosOrbit == i ? ' selected' : ''}>Position ${i}</option>`;
  }

  let html = `<div style="margin-bottom:8px;font-size:11px;">
    <select id="astros-galaxy" onchange="_astrosGalaxyId=this.value">${galOpts}</select>
    <select id="astros-terrain" onchange="_astrosTerrain=this.value">${terrainOpts}</select>
    <select id="astros-type" onchange="_astrosType=this.value">${typeOpts}</select>
    <select id="astros-orbit" onchange="_astrosOrbit=this.value">${orbitOpts}</select>
    <button class="btn btn-primary btn-sm" onclick="fetchAstrosReport()">Report</button>
  </div>`;
  html += '<div id="astros-report-results"></div>';
  container.innerHTML = html;
}

async function fetchAstrosReport() {
  const results = document.getElementById('astros-report-results');
  if (!results) return;

  if (!_astrosGalaxyId) {
    results.innerHTML = '<p class="text-dim" style="font-size:11px;">Select a galaxy first.</p>';
    return;
  }

  results.innerHTML = '<p class="text-dim" style="font-size:11px;">Loading...</p>';

  let url = `/api/astros-report?galaxy_id=${_astrosGalaxyId}`;
  if (_astrosTerrain) url += `&terrain=${_astrosTerrain}`;
  if (_astrosType) url += `&body_type=${_astrosType}`;
  if (_astrosOrbit) url += `&orbit=${_astrosOrbit}`;

  try {
    const res = await apiFetch(url);
    const data = await res.json();
    const astros = data.results || [];

    if (!astros.length) {
      results.innerHTML = '<p class="text-dim" style="font-size:11px;">No astros found matching criteria.</p>';
      return;
    }

    let html = `<div style="font-size:10px;color:var(--text-dim);margin-bottom:4px;">${data.count} result${data.count !== 1 ? 's' : ''}</div>`;
    html += `<table class="data-table" style="font-size:11px;">
      <thead><tr><th>Location</th><th>Terrain</th><th>Type</th><th>Orbit</th><th>Area</th><th>Solar</th><th>Fertility</th><th>Metal</th><th>Gas</th><th>Crystal</th><th>Base</th></tr></thead><tbody>`;
    for (const a of astros) {
      const ownerCell = a.occupied ? '<span class="text-bright">Yes</span>' : '';
      html += `<tr>
        <td>${coordLink(a.location)}</td>
        <td>${escStr(a.terrain)}</td>
        <td>${escStr(a.type)}</td>
        <td>${a.orbit}</td>
        <td>${a.area}</td>
        <td>${a.solar}</td>
        <td>${a.fertility}</td>
        <td>${a.metal}</td>
        <td>${a.gas}</td>
        <td>${a.crystal}</td>
        <td>${ownerCell}</td>
      </tr>`;
    }
    html += '</tbody></table>';
    results.innerHTML = html;
  } catch (e) {
    console.error('fetchAstrosReport error:', e);
    results.innerHTML = '<p class="text-dim" style="font-size:11px;">Error loading astros report.</p>';
  }
}

// ============================================================
// REPORT: PLAYER (Reports > Player)
// ============================================================

let _playerReportId = '';
let _playerReportShow = 'bases';

async function loadPlayerReport() {
  const container = document.getElementById('player-report-container');
  if (!container) return;

  let showSelect = `<select id="player-report-show" onchange="_playerReportShow=this.value">
    <option value="bases"${_playerReportShow === 'bases' ? ' selected' : ''}>Bases</option>
    <option value="fleets"${_playerReportShow === 'fleets' ? ' selected' : ''}>Fleets</option>
    <option value="moving_fleets"${_playerReportShow === 'moving_fleets' ? ' selected' : ''}>Moving Fleets</option>
  </select>`;

  let html = `<div style="margin-bottom:8px;">Player ID: <input type="number" id="player-report-id" value="${escStr(_playerReportId)}" placeholder="Player ID" class="player-report-id-input" min="1" onkeydown="if(event.key==='Enter')fetchPlayerReport()"> &nbsp; Show: ${showSelect} &nbsp; <button class="btn btn-primary btn-sm" onclick="fetchPlayerReport()">Get Report</button></div>`;
  html += '<div id="player-report-results"></div>';
  container.innerHTML = html;
}

async function fetchPlayerReport() {
  const idInput = document.getElementById('player-report-id');
  _playerReportId = idInput ? idInput.value.trim() : '';
  const results = document.getElementById('player-report-results');
  if (!results) return;

  if (!_playerReportId || isNaN(_playerReportId)) {
    results.innerHTML = '<div class="empty-state"><p>Enter a player ID to search.</p></div>';
    return;
  }

  results.innerHTML = '<div class="empty-state"><p>Loading...</p></div>';

  try {
    const res = await apiFetch(`/api/player-report?player_id=${_playerReportId}&show=${_playerReportShow}`);
    const data = await res.json();

    const rows = Array.isArray(data) ? data : (data.data || data.bases || []);
    let html = '';
    if (data.message && !rows.length) {
      html = `<div class="empty-state"><p>${data.message}</p></div>`;
    } else if (!rows.length) {
      html = `<div class="empty-state"><p>No data found for player #${escStr(_playerReportId)}. Scout regions to discover their bases.</p></div>`;
    } else if (_playerReportShow === 'bases') {
      html = '<table class="data-table"><thead><tr><th>Player</th><th>Base</th><th>Location</th><th>Last Seen</th></tr></thead><tbody>';
      for (const r of rows) {
        const lastSeen = r.last_seen ? fmtDate(r.last_seen) : '';
        html += `<tr><td class="text-bright">${escStr(r.player)}</td><td>${escStr(r.base)}</td><td>${coordLink(r.location)}</td><td class="text-dim">${lastSeen}</td></tr>`;
      }
      html += '</tbody></table>';
    } else if (_playerReportShow === 'fleets') {
      html = '<table class="data-table"><thead><tr><th>Player</th><th>Location</th><th>Size</th><th>Date Seen</th></tr></thead><tbody>';
      for (const r of rows) {
        const daysAgo = r.days_ago != null ? `${r.days_ago} day(s) ago` : '';
        html += `<tr><td class="text-bright">${escStr(r.player)}</td><td>${coordLink(r.location)}</td><td>${(r.size||0).toLocaleString()}</td><td class="text-dim">${daysAgo}</td></tr>`;
      }
      html += '</tbody></table>';
    } else if (_playerReportShow === 'moving_fleets') {
      html = '<table class="data-table"><thead><tr><th>Player</th><th>Destination</th><th>Arrival</th><th>Size</th><th>Date Seen</th></tr></thead><tbody>';
      for (const r of rows) {
        const daysAgo = r.days_ago != null ? `${r.days_ago} day(s) ago` : '';
        const arrival = r.arrival ? fmtDateTime(r.arrival) : '';
        html += `<tr><td class="text-bright">${escStr(r.player)}</td><td>${coordLink(r.destination||'')}</td><td>${arrival}</td><td>${(r.size||0).toLocaleString()}</td><td class="text-dim">${daysAgo}</td></tr>`;
      }
      html += '</tbody></table>';
    }

    results.innerHTML = html;
  } catch (e) { console.error(e); results.innerHTML = '<div class="empty-state"><p>Error loading report.</p></div>'; }
}

// ============================================================
// REPORT: GUILD (Reports > Guild)
// ============================================================

let _guildReportGuildId = null;
let _guildReportShow = 'bases';
let _guildReportGuilds = null;

async function loadGuildReport() {
  const container = document.getElementById('guild-report-container');
  if (!container) return;

  // Cache guild list
  if (!_guildReportGuilds) {
    try {
      const res = await apiFetch('/api/guilds');
      _guildReportGuilds = await res.json();
    } catch (e) { _guildReportGuilds = []; }
  }

  // Default to first guild if none selected
  if (!_guildReportGuildId && _guildReportGuilds.length > 0) {
    _guildReportGuildId = _guildReportGuilds[0].id;
  }

  let guildSelect = `<select id="guild-report-guild" onchange="_guildReportGuildId=parseInt(this.value)">`;
  for (const g of _guildReportGuilds) {
    guildSelect += `<option value="${g.id}" ${g.id === _guildReportGuildId ? 'selected' : ''}>[${escStr(g.tag)}] ${escStr(g.name)}</option>`;
  }
  guildSelect += '</select>';

  let showSelect = `<select id="guild-report-show" onchange="_guildReportShow=this.value">
    <option value="bases"${_guildReportShow === 'bases' ? ' selected' : ''}>Bases</option>
    <option value="fleets"${_guildReportShow === 'fleets' ? ' selected' : ''}>Fleets</option>
    <option value="moving_fleets"${_guildReportShow === 'moving_fleets' ? ' selected' : ''}>Moving Fleets</option>
  </select>`;

  let html = '';
  if (!_guildReportGuilds.length) {
    html = '<div class="empty-state"><p>No guilds exist yet.</p></div>';
  } else {
    html = `<div style="margin-bottom:8px;">Guild: ${guildSelect} &nbsp; Show: ${showSelect} &nbsp; <button class="btn btn-primary btn-sm" onclick="fetchGuildReport()">Get Report</button></div>`;
    html += '<div id="guild-report-results"></div>';
  }
  container.innerHTML = html;
}

async function fetchGuildReport() {
  const results = document.getElementById('guild-report-results');
  if (!results) return;

  if (!_guildReportGuildId) {
    results.innerHTML = '<div class="empty-state"><p>No guild selected.</p></div>';
    return;
  }

  results.innerHTML = '<div class="empty-state"><p>Loading...</p></div>';

  try {
    const res = await apiFetch(`/api/guild-report?guild_id=${_guildReportGuildId}&show=${_guildReportShow}`);
    const data = await res.json();

    const rows = Array.isArray(data) ? data : (data.data || []);
    let html = '';
    if (data.message && !rows.length) {
      html = `<div class="empty-state"><p>${data.message}</p></div>`;
    } else if (!rows.length) {
      html = `<div class="empty-state"><p>No data. Scout regions to discover guild member activity.</p></div>`;
    } else if (_guildReportShow === 'bases') {
      html = '<table class="data-table"><thead><tr><th>Player</th><th>Base</th><th>Location</th><th>Last Seen</th></tr></thead><tbody>';
      for (const r of rows) {
        const lastSeen = r.last_seen ? fmtDate(r.last_seen) : '';
        html += `<tr><td class="text-bright">${escStr(r.player)}</td><td>${escStr(r.base)}</td><td>${coordLink(r.location)}</td><td class="text-dim">${lastSeen}</td></tr>`;
      }
      html += '</tbody></table>';
    } else if (_guildReportShow === 'fleets') {
      html = '<table class="data-table"><thead><tr><th>Player</th><th>Location</th><th>Size</th><th>Date Seen</th></tr></thead><tbody>';
      for (const r of rows) {
        const daysAgo = r.days_ago != null ? `${r.days_ago} day(s) ago` : '';
        html += `<tr><td class="text-bright">${escStr(r.player)}</td><td>${coordLink(r.location)}</td><td>${(r.size||0).toLocaleString()}</td><td class="text-dim">${daysAgo}</td></tr>`;
      }
      html += '</tbody></table>';
    } else if (_guildReportShow === 'moving_fleets') {
      html = '<table class="data-table"><thead><tr><th>Player</th><th>Destination</th><th>Arrival</th><th>Size</th><th>Date Seen</th></tr></thead><tbody>';
      for (const r of rows) {
        const daysAgo = r.days_ago != null ? `${r.days_ago} day(s) ago` : '';
        const arrival = r.arrival ? fmtDateTime(r.arrival) : '';
        html += `<tr><td class="text-bright">${escStr(r.player)}</td><td>${coordLink(r.destination||'')}</td><td>${arrival}</td><td>${(r.size||0).toLocaleString()}</td><td class="text-dim">${daysAgo}</td></tr>`;
      }
      html += '</tbody></table>';
    }

    results.innerHTML = html;
  } catch (e) { console.error(e); results.innerHTML = '<div class="empty-state"><p>Error loading report.</p></div>'; }
}

// ============================================================
// GALAXY REPORT (Empire > Reports > Galaxy Report)
// ============================================================

let _galaxyReportGalaxyId = null;
let _galaxyReportShow = 'bases';
let _galaxyReportGalaxies = null;

async function loadGalaxyReport() {
  const container = document.getElementById('galaxy-report-container');
  if (!container) return;

  // If no galaxy selected, pick user's home galaxy
  if (!_galaxyReportGalaxyId) {
    try {
      const res = await apiFetch('/api/my-bases-coords');
      const data = await res.json();
      if (data.length > 0) _galaxyReportGalaxyId = data[0].galaxy_id;
    } catch (e) {}
  }

  // Cache galaxy list
  if (!_galaxyReportGalaxies) {
    try {
      const galRes = await apiFetch('/api/galaxies');
      _galaxyReportGalaxies = await galRes.json();
    } catch (e) { _galaxyReportGalaxies = []; }
  }

  // Build controls
  let galSelect = `<select id="galaxy-report-galaxy" onchange="_galaxyReportGalaxyId=parseInt(this.value)">`;
  for (const g of _galaxyReportGalaxies) {
    galSelect += `<option value="${g.id}" ${g.id === _galaxyReportGalaxyId ? 'selected' : ''}>${g.name}</option>`;
  }
  galSelect += '</select>';

  let showSelect = `<select id="galaxy-report-show" onchange="_galaxyReportShow=this.value">
    <option value="bases"${_galaxyReportShow === 'bases' ? ' selected' : ''}>Bases</option>
    <option value="fleets"${_galaxyReportShow === 'fleets' ? ' selected' : ''}>Fleets</option>
    <option value="moving_fleets"${_galaxyReportShow === 'moving_fleets' ? ' selected' : ''}>Moving Fleets</option>
  </select>`;

  let html = `<div style="margin-bottom:8px;">Galaxy: ${galSelect} &nbsp; Show: ${showSelect} &nbsp; <button class="btn btn-primary btn-sm" onclick="fetchGalaxyReport()">Get Report</button></div>`;
  html += '<div id="galaxy-report-results"></div>';
  container.innerHTML = html;
}

async function fetchGalaxyReport() {
  const results = document.getElementById('galaxy-report-results');
  if (!results) return;

  if (!_galaxyReportGalaxyId) {
    results.innerHTML = '<div class="empty-state"><p>No galaxy selected.</p></div>';
    return;
  }

  results.innerHTML = '<div class="empty-state"><p>Loading...</p></div>';

  try {
    const res = await apiFetch(`/api/galaxy-report?galaxy_id=${_galaxyReportGalaxyId}&show=${_galaxyReportShow}`);
    const data = await res.json();

    const rows = Array.isArray(data) ? data : (data.data || []);
    let html = '';
    if (data.message && !rows.length) {
      html = `<div class="empty-state"><p>${data.message}</p></div>`;
    } else if (!rows.length) {
      html = `<div class="empty-state"><p>No data. Send Scout Ships to explore the galaxy.</p></div>`;
    } else if (_galaxyReportShow === 'bases') {
      html = '<table class="data-table"><thead><tr><th>Player</th><th>Base</th><th>Location</th><th>Last Seen</th></tr></thead><tbody>';
      for (const r of rows) {
        const lastSeen = r.last_seen ? fmtDate(r.last_seen) : '';
        html += `<tr><td class="text-bright">${escStr(r.player)}</td><td>${escStr(r.base)}</td><td>${coordLink(r.location)}</td><td class="text-dim">${lastSeen}</td></tr>`;
      }
      html += '</tbody></table>';
    } else if (_galaxyReportShow === 'fleets') {
      html = '<table class="data-table"><thead><tr><th>Player</th><th>Location</th><th>Size</th><th>Date Seen</th></tr></thead><tbody>';
      for (const r of rows) {
        const daysAgo = r.days_ago != null ? `${r.days_ago} day(s) ago` : '';
        html += `<tr><td class="text-bright">${escStr(r.player)}</td><td>${coordLink(r.location)}</td><td>${(r.size||0).toLocaleString()}</td><td class="text-dim">${daysAgo}</td></tr>`;
      }
      html += '</tbody></table>';
    } else if (_galaxyReportShow === 'moving_fleets') {
      html = '<table class="data-table"><thead><tr><th>Player</th><th>Destination</th><th>Arrival</th><th>Size</th><th>Date Seen</th></tr></thead><tbody>';
      for (const r of rows) {
        const daysAgo = r.days_ago != null ? `${r.days_ago} day(s) ago` : '';
        const arrival = r.arrival ? fmtDateTime(r.arrival) : '';
        html += `<tr><td class="text-bright">${escStr(r.player)}</td><td>${coordLink(r.destination||'')}</td><td>${arrival}</td><td>${(r.size||0).toLocaleString()}</td><td class="text-dim">${daysAgo}</td></tr>`;
      }
      html += '</tbody></table>';
    }

    results.innerHTML = html;
  } catch (e) { console.error(e); results.innerHTML = '<div class="empty-state"><p>Error loading report.</p></div>'; }
}
