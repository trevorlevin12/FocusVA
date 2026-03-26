let currentFilter = 'status=pending';
let currentEmailId = null;

// ── SVG icon library ────────────────────────────────────────
const ICONS = {
  send: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>`,
  check: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.25" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`,
  x: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`,
  refresh: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>`,
  sparkle: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3L13.5 8.5L19 10L13.5 11.5L12 17L10.5 11.5L5 10L10.5 8.5Z"/><path d="M19 3L19.75 5.25L22 6L19.75 6.75L19 9L18.25 6.75L16 6L18.25 5.25Z"/><path d="M5 17L5.5 18.5L7 19L5.5 19.5L5 21L4.5 19.5L3 19L4.5 18.5Z"/></svg>`,
  pencil: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>`,
  trash: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>`,
  chevron: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>`,
  inbox: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></svg>`,
};

// ── API helper ──────────────────────────────────────────────
async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Request failed' }));
    throw new Error(err.detail || 'Request failed');
  }
  return res.json();
}

// ── Toast ───────────────────────────────────────────────────
function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.remove('show'), 3000);
}

// ── Helpers ─────────────────────────────────────────────────
function escapeHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function formatDate(str) {
  if (!str) return '';
  const d = new Date(str);
  if (isNaN(d)) return str;
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) + ' ' +
    d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
}

function senderName(sender) {
  const m = sender.match(/^"?([^"<]+)"?\s*</);
  return m ? m[1].trim() : sender;
}

function senderInitials(name) {
  const parts = name.trim().split(/\s+/);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return name.slice(0, 2).toUpperCase();
}

const AVATAR_COLORS = [
  '#5b66f5', '#10a37f', '#d97706',
  '#dc4f4f', '#7c3aed', '#0891b2',
  '#c2410c', '#be185d',
];

function avatarColor(name) {
  const code = (name || ' ').charCodeAt(0);
  return AVATAR_COLORS[code % AVATAR_COLORS.length];
}

function badgeHtml(classification) {
  const label = (classification || '').replace(/_/g, ' ');
  return `<span class="badge badge-${escapeHtml(classification)}">${escapeHtml(label)}</span>`;
}

// ── Collapsible toggle ──────────────────────────────────────
function toggleSection(btn) {
  btn.closest('.collapsible').classList.toggle('collapsed');
}

// ── Auto-resize textarea ────────────────────────────────────
function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = el.scrollHeight + 'px';
}

// ── Two-step confirm helper (replaces native confirm()) ─────
// Usage: confirmAction(buttonEl, label, fn)
// First click → button turns into "Confirm?" with danger styling
// Second click within 3s → executes fn
// Timeout → reverts label and styling
function confirmAction(btn, originalLabel, fn) {
  if (btn._confirming) {
    clearTimeout(btn._confirmTimer);
    btn._confirming = false;
    btn.innerHTML = originalLabel;
    btn.classList.remove('danger');
    fn();
    return;
  }
  btn._confirming = true;
  btn.innerHTML = 'Confirm?';
  btn.classList.add('danger');
  btn._confirmTimer = setTimeout(() => {
    btn._confirming = false;
    btn.innerHTML = originalLabel;
    btn.classList.remove('danger');
  }, 3000);
}

// ── Email List ──────────────────────────────────────────────
async function loadEmails(filter) {
  currentFilter = filter;
  const list = document.getElementById('emailList');
  list.innerHTML = '<div class="loading">Loading...</div>';

  try {
    let emails;
    if (filter === 'spam') {
      const [spam, bids] = await Promise.all([
        api('/emails?classification=vendor_spam'),
        api('/emails?classification=bid_invite'),
      ]);
      emails = [...spam, ...bids].sort(
        (a, b) => new Date(b.received_at) - new Date(a.received_at)
      );
    } else {
      emails = await api('/emails?' + filter);
    }

    if (emails.length === 0) {
      list.innerHTML = '<div class="loading">No emails here</div>';
      return;
    }

    list.innerHTML = emails.map(e => {
      const name = senderName(e.sender);
      const initials = senderInitials(name);
      const color = avatarColor(name);
      const preview = (() => {
        const src = (e.draft_body || e.body || '').replace(/\s+/g, ' ').trim();
        return src.length > 70 ? src.slice(0, 70) + '…' : src;
      })();

      return `
        <div class="email-row${e.id === currentEmailId ? ' active' : ''}"
             data-id="${e.id}"
             onclick="loadDetail(${e.id})">
          <div class="email-avatar" style="background:${color};">${escapeHtml(initials)}</div>
          <div class="email-row-content">
            <div class="email-row-header">
              <span class="email-sender">${escapeHtml(name)}</span>
              <span class="email-time">${formatDate(e.received_at)}</span>
            </div>
            <div class="email-subject">${escapeHtml(e.subject || '(no subject)')}</div>
            <div class="email-meta">
              ${badgeHtml(e.classification)}
              <span class="status-dot status-${escapeHtml(e.status)}"></span>
            </div>
          </div>
        </div>
      `;
    }).join('');
  } catch (err) {
    list.innerHTML = `<div class="loading">Error: ${escapeHtml(err.message)}</div>`;
  }
}

// ── Detail Panel ────────────────────────────────────────────
async function loadDetail(id) {
  currentEmailId = id;
  document.querySelectorAll('.email-row').forEach(r => {
    r.classList.toggle('active', +r.dataset.id === id);
  });

  const panel = document.getElementById('detailPanel');
  panel.innerHTML = '<div class="loading">Loading...</div>';

  try {
    const { email, job_data, draft } = await api(`/emails/${id}`);

    const hasDraft = !!draft;
    const hasJobData = Object.keys(job_data).length > 0;

    // ── Action bar buttons ─────────────────────
    const draftActionButtons = hasDraft
      ? `<button class="btn btn-approve" onclick="approveDraft(${id})">${ICONS.send} Approve &amp; Send</button>
         <button class="btn btn-reject"  onclick="rejectEmail(${id})">${ICONS.x} Reject</button>
         <button class="btn btn-save"    onclick="saveDraft(${id})">Save</button>
         <button class="btn btn-regenerate" onclick="regenerateDraft(${id})" id="regenBtn">${ICONS.sparkle} Regenerate</button>`
      : `<button class="btn btn-reject" onclick="rejectEmail(${id})">${ICONS.x} Reject</button>`;

    // ── Draft section ──────────────────────────
    const draftSection = hasDraft
      ? `<div class="draft-section">
           <div class="draft-section-header">
             <span class="section-title">Draft Response</span>
             <span class="draft-sparkle" title="AI generated">${ICONS.sparkle}</span>
           </div>
           <textarea class="draft-textarea" id="draftBody" oninput="autoResize(this)">${escapeHtml(draft.body)}</textarea>
         </div>`
      : `<div class="draft-section">
           <div class="draft-section-header">
             <span class="section-title">Draft Response</span>
             <span class="draft-sparkle">${ICONS.sparkle}</span>
           </div>
           <p class="draft-placeholder">No draft generated for this email type.</p>
         </div>`;

    // ── Job data collapsible ───────────────────
    const jobCollapsedClass = hasJobData ? '' : ' collapsed';
    const jobChips = hasJobData
      ? Object.entries(job_data).map(([k, v]) =>
          `<span class="chip"><strong>${escapeHtml(k.replace(/_/g, ' '))}:</strong> ${escapeHtml(String(v))}</span>`
        ).join('')
      : '<span style="color:var(--text-3);font-size:13px;">No job data extracted.</span>';

    const jobSection = `
      <div class="collapsible${jobCollapsedClass}">
        <button class="collapsible-header" onclick="toggleSection(this)">
          <span>Job Details</span>
          <span class="chevron">${ICONS.chevron}</span>
        </button>
        <div class="collapsible-body">
          <div class="collapsible-body-inner">
            <div class="chip-grid">${jobChips}</div>
          </div>
        </div>
      </div>
    `;

    // ── Original email collapsible ─────────────
    const emailSection = `
      <div class="collapsible collapsed">
        <button class="collapsible-header" onclick="toggleSection(this)">
          <span>Original Email</span>
          <span class="chevron">${ICONS.chevron}</span>
        </button>
        <div class="collapsible-body">
          <div class="collapsible-body-inner">
            <div class="email-body">${escapeHtml(email.body)}</div>
          </div>
        </div>
      </div>
    `;

    panel.innerHTML = `
      <div class="detail-header">
        <div class="detail-subject">${escapeHtml(email.subject || '(no subject)')}</div>
        <div class="detail-meta">
          <span><span class="detail-meta-label">From</span> ${escapeHtml(email.sender)}</span>
          <span>${formatDate(email.received_at)}</span>
          ${badgeHtml(email.classification)}
          <span class="status-dot status-${escapeHtml(email.status)}"></span>
          <span>${escapeHtml(email.status)}</span>
        </div>
      </div>

      <div class="action-bar">
        ${draftActionButtons}
      </div>

      <div class="detail-body">
        ${draftSection}
        ${jobSection}
        ${emailSection}
      </div>
    `;

    if (hasDraft) {
      const ta = document.getElementById('draftBody');
      if (ta) autoResize(ta);
    }

  } catch (err) {
    panel.innerHTML = `<div class="loading">Error: ${escapeHtml(err.message)}</div>`;
  }
}

// ── Actions ─────────────────────────────────────────────────
async function saveDraft(id) {
  const body = document.getElementById('draftBody').value;
  try {
    await api(`/emails/${id}/draft`, {
      method: 'PUT',
      body: JSON.stringify({ body }),
    });
    showToast('Draft saved');
  } catch (err) {
    showToast('Error: ' + err.message);
  }
}

async function approveDraft(id) {
  const body = document.getElementById('draftBody').value;
  try {
    await api(`/emails/${id}/draft`, { method: 'PUT', body: JSON.stringify({ body }) });
    await api(`/emails/${id}/approve`, { method: 'POST', body: JSON.stringify({ approved_by: 'staff' }) });
    showToast('Email sent');
    await loadEmails(currentFilter);
    document.getElementById('detailPanel').innerHTML =
      `<div class="empty-state"><div class="empty-state-icon">${ICONS.send}</div><p>Email sent successfully.</p></div>`;
    currentEmailId = null;
  } catch (err) {
    showToast('Error: ' + err.message);
  }
}

async function rejectEmail(id) {
  try {
    await api(`/emails/${id}/reject`, { method: 'POST', body: JSON.stringify({}) });
    showToast('Email rejected');
    await loadEmails(currentFilter);
    document.getElementById('detailPanel').innerHTML =
      `<div class="empty-state"><div class="empty-state-icon">${ICONS.x}</div><p>Email rejected.</p></div>`;
    currentEmailId = null;
  } catch (err) {
    showToast('Error: ' + err.message);
  }
}

// ── Tab navigation ──────────────────────────────────────────
document.querySelectorAll('.tab[data-filter]').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    hideAdmin();
    loadEmails(tab.dataset.filter);
    document.getElementById('detailPanel').innerHTML =
      `<div class="empty-state"><div class="empty-state-icon">${ICONS.inbox}</div><p>Select an email to review</p></div>`;
    currentEmailId = null;
  });
});

// ── Regenerate ──────────────────────────────────────────────
async function regenerateDraft(id) {
  const btn = document.getElementById('regenBtn');
  btn.disabled = true;
  btn.innerHTML = `${ICONS.sparkle} Regenerating...`;
  try {
    const result = await api(`/emails/${id}/regenerate`, { method: 'POST' });
    const ta = document.getElementById('draftBody');
    ta.value = result.body;
    autoResize(ta);
    showToast('Draft regenerated');
  } catch (err) {
    showToast('Error: ' + err.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = `${ICONS.sparkle} Regenerate`;
  }
}

// ── Poll ────────────────────────────────────────────────────
async function pollNow() {
  const btn = document.getElementById('refreshBtn');
  btn.disabled = true;
  btn.innerHTML = `${ICONS.refresh} Checking...`;
  try {
    const result = await api('/poll', { method: 'POST' });
    showToast(result.new > 0 ? `${result.new} new email(s) processed` : 'No new emails');
    await loadEmails(currentFilter);
  } catch (err) {
    showToast('Error: ' + err.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = `${ICONS.refresh} Check Now`;
  }
}

// ── Admin ────────────────────────────────────────────────────
function showAdmin() {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelector('[onclick="showAdmin()"]').classList.add('active');
  document.getElementById('emailList').style.display = 'none';
  document.getElementById('detailPanel').style.display = 'none';
  document.getElementById('settingsPanel').style.display = 'none';
  document.getElementById('adminPanel').style.display = 'flex';
  loadJobTypes();
}

function hideAdmin() {
  document.getElementById('emailList').style.display = '';
  document.getElementById('detailPanel').style.display = '';
  document.getElementById('adminPanel').style.display = 'none';
}

async function loadJobTypes() {
  const list = document.getElementById('jobTypeList');
  list.innerHTML = '<div class="loading">Loading...</div>';
  try {
    const types = await api('/admin/job-types');
    if (types.length === 0) {
      list.innerHTML = '<div class="loading">No job types configured.</div>';
      return;
    }
    list.innerHTML = types.map(jt => renderJobType(jt)).join('');
  } catch (err) {
    list.innerHTML = `<div class="loading">Error: ${escapeHtml(err.message)}</div>`;
  }
}

function renderJobType(jt) {
  const questions = jt.questions.map((q, i) => `
    <div class="question-row" id="qrow-${q.id}">
      <span class="q-order">${i + 1}</span>
      <div class="q-content">
        <div class="q-text" id="qtext-${q.id}">${escapeHtml(q.question_text)}</div>
        <div class="q-meta">${escapeHtml(q.field_name)} &middot; ${q.required ? 'Required' : 'Optional'}</div>
      </div>
      <div class="q-actions">
        <button class="btn-icon" onclick="editQuestion(${q.id}, ${jt.id})" title="Edit">${ICONS.pencil}</button>
        <button class="btn-icon" onclick="deleteQuestion(this, ${q.id}, ${jt.id})" title="Delete">${ICONS.trash}</button>
      </div>
    </div>
  `).join('');

  return `
    <div class="job-type-card" id="jtcard-${jt.id}">
      <div class="jt-header">
        <div>
          <div class="jt-name">${escapeHtml(jt.name)}</div>
          <div class="jt-desc">${escapeHtml(jt.description || '')}</div>
        </div>
        <div class="jt-actions">
          <button class="btn btn-save" onclick="deleteJobType(this, ${jt.id})">Delete</button>
        </div>
      </div>
      <div class="questions-list">${questions || '<div class="q-empty">No questions yet.</div>'}</div>
      <div class="add-question-form" id="addq-${jt.id}" style="display:none;">
        <input type="text" id="qtext-new-${jt.id}" placeholder="Question text" />
        <input type="text" id="qfield-new-${jt.id}" placeholder="field_name (snake_case)" />
        <label><input type="checkbox" id="qreq-new-${jt.id}" checked /> Required</label>
        <div class="admin-form-actions">
          <button class="btn btn-approve" onclick="addQuestion(${jt.id})">Add</button>
          <button class="btn btn-save" onclick="document.getElementById('addq-${jt.id}').style.display='none'">Cancel</button>
        </div>
      </div>
      <button class="btn-add-question" onclick="document.getElementById('addq-${jt.id}').style.display='flex'">+ Add Question</button>
    </div>
  `;
}

function showNewJobTypeForm() {
  document.getElementById('newJobTypeForm').style.display = 'flex';
  document.getElementById('newJobTypeName').focus();
}
function hideNewJobTypeForm() {
  document.getElementById('newJobTypeForm').style.display = 'none';
  document.getElementById('newJobTypeName').value = '';
  document.getElementById('newJobTypeDesc').value = '';
}

async function createJobType() {
  const name = document.getElementById('newJobTypeName').value.trim();
  const description = document.getElementById('newJobTypeDesc').value.trim();
  if (!name) { showToast('Name is required'); return; }
  try {
    await api('/admin/job-types', {
      method: 'POST',
      body: JSON.stringify({ name, description }),
    });
    hideNewJobTypeForm();
    showToast('Job type created');
    loadJobTypes();
  } catch (err) {
    showToast('Error: ' + err.message);
  }
}

// Uses two-step confirm instead of native confirm()
async function deleteJobType(btn, id) {
  confirmAction(btn, 'Delete', async () => {
    try {
      await api(`/admin/job-types/${id}`, { method: 'DELETE' });
      showToast('Deleted');
      loadJobTypes();
    } catch (err) {
      showToast('Error: ' + err.message);
    }
  });
}

async function addQuestion(jtId) {
  const text = document.getElementById(`qtext-new-${jtId}`).value.trim();
  const field = document.getElementById(`qfield-new-${jtId}`).value.trim();
  const required = document.getElementById(`qreq-new-${jtId}`).checked;
  if (!text || !field) { showToast('Question text and field name are required'); return; }
  try {
    await api(`/admin/job-types/${jtId}/questions`, {
      method: 'POST',
      body: JSON.stringify({ question_text: text, field_name: field, required }),
    });
    showToast('Question added');
    loadJobTypes();
  } catch (err) {
    showToast('Error: ' + err.message);
  }
}

// Inline edit — replaces text with an input field in-place
function editQuestion(qId, jtId) {
  const textEl = document.getElementById(`qtext-${qId}`);
  if (!textEl || textEl.querySelector('input')) return; // already editing

  const current = textEl.textContent;
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'q-edit-input';
  input.value = current;

  textEl.textContent = '';
  textEl.appendChild(input);
  input.focus();
  input.select();

  const save = async () => {
    const newText = input.value.trim();
    if (!newText || newText === current) {
      textEl.textContent = current;
      return;
    }
    try {
      await api(`/admin/questions/${qId}`, {
        method: 'PUT',
        body: JSON.stringify({ question_text: newText }),
      });
      showToast('Question updated');
      loadJobTypes();
    } catch (err) {
      textEl.textContent = current;
      showToast('Error: ' + err.message);
    }
  };

  input.addEventListener('blur', save);
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
    if (e.key === 'Escape') { textEl.textContent = current; }
  });
}

// Uses two-step confirm instead of native confirm()
async function deleteQuestion(btn, qId, jtId) {
  confirmAction(btn, ICONS.trash, async () => {
    try {
      await api(`/admin/questions/${qId}`, { method: 'DELETE' });
      showToast('Question deleted');
      loadJobTypes();
    } catch (err) {
      showToast('Error: ' + err.message);
    }
  });
}

// ── Auth ─────────────────────────────────────────────────────
async function checkAuthStatus() {
  const params = new URLSearchParams(window.location.search);
  const authError = params.get('auth_error');
  if (authError) {
    const banner = document.getElementById('authBanner');
    const msg = document.getElementById('authBannerMsg');
    banner.classList.add('error');
    banner.style.display = 'flex';
    msg.textContent = 'Gmail connection failed: ' + decodeURIComponent(authError);
    const url = new URL(window.location);
    url.searchParams.delete('auth_error');
    window.history.replaceState({}, '', url);
    return;
  }
  try {
    const status = await api('/auth/status');
    const banner = document.getElementById('authBanner');
    banner.style.display = status.connected ? 'none' : 'flex';
  } catch (_) { /* non-fatal */ }
}

// ── Settings ─────────────────────────────────────────────────
function showSettings() {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelector('[onclick="showSettings()"]').classList.add('active');
  document.getElementById('emailList').style.display = 'none';
  document.getElementById('detailPanel').style.display = 'none';
  document.getElementById('adminPanel').style.display = 'none';
  document.getElementById('settingsPanel').style.display = 'block';
  loadSettingsStatus();
}

function hideSettings() {
  document.getElementById('settingsPanel').style.display = 'none';
}

async function loadSettingsStatus() {
  const statusEl = document.getElementById('gmailStatus');
  try {
    const res = await api('/auth/status');
    if (res.connected) {
      statusEl.textContent = 'Connected';
      statusEl.className = 'settings-status connected';
    } else {
      statusEl.innerHTML = 'Not connected — <a href="/auth/login">Connect Gmail</a>';
      statusEl.className = 'settings-status disconnected';
    }
  } catch (_) {
    statusEl.textContent = 'Unable to check status';
    statusEl.className = 'settings-status';
  }
}

let _crawlPollInterval = null;

async function startCrawl() {
  const since = document.getElementById('crawlSince').value;
  if (!since) { showToast('Please select a date first'); return; }
  const btn = document.getElementById('crawlBtn');
  btn.disabled = true;
  const progress = document.getElementById('crawlProgress');
  const progressText = document.getElementById('crawlProgressText');
  progress.style.display = 'block';
  progressText.textContent = 'Starting import...';
  try {
    const res = await api('/admin/crawl-history', {
      method: 'POST',
      body: JSON.stringify({ since_date: since }),
    });
    const key = res.status_key;
    if (_crawlPollInterval) clearInterval(_crawlPollInterval);
    _crawlPollInterval = setInterval(async () => {
      try {
        const status = await api(`/admin/crawl-status?key=${key}`);
        progressText.textContent =
          `${status.indexed} of ${status.total} indexed, ${status.skipped} skipped, ${status.errors} errors`;
        if (status.done) {
          clearInterval(_crawlPollInterval);
          _crawlPollInterval = null;
          btn.disabled = false;
          showToast('Import complete');
        }
      } catch (_) {
        clearInterval(_crawlPollInterval);
        btn.disabled = false;
      }
    }, 2000);
  } catch (err) {
    showToast('Error: ' + err.message);
    btn.disabled = false;
    progress.style.display = 'none';
  }
}

// ── Boot ─────────────────────────────────────────────────────
checkAuthStatus();
loadEmails(currentFilter);
