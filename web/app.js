/**
 * Zen Data Protsk - Automation Dashboard Client Logic
 */

// Application State
const state = {
  stats: {
    total_completed: 0,
    total_unfilled: 0,
    total_resolved: 0,
    last_completed_qr: 0,
    next_qr: 1
  },
  completedPage: 1,
  completedLimit: 25,
  completedTotal: 0,
  completedSearch: '',
  unfilledStatusFilter: '',
  autoRefreshTimer: null,
  autoRefreshSec: 10,
  // Verification State
  verifyPage: 1,
  verifyLimit: 25,
  verifyTotal: 0,
  verifyFilter: '',
  verifySearch: '',
  verifyStats: {
    total_verified: 0,
    avg_accuracy: 0.0,
    perfect_count: 0,
    minor_count: 0,
    low_count: 0,
    flagged_qrs: []
  },
  isVerifying: false,
  verifyProgressInterval: null
};

// ==========================================================================
// Initialization
// ==========================================================================

document.addEventListener('DOMContentLoaded', () => {
  setupTabs();
  setupRefreshControls();
  setupSearch();
  setupAudioBeep();
  setupExportDropdown();
  setupManualForm();
  setupModals();
  setupVerification();

  // Initial Load
  fetchAllData();
  startAutoRefresh();
});

// ==========================================================================
// API Interaction Functions
// ==========================================================================

async function fetchStats() {
  try {
    const res = await fetch('/api/stats');
    if (!res.ok) throw new Error('Failed to fetch stats');
    const data = await res.json();
    state.stats = data;
    renderStats();
    updateConnectionStatus(true);
  } catch (err) {
    console.error('Stats fetch error:', err);
    updateConnectionStatus(false);
  }
}

async function fetchCompletedRecords() {
  try {
    const params = new URLSearchParams({
      page: state.completedPage,
      limit: state.completedLimit,
      search: state.completedSearch
    });
    const res = await fetch(`/api/records?${params.toString()}`);
    if (!res.ok) throw new Error('Failed to fetch completed records');
    const data = await res.json();
    state.completedTotal = data.total;
    renderCompletedTable(data.records);
    renderCompletedPagination(data.total);
  } catch (err) {
    console.error('Completed records fetch error:', err);
    document.getElementById('completedTableBody').innerHTML = `
      <tr><td colspan="8" class="text-center py-6 text-danger">Failed to load records. Is the server running?</td></tr>
    `;
  }
}

async function fetchUnfilledRecords() {
  try {
    const params = new URLSearchParams();
    if (state.unfilledStatusFilter) {
      params.append('status', state.unfilledStatusFilter);
    }
    const res = await fetch(`/api/unfilled?${params.toString()}`);
    if (!res.ok) throw new Error('Failed to fetch unfilled records');
    const data = await res.json();
    renderUnfilledTable(data.records);
  } catch (err) {
    console.error('Unfilled records fetch error:', err);
  }
}

function fetchAllData() {
  fetchStats();
  fetchCompletedRecords();
  fetchUnfilledRecords();
  fetchVerificationStats();
  fetchVerificationRecords();
}


// ==========================================================================
// Render Functions
// ==========================================================================

function renderStats() {
  document.getElementById('statCompleted').textContent = state.stats.total_completed;
  document.getElementById('statUnfilled').textContent = state.stats.total_unfilled;
  document.getElementById('statResolved').textContent = state.stats.total_resolved;
  document.getElementById('statNextQr').textContent = `QRCode - ${state.stats.next_qr}`;
  document.getElementById('statLastCompleted').textContent = `Last: QRCode - ${state.stats.last_completed_qr}`;

  // Badges in tabs
  document.getElementById('tabBadgeCompleted').textContent = state.stats.total_completed;
  document.getElementById('tabBadgeUnfilled').textContent = state.stats.total_unfilled;

  // Next QR suggestion for manual entry
  const qrInput = document.getElementById('formQrNumber');
  if (qrInput && !qrInput.value) {
    qrInput.placeholder = state.stats.next_qr;
  }
}

function renderCompletedTable(records) {
  const tbody = document.getElementById('completedTableBody');
  if (!records || records.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="8" class="text-center py-6 text-muted">
          ${state.completedSearch ? 'No completed records matching your search.' : 'No completed QR codes recorded yet.'}
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = records.map(r => `
    <tr>
      <td>
        <span class="badge badge-purple font-mono">${escapeHtml(r.qr_label)}</span>
      </td>
      <td>
        <strong>${escapeHtml(r.name || 'N/A')}</strong>
      </td>
      <td class="text-secondary">${escapeHtml(r.designation || '-')}</td>
      <td>${escapeHtml(r.company || '-')}</td>
      <td class="font-mono text-sm">${escapeHtml(r.office_contact || '-')}</td>
      <td class="text-secondary text-sm">${escapeHtml(r.email || '-')}</td>
      <td class="text-muted text-sm">${escapeHtml(r.updated_at || r.created_at || '-')}</td>
      <td style="text-align: right;">
        <button class="btn btn-secondary btn-sm" onclick="viewRecordDetails(${r.qr_number})">
          View
        </button>
      </td>
    </tr>
  `).join('');
}

function renderCompletedPagination(total) {
  const start = total === 0 ? 0 : (state.completedPage - 1) * state.completedLimit + 1;
  const end = Math.min(state.completedPage * state.completedLimit, total);
  const totalPages = Math.ceil(total / state.completedLimit) || 1;

  document.getElementById('pageStart').textContent = start;
  document.getElementById('pageEnd').textContent = end;
  document.getElementById('pageTotal').textContent = total;
  document.getElementById('pageCurrentDisplay').textContent = `Page ${state.completedPage} of ${totalPages}`;

  document.getElementById('btnPrevPage').disabled = state.completedPage <= 1;
  document.getElementById('btnNextPage').disabled = state.completedPage >= totalPages;
}

function renderUnfilledTable(records) {
  const tbody = document.getElementById('unfilledTableBody');
  if (!records || records.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" class="text-center py-6 text-muted">
          No unfilled forms recorded. All caught up!
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = records.map(r => {
    const isUnfilled = r.status === 'unfilled';
    const statusBadge = isUnfilled
      ? `<span class="badge badge-danger">Unfilled</span>`
      : `<span class="badge badge-success">Resolved</span>`;

    const missingTags = r.missing_fields
      ? r.missing_fields.split(',').map(f => `<span class="tag-field">${escapeHtml(f.trim())}</span>`).join(' ')
      : '<span class="text-muted text-sm">None</span>';

    return `
      <tr>
        <td>
          <span class="badge badge-danger font-mono">${escapeHtml(r.qr_label)}</span>
        </td>
        <td>${statusBadge}</td>
        <td>
          <div style="max-width: 280px; word-break: break-word;">
            ${escapeHtml(r.reason || 'Skipped')}
          </div>
        </td>
        <td>
          <div class="tags-list">${missingTags}</div>
        </td>
        <td class="text-muted text-sm">${escapeHtml(r.updated_at || r.created_at || '-')}</td>
        <td style="text-align: right;">
          <div style="display: inline-flex; gap: 0.35rem; justify-content: flex-end;">
            <button class="btn btn-secondary btn-sm" onclick="inspectUnfilled(${r.qr_number})">
              Details
            </button>
            <button class="btn btn-primary btn-sm" onclick="fillUnfilledRecord(${r.qr_number})" title="Fill this form manually">
              Fill
            </button>
            ${isUnfilled ? `
              <button class="btn btn-success btn-sm" onclick="resolveUnfilled(${r.qr_number})" title="Mark as resolved">
                Resolve
              </button>
            ` : ''}
          </div>
        </td>
      </tr>
    `;
  }).join('');
}

// ==========================================================================
// Handlers & Event Setup
// ==========================================================================

function setupTabs() {
  const buttons = document.querySelectorAll('.tab-button');
  buttons.forEach(btn => {
    btn.addEventListener('click', () => {
      const targetId = btn.getAttribute('data-tab');
      // Update buttons
      buttons.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      // Update panes
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
      document.getElementById(targetId).classList.add('active');

      if (targetId === 'tabCompleted') fetchCompletedRecords();
      if (targetId === 'tabUnfilled') fetchUnfilledRecords();
    });
  });

  // Filter chips in unfilled tab
  const filterChips = document.querySelectorAll('.filter-chip');
  filterChips.forEach(chip => {
    chip.addEventListener('click', () => {
      filterChips.forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      state.unfilledStatusFilter = chip.getAttribute('data-status');
      fetchUnfilledRecords();
    });
  });

  // Pagination buttons
  document.getElementById('btnPrevPage').addEventListener('click', () => {
    if (state.completedPage > 1) {
      state.completedPage--;
      fetchCompletedRecords();
    }
  });

  document.getElementById('btnNextPage').addEventListener('click', () => {
    const totalPages = Math.ceil(state.completedTotal / state.completedLimit);
    if (state.completedPage < totalPages) {
      state.completedPage++;
      fetchCompletedRecords();
    }
  });
}

function setupSearch() {
  const input = document.getElementById('completedSearchInput');
  const clearBtn = document.getElementById('completedSearchClear');
  let debounceTimeout = null;

  input.addEventListener('input', (e) => {
    const val = e.target.value.trim();
    clearBtn.style.display = val ? 'block' : 'none';

    clearTimeout(debounceTimeout);
    debounceTimeout = setTimeout(() => {
      state.completedSearch = val;
      state.completedPage = 1;
      fetchCompletedRecords();
    }, 300);
  });

  clearBtn.addEventListener('click', () => {
    input.value = '';
    clearBtn.style.display = 'none';
    state.completedSearch = '';
    state.completedPage = 1;
    fetchCompletedRecords();
  });
}

function setupRefreshControls() {
  const select = document.getElementById('autoRefreshSelect');
  const manualBtn = document.getElementById('btnManualRefresh');

  select.addEventListener('change', (e) => {
    state.autoRefreshSec = parseInt(e.target.value, 10);
    startAutoRefresh();
  });

  manualBtn.addEventListener('click', () => {
    fetchAllData();
    showToast('Refreshing records...', 'info');
  });
}

function startAutoRefresh() {
  if (state.autoRefreshTimer) {
    clearInterval(state.autoRefreshTimer);
    state.autoRefreshTimer = null;
  }
  if (state.autoRefreshSec > 0) {
    state.autoRefreshTimer = setInterval(() => {
      fetchAllData();
    }, state.autoRefreshSec * 1000);
  }
}

function updateConnectionStatus(isOnline) {
  const el = document.getElementById('connectionStatus');
  const dot = el.querySelector('.status-dot');
  const text = el.querySelector('.status-text');

  if (isOnline) {
    dot.className = 'status-dot online';
    text.textContent = 'Connected';
  } else {
    dot.className = 'status-dot offline';
    text.textContent = 'Disconnected';
  }
}

// ==========================================================================
// Web Audio Beep & Test
// ==========================================================================

function playBrowserBeep() {
  try {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) return;
    const ctx = new AudioContext();

    // 1st Beep: 1400Hz for 0.35s
    const osc1 = ctx.createOscillator();
    const gain1 = ctx.createGain();
    osc1.type = 'sine';
    osc1.frequency.setValueAtTime(1400, ctx.currentTime);
    gain1.gain.setValueAtTime(0.25, ctx.currentTime);
    gain1.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.35);
    osc1.connect(gain1);
    gain1.connect(ctx.destination);
    osc1.start(ctx.currentTime);
    osc1.stop(ctx.currentTime + 0.35);

    // 2nd Beep: 1800Hz for 0.45s after 0.1s gap
    const osc2 = ctx.createOscillator();
    const gain2 = ctx.createGain();
    osc2.type = 'sine';
    osc2.frequency.setValueAtTime(1800, ctx.currentTime + 0.45);
    gain2.gain.setValueAtTime(0.25, ctx.currentTime + 0.45);
    gain2.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.9);
    osc2.connect(gain2);
    gain2.connect(ctx.destination);
    osc2.start(ctx.currentTime + 0.45);
    osc2.stop(ctx.currentTime + 0.9);
  } catch (e) {
    console.error('AudioContext error:', e);
  }
}

function setupAudioBeep() {
  const btn = document.getElementById('btnTestBeep');
  btn.addEventListener('click', async () => {
    playBrowserBeep();
    showToast('Alert beep sound played!', 'info');

    // Also trigger backend sound if server is running locally
    try {
      fetch('/api/beep', { method: 'POST' });
    } catch (e) {}
  });
}

// ==========================================================================
// Export Dropdown
// ==========================================================================

function setupExportDropdown() {
  const btn = document.getElementById('btnExportMenu');
  const menu = document.getElementById('exportDropdown');

  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    menu.classList.toggle('show');
  });

  document.addEventListener('click', () => {
    menu.classList.remove('show');
  });

  document.getElementById('exportCompletedCsv').addEventListener('click', () => {
    window.location.href = '/api/export?type=completed&format=csv';
  });

  document.getElementById('exportCompletedJson').addEventListener('click', () => {
    window.location.href = '/api/export?type=completed&format=json';
  });

  document.getElementById('exportUnfilledCsv').addEventListener('click', () => {
    window.location.href = '/api/export?type=unfilled&format=csv';
  });

  document.getElementById('exportUnfilledJson').addEventListener('click', () => {
    window.location.href = '/api/export?type=unfilled&format=json';
  });
}

// ==========================================================================
// Manual Form Submission
// ==========================================================================

function setupManualForm() {
  const form = document.getElementById('manualEntryForm');
  form.addEventListener('submit', async (e) => {
    e.preventDefault();

    const qrNumber = parseInt(document.getElementById('formQrNumber').value, 10);
    const data = {
      name: document.getElementById('formName').value.trim(),
      designation: document.getElementById('formDesignation').value.trim(),
      company: document.getElementById('formCompany').value.trim(),
      website: document.getElementById('formWebsite').value.trim(),
      address: document.getElementById('formAddress').value.trim(),
      email: document.getElementById('formEmail').value.trim(),
      office_contact: document.getElementById('formOfficeContact').value.trim()
    };

    if (!qrNumber || !data.name || !data.company) {
      showToast('Please fill all required fields.', 'error');
      return;
    }

    try {
      const res = await fetch('/api/save-record', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ qr_number: qrNumber, data })
      });
      const result = await res.json();
      if (result.success) {
        showToast(`QRCode - ${qrNumber} successfully saved to database!`, 'success');
        form.reset();
        fetchAllData();
        // Switch to completed tab
        document.querySelector('[data-tab="tabCompleted"]').click();
      } else {
        showToast(`Error saving record: ${result.error}`, 'error');
      }
    } catch (err) {
      console.error('Save record error:', err);
      showToast('Network error while saving form.', 'error');
    }
  });
}

// ==========================================================================
// Modal Handlers
// ==========================================================================

let activeDetailQr = null;

async function viewRecordDetails(qrNumber) {
  try {
    const res = await fetch(`/api/record?qr=${qrNumber}`);
    if (!res.ok) throw new Error('Record not found');
    const record = await res.json();

    activeDetailQr = record;
    document.getElementById('modalQrLabel').textContent = record.qr_label;
    document.getElementById('modalName').textContent = record.name || 'N/A';
    document.getElementById('modalDesignation').textContent = record.designation || '-';
    document.getElementById('modalCompany').textContent = record.company || '-';
    document.getElementById('modalEmail').textContent = record.email || '-';
    document.getElementById('modalOfficeContact').textContent = record.office_contact || '-';
    document.getElementById('modalWebsite').textContent = record.website || '-';
    document.getElementById('modalAddress').textContent = record.address || '-';
    document.getElementById('modalUpdatedAt').textContent = record.updated_at || record.created_at || '-';

    document.getElementById('detailModal').classList.add('show');
  } catch (err) {
    showToast('Failed to load record details.', 'error');
  }
}

async function inspectUnfilled(qrNumber) {
  try {
    const res = await fetch(`/api/unfilled?status=`);
    const data = await res.json();
    const item = data.records.find(r => r.qr_number === qrNumber);
    if (!item) return;

    document.getElementById('unfilledModalQr').textContent = item.qr_label;
    document.getElementById('unfilledModalReason').textContent = item.reason || 'No description';

    const missingContainer = document.getElementById('unfilledModalMissing');
    if (item.missing_fields) {
      missingContainer.innerHTML = item.missing_fields
        .split(',')
        .map(f => `<span class="tag-field">${escapeHtml(f.trim())}</span>`)
        .join(' ');
    } else {
      missingContainer.innerHTML = '<span class="text-muted">None</span>';
    }

    let rawFormatted = 'No raw data captured.';
    if (item.raw_data) {
      try {
        const parsed = JSON.parse(item.raw_data);
        rawFormatted = JSON.stringify(parsed, null, 2);
      } catch (e) {
        rawFormatted = item.raw_data;
      }
    }
    document.getElementById('unfilledModalRaw').textContent = rawFormatted;

    document.getElementById('unfilledModalFillBtn').onclick = () => {
      document.getElementById('unfilledModal').classList.remove('show');
      fillUnfilledRecord(qrNumber, item);
    };

    document.getElementById('unfilledModal').classList.add('show');
  } catch (err) {
    showToast('Failed to load unfilled details.', 'error');
  }
}

async function resolveUnfilled(qrNumber) {
  try {
    const res = await fetch('/api/unfilled/resolve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ qr_number: qrNumber })
    });
    const result = await res.json();
    if (result.success) {
      showToast(`QRCode - ${qrNumber} marked as resolved!`, 'success');
      fetchAllData();
    }
  } catch (e) {
    showToast('Failed to resolve record.', 'error');
  }
}

async function fillUnfilledRecord(qrNumber, itemData = null) {
  if (!itemData) {
    const res = await fetch('/api/unfilled?status=');
    const data = await res.json();
    itemData = data.records.find(r => r.qr_number === qrNumber);
  }

  // Switch to manual entry tab
  document.querySelector('[data-tab="tabManualEntry"]').click();

  // Prepopulate form
  document.getElementById('formQrNumber').value = qrNumber;

  if (itemData && itemData.raw_data) {
    try {
      const parsed = JSON.parse(itemData.raw_data);
      if (parsed.name) document.getElementById('formName').value = parsed.name;
      if (parsed.designation) document.getElementById('formDesignation').value = parsed.designation;
      if (parsed.company) document.getElementById('formCompany').value = parsed.company;
      if (parsed.website) document.getElementById('formWebsite').value = parsed.website;
      if (parsed.address) document.getElementById('formAddress').value = parsed.address;
      if (parsed.email) document.getElementById('formEmail').value = parsed.email;
      if (parsed.office_contact) document.getElementById('formOfficeContact').value = parsed.office_contact;
    } catch (e) {}
  }

  showToast(`Editing QRCode - ${qrNumber}. Complete fields and click Save.`, 'info');
}

function setupModals() {
  const detailModal = document.getElementById('detailModal');
  const unfilledModal = document.getElementById('unfilledModal');

  document.getElementById('modalCloseBtn').onclick = () => detailModal.classList.remove('show');
  document.getElementById('modalCloseBtnFooter').onclick = () => detailModal.classList.remove('show');

  document.getElementById('unfilledModalCloseBtn').onclick = () => unfilledModal.classList.remove('show');
  document.getElementById('unfilledModalCloseBtnFooter').onclick = () => unfilledModal.classList.remove('show');

  // Edit from detail modal
  document.getElementById('modalEditBtn').onclick = () => {
    if (!activeDetailQr) return;
    detailModal.classList.remove('show');
    document.querySelector('[data-tab="tabManualEntry"]').click();

    document.getElementById('formQrNumber').value = activeDetailQr.qr_number;
    document.getElementById('formName').value = activeDetailQr.name || '';
    document.getElementById('formDesignation').value = activeDetailQr.designation || '';
    document.getElementById('formCompany').value = activeDetailQr.company || '';
    document.getElementById('formWebsite').value = activeDetailQr.website || '';
    document.getElementById('formAddress').value = activeDetailQr.address || '';
    document.getElementById('formEmail').value = activeDetailQr.email || '';
    document.getElementById('formOfficeContact').value = activeDetailQr.office_contact || '';
  };

  window.addEventListener('click', (e) => {
    if (e.target === detailModal) detailModal.classList.remove('show');
    if (e.target === unfilledModal) unfilledModal.classList.remove('show');
  });
}

// ==========================================================================
// Toast Helpers
// ==========================================================================

function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(100%)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// ==========================================================================
// Verification System Client Logic
// ==========================================================================

async function fetchVerificationStats() {
  try {
    const res = await fetch('/api/verify/stats');
    if (!res.ok) throw new Error('Failed to fetch verify stats');
    const data = await res.json();
    state.verifyStats = data;
    renderVerificationStats();
  } catch (err) {
    console.error('Verify stats fetch error:', err);
  }
}

async function fetchVerificationRecords() {
  try {
    const params = new URLSearchParams({
      page: state.verifyPage,
      limit: state.verifyLimit,
      status: state.verifyFilter,
      search: state.verifySearch
    });
    const res = await fetch(`/api/verify/results?${params.toString()}`);
    if (!res.ok) throw new Error('Failed to fetch verify records');
    const data = await res.json();
    state.verifyTotal = data.total;
    renderVerificationTable(data.records);
    renderVerificationPagination(data.total);
  } catch (err) {
    console.error('Verify records fetch error:', err);
    const tbody = document.getElementById('verifyTableBody');
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="7" class="text-center py-6 text-danger">Failed to load verification records.</td></tr>`;
    }
  }
}

let currentInspectQrNumber = null;

async function setQrStatus(qrNumber, status) {
  try {
    const res = await fetch('/api/verify/update-status', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ qr_number: qrNumber, status: status })
    });
    if (!res.ok) throw new Error('Failed to update status');
    const data = await res.json();
    if (data.success) {
      showToast(`QRCode - ${qrNumber} marked as ${status.toUpperCase()}`, status === 'resolved' ? 'success' : 'error');
      fetchVerificationStats();
      fetchVerificationRecords();
    }
  } catch (err) {
    console.error('Update status error:', err);
    showToast('Failed to update status', 'error');
  }
}

function renderVerificationStats() {
  const stats = state.verifyStats;
  const avgEl = document.getElementById('verifyStatAvgAccuracy');
  const totalEl = document.getElementById('verifyStatTotal');
  const resEl = document.getElementById('verifyStatResolved');
  const blockEl = document.getElementById('verifyStatBlocked');
  const badgeVerify = document.getElementById('tabBadgeVerify');
  const cardFlaggedLow = document.getElementById('cardFlaggedLow');

  if (avgEl) avgEl.textContent = `${stats.avg_accuracy}%`;
  if (totalEl) totalEl.textContent = stats.total_verified;
  if (resEl) resEl.textContent = stats.resolved_count ?? stats.perfect_count ?? 0;
  if (blockEl) blockEl.textContent = stats.blocked_count ?? stats.low_count ?? 0;
  if (badgeVerify) badgeVerify.textContent = stats.total_verified;

  // Highlight blocked card if blocked_count > 0
  if (cardFlaggedLow) {
    const blockedNum = stats.blocked_count ?? stats.low_count ?? 0;
    if (blockedNum > 0) {
      cardFlaggedLow.classList.add('pulse-highlight');
    } else {
      cardFlaggedLow.classList.remove('pulse-highlight');
    }
  }
}

function renderVerificationTable(records) {
  const tbody = document.getElementById('verifyTableBody');
  if (!tbody) return;

  if (!records || records.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="7" class="text-center py-6 text-muted">
          No verification records found. Click <strong>"Run Verification"</strong> above to analyze submitted forms against card images.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = records.map(r => {
    const acc = Number(r.accuracy).toFixed(1);
    const isBlocked = r.status === 'blocked' || (Number(acc) < 100.0 && r.status !== 'resolved');
    const isResolved = r.status === 'resolved' || (!isBlocked && Number(acc) >= 100.0);

    let accBadgeClass = 'acc-minor';
    let statusBadge = '<span class="badge badge-danger">Blocked</span>';
    let rowClass = '';

    if (isResolved) {
      statusBadge = '<span class="badge badge-success">Resolved</span>';
      if (Number(acc) >= 100.0) {
        accBadgeClass = 'acc-perfect';
      }
    } else {
      statusBadge = '<span class="badge badge-danger">Blocked</span>';
      rowClass = 'row-flagged-low'; // Highlighting blocked / lower accuracy QR row
      accBadgeClass = Number(acc) < 90.0 ? 'acc-low' : 'acc-minor';
    }

    // Mini field dots: N (Name), D (Designation), C (Company), W (Website), A (Address), E (Email), O (Office Contact)
    const fieldMap = [
      { key: 'name', char: 'N', name: 'Name' },
      { key: 'designation', char: 'D', name: 'Designation' },
      { key: 'company', char: 'C', name: 'Company' },
      { key: 'website', char: 'W', name: 'Website' },
      { key: 'address', char: 'A', name: 'Address' },
      { key: 'email', char: 'E', name: 'Email' },
      { key: 'office_contact', char: 'O', name: 'Office Contact' }
    ];

    const scores = r.field_scores || {};
    const dotsHtml = fieldMap.map(f => {
      const fScore = Number(scores[f.key] ?? 100.0);
      const isMismatch = fScore < 100.0;
      const dotCls = isMismatch ? 'dot-mismatch' : 'dot-100';
      return `<span class="field-dot ${dotCls}" title="${f.name}: ${fScore}%">${f.char}</span>`;
    }).join('');

    // Discrepancy summary preview
    let discPreview = '<span class="text-muted text-xs">No discrepancies</span>';
    if (r.discrepancies && r.discrepancies.length > 0) {
      const firstDisc = escapeHtml(r.discrepancies[0]);
      const moreCount = r.discrepancies.length - 1;
      discPreview = `<span class="text-xs text-danger font-mono">${firstDisc}</span>`;
      if (moreCount > 0) {
        discPreview += ` <span class="badge badge-secondary" style="font-size:0.7rem;">+${moreCount} more</span>`;
      }
    }

    const imgThumb = r.image_url
      ? `<img src="${escapeHtml(r.image_url)}" class="qr-thumb-preview" alt="Card" onclick="openVerificationModal(${r.qr_number})" title="Click to inspect card image in large size">`
      : '<span class="text-muted text-xs">No image</span>';

    return `
      <tr class="${rowClass}">
        <td>
          <strong class="${isBlocked ? 'text-danger font-bold' : ''}">${escapeHtml(r.qr_label)}</strong>
          ${isBlocked ? '<span class="badge badge-danger ml-1" style="font-size:0.65rem;">BLOCKED</span>' : ''}
        </td>
        <td>
          <span class="badge-accuracy ${accBadgeClass}">
            ${acc}% Match
          </span>
        </td>
        <td>${statusBadge}</td>
        <td>
          <div class="mini-indicators">${dotsHtml}</div>
        </td>
        <td>${discPreview}</td>
        <td>${imgThumb}</td>
        <td style="text-align: right;">
          <div class="verify-row-actions">
            <button class="btn btn-xs btn-secondary" onclick="openVerificationModal(${r.qr_number})" title="Inspect match and large image">
              Inspect
            </button>
            <button class="btn btn-xs btn-action-resolved ${isResolved ? 'active-status' : ''}" onclick="setQrStatus(${r.qr_number}, 'resolved')" title="Mark QRCode as Resolved">
              Resolved
            </button>
            <button class="btn btn-xs btn-action-blocked ${isBlocked ? 'active-status' : ''}" onclick="setQrStatus(${r.qr_number}, 'blocked')" title="Mark QRCode as Blocked">
              Blocked
            </button>
          </div>
        </td>
      </tr>
    `;
  }).join('');
}

function renderVerificationPagination(total) {
  const pStart = document.getElementById('verifyPageStart');
  const pEnd = document.getElementById('verifyPageEnd');
  const pTotal = document.getElementById('verifyPageTotal');
  const btnPrev = document.getElementById('btnPrevVerifyPage');
  const btnNext = document.getElementById('btnNextVerifyPage');
  const curDisplay = document.getElementById('verifyPageCurrentDisplay');

  if (!pStart || !pEnd || !pTotal) return;

  const start = total === 0 ? 0 : (state.verifyPage - 1) * state.verifyLimit + 1;
  const end = Math.min(state.verifyPage * state.verifyLimit, total);

  pStart.textContent = start;
  pEnd.textContent = end;
  pTotal.textContent = total;
  if (curDisplay) curDisplay.textContent = `Page ${state.verifyPage}`;

  if (btnPrev) btnPrev.disabled = state.verifyPage <= 1;
  if (btnNext) btnNext.disabled = end >= total;
}

async function openVerificationModal(qrNumber) {
  try {
    currentInspectQrNumber = qrNumber;
    const res = await fetch(`/api/verify/record?qr=${qrNumber}`);
    if (!res.ok) throw new Error('Failed to fetch verification detail');
    const rec = await res.json();

    const modal = document.getElementById('verifyDetailModal');
    if (!modal) return;

    document.getElementById('verifyModalQr').textContent = rec.qr_label || `QRCode - ${qrNumber}`;

    const acc = Number(rec.accuracy).toFixed(1);
    const accBadge = document.getElementById('verifyModalAccuracy');
    accBadge.textContent = `${acc}% Match`;
    accBadge.className = 'badge ' + (Number(acc) >= 100 ? 'badge-success' : (Number(acc) < 90 ? 'badge-danger' : 'badge-info'));

    // Status Badge inside Modal
    const statusBadge = document.getElementById('verifyModalStatusBadge');
    const isBlocked = rec.status === 'blocked' || (Number(acc) < 100 && rec.status !== 'resolved');
    if (statusBadge) {
      if (isBlocked) {
        statusBadge.textContent = 'Blocked';
        statusBadge.className = 'badge badge-danger';
      } else {
        statusBadge.textContent = 'Resolved';
        statusBadge.className = 'badge badge-success';
      }
    }

    // Prominent Large Card Image
    const imgEl = document.getElementById('verifyModalImg');
    const imgLink = document.getElementById('verifyModalImgLink');
    if (rec.image_url) {
      imgEl.src = rec.image_url;
      imgLink.href = rec.image_url;
      imgLink.style.display = 'inline-block';
    } else {
      imgEl.src = '';
      imgLink.style.display = 'none';
    }

    // Raw OCR
    document.getElementById('verifyModalRawOcr').textContent = rec.ocr_raw_text || 'No raw OCR captured.';

    // 7 Fields Comparison Table
    const webData = rec.website_data || {};
    const imgData = rec.image_data || {};
    const scores = rec.field_scores || {};

    const fieldsList = [
      { key: 'name', label: 'Name' },
      { key: 'designation', label: 'Designation' },
      { key: 'company', label: 'Company Name' },
      { key: 'website', label: 'Website' },
      { key: 'address', label: 'Address' },
      { key: 'email', label: 'Email' },
      { key: 'office_contact', label: 'Office Contact' }
    ];

    const fieldsTbody = document.getElementById('verifyModalFieldsBody');
    fieldsTbody.innerHTML = fieldsList.map(f => {
      const webVal = webData[f.key] || '';
      const imgVal = imgData[f.key] || '';
      const fScore = Number(scores[f.key] ?? 100.0).toFixed(1);
      const isMatch = Number(fScore) >= 100.0;
      const statusHtml = isMatch
        ? '<span class="badge badge-success text-xs">Match</span>'
        : `<span class="badge badge-danger text-xs">${fScore}%</span>`;

      return `
        <tr>
          <td><strong>${f.label}</strong></td>
          <td class="val-portal">${escapeHtml(webVal) || '<span class="text-muted">(empty)</span>'}</td>
          <td class="val-image">${escapeHtml(imgVal) || '<span class="text-muted">(empty)</span>'}</td>
          <td style="text-align: center; font-weight: 700;">${fScore}%</td>
          <td style="text-align: center;">${statusHtml}</td>
        </tr>
      `;
    }).join('');

    // AI Note & Discrepancy Card
    const aiBox = document.getElementById('verifyModalAiNoteBox');
    const aiText = document.getElementById('verifyModalAiNoteText');
    const discList = document.getElementById('verifyModalDiscList');
    const isFullMatch = Number(acc) >= 100.0 || (!rec.discrepancies || rec.discrepancies.length === 0);

    if (aiBox && aiText) {
      if (isFullMatch) {
        aiBox.className = 'ai-note-card success';
        aiText.innerHTML = `<strong>✅ 100% Match Verified</strong>: ${escapeHtml(rec.ai_note || 'All 7 fields match the original card image with exact precision. No human data entry errors detected.')}`;
        if (discList) discList.style.display = 'none';
      } else {
        aiBox.className = 'ai-note-card blocked';
        aiText.innerHTML = `<strong>⚠️ Verification Discrepancy Flagged</strong>: ${escapeHtml(rec.ai_note || 'AI identified genuine field mismatches between portal submission and source image.')}`;
        if (discList && rec.discrepancies && rec.discrepancies.length > 0) {
          discList.style.display = 'block';
          discList.innerHTML = rec.discrepancies.map(d => `<li>${escapeHtml(d)}</li>`).join('');
        } else if (discList) {
          discList.style.display = 'none';
        }
      }
    }

    modal.classList.add('show');
  } catch (err) {
    console.error('Error opening verification modal:', err);
    showToast('Failed to load verification record details', 'error');
  }
}


async function startVerificationJob() {
  const startQr = parseInt(document.getElementById('verifyStartQr')?.value || '1', 10);
  const endQr = parseInt(document.getElementById('verifyEndQr')?.value || '160', 10);

  try {
    const res = await fetch('/api/verify/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ start_qr: startQr, end_qr: endQr })
    });
    const data = await res.json();
    if (data.success) {
      showToast(data.message || 'Verification started!', 'info');
      startProgressPolling();
    } else {
      showToast(data.message || 'Could not start verification.', 'error');
    }
  } catch (err) {
    showToast('Error connecting to verification service.', 'error');
  }
}

async function stopVerificationJob() {
  try {
    const res = await fetch('/api/verify/stop', { method: 'POST' });
    const data = await res.json();
    showToast('Verification stopped.', 'info');
  } catch (err) {
    console.error('Stop verification error:', err);
  }
}

function startProgressPolling() {
  const banner = document.getElementById('verifyProgressBanner');
  if (banner) banner.style.display = 'block';

  if (state.verifyProgressInterval) clearInterval(state.verifyProgressInterval);

  state.verifyProgressInterval = setInterval(async () => {
    try {
      const res = await fetch('/api/verify/progress');
      if (!res.ok) return;
      const prog = await res.json();

      const titleEl = document.getElementById('verifyProgressTitle');
      const subEl = document.getElementById('verifyProgressSubtitle');
      const barEl = document.getElementById('verifyProgressBar');
      const countEl = document.getElementById('verifyProgressCount');
      const pctEl = document.getElementById('verifyProgressPercent');

      if (titleEl) titleEl.textContent = prog.running ? 'Analyzing Submissions Against Source Images...' : 'Verification Completed';
      if (subEl) subEl.textContent = prog.message;
      if (barEl) barEl.style.width = `${prog.percent}%`;
      if (countEl) countEl.textContent = `${prog.processed} / ${prog.total} QRs processed`;
      if (pctEl) pctEl.textContent = `${prog.percent}%`;

      // Live refresh of table and stats
      fetchVerificationStats();
      fetchVerificationRecords();

      if (!prog.running) {
        clearInterval(state.verifyProgressInterval);
        state.verifyProgressInterval = null;
        setTimeout(() => {
          if (banner) banner.style.display = 'none';
        }, 3500);
      }
    } catch (err) {
      console.error('Progress poll error:', err);
    }
  }, 2500);
}

function setupVerification() {
  const btnStart = document.getElementById('btnStartVerify');
  if (btnStart) btnStart.onclick = startVerificationJob;

  const btnStop = document.getElementById('btnStopVerify');
  if (btnStop) btnStop.onclick = stopVerificationJob;

  // Filter chips
  document.querySelectorAll('[data-verify-filter]').forEach(chip => {
    chip.addEventListener('click', () => {
      document.querySelectorAll('[data-verify-filter]').forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      state.verifyFilter = chip.getAttribute('data-verify-filter');
      state.verifyPage = 1;
      fetchVerificationRecords();
    });
  });

  // Search box
  const searchInput = document.getElementById('verifySearchInput');
  const clearBtn = document.getElementById('verifySearchClear');
  if (searchInput) {
    let debounce;
    searchInput.addEventListener('input', (e) => {
      clearTimeout(debounce);
      const val = e.target.value.trim();
      if (clearBtn) clearBtn.style.display = val ? 'block' : 'none';
      debounce = setTimeout(() => {
        state.verifySearch = val;
        state.verifyPage = 1;
        fetchVerificationRecords();
      }, 300);
    });
  }

  if (clearBtn) {
    clearBtn.addEventListener('click', () => {
      if (searchInput) searchInput.value = '';
      clearBtn.style.display = 'none';
      state.verifySearch = '';
      state.verifyPage = 1;
      fetchVerificationRecords();
    });
  }

  // Pagination buttons
  const btnPrev = document.getElementById('btnPrevVerifyPage');
  const btnNext = document.getElementById('btnNextVerifyPage');
  if (btnPrev) {
    btnPrev.onclick = () => {
      if (state.verifyPage > 1) {
        state.verifyPage--;
        fetchVerificationRecords();
      }
    };
  }
  if (btnNext) {
    btnNext.onclick = () => {
      state.verifyPage++;
      fetchVerificationRecords();
    };
  }

  // Modal Action Buttons (Resolved / Blocked)
  const handleModalResolve = async () => {
    if (!currentInspectQrNumber) return;
    await setQrStatus(currentInspectQrNumber, 'resolved');
    const statusBadge = document.getElementById('verifyModalStatusBadge');
    if (statusBadge) {
      statusBadge.textContent = 'Resolved';
      statusBadge.className = 'badge badge-success';
    }
  };

  const handleModalBlock = async () => {
    if (!currentInspectQrNumber) return;
    await setQrStatus(currentInspectQrNumber, 'blocked');
    const statusBadge = document.getElementById('verifyModalStatusBadge');
    if (statusBadge) {
      statusBadge.textContent = 'Blocked';
      statusBadge.className = 'badge badge-danger';
    }
  };

  document.getElementById('btnModalResolve')?.addEventListener('click', handleModalResolve);
  document.getElementById('btnModalResolveTop')?.addEventListener('click', handleModalResolve);
  document.getElementById('btnModalBlock')?.addEventListener('click', handleModalBlock);
  document.getElementById('btnModalBlockTop')?.addEventListener('click', handleModalBlock);

  // Close modals
  const vCloseBtn = document.getElementById('verifyModalCloseBtn');
  const vCloseBtnFooter = document.getElementById('verifyModalCloseBtnFooter');
  const vModal = document.getElementById('verifyDetailModal');
  if (vCloseBtn) vCloseBtn.onclick = () => vModal.classList.remove('show');
  if (vCloseBtnFooter) vCloseBtnFooter.onclick = () => vModal.classList.remove('show');
  if (vModal) {
    window.addEventListener('click', (e) => {
      if (e.target === vModal) vModal.classList.remove('show');
    });
  }
}


