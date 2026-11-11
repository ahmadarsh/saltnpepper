'use strict';
const $ = id => document.getElementById(id);
const state = {
  autoSelect: false,
  workspaceStarted: false,
  workspaceBoardId: null,
  workspaceModelIds: new Set(),
  workspaceRunIds: new Set(),
  workspaceName: 'Untitled',
  selectionVersion: 0,
  models: [],
  model: null,
  inventory: [],
  input: new Set(),
  output: new Set(),
  jobs: new Map(),
  runs: [],
  viewer: null,
  hover: null
};

async function api(url, options) {
  const r = await fetch(url, options);
  let data;
  try {
    data = await r.json();
  } catch {
    data = { error: `HTTP ${r.status}` };
  }
  if (!r.ok) {
    throw Error(typeof data.error === 'string' ? data.error : JSON.stringify(data.error || data));
  }
  return data;
}

function toast(message) {
  const e = $('toast');
  if (!e) return;
  e.textContent = message;
  e.classList.add('show');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => e.classList.remove('show'), 5000);
}

function esc(x) {
  return String(x ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  }[c]));
}

function displaySolidName(s) {
  const name = String(s?.name || 'Solid ' + s?.tag);
  if (s?.kicad_pad_id) return name;
  if (s?.kind !== 'pad' || /^(?:input|output)[_\s-]+pad$/i.test(name)) return name;
  const pad = name.match(/(?:^|[_\s-])pad[_\s-]*(\d+|base)?$/i);
  if (!pad) return name;
  return pad[1] && /^\d+$/.test(pad[1]) ? 'Pad ' + pad[1] : 'Pad (base)';
}

function updateStatusBar() {
  const el = $('workspaceStatus');
  if (!el) return;
  if (state.model) {
    el.textContent = `${state.model.filename || 'Model'} · ${state.inventory.length} solids · IN: ${state.input.size} · OUT: ${state.output.size}`;
  } else {
    el.textContent = 'SI Units (mm, V, A, °C) · Ready';
  }
}

async function health() {
  try {
    await api('/api/health');
    $('health').innerHTML = '<i></i> Engine online';
    $('health').classList.remove('offline');
  } catch {
    $('health').innerHTML = '<i></i> Engine offline';
    $('health').classList.add('offline');
  }
}

async function loadModels() {
  try {
    const d = await api('/api/models');
    state.models = (d.models || []).filter(m => state.workspaceModelIds.has(m.id) || (state.workspaceBoardId && m.board_id===state.workspaceBoardId));
    state.models.forEach(m=>state.workspaceModelIds.add(m.id));
    renderModels();
    state.models
      .filter(m => ['queued', 'running'].includes(m.status) && m.job_id)
      .forEach(m => trackJob(m.job_id));
    if (state.autoSelect && !state.model && state.models.length) {
      const ready = state.models.find(m => m.status === 'ready') || state.models[0];
      if (ready) selectModel(ready.id);
    }
  } catch (e) {
    toast('Could not load models: ' + e.message);
  }
}

function renderModels() {
  $('models').innerHTML = state.models.length
    ? state.models.map(m => {
        const count = m.counts?.solids ? ` · ${m.counts.solids} solids` : '';
        return `<div class="model-entry"><button class="model ${state.model?.id === m.id ? 'active' : ''}" type="button" data-model="${esc(m.id)}">
          <span class="model-icon">⬡</span>
          <span>
            <strong>${esc(m.filename)}</strong>
            <small>${esc(m.status || 'available')}${esc(count)}</small>
          </span>
        </button><button class="icon-btn delete-model" type="button" data-delete-model="${esc(m.id)}" aria-label="Delete ${esc(m.filename)}" title="Delete imported geometry">×</button></div>`;
      }).join('')
    : '<p class="muted">No models imported yet.</p>';
  $('models').querySelectorAll('[data-delete-model]').forEach(b => {
    b.onclick = () => deleteSaved('models', b.dataset.deleteModel);
  });
  $('models').querySelectorAll('[data-model]').forEach(b => {
    b.onclick = () => selectModel(b.dataset.model);
  });
}

async function selectModel(id) {
  const version = ++state.selectionVersion;
  try {
    const m = await api('/api/models/' + encodeURIComponent(id));
    if (version !== state.selectionVersion) return;
    state.model = m;
    state.workspaceStarted = true;
    state.workspaceModelIds.add(m.id);
    if(m.board_id)state.workspaceBoardId=m.board_id;
    state.inventory = m.inventory?.solids || [];
    state.input.clear();
    state.output.clear();
    $('modelTitle').textContent = m.filename || 'Model preview';
    $('modelSubtitle').textContent = state.inventory.length
      ? `${state.inventory.length} solids · select port contacts`
      : `Status: ${m.status}`;
    const note = m.inventory?.naming_note || '';
    $('namingNote').textContent = note;
    $('namingNote').hidden = !note;
    renderModels();
    renderSolids();
    renderGroups();
    updateStatusBar();
    loadPreview(id);
    if(typeof workspaceRefreshUI==='function')workspaceRefreshUI();
  } catch (e) {
    toast('Could not open model: ' + e.message);
  }
}

async function upload(file) {
  if (!file) return;
  if (!/\.(step|stp)$/i.test(file.name)) {
    toast('Choose a .step or .stp file.');
    return;
  }
  const uploadVersion=++state.selectionVersion;
  try {
    toast('Uploading ' + file.name + '…');
    const d = await api('/api/models?filename=' + encodeURIComponent(file.name), {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: file
    });
    if(uploadVersion!==state.selectionVersion)return;
    state.workspaceStarted=true;state.workspaceBoardId=null;
    state.workspaceModelIds=new Set([d.model_id]);state.workspaceRunIds.clear();state.jobs.clear();
    if(state.workspaceName==='Untitled')state.workspaceName=file.name.replace(/\.(step|stp)$/i,'');
    trackJob(d.job_id);
    await loadModels();
    await selectModel(d.model_id);
    if(typeof workspaceMarkChanged==='function')workspaceMarkChanged();
  } catch (e) {
    toast('Import failed: ' + e.message);
  }
}

$('file').onchange = e => {
  upload(e.target.files[0]);
  e.target.value = '';
};

const dz = $('dropzone');
dz.ondragover = e => {
  e.preventDefault();
  dz.classList.add('dragging');
};
dz.ondragleave = () => dz.classList.remove('dragging');
dz.ondrop = e => {
  e.preventDefault();
  dz.classList.remove('dragging');
  upload(e.dataTransfer.files[0]);
};
dz.onkeydown = e => {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault();
    $('file').click();
  }
};

$('example').onclick = async () => {
  const version=++state.selectionVersion;
  try {
    const d = await api('/api/models/example', { method: 'POST' });
    if(version!==state.selectionVersion)return;
    state.workspaceStarted=true;state.workspaceBoardId=null;
    state.workspaceModelIds=new Set([d.model_id]);state.workspaceRunIds.clear();state.jobs.clear();
    toast('Importing example copper-bar.step…');
    trackJob(d.job_id);
    await loadModels();
    await selectModel(d.model_id);
  } catch (e) {
    toast('Could not load example: ' + e.message);
  }
};

$('refreshModels').onclick = loadModels;

function clearWorkspace() {
  state.selectionVersion++;
  state.autoSelect = false;
  state.model = null;
  state.inventory = [];
  state.input.clear(); state.output.clear(); state.hover = null;
  state.models=[];state.runs=[];state.jobs.clear();
  state.workspaceBoardId=null;state.workspaceModelIds.clear();state.workspaceRunIds.clear();state.workspaceName='Untitled';state.workspaceStarted=false;
  if(typeof workspaceReset==='function')workspaceReset();
  if (state.viewer) {
    const v = state.viewer;
    for (const b of v.bodies) {
      v.gl.deleteVertexArray(b.vao); v.gl.deleteBuffer(b.vbo); v.gl.deleteBuffer(b.ibo);
    }
    v.bodies = []; v.zoom = 1; v.pan = [0, 0]; v.yaw = -.35; v.pitch = .65;
  }
  $('runForm').reset(); $('advDetails').open = false;
  $('search').value = ''; $('allSolids').checked = false; $('hideOthers').checked = false;
  $('modelTitle').textContent = 'Model preview';
  $('modelSubtitle').textContent = 'Select a processed model to begin.';
  $('namingNote').hidden = true;
  $('previewMessage').style.display = 'flex';
  $('previewMessage').innerHTML = '<strong>Ready for geometry</strong><small>Import or select a saved STEP model.</small>';
  $('hoverReadout').innerHTML = '<i></i> 3D CAD PREVIEW';
  renderModels(); renderSolids(); renderGroups(); updateStatusBar(); draw();
  $('result').innerHTML = '<div class="panel result-empty"><h2>No run selected yet.</h2><p>Choose a saved run to inspect its fields.</p><a class="button secondary" href="#runs">Browse runs</a></div>';
  $('runs').innerHTML='<p class="empty">No simulations in this workspace.</p>';
  renderJobs();updateRunsBadge();
  location.hash = '#home';
}
$('clearWorkspace').onclick = () => { clearWorkspace(); toast('Workspace cleared. Saved geometry and runs are retained.'); };

// Native confirm() can be suppressed by embedded webviews. Use an HTML dialog.
function confirmDeletion(message) {
  const dialog = $('deleteDialog');
  if (dialog.open) return Promise.resolve(false);
  $('deleteMessage').textContent = message;
  return new Promise(resolve => {
    dialog.returnValue = 'cancel';
    dialog.addEventListener('close', () => resolve(dialog.returnValue === 'delete'), { once: true });
    dialog.showModal();
    $('cancelDelete').focus();
  });
}

async function deleteSaved(kind, id = '') {
  const item = kind === 'models' ? 'this imported geometry' : id ? 'this simulation run and its files' : 'all saved simulation runs and their files';
  if (!await confirmDeletion(`Permanently delete ${item}?`)) return;
  try {
    const result = await api('/api/' + kind + (id ? '/' + encodeURIComponent(id) : ''), { method: 'DELETE' });
    for (const job of result.deleted_jobs) state.jobs.delete(job);
    if(kind==='models')result.deleted.forEach(key=>state.workspaceModelIds.delete(key));
    if(kind==='runs')result.deleted.forEach(key=>state.workspaceRunIds.delete(key));
    if (kind === 'models' && result.deleted.includes(state.model?.id)) {
      // Removing geometry does not close its board workspace or lose its runs.
      state.selectionVersion++;state.model=null;state.inventory=[];state.input.clear();state.output.clear();state.hover=null;
      if(state.viewer){for(const b of state.viewer.bodies){state.viewer.gl.deleteVertexArray(b.vao);state.viewer.gl.deleteBuffer(b.vbo);state.viewer.gl.deleteBuffer(b.ibo);}state.viewer.bodies=[];}
      $('modelTitle').textContent='Model preview';$('modelSubtitle').textContent='Add or prepare geometry to continue.';
      $('namingNote').hidden=true;$('previewMessage').style.display='flex';$('previewMessage').innerHTML='<strong>Ready for geometry</strong><small>Saved simulation results are retained in this workspace.</small>';
      if($('kcHandoff'))$('kcHandoff').hidden=true;
      renderSolids();renderGroups();updateStatusBar();draw();
    }
    if (kind === 'runs' && result.deleted.some(key => location.hash === '#results/' + key)) {
      $('result').innerHTML = '<div class="panel result-empty"><h2>Run deleted</h2><p>Choose another run or start a new simulation.</p></div>';
      location.hash = '#runs';
    }
    await Promise.all([loadModels(), loadRuns()]); renderJobs();
    if(typeof workspaceMarkChanged==='function')workspaceMarkChanged();
    toast(`${result.deleted.length} ${kind === 'models' ? 'geometry item(s)' : 'run(s)'} deleted.`);
  } catch (e) { toast(e.message); }
}
$('deleteRuns').onclick = () => deleteSaved('runs');


function setHover(tag) {
  state.hover = tag;
  const readout = $('hoverReadout');
  if (readout) {
    if (tag != null) {
      const s = state.inventory.find(x => Number(x.tag) === tag);
      const role = state.input.has(tag) ? ' [INPUT]' : state.output.has(tag) ? ' [OUTPUT]' : '';
      readout.innerHTML = `<i></i> ${esc(s?.name || 'Solid ' + tag)} · ${esc((s?.kind || 'solid').toUpperCase())}${esc(role)}`;
    } else {
      readout.innerHTML = '<i></i> 3D CAD PREVIEW';
    }
  }
  draw();
}

function renderSolids() {
  const q = $('search').value.toLowerCase();
  const selectable = state.inventory.filter(s => !s.kicad_pad_member);
  const solids = selectable.filter(s =>
    ($('allSolids').checked || s.kind === 'pad') &&
    `${s.name} ${displaySolidName(s)} ${s.tag} ${s.kind}`.toLowerCase().includes(q)
  );
  if ($('solidCountBadge')) {
    $('solidCountBadge').textContent = `${solids.length} / ${selectable.length || 0}`;
  }
  $('solids').innerHTML = solids.length
    ? solids.map(s => {
        const tag = Number(s.tag);
        const isIn = state.input.has(tag);
        const isOut = state.output.has(tag);
        const rowCls = isIn ? 'in-input' : isOut ? 'in-output' : '';
        return `<div class="solid-row ${rowCls}" draggable="true" data-tag="${tag}">
          <span class="solid-dot"></span>
          <span class="solid-name ${s.kind === 'pad' ? 'pad-number' : ''}" title="${esc(s.name)} · Solid ${tag}${s.name_inferred ? ' · Inferred name' : ''}">${esc(displaySolidName(s))}${s.name_inferred ? ' *' : ''}</span>
          ${s.kind !== 'pad' ? `<span class="solid-kind">${esc(s.kind)}</span>` : ''}
          <button class="assign ${isIn ? 'active' : ''}" type="button" data-assign="input" title="Assign to Input">${isIn ? 'IN ✓' : '+ IN'}</button>
          <button class="assign ${isOut ? 'active' : ''}" type="button" data-assign="output" title="Assign to Output">${isOut ? 'OUT ✓' : '+ OUT'}</button>
        </div>`;
      }).join('')
    : `<p class="empty">${state.inventory.length ? 'No matching pads. Try “Show all solids”.' : 'Select a processed model to see its pads.'}</p>`;

  $('solids').querySelectorAll('.solid-row').forEach(row => {
    const tag = Number(row.dataset.tag);
    row.ondragstart = e => {
      e.dataTransfer.setData('text/plain', String(tag));
      e.dataTransfer.effectAllowed = 'copy';
    };
    row.onmouseenter = () => setHover(tag);
    row.onmouseleave = () => setHover(null);
    row.querySelectorAll('[data-assign]').forEach(b => {
      b.onclick = () => assign(tag, b.dataset.assign, true);
    });
  });
}

function assign(tag, group, toggleIfPresent = false) {
  const solid=state.inventory.find(s => Number(s.tag) === tag);
  if (!solid) return;
  tag=Number(solid.kicad_pad_tag??tag);
  if (toggleIfPresent && state[group].has(tag)) {
    state[group].delete(tag);
  } else {
    state[group].add(tag);
    state[group === 'input' ? 'output' : 'input'].delete(tag);
  }
  renderSolids();
  renderGroups();
  updateStatusBar();
  draw();
  if(typeof workspaceMarkChanged==='function')workspaceMarkChanged();
}

function renderGroups() {
  for (const group of ['input', 'output']) {
    const tags = state[group];
    $(group + 'Count').textContent = tags.size;
    $(group + 'Items').innerHTML = tags.size
      ? [...tags].map(tag => {
          const s = state.inventory.find(x => Number(x.tag) === tag);
          return `<div class="chip" data-chip-tag="${tag}" title="${esc(s?.name || 'Solid ' + tag)} · Solid ${tag}">
            <span>${esc(displaySolidName(s || {tag}))}</span>
            <button type="button" data-remove="${tag}" aria-label="Remove ${esc(s?.name || tag)} from ${group}">×</button>
          </div>`;
        }).join('')
      : `<p>Drop ${group} pads here</p>`;

    $(group + 'Items').querySelectorAll('.chip').forEach(chip => {
      const tag = Number(chip.dataset.chipTag);
      chip.onmouseenter = () => setHover(tag);
      chip.onmouseleave = () => setHover(null);
    });
    $(group + 'Items').querySelectorAll('[data-remove]').forEach(b => {
      b.onclick = e => {
        e.stopPropagation();
        tags.delete(Number(b.dataset.remove));
        setHover(null);
        renderSolids();
        renderGroups();
        updateStatusBar();
        draw();
      };
    });
  }
}

for (const group of ['input', 'output']) {
  const el = $(group + 'Group');
  el.ondragover = e => {
    e.preventDefault();
    el.classList.add('drag-over');
  };
  el.ondragleave = () => el.classList.remove('drag-over');
  el.ondrop = e => {
    e.preventDefault();
    el.classList.remove('drag-over');
    assign(Number(e.dataTransfer.getData('text/plain')), group);
  };
}

if ($('clearPorts')) {
  $('clearPorts').onclick = () => {
    state.input.clear();
    state.output.clear();
    renderSolids();
    renderGroups();
    updateStatusBar();
    draw();
  };
}

$('search').oninput = renderSolids;
$('allSolids').onchange = renderSolids;
$('hideOthers').onchange = draw;

$('examplePorts').onclick = () => {
  const names = s => String(s.name || '').toLowerCase().replace(/[^a-z0-9]/g, '');
  const ins = state.inventory.filter(s => names(s) === 'inputpad');
  const outs = state.inventory.filter(s => names(s) === 'outputpad');
  if (!ins.length || !outs.length) {
    toast('Example port names were not found in this model. Assign ports manually.');
    return;
  }
  state.input = new Set(ins.map(s => Number(s.tag)));
  state.output = new Set(outs.map(s => Number(s.tag)));
  renderSolids();
  renderGroups();
  updateStatusBar();
  draw();
  toast(`Assigned ${ins.length} input and ${outs.length} output pads.`);
};

$('runForm').onsubmit = async e => {
  e.preventDefault();
  if (!state.model?.id || !state.inventory.length) {
    toast('Select a processed model first.');
    return;
  }
  if (!state.input.size || !state.output.size) {
    toast('Assign at least one input and one output solid.');
    return;
  }
  const f = new FormData(e.target);
  const p = {};
  for (const [k, v] of f) {
    if (k === 'refine') continue;
    p[k] = ['analysis_mode', 'cooling_mode', 'input_face', 'output_face'].includes(k) ? v : Number(v);
  }
  p.refine = e.target.elements.refine.checked;
  if ($('advDetails')) $('advDetails').open = false;
  const modelId=state.model.id;
  try {
    const d = await api('/api/runs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model_id: modelId,
        input_tags: [...state.input],
        output_tags: [...state.output],
        parameters: p
      })
    });
    if(!state.workspaceModelIds.has(modelId))return;
    state.workspaceRunIds.add(d.run_id);
    if(typeof workspaceMarkChanged==='function')workspaceMarkChanged();
    trackJob(d.job_id);
    loadRuns();
    toast('Simulation queued.');
    location.hash = '#runs';
  } catch (err) {
    toast('Could not start simulation: ' + err.message);
  }
};

function trackJob(id) {
  if (!id || state.jobs.has(id)) return;
  state.jobs.set(id, { id, status: 'queued' });
  pollJob(id);
}

async function pollJob(id) {
  if (!state.jobs.has(id)) return;
  try {
    const j = await api('/api/jobs/' + encodeURIComponent(id));
    if (!state.jobs.has(id)) return;
    state.jobs.set(id, j);
    renderJobs();
    if (['queued', 'running'].includes(j.status)) {
      setTimeout(() => pollJob(id), 1200);
    } else {
      await Promise.all([loadModels(), loadRuns()]);
      if (j.kind?.includes('model') && j.status === 'succeeded' && state.model?.id === j.model_id) {
        selectModel(j.model_id);
      }
      if (j.status === 'failed') {
        toast('Job failed: ' + (j.error || j.message || 'See activity for details.'));
      }
    }
  } catch (e) {
    const j = state.jobs.get(id);
    if (j) {
      j.message = 'Waiting for server: ' + e.message;
      renderJobs();
      setTimeout(() => pollJob(id), 3000);
    }
  }
}

function updateRunsBadge() {
  const badge = $('runsBadge');
  if (!badge) return;
  const activeCount = [...state.jobs.values()].filter(j => ['queued', 'running'].includes(j.status)).length;
  const total = activeCount || state.runs.length;
  badge.hidden = total === 0;
  badge.textContent = activeCount ? `${activeCount} live` : String(state.runs.length);
}

function renderJobs() {
  const openLogs = new Set(
    [...document.querySelectorAll('[data-job-log][open]')].map(el => el.dataset.jobLog)
  );
  document.querySelectorAll('[data-job-status]').forEach(el => {
    const j = state.jobs.get(el.dataset.jobStatus);
    if (j) el.textContent = j.status;
  });
  const jobsArr = [...state.jobs.values()].reverse();
  $('jobs').innerHTML = jobsArr.length
    ? jobsArr.map(j => `<div class="job">
        <div class="job-head">
          <div>
            <strong>${esc(j.kind || 'Job')} · ${esc(j.status)}</strong>
            <small>${esc(j.stage || '')} ${esc(j.message || '')}</small>
          </div>
          ${['queued', 'running'].includes(j.status) ? `<button type="button" data-cancel="${esc(j.id)}">Cancel</button>` : ''}
        </div>
        ${j.error ? `<p class="error">${esc(typeof j.error === 'string' ? j.error : JSON.stringify(j.error))}</p>` : ''}
        ${j.log_tail ? `<details data-job-log="${esc(j.id)}" ${openLogs.has(j.id) ? 'open' : ''}><summary>Show worker log</summary><pre>${esc(Array.isArray(j.log_tail) ? j.log_tail.join('\n') : j.log_tail)}</pre></details>` : ''}
      </div>`).join('')
    : '<p class="empty">No active worker jobs in this session.</p>';

  $('jobs').querySelectorAll('[data-cancel]').forEach(b => {
    b.onclick = async () => {
      try {
        await api('/api/jobs/' + encodeURIComponent(b.dataset.cancel) + '/cancel', { method: 'POST' });
        toast('Cancellation requested.');
      } catch (e) {
        toast(e.message);
      }
    };
  });
  updateRunsBadge();
}

async function loadRuns() {
  try {
    const d = await api('/api/runs');
    state.runs = (d.runs || []).filter(r=>state.workspaceRunIds.has(r.id)||state.workspaceModelIds.has(r.model_id)||(state.workspaceBoardId&&r.board_id===state.workspaceBoardId));
    state.runs.forEach(r=>state.workspaceRunIds.add(r.id));
    state.runs
      .filter(r => ['queued', 'running'].includes(r.status) && r.job_id)
      .forEach(r => trackJob(r.job_id));
    $('runs').innerHTML = state.runs.length
      ? state.runs.map(r => `<div class="run-item">
          <div>
            <strong>Run ${esc(String(r.id).slice(0, 12))}</strong>
            <small>
              <span data-job-status="${esc(r.job_id || '')}">${esc(state.jobs.get(r.job_id)?.status || r.status)}</span>
              · ${esc(r.filename || ('model ' + String(r.model_id || '').slice(0, 12)))}
            </small>
          </div>
          <button type="button" data-delete-run="${esc(r.id)}">Delete</button>
          <button type="button" data-run="${esc(r.id)}">Open results ↗</button>
        </div>`).join('')
      : '<p class="empty">No simulations yet. Configure a model and start a run.</p>';
    $('runs').querySelectorAll('[data-delete-run]').forEach(b => {
      b.onclick = () => deleteSaved('runs', b.dataset.deleteRun);
    });
    $('runs').querySelectorAll('[data-run]').forEach(b => {
      b.onclick = () => {
        location.hash = '#results/' + encodeURIComponent(b.dataset.run);
      };
    });
    updateRunsBadge();
  } catch (e) {
    toast('Could not load runs: ' + e.message);
  }
}

$('refreshRuns').onclick = loadRuns;

function metric(label, value, unit, scale = 1) {
  const number = Number(value);
  return `<div class="metric">
    <small>${esc(label)}</small>
    <strong>${value == null || !Number.isFinite(number) ? '--' : (number * scale).toFixed(3)} <span>${esc(unit)}</span></strong>
  </div>`;
}

async function showRun(id) {
  try {
    const r = await api('/api/runs/' + encodeURIComponent(id));
    if (!location.hash.startsWith('#results/' + encodeURIComponent(id))) return;
    const report = r.report || {};
    const links = (r.artifacts || [])
      .map(a => `<a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.name)} &#8599;</a>`)
      .join('');
    const viewer = r.viewer_url
      ? r.viewer_url + (r.viewer_url.includes('?') ? '&' : '?') + 'embedded=1'
      : null;

    $('result').innerHTML = `<div class="result-card">
      <div class="result-top">
        <div class="result-title-group">
          <a href="#runs" class="button secondary compact-btn" title="All runs">&#8592; Runs</a>
          <div>
            <h2>Run ${esc(String(r.id).slice(0, 12))}</h2>
            <small>${esc(r.status)}${r.filename ? ' &middot; ' + esc(r.filename) : ''}</small>
          </div>
        </div>
        ${r.report ? `<div class="metric-grid">
          ${metric('Terminal drop', report.terminal_drop_V, 'mV', 1000)}
          ${metric('Resistance', report.resistance_ohm, 'm\u03a9', 1000)}
          ${metric('Peak temperature', report.maximum_temperature_C, '\u00b0C')}
          ${metric('Joule heating', report.total_joule_power_W, 'mW', 1000)}
        </div>` : ''}
        <div class="result-utilities">
          ${links ? `<details><summary>⬇ Artifacts (${(r.artifacts || []).length})</summary><div class="utility-popover"><div class="artifact-grid">${links}</div></div></details>` : ''}
          ${r.report ? `<details><summary>📄 Report</summary><div class="utility-popover"><pre class="report">${esc(typeof r.report === 'string' ? r.report : JSON.stringify(r.report, null, 2))}</pre></div></details>` : ''}
          ${viewer ? `<a class="button primary compact-btn" href="${esc(r.viewer_url)}" target="_blank" rel="noopener">Open viewer &#8599;</a>` : ''}
        </div>
      </div>
      ${r.error ? `<p class="error">${esc(typeof r.error === 'string' ? r.error : JSON.stringify(r.error))}</p>` : ''}
      ${viewer
        ? `<iframe class="result-frame" title="Simulation result viewer" src="${esc(viewer)}"></iframe>`
        : `<div class="panel result-empty"><h2>Results are not ready yet.</h2><p>Follow the run progress on the Runs page.</p><a href="#runs" class="button secondary">View activity</a></div>`}
    </div>`;

    const frame = $('result').querySelector('iframe');
    if (frame) frame.onload = sendTheme;
  } catch (e) {
    toast('Could not load run: ' + e.message);
  }
}

function decode64(b64, Type) {
  const raw = atob(b64);
  const buf = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) buf[i] = raw.charCodeAt(i);
  return new Type(buf.buffer);
}

function updateGizmo(yaw, pitch) {
  const cy = Math.cos(yaw), sy = Math.sin(yaw);
  const cx = Math.cos(pitch), sx = Math.sin(pitch);
  const axes = [
    { line: 'gx', text: 'gxt', v: [1, 0, 0] },
    { line: 'gy', text: 'gyt', v: [0, 1, 0] },
    { line: 'gz', text: 'gzt', v: [0, 0, 1] }
  ];
  for (const a of axes) {
    const [vx, vy, vz] = a.v;
    const rx = cy * vx - sy * vy;
    const ry0 = sy * vx + cy * vy;
    const ry = cx * ry0 - sx * vz;
    const lEl = $(a.line), tEl = $(a.text);
    if (lEl) {
      lEl.setAttribute('x2', (rx * 20).toFixed(1));
      lEl.setAttribute('y2', (-ry * 20).toFixed(1));
    }
    if (tEl) {
      tEl.setAttribute('x', (rx * 25).toFixed(1));
      tEl.setAttribute('y', (-ry * 25 + 2.5).toFixed(1));
    }
  }
}

function initViewer() {
  const canvas = $('canvas');
  const gl = canvas.getContext('webgl2', { antialias: true, alpha: true });
  if (!gl) return null;

  function shader(type, source) {
    const s = gl.createShader(type);
    gl.shaderSource(s, source);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw Error(gl.getShaderInfoLog(s));
    return s;
  }

  const program = gl.createProgram();
  gl.attachShader(program, shader(gl.VERTEX_SHADER, `#version 300 es
    in vec3 pos;
    uniform float scale;
    uniform float aspect;
    uniform float yaw;
    uniform float pitch;
    uniform float depthScale;
    uniform vec2 pan;
    out vec3 vPos;
    void main() {
      float cy = cos(yaw), sy = sin(yaw), cx = cos(pitch), sx = sin(pitch);
      vec3 p = vec3(cy * pos.x - sy * pos.y, sy * pos.x + cy * pos.y, pos.z);
      p = vec3(p.x, cx * p.y - sx * p.z, sx * p.y + cx * p.z);
      vPos = p;
      gl_Position = vec4(p.x * scale / aspect + pan.x, p.y * scale + pan.y, -p.z * depthScale, 1.0);
    }`));
  gl.attachShader(program, shader(gl.FRAGMENT_SHADER, `#version 300 es
    precision highp float;
    in vec3 vPos;
    uniform vec3 color;
    out vec4 outColor;
    void main() {
      vec3 n = normalize(cross(dFdx(vPos), dFdy(vPos)));
      float diff = abs(dot(n, normalize(vec3(0.35, -0.45, 0.82))));
      float rim = abs(dot(n, normalize(vec3(-0.5, 0.5, 0.7))));
      vec3 shaded = color * (0.52 + 0.42 * diff + 0.12 * rim);
      outColor = vec4(clamp(shaded, 0.0, 1.0), 1.0);
    }`));
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw Error(gl.getProgramInfoLog(program));
  gl.useProgram(program);
  gl.enable(gl.DEPTH_TEST);

  const v = {
    gl,
    program,
    canvas,
    bodies: [],
    yaw: -0.35,
    pitch: 0.55,
    zoom: 1,
    pan: [0, 0],
    baseScale: 1,
    depthScale: 1,
    maxRenderSize: Math.min(gl.getParameter(gl.MAX_RENDERBUFFER_SIZE), ...gl.getParameter(gl.MAX_VIEWPORT_DIMS))
  };

  canvas.onpointerdown = e => {
    canvas.setPointerCapture(e.pointerId);
    v.drag = { x: e.clientX, y: e.clientY, isPan: e.shiftKey || e.button === 2 };
  };
  canvas.onpointermove = e => {
    if (!v.drag) return;
    const dx = e.clientX - v.drag.x;
    const dy = e.clientY - v.drag.y;
    if (v.drag.isPan) {
      const rect = canvas.getBoundingClientRect();
      v.pan[0] += (2 * dx) / Math.max(1, rect.width);
      v.pan[1] -= (2 * dy) / Math.max(1, rect.height);
    } else {
      v.yaw += dx * 0.01;
      v.pitch = Math.max(-Math.PI, Math.min(Math.PI, v.pitch + dy * 0.01));
    }
    v.drag.x = e.clientX;
    v.drag.y = e.clientY;
    draw();
  };
  canvas.onpointerup = canvas.onpointercancel = () => {
    v.drag = null;
  };
  canvas.oncontextmenu = e => e.preventDefault();
  canvas.addEventListener('wheel', e => {
    e.preventDefault();
    v.zoom = Math.max(0.1, Math.min(25, v.zoom * Math.exp(-e.deltaY * 0.0012)));
    draw();
  }, { passive: false });

  if (typeof ResizeObserver !== 'undefined') {
    new ResizeObserver(() => requestAnimationFrame(draw)).observe(canvas);
  }
  window.addEventListener('resize', draw);
  return v;
}

async function loadPreview(id) {
  $('previewMessage').style.display = 'flex';
  $('previewMessage').innerHTML = '<span class="preview-symbol">⌬</span><strong>Preparing 3D preview</strong><small>Loading model geometry…</small>';
  if (state.viewer) {
    for (const b of state.viewer.bodies) {
      state.viewer.gl.deleteVertexArray(b.vao);
      state.viewer.gl.deleteBuffer(b.vbo);
      state.viewer.gl.deleteBuffer(b.ibo);
    }
    state.viewer.bodies = [];
    draw();
  }
  try {
    const d = await api('/api/models/' + encodeURIComponent(id) + '/preview.json');
    if (state.model?.id !== id) return;
    if (!state.viewer) state.viewer = initViewer();
    const v = state.viewer;
    if (!v) throw Error('WebGL 2 is unavailable in this browser.');
    const gl = v.gl;
    let extent = 0;
    for (const body of d.bodies || []) {
      const verts = decode64(body.vertices_b64, Float32Array);
      for (let i = 0; i < verts.length; i++) extent = Math.max(extent, Math.abs(verts[i]) * 2);
      const indices = decode64(body.triangles_b64, Uint32Array);
      const vao = gl.createVertexArray();
      const vbo = gl.createBuffer();
      const ibo = gl.createBuffer();
      gl.bindVertexArray(vao);
      gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
      gl.bufferData(gl.ARRAY_BUFFER, verts, gl.STATIC_DRAW);
      const loc = gl.getAttribLocation(v.program, 'pos');
      gl.enableVertexAttribArray(loc);
      gl.vertexAttribPointer(loc, 3, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ibo);
      gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, indices, gl.STATIC_DRAW);
      v.bodies.push({ tag: Number(body.tag), kind: body.kind, vao, vbo, ibo, count: indices.length });
    }
    if (!Number.isFinite(extent) || extent <= 0) extent = 1;
    v.baseScale = 1.65 / extent;
    // Rotation depth is bounded by model size, independently of screen zoom.
    v.depthScale = .9 / extent;
    v.zoom = 1;
    v.pan = [0, 0];
    $('previewMessage').style.display = v.bodies.length ? 'none' : 'flex';
    if (!v.bodies.length) {
      $('previewMessage').innerHTML = '<strong>No preview geometry available</strong>';
    }
    draw();
  } catch (e) {
    if (state.model?.id !== id) return;
    $('previewMessage').innerHTML = `<strong>Preview unavailable</strong><small>${esc(e.message)}. You can still assign ports and run a simulation.</small>`;
  }
}

function draw() {
  const v = state.viewer;
  if (!v) return;
  const { gl, canvas, program } = v;
  const pixelRatio = Math.min(Math.max(window.devicePixelRatio || 1, 1.5),
    v.maxRenderSize / Math.max(1, canvas.clientWidth), v.maxRenderSize / Math.max(1, canvas.clientHeight));
  v.renderPixelRatio = pixelRatio;
  const w = Math.max(1, Math.floor(canvas.clientWidth * pixelRatio));
  const h = Math.max(1, Math.floor(canvas.clientHeight * pixelRatio));
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
  }
  gl.viewport(0, 0, w, h);
  gl.clearColor(0, 0, 0, 0);
  gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
  gl.useProgram(program);
  gl.enable(gl.DEPTH_TEST);
  gl.depthFunc(gl.LEQUAL);
  gl.uniform1f(gl.getUniformLocation(program, 'scale'), v.baseScale * v.zoom * Math.min(1, w / h));
  gl.uniform1f(gl.getUniformLocation(program, 'aspect'), w / h);
  gl.uniform1f(gl.getUniformLocation(program, 'yaw'), v.yaw);
  gl.uniform1f(gl.getUniformLocation(program, 'pitch'), v.pitch);
  gl.uniform1f(gl.getUniformLocation(program, 'depthScale'), v.depthScale);
  gl.uniform2fv(gl.getUniformLocation(program, 'pan'), v.pan);
  updateGizmo(v.yaw, v.pitch);

  for (const selectedPass of [false, true]) {
    if (selectedPass) {
      gl.enable(gl.POLYGON_OFFSET_FILL);
      gl.polygonOffset(-1, -1);
    } else gl.disable(gl.POLYGON_OFFSET_FILL);
    for (const b of v.bodies) {
    const input = state.input.has(b.tag);
    const output = state.output.has(b.tag);
    if ((input || output) !== selectedPass) continue;
    if ($('hideOthers').checked && !input && !output && state.hover !== b.tag) continue;
    const col = input ? [1, 0.04, 0.09]
      : output ? [0.04, 0.25, 1]
      : state.hover === b.tag ? [0.98, 0.92, 0.42]
      : b.kind === 'pad' ? [0.80, 0.58, 0.36] : [0.64, 0.43, 0.25];
    gl.uniform3fv(gl.getUniformLocation(program, 'color'), col);
    gl.bindVertexArray(b.vao);
    gl.drawElements(gl.TRIANGLES, b.count, gl.UNSIGNED_INT, 0);
    }
  }
  gl.disable(gl.POLYGON_OFFSET_FILL);
}

document.querySelectorAll('[data-view]').forEach(b => {
  b.onclick = () => {
    const v = state.viewer;
    if (!v) return;
    const mode = b.dataset.view;
    if (mode === 'top') {
      v.yaw = 0;
      v.pitch = 0;
      v.pan = [0, 0];
    } else if (mode === 'bottom') {
      v.yaw = 0;
      v.pitch = Math.PI;
      v.pan = [0, 0];
    } else if (mode === 'iso') {
      v.yaw = -0.35;
      v.pitch = 0.55;
      v.pan = [0, 0];
    } else if (mode === 'zoom-in') {
      v.zoom = Math.min(25, v.zoom * 1.25);
    } else if (mode === 'zoom-out') {
      v.zoom = Math.max(0.1, v.zoom / 1.25);
    } else {
      v.yaw = -0.35;
      v.pitch = 0.55;
      v.zoom = 1;
      v.pan = [0, 0];
    }
    draw();
  };
});

// Close popovers on outside click or Escape
document.addEventListener('click', e => {
  document.querySelectorAll('details[open]').forEach(d => {
    if ((d.classList.contains('adv-popover') || d.closest('.result-utilities')) && !d.contains(e.target)) {
      d.open = false;
    }
  });
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    document.querySelectorAll('details[open]').forEach(d => {
      if (d.classList.contains('adv-popover') || d.closest('.result-utilities')) d.open = false;
    });
  }
});

let currentTheme = 'salt';
function sendTheme() {
  const frame = $('result').querySelector('iframe');
  if (frame?.contentWindow) {
    frame.contentWindow.postMessage({ type: 'salt-pepper-theme', theme: currentTheme }, location.origin);
  }
}

function setTheme(theme) {
  currentTheme = theme === 'pepper' ? 'pepper' : 'salt';
  document.documentElement.dataset.theme = currentTheme;
  document.querySelectorAll('[data-theme-choice]').forEach(b => {
    b.setAttribute('aria-pressed', String(b.dataset.themeChoice === currentTheme));
  });
  try {
    localStorage.setItem('salt-pepper-theme', currentTheme);
  } catch {}
  sendTheme();
  draw();
}

document.querySelectorAll('[data-theme-choice]').forEach(b => {
  b.onclick = () => setTheme(b.dataset.themeChoice);
});

try {
  setTheme(localStorage.getItem('salt-pepper-theme'));
} catch {
  setTheme('salt');
}

function route() {
  const parts = location.hash.slice(1).split('/');
  const requested = ['home', 'setup', 'kicad', 'runs', 'results'].includes(parts[0]) ? parts[0] : 'home';
  const view=state.workspaceStarted?requested:'home';
  if(!state.workspaceStarted&&location.hash!=='#home')history.replaceState(null,'','#home');
  for (const name of ['home', 'setup', 'kicad', 'runs', 'results']) {
    $(name + 'View').hidden = name !== view;
    const nav = document.querySelector(`[data-nav="${name}"]`);
    if (nav) {
      nav.classList.toggle('active', name === view);
      if (name === view) nav.setAttribute('aria-current', 'page');
      else nav.removeAttribute('aria-current');
    }
  }
  if ($('example')) $('example').hidden = view !== 'setup';
  if (view === 'results' && parts[1]) {
    showRun(decodeURIComponent(parts[1]));
  } else if (view === 'results') {
    const latestRun = state.runs.find(r => r.status === 'succeeded');
    if (latestRun) {
      location.hash = '#results/' + encodeURIComponent(latestRun.id);
      return;
    }
    $('result').innerHTML = `<div class="panel result-empty">
      <h2>No run selected yet.</h2>
      <p>Choose a completed run to explore its 3D fields, terminal metrics, and mesh artifacts.</p>
      <div class="empty-actions">
        <a class="button primary" href="#runs">Browse runs &#8599;</a>
        <a class="button secondary" href="#setup">Back to setup</a>
      </div>
    </div>`;
  }
  if (view === 'setup') requestAnimationFrame(draw);
}

window.addEventListener('hashchange', route);
route();

const welcome = $('welcome');
function dismissWelcome() {
  welcome.classList.add('dismissed');
  welcome.setAttribute('aria-hidden', 'true');
  try {
    sessionStorage.setItem('salt-pepper-intro', 'seen');
  } catch {}
}
$('skipWelcome').onclick = dismissWelcome;
// Startup goes straight to the explicit New / Open workspace choices.
dismissWelcome();

health();
loadModels();
loadRuns().then(() => {
  if (location.hash === '#results') route();
});
setInterval(health, 15000);

const accents = ['mint', 'cyan', 'violet', 'rose', 'amber'];
const savedAccent = localStorage.getItem('sp-accent');
$('accentColour').value = accents.includes(savedAccent) ? savedAccent : 'mint';
document.documentElement.dataset.accent = $('accentColour').value;
$('accentColour').onchange = e => {
  document.documentElement.dataset.accent = e.target.value;
  localStorage.setItem('sp-accent', e.target.value);
};
