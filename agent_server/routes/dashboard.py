"""Dashboard route — serves inline HTML for the sim control UI."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["dashboard"])


@router.get("/", response_class=HTMLResponse)
async def dashboard():
    return DASHBOARD_HTML


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Sim Agent Server</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #1a1a2e; color: #eee; padding: 24px; }
  h1 { margin-bottom: 16px; }

  /* Scene control row — full-width card with status left, button right */
  .scene-bar {
    background: #16213e; border-radius: 8px; padding: 14px 18px;
    margin-bottom: 16px;
    display: flex; align-items: center; justify-content: space-between;
  }
  .scene-bar .scene-status { display: flex; align-items: center; gap: 8px; font-size: 14px; }
  .scene-bar .scene-status .label { color: #888; font-size: 12px; text-transform: uppercase; }

  /* State cards */
  .row { display: flex; gap: 16px; margin-bottom: 16px; flex-wrap: wrap; }
  .card {
    background: #16213e; border-radius: 8px; padding: 16px;
    flex: 1; min-width: 180px;
  }
  .card h3 { font-size: 13px; text-transform: uppercase; color: #888; margin-bottom: 10px; }
  .card .value { font-size: 20px; font-weight: 600; font-family: 'SF Mono', 'Menlo', monospace; }
  .card .label { font-size: 11px; color: #666; margin-top: 2px; }

  /* Lease badge */
  .badge {
    display: inline-block; padding: 3px 10px; border-radius: 12px;
    font-size: 12px; font-weight: 600; text-transform: uppercase;
  }
  .badge.free, .badge.idle, .badge.completed { background: #1b5e20; color: #a5d6a7; }
  .badge.held, .badge.running { background: #b71c1c; color: #ef9a9a; }
  .badge.resetting, .badge.stopped { background: #e65100; color: #ffcc80; }
  .badge.error { background: #880e4f; color: #f48fb1; }


  /* Service table (matches original dashboard) */
  table { width: 100%; border-collapse: collapse; margin-bottom: 16px; }
  th, td { padding: 10px 14px; text-align: left; border-bottom: 1px solid #333; }
  th { color: #aaa; font-size: 13px; text-transform: uppercase; }
  .dot { display: inline-block; width: 12px; height: 12px; border-radius: 50%; margin-right: 6px; }
  .dot.on  { background: #4caf50; box-shadow: 0 0 6px #4caf50; }
  .dot.off { background: #f44336; }

  /* Buttons */
  button { padding: 6px 16px; border: none; border-radius: 4px; cursor: pointer;
           font-size: 13px; font-weight: 500; color: #fff; }
  button:hover { opacity: 0.85; }
  button:disabled { opacity: .35; cursor: default; }
  .btn-start { background: #388e3c; }
  .btn-stop  { background: #c62828; }
  .btn-reset { background: #1565c0; }


  /* Execution list */
  .exec-item {
    background: #0d1527; border-radius: 6px; padding: 10px 14px;
    margin-bottom: 8px; border-left: 3px solid #388e3c;
  }
  .exec-item.running { border-left-color: #c62828; }
  .exec-item.error { border-left-color: #880e4f; }
  .exec-item.stopped { border-left-color: #e65100; }
  .exec-item .exec-header {
    display: flex; align-items: center; gap: 10px; margin-bottom: 6px;
  }
  .exec-item .exec-cols {
    display: flex; gap: 12px; flex-wrap: wrap;
  }
  .exec-item .exec-col {
    flex: 1; min-width: 200px;
  }
  .exec-item .exec-col h4 {
    font-size: 11px; text-transform: uppercase; color: #666;
    margin-bottom: 4px;
  }
  .exec-item .log-box {
    max-height: 120px; font-size: 11px; margin: 0;
  }
  .exec-item .log-box.collapsed { max-height: 80px; }
  .exec-item .expand-btn {
    background: none; border: none; color: #4caf50; cursor: pointer;
    font-size: 11px; padding: 0; margin-left: 6px;
  }

  /* Camera panels */
  .cam-row { display: flex; gap: 16px; margin-bottom: 16px; flex-wrap: wrap; }
  .cam-card {
    background: #16213e; border-radius: 8px; padding: 12px;
    flex: 1; min-width: 260px; text-align: center;
  }
  .cam-card h3 { font-size: 13px; text-transform: uppercase; color: #888; margin-bottom: 8px; }
  .cam-card img {
    width: 256px; height: 256px; border-radius: 4px;
    background: #000; display: block; margin: 0 auto;
  }

  /* Log / output boxes */
  .log-title { font-weight: bold; margin-bottom: 4px; font-size: 14px; }
  .log-box {
    background: #111; padding: 10px; border-radius: 4px;
    max-height: 260px; overflow-y: auto;
    font-family: 'SF Mono', 'Menlo', monospace; font-size: 12px;
    white-space: pre-wrap; color: #ccc; line-height: 1.5;
  }
</style></head><body>

<h1>Sim Agent Server</h1>

<!-- Scene control row: status on left, rewind/reset on right -->
<div class="scene-bar">
  <div class="scene-status">
    <span id="scene-dot" class="dot off"></span>
    <div>
      <div id="scene-label">Scene not loaded</div>
      <div class="label">Scene Status</div>
    </div>
  </div>
  <button id="btn-reset" class="btn-reset" onclick="resetScene()" disabled>Reset Scene</button>
</div>

<!-- Camera views -->
<div class="cam-row" id="cam-row" style="display:none;">
  <div class="cam-card">
    <h3>Agent View</h3>
    <img id="cam-agent" alt="Agent View">
  </div>
  <div class="cam-card">
    <h3>Wrist Camera</h3>
    <img id="cam-wrist" alt="Wrist Camera">
  </div>
</div>

<!-- Robot State cards -->
<div class="row">
  <div class="card">
    <h3>Base Pose</h3>
    <div><span class="value" id="base-x">&mdash;</span> <span class="label">X (m)</span></div>
    <div><span class="value" id="base-y">&mdash;</span> <span class="label">Y (m)</span></div>
    <div><span class="value" id="base-theta">&mdash;</span> <span class="label">&theta; (rad)</span></div>
  </div>
  <div class="card">
    <h3>End Effector</h3>
    <div><span class="value" id="ee-x">&mdash;</span> <span class="label">X (m)</span></div>
    <div><span class="value" id="ee-y">&mdash;</span> <span class="label">Y (m)</span></div>
    <div><span class="value" id="ee-z">&mdash;</span> <span class="label">Z (m)</span></div>
  </div>
  <div class="card">
    <h3>Gripper</h3>
    <div><span class="value" id="grip-pos">&mdash;</span> <span class="label">Width</span></div>
    <div><span class="value" id="grip-state">&mdash;</span> <span class="label">State</span></div>
  </div>
</div>

<!-- Lease row -->
<div class="row">
  <div class="card" style="flex: 2;">
    <h3>Lease</h3>
    <div style="display:flex; align-items:center; gap:12px;">
      <span id="lease-badge" class="badge free">Free</span>
      <span style="font-size:14px;">Holder: <strong id="lease-holder">none</strong></span>
    </div>
    <div style="margin-top:8px; font-size:13px; color:#aaa;">
      Remaining: <span id="lease-remaining">&mdash;</span>s
      &nbsp;|&nbsp; Idle: <span id="lease-idle">&mdash;</span>s
    </div>
    <div id="lease-actions" style="margin-top:10px; display:none;">
      <button class="btn-stop" onclick="releaseLease()" style="font-size:12px; padding:4px 12px;">Release Lease</button>
    </div>
  </div>
</div>

<!-- Code Execution History -->
<div class="card" style="margin-bottom:16px;">
  <h3 style="margin-bottom:10px;">Code Executions</h3>
  <div id="exec-list">(no executions)</div>
</div>

<!-- Service table (like original dashboard) -->
<table>
  <thead><tr><th>Service</th><th>Status</th><th>Uptime</th><th>Action</th></tr></thead>
  <tbody id="tbl"></tbody>
</table>

<!-- Log output -->
<div class="log-title">Simulation Output</div>
<div class="log-box" id="log-box">(no output)</div>

<script>
let simRunning = false;
let hasCameras = false;
let currentLeaseId = null;

function fmtUptime(s) {
  if (s == null) return "\u2014";
  let m = Math.floor(s / 60), sec = s % 60;
  return m + "m " + sec + "s";
}

async function api(method, path, body, headers) {
  const opts = { method };
  if (body) {
    opts.headers = {'Content-Type':'application/json', ...(headers || {})};
    opts.body = JSON.stringify(body);
  } else if (headers) {
    opts.headers = headers;
  }
  const r = await fetch(path, opts);
  return r.json();
}

let execItems = [];
let expandedItems = {};

function toggleExpand(id) {
  expandedItems[id] = !expandedItems[id];
  renderExecList();
}

function esc(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

function renderExecList() {
  const el = document.getElementById('exec-list');
  if (!execItems.length) { el.innerHTML = '<div style="color:#666;font-size:13px;">(no executions)</div>'; return; }
  el.innerHTML = execItems.map(item => {
    const id = item.execution_id;
    const expanded = expandedItems[id];
    const status = item.status || 'idle';
    const label = status.charAt(0).toUpperCase() + status.slice(1);
    const out = (item.stdout || '') + (item.stderr ? '\n[stderr] ' + item.stderr : '') || '(no output)';
    const code = item.code || '(none)';
    const duration = item.duration != null ? item.duration + 's' : '';
    const stopBtn = item._current ? ' <button class="btn-stop" onclick="stopCode()" style="font-size:11px;padding:2px 10px;">Stop</button>' : '';
    const toggle = `<button class="expand-btn" onclick="toggleExpand('${id}')">[${expanded?'collapse':'expand'}]</button>`;
    const detail = expanded ? `<div class="exec-cols">
        <div class="exec-col"><h4>Output</h4><div class="log-box">${esc(out)}</div></div>
        <div class="exec-col"><h4>Code</h4><div class="log-box">${esc(code)}</div></div>
      </div>` : '';
    return `<div class="exec-item ${status}">
      <div class="exec-header">
        <span class="badge ${status}" style="font-size:11px;padding:2px 8px;">${label}</span>
        <span style="font-size:12px;color:#aaa;font-family:monospace;">${id}</span>
        ${duration ? '<span style="font-size:12px;color:#666;">' + duration + '</span>' : ''}
        ${stopBtn}
        ${toggle}
      </div>
      ${detail}
    </div>`;
  }).join('');
}

async function releaseLease() {
  const ls = await api('GET', '/api/lease/status');
  if (ls.lease_id) {
    await api('POST', '/api/lease/release', {lease_id: ls.lease_id});
  }
  poll();
}

async function stopCode() {
  const ls = await api('GET', '/api/lease/status');
  if (ls.lease_id) {
    await api('POST', '/api/code/stop', {reason: 'dashboard'}, {'X-Lease-Id': ls.lease_id});
  }
  poll();
}

async function startSim(gui) {
  document.querySelectorAll('#tbl button').forEach(b => b.disabled = true);
  await api('POST', '/api/start', {gui});
  poll();
}

async function stopSim() {
  document.querySelectorAll('#tbl button').forEach(b => b.disabled = true);
  await api('POST', '/api/stop');
  poll();
}

async function resetScene() {
  const btn = document.getElementById('btn-reset');
  btn.disabled = true;
  await api('POST', '/api/reset');
  btn.disabled = false;
  poll();
}

async function poll() {
  try {
    // Sim status
    const sim = await api('GET', '/api/sim_status');
    simRunning = sim.running;
    hasCameras = sim.has_cameras;
    const on = simRunning;

    // Render service table row
    const actions = on
      ? '<button class="btn-stop" onclick="stopSim()">Stop</button>'
      : '<button class="btn-start" onclick="startSim(false)" style="margin-right:8px;">Server Only</button>'
        + '<button class="btn-start" onclick="startSim(true)" style="background:#1565c0;">Server + GUI</button>';
    document.getElementById('tbl').innerHTML = `<tr>
      <td><span class="dot ${on?'on':'off'}"></span>Simulation</td>
      <td>${on ? 'Running' : 'Stopped'}</td>
      <td>${fmtUptime(sim.uptime)}</td>
      <td>${actions}</td>
    </tr>`;

    document.getElementById('btn-reset').disabled = !on;
    document.getElementById('scene-dot').className = 'dot ' + (on ? 'on' : 'off');
    document.getElementById('scene-label').textContent = on ? 'Scene loaded' : 'Scene not loaded';

    // Robot state
    if (on) {
      try {
        const st = await api('GET', '/api/state');
        document.getElementById('base-x').textContent = st.base.x.toFixed(3);
        document.getElementById('base-y').textContent = st.base.y.toFixed(3);
        document.getElementById('base-theta').textContent = st.base.theta.toFixed(3);
        document.getElementById('ee-x').textContent = st.ee.x.toFixed(3);
        document.getElementById('ee-y').textContent = st.ee.y.toFixed(3);
        document.getElementById('ee-z').textContent = st.ee.z.toFixed(3);
        document.getElementById('grip-pos').textContent = st.gripper.position.toFixed(4);
        document.getElementById('grip-state').textContent = st.gripper.closed ? 'Closed' : 'Open';
      } catch(e) {}
    } else {
      ['base-x','base-y','base-theta','ee-x','ee-y','ee-z','grip-pos','grip-state']
        .forEach(id => document.getElementById(id).textContent = '\u2014');
    }

    // Lease
    const ls = await api('GET', '/api/lease/status');
    const leaseBadge = document.getElementById('lease-badge');
    leaseBadge.textContent = ls.state.charAt(0).toUpperCase() + ls.state.slice(1);
    leaseBadge.className = 'badge ' + ls.state;
    document.getElementById('lease-holder').textContent = ls.holder || 'none';
    document.getElementById('lease-remaining').textContent = ls.remaining ?? '\u2014';
    document.getElementById('lease-idle').textContent = ls.idle ?? '\u2014';
    document.getElementById('lease-actions').style.display = ls.state === 'held' ? 'block' : 'none';

    // Track lease — clear our local ref if lease was revoked
    if (ls.state === 'free' || ls.state === 'resetting') {
      if (currentLeaseId && ls.lease_id !== currentLeaseId) {
        currentLeaseId = null;
      }
    }

    // Code execution history + current
    try {
      const [cs, hist] = await Promise.all([
        api('GET', '/api/code/status?stdout_offset=0&stderr_offset=0'),
        api('GET', '/api/code/history'),
      ]);
      // Build list: current running on top, then history
      let items = [];
      if (cs.status === 'running') {
        items.push({...cs, _current: true});
      }
      if (hist.ok && hist.history) {
        for (const h of hist.history) {
          if (cs.status === 'running' && h.execution_id === cs.execution_id) continue;
          items.push(h);
        }
      }
      execItems = items;
      renderExecList();
    } catch(e) {}

    // Logs
    try {
      const logData = await api('GET', '/api/logs');
      const el = document.getElementById('log-box');
      const content = logData.logs.map(l => l.replace(/</g, '&lt;')).join('\n') || '(no output)';
      const wasAtBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 10;
      el.innerHTML = content;
      if (wasAtBottom) el.scrollTop = el.scrollHeight;
    } catch(e) {}

  } catch(e) { console.error('poll error:', e); }
}

poll();
setInterval(poll, 2000);

// Camera streams — connect/disconnect MJPEG streams based on sim state
let camsActive = false;
function updateCameras() {
  const row = document.getElementById('cam-row');
  if (simRunning && hasCameras && !camsActive) {
    row.style.display = 'flex';
    document.getElementById('cam-agent').src = '/api/camera/robot0_agentview_center/stream';
    document.getElementById('cam-wrist').src = '/api/camera/robot0_eye_in_hand/stream';
    camsActive = true;
  } else if ((!simRunning || !hasCameras) && camsActive) {
    document.getElementById('cam-agent').src = '';
    document.getElementById('cam-wrist').src = '';
    row.style.display = 'none';
    camsActive = false;
  }
}
setInterval(updateCameras, 500);


</script>
</body></html>"""
