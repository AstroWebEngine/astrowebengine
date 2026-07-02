/* AstroWebEngine frontend (social_guild.js)
   Guild pages, guild board, guild graphs, and guild directory UI. */

// ============================================================
// GUILD SYSTEM
// ============================================================

let _myGuild = null;
let _guildDirectoryById = {};
let _guildPublicProfile = null;
let _guildEditOriginal = null;
let _guildInfoSlot = 1;
let _guildInfoEditing = false;
let _guildInfoPreview = false;
let _guildInfoDraft = null;
const _guildGraphViews = [
  { key: 'level', label: 'Level' },
  { key: 'members', label: 'Members' },
  { key: 'economy', label: 'Economy' },
  { key: 'fleet', label: 'Fleet' },
  { key: 'technology', label: 'Technology' },
  { key: 'comb_exp', label: 'Combat Experience' }
];
const _guildGraphPalette = ['#f4f4f4', '#ff3f3f', '#4ec6ff', '#f1d769', '#67eb9b', '#c7a4ff'];
let _guildGraphState = {
  view: 'level',
  scale: 'days',
  guildIds: [null, null, null, null, null, null],
  compareSlots: [],
  labels: [],
  datasets: []
};

function annotateGuildDirectory(guilds) {
  const ranked = (guilds || []).map(g => ({ ...g }));
  const rankByMetric = (field, rankField) => {
    ranked
      .slice()
      .sort((a, b) => Number(b?.[field] || 0) - Number(a?.[field] || 0))
      .forEach((guild, index) => {
        const match = ranked.find(row => row.id === guild.id);
        if (match) match[rankField] = index + 1;
      });
  };
  rankByMetric('guild_level', 'guild_level_rank');
  rankByMetric('total_economy', 'economy_rank');
  rankByMetric('total_fleet', 'fleet_rank');
  return ranked;
}

function mergeGuildDirectoryMeta(guild) {
  if (!guild || !guild.id) return guild;
  const meta = _guildDirectoryById[guild.id] || {};
  return {
    ...meta,
    ...guild,
    guild_level: guild.guild_level ?? meta.guild_level ?? null,
    total_economy: guild.total_economy ?? meta.total_economy ?? 0,
    total_fleet: guild.total_fleet ?? meta.total_fleet ?? 0,
    guild_level_rank: guild.guild_level_rank ?? meta.guild_level_rank ?? null,
    economy_rank: guild.economy_rank ?? meta.economy_rank ?? null,
    fleet_rank: guild.fleet_rank ?? meta.fleet_rank ?? null,
  };
}

function formatGuildMetricWithRank(valueHtml, rank) {
  return rank ? `${valueHtml} <small>(Rank ${rank})</small>` : valueHtml;
}

async function loadGuild() {
  try {
    const [myRes, allRes] = await Promise.all([apiFetch('/api/guilds/my'), apiFetch('/api/guilds')]);
    const myData = myRes ? await myRes.json() : {};
    const allGuilds = annotateGuildDirectory(allRes ? await allRes.json() : []);
    _myGuild = myData.guild || null;
    if (_myGuild) {
      _guildPublicProfile = null;
    } else {
      _guildInfoSlot = 1;
      _guildInfoEditing = false;
      _guildInfoPreview = false;
      _guildInfoDraft = null;
    }
    _guildDirectoryById = {};
    for (const guild of allGuilds) _guildDirectoryById[guild.id] = guild;
    if (_guildPublicProfile) {
      _guildPublicProfile = mergeGuildDirectoryMeta(_guildPublicProfile);
    }
    if (!_guildGraphState.guildIds.some(Boolean) && _myGuild && _myGuild.id) {
      _guildGraphState.guildIds[0] = _myGuild.id;
    }
    if (_myGuild) {
      renderMyGuild(mergeGuildDirectoryMeta(myData.guild));
      renderGuildMembers(mergeGuildDirectoryMeta(myData.guild));
    } else if (_guildPublicProfile) {
      renderPublicGuildProfile(_guildPublicProfile);
      renderGuildMembers(_guildPublicProfile);
    } else {
      renderMyGuild(null);
      renderGuildMembers(null);
    }
    renderGuildList(allGuilds, !!myData.guild);
    // Show/hide guild panels
    const boardPanel = document.getElementById('guild-board-panel');
    const membersPanel = document.getElementById('guild-members-panel');
    const appsPanel = document.getElementById('guild-apps-panel');
    const createPanel = document.getElementById('guild-create-panel');
    const boardHeader = document.querySelector('#guild-board-panel .panel-title');
    const boardBody = document.getElementById('guild-board');
    if (boardPanel) boardPanel.style.display = '';
    if (membersPanel) membersPanel.style.display = (myData.guild || _guildPublicProfile) ? '' : 'none';
    if (appsPanel) appsPanel.style.display = 'none';
    if (createPanel) createPanel.style.display = myData.guild ? 'none' : '';
    if (myData.guild) {
      const myGuildMember = (myData.guild.members || []).find(m => m.username === USERNAME);
      const myPerms = myGuildMember ? (myGuildMember.permissions || '') : '';
      const canRecruit = myData.guild.my_rank === 'leader' || myData.guild.my_rank === 'vice_leader' || myPerms.includes('R');
      _boardFolderNames = {general:'General',announcements:'Announcements',combat:'Combat',
        trade: myData.guild.board_name_3 || 'Trade', strategy: myData.guild.board_name_4 || 'Strategy'};
      // Show unread announcement badge on board panel header
      _unreadAnnouncements = myData.guild.unread_announcements || 0;
      const unreadAnn = _unreadAnnouncements;
      if (boardHeader) {
        boardHeader.innerHTML = unreadAnn > 0
          ? `Board <span style="color:red;font-weight:bold;font-size:11px;">(${unreadAnn})</span>`
          : 'Board';
      }
      // Auto-open announcements if there are unread ones
      if (unreadAnn > 0 && _boardFolder === 'general') {
        _boardFolder = 'announcements';
      }
      loadGuildBoard();
      if (appsPanel) appsPanel.style.display = canRecruit ? '' : 'none';
      if (canRecruit) loadGuildApplications();
    } else {
      if (boardHeader) boardHeader.textContent = 'Board';
      if (boardBody) {
        boardBody.innerHTML = '<div class="empty-state"><p>You are not a member of any guild.</p></div>';
      }
    }
  } catch (e) { console.error(e); }
}

let _boardFolder = 'general';
let _boardFolderNames = {general:'General',announcements:'Announcements',combat:'Combat',trade:'Trade',strategy:'Strategy'};
let _unreadAnnouncements = 0;
async function loadGuildBoard(folder) {
  if (folder) _boardFolder = folder;
  if (_boardFolder === 'announcements') _unreadAnnouncements = 0;
  try {
    const res = await apiFetch(`/api/guilds/board?folder=${_boardFolder}`);
    const data = await res.json();
    const el = document.getElementById('guild-board');
    const folders = ['general','announcements','combat','trade','strategy'];
    const folderNames = _boardFolderNames;
    let tabs = folders.map(f => {
      let label = folderNames[f];
      if (f === 'announcements' && _unreadAnnouncements > 0 && _boardFolder !== 'announcements') {
        label += ` <span style="color:red;font-weight:bold;">(${_unreadAnnouncements})</span>`;
      }
      return `<a href="#" class="${f===_boardFolder?'active':''}" onclick="loadGuildBoard('${f}');return false;">${label}</a>`;
    }).join('');
    let postsHtml = '';
    if (!data.posts || !data.posts.length) {
      postsHtml = '<div style="text-align:center;padding:12px;font-size:12px;" class="text-dim">Board is empty</div>';
    } else {
      postsHtml = `<table class="data-table" style="width:100%;font-size:12px;">
        <thead><tr><th></th><th style="text-align:left;">From</th><th></th><th>Date</th></tr></thead><tbody>`;
      for (const p of data.posts) {
        const dt = fmtDateTime(p.created_at);
        const author = p.author || 'System';
        const canDel = (p.author === USERNAME) ? `<input type="checkbox" class="board-post-check" value="${p.id}">` : '';
        const likeCount = p.likes || 0;
        postsHtml += `<tr>
          <td style="width:20px;">${canDel}</td>
          <td class="text-accent" style="white-space:nowrap;">${escStr(author)}</td>
          <td>Like ${likeCount} Â· <a href="#" class="text-dim" onclick="return false;">Quote</a></td>
          <td style="white-space:nowrap;text-align:right;" class="text-dim">${dt}</td>
        </tr>
        <tr><td colspan="4" style="padding:4px 8px 12px;font-size:12px;">${parseBBCode(p.body)}</div></td></tr>`;
      }
      postsHtml += '</tbody></table>';
      postsHtml += `<div style="margin-top:6px;display:flex;justify-content:space-between;align-items:center;">
        <div><a href="#" class="text-dim" style="font-size:11px;" onclick="return false;">see all posts</a> Â· <a href="#" class="text-dim" style="font-size:11px;" onclick="return false;">see my posts</a></div>
        <button class="input-button" onclick="deleteSelectedBoardPosts()">Delete selected</button>
        <span class="text-dim" style="font-size:10px;">viewing ${data.posts.length} messages of a total of ${data.total || data.posts.length}</span>
      </div>`;
      postsHtml += `<div class="text-dim" style="text-align:center;font-size:10px;margin-top:4px;">Messages more than 5 days old will be automatically deleted.</div>`;
    }
    // New post form with BBCode helper + text area + char counter
    const charLimit = 5000;
    let postForm = `<div style="margin-top:12px;border-top:1px solid var(--border);padding-top:8px;">
      <div style="text-align:center;font-size:14px;margin-bottom:6px;"><b>N</b>ew Post</div>
      <div style="display:flex;gap:12px;">
        <div style="font-size:10px;color:var(--text-dim);">
          <b>BBCode</b><br>
          [b] [i] [u] [h]<br>
          [code] [quote] [*]<br>
          [url] [color] [size]<br>
          [left] [center] [right]<br>
          [color=]
        </div>
        <div style="flex:1;">
          <textarea id="board-post-body" rows="4" style="width:100%;font-size:12px;background:var(--bg-dark);color:var(--text-bright);border:1px solid var(--border);" maxlength="${charLimit}"></textarea>
          <div style="text-align:right;font-size:10px;color:var(--text-dim);">(chars left: ${charLimit})</div>
          <div style="display:flex;gap:8px;justify-content:center;margin-top:4px;">
            <button class="input-button" onclick="submitBoardPost()">Post</button>
          </div>
        </div>
      </div>
    </div>`;
    el.innerHTML = `<div class="awe-tab-bar" style="margin-bottom:8px;">${tabs}</div>${postsHtml}${postForm}`;
  } catch (e) { console.error(e); }
}
async function submitBoardPost() {
  const body = document.getElementById('board-post-body')?.value?.trim();
  if (!body) return;
  try {
    const res = await apiFetch('/api/guilds/board', { method: 'POST', body: JSON.stringify({ folder: _boardFolder, body }) });
    const data = await res.json();
    if (data.success) { showSnack('Posted!'); loadGuildBoard(); }
    else showSnack(data.detail || 'Failed');
  } catch (e) { console.error(e); }
}
async function deleteBoardPost(postId) {
  if (!confirm('Delete this post?')) return;
  try {
    const res = await apiFetch(`/api/guilds/board/${postId}`, { method: 'DELETE' });
    const data = await res.json();
    if (data.success) loadGuildBoard();
  } catch (e) { console.error(e); }
}
async function deleteSelectedBoardPosts() {
  const checks = document.querySelectorAll('.board-post-check:checked');
  if (!checks.length) return;
  for (const c of checks) {
    try { await apiFetch(`/api/guilds/board/${c.value}`, { method: 'DELETE' }); } catch(e) {}
  }
  loadGuildBoard();
}

function guildRankSymbol(rank) {
  return rank === 'leader' ? '&lt;*&gt;' : (rank === 'vice_leader' ? '(*)' : '');
}

function fmtGuildAge(createdAt) {
  if (!createdAt) return '';
  const dt = new Date(createdAt);
  if (Number.isNaN(dt.getTime())) return '';
  const days = Math.max(0, Math.floor((Date.now() - dt.getTime()) / 86400000));
  return `${fmtNum(days)} Days`;
}

function normalizeGuildUrl(url) {
  const raw = (url || '').trim();
  if (!raw) return '';
  return /^https?:\/\//i.test(raw) ? raw : `https://${raw}`;
}

function getGuildInfoPages(guild) {
  const rawPages = Array.isArray(guild?.info_pages) ? guild.info_pages : [];
  const bySlot = {};
  for (const page of rawPages) {
    if (page && page.slot >= 1 && page.slot <= 4) bySlot[page.slot] = page;
  }
  return [1, 2, 3, 4].map(slot => ({
    slot,
    title: bySlot[slot]?.title || `Info ${slot}`,
    body: bySlot[slot]?.body || '',
  }));
}

function currentGuildInfoPage(guild) {
  const pages = getGuildInfoPages(guild);
  return pages.find(page => page.slot === _guildInfoSlot) || pages[0];
}

function selectGuildInfoSlot(slot) {
  _guildInfoSlot = Math.max(1, Math.min(4, Number(slot) || 1));
  _guildInfoEditing = false;
  _guildInfoPreview = false;
  _guildInfoDraft = null;
  if (_myGuild) renderMyGuild(_myGuild);
  else if (_guildPublicProfile) renderPublicGuildProfile(_guildPublicProfile);
}

function startGuildInfoEdit() {
  if (!_myGuild || !_myGuild.can_edit_internal) return;
  const page = currentGuildInfoPage(_myGuild);
  _guildInfoDraft = {
    title: page.title || `Info ${page.slot}`,
    body: page.body || '',
  };
  _guildInfoEditing = true;
  _guildInfoPreview = false;
  renderMyGuild(_myGuild);
}

function syncGuildInfoDraftFromDom() {
  if (!_guildInfoDraft) _guildInfoDraft = {};
  const titleEl = document.getElementById('guild-info-editor-title');
  const bodyEl = document.getElementById('guild-info-editor-body');
  if (titleEl) _guildInfoDraft.title = titleEl.value;
  if (bodyEl) _guildInfoDraft.body = bodyEl.value;
}

function updateGuildInfoCounter() {
  syncGuildInfoDraftFromDom();
  const counter = document.getElementById('guild-info-editor-counter');
  if (counter) counter.textContent = Math.max(0, 5000 - ((_guildInfoDraft?.body || '').length));
}

function resetGuildInfoDraft() {
  if (!_myGuild) return;
  const page = currentGuildInfoPage(_myGuild);
  _guildInfoDraft = {
    title: page.title || `Info ${page.slot}`,
    body: page.body || '',
  };
  _guildInfoPreview = false;
  renderMyGuild(_myGuild);
}

function toggleGuildInfoPreview() {
  syncGuildInfoDraftFromDom();
  _guildInfoPreview = !_guildInfoPreview;
  if (_myGuild) renderMyGuild(_myGuild);
}

async function saveGuildInfoPage() {
  if (!_myGuild) return;
  syncGuildInfoDraftFromDom();
  const payload = {
    title: (_guildInfoDraft?.title || `Info ${_guildInfoSlot}`).trim(),
    body: _guildInfoDraft?.body || '',
  };
  try {
    const res = await apiFetch(`/api/guilds/${_myGuild.id}/info/${_guildInfoSlot}`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (data.success) {
      const pages = getGuildInfoPages(_myGuild).map(page =>
        page.slot === _guildInfoSlot
          ? { ...page, title: payload.title || `Info ${_guildInfoSlot}`, body: payload.body }
          : page
      );
      _myGuild.info_pages = pages;
      _guildInfoEditing = false;
      _guildInfoPreview = false;
      _guildInfoDraft = null;
      showSnack('Guild page updated!');
      renderMyGuild(_myGuild);
    }
  } catch (e) {
    showSnack(e.message || 'Failed to update guild page');
  }
}

function openGuildCreateForm() {
  const panel = document.getElementById('guild-create-panel');
  if (panel) panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  const tagInput = document.getElementById('guild-create-tag');
  if (tagInput) setTimeout(() => tagInput.focus(), 120);
}

function resetGuildCreateForm() {
  const tag = document.getElementById('guild-create-tag');
  const name = document.getElementById('guild-create-name');
  const status = document.getElementById('guild-create-status');
  if (tag) tag.value = '';
  if (name) name.value = '';
  if (status) status.textContent = '';
}

function guildGraphInputValue(raw) {
  const num = Number(String(raw || '').trim());
  return Number.isFinite(num) && num > 0 ? Math.floor(num) : null;
}

function guildGraphMetaForId(guildId, slot) {
  if (slot && slot.guild_id === guildId && slot.tag) return slot;
  return _guildDirectoryById[guildId] || null;
}

function renderGuildGraphsMenu() {
  const menu = document.getElementById('guild-graphs-menu');
  if (!menu) return;
  menu.innerHTML = _guildGraphViews.map(view => `
    <button class="btn ${_guildGraphState.view === view.key ? 'btn-primary' : 'btn-ghost'}" type="button"
            onclick="setGuildGraphView('${view.key}')">${view.label}</button>
  `).join('');
}

function renderGuildGraphCompareForm(compareSlots) {
  const container = document.getElementById('guild-graphs-compare');
  if (!container) return;
  const slots = compareSlots && compareSlots.length
    ? compareSlots
    : _guildGraphState.guildIds.map((guildId, index) => {
        const meta = guildGraphMetaForId(guildId);
        return {
          index,
          guild_id: guildId,
          tag: meta?.tag || '',
          name: meta?.name || ''
        };
      });
  _guildGraphState.compareSlots = slots;
  container.innerHTML = slots.map(slot => {
    const tag = slot.tag ? `[${escStr(slot.tag)}]` : '';
    const name = slot.name ? escStr(slot.name) : '';
    const detailsLink = slot.guild_id
      ? `<a href="#" onclick="openGuildGraphDetails(${slot.guild_id});return false;">Details</a>`
      : '';
    return `
      <div class="guild-graph-slot">
        <input type="text" id="guild-graph-slot-${slot.index}" value="${slot.guild_id || ''}" maxlength="9" />
        <div class="guild-graph-slot-meta">
          <div class="guild-graph-slot-tag">${tag}${name ? ` ${name}` : ''}</div>
          <div class="guild-graph-slot-links">${detailsLink}</div>
        </div>
      </div>
    `;
  }).join('');
  const scaleEl = document.getElementById('guild-graphs-scale');
  if (scaleEl) scaleEl.value = _guildGraphState.scale || 'days';
}

function setGuildGraphView(viewKey) {
  collectGuildGraphFormState();
  _guildGraphState.view = viewKey;
  renderGuildGraphsMenu();
  loadGuildGraphs();
}

function collectGuildGraphFormState() {
  _guildGraphState.guildIds = Array.from({ length: 6 }, (_, index) =>
    guildGraphInputValue(document.getElementById(`guild-graph-slot-${index}`)?.value)
  );
  const scaleEl = document.getElementById('guild-graphs-scale');
  _guildGraphState.scale = scaleEl && scaleEl.value === 'months' ? 'months' : 'days';
}

function buildGuildGraphQuery() {
  const params = new URLSearchParams();
  params.set('view', _guildGraphState.view);
  params.set('scale', _guildGraphState.scale);
  _guildGraphState.guildIds.forEach((guildId, index) => {
    if (guildId) params.set(`guild${index}`, guildId);
  });
  return params.toString();
}

function guildGraphTickText(value) {
  if (value === null || value === undefined) return '';
  const num = Number(value);
  if (!Number.isFinite(num)) return '';
  if (Math.abs(num) >= 1000) return fmtNum(Math.round(num));
  if (Math.abs(num) >= 100) return num.toFixed(0);
  if (Math.abs(num) >= 10) return Number.isInteger(num) ? String(num) : num.toFixed(1).replace(/\.0$/, '');
  return Number.isInteger(num) ? String(num) : num.toFixed(2).replace(/0$/, '').replace(/\.$/, '');
}

function guildGraphNiceMax(maxValue) {
  if (!Number.isFinite(maxValue) || maxValue <= 0) return 1;
  const roughStep = maxValue / 4;
  const pow = Math.pow(10, Math.floor(Math.log10(roughStep)));
  const norm = roughStep / pow;
  let step;
  if (norm <= 1) step = 1;
  else if (norm <= 2) step = 2;
  else if (norm <= 2.5) step = 2.5;
  else if (norm <= 5) step = 5;
  else step = 10;
  return step * pow * 4;
}

function guildGraphLinePath(points) {
  let path = '';
  let drawing = false;
  for (const point of points) {
    if (!point) {
      drawing = false;
      continue;
    }
    path += `${drawing ? 'L' : 'M'}${point.x.toFixed(2)} ${point.y.toFixed(2)} `;
    drawing = true;
  }
  return path.trim();
}

function renderGuildGraphChart(data) {
  const wrap = document.getElementById('guild-graphs-chart-wrap');
  if (!wrap) return;
  const datasets = data.datasets || [];
  const hasData = datasets.some(set => (set.values || []).some(value => value !== null && value !== undefined));
  if (!hasData) {
    wrap.innerHTML = '<div class="guild-graphs-empty">No guild history has been recorded yet.</div>';
    return;
  }

  const width = 650;
  const height = 400;
  const margin = { top: 46, right: 18, bottom: 44, left: 62 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const pointCount = Math.max(1, (data.labels || []).length);
  const allValues = datasets.flatMap(set => (set.values || []).filter(value => value !== null && value !== undefined));
  const maxValue = guildGraphNiceMax(Math.max(...allValues));
  const xForIndex = index => margin.left + (pointCount === 1 ? plotWidth / 2 : (index / (pointCount - 1)) * plotWidth);
  const yForValue = value => margin.top + plotHeight - ((value / maxValue) * plotHeight);
  const yTicks = Array.from({ length: 5 }, (_, idx) => (maxValue / 4) * idx);
  const xLabelStep = pointCount > 18 ? 4 : pointCount > 12 ? 3 : pointCount > 8 ? 2 : 1;

  const gridLines = yTicks.map(tick => {
    const y = yForValue(tick);
    return `
      <line class="guild-graph-grid" x1="${margin.left}" y1="${y}" x2="${width - margin.right}" y2="${y}"></line>
      <text class="guild-graph-tick" x="${margin.left - 10}" y="${y + 4}" text-anchor="end">${guildGraphTickText(tick)}</text>
    `;
  }).join('');

  const xLabels = (data.labels || []).map((label, index) => {
    if (index !== pointCount - 1 && index % xLabelStep !== 0) return '';
    return `<text class="guild-graph-axis" x="${xForIndex(index)}" y="${height - 12}" text-anchor="middle">${escStr(label)}</text>`;
  }).join('');

  const legendStart = width / 2 - ((datasets.length * 86) / 2);
  const legends = datasets.map((set, index) => `
    <g class="guild-graph-legend">
      <rect x="${legendStart + index * 86}" y="20" width="16" height="16" fill="${_guildGraphPalette[index % _guildGraphPalette.length]}"></rect>
      <text x="${legendStart + index * 86 + 24}" y="33">[${escStr(set.tag)}]</text>
    </g>
  `).join('');

  const seriesMarkup = datasets.map((set, index) => {
    const color = _guildGraphPalette[index % _guildGraphPalette.length];
    const points = (set.values || []).map((value, pointIndex) => (
      value === null || value === undefined ? null : { x: xForIndex(pointIndex), y: yForValue(Number(value)), value: Number(value) }
    ));
    const path = guildGraphLinePath(points);
    const pointDots = points.map(point => {
      if (!point) return '';
      return `<circle cx="${point.x}" cy="${point.y}" r="3.2" fill="${color}"></circle>`;
    }).join('');
    return `
      <path d="${path}" fill="none" stroke="${color}" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"></path>
      ${pointDots}
    `;
  }).join('');

  wrap.innerHTML = `
    <svg class="guild-graph-svg" viewBox="0 0 ${width} ${height}" aria-label="${escAttr(data.title)} graph">
      <text class="guild-graph-title" x="${width / 2}" y="16" text-anchor="middle">${escStr(data.title)}</text>
      ${legends}
      ${gridLines}
      <line class="guild-graph-axis-line" x1="${margin.left}" y1="${margin.top}" x2="${margin.left}" y2="${margin.top + plotHeight}"></line>
      <line class="guild-graph-axis-line" x1="${margin.left}" y1="${margin.top + plotHeight}" x2="${width - margin.right}" y2="${margin.top + plotHeight}"></line>
      ${seriesMarkup}
      ${xLabels}
      <text class="guild-graph-axis-label" x="${width / 2}" y="${height - 2}" text-anchor="middle">${escStr(data.x_label || '')}</text>
    </svg>
  `;
}

async function openGuildGraphDetails(guildId) {
  document.getElementById('generic-modal-title').textContent = 'Guild Details';
  document.getElementById('generic-modal-body').innerHTML = '<p class="text-dim" style="text-align:center;padding:12px;">Loading...</p>';
  openModal('generic-modal');
  try {
    const res = await apiFetch(`/api/guilds/${guildId}/view`);
    const guild = await res.json();
    const description = guild.description
      ? `<div style="margin-top:10px;padding:10px;border:1px solid var(--border);font-size:12px;">${parseBBCode(guild.description)}</div>`
      : '';
    document.getElementById('generic-modal-body').innerHTML = `
      <table class="data-table" style="width:100%;font-size:12px;">
        <tbody>
          <tr><th style="width:120px;">Name</th><td>${escStr(guild.name || '')}</td></tr>
          <tr><th>Tag</th><td>[${escStr(guild.tag || '')}]</td></tr>
          <tr><th>Leader</th><td>${escStr(guild.leader || '')}</td></tr>
          <tr><th>Members</th><td>${fmtNum(guild.member_count || 0)}</td></tr>
        </tbody>
      </table>
      ${description}
    `;
  } catch (e) {
    document.getElementById('generic-modal-body').innerHTML = '<p class="text-dim" style="text-align:center;padding:12px;">Unable to load guild details.</p>';
  }
}

async function loadGuildGraphs() {
  const wrap = document.getElementById('guild-graphs-chart-wrap');
  if (wrap) wrap.innerHTML = '<div class="text-dim" style="text-align:center;padding:24px;">Loading...</div>';
  try {
    const res = await apiFetch(`/api/guilds/graphs?${buildGuildGraphQuery()}`);
    if (!res) return;
    const data = await res.json();
    _guildGraphState.view = data.view || _guildGraphState.view;
    _guildGraphState.scale = data.scale || _guildGraphState.scale;
    _guildGraphState.guildIds = (data.compare_slots || []).map(slot => slot.guild_id || null);
    _guildGraphState.compareSlots = data.compare_slots || [];
    _guildGraphState.labels = data.labels || [];
    _guildGraphState.datasets = data.datasets || [];
    renderGuildGraphsMenu();
    renderGuildGraphCompareForm(data.compare_slots || []);
    renderGuildGraphChart(data);
  } catch (e) {
    if (wrap) wrap.innerHTML = '<div class="guild-graphs-empty">Error loading guild history.</div>';
  }
}

function submitGuildGraphs() {
  collectGuildGraphFormState();
  loadGuildGraphs();
}

function openGuildGraphs(initialView) {
  if (typeof initialView === 'number' && Number.isFinite(initialView)) {
    _guildGraphState.guildIds[0] = initialView;
  } else if (initialView) {
    _guildGraphState.view = initialView;
  }
  if (!_guildGraphState.guildIds.some(Boolean) && _myGuild && _myGuild.id) {
    _guildGraphState.guildIds[0] = _myGuild.id;
  }
  if (document.getElementById('guild-edit-modal')?.classList.contains('active')) {
    closeModal('guild-edit-modal');
  }
  renderGuildGraphsMenu();
  renderGuildGraphCompareForm();
  const wrap = document.getElementById('guild-graphs-chart-wrap');
  if (wrap) wrap.innerHTML = '<div class="text-dim" style="text-align:center;padding:24px;">Loading...</div>';
  openModal('guild-graphs-modal');
  loadGuildGraphs();
}

function openGuildScannerReport(guildId) {
  _guildReportGuildId = Number(guildId) || null;
  _scannersTab = 'guild';
  switchTab('empire');
  switchEmpireSubtab('reports');
  loadScanners();
}

function renderPublicGuildProfile(guild) {
  const el = document.getElementById('guild-my');
  if (!el || !guild) return;
  const mergedGuild = mergeGuildDirectoryMeta(guild);
  const guildAge = fmtGuildAge(mergedGuild.created_at);
  const safeHomepage = normalizeGuildUrl(mergedGuild.homepage);
  const safeForum = normalizeGuildUrl(mergedGuild.forum_url);
  const leaderMember = (mergedGuild.members || []).find(m => m.username === mergedGuild.leader);
  const leaderAction = leaderMember && leaderMember.id
    ? `showPlayerProfile(${leaderMember.id})`
    : `showPlayerProfileByName('${escAttr(mergedGuild.leader)}')`;
  const infoPages = getGuildInfoPages(mergedGuild);
  const currentPage = currentGuildInfoPage(mergedGuild);
  const externalLinks = [];
  if (safeHomepage) externalLinks.push(`<a href="${escAttr(safeHomepage)}" target="_blank" rel="noopener noreferrer">Homepage</a>`);
  if (safeForum) externalLinks.push(`<a href="${escAttr(safeForum)}" target="_blank" rel="noopener noreferrer">Forum</a>`);
  const actionButtons = [
    `<button class="btn btn-ghost btn-sm" onclick="openGuildGraphs(${mergedGuild.id})">Historical graphs</button>`
  ];
  if (!_myGuild) {
    actionButtons.push(`<button class="btn btn-primary btn-sm" onclick="joinGuild(${mergedGuild.id})">Request to join</button>`);
  }
  actionButtons.push(`<button class="btn btn-ghost btn-sm" onclick="openGuildScannerReport(${mergedGuild.id})">List bases and fleets</button>`);
  actionButtons.push(`<button class="btn btn-ghost btn-sm" onclick="showSnack('Guild profile reports are not implemented yet')">Report</button>`);
  const infoTabs = infoPages.map(page => `
    <a href="#" class="${page.slot === _guildInfoSlot ? 'active' : ''}" onclick="selectGuildInfoSlot(${page.slot});return false;">${escStr(page.title || `Info ${page.slot}`)}</a>
  `).join('');
  const levelValue = formatGuildMetricWithRank(mergedGuild.guild_level || '?', mergedGuild.guild_level_rank);
  const economyValue = formatGuildMetricWithRank(fmtNum(mergedGuild.total_economy || 0), mergedGuild.economy_rank);
  const fleetValue = formatGuildMetricWithRank(fmtNum(mergedGuild.total_fleet || 0), mergedGuild.fleet_rank);
  el.innerHTML = `
    <div class="guild-profile-shell">
      <div class="guild-profile-name">${escStr(mergedGuild.name)}</div>
      <div class="guild-profile-layout">
        <div class="guild-profile-specs">
          <div class="guild-profile-stat"><span class="guild-profile-label">Guild</span><span class="guild-profile-value">${mergedGuild.id}</span></div>
          <div class="guild-profile-stat"><span class="guild-profile-label">Tag</span><span class="guild-profile-value">[${escStr(mergedGuild.tag)}]</span></div>
          <div class="guild-profile-stat"><span class="guild-profile-label">Guild Master</span><span class="guild-profile-value"><a href="#" class="text-accent" onclick="${leaderAction};return false;">${escStr(mergedGuild.leader)}</a></span></div>
          <div class="guild-profile-stat"><span class="guild-profile-label">Members</span><span class="guild-profile-value">${mergedGuild.member_count || (mergedGuild.members || []).length}</span></div>
          <div class="guild-profile-stat"><span class="guild-profile-label">Level</span><span class="guild-profile-value">${levelValue}</span></div>
          <div class="guild-profile-stat"><span class="guild-profile-label">Economy</span><span class="guild-profile-value">${economyValue}</span></div>
          <div class="guild-profile-stat"><span class="guild-profile-label">Fleet</span><span class="guild-profile-value">${fleetValue}</span></div>
          ${guildAge ? `<div class="guild-profile-stat"><span class="guild-profile-label">Guild Created</span><span class="guild-profile-value">${guildAge}</span></div>` : ''}
        </div>
        <div class="guild-profile-emblem">
          <div class="guild-profile-tag">[${escStr(mergedGuild.tag)}]</div>
        </div>
        <div class="guild-profile-description bbcode-content">
          ${mergedGuild.description ? parseBBCode(mergedGuild.description) : '<span class="text-dim">No guild description.</span>'}
        </div>
      </div>
      ${externalLinks.length ? `<div class="guild-profile-links">${externalLinks.join('<span class="text-dim">&middot;</span>')}</div>` : ''}
      <div class="guild-action-row">${actionButtons.join('')}</div>
      <div class="guild-internal-shell">
        <div class="awe-tab-bar guild-internal-tabs">${infoTabs}</div>
        <div class="guild-internal-content bbcode-content">${currentPage.body ? parseBBCode(currentPage.body) : '<span class="text-dim">No guild info posted.</span>'}</div>
      </div>
    </div>`;
}

function renderMyGuild(guild) {
  const el = document.getElementById('guild-my');
  if (!guild) {
    el.innerHTML = `<div class="guild-empty-shell">
      <div class="guild-empty-copy">
        <div class="guild-empty-title">You are not a member of any guild.</div>
        <div class="guild-empty-actions">
          <a href="#" class="text-accent" onclick="openGuildCreateForm();return false;">Create new guild</a>
        </div>
      </div>
    </div>`;
    return;
  }
  const guildAge = fmtGuildAge(guild.created_at);
  const safeHomepage = normalizeGuildUrl(guild.homepage);
  const safeForum = normalizeGuildUrl(guild.forum_url);
  const leaderMember = (guild.members || []).find(m => m.username === guild.leader);
  const leaderAction = leaderMember && leaderMember.id
    ? `showPlayerProfile(${leaderMember.id})`
    : `showPlayerProfileByName('${escAttr(guild.leader)}')`;
  const mergedGuild = mergeGuildDirectoryMeta(guild);
  const externalLinks = [];
  if (safeHomepage) externalLinks.push(`<a href="${escAttr(safeHomepage)}" target="_blank" rel="noopener noreferrer">Homepage</a>`);
  if (safeForum) externalLinks.push(`<a href="${escAttr(safeForum)}" target="_blank" rel="noopener noreferrer">Forum</a>`);
  const infoPages = getGuildInfoPages(guild);
  const currentPage = currentGuildInfoPage(guild);
  const actionButtons = [];
  if (guild.my_rank === 'leader') {
    actionButtons.push(`<button class="btn btn-primary btn-sm" onclick="openGuildEditModal(${guild.id}, '${escAttr(guild.name)}', '${escAttr(guild.tag)}')">Edit guild</button>`);
  } else {
    actionButtons.push(`<button class="btn btn-ghost btn-sm" onclick="leaveGuild()">Withdraw from guild</button>`);
  }
  actionButtons.push(`<button class="btn btn-ghost btn-sm" onclick="openGuildLogModal()">Guild logs</button>`);
  actionButtons.push(`<button class="btn btn-ghost btn-sm" onclick="openGuildGraphs()">Historical graphs</button>`);
  const infoTabs = infoPages.map(page => `
    <a href="#" class="${page.slot === _guildInfoSlot ? 'active' : ''}" onclick="selectGuildInfoSlot(${page.slot});return false;">${escStr(page.title || `Info ${page.slot}`)}</a>
  `).join('');
  const draft = _guildInfoDraft || {
    title: currentPage.title || `Info ${currentPage.slot}`,
    body: currentPage.body || '',
  };
  const infoEditButton = guild.can_edit_internal
    ? `<div class="guild-internal-edit-row"><button class="btn btn-ghost btn-sm" onclick="startGuildInfoEdit()">Edit</button></div>`
    : '';
  const infoEditor = !_guildInfoEditing ? '' : `
    <div class="guild-internal-editor">
      <div class="guild-internal-editor-title-row">
        <label for="guild-info-editor-title">Title:</label>
        <input type="text" id="guild-info-editor-title" maxlength="30" value="${escAttr(draft.title || `Info ${currentPage.slot}`)}" oninput="syncGuildInfoDraftFromDom()" />
      </div>
      <div class="guild-internal-toolbar">
        <span class="guild-internal-toolbar-title">BBCode</span>
        <button class="btn btn-ghost btn-sm bbcode-btn" type="button" onclick="bbcodeInsertTag('guild-info-editor-body','b')">b</button>
        <button class="btn btn-ghost btn-sm bbcode-btn" type="button" onclick="bbcodeInsertTag('guild-info-editor-body','u')">u</button>
        <button class="btn btn-ghost btn-sm bbcode-btn" type="button" onclick="bbcodeInsertTag('guild-info-editor-body','i')">i</button>
        <button class="btn btn-ghost btn-sm bbcode-btn" type="button" onclick="bbcodeInsertTag('guild-info-editor-body','s')">s</button>
        <button class="btn btn-ghost btn-sm bbcode-btn" type="button" onclick="bbcodeInsertTag('guild-info-editor-body','code')">code</button>
        <button class="btn btn-ghost btn-sm bbcode-btn" type="button" onclick="bbcodeInsertTag('guild-info-editor-body','quote')">quote</button>
        <button class="btn btn-ghost btn-sm bbcode-btn" type="button" onclick="bbcodeInsertTag('guild-info-editor-body','list')">list</button>
        <button class="btn btn-ghost btn-sm bbcode-btn" type="button" onclick="bbcodeInsertTag('guild-info-editor-body','*')">*</button>
        <button class="btn btn-ghost btn-sm bbcode-btn" type="button" onclick="bbcodeInsertTag('guild-info-editor-body','url')">url</button>
        <button class="btn btn-ghost btn-sm bbcode-btn" type="button" onclick="bbcodeInsertTag('guild-info-editor-body','left')">left</button>
        <button class="btn btn-ghost btn-sm bbcode-btn" type="button" onclick="bbcodeInsertTag('guild-info-editor-body','center')">center</button>
        <button class="btn btn-ghost btn-sm bbcode-btn" type="button" onclick="bbcodeInsertTag('guild-info-editor-body','right')">right</button>
        <button class="btn btn-ghost btn-sm bbcode-btn" type="button" onclick="bbcodeInsertTag('guild-info-editor-body','img')">img</button>
        <button class="btn btn-ghost btn-sm bbcode-btn" type="button" onclick="bbcodeInsertTag('guild-info-editor-body','size=')">size=</button>
        <button class="btn btn-ghost btn-sm bbcode-btn" type="button" onclick="bbcodeInsertTag('guild-info-editor-body','color=')">color=</button>
      </div>
      ${_guildInfoPreview
        ? `<div class="guild-internal-preview bbcode-content">${draft.body ? parseBBCode(draft.body) : '<span class="text-dim">Nothing to preview.</span>'}</div>`
        : `<textarea id="guild-info-editor-body" rows="12" maxlength="5000" oninput="updateGuildInfoCounter()">${escStr(draft.body || '')}</textarea>`}
      <div class="guild-internal-editor-footer">
        <div class="guild-internal-editor-counter">(chars left: <span id="guild-info-editor-counter">${Math.max(0, 5000 - (draft.body || '').length)}</span>)</div>
        <div class="guild-internal-editor-actions">
          <button class="btn btn-ghost" type="button" onclick="resetGuildInfoDraft()">Reset</button>
          <button class="btn btn-ghost" type="button" onclick="toggleGuildInfoPreview()">${_guildInfoPreview ? 'Back' : 'Preview'}</button>
          <button class="btn btn-primary" type="button" onclick="saveGuildInfoPage()">Submit</button>
        </div>
      </div>
    </div>`;
  const infoBody = _guildInfoEditing
    ? infoEditor
    : `<div class="guild-internal-content bbcode-content">${currentPage.body ? parseBBCode(currentPage.body) : '<span class="text-dim">No guild info posted.</span>'}</div>`;
  const levelValue = formatGuildMetricWithRank(mergedGuild.guild_level || '?', mergedGuild.guild_level_rank);
  const economyValue = formatGuildMetricWithRank(fmtNum(mergedGuild.total_economy || 0), mergedGuild.economy_rank);
  const fleetValue = formatGuildMetricWithRank(fmtNum(mergedGuild.total_fleet || 0), mergedGuild.fleet_rank);
  el.innerHTML = `
    <div class="guild-profile-shell">
      <div class="guild-profile-name">${escStr(guild.name)}</div>
      <div class="guild-profile-layout">
        <div class="guild-profile-specs">
          <div class="guild-profile-stat"><span class="guild-profile-label">Guild</span><span class="guild-profile-value">${guild.id}</span></div>
          <div class="guild-profile-stat"><span class="guild-profile-label">Tag</span><span class="guild-profile-value">[${escStr(guild.tag)}]</span></div>
          <div class="guild-profile-stat"><span class="guild-profile-label">Guild Master</span><span class="guild-profile-value"><a href="#" class="text-accent" onclick="${leaderAction};return false;">${escStr(guild.leader)}</a></span></div>
          <div class="guild-profile-stat"><span class="guild-profile-label">Members</span><span class="guild-profile-value">${guild.member_count || guild.members.length}</span></div>
          <div class="guild-profile-stat"><span class="guild-profile-label">Level</span><span class="guild-profile-value">${levelValue}</span></div>
          <div class="guild-profile-stat"><span class="guild-profile-label">Economy</span><span class="guild-profile-value">${economyValue}</span></div>
          <div class="guild-profile-stat"><span class="guild-profile-label">Fleet</span><span class="guild-profile-value">${fleetValue}</span></div>
          ${guildAge ? `<div class="guild-profile-stat"><span class="guild-profile-label">Guild Created</span><span class="guild-profile-value">${guildAge}</span></div>` : ''}
        </div>
        <div class="guild-profile-emblem">
          <div class="guild-profile-tag">[${escStr(guild.tag)}]</div>
        </div>
        <div class="guild-profile-description bbcode-content">
          ${guild.description ? parseBBCode(guild.description) : '<span class="text-dim">No guild description.</span>'}
        </div>
      </div>
      ${externalLinks.length ? `<div class="guild-profile-links">${externalLinks.join('<span class="text-dim">&middot;</span>')}</div>` : ''}
      <div class="guild-action-row">${actionButtons.join('')}</div>
      <div class="guild-internal-shell">
        <div class="awe-tab-bar guild-internal-tabs">${infoTabs}</div>
        ${infoEditButton}
        ${infoBody}
      </div>
    </div>`;
}

function renderGuildMembers(guild) {
  const el = document.getElementById('guild-members');
  if (!el) return;
  if (!guild) {
    el.innerHTML = '';
    return;
  }
  const myMember = guild.members.find(m => m.username === USERNAME);
  const myPerms = myMember ? myMember.permissions || '' : '';
  const hasOfficerAccess = guild.my_rank === 'leader' || guild.my_rank === 'vice_leader';
  const canTitle = hasOfficerAccess || myPerms.includes('T');
  const canKick = hasOfficerAccess || myPerms.includes('K');
  const showActions = canTitle || canKick;
  const showInactivity = guild.members.some(m => m.inactivity_mins !== null && m.inactivity_mins !== undefined);
  const rows = guild.members.map(m => {
    const rankBits = [];
    if (m.title) rankBits.push(`<span class="guild-member-title">${escStr(m.title)}</span>`);
    const rankMarker = guildRankSymbol(m.rank);
    if (rankMarker) rankBits.push(`<span class="guild-member-rank">${rankMarker}</span>`);
    if (m.permissions) rankBits.push(`<span class="guild-member-flags">${escStr(m.permissions)}</span>`);
    const rankCell = rankBits.length ? rankBits.join(' ') : '<span class="text-dim">-</span>';
    const playerAction = m.id ? `showPlayerProfile(${m.id})` : `showPlayerProfileByName('${escAttr(m.username)}')`;
    let actions = '';
    if (showActions && m.username !== USERNAME && m.rank !== 'leader') {
      if (canTitle) actions += `<button class="btn btn-ghost btn-sm" onclick="openPermEditor('${escAttr(m.username)}','${m.rank}','${escAttr(m.permissions || '')}','${escAttr(m.title || '')}')" title="Edit permissions">Perms</button>`;
      if (canKick) actions += `<button class="btn btn-danger btn-sm" onclick="kickGuildMember('${escAttr(m.username)}')" title="Kick">Kick</button>`;
    }
    return `<tr class="${m.username === USERNAME ? 'guild-member-self' : ''}">
      <td class="center">${m.id || ''}</td>
      <td class="center guild-member-rankcell">${rankCell}</td>
      <td><a href="#" class="text-accent" onclick="${playerAction};return false;">${escStr(m.username)}</a></td>
      <td class="right">${Number(m.level || 0).toFixed(2)}</td>
      <td class="right">${fmtNum(m.economy || 0)}</td>
      <td class="right">${fmtNum(m.fleet || 0)}</td>
      <td class="right">${fmtNum(m.technology || 0)}</td>
      <td class="right">${fmtNum(m.experience || 0)}</td>
      ${showInactivity ? `<td class="right">${m.inactivity_mins !== null && m.inactivity_mins !== undefined ? `${fmtNum(m.inactivity_mins)} min` : '-'}</td>` : ''}
      ${showActions ? `<td class="center guild-member-actions">${actions || '<span class="text-dim">-</span>'}</td>` : ''}
    </tr>`;
  }).join('');
  el.innerHTML = `
    <table class="data-table guild-members-table">
      <thead>
        <tr>
          <th class="center">ID</th>
          <th class="center">Title/Rank</th>
          <th>Player</th>
          <th class="right">Level</th>
          <th class="right">Economy</th>
          <th class="right">Fleet</th>
          <th class="right">Technology</th>
          <th class="right">Experience</th>
          ${showInactivity ? '<th class="right">Inactivity</th>' : ''}
          ${showActions ? '<th class="center">Actions</th>' : ''}
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
    <div class="guild-members-legend">&lt;*&gt;=Guild Master &nbsp;(*)=Vice Leader &nbsp;R=Recruit K=Kick M=Announcements I=Internal T=Titles F=Fleets +=View Inactivity/Scouted data -=Scouted data</div>`;
}

function renderGuildList(guilds, inGuild) {
  const el = document.getElementById('guild-list');
  if (!el) return;
  const createBlock = inGuild ? '' : `
    <div class="guild-create-box">
      <div class="guild-create-title">Create new guild</div>
      <div class="guild-create-simple">
        <div class="guild-create-row">
          <label for="guild-create-tag">Tag</label>
          <input type="text" id="guild-create-tag" maxlength="5" placeholder="SHIP" style="text-transform:uppercase;" />
        </div>
        <div class="guild-create-row">
          <label for="guild-create-name">Name</label>
          <input type="text" id="guild-create-name" maxlength="36" placeholder="Ship Happens" />
        </div>
      </div>
      <div class="guild-create-note">Requires 21 total economy to create a guild.</div>
      <div class="guild-create-actions">
        <button class="btn btn-ghost" onclick="resetGuildCreateForm()">Reset</button>
        <button class="btn btn-primary" onclick="createGuild()">Submit</button>
      </div>
      <div id="guild-create-status" style="font-size:11px;margin-top:6px;"></div>
    </div>`;
  if (!guilds.length) {
    el.innerHTML = `${createBlock}<div class="empty-state"><p>No guilds created yet.</p></div>`;
    return;
  }
  let html = `${createBlock}<div class="guild-directory-title">Guild Directory</div><table class="data-table guild-directory-table"><thead><tr><th>Tag</th><th>Name</th><th>Leader</th><th class="right">Members</th><th class="right">Level</th><th></th></tr></thead><tbody>`;
  for (const g of guilds) {
    const joinBtn = inGuild ? '' : `<button class="btn btn-primary btn-sm" onclick="joinGuild(${g.id})">Apply</button>`;
    html += `<tr>
      <td class="text-accent font-bold">[${escStr(g.tag)}]</td>
      <td><a href="#" class="text-bright" onclick="viewGuildProfile(${g.id});return false;">${escStr(g.name)}</a></td>
      <td class="text-dim">${escStr(g.leader)}</td>
      <td class="right">${fmtNum(g.members || 0)}</td>
      <td class="right">${g.guild_level || '-'}</td>
      <td class="center">${joinBtn}</td>
    </tr>`;
  }
  html += '</tbody></table>';
  el.innerHTML = html;
}

async function createGuild() {
  const name = document.getElementById('guild-create-name').value.trim();
  const tag = document.getElementById('guild-create-tag').value.trim();
  const statusEl = document.getElementById('guild-create-status');
  if (!name || !tag) { statusEl.innerHTML = '<span class="text-danger">Name and tag required</span>'; return; }
  try {
    const res = await apiFetch('/api/guilds', { method: 'POST', body: JSON.stringify({ name, tag, description: '' }) });
    const data = await res.json();
    if (data.success) { resetGuildCreateForm(); showSnack('Guild created!'); loadGuild(); }
    else { statusEl.innerHTML = `<span class="text-danger">${data.detail || 'Failed'}</span>`; }
  } catch (e) { statusEl.innerHTML = '<span class="text-danger">Error</span>'; }
}

async function joinGuild(guildId) {
  try {
    const res = await apiFetch(`/api/guilds/${guildId}/join`, { method: 'POST' });
    const data = await res.json();
    if (data.success) { showSnack(data.message || 'Application submitted!'); loadGuild(); }
    else showSnack(data.detail || 'Failed');
  } catch (e) {}
}

async function leaveGuild() {
  if (!confirm('Leave your guild? If you are the last member, the guild will be disbanded.')) return;
  try {
    const res = await apiFetch('/api/guilds/leave', { method: 'POST' });
    const data = await res.json();
    if (data.success) { showSnack(data.message || 'Left guild'); loadGuild(); }
    else showSnack(data.detail || 'Failed');
  } catch (e) {}
}

async function kickGuildMember(username) {
  if (!confirm(`Kick ${username} from the guild?`)) return;
  try {
    const res = await apiFetch('/api/guilds/kick', { method: 'POST', body: JSON.stringify({ username }) });
    const data = await res.json();
    if (data.success) { showSnack(`${username} kicked`); loadGuild(); }
    else showSnack(data.detail || 'Failed');
  } catch (e) {}
}

async function saveGuildMemberPerms(username, rank, permissions, title, oldPerms) {
  try {
    const res = await apiFetch('/api/guilds/promote', {
      method: 'POST',
      body: JSON.stringify({ username, rank, permissions, title, old_permissions: oldPerms || '' })
    });
    const data = await res.json();
    if (data.success) { showSnack(`${username} updated`); loadGuild(); }
    else showSnack(data.detail || 'Failed');
  } catch (e) { console.error(e); }
}

async function loadGuildApplications() {
  const panel = document.getElementById('guild-apps-panel');
  const el = document.getElementById('guild-apps');
  if (!panel || !el) return;
  try {
    const res = await apiFetch('/api/guilds/applications');
    const data = await res.json();
    const apps = data.applications || [];
    if (!apps.length) {
      panel.style.display = '';
      el.innerHTML = '<div class="text-dim" style="text-align:center;padding:12px;font-size:11px;">No pending members</div>';
      return;
    }
    panel.style.display = '';
    let html = '<table class="data-table" style="font-size:11px;"><thead><tr><th>Player</th><th>Applied</th><th></th></tr></thead><tbody>';
    for (const a of apps) {
      html += `<tr>
        <td class="text-bright">${escStr(a.username)}</td>
        <td class="text-dim">${fmtDateTime(a.applied_at)}</td>
        <td style="white-space:nowrap;">
          <button class="btn btn-primary btn-sm" onclick="acceptApplication(${a.id})" style="font-size:10px;">Accept</button>
          <button class="btn btn-danger btn-sm" onclick="rejectApplication(${a.id})" style="font-size:10px;">Reject</button>
        </td>
      </tr>`;
    }
    html += '</tbody></table>';
    el.innerHTML = html;
  } catch (e) {
    panel.style.display = 'none';
  }
}

async function acceptApplication(appId) {
  try {
    const res = await apiFetch(`/api/guilds/applications/${appId}/accept`, { method: 'POST' });
    const data = await res.json();
    if (data.success) { showSnack('Member accepted!'); loadGuild(); }
    else showSnack(data.detail || 'Failed');
  } catch (e) {}
}

async function rejectApplication(appId) {
  try {
    const res = await apiFetch(`/api/guilds/applications/${appId}/reject`, { method: 'POST' });
    const data = await res.json();
    if (data.success) { showSnack('Application rejected'); loadGuild(); }
    else showSnack(data.detail || 'Failed');
  } catch (e) {}
}

async function openGuildLogModal() {
  document.getElementById('generic-modal-title').textContent = 'Guild logs';
  document.getElementById('generic-modal-body').innerHTML = '<p class="text-dim" style="text-align:center;padding:12px;">Loading...</p>';
  openModal('generic-modal');
  try {
    const res = await apiFetch('/api/guilds/log');
    const data = await res.json();
    const logs = data.logs || [];
    let html = '';
    if (!logs.length) {
      html = '<p class="text-dim" style="font-size:11px;padding:8px;">No log entries yet.</p>';
    } else {
      html = '<div class="guild-log-wrap"><table class="data-table guild-log-table"><thead><tr><th>Date</th><th>Done By</th><th>Description</th><th>Member</th></tr></thead><tbody>';
      for (const l of logs) {
        html += `<tr>
          <td class="text-dim" style="white-space:nowrap;">${fmtDateTime(l.date)}</td>
          <td class="text-bright">${escStr(l.done_by)}</td>
          <td>${escStr(l.description)}</td>
          <td class="text-accent">${escStr(l.member)}</td>
        </tr>`;
      }
      html += '</tbody></table></div>';
    }
    document.getElementById('generic-modal-body').innerHTML = html;
  } catch (e) {
    document.getElementById('generic-modal-body').innerHTML = '<p class="text-dim" style="font-size:11px;padding:8px;">Error loading log.</p>';
  }
}

function openPermEditor(username, currentRank, currentPerms, currentTitle) {
  const allFlags = ['R','K','M','I','T','F','+','-'];
  const flagNames = {R:'Recruit',K:'Kick',M:'Announcements',I:'Internal',T:'Titles',F:'Fleets','+':'Inactivity+Scouted','-':'Scouted only'};
  let checkboxes = allFlags.map(f => {
    const checked = currentPerms.includes(f) ? 'checked' : '';
    return `<label style="display:inline-flex;align-items:center;gap:3px;margin-right:8px;font-size:11px;cursor:pointer;">
      <input type="checkbox" class="perm-cb" value="${f}" ${checked}> <b>${f}</b>=${flagNames[f]}
    </label>`;
  }).join('');
  const isVL = currentRank === 'vice_leader';
  const html = `<div style="padding:12px;">
    <div style="margin-bottom:8px;font-size:13px;">Permissions for <b>${escStr(username)}</b></div>
    <div class="form-group" style="margin-bottom:8px;">
      <label>Rank</label>
      <select id="perm-rank" style="font-size:11px;">
        <option value="member" ${!isVL?'selected':''}>Member</option>
        <option value="vice_leader" ${isVL?'selected':''}>Vice Leader (*)</option>
      </select>
    </div>
    <div class="form-group" style="margin-bottom:8px;">
      <label>Title</label>
      <input type="text" id="perm-title" value="${escStr(currentTitle)}" maxlength="30" placeholder="e.g. Nostalgic, Recruiter" style="font-size:11px;" />
    </div>
    <div style="margin-bottom:8px;">
      <label>Permission Flags</label><br>
      ${checkboxes}
    </div>
    <div style="display:flex;gap:8px;">
      <button class="btn btn-primary btn-sm" onclick="
        const rank = document.getElementById('perm-rank').value;
        const title = document.getElementById('perm-title').value;
        const perms = [...document.querySelectorAll('.perm-cb:checked')].map(c=>c.value).join('');
        saveGuildMemberPerms('${escStr(username)}', rank, perms, title, '${escStr(currentPerms)}');
        closeModal('perm-editor-modal');
      ">Save</button>
      <button class="btn btn-ghost btn-sm" onclick="closeModal('perm-editor-modal')">Cancel</button>
    </div>
  </div>`;
  // Use a dynamic modal
  let modal = document.getElementById('perm-editor-modal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'perm-editor-modal';
    modal.className = 'modal-overlay';
    modal.innerHTML = `<div class="modal" style="width:min(450px,90vw);"><div class="modal-header"><span class="modal-title">Edit Permissions</span><button class="modal-close" onclick="closeModal('perm-editor-modal')">&times;</button></div><div class="modal-body" id="perm-editor-body"></div></div>`;
    document.body.appendChild(modal);
  }
  document.getElementById('perm-editor-body').innerHTML = html;
  openModal('perm-editor-modal');
}

function openGuildEditModal(guildId, name, tag) {
  document.getElementById('guild-edit-id').value = guildId;
  document.getElementById('guild-edit-name').value = name;
  document.getElementById('guild-edit-tag').value = tag;
  apiFetch('/api/guilds/my').then(r => r.json()).then(d => {
    if (d.guild) {
      document.getElementById('guild-edit-desc').value = d.guild.description || '';
      document.getElementById('guild-edit-homepage').value = d.guild.homepage || '';
      document.getElementById('guild-edit-forum').value = d.guild.forum_url || '';
      document.getElementById('guild-edit-board3').value = (d.guild.board_name_3 && d.guild.board_name_3 !== 'Trade') ? d.guild.board_name_3 : '';
      document.getElementById('guild-edit-board4').value = (d.guild.board_name_4 && d.guild.board_name_4 !== 'Strategy') ? d.guild.board_name_4 : '';
      _guildEditOriginal = {
        id: guildId,
        name,
        tag,
        description: d.guild.description || '',
        homepage: d.guild.homepage || '',
        forum_url: d.guild.forum_url || '',
        board_name_3: (d.guild.board_name_3 && d.guild.board_name_3 !== 'Trade') ? d.guild.board_name_3 : '',
        board_name_4: (d.guild.board_name_4 && d.guild.board_name_4 !== 'Strategy') ? d.guild.board_name_4 : ''
      };
      const counter = document.getElementById('guild-edit-counter');
      if (counter) counter.textContent = 1200 - (d.guild.description || '').length;
    }
  });
  document.getElementById('guild-edit-status').textContent = '';
  openModal('guild-edit-modal');
}

function resetGuildEditForm() {
  if (!_guildEditOriginal) return;
  document.getElementById('guild-edit-id').value = _guildEditOriginal.id || '';
  document.getElementById('guild-edit-name').value = _guildEditOriginal.name || '';
  document.getElementById('guild-edit-tag').value = _guildEditOriginal.tag || '';
  document.getElementById('guild-edit-desc').value = _guildEditOriginal.description || '';
  document.getElementById('guild-edit-homepage').value = _guildEditOriginal.homepage || '';
  document.getElementById('guild-edit-forum').value = _guildEditOriginal.forum_url || '';
  document.getElementById('guild-edit-board3').value = _guildEditOriginal.board_name_3 || '';
  document.getElementById('guild-edit-board4').value = _guildEditOriginal.board_name_4 || '';
  document.getElementById('guild-edit-status').textContent = '';
  const counter = document.getElementById('guild-edit-counter');
  if (counter) counter.textContent = 1200 - ((_guildEditOriginal.description || '').length);
}

async function saveGuildEdit() {
  const guildId = document.getElementById('guild-edit-id').value;
  const name = document.getElementById('guild-edit-name').value.trim();
  const tag = document.getElementById('guild-edit-tag').value.trim();
  const description = document.getElementById('guild-edit-desc').value;
  const homepage = document.getElementById('guild-edit-homepage').value.trim();
  const forum_url = document.getElementById('guild-edit-forum').value.trim();
  const board_name_3 = document.getElementById('guild-edit-board3').value.trim();
  const board_name_4 = document.getElementById('guild-edit-board4').value.trim();
  const statusEl = document.getElementById('guild-edit-status');
  if (!name || !tag) { statusEl.innerHTML = '<span class="text-danger">Name and tag required</span>'; return; }
  try {
    const res = await apiFetch(`/api/guilds/${guildId}/edit`, {
      method: 'POST',
      body: JSON.stringify({ name, tag, description, homepage, forum_url, board_name_3, board_name_4 })
    });
    const data = await res.json();
    if (data.success) {
      showSnack('Guild updated!');
      closeModal('guild-edit-modal');
      loadGuild();
    } else {
      statusEl.innerHTML = `<span class="text-danger">${data.detail || 'Failed'}</span>`;
    }
  } catch (e) { statusEl.innerHTML = '<span class="text-danger">Error saving</span>'; }
}

