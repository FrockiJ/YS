let token = null;
const API_BASE = window.APP_API_PREFIX || '/api';
const LOGIN_ENDPOINT = `${API_BASE}/auth/login`;
const $ = (sel) => document.querySelector(sel);

$('#login').onclick = async () => {
  const email = $('#email').value;
  const password = $('#password').value;
  const resp = await fetch(LOGIN_ENDPOINT, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ email, password })
  });
  const raw = await resp.text();
  let data = null;
  try { data = raw ? JSON.parse(raw) : null; } catch (_) {}
  if (!resp.ok || !data) {
    alert((data && data.detail) || raw || 'Login failed');
    return;
  }
  token = data.token || data.access_token;
  $('#who').textContent = 'Logged in as: ' + (data.user?.username || data.user || '');
};

async function authGet(url) {
  const headers = token ? { 'Authorization': 'Bearer ' + token } : {};
  const resp = await fetch(API_BASE + url, { headers });
  if (!resp.ok) {
    alert('Please login first');
    throw new Error('unauthorized');
  }
  return resp.json();
}

async function authPost(url, body) {
  const headers = { 'Content-Type': 'application/json' };
  if (token) { headers['Authorization'] = 'Bearer ' + token; }
  const opts = { method: 'POST', headers };
  if (body && Object.keys(body).length) {
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(API_BASE + url, opts);
  const raw = await resp.text();
  let data = null;
  try { data = raw ? JSON.parse(raw) : null; } catch (_) {}
  if (!resp.ok || (data && data.ok === false)) {
    const msg = (data && (data.error || data.msg)) || raw || 'Request failed';
    throw new Error(msg);
  }
  return data || {};
}

$('#load-sum').onclick = async () => {
  const group = $('#group').value;
  const res = await authGet('/admin/summary?group_by=' + group);
  const tb = $('#sum tbody');
  tb.innerHTML = '';
  (res.rows || []).forEach((row) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${row.key || ''}</td><td>${row.chunks || 0}</td>`;
    tb.appendChild(tr);
  });
};

$('#exp-sum').onclick = () => {
  const group = $('#group').value;
  const headers = token ? { 'Authorization': 'Bearer ' + token } : {};
  fetch(API_BASE + '/export/summary.csv?group_by=' + group, { headers })
    .then((r) => r.blob())
    .then((blob) => {
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'summary_' + group + '.csv';
      a.click();
    });
};

$('#load-ali').onclick = async () => {
  const res = await authGet('/admin/aliases?limit=500');
  const tb = $('#ali tbody');
  tb.innerHTML = '';
  (res.rows || []).forEach((row) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${row.canonical}</td><td>${row.variant}</td><td>${row.type}</td><td>${row.lang}</td><td>${row.source}</td><td>${row.confidence}</td>`;
    tb.appendChild(tr);
  });
};

$('#exp-ali').onclick = () => {
  const headers = token ? { 'Authorization': 'Bearer ' + token } : {};
  fetch(API_BASE + '/export/aliases.csv', { headers })
    .then((r) => r.blob())
    .then((blob) => {
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'aliases.csv';
      a.click();
    });
};

$('#load-ch').onclick = async () => {
  const res = await authGet('/admin/chunks?limit=100');
  const tb = $('#ch tbody');
  tb.innerHTML = '';
  (res.rows || []).forEach((row) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${row.id}</td><td>${row.filename}</td><td>${row.page}</td><td>${row.chunk_idx}</td><td>${JSON.stringify(row.meta || {})}</td><td>${row.preview}</td>`;
    tb.appendChild(tr);
  });
};

const extractStatus = $('#extract-status');
if (extractStatus) {
  async function pollExtractJob(jobId) {
    for (;;) {
      const result = await authGet(`/extract/jobs/${jobId}`);
      const job = result.job || {};
      const status = job.status || 'queued';
      const processed = job.processed_files || 0;
      const total = job.total_files || 0;
      extractStatus.textContent = `Job ${jobId}: ${status} (${processed}/${total})`;
      if (['succeeded', 'failed', 'cancelled'].includes(status)) {
        const summary = job.summary || {};
        const backup = summary.backup_dir ? ` | backup: ${summary.backup_dir}` : '';
        extractStatus.textContent = `Job ${jobId}: ${status} (${processed}/${total})${backup}`;
        return job;
      }
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
  }

  $('#run-extract').onclick = async () => {
    extractStatus.textContent = 'Queueing...';
    try {
      const result = await authPost('/extract', { source_scope: 'spreadsheets', execution_mode: 'async', rebuild_mode: 'incremental' });
      if (!result.job_id) {
        extractStatus.textContent = 'No job id returned';
        return;
      }
      await pollExtractJob(result.job_id);
    } catch (err) {
      extractStatus.textContent = 'Failed: ' + (err?.message || err);
    }
  };
}
