/* ============================================================
   AstroWebEngine - Frontend (social_scanners.js)
   Scanner report hub and scanner-specific UI
   Split from social.js for easier maintenance
   ============================================================ */
async function loadScanners() {
  const container = document.getElementById('scanners-container');
  if (!container) return;

  // Full registry of all possible report types
  const ALL_REPORTS = {
    scanners: 'Scanners', player: 'Player', guild: 'Guild', galaxy: 'Galaxy',
    top_scouters: 'Top Scouters', top_jump_gates: 'Top Jump Gates',
    trade: 'Trade', wormholes: 'Wormholes', astros: 'Astros',
  };
  // Read enabled categories from engine config (defaults to all report categories)
  const enabledCategories = getEngineFlag('report_categories', Object.keys(ALL_REPORTS));
  const reportTabs = enabledCategories.filter(k => k in ALL_REPORTS);
  const reportLabels = {};
  for (const k of reportTabs) reportLabels[k] = ALL_REPORTS[k];
  // Reset to first tab if current tab is not enabled
  if (!reportTabs.includes(_scannersTab)) _scannersTab = reportTabs[0] || 'scanners';

  // Sidebar + content layout
  let sidebarHtml = `<div class="awe-sidebar report-split-sidebar">`;
  for (const tab of reportTabs) {
    sidebarHtml += `<a href="#" class="awe-sidebar-link ${_scannersTab===tab?'active':''}" onclick="_scannersTab='${tab}';loadScanners();return false;">${reportLabels[tab]}</a>`;
  }
  sidebarHtml += `</div>`;

  if (_scannersTab === 'galaxy' || _scannersTab === 'galaxy_report') {
    _scannersTab = 'galaxy';
    container.innerHTML = `<div style="text-align:center;font-size:14px;margin-bottom:8px;color:var(--text-bright);"><b>R</b>eports</div>
      <div class="report-split-layout">${sidebarHtml}<div class="report-split-main" id="galaxy-report-container"></div></div>`;
    if (typeof loadGalaxyReport === 'function') loadGalaxyReport();
    return;
  }

  if (_scannersTab === 'trade') {
    container.innerHTML = `<div style="text-align:center;font-size:14px;margin-bottom:8px;color:var(--text-bright);"><b>R</b>eports</div>
      <div class="report-split-layout">${sidebarHtml}<div class="report-split-main" id="report-trade-content"><p class="text-dim" style="padding:12px;font-size:12px;">Guild's bases with empty trade routes</p></div></div>`;
    loadReportTrade();
    return;
  }

  if (_scannersTab === 'player') {
    container.innerHTML = `<div style="text-align:center;font-size:14px;margin-bottom:8px;color:var(--text-bright);"><b>R</b>eports</div>
      <div class="report-split-layout">${sidebarHtml}<div class="report-split-main" id="player-report-container"></div></div>`;
    loadPlayerReport();
    return;
  }

  if (_scannersTab === 'guild') {
    container.innerHTML = `<div style="text-align:center;font-size:14px;margin-bottom:8px;color:var(--text-bright);"><b>R</b>eports</div>
      <div class="report-split-layout">${sidebarHtml}<div class="report-split-main" id="guild-report-container"></div></div>`;
    loadGuildReport();
    return;
  }

  if (_scannersTab === 'wormholes') {
    container.innerHTML = `<div style="text-align:center;font-size:14px;margin-bottom:8px;color:var(--text-bright);"><b>R</b>eports</div>
      <div class="report-split-layout">${sidebarHtml}<div class="report-split-main" id="wormhole-report-content"><p class="text-dim" style="padding:12px;font-size:12px;">Loading...</p></div></div>`;
    _loadWormholeReport();
    return;
  }

  if (_scannersTab === 'top_scouters') {
    container.innerHTML = `<div style="text-align:center;font-size:14px;margin-bottom:8px;color:var(--text-bright);"><b>R</b>eports</div>
      <div class="report-split-layout">${sidebarHtml}<div class="report-split-main" id="top-scouters-content"><p class="text-dim" style="padding:12px;font-size:12px;">Loading...</p></div></div>`;
    loadTopScouters();
    return;
  }

  if (_scannersTab === 'top_jump_gates') {
    container.innerHTML = `<div style="text-align:center;font-size:14px;margin-bottom:8px;color:var(--text-bright);"><b>R</b>eports</div>
      <div class="report-split-layout">${sidebarHtml}<div class="report-split-main" id="top-jump-gates-content"><p class="text-dim" style="padding:12px;font-size:12px;">Loading...</p></div></div>`;
    loadTopJumpGates();
    return;
  }

  if (_scannersTab === 'astros') {
    container.innerHTML = `<div style="text-align:center;font-size:14px;margin-bottom:8px;color:var(--text-bright);"><b>R</b>eports</div>
      <div class="report-split-layout">${sidebarHtml}<div class="report-split-main" id="astros-report-content"><p class="text-dim" style="padding:12px;font-size:12px;">Loading...</p></div></div>`;
    loadAstrosReport();
    return;
  }

  // Default: Scanners
  try {
    const res = await apiFetch('/api/scanners');
    const data = await res.json();

    let contentHtml = `<div style="font-weight:bold;margin-bottom:6px;font-size:12px;">Fleet movements detected in your base regions</div>`;

    if (!data.length) {
      contentHtml += '<div class="empty-state"><p>No incoming fleet movements detected in your base regions.</p></div>';
    } else {
      contentHtml += '<table class="data-table"><thead><tr><th>Player</th><th>Fleet</th><th>Destination</th><th>Size</th><th>Arrival</th><th>ETA</th></tr></thead><tbody>';
      for (const r of data) {
        const playerDisplay = r.guild_tag ? `[${escStr(r.guild_tag)}] ${escStr(r.player)}` : escStr(r.player);
        const playerClass = r.is_own ? 'text-accent' : 'text-bright';
        const fleetName = r.fleet_name ? escStr(r.fleet_name) : 'â€”';
        const dest = escStr(r.destination || '');
        const arrival = r.arrival ? `<span class="countdown" data-end="${r.arrival}">${fmtTime(Math.max(0, (serverDate(r.arrival) - Date.now()) / 1000))}</span>` : '';
        const arrivalTime = r.arrival ? fmtDateTime(r.arrival) : '';

        let shipInfo = '';
        if (r.ships) {
          const shipList = Object.entries(r.ships).map(([k, v]) => `${k.replace(/_/g, ' ')} x${v}`).join(', ');
          shipInfo = `<div class="text-dim" style="font-size:10px;">${shipList}</div>`;
        }

        contentHtml += `<tr>
          <td class="${playerClass}">${playerDisplay}</td>
          <td>${fleetName}${shipInfo}</td>
          <td>${coordLink(dest)}</td>
          <td>${(r.size||0).toLocaleString()}</td>
          <td class="text-dim">${arrivalTime}</td>
          <td>${arrival}</td>
        </tr>`;
      }
      contentHtml += '</tbody></table>';
    }

    container.innerHTML = `<div style="text-align:center;font-size:14px;margin-bottom:8px;color:var(--text-bright);"><b>R</b>eports</div>
      <div class="report-split-layout">${sidebarHtml}<div class="report-split-main">${contentHtml}</div></div>`;
    updateCountdowns();
  } catch (e) {
    console.error(e);
    container.innerHTML = `<div style="text-align:center;font-size:14px;margin-bottom:8px;color:var(--text-bright);"><b>R</b>eports</div>
      <div class="report-split-layout">${sidebarHtml}<div class="report-split-main"><div class="empty-state"><p>Error loading scanners.</p></div></div></div>`;
  }
}

// ============================================================
// REPORT: TRADE (Reports > Trade)
// ============================================================

