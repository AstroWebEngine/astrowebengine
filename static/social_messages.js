/* ============================================================
   AstroWebEngine - Frontend (social_messages.js)
   Messages, savebox, contacts, and player/guild lookup flows
   Split from social.js for easier maintenance
   ============================================================ */
let _msgTab = 'inbox';
let _expandedMsgId = null;
let _expandedSentMsgId = null;

function switchMsgTab(tab) {
  _msgTab = tab;
  document.querySelectorAll('#msg-tab-bar a').forEach(a => {
    a.classList.toggle('active', a.textContent.trim().toLowerCase() === tab);
  });
  if (tab === 'sentbox') loadSentMessages();
  else if (tab === 'savebox') loadSavedMessages();
  else if (tab === 'contacts') loadContacts();
  else loadMessages();
}

async function loadMessages() {
  const container = document.getElementById('messages-content');
  try {
    const res = await apiFetch('/api/messages');
    if (!res) return;
    const msgs = await res.json();
    if (!msgs.length) { container.innerHTML = '<div style="text-align:center;font-size:14px;margin-bottom:8px;color:var(--text-bright);"><b>I</b>nbox</div><p class="text-dim" style="text-align:center;padding:16px;font-size:12px;">Inbox is empty.</p>'; return; }
    let html = `<div style="text-align:center;font-size:14px;margin-bottom:8px;color:var(--text-bright);"><b>I</b>nbox</div>`;
    html += '<table class="data-table" style="width:100%;font-size:12px;"><thead><tr><th style="width:20px;"></th><th>From</th><th></th><th style="text-align:right;">Date</th></tr></thead><tbody>';
    for (const m of msgs) {
      const unread = !m.is_read;
      const dateStr = fmtDateTime(m.created_at);
      const bold = unread ? 'font-weight:bold;' : '';
      html += `<tr style="cursor:pointer;${bold}" onclick="toggleMsgExpand(${m.id})">
        <td><input type="checkbox" class="msg-check" value="${m.id}" onclick="event.stopPropagation()"/></td>
        <td class="text-bright">${escStr(m.sender)}</td>
        <td><a href="#" class="text-dim" onclick="event.stopPropagation();copyToSavebox(${m.id});return false;" style="font-size:11px;">Copy Savebox</a></td>
        <td class="text-dim" style="text-align:right;white-space:nowrap;">${dateStr}</td>
      </tr>`;
      const expanded = _expandedMsgId === m.id;
      html += `<tr id="msg-expand-${m.id}" style="display:${expanded?'table-row':'none'};"><td></td><td colspan="3" style="padding:8px 4px;border-top:none;">
        <div class="text-dim" style="font-size:11px;">Loading...</div></td></tr>`;
    }
    html += '</tbody></table>';
    html += `<div style="text-align:center;margin-top:8px;font-size:11px;">
      <button class="btn btn-danger btn-sm" onclick="deleteSelectedMessages()">Delete selected</button>
      <button class="btn btn-danger btn-sm" onclick="deleteAllMessages()" style="margin-left:8px;">Delete all</button>
      <span class="text-dim" style="margin-left:12px;">viewing ${msgs.length} messages</span></div>`;
    html += '<div class="text-dim" style="text-align:center;font-size:10px;margin-top:4px;">Messages more than 5 days old will be automatically deleted.</div>';
    container.innerHTML = html;
    if (_expandedMsgId) loadMsgBody(_expandedMsgId);
  } catch (e) { console.error(e); }
}

async function loadSentMessages() {
  const container = document.getElementById('messages-content');
  try {
    const res = await apiFetch('/api/messages/sent');
    if (!res) { container.innerHTML = '<p class="text-dim" style="text-align:center;padding:16px;font-size:12px;">Sentbox is empty.</p>'; return; }
    const msgs = await res.json();
    if (!msgs.length) { container.innerHTML = '<p class="text-dim" style="text-align:center;padding:16px;font-size:12px;">Sentbox is empty.</p>'; return; }
    let html = '<table class="data-table" style="width:100%;font-size:12px;"><thead><tr><th>To</th><th>Subject</th><th style="text-align:right;">Date</th></tr></thead><tbody>';
    for (const m of msgs) {
      const dateStr = fmtDateTime(m.created_at);
      html += `<tr style="cursor:pointer;" onclick="toggleSentMsgExpand(${m.id})">
        <td class="text-bright">${escStr(m.recipient || '?')}</td>
        <td>${escStr(m.subject || '(no subject)')}</td>
        <td class="text-dim" style="text-align:right;">${dateStr}</td>
      </tr>`;
      const expanded = _expandedSentMsgId === m.id;
      html += `<tr id="sent-expand-${m.id}" style="display:${expanded?'table-row':'none'};"><td colspan="3" style="padding:8px 4px;border-top:none;">
        <div style="white-space:pre-wrap;font-size:12px;">${escStr(m.body || '')}</div></td></tr>`;
    }
    html += '</tbody></table>';
    container.innerHTML = html;
  } catch (e) { container.innerHTML = '<p class="text-dim" style="text-align:center;padding:16px;font-size:12px;">Sentbox is empty.</p>'; }
}

function toggleSentMsgExpand(msgId) {
  if (_expandedSentMsgId === msgId) {
    document.getElementById(`sent-expand-${msgId}`).style.display = 'none';
    _expandedSentMsgId = null;
    return;
  }
  if (_expandedSentMsgId) {
    const prev = document.getElementById(`sent-expand-${_expandedSentMsgId}`);
    if (prev) prev.style.display = 'none';
  }
  _expandedSentMsgId = msgId;
  const row = document.getElementById(`sent-expand-${msgId}`);
  if (row) row.style.display = 'table-row';
}

function renderMsgCompose(prefillTo, prefillSubject) {
  const container = document.getElementById('messages-content');
  const toName = prefillTo || '';
  const subjVal = prefillSubject || '';
  container.innerHTML = `<div style="text-align:center;font-size:14px;margin-bottom:4px;color:var(--text-bright);"><b>N</b>ew Message</div>
    <div style="text-align:center;font-size:12px;margin-bottom:8px;color:var(--text-dim);">To: ${escStr(toName)}</div>
    <input type="hidden" id="msg-to" value="${escStr(toName)}" />
    ${subjVal ? `<div style="text-align:center;font-size:12px;margin-bottom:8px;"><input type="text" id="msg-subject" maxlength="200" value="${escStr(subjVal)}" class="msg-subject-input" placeholder="Subject"></div>` : '<input type="hidden" id="msg-subject" value="" />'}
    <div style="display:flex;gap:12px;padding:0 12px;">
      <div style="min-width:120px;font-size:11px;color:var(--text-dim);padding-top:4px;">
        <div style="font-weight:bold;margin-bottom:4px;">BBCode</div>
        <div>[b] - [u] - [i] - [s]</div>
        <div>[code] [quote]</div>
        <div>[url] [url=]</div>
        <div>[color=]</div>
      </div>
      <div style="flex:1;">
        <textarea id="msg-body" rows="12" maxlength="5000" style="width:100%;font-size:12px;" placeholder="Write your message..." oninput="updateMsgCharCount()"></textarea>
        <div style="text-align:right;font-size:11px;color:var(--text-dim);" id="msg-char-count">(chars left: 5000)</div>
      </div>
    </div>
    <div style="text-align:center;margin-top:8px;">
      <button class="btn btn-primary btn-sm" onclick="sendMessage()">Send</button>
      <button class="btn btn-ghost btn-sm" onclick="switchMsgTab('inbox')" style="margin-left:8px;">Cancel</button>
    </div>
    <div id="msg-send-status" style="text-align:center;margin-top:6px;font-size:11px;"></div>`;
}

function updateMsgCharCount() {
  const body = document.getElementById('msg-body');
  const counter = document.getElementById('msg-char-count');
  if (body && counter) counter.textContent = `(chars left: ${5000 - body.value.length})`;
}

async function toggleMsgExpand(msgId) {
  if (_expandedMsgId === msgId) {
    document.getElementById(`msg-expand-${msgId}`).style.display = 'none';
    _expandedMsgId = null;
    return;
  }
  if (_expandedMsgId) {
    const prev = document.getElementById(`msg-expand-${_expandedMsgId}`);
    if (prev) prev.style.display = 'none';
  }
  _expandedMsgId = msgId;
  const row = document.getElementById(`msg-expand-${msgId}`);
  if (row) { row.style.display = 'table-row'; loadMsgBody(msgId); }
}

async function loadMsgBody(msgId) {
  try {
    await apiFetch(`/api/messages/${msgId}/read`, { method: 'POST' });
    const res = await apiFetch('/api/messages');
    if (!res) return;
    const msgs = await res.json();
    const msg = msgs.find(m => m.id === msgId);
    if (!msg) return;
    const row = document.getElementById(`msg-expand-${msgId}`);
    if (row) {
      const cell = row.querySelector('td:last-child');
      const sender = escStr(msg.sender || '');
      const subj = escStr(msg.subject || '');
      const isBattleReport = (msg.subject || '').startsWith('Battle Report');
      const boardLink = isBattleReport ? `&nbsp;|&nbsp; <a href="#" class="text-accent" onclick="copyMsgToBoard(${msgId});return false;">Copy to Board</a>` : '';
      cell.innerHTML = `<div style="white-space:pre-wrap;font-size:12px;">${escStr(msg.body || '')}</div>
        <div style="margin-top:6px;font-size:11px;">
          <a href="#" class="text-accent" onclick="renderMsgCompose('${sender}','Re: ${subj}');return false;">Reply</a>${boardLink}
          &nbsp;|&nbsp; <a href="#" class="text-accent" onclick="copyToSavebox(${msgId});return false;">Copy Savebox</a>
          &nbsp;|&nbsp; <a href="#" class="text-dim" onclick="deleteMessage(${msgId});return false;">Delete</a>
        </div>`;
    }
    updateUnreadCount();
    // Update the row styling to not be bold anymore
    const mainRow = row ? row.previousElementSibling : null;
    if (mainRow) mainRow.style.fontWeight = '';
  } catch (e) { console.error(e); }
}

async function sendMessage() {
  const to = document.getElementById('msg-to').value.trim();
  const subject = document.getElementById('msg-subject').value.trim();
  const body = document.getElementById('msg-body').value.trim();
  const statusEl = document.getElementById('msg-send-status');
  if (!to || !body) { statusEl.textContent = 'Recipient and message required'; statusEl.className = 'text-danger'; return; }
  try {
    const res = await apiFetch('/api/messages', {
      method: 'POST', body: JSON.stringify({ recipient: to, subject, body })
    });
    const data = await res.json();
    if (data.success) {
      statusEl.textContent = 'Message sent!';
      statusEl.className = 'text-success';
      document.getElementById('msg-to').value = '';
      document.getElementById('msg-subject').value = '';
      document.getElementById('msg-body').value = '';
      setTimeout(() => { loadMessages(); }, 1500);
    } else {
      statusEl.textContent = data.detail || 'Failed';
      statusEl.className = 'text-danger';
    }
  } catch (e) { statusEl.textContent = 'Error'; statusEl.className = 'text-danger'; }
}

async function deleteSelectedMessages() {
  const checks = document.querySelectorAll('.msg-check:checked');
  if (!checks.length) return;
  for (const cb of checks) {
    try { await apiFetch(`/api/messages/${cb.value}`, { method: 'DELETE' }); } catch (e) {}
  }
  _expandedMsgId = null;
  loadMessages();
  updateUnreadCount();
}

async function deleteMessage(msgId) {
  try {
    await apiFetch(`/api/messages/${msgId}`, { method: 'DELETE' });
    _expandedMsgId = null;
    loadMessages();
    updateUnreadCount();
  } catch (e) {}
}

async function deleteAllMessages() {
  if (!confirm('Delete all inbox messages (except saved)?')) return;
  try {
    await apiFetch('/api/messages/delete-all', { method: 'POST' });
    _expandedMsgId = null;
    loadMessages();
    updateUnreadCount();
  } catch (e) {}
}

async function copyToSavebox(msgId) {
  try {
    await apiFetch(`/api/messages/${msgId}/save`, { method: 'POST' });
    showSnack('Copied to Savebox');
  } catch (e) {}
}

async function copyMsgToBoard(msgId) {
  try {
    const res = await apiFetch(`/api/messages/${msgId}/copy-to-board`, { method: 'POST' });
    const data = await res.json();
    if (data.success) showSnack('Battle report posted to guild board');
    else showSnack(data.detail || 'Failed');
  } catch (e) { showSnack('You must be in a guild to use this feature.'); }
}

async function loadSavedMessages() {
  const container = document.getElementById('messages-content');
  try {
    const res = await apiFetch('/api/messages/saved');
    if (!res) return;
    const msgs = await res.json();
    let html = `<div style="text-align:center;font-size:14px;margin-bottom:8px;color:var(--text-bright);"><b>S</b>avebox</div>`;
    if (!msgs.length) {
      html += '<p class="text-dim" style="text-align:center;padding:16px;font-size:12px;">Savebox is empty. Use "Copy Savebox" on inbox messages to save them here.</p>';
      container.innerHTML = html;
      return;
    }
    html += '<table class="data-table" style="width:100%;font-size:12px;"><thead><tr><th>From</th><th></th><th style="text-align:right;">Date</th></tr></thead><tbody>';
    for (const m of msgs) {
      const dateStr = fmtDateTime(m.created_at);
      html += `<tr style="cursor:pointer;" onclick="toggleMsgExpand(${m.id})">
        <td class="text-bright">${escStr(m.sender)}</td>
        <td></td>
        <td class="text-dim" style="text-align:right;white-space:nowrap;">${dateStr}</td>
      </tr>`;
      const expanded = _expandedMsgId === m.id;
      html += `<tr id="msg-expand-${m.id}" style="display:${expanded?'table-row':'none'};"><td colspan="3" style="padding:8px 4px;border-top:none;">
        <div style="white-space:pre-wrap;font-size:12px;">${escStr(m.body || '')}</div></td></tr>`;
    }
    html += '</tbody></table>';
    container.innerHTML = html;
  } catch (e) { console.error(e); }
}

async function updateUnreadCount() {
  try {
    const res = await apiFetch('/api/messages/unread-count');
    if (!res) return;
    const d = await res.json();
    const badge = document.getElementById('msg-count-badge');
    const hudMsg = document.getElementById('hud-messages');
    const notifBadge = document.getElementById('notif-badge');
    if (badge) {
      if (d.count > 0) { badge.textContent = d.count; badge.style.display = 'inline'; }
      else { badge.style.display = 'none'; }
    }
    if (hudMsg) hudMsg.textContent = d.count > 0 ? `${d.count} New` : 'Messages';
    if (notifBadge) {
      if (d.count > 0) { notifBadge.textContent = d.count > 9 ? '9+' : d.count; notifBadge.style.display = 'inline-block'; }
      else { notifBadge.style.display = 'none'; }
    }
  } catch (e) {}
}

// ============================================================
// CONTACTS
// ============================================================

let _contactAddedMsg = '';

async function loadContacts() {
  const container = document.getElementById('messages-content');
  try {
    const res = await apiFetch('/api/contacts');
    if (!res) return;
    const contacts = await res.json();

    let html = '';
    if (_contactAddedMsg) {
      html += `<div style="text-align:center;font-size:12px;color:var(--text-bright);margin-bottom:4px;">${_contactAddedMsg}</div>`;
      _contactAddedMsg = '';
    }

    html += `<div style="text-align:center;font-size:14px;margin-bottom:8px;color:var(--text-bright);"><b>C</b>ontacts</div>`;

    if (!contacts.length) {
      html += '<p class="text-dim" style="text-align:center;font-size:12px;margin-bottom:12px;">Your contacts list is empty</p>';
    } else {
      html += '<table class="data-table" style="width:100%;font-size:12px;margin-bottom:4px;"><thead><tr><th>ID</th><th>Player</th><th>Msg</th><th>Comment</th><th>Remove</th></tr></thead><tbody>';
      for (const c of contacts) {
        html += `<tr>
          <td class="text-dim">${c.id}</td>
          <td><a href="#" class="text-accent" onclick="showPlayerProfileByName('${escAttr(c.username)}');return false;">${escStr(c.username)}</a></td>
          <td><a href="#" class="text-accent" onclick="msgContact('${escAttr(c.username)}');return false;">Msg</a></td>
          <td><input type="text" class="contact-comment" data-id="${c.id}" value="${escStr(c.note || '')}" maxlength="100" style="width:100%;font-size:11px;"></td>
          <td><a href="#" class="text-dim" onclick="removeContact(${c.id});return false;">Remove</a></td>
        </tr>`;
      }
      html += '</tbody></table>';
      html += `<div style="text-align:center;margin-bottom:12px;"><button class="btn btn-primary btn-sm" onclick="updateAllContacts()">Update All</button></div>`;
    }

    // Search section
    html += `<table class="data-table" style="width:100%;font-size:12px;">
      <tr>
        <td style="text-align:right;white-space:nowrap;padding:6px 8px;"><b>Search player (Id or nickname):</b></td>
        <td style="padding:6px 4px;"><input type="text" id="contact-search-player" style="width:100%;" onkeydown="if(event.key==='Enter')searchPlayer()"></td>
        <td style="padding:6px 4px;width:60px;"><a href="#" class="text-bright" onclick="searchPlayer();return false;" style="font-weight:bold;">Submit</a></td>
      </tr>
      <tr>
        <td style="text-align:right;white-space:nowrap;padding:6px 8px;"><b>Search guild (Id, tag, or name):</b></td>
        <td style="padding:6px 4px;"><input type="text" id="contact-search-guild" style="width:100%;" onkeydown="if(event.key==='Enter')searchGuild()"></td>
        <td style="padding:6px 4px;width:60px;"><a href="#" class="text-bright" onclick="searchGuild();return false;" style="font-weight:bold;">Submit</a></td>
      </tr>
    </table>`;
    html += '<div id="contact-search-results" style="margin-top:8px;"></div>';

    container.innerHTML = html;
  } catch (e) { console.error(e); }
}

async function updateAllContacts() {
  const inputs = document.querySelectorAll('.contact-comment');
  for (const inp of inputs) {
    const id = inp.dataset.id;
    const note = inp.value.trim();
    try {
      await apiFetch(`/api/contacts/${id}`, {
        method: 'PUT', body: JSON.stringify({ note })
      });
    } catch (e) {}
  }
  showSnack('Contacts updated');
}

async function showPlayerProfileByName(username) {
  // Search by name then show profile
  try {
    const res = await apiFetch(`/api/contacts/search-player?q=${encodeURIComponent(username)}`);
    const data = await res.json();
    const match = data.find(p => p.username === username);
    if (match) showPlayerProfile(match.id);
  } catch (e) {}
}

async function searchPlayer() {
  const query = (document.getElementById('contact-search-player').value || '').trim();
  const resultsEl = document.getElementById('contact-search-results');
  if (!resultsEl || !query) return;
  resultsEl.innerHTML = '<p class="text-dim" style="padding:8px;font-size:12px;">Searching...</p>';
  try {
    const res = await apiFetch(`/api/contacts/search-player?q=${encodeURIComponent(query)}`);
    const data = await res.json();
    if (!data.length) {
      resultsEl.innerHTML = '<p class="text-dim" style="padding:8px;font-size:12px;">No players found.</p>';
      return;
    }
    let html = '<div style="padding:8px;font-size:12px;"><b>Player(s) found:</b></div>';
    for (const p of data) {
      const display = p.guild_tag ? `[${escStr(p.guild_tag)}] ${escStr(p.username)}` : escStr(p.username);
      html += `<div style="padding:4px 16px;font-size:12px;"><a href="#" class="text-accent" onclick="showPlayerProfile(${p.id});return false;">${display}</a> &nbsp; <span class="text-dim">(#${p.id})</span></div>`;
    }
    resultsEl.innerHTML = html;
  } catch (e) { resultsEl.innerHTML = '<p class="text-dim" style="padding:8px;font-size:12px;">Error searching.</p>'; }
}

async function searchGuild() {
  const query = (document.getElementById('contact-search-guild').value || '').trim();
  const resultsEl = document.getElementById('contact-search-results');
  if (!resultsEl || !query) return;
  resultsEl.innerHTML = '<p class="text-dim" style="padding:8px;font-size:12px;">Searching...</p>';
  try {
    const res = await apiFetch(`/api/contacts/search-guild?q=${encodeURIComponent(query)}`);
    const data = await res.json();
    if (!data.length) {
      resultsEl.innerHTML = '<p class="text-dim" style="padding:8px;font-size:12px;">No guilds found.</p>';
      return;
    }
    let html = '<div style="padding:8px;font-size:12px;"><b>Guild(s) found:</b></div>';
    for (const g of data) {
      html += `<div style="padding:4px 16px;font-size:12px;"><a href="#" class="text-accent" onclick="viewGuildProfile(${g.id});return false;">[${escStr(g.tag)}] ${escStr(g.name)}</a> &nbsp; <span class="text-dim">(${g.member_count} members)</span></div>`;
    }
    resultsEl.innerHTML = html;
  } catch (e) { resultsEl.innerHTML = '<p class="text-dim" style="padding:8px;font-size:12px;">Error searching.</p>'; }
}

async function addContactById(userId) {
  try {
    const res = await apiFetch('/api/contacts', {
      method: 'POST', body: JSON.stringify({ user_id: userId })
    });
    const data = await res.json();
    if (data.success) {
      _contactAddedMsg = 'Contact Added';
      switchMsgTab('contacts');
    }
    else showSnack(data.detail || 'Already in contacts');
  } catch (e) { showSnack('Could not add contact'); }
}

async function viewGuildProfile(guildId) {
  try {
    const res = await apiFetch(`/api/guilds/${guildId}/view`);
    const data = await res.json();
    _guildPublicProfile = mergeGuildDirectoryMeta(data);
    _guildInfoSlot = 1;
    _guildInfoEditing = false;
    _guildInfoPreview = false;
    _guildInfoDraft = null;
    switchTab('guild');
    renderPublicGuildProfile(_guildPublicProfile);
    renderGuildMembers(_guildPublicProfile);
    const membersPanel = document.getElementById('guild-members-panel');
    if (membersPanel) membersPanel.style.display = '';
    const guildPanel = document.getElementById('guild-my');
    if (guildPanel) guildPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (e) {
    showSnack('Error loading guild');
  }
}

async function showPlayerProfile(playerId) {
  const container = document.getElementById('messages-content');
  if (!container) return;
  container.innerHTML = '<p class="text-dim" style="text-align:center;padding:16px;font-size:12px;">Loading...</p>';
  try {
    const res = await apiFetch(`/api/contacts/search-player?q=${playerId}`);
    const data = await res.json();
    if (!data.length) { container.innerHTML = '<p class="text-dim" style="text-align:center;padding:16px;">Player not found.</p>'; return; }
    const p = data[0];
    const display = p.guild_tag ? `[${escStr(p.guild_tag)}] ${escStr(p.username)}` : escStr(p.username);

    let html = `<div style="text-align:center;font-size:14px;margin-bottom:12px;color:var(--text-bright);"><b>P</b>layer Profile</div>`;
    html += `<table class="data-table" style="width:auto;margin:0 auto;font-size:12px;">
      <tr><td style="text-align:right;padding:4px 12px;"><b>Nick</b></td><td style="padding:4px 12px;">${escStr(p.username)}</td></tr>
      <tr><td style="text-align:right;padding:4px 12px;"><b>Player Id</b></td><td style="padding:4px 12px;">${p.id}</td></tr>`;
    if (p.guild_tag) {
      html += `<tr><td style="text-align:right;padding:4px 12px;"><b>Guild</b></td><td style="padding:4px 12px;">[${escStr(p.guild_tag)}]</td></tr>`;
    }
    html += '</table>';

    html += `<div style="text-align:center;margin-top:16px;font-size:12px;">
      <div style="margin:6px 0;"><a href="#" class="text-accent" onclick="msgContact('${escAttr(p.username)}');return false;">Send a Message</a></div>
      <div style="margin:6px 0;"><a href="#" class="text-accent" onclick="addContactById(${p.id});return false;">Add player to Contacts</a></div>
      <div style="margin:6px 0;"><a href="#" class="text-accent" onclick="_playerReportId='${p.id}';_scannersTab='player';loadScanners();return false;">List bases and fleets</a></div>
      <div style="margin:6px 0;"><a href="#" class="text-dim" style="cursor:not-allowed;">Block messages from this player</a></div>
      <div style="margin:6px 0;"><a href="#" class="text-dim" style="cursor:not-allowed;">Report this player profile</a></div>
    </div>`;

    html += `<div style="text-align:center;margin-top:16px;"><a href="#" class="text-dim" onclick="switchMsgTab('contacts');return false;" style="font-size:11px;">&laquo; Back to Contacts</a></div>`;

    container.innerHTML = html;
  } catch (e) { container.innerHTML = '<p class="text-dim" style="text-align:center;padding:16px;">Error loading profile.</p>'; }
}

async function addContactFromMsg(username) {
  try {
    const res = await apiFetch('/api/contacts', {
      method: 'POST', body: JSON.stringify({ username, note: '' })
    });
    const data = await res.json();
    if (data.success) showSnack(`${username} added to contacts`);
    else showSnack(data.detail || 'Already in contacts');
  } catch (e) { showSnack('Could not add contact'); }
}

function msgContact(username) {
  _msgTab = 'inbox';
  document.querySelectorAll('#msg-tab-bar a').forEach(a => {
    a.classList.toggle('active', a.textContent.trim().toLowerCase() === 'inbox');
  });
  renderMsgCompose(username);
}

async function removeContact(contactId) {
  try {
    await apiFetch(`/api/contacts/${contactId}`, { method: 'DELETE' });
    loadContacts();
  } catch (e) {}
}

