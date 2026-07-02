/* ═══════════════════════════════════════════════════
   AstroWebEngine — Frontend (map.js)
   Galaxy map (configurable drill-down), regions, systems,
   planets, planet details, colonize, send fleet modals
   Map depth: 4 = Galaxy → Region → System → Orbit
   ═══════════════════════════════════════════════════ */

// ============================================================
// GALAXY MAP — configurable drill-down depth
// ============================================================

/** Get map depth from engine config (default 4) */
function getMapDepth() { return getEngineFlag('map_depth', 4); }

let clusterData = [], galaxyData = [];
let currentClusterId = null, currentGalaxyId = null, currentGalaxyName = '';
let currentRegionId = null, currentSystemId = null;
let regionSummaryData = [], _currentSystems = [];

// Map drill-down state: 'galaxy' | 'region' | 'system'
let _mapLevel = 'galaxy';
let _selectedRegionName = '';
let _selectedSystemName = '';
let _mapSidebarPicker = '';
let _mapSidebarSection = '';
let _mapSidebarPos = { x: 18, y: 18 };
let _mapSidebarDrag = null;
let _mapSidebarHighlights = {
  bases: [],
  fleets: [],
  portals: [],
  guilds: [],
};
let _galaxyZoomStage = 0;
let _galaxyZoomFocus = { x: 50, y: 50 };
let _galaxyZoomRegionId = null;
let _regionZoomStage = 0;
let _regionZoomFocus = { x: 50, y: 50 };
let _currentRegionRender = null;

function getSelectedRegionCoord() {
  if (_selectedRegionName) return _selectedRegionName;
  const region = regionSummaryData.find(r => r.id === currentRegionId);
  if (!region || !currentGalaxyName) return '';
  return `${currentGalaxyName}:${region.name}`;
}

function getSelectedRegionNumber() {
  const coord = getSelectedRegionCoord();
  return coord.includes(':') ? coord.split(':').pop() : coord;
}

function getSelectedSystemNumber() {
  const coord = _selectedSystemName || '';
  return coord.includes(':') ? coord.split(':').pop() : coord;
}

function getMapLocationInputValue() {
  if (_selectedSystemName) return _selectedSystemName;
  if (_selectedRegionName) return _selectedRegionName;
  return currentGalaxyName || '';
}

function getMapSidebarGalaxies() {
  const flattened = clusterData
    .slice()
    .sort((a, b) => (a.cluster_index || 0) - (b.cluster_index || 0))
    .flatMap((cluster) =>
      (cluster.galaxies || [])
        .slice()
        .sort((a, b) => (a.galaxy_index || 0) - (b.galaxy_index || 0))
    );
  if (flattened.length) return flattened;
  return (galaxyData || [])
    .slice()
    .sort((a, b) => String(a.name || '').localeCompare(String(b.name || ''), undefined, { numeric: true }));
}

function getGalaxyPickerCode(name) {
  const match = String(name || '').match(/(\d{2,})$/);
  return match ? match[1].slice(-2) : String(name || '');
}

function toggleMapSidebarPicker(kind) {
  if (kind === 'region' && !currentGalaxyId) return false;
  _mapSidebarPicker = _mapSidebarPicker === kind ? '' : kind;
  renderGalaxySidebar();
  return false;
}

function toggleMapSidebarSection(name) {
  _mapSidebarSection = _mapSidebarSection === name ? '' : name;
  renderGalaxySidebar();
  return false;
}

function pickSidebarGalaxy(galaxyId) {
  _mapSidebarPicker = '';
  selectGalaxy(parseInt(galaxyId, 10));
  return false;
}

function pickSidebarRegion(regionCode) {
  const code = String(regionCode || '').padStart(2, '0');
  const region = regionSummaryData.find(r => String(r.name || '').padStart(2, '0') === code);
  _mapSidebarPicker = '';
  if (region) {
    selectRegion(region.id, `${currentGalaxyName}:${code}`);
  } else if (currentGalaxyName) {
    coordToMap(`${currentGalaxyName}:${code}`);
  }
  return false;
}

function submitMapSidebarLocation() {
  const input = document.getElementById('map-coord-input');
  const value = (input?.value || '').trim();
  if (!value) return false;
  _mapSidebarPicker = '';
  coordToMap(value);
  return false;
}

function renderMapSidebarPicker() {
  if (_mapSidebarPicker === 'galaxy') {
    const items = getMapSidebarGalaxies().map((g) => {
      const cls = g.id === currentGalaxyId ? ' active' : '';
      return `<button class="map-side-picker-item${cls}" onclick="pickSidebarGalaxy(${g.id});return false;">${escStr(getGalaxyPickerCode(g.name))}</button>`;
    }).join('');
    return `<div class="map-side-picker"><div class="map-side-picker-grid galaxy">${items}</div></div>`;
  }
  if (_mapSidebarPicker === 'region') {
    const items = Array.from({ length: 100 }, (_, index) => {
      const code = String(index).padStart(2, '0');
      const region = regionSummaryData.find(r => String(r.name || '').padStart(2, '0') === code);
      const cls = `${region ? '' : ' muted'}${region?.id === currentRegionId ? ' active' : ''}`;
      return `<button class="map-side-picker-item${cls}" onclick="pickSidebarRegion('${escAttr(code)}');return false;">${code}</button>`;
    }).join('');
    return `<div class="map-side-picker"><div class="map-side-picker-grid region">${items}</div></div>`;
  }
  return '';
}

function setMapSidebarHighlightData(kind, items) {
  const key = String(kind || '').toLowerCase();
  if (!Object.prototype.hasOwnProperty.call(_mapSidebarHighlights, key)) return;
  _mapSidebarHighlights[key] = Array.isArray(items) ? items : [];
  if (_mapLevel === 'galaxy' && regionSummaryData.length) {
    renderRegionGrid(regionSummaryData);
  }
}

function loadMapSidebarPosition() {
  try {
    const raw = localStorage.getItem('awe_map_sidebar_pos');
    if (!raw) return;
    const parsed = JSON.parse(raw);
    if (Number.isFinite(parsed?.x) && Number.isFinite(parsed?.y)) {
      _mapSidebarPos = { x: parsed.x, y: parsed.y };
    }
  } catch (_) {}
}

function saveMapSidebarPosition() {
  try {
    localStorage.setItem('awe_map_sidebar_pos', JSON.stringify(_mapSidebarPos));
  } catch (_) {}
}

function getMapSidebarBounds() {
  const layout = document.querySelector('#tab-galaxy .map-layout');
  const mapView = document.getElementById('map-view');
  const sidebar = document.getElementById('map-sidebar');
  if (!layout || !mapView || !sidebar) return null;

  const layoutRect = layout.getBoundingClientRect();
  const mapRect = mapView.getBoundingClientRect();
  const sidebarRect = sidebar.getBoundingClientRect();

  return {
    minX: Math.max(0, mapRect.left - layoutRect.left + 6),
    minY: Math.max(0, mapRect.top - layoutRect.top + 6),
    maxX: Math.max(0, mapRect.right - layoutRect.left - sidebarRect.width - 6),
    maxY: Math.max(0, mapRect.bottom - layoutRect.top - sidebarRect.height - 6),
  };
}

function clampMapSidebarPosition() {
  const bounds = getMapSidebarBounds();
  if (!bounds) return;
  _mapSidebarPos = {
    x: Math.max(bounds.minX, Math.min(bounds.maxX, _mapSidebarPos.x)),
    y: Math.max(bounds.minY, Math.min(bounds.maxY, _mapSidebarPos.y)),
  };
}

function applyMapSidebarPosition() {
  const sidebar = document.getElementById('map-sidebar');
  if (!sidebar) return;
  clampMapSidebarPosition();
  sidebar.style.left = `${_mapSidebarPos.x}px`;
  sidebar.style.top = `${_mapSidebarPos.y}px`;
}

function beginMapSidebarDrag(e) {
  const sidebar = document.getElementById('map-sidebar');
  if (!sidebar) return;
  if (e.button !== 0) return;
  const rect = sidebar.getBoundingClientRect();
  _mapSidebarDrag = {
    offsetX: e.clientX - rect.left,
    offsetY: e.clientY - rect.top,
  };
  document.body.classList.add('map-sidebar-dragging');
  e.preventDefault();
}

function updateMapSidebarDrag(e) {
  if (!_mapSidebarDrag) return;
  const layout = document.querySelector('#tab-galaxy .map-layout');
  if (!layout) return;
  const layoutRect = layout.getBoundingClientRect();
  _mapSidebarPos = {
    x: e.clientX - layoutRect.left - _mapSidebarDrag.offsetX,
    y: e.clientY - layoutRect.top - _mapSidebarDrag.offsetY,
  };
  applyMapSidebarPosition();
}

function endMapSidebarDrag() {
  if (!_mapSidebarDrag) return;
  _mapSidebarDrag = null;
  document.body.classList.remove('map-sidebar-dragging');
  saveMapSidebarPosition();
}

function initMapSidebarDrag() {
  document.addEventListener('pointermove', updateMapSidebarDrag);
  document.addEventListener('pointerup', endMapSidebarDrag);
  document.addEventListener('pointercancel', endMapSidebarDrag);
  window.addEventListener('resize', applyMapSidebarPosition);
}

function setRegionZoomStage(stage, focusX = null, focusY = null) {
  _regionZoomStage = Math.max(0, Math.min(3, stage));
  if (Number.isFinite(focusX) && Number.isFinite(focusY)) {
    _regionZoomFocus = {
      x: Math.max(0, Math.min(100, focusX)),
      y: Math.max(0, Math.min(100, focusY)),
    };
  }
  if (_currentRegionRender) {
    renderSystemList(
      _currentRegionRender.systems,
      _currentRegionRender.isSnapshot,
      _currentRegionRender.isFog,
    );
  }
}

function setGalaxyZoomStage(stage, regionId = null, focusX = null, focusY = null) {
  _galaxyZoomStage = Math.max(0, Math.min(3, stage));
  if (regionId != null && Number.isFinite(regionId)) {
    _galaxyZoomRegionId = regionId;
  } else if (_galaxyZoomStage === 0) {
    _galaxyZoomRegionId = null;
  }
  if (Number.isFinite(focusX) && Number.isFinite(focusY)) {
    _galaxyZoomFocus = {
      x: Math.max(0, Math.min(100, focusX)),
      y: Math.max(0, Math.min(100, focusY)),
    };
  }
  if (regionSummaryData.length) renderRegionGrid(regionSummaryData);
}

function getGalaxyZoomFocusFromEvent(e) {
  const mapEl = e.target.closest('.region-grid-viewport');
  if (!mapEl) return null;
  const rect = mapEl.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;

  const displayX = ((e.clientX - rect.left) / rect.width) * 100;
  const displayY = ((e.clientY - rect.top) / rect.height) * 100;
  const currentZoom = [1, 1.7, 3.0, 5.0][_galaxyZoomStage] || 1;
  const focusX = _galaxyZoomFocus.x + ((displayX - 50) / currentZoom);
  const focusY = _galaxyZoomFocus.y + ((displayY - 50) / currentZoom);

  return {
    x: Math.max(0, Math.min(100, focusX)),
    y: Math.max(0, Math.min(100, focusY)),
  };
}

function getRegionZoomFocusFromEvent(e) {
  const mapEl = e.target.closest('.starfield-map-region');
  if (!mapEl) return null;
  const rect = mapEl.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;

  const displayX = ((e.clientX - rect.left) / rect.width) * 100;
  const displayY = ((e.clientY - rect.top) / rect.height) * 100;
  const currentZoom = [1, 1.7, 3.0, 5.0][_regionZoomStage] || 1;
  const focusX = _regionZoomFocus.x + ((displayX - 50) / currentZoom);
  const focusY = _regionZoomFocus.y + ((displayY - 50) / currentZoom);

  return {
    x: Math.max(0, Math.min(100, focusX)),
    y: Math.max(0, Math.min(100, focusY)),
  };
}

function showMapLevel(level) {
  _mapLevel = level;
  document.querySelectorAll('.map-level').forEach(el => el.classList.remove('active'));
  const target = document.getElementById(`map-level-${level}`);
  if (target) target.classList.add('active');
  const mapView = document.getElementById('map-view');
  if (mapView) mapView.classList.toggle('system-page', level === 'system');
  renderGalaxySidebar();
  updateBreadcrumb();
  updateMapSubnav();
}

function updateBreadcrumb() {
  const bc = document.getElementById('map-breadcrumb');
  if (!bc) return;
  if (_mapLevel !== 'system' || !currentGalaxyName || !currentSystemId) {
    bc.innerHTML = '';
    bc.style.display = 'none';
    return;
  }
  const regionNum = getSelectedRegionNumber();
  const systemNum = getSelectedSystemNumber();
  bc.style.display = 'flex';
  if (getMapDepth() === 3) {
    // Flat map: galaxy > system (the region is hidden). Coords are galaxy:system:position.
    const sysCoord = _selectedSystemName || `${currentGalaxyName}:${systemNum}`;
    bc.innerHTML = `<b><a class="bc-link" onclick="navigateToGalaxy()">Galaxy ${escStr(currentGalaxyName)}</a>
      <span class="bc-sep">&gt;</span>
      <span class="bc-current">System ${escStr(systemNum)}</span>
      <span class="bc-coords">(${coordLink(sysCoord)})</span></b>`;
    return;
  }
  const sysCoord = _selectedSystemName || `${currentGalaxyName}:${regionNum}:${systemNum}`;
  bc.innerHTML = `<b><a class="bc-link" onclick="navigateToGalaxy()">Galaxy ${escStr(currentGalaxyName)}</a>
    <span class="bc-sep">&gt;</span>
    <a class="bc-link" onclick="navigateToRegion()">Region ${escStr(regionNum)}</a>
    <span class="bc-sep">&gt;</span>
    <span class="bc-current">System ${escStr(systemNum)}</span>
    <span class="bc-coords">(${coordLink(sysCoord)})</span></b>`;
}

function updateMapSubnav() {
  const galaxyLink = document.getElementById('map-nav-galaxy');
  const regionLink = document.getElementById('map-nav-region');
  const sidebar = document.getElementById('map-sidebar');
  if (sidebar) sidebar.classList.toggle('system-mode', _mapLevel === 'system');
  if (!galaxyLink || !regionLink) return;

  galaxyLink.classList.toggle('active', _mapLevel === 'galaxy');
  regionLink.classList.toggle('active', _mapLevel === 'region');
  regionLink.classList.toggle('disabled', !currentGalaxyId);
}

function syncMapGalaxySelect() {
  const select = document.getElementById('map-galaxy-select');
  if (!select) return;
  const optionGroups = clusterData.map(c => {
    const galaxies = (c.galaxies || []).map(g =>
      `<option value="${g.id}">${escStr(g.name)}</option>`
    ).join('');
    return `<optgroup label="${escStr(c.name)}">${galaxies}</optgroup>`;
  }).join('');
  select.innerHTML = optionGroups;
  if (currentGalaxyId) select.value = String(currentGalaxyId);
}

function navigateToClusterMap() {
  navigateToGalaxy();
}

function navigateToGalaxy() {
  currentSystemId = null;
  _selectedSystemName = '';
  _mapSidebarPicker = '';
  if (getMapDepth() === 3) {
    // Flat map: the "galaxy" view is the flat system table.
    if (_currentSystems.length) { showMapLevel('galaxy'); renderGalaxyTable(); return; }
    const region = (regionSummaryData || [])[0];
    if (region) { loadFlatmapGalaxy(region.id); return; }
  }
  currentRegionId = null;
  _selectedRegionName = '';
  _galaxyZoomStage = 0;
  _galaxyZoomFocus = { x: 50, y: 50 };
  _galaxyZoomRegionId = null;
  showMapLevel('galaxy');
  renderRegionGrid(regionSummaryData);
}

// ── flat coordinate table view (map_depth=3) ───────────────────────
// The galaxy view is a system picker + a table of that system's positions,
// rather than the AE starfield. Systems live in the galaxy's single (hidden)
// region; we fetch them once and page client-side.
let _flatmapSysIdx = 0;

async function loadFlatmapGalaxy(regionId) {
  try {
    const res = await apiFetch(`/api/regions/${regionId}`);
    if (!res) return;
    const data = await res.json();
    _currentSystems = (data.systems || []).slice()
      .sort((a, b) => (parseInt(a.name, 10) || 0) - (parseInt(b.name, 10) || 0));
    if (_flatmapSysIdx >= _currentSystems.length) _flatmapSysIdx = 0;
    showMapLevel('galaxy');
    renderGalaxyTable();
  } catch (e) { console.error(e); }
}

function flatmapStepSystem(delta) {
  if (!_currentSystems.length) return;
  _flatmapSysIdx = (_flatmapSysIdx + delta + _currentSystems.length) % _currentSystems.length;
  renderGalaxyTable();
}

function flatmapGotoSystem(n) {
  const idx = _currentSystems.findIndex(s => (parseInt(s.name, 10) || 0) === parseInt(n, 10));
  if (idx >= 0) { _flatmapSysIdx = idx; renderGalaxyTable(); }
}

function renderGalaxyTable() {
  const container = document.getElementById('region-grid');
  if (!container) return;
  const sys = _currentSystems[_flatmapSysIdx];
  if (!sys) { container.innerHTML = '<div class="text-dim" style="padding:12px;">No systems in this galaxy</div>'; return; }
  const sysNum = parseInt(sys.name, 10) || (_flatmapSysIdx + 1);
  currentSystemId = sys.id;
  _selectedSystemName = `${currentGalaxyName}:${sysNum}`;

  const positions = [...(sys.planets || [])]
    .sort((a, b) => ((a.orbit * 10 + (a.orbit_row || 0)) - (b.orbit * 10 + (b.orbit_row || 0))));
  let rows = '';
  positions.forEach((p) => {
    const posCoord = p.orbit * 10 + (p.orbit_row || 0);
    const coord = `${currentGalaxyName}:${sysNum}:${posCoord}`;
    let owner;
    if (p.fog) owner = '<span class="map-system-empty-label">- unexplored -</span>';
    else if (p.is_colonized) owner = `<span class="${p.is_mine ? 'map-system-owner-mine' : 'map-system-owner-other'}">${escStr(p.owner || '')}</span>`;
    else owner = '<span class="map-system-empty-label">- empty -</span>';
    const onclick = (p.is_colonized && p.base_id) ? `openBaseDetail(${p.base_id})` : `openPlanetDetail(${p.id})`;
    const sprite = `/static/astros/${p.fog ? 'rocky' : p.type}.jpg`;
    rows += `<tr class="flatmap-row${p.is_mine ? ' mine' : ''}${p.is_colonized && !p.is_mine ? ' enemy' : ''}" onclick="${onclick}">
      <td class="flatmap-pos">${posCoord}</td>
      <td class="flatmap-astro"><img src="${sprite}" width="22" height="22" onerror="this.style.visibility='hidden'"> ${escStr(astroName(p.type) || '')}</td>
      <td class="flatmap-owner">${owner}</td>
      <td class="flatmap-coord">${coordLink(coord)}</td>
    </tr>`;
  });

  const galOptions = (galaxyData || [])
    .slice().sort((a, b) => (a.galaxy_index || 0) - (b.galaxy_index || 0))
    .map(g => `<option value="${g.id}"${g.id === currentGalaxyId ? ' selected' : ''}>${escStr(g.name)}</option>`).join('');

  container.innerHTML = `
    <div class="flatmap-galaxy-view">
      <div class="flatmap-nav">
        <label class="flatmap-nav-item">Galaxy
          <select onchange="selectGalaxy(parseInt(this.value,10))">${galOptions}</select>
        </label>
        <label class="flatmap-nav-item">System
          <button class="flatmap-step" onclick="flatmapStepSystem(-1)">&lsaquo;</button>
          <input type="number" value="${sysNum}" min="1" class="flatmap-sys-input"
                 onkeydown="if(event.key==='Enter')flatmapGotoSystem(this.value)">
          <button class="flatmap-step" onclick="flatmapStepSystem(1)">&rsaquo;</button>
        </label>
        <span class="flatmap-loc">${escStr(currentGalaxyName)}:${sysNum}</span>
      </div>
      <table class="flatmap-galaxy-table">
        <thead><tr><th>Pos</th><th>Astro</th><th>Owner</th><th>Coords</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="4" class="text-dim" style="padding:10px;">empty system</td></tr>'}</tbody>
      </table>
    </div>`;
  updateBreadcrumb();
}

function navigateToRegion() {
  currentSystemId = null;
  _selectedSystemName = '';
  _mapSidebarPicker = '';
  showMapLevel('region');
}

// ── Scroll-to-zoom: mouse wheel drills in/out of map levels ──
(function initMapScrollZoom() {
  document.addEventListener('DOMContentLoaded', () => {
    loadMapSidebarPosition();
    initMapSidebarDrag();
    const mapView = document.getElementById('map-view');
    if (!mapView) return;
    mapView.addEventListener('wheel', (e) => {
      if (!document.getElementById('tab-galaxy')?.classList.contains('active')) return;
      e.preventDefault();
      const depth = getMapDepth();
      if (e.deltaY < 0) {
        // Scroll UP = zoom IN
        if (_mapLevel === 'galaxy') {
          const cell = e.target.closest('.region-cell');
          const eventFocus = getGalaxyZoomFocusFromEvent(e);
          const fx = cell ? parseFloat(cell.dataset.mapX) : eventFocus?.x ?? null;
          const fy = cell ? parseFloat(cell.dataset.mapY) : eventFocus?.y ?? null;
          const regionId = cell ? parseInt(cell.dataset.regionId, 10) : null;
          if (_galaxyZoomStage < 3) {
            setGalaxyZoomStage(_galaxyZoomStage + 1, regionId, fx, fy);
          } else if (cell && cell.onclick) {
            cell.onclick();
          }
        } else if (_mapLevel === 'region' && depth >= 4) {
          const card = e.target.closest('.starfield-system');
          const eventFocus = getRegionZoomFocusFromEvent(e);
          const fx = card ? parseFloat(card.dataset.mapX) : eventFocus?.x ?? null;
          const fy = card ? parseFloat(card.dataset.mapY) : eventFocus?.y ?? null;
          if (_regionZoomStage < 3) {
            setRegionZoomStage(_regionZoomStage + 1, fx, fy);
          }
        }
      } else {
        // Scroll DOWN = zoom OUT
        if (_mapLevel === 'system') {
          depth >= 4 ? navigateToRegion() : navigateToGalaxy();
        } else if (_mapLevel === 'galaxy') {
          if (_galaxyZoomStage > 0) setGalaxyZoomStage(_galaxyZoomStage - 1);
        } else if (_mapLevel === 'region') {
          if (_regionZoomStage > 0) setRegionZoomStage(_regionZoomStage - 1);
          else navigateToGalaxy();
        }
      }
    }, { passive: false });
  });
})();

async function loadGalaxy() {
  // If already loaded, just re-show the current view (don't re-fetch)
  if (clusterData.length > 0 && currentGalaxyId) return;

  const sidebar = document.getElementById('map-sidebar');
  try {
    const cRes = await apiFetch('/api/clusters');
    if (cRes && cRes.ok) {
      clusterData = await cRes.json();
    } else {
      console.warn('loadGalaxy: clusters fetch failed', cRes?.status);
    }
    const gRes = await apiFetch('/api/galaxies');
    if (gRes && gRes.ok) {
      galaxyData = await gRes.json();
    } else {
      console.warn('loadGalaxy: galaxies fetch failed', gRes?.status);
    }
    if (clusterData.length > 0) {
      renderGalaxySidebar();
      // Restore last galaxy from localStorage, or fall back to first
      const saved = parseInt(localStorage.getItem('awe_last_galaxy'));
      const validSaved = saved && galaxyData.some(g => g.id === saved);
      const startId = validSaved ? saved : clusterData[0]?.galaxies?.[0]?.id;
      if (startId) selectGalaxy(startId);
    } else if (sidebar) {
      sidebar.innerHTML = '<div class="empty-state" style="padding:12px;font-size:11px;"><p>No galaxies yet</p></div>';
    }
  } catch (e) {
    console.error('loadGalaxy error:', e);
    if (sidebar) sidebar.innerHTML = '<div class="empty-state" style="padding:12px;"><p>Error loading map.</p></div>';
  }
}

function renderGalaxySidebar() {
  const sidebar = document.getElementById('map-sidebar');
  if (!sidebar) {
    syncMapGalaxySelect();
    return;
  }
  const regionNum = getSelectedRegionNumber() || '--';
  const galaxyLabel = currentGalaxyName ? `Galaxy ${currentGalaxyName}` : 'Galaxy';
  const regionLabel = currentRegionId ? `Region ${regionNum}` : 'Region';
  const pickerHtml = renderMapSidebarPicker();
  const basesOpen = _mapSidebarSection === 'bases';
  const portalsOpen = _mapSidebarSection === 'portals';
  const guildsOpen = _mapSidebarSection === 'guilds';

  const html = `<div class="map-side-box">
    <div class="map-side-header" onpointerdown="beginMapSidebarDrag(event)">Current Location</div>
    <div class="map-side-body">
      <div class="map-side-tabs">
        <button id="map-nav-galaxy" class="map-side-tab${_mapSidebarPicker === 'galaxy' ? ' picker-open' : ''}" onclick="toggleMapSidebarPicker('galaxy');return false;">${escStr(galaxyLabel)}</button>
        ${getMapDepth() >= 4 ? `<button id="map-nav-region" class="map-side-tab${currentGalaxyId ? '' : ' disabled'}${_mapSidebarPicker === 'region' ? ' picker-open' : ''}" onclick="toggleMapSidebarPicker('region');return false;">${escStr(regionLabel)}</button>` : ''}
      </div>
      ${pickerHtml}
      <div class="map-side-coord-jump map-side-coord-row">
        <input
          type="text"
          id="map-coord-input"
          value="${escStr(getMapLocationInputValue())}"
          autocomplete="off"
          onkeydown="if(event.key==='Enter'){submitMapSidebarLocation();}"
        />
        <button class="map-side-go" onclick="submitMapSidebarLocation();return false;" title="Go to location">&larr;</button>
      </div>
      <div class="map-side-section-row${basesOpen ? ' open' : ''}">
        <button class="map-side-section-link" onclick="toggleMapSidebarSection('bases');return false;"><span>Bases</span><span id="map-base-count" class="map-side-count">0</span></button>
        <button class="map-side-section-switch${basesOpen ? ' open' : ''}" onclick="toggleMapSidebarSection('bases');return false;" aria-label="Toggle Bases"></button>
      </div>
      <div class="map-side-section-body${basesOpen ? ' open' : ''}">
        <div class="jump-to-base-bar map-side-list" id="jump-to-base-menu"></div>
      </div>
      <div class="map-side-section-row${portalsOpen ? ' open' : ''}">
        <button class="map-side-section-link" onclick="toggleMapSidebarSection('portals');return false;"><span>Top Portals</span><span class="map-side-count">0</span></button>
        <button class="map-side-section-switch${portalsOpen ? ' open' : ''}" onclick="toggleMapSidebarSection('portals');return false;" aria-label="Toggle Top Portals"></button>
      </div>
      <div class="map-side-section-body${portalsOpen ? ' open' : ''}">
        <div class="text-dim" style="font-size:10px;padding:2px 0 0;">Map portal intel is not wired yet.</div>
      </div>
      <div class="map-side-section-row${guildsOpen ? ' open' : ''}">
        <button class="map-side-section-link" onclick="toggleMapSidebarSection('guilds');return false;"><span>Guilds</span><span class="map-side-count">0</span></button>
        <button class="map-side-section-switch${guildsOpen ? ' open' : ''}" onclick="toggleMapSidebarSection('guilds');return false;" aria-label="Toggle Guilds"></button>
      </div>
      <div class="map-side-section-body${guildsOpen ? ' open' : ''}">
        <div class="text-dim" style="font-size:10px;padding:2px 0 0;">Guild highlights still need report-driven data.</div>
      </div>
    </div>
  </div>`;
  sidebar.innerHTML = html;
  updateMapSubnav();
  applyMapSidebarPosition();
  if (typeof renderMyBasesJumpMenu === 'function') {
    Promise.resolve(renderMyBasesJumpMenu()).finally(syncMapSidebarCounts);
  } else {
    syncMapSidebarCounts();
  }
}

function syncMapSidebarCounts() {
  const countEl = document.getElementById('map-base-count');
  const menu = document.getElementById('jump-to-base-menu');
  if (!countEl || !menu) return;
  countEl.textContent = String(menu.querySelectorAll('button, a').length);
}

async function selectGalaxy(galaxyId) {
  currentGalaxyId = galaxyId;
  const gal = galaxyData.find(g => g.id === galaxyId);
  currentGalaxyName = gal ? gal.name : '';
  currentClusterId = gal ? gal.cluster_id : null;
  currentRegionId = null;
  currentSystemId = null;
  _selectedRegionName = '';
  _selectedSystemName = '';
  _mapSidebarPicker = '';
  _galaxyZoomStage = 0;
  _galaxyZoomFocus = { x: 50, y: 50 };
  _galaxyZoomRegionId = null;
  localStorage.setItem('awe_last_galaxy', galaxyId);
  const select = document.getElementById('map-galaxy-select');
  if (select) select.value = String(galaxyId);
  showMapLevel('galaxy');
  // For map_depth=3, loadGalaxyRegions -> renderRegionGrid intercepts and renders
  // the flat coordinate table instead of the region grid.
  await loadGalaxyRegions(galaxyId);
}

// Get the current galaxy id (useful for other modules like reports)
function getSelectedGalaxyId() { return currentGalaxyId; }
function getSelectedGalaxyName() { return currentGalaxyName; }

async function loadGalaxyRegions(galaxyId) {
  try {
    const res = await apiFetch(`/api/galaxies/${galaxyId}/regions`);
    if (!res) return;
    regionSummaryData = await res.json();
    renderRegionGrid(regionSummaryData);
  } catch (e) { console.error(e); }
}

function renderRegionGrid(regions) {
  // map_depth=3: the galaxy view is the flat coordinate table, not a region
  // grid. Intercept here so EVERY galaxy-level render produces the table.
  if (getMapDepth() === 3) {
    const r = (regions || regionSummaryData || [])[0];
    if (r) loadFlatmapGalaxy(r.id);
    return;
  }
  const starColors = { yellow: '#ffffcd', red: '#ffc1c1', blue: '#bacbff', white: '#fcfcfc', orange: '#fcdcc6', 'white-dwarf': '#ffffff', 'red-giant': '#f1b6af', 'blue-giant': '#acbaf5', 'super-giant': '#eec2b6', neutron: '#afd0de' };
  const maxX = Math.max(...regions.map(r => r.grid_x)) + 1;
  const maxY = Math.max(...regions.map(r => r.grid_y)) + 1;
  const grid = Array.from({ length: maxY }, () => Array(maxX).fill(null));
  regions.forEach(r => { grid[r.grid_y][r.grid_x] = r; });

  const container = document.getElementById('region-grid');
  const rect = container.getBoundingClientRect();
  const availH = window.innerHeight - rect.top - 8;
  const availW = container.parentElement?.clientWidth || window.innerWidth - 40;
  const baseGridPx = Math.min(availH, availW);
  const gridPx = baseGridPx > 480 ? Math.round(baseGridPx * 0.88) : baseGridPx;
  const galaxyZoomFactor = [1, 1.7, 3.0, 5.0][_galaxyZoomStage] || 1;
  const focusXPx = (_galaxyZoomFocus.x / 100) * gridPx * galaxyZoomFactor;
  const focusYPx = (_galaxyZoomFocus.y / 100) * gridPx * galaxyZoomFactor;
  const translateXPx = (gridPx / 2) - focusXPx;
  const translateYPx = (gridPx / 2) - focusYPx;
  const regionsById = new Map(regions.map(r => [r.id, r]));

  function getSystemMiniPosition(regionId, systemName) {
    const pos = parseInt(systemName, 10);
    if (!Number.isFinite(pos)) return null;
    const subCol = pos % 10;
    const subRow = Math.floor(pos / 10);
    const rng = _mulberry32((regionId * 100 + pos) * 7919);
    return {
      x: (subCol + 0.5 + (rng() - 0.5) * 0.3) * 10,
      y: (subRow + 0.5 + (rng() - 0.5) * 0.3) * 10,
    };
  }

  let html = `<div class="region-grid-viewport" style="width:${gridPx}px;height:${gridPx}px;overflow:hidden;position:relative;margin:0 auto;">
    <div class="region-grid region-grid-zoom" style="width:${gridPx}px;height:${gridPx}px;grid-template-columns:repeat(${maxX},1fr);grid-template-rows:repeat(${maxY},1fr);transform-origin:top left;transform:translate(${translateXPx.toFixed(2)}px,${translateYPx.toFixed(2)}px) scale(${galaxyZoomFactor});">`;
  let densityHtml = '';
  for (let y = 0; y < maxY; y++) {
    for (let x = 0; x < maxX; x++) {
      const r = grid[y][x];
      if (r) {
        const active = r.id === currentRegionId || r.id === _galaxyZoomRegionId ? ' active' : '';
        const vis = r.visibility || 'live';
        const fogClass = vis === 'fog' ? ' fog' : (vis === 'snapshot' ? ' snapshot' : '');
        const fullName = `${currentGalaxyName}:${r.name}`;
        const mapX = ((x + 0.5) / maxX) * 100;
        const mapY = ((y + 0.5) / maxY) * 100;

        const isVoid = (r.systems === 0 && vis !== 'fog');
        if (isVoid) {
          html += `<div class="region-cell void" data-region-id="${r.id}" data-map-x="${mapX.toFixed(2)}" data-map-y="${mapY.toFixed(2)}">
            <div class="rg-name void-name">Region: ${escStr(fullName)}</div></div>`;
        } else {
          const starInfo = r.star_info || [];
          let miniStars = '';
          for (const [sName, sType] of starInfo) {
            const spriteType = sType || 'yellow';
            const spriteSrc = `/static/stars/starxs_${spriteType}.png`;
            const pos = parseInt(sName, 10) || 0;
            const subCol = pos % 10;
            const subRow = Math.floor(pos / 10);
            const rng = _mulberry32((r.id * 100 + pos) * 7919);
            const sx = (subCol + 0.5 + (rng() - 0.5) * 0.3) * 10;
            const sy = (subRow + 0.5 + (rng() - 0.5) * 0.3) * 10;
            miniStars += `<div class="rg-mini-star" style="left:${sx.toFixed(1)}%;top:${sy.toFixed(1)}%;background-image:url('${spriteSrc}');"></div>`;
            const densityX = ((x + (sx / 100)) / maxX) * 100;
            const densityY = ((y + (sy / 100)) / maxY) * 100;
            const densitySize = /giant/i.test(spriteType) ? 28 : (spriteType === 'neutron' ? 20 : 24);
            densityHtml += `<div class="map-galaxy-density" style="left:${densityX.toFixed(2)}%;top:${densityY.toFixed(2)}%;width:${densitySize}px;height:${densitySize}px;margin-left:${(-densitySize / 2).toFixed(1)}px;margin-top:${(-densitySize / 2).toFixed(1)}px;"></div>`;
          }

          html += `<div class="region-cell${active}${fogClass}" data-region-id="${r.id}" data-map-x="${mapX.toFixed(2)}" data-map-y="${mapY.toFixed(2)}" onclick="selectRegion(${r.id},'${escStr(fullName)}')">
            <div class="rg-name">Region: ${escStr(fullName)} (${fmtNum(r.systems || 0)} systems)</div>
            <div class="rg-mini-starfield">${miniStars}</div></div>`;
        }
      } else {
        html += `<div class="region-cell empty"></div>`;
      }
    }
  }
  html += '</div>';
  html += `<div class="map-galaxy-density-layer" style="width:${gridPx}px;height:${gridPx}px;transform-origin:top left;transform:translate(${translateXPx.toFixed(2)}px,${translateYPx.toFixed(2)}px) scale(${galaxyZoomFactor});">${densityHtml}</div>`;

  const highlightKeys = new Set();
  let highlightHtml = '';
  for (const base of (_mapSidebarHighlights.bases || [])) {
    if (!base || base.galaxy_id !== currentGalaxyId) continue;
    const region = regionsById.get(base.region_id);
    if (!region) continue;
    const localPos = getSystemMiniPosition(base.region_id, base.system_name);
    if (!localPos) continue;
    const key = `base:${base.region_id}:${base.system_name}`;
    if (highlightKeys.has(key)) continue;
    highlightKeys.add(key);
    const xPct = ((region.grid_x + (localPos.x / 100)) / maxX) * 100;
    const yPct = ((region.grid_y + (localPos.y / 100)) / maxY) * 100;
    const fullCoord = `${currentGalaxyName}:${base.region_name}:${base.system_name}`;
    const title = `${base.base_name || 'Base'} (${fullCoord})`;
    highlightHtml += `<button class="map-galaxy-highlight map-galaxy-highlight-base" style="left:${xPct.toFixed(2)}%;top:${yPct.toFixed(2)}%;" title="${escAttr(title)}" onclick="jumpToMyBaseByCoord(${base.region_id}, '${escAttr(base.region_name)}', ${base.system_id}, '${escAttr(fullCoord)}');return false;"></button>`;
  }

  html += `<div class="map-galaxy-highlight-layer" style="width:${gridPx}px;height:${gridPx}px;transform-origin:top left;transform:translate(${translateXPx.toFixed(2)}px,${translateYPx.toFixed(2)}px) scale(${galaxyZoomFactor});">${highlightHtml}</div></div>`;
  document.getElementById('region-grid').innerHTML = html;
}

async function jumpToMyBaseByCoord(regionId, regionName, systemId, systemCoord) {
  if (!currentGalaxyId) return;
  await selectRegion(regionId, `${currentGalaxyName}:${regionName}`);
  const sys = _currentSystems.find(s => s.id === systemId);
  if (sys) {
    selectSystem(systemId, systemCoord);
  }
}

function timeSince(isoStr) {
  const diff = (Date.now() - serverDate(isoStr).getTime()) / 1000;
  if (diff < 60) return `${Math.round(diff)}s`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
  return `${Math.floor(diff / 86400)}d`;
}

async function selectRegion(regionId, regionName) {
  currentRegionId = regionId;
  currentSystemId = null;
  _selectedRegionName = regionName || `${currentGalaxyName}:${String(regionId).padStart(2, '0')}`;
  _selectedSystemName = '';
  _mapSidebarPicker = '';
  _regionZoomStage = 0;
  _regionZoomFocus = { x: 50, y: 50 };
  showMapLevel('region');
  try {
    const res = await apiFetch(`/api/regions/${regionId}`);
    if (!res) return;
    const data = await res.json();
    _currentSystems = data.systems || [];
    const isFog = data.visibility === 'fog';
    const isSnap = data.visibility === 'snapshot';
    renderSystemList(data.systems || [], isSnap, isFog);
  } catch (e) { console.error(e); }
}

// Mulberry32 seeded PRNG
function _mulberry32(seed) {
  let s = seed | 0;
  return function() {
    s = (s + 0x6D2B79F5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function renderSystemList(systems, isSnapshot, isFog) {
  _currentRegionRender = { systems, isSnapshot, isFog };
  if (!systems.length) {
    document.getElementById('system-list').innerHTML = '<div class="text-dim" style="padding:12px;">No systems in this region</div>';
    return;
  }
  const flat = getMapDepth() === 3;
  const selRegion = regionSummaryData.find(r => r.id === currentRegionId);
  // Flat (map_depth=3) coords skip the hidden synthetic region: galaxy:system.
  const regionPrefix = flat ? `${currentGalaxyName}:`
    : (selRegion ? `${currentGalaxyName}:${selRegion.name}:` : '');
  let html = '';
  if (isFog) {
    html += '<div class="fog-notice"><span class="fog-badge">Unexplored</span> Astro types hidden. Send a fleet to scout for detailed intel.</div>';
  } else if (isSnapshot) {
    html += '<div class="snapshot-notice"><span class="snapshot-badge">Snapshot</span> This data may be outdated. Send a fleet to get fresh intel.</div>';
  }
  const starColors = { yellow: '#ffffcd', red: '#ffc1c1', blue: '#bacbff', white: '#fcfcfc', orange: '#fcdcc6', 'white-dwarf': '#ffffff', 'red-giant': '#f1b6af', 'blue-giant': '#acbaf5', 'super-giant': '#eec2b6', neutron: '#afd0de' };
  const starGlowColors = { yellow: 'rgba(255,255,205,0.3)', red: 'rgba(255,193,193,0.3)', blue: 'rgba(186,203,255,0.3)', white: 'rgba(252,252,252,0.25)', orange: 'rgba(252,220,198,0.3)', 'white-dwarf': 'rgba(255,255,255,0.25)', 'red-giant': 'rgba(241,182,175,0.35)', 'blue-giant': 'rgba(172,186,245,0.35)', 'super-giant': 'rgba(238,194,182,0.35)', neutron: 'rgba(175,208,222,0.3)' };

  // Flat galaxies hold many systems numbered 1..N — lay them on an adaptive
  // near-square grid by list index. The 4-level path keeps the 10x10 region grid.
  const cols = flat ? Math.max(1, Math.ceil(Math.sqrt(systems.length))) : 10;
  const rows = flat ? Math.max(1, Math.ceil(systems.length / cols)) : 10;
  const cellW = 100 / cols;
  const cellH = 100 / rows;
  const zoomFactor = [1, 1.7, 3.0, 5.0][_regionZoomStage] || 1;

  const bgRng = _mulberry32(currentRegionId || 42);
  let bgStars = '';
  for (let i = 0; i < 120; i++) {
    const bx = bgRng() * 100;
    const by = bgRng() * 100;
    const bSize = 0.5 + bgRng() * 1.5;
    const bOpacity = 0.08 + bgRng() * 0.2;
    bgStars += `<div class="starfield-bg-star" style="left:${bx}%;top:${by}%;width:${bSize}px;height:${bSize}px;opacity:${bOpacity};"></div>`;
  }

  const slContainer = document.getElementById('system-list');
  const slRect = slContainer.getBoundingClientRect();
  const slAvailH = window.innerHeight - slRect.top - 8;
  const slAvailW = slContainer.parentElement?.clientWidth || window.innerWidth - 40;
  const sfPx = Math.max(420, Math.round(Math.min(slAvailH, slAvailW) * 0.82));

  html += `<div class="starfield-map starfield-map-region" style="width:${sfPx}px;height:${sfPx}px;">${bgStars}`;

  systems.forEach((s, idx) => {
    const glowCol = starGlowColors[s.star_type] || 'rgba(170,170,170,0.3)';
    const shortCoord = `${s.name}`;
    const mediumCoord = flat ? `${currentGalaxyName}:${s.name}`
      : (selRegion ? `${selRegion.name}:${s.name}` : shortCoord);
    const fullCoord = `${regionPrefix}${s.name}`;
    const sysCoord = flat ? mediumCoord
      : (_regionZoomStage >= 3 ? fullCoord : (_regionZoomStage >= 1 ? mediumCoord : shortCoord));

    const pos = flat ? idx : (parseInt(s.name, 10) || 0);
    const rng = _mulberry32(s.id * 7919 + 1301);
    const gridCol = pos % cols;
    const gridRow = Math.floor(pos / cols);
    const jitter = 0.2;
    const xPct = (gridCol + 0.5 + (rng() - 0.5) * jitter * 2) * cellW;
    const yPct = (gridRow + 0.5 + (rng() - 0.5) * jitter * 2) * cellH;
    const displayX = 50 + (xPct - _regionZoomFocus.x) * zoomFactor;
    const displayY = 50 + (yPct - _regionZoomFocus.y) * zoomFactor;

    const starType = s.star_type || 'yellow';
    const spriteSrc = `/static/stars/star_${starType}.png`;
    const starSize = [16, 19, 24, 30][_regionZoomStage] || 18;
    const glowSize = starSize * 2.1;

    const hasMyBase = s.planets.some(p => p.is_mine);
    const hasEnemy = s.planets.some(p => p.is_colonized && !p.is_mine);
    let ringClass = '';
    if (hasMyBase) ringClass = ' star-mine';
    else if (hasEnemy) ringClass = ' star-enemy';

    html += `<div class="starfield-system${ringClass}" data-map-x="${xPct.toFixed(2)}" data-map-y="${yPct.toFixed(2)}" style="left:${displayX.toFixed(2)}%;top:${displayY.toFixed(2)}%;" onclick="selectSystem(${s.id},'${escStr(fullCoord)}')">
      <div class="starfield-glow" style="width:${glowSize}px;height:${glowSize}px;background:radial-gradient(circle, ${glowCol} 0%, transparent 70%);"></div>
      <img class="starfield-star-img" src="${spriteSrc}" alt="${escStr(starType)}" width="${starSize}" height="${starSize}">
      <div class="starfield-label">${escStr(sysCoord)}</div>
    </div>`;
  });

  html += '</div>';
  document.getElementById('system-list').innerHTML = html;
}

function selectSystem(systemId, systemName) {
  currentSystemId = systemId;
  _selectedSystemName = systemName || `System ${systemId}`;
  _mapSidebarPicker = '';
  showMapLevel('system');
  const system = _currentSystems.find(s => s.id === systemId);
  if (system) renderPlanetDetail(system.planets);
}

// ── Planet type colors ──
const typeColors = {
  arid:'#d4a040', asteroid:'#999', craters:'#a08050', crystalline:'#c8a0ff',
  earthly:'#44cc66', gaia:'#22ee88', glacial:'#88ccff', magma:'#ff4422',
  metallic:'#aab', oceanic:'#44aadd', radioactive:'#88ff44', rocky:'#c0a060',
  toxic:'#aacc00', tundra:'#aaddee', volcanic:'#ff6622', gas_giant:'#cc8844', asteroid_belt:'#888',
  planet:'#556', moon:'#445', asteroid_fog:'#444',
};

function renderPlanetDetail(planets) {
  if (!planets.length) {
    document.getElementById('planet-detail').innerHTML = '<div class="text-dim" style="padding:12px;">No astros in this system</div>';
    return;
  }

  const system = _currentSystems.find(s => s.id === currentSystemId);
  const starType = system ? system.star_type : 'yellow';
  const orbitX = { 1: 0, 2: 130, 3: 260, 4: 390, 5: 520 };
  const rowY = { 0: 0, 1: 120, 2: 200, 3: 260 };
  const fogSpriteFor = (planet) => {
    const type = String(planet?.type || '').toLowerCase();
    if (type === 'gas_giant') return '/static/astros/gas_giant.jpg';
    if (type === 'asteroid_belt') return '/static/astros/asteroid_belt.jpg';
    if (type === 'asteroid') return '/static/astros/asteroid.jpg';
    const category = String(planet?.category || '').toLowerCase();
    if (category === 'moon') return '/static/astros/craters.jpg';
    return '/static/astros/rocky.jpg';
  };
  const astroHtml = [...planets]
    .sort((a, b) => (a.orbit - b.orbit) || ((a.orbit_row || 0) - (b.orbit_row || 0)))
    .map((p) => {
      const orbit = Math.max(1, Math.min(5, p.orbit || 1));
      const row = Math.max(0, Math.min(3, p.orbit_row || 0));
      const left = orbitX[orbit] || 0;
      const top = rowY[row] || 0;
      const fogType = String(p.type || '').toLowerCase();
      const sizeClass = (fogType === 'gas_giant' || fogType === 'asteroid_belt')
        ? 'small'
        : (p.category === 'Asteroid' ? 'micro' : (p.category === 'Moon' ? 'micro' : 'small'));
      const action = p.is_colonized && p.base_id ? `openBaseDetail(${p.base_id})` : `openPlanetDetail(${p.id})`;
      const spriteSrc = p.fog ? fogSpriteFor(p) : `/static/astros/${p.type}.jpg`;
      const ownerText = p.fog
        ? '<span class="map-system-empty-label">- unexplored -</span>'
        : (p.is_colonized
          ? `<span class="${p.is_mine ? 'map-system-owner-mine' : 'map-system-owner-other'}">${escStr(p.owner)}</span>`
          : '<span class="map-system-empty-label">- empty -</span>');
      return `<div class="map-system-astro map-system-astro-${sizeClass}" style="top:${top}px;left:${left}px;">
        <div class="map-system-astro-visual${p.debris > 0 ? ' has-debris' : ''}${p.fog ? ' fogged' : ''}" onclick="${action}">
          <img src="${spriteSrc}" alt="${escStr(p.fog ? `${p.category || 'Unexplored'} (${p.name})` : p.name)}" class="map-system-astro-img${p.fog ? ' fogged' : ''}" />
        </div>
        <div class="map-system-astro-desc">${ownerText}</div>
      </div>`;
    }).join('');

  let html = `<div class="map-system-page">
    <div class="map-system-wrap">
      <div class="map-system-box map-system-${escStr(starType)}">
        <div class="map-system-canvas">${astroHtml}</div>
      </div>
    </div>
  </div>`;
  document.getElementById('planet-detail').innerHTML = html;
}

function renderAstroCard(p) {
  if (p.fog) {
    const catKey = p.category === 'Moon' ? 'moon' : (p.category === 'Asteroid' ? 'asteroid_fog' : 'planet');
    const col = typeColors[catKey] || '#555';
    const label = p.category === 'Asteroid' ? 'Ast' : (p.category === 'Moon' ? 'Moo' : 'Pla');
    const fogSize = p.category === 'Asteroid' ? 'astro-xs' : (p.category === 'Moon' ? 'astro-sm' : 'astro-lg');
    const fogSzPx = p.category === 'Asteroid' ? 14 : (p.category === 'Moon' ? 22 : 40);
    return `<div class="astro-orb ${fogSize} astro-fog" style="width:${fogSzPx}px;height:${fogSzPx}px;background:${col};border-color:var(--border);" title="${p.category} (unexplored)">
      <span class="astro-orb-label" style="color:#888;">${label}</span>
    </div>`;
  }
  const orbSz = p.category === 'Asteroid' ? 14 : (p.category === 'Moon' ? 22 : 40);
  const sizeClass = p.category === 'Asteroid' ? 'astro-xs' : (p.category === 'Moon' ? 'astro-sm' : 'astro-lg');
  let borderCol = 'var(--border)';
  if (p.is_colonized && p.is_mine) borderCol = '#22cc66';
  else if (p.is_colonized) borderCol = '#cc4444';
  else if (p.has_wormhole) borderCol = 'var(--accent)';
  const spriteUrl = `/static/astros/${p.type}.jpg`;
  const detailClick = p.is_colonized && p.base_id
    ? `openBaseDetail(${p.base_id})`
    : `openPlanetDetail(${p.id})`;
  // Fleet presence dots
  let dotsHtml = '';
  if (p.fleet_dots && p.fleet_dots.length) {
    const dotColors = {mine: '#fff', guild: '#4c4', other: '#cc4'};
    const dots = p.fleet_dots.map(d => {
      const sz = d.size >= 5 ? 10 : (d.size >= 2 ? 8 : 6);
      return `<span style="display:inline-block;width:${sz}px;height:${sz}px;border-radius:50%;background:${dotColors[d.cat] || '#cc4'};margin:1px;box-shadow:0 0 2px #000,0 0 4px ${dotColors[d.cat] || '#cc4'};border:1px solid rgba(0,0,0,0.5);"></span>`;
    }).join('');
    dotsHtml = `<div style="position:absolute;bottom:-6px;left:50%;transform:translateX(-50%);display:flex;gap:2px;z-index:2;">${dots}</div>`;
  }
  // Debris asterisk
  let debrisHtml = '';
  if (p.debris > 0) {
    debrisHtml = `<span style="position:absolute;top:-4px;right:-2px;color:#fc0;font-weight:bold;font-size:14px;text-shadow:0 0 3px #000;">*</span>`;
  }
  return `<div class="astro-orb ${sizeClass}" style="width:${orbSz}px;height:${orbSz}px;border-color:${borderCol};cursor:pointer;position:relative;" title="${p.name} - ${astroName(p.type)} (${p.owner || 'Uncolonized'})" onclick="${detailClick}">
    <img src="${spriteUrl}" class="astro-orb-img" alt="${astroName(p.type)}" />
    ${dotsHtml}${debrisHtml}
  </div>`;
}

// ============================================================
// COLONIZE
// ============================================================

let _colonizePlanetId = null;
async function openColonizeModal(planetId, planetName) {
  _colonizePlanetId = planetId;
  document.getElementById('colonize-planet-name').textContent = planetName;
  document.getElementById('colonize-info').textContent = '';
  document.getElementById('colonize-info').className = 'alert alert-info mb-12';
  document.getElementById('colonize-info').style.display = 'none';
  try {
    const res = await apiFetch('/api/fleets');
    if (!res) return;
    const fleets = await res.json();
    const sel = document.getElementById('colonize-fleet-sel');
    const eligible = fleets.filter(f =>
      !f.is_moving && f.colonizer_ship && (f.ships?.[f.colonizer_ship] || 0) > 0 &&
      f.location_planet_id === planetId
    );
    if (eligible.length > 0) {
      sel.innerHTML = eligible.map(f => {
        const cnt = f.ships[f.colonizer_ship] || 0;
        return `<option value="${f.id}">${escStr(f.name)} (${cnt} ${escStr(shipName(f.colonizer_ship))})</option>`;
      }).join('');
      document.getElementById('colonize-no-fleet-msg').style.display = 'none';
      document.getElementById('colonize-btn').disabled = false;
    } else {
      sel.innerHTML = '<option disabled>No eligible fleets</option>';
      document.getElementById('colonize-no-fleet-msg').style.display = 'block';
      document.getElementById('colonize-no-fleet-msg').textContent =
        'You need a fleet with a colony ship stationed at this planet. Send one here first.';
      document.getElementById('colonize-btn').disabled = true;
    }
  } catch (e) { console.error(e); }
  openModal('colonize-modal');
}

async function doColonize() {
  if (!_colonizePlanetId) return;
  const fleetId = parseInt(document.getElementById('colonize-fleet-sel').value);
  if (!fleetId) return;
  const infoEl = document.getElementById('colonize-info');
  try {
    const res = await apiFetch('/api/colonize', {
      method: 'POST', body: JSON.stringify({ planet_id: _colonizePlanetId, fleet_id: fleetId })
    });
    const data = await res.json();
    if (data.success) {
      closeModal('colonize-modal');
      showSnack('Colony established!');
      await updateHUD();
      if (currentRegionId) await selectRegion(currentRegionId);
    } else {
      infoEl.textContent = data.detail || 'Failed';
      infoEl.className = 'alert alert-error mb-12';
      infoEl.style.display = 'block';
    }
  } catch (e) { console.error(e); }
}

// ============================================================
// SEND FLEET TO ASTRO
// ============================================================

let _sendToPlanetId = null, _sendToPlanetName = '';
function openSendFleetToAstro(planetId, planetName) {
  _sendToPlanetId = planetId;
  _sendToPlanetName = planetName;
  document.getElementById('send-dest-label').textContent = `Destination: ${planetName}`;
  document.getElementById('send-info').style.display = 'none';
  loadSendFleetOptions();
  openModal('send-fleet-modal');
}

async function loadSendFleetOptions() {
  try {
    const res = await apiFetch('/api/fleets');
    if (!res) return;
    const fleets = await res.json();
    const sel = document.getElementById('send-fleet-sel');
    const available = fleets.filter(f => !f.is_moving && f.total_ships > 0);
    sel.innerHTML = available.map(f => {
  const loc = f.location_name || f.base_name || '—';
      return `<option value="${f.id}">${escStr(f.name)} (${fmtNum(f.total_ships)} ships at ${escStr(loc)})</option>`;
    }).join('');
    if (!sel.innerHTML) sel.innerHTML = '<option disabled>No available fleets</option>';
  } catch (e) {}
}

async function doSendFleet() {
  const fleetId = parseInt(document.getElementById('send-fleet-sel').value);
  if (!fleetId) return;
  closeModal('send-fleet-modal');
  closeModal('base-detail-modal');
  // Pre-fill destination coords and open fleet Move tab
  window._prefillMoveCoords = _sendToPlanetName;
  _openFleetId = fleetId;
  _activeFleetTab = 'move';
  switchTab('fleets');
}

// ============================================================
// BASE / PLANET DETAIL MODAL
// ============================================================

async function openBaseDetail(baseId) {
  document.getElementById('base-detail-content').innerHTML =
    '<div class="text-dim" style="padding:20px;text-align:center;">Loading...</div>';
  openModal('base-detail-modal');
  try {
    const res = await apiFetch(`/api/base-detail/${baseId}`);
    if (!res) return;
    const d = await res.json();
    renderBaseDetail(d);
  } catch (e) {
    document.getElementById('base-detail-content').innerHTML =
      '<div class="text-danger" style="padding:20px;">Failed to load base detail.</div>';
  }
}

async function openPlanetDetail(planetId) {
  document.getElementById('base-detail-content').innerHTML =
    '<div class="text-dim" style="padding:20px;text-align:center;">Loading...</div>';
  openModal('base-detail-modal');
  try {
    const res = await apiFetch(`/api/planet-detail/${planetId}`);
    if (!res) return;
    const d = await res.json();
    if (d.base_id) {
      const res2 = await apiFetch(`/api/base-detail/${d.base_id}`);
      if (res2) {
        const bd = await res2.json();
        renderBaseDetail(bd);
        return;
      }
    }
    renderUncolonizedPlanetDetail(d);
  } catch (e) {
    document.getElementById('base-detail-content').innerHTML =
      '<div class="text-danger" style="padding:20px;">Failed to load planet detail.</div>';
  }
}

function renderDetailLocationPath(location, coords, astroSuffix) {
  const galaxyName = String(location?.galaxy || '');
  const regionName = String(location?.region || '').padStart(2, '0');
  const systemName = String(location?.system || '').padStart(2, '0');
  const safeGalaxy = escAttr(galaxyName);
  const safeRegion = escAttr(regionName);
  const safeCoords = escAttr(coords || '');

  return `<a href="#" class="bd-path-link" onclick="event.preventDefault();openDetailGalaxy('${safeGalaxy}')">Galaxy ${escStr(galaxyName)}</a>
    <span class="bd-path-sep">&gt;</span>
    <a href="#" class="bd-path-link" onclick="event.preventDefault();openDetailRegion('${safeGalaxy}','${safeRegion}')">Region ${escStr(regionName)}</a>
    <span class="bd-path-sep">&gt;</span>
    <a href="#" class="bd-path-link" onclick="event.preventDefault();openDetailSystem('${safeCoords}')">System ${escStr(systemName)}</a>
    <span class="bd-path-sep">&gt;</span>
    <span>Astro ${escStr(astroSuffix)}</span>`;
}

async function openDetailGalaxy(galaxyName) {
  closeModal('base-detail-modal');
  switchTab('galaxy');
  await loadGalaxy();
  const galaxy = (galaxyData || []).find((g) => String(g.name || '') === String(galaxyName || ''));
  if (galaxy) await selectGalaxy(galaxy.id);
}

async function openDetailRegion(galaxyName, regionName) {
  closeModal('base-detail-modal');
  switchTab('galaxy');
  await loadGalaxy();
  const galaxy = (galaxyData || []).find((g) => String(g.name || '') === String(galaxyName || ''));
  if (!galaxy) return;
  await selectGalaxy(galaxy.id);
  const code = String(regionName || '').padStart(2, '0');
  const region = regionSummaryData.find((r) => String(r.name || '').padStart(2, '0') === code);
  if (region) await selectRegion(region.id, `${galaxyName}:${code}`);
}

async function openDetailSystem(coords) {
  closeModal('base-detail-modal');
  await coordToMap(coords);
}

function renderBaseDetail(d) {
  const p = d.planet;
  const ownerShield = shieldIcon(d.owner_level, d.owner_protection_broken);
  const ownerDisplay = d.guild_tag ? `${ownerShield}[${escStr(d.guild_tag)}] ${escStr(d.owner)}` : `${ownerShield}${escStr(d.owner)}`;
  const astroSuffix = p.coords ? p.coords.split(':').pop() : p.orbit;
  const coordPath = renderDetailLocationPath(d.location, p.coords, astroSuffix);

  document.getElementById('base-detail-title').innerHTML = coordPath;

  let html = '<div class="bd-layout">';

  html += `<div class="bd-planet-info">
    <div class="bd-coord-path">${coordPath}&nbsp;&nbsp;(${coordLink(p.coords)})</div>
    <table class="bd-stat-table">
      <tr><td class="bd-stat-label">Astro Type:</td><td>${escStr(p.category)}</td></tr>
      <tr><td class="bd-stat-label">Terrain:</td><td>${astroName(p.type)}</td></tr>
      ${p.temperature != null ? `<tr><td class="bd-stat-label">Temperature:</td><td>${p.temperature}°C</td></tr>` : ''}
      <tr><td class="bd-stat-label">Area:</td><td>${p.area}</td></tr>
      <tr><td class="bd-stat-label">Solar Energy:</td><td>${p.solar}</td></tr>
      <tr><td class="bd-stat-label">Fertility:</td><td>${p.fertility}</td></tr>
    </table>
    <table class="bd-resource-table">
      <tr><th colspan="2">Resources</th></tr>
      <tr><td>Metal</td><td>${p.metal}</td></tr>
      <tr><td>Gas</td><td>${p.gas}</td></tr>
      <tr><td>Crystals</td><td>${p.crystal}</td></tr>
    </table>
  </div>`;

  html += `<div class="bd-planet-image">
    <img src="/static/astros/${p.type}.jpg" alt="${astroName(p.type)}" class="bd-astro-img" />
  </div>`;

  // Wormhole indicator
  if (d.wormhole) {
    html += `<div style="background:var(--bg-dark);border:1px solid var(--accent);border-radius:4px;padding:6px 12px;margin:8px 0;text-align:center;color:var(--accent);font-size:12px;">
      Wormhole (+${d.wormhole.speed_pct}% speed)
    </div>`;
  }

  html += `<div class="bd-base-info">
    <div class="bd-base-name">${escStr(d.base_name)}</div>
    <div class="bd-owner-card">
      <div class="bd-info-label">Base information</div>
      <div class="bd-info-row"><span>Base Owner:</span> <span class="text-accent">${ownerDisplay}</span></div>
      ${d.occupied_by ? `<div class="bd-info-row"><span>Occupied by:</span> <span class="text-danger">${escStr(d.occupied_by)}</span></div>` : ''}
    </div>
  </div>`;

  html += '</div>';

  html += `<table class="bd-summary-bar">
    <tr>
      <th>Base</th><th>Owner</th><th>Occupier</th><th>Economy</th>
    </tr>
    <tr>
      <td>${escStr(d.base_name)}</td>
      <td>${ownerDisplay}</td>
      <td>${d.occupied_by ? escStr(d.occupied_by) : ''}</td>
      <td class="text-warn">${d.economy} / ${d.economy_max}</td>
    </tr>
  </table>`;

  html += `<div class="bd-actions">
    <a href="javascript:void(0)" onclick="closeModal('base-detail-modal');openSendFleetToAstro(${p.id},'${escStr(p.coords)}')" class="bd-action-link">Send Fleet</a>
    &nbsp; <a href="javascript:void(0)" onclick="addBookmark('${escStr(d.base_name)}','${escStr(p.coords)}',${p.id})" class="bd-action-link">&#9733; Bookmark</a>
  </div>`;

  if (d.fleets.length > 0 || d.incoming_fleets.length > 0) {
    html += `<div class="bd-section-title">Fleets</div>
    <table class="bd-fleet-table">
      <tr><th>Fleet</th><th>Player</th><th>Arrival</th><th>Size</th></tr>`;
    for (const f of d.fleets) {
      const pClass = f.is_mine ? 'text-success' : 'text-danger';
      const playerDisplay = f.guild_tag ? `[${escStr(f.guild_tag)}] ${escStr(f.player)}` : escStr(f.player);
      html += `<tr>
        <td>${escStr(f.name)}</td>
        <td class="${pClass}">${playerDisplay}</td>
        <td class="text-dim"></td>
        <td style="text-align:right;">${fmtNum(f.size)}</td>
      </tr>`;
    }
    for (const f of d.incoming_fleets) {
      const pClass = f.is_mine ? 'text-success' : 'text-danger';
      const playerDisplay = f.guild_tag ? `[${escStr(f.guild_tag)}] ${escStr(f.player)}` : escStr(f.player);
      const arrivalStr = f.arrival ? `<span class="countdown" data-end="${f.arrival}">${fmtTime(Math.max(0, (serverDate(f.arrival) - Date.now()) / 1000))}</span>` : '—';
      html += `<tr>
        <td>${escStr(f.name)}</td>
        <td class="${pClass}">${playerDisplay}</td>
        <td>${arrivalStr}</td>
        <td style="text-align:right;">${fmtNum(f.size)}</td>
      </tr>`;
    }
    html += '</table>';
  }

  if (d.structures.length > 0 || d.defenses.length > 0) {
    html += '<div class="bd-struct-defense-wrap">';

    html += `<table class="bd-struct-table">
      <tr><th>Structures</th><th>Level</th></tr>`;
    for (const s of d.structures) {
      const lvClass = s.is_constructing ? 'text-warn' : '';
      html += `<tr><td>${escStr(s.name)}</td><td class="${lvClass}">${s.level}${s.is_constructing ? ' ⚙' : ''}</td></tr>`;
    }
    html += '</table>';

    if (d.defenses.length > 0) {
      html += `<table class="bd-struct-table">
        <tr><th>Defenses</th><th>Units</th></tr>`;
      for (const def of d.defenses) {
        html += `<tr><td>${escStr(def.name)}</td><td>${def.quantity} / ${def.max_quantity}</td></tr>`;
      }
      html += '</table>';
    }

    html += '</div>';
  }

  document.getElementById('base-detail-content').innerHTML = html;
}

function renderUncolonizedPlanetDetail(d) {
  const astroSuffix = d.coords ? d.coords.split(':').pop() : d.orbit;
  const coordPath = renderDetailLocationPath(d.location, d.coords, astroSuffix);
  document.getElementById('base-detail-title').innerHTML = coordPath;
  const isFogged = !!d.fog;
  const detailSprite = isFogged
    ? (() => {
        const type = String(d.type || '').toLowerCase();
        if (type === 'gas_giant') return '/static/astros/gas_giant.jpg';
        if (type === 'asteroid_belt') return '/static/astros/asteroid_belt.jpg';
        if (type === 'asteroid') return '/static/astros/asteroid.jpg';
        if (String(d.category || '').toLowerCase() === 'moon') return '/static/astros/craters.jpg';
        return '/static/astros/rocky.jpg';
      })()
    : `/static/astros/${d.type}.jpg`;
  const terrainText = isFogged && !['gas_giant', 'asteroid', 'asteroid_belt'].includes(String(d.type || '').toLowerCase())
    ? 'Unexplored'
    : astroName(d.type);

  let html = '<div class="bd-layout">';

  html += `<div class="bd-planet-info">
    <div class="bd-coord-path">${coordPath}&nbsp;&nbsp;(${coordLink(d.coords)})</div>
    <table class="bd-stat-table">
      <tr><td class="bd-stat-label">Astro Type:</td><td>${escStr(d.category)}</td></tr>
      <tr><td class="bd-stat-label">Terrain:</td><td>${terrainText}</td></tr>
      ${d.temperature != null ? `<tr><td class="bd-stat-label">Temperature:</td><td>${d.temperature}°C</td></tr>` : ''}
      <tr><td class="bd-stat-label">Area:</td><td>${d.area}</td></tr>
      <tr><td class="bd-stat-label">Solar Energy:</td><td>${d.solar}</td></tr>
      <tr><td class="bd-stat-label">Fertility:</td><td>${d.fertility}</td></tr>
    </table>
    <table class="bd-resource-table">
      <tr><th colspan="2">Resources</th></tr>
      <tr><td>Metal</td><td>${d.metal}</td></tr>
      <tr><td>Gas</td><td>${d.gas}</td></tr>
      <tr><td>Crystals</td><td>${d.crystal}</td></tr>
    </table>
  </div>`;

  html += `<div class="bd-planet-image">
    <img src="${detailSprite}" alt="${terrainText}" class="bd-astro-img${isFogged ? ' fogged' : ''}" />
  </div>`;

  // Wormhole indicator
  if (d.wormhole) {
    html += `<div style="background:var(--bg-dark);border:1px solid var(--accent);border-radius:4px;padding:6px 12px;margin:8px 0;text-align:center;color:var(--accent);font-size:12px;">
      Wormhole (+${d.wormhole.speed_pct}% speed)
    </div>`;
  }

  html += `<div class="bd-base-info">
    <div class="bd-base-name" style="color:var(--text-dim);">${isFogged ? 'Unexplored' : 'Uncolonized'}</div>
    <div class="bd-owner-card">
      <div class="bd-info-label">${isFogged ? 'Send a fleet to scout for detailed intel' : 'No base established'}</div>
    </div>
  </div>`;

  html += '</div>';

  const nonColonizable = new Set(['gas_giant', 'asteroid_belt']);
  html += '<div class="bd-actions">';
  if (!nonColonizable.has(d.type)) {
    html += `<a href="javascript:void(0)" onclick="closeModal('base-detail-modal');openColonizeModal(${d.planet_id},'${escStr(d.name)}')" class="bd-action-link">Colonize</a> &nbsp; `;
    html += `<a href="javascript:void(0)" onclick="closeModal('base-detail-modal');openSendFleetToAstro(${d.planet_id},'${escStr(d.name)}')" class="bd-action-link">Send Fleet</a>`;
  }
  html += ` &nbsp; <a href="javascript:void(0)" onclick="addBookmark('${escStr(d.name)}','${escStr(d.coords || d.name)}',${d.planet_id})" class="bd-action-link">&#9733; Bookmark</a>`;
  html += '</div>';

  if (d.fleets && d.fleets.length > 0) {
    html += `<div class="bd-section-title">Fleets</div>
    <table class="bd-fleet-table">
      <tr><th>Fleet</th><th>Player</th><th>Arrival</th><th>Size</th></tr>`;
    for (const f of d.fleets) {
      const pClass = f.is_mine ? 'text-success' : 'text-danger';
      const playerDisplay = f.guild_tag ? `[${escStr(f.guild_tag)}] ${escStr(f.player)}` : escStr(f.player);
      html += `<tr><td>${escStr(f.name)}</td><td class="${pClass}">${playerDisplay}</td><td class="text-dim"></td><td style="text-align:right;">${fmtNum(f.size)}</td></tr>`;
    }
    html += '</table>';
  }

  document.getElementById('base-detail-content').innerHTML = html;
}
