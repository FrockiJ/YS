let pollTimer = null;
const API_BASE = window.APP_API_PREFIX || "";
const $ = (sel) => document.querySelector(sel);

function pct(done, total) {
  if (!total || total <= 0) {
    return 0;
  }
  return Math.max(0, Math.min(100, Math.round((done / total) * 100)));
}

function fmt(value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  return String(value);
}

function fmtJson(value) {
  if (!value) {
    return "-";
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch (_) {
    return String(value);
  }
}

async function apiGet(url) {
  const resp = await fetch(API_BASE + url);
  const raw = await resp.text();
  let data = null;
  try { data = raw ? JSON.parse(raw) : null; } catch (_) {}
  if (!resp.ok) {
    throw new Error((data && (data.error || data.detail)) || raw || "Request failed");
  }
  return data;
}

function renderJobs(rows) {
  const select = $("#job-select");
  const activeRows = (rows || []).filter((row) => ["running", "queued", "paused"].includes(row.status));
  select.innerHTML = "";
  if (!activeRows.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No active extract jobs";
    select.appendChild(option);
    return;
  }
  activeRows
    .sort((a, b) => {
      const rank = { running: 0, queued: 1, paused: 2, failed: 3, succeeded: 4 };
      return (rank[a.status] ?? 99) - (rank[b.status] ?? 99);
    })
    .forEach((job, idx) => {
      const option = document.createElement("option");
      option.value = job.id;
      option.textContent = `${job.status} | ${job.id} | ${job.processed_files || 0}/${job.total_files || 0}`;
      if (idx === 0) {
        option.selected = true;
      }
      select.appendChild(option);
    });
}

async function loadJobs() {
  const result = await apiGet("/extract/jobs?limit=20");
  renderJobs(result.rows || []);
}

function renderJob(job) {
  const summary = job.summary || {};
  const processed = job.processed_files || 0;
  const total = job.total_files || 0;
  const currentDone = summary.current_items_done ?? null;
  const currentTotal = summary.current_items_total ?? null;
  const hasCurrentProgress = summary.current_file || currentDone !== null || currentTotal !== null;

  $("#files-label").textContent = `Files: ${processed} / ${total}`;
  $("#job-status").textContent = fmt(job.status || "queued");
  $("#files-bar").style.width = `${pct(processed, total)}%`;

  $("#current-file").textContent = fmt(summary.current_file);
  $("#current-phase").textContent = fmt(summary.current_phase);
  $("#current-source-kind").textContent = fmt(summary.current_source_kind);
  $("#current-items").textContent = currentTotal ? `${currentDone || 0} / ${currentTotal}` : fmt(currentDone);
  $("#chunks-done").textContent = fmt(summary.current_chunks_done);
  $("#records-done").textContent = fmt(summary.current_records_done);
  $("#current-bar").style.width = currentTotal ? `${pct(currentDone || 0, currentTotal)}%` : "0%";

  $("#heartbeat-at").textContent = fmt(job.heartbeat_at);
  $("#lease-expires-at").textContent = fmt(job.lease_expires_at);
  $("#attempt-count").textContent = `${fmt(job.attempt_count)} / ${fmt(job.max_attempts)}`;
  $("#success-failed").textContent = `${job.success_files || 0} / ${job.failed_files || 0}`;

  $("#last-result").textContent = fmtJson(summary.last_result);
  $("#job-error").textContent = fmt(job.error);

  if (!hasCurrentProgress && ["running", "queued"].includes(job.status)) {
    $("#job-hint").textContent = "Current File Progress is blank because the running worker has not yet written current_* progress fields. This usually means the job started before the latest monitor patch or is still on coarse file-level progress only.";
  } else {
    $("#job-hint").textContent = "Auto-selects the current running extract job when available.";
  }

  $("#status-line").textContent = `Job ${job.id}: ${fmt(job.status)} (${processed}/${total})`;
}

async function pollJob(jobId) {
  try {
    const result = await apiGet(`/extract/jobs/${jobId}`);
    const job = result.job || {};
    renderJob(job);
    if (["succeeded", "failed", "cancelled"].includes(job.status)) {
      stopPolling();
      await loadJobs();
    }
  } catch (err) {
    $("#status-line").textContent = `Failed: ${err.message || err}`;
  }
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

function startPolling(jobId) {
  stopPolling();
  if (!jobId) {
    $("#status-line").textContent = "No active job selected";
    return;
  }
  pollJob(jobId);
  pollTimer = setInterval(() => pollJob(jobId), 2500);
}

$("#refresh-jobs").onclick = async () => {
  try {
    await loadJobs();
    $("#status-line").textContent = "Jobs refreshed";
  } catch (err) {
    $("#status-line").textContent = `Failed: ${err.message || err}`;
  }
};

$("#load-job").onclick = () => {
  startPolling($("#job-select").value);
};

$("#stop-job").onclick = () => {
  stopPolling();
  $("#status-line").textContent = "Stopped";
};

async function boot() {
  try {
    await loadJobs();
    const first = $("#job-select").value;
    if (first) {
      startPolling(first);
    } else {
      $("#status-line").textContent = "No active extract jobs";
    }
  } catch (err) {
    $("#status-line").textContent = `Failed: ${err.message || err}`;
  }
}

boot();
