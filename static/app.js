let currentFilter = 'status=pending';
let currentEmailId = null;

// ── API helper ─────────────────────────────────────────────
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

// ── Toast ──────────────────────────────────────────────────
function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.remove('show'), 3000);
}

// ── Helpers ────────────────────────────────────────────────
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

function badgeHtml(classification) {
  const label = (classification || '').replace(/_/g, ' ');
  return `<span class="badge badge-${escapeHtml(classification)}">${escapeHtml(label)}</span>`;
}

// ── Email List ─────────────────────────────────────────────
async function loadEmails(filter) {
  currentFilter = filter;
  const list = document.getElementById('emailList');
  list.innerHTML = '<div class="loading">Loading...</div>';

  try {
    let emails;
    if (filter === 'spam') {
      // Fetch both spam labels, merge, sort
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

    list.innerHTML = emails.map(e => `
      <div class="email-row${e.id === currentEmailId ? ' active' : ''}"
           data-id="${e.id}"
           onclick="loadDetail(${e.id})">
        <div class="email-row-header">
          <span class="email-sender">${escapeHtml(senderName(e.sender))}</span>
          <span class="email-time">${formatDate(e.received_at)}</span>
        </div>
        <div class="email-subject">${escapeHtml(e.subject || '(no subject)')}</div>
        <div class="email-meta">
          ${badgeHtml(e.classification)}
          <span class="status-dot status-${escapeHtml(e.status)}"></span>
        </div>
      </div>
    `).join('');
  } catch (err) {
    list.innerHTML = `<div class="loading">Error: ${escapeHtml(err.message)}</div>`;
  }
}

// ── Detail Panel ───────────────────────────────────────────
async function loadDetail(id) {
  currentEmailId = id;
  document.querySelectorAll('.email-row').forEach(r => {
    r.classList.toggle('active', +r.dataset.id === id);
  });

  const panel = document.getElementById('detailPanel');
  panel.innerHTML = '<div class="loading">Loading...</div>';

  try {
    const { email, job_data, draft } = await api(`/emails/${id}`);

    const jobHtml = Object.keys(job_data).length > 0
      ? `<div class="section">
           <div class="section-title">Extracted Job Details</div>
           <div class="job-data-grid">
             ${Object.entries(job_data).map(([k, v]) => `
               <div class="job-field">
                 <label>${escapeHtml(k.replace(/_/g, ' '))}</label>
                 <span>${escapeHtml(String(v))}</span>
               </div>
             `).join('')}
           </div>
         </div>`
      : '';

    const draftHtml = draft
      ? `<div class="section">
           <div class="section-title">AI Draft Response</div>
           <textarea class="draft-textarea" id="draftBody">${escapeHtml(draft.body)}</textarea>
           <div class="actions">
             <button class="btn btn-approve" onclick="approveDraft(${id})">Approve &amp; Send</button>
             <button class="btn btn-reject"  onclick="rejectEmail(${id})">Reject</button>
             <button class="btn btn-save"    onclick="saveDraft(${id})">Save Edits</button>
           </div>
         </div>`
      : `<div class="section">
           <div class="section-title">Draft</div>
           <p style="color:#94a3b8;font-size:14px;">
             No draft generated for this email type.
           </p>
         </div>`;

    panel.innerHTML = `
      <div class="detail-header">
        <div class="detail-subject">${escapeHtml(email.subject || '(no subject)')}</div>
        <div class="detail-meta">
          <span>From: ${escapeHtml(email.sender)}</span>
          <span>${formatDate(email.received_at)}</span>
          ${badgeHtml(email.classification)}
          <span class="status-dot status-${escapeHtml(email.status)}"></span>
          <span>${escapeHtml(email.status)}</span>
        </div>
      </div>
      <div class="section">
        <div class="section-title">Original Email</div>
        <div class="email-body">${escapeHtml(email.body)}</div>
      </div>
      ${jobHtml}
      ${draftHtml}
    `;
  } catch (err) {
    panel.innerHTML = `<div class="loading">Error: ${escapeHtml(err.message)}</div>`;
  }
}

// ── Actions ────────────────────────────────────────────────
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
    showToast('Email sent!');
    await loadEmails(currentFilter);
    document.getElementById('detailPanel').innerHTML =
      '<div class="empty-state"><p>Email sent successfully.</p></div>';
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
      '<div class="empty-state"><p>Email rejected.</p></div>';
    currentEmailId = null;
  } catch (err) {
    showToast('Error: ' + err.message);
  }
}

// ── Tab navigation ─────────────────────────────────────────
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    loadEmails(tab.dataset.filter);
    document.getElementById('detailPanel').innerHTML =
      '<div class="empty-state"><p>Select an email to review</p></div>';
    currentEmailId = null;
  });
});

// ── Boot ───────────────────────────────────────────────────
loadEmails(currentFilter);
