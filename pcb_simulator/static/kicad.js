'use strict';
// V0.9 Mac review prototype. Terminal identities come from the PCB, never list order.
const KC = { boardId:null, board:null, filename:'', net:null, pads:[], input:new Set(), output:new Set(), role:'input', exportId:null, busy:false, views:{}, version:0, allNets:true, layers:{}, previewReady:false };
const kcBase = () => '/api/kicad/boards/' + KC.boardId;
const kcProgress = (text,error=false) => { $('kcProgress').textContent=text; $('kcProgress').classList.toggle('error',error); $('kcProgress').classList.toggle('busy',KC.busy&&!error); };
function kcBusy(value) {
  KC.busy=value; $('kcDemo').disabled=value;
  $('kcNets').querySelectorAll('button').forEach(b=>b.disabled=value);
  $('kcPrepare').disabled=value||!KC.net||!KC.input.size||!KC.output.size;
}
async function kcWait(id,version=null) {
  for (let i=0;i<900;i++) {
    if(version!==null&&version!==KC.version)return null;
    const job=await api('/api/jobs/'+id);
    kcProgress(job.message || job.stage || 'Working…');
    if (job.status==='succeeded') return job;
    if (['failed','cancelled'].includes(job.status)) throw Error(job.error||job.message||'Import stopped.');
    await new Promise(r=>setTimeout(r,250));
  }
  throw Error('The export took too long. Check the worker log.');
}
async function kcReadLayers(board,base) {
  const layers={};
  if(board.colour_layers)await Promise.all(['top','bottom'].map(async side=>{
    const r=await fetch(base+'/coloured/'+side+'.svg');if(!r.ok)throw Error('Could not load the copper preview.');
    const doc=new DOMParser().parseFromString(await r.text(),'image/svg+xml');
    if(doc.querySelector('parsererror'))throw Error('The copper preview is invalid.');
    layers[side]=doc.documentElement.innerHTML;
  }));
  return layers;
}
async function kcRestoreBoard(boardId,net,inputIds=[],outputIds=[]) {
  const version=++KC.version,base='/api/kicad/boards/'+boardId;
  const response=await api(base),layers=await kcReadLayers(response.board,base);
  if(version!==KC.version)return;
  KC.boardId=boardId;KC.board=response.board;KC.filename=response.filename;KC.layers=layers;KC.exportId=null;KC.views={};
  KC.net=KC.board.nets.some(n=>n.name===net)?net:null;KC.pads=KC.net?KC.board.pads.filter(p=>p.net===KC.net):[];
  const known=new Set(KC.pads.map(p=>p.id));KC.input=new Set(inputIds.filter(id=>known.has(id)));KC.output=new Set(outputIds.filter(id=>known.has(id)&&!KC.input.has(id)));
  KC.allNets=!KC.net;KC.previewReady=!!layers.top;
  $('kcBoardName').textContent=KC.filename;$('kcNetName').textContent=KC.net||'All nets';$('kcNetInfo').textContent='Restored from workspace';$('kcHandoff').hidden=true;
  $('kcImportTiming').hidden=true;kcRenderNets();kcRenderPads();kcRenderSelections();kcDraw();kcRenderDetails();kcBusy(false);kcProgress('Board and pad selections restored from workspace.');
}
async function kcUpload(file) {
  if (!file||KC.busy)return;
  const importStarted=performance.now();
  $('kcImportTiming').hidden=true;
  kcBusy(true);const version=++KC.version;
  try {
    kcProgress('Reading '+file.name+'…');
    const uploaded=await api('/api/kicad/boards?filename='+encodeURIComponent(file.name),{method:'POST',body:file});
    if(version!==KC.version)return;
    KC.boardId=uploaded.board_id;KC.filename=file.name;
    await kcWait(uploaded.job_id,version);if(version!==KC.version)return;
    const base='/api/kicad/boards/'+uploaded.board_id,response=await api(base),layers=await kcReadLayers(response.board,base);
    if(version!==KC.version)return;
    KC.board=response.board;KC.net=null;KC.pads=[];KC.input.clear();KC.output.clear();KC.views={};KC.allNets=true;KC.layers=layers;KC.previewReady=false;
    state.workspaceStarted=true;state.workspaceBoardId=uploaded.board_id;state.workspaceModelIds.clear();state.workspaceRunIds.clear();state.models=[];state.runs=[];state.jobs.clear();state.model=null;state.inventory=[];state.input.clear();state.output.clear();
    if(state.workspaceName==='Untitled')state.workspaceName=file.name.replace(/\.kicad_pcb$/i,'');
    await Promise.all([loadModels(),loadRuns()]);
    $('kcNetName').textContent='All nets';$('kcNetInfo').textContent='Choose a colour in the net list to pick its terminals.';
    $('kcBoardName').textContent=response.filename;
    $('kcHandoff').hidden=true;
    kcRenderNets();kcRenderPads();kcRenderSelections();kcDraw();kcRenderDetails();
    KC.lastImportSeconds=(performance.now()-importStarted)/1000;
    const timing=KC.board.import_timings;
    $('kcImportTiming').textContent=`Import ${KC.lastImportSeconds.toFixed(2)} s${timing?' · colour '+timing.colour_seconds.toFixed(2)+' s':''}`;
    $('kcImportTiming').hidden=false;
    kcProgress(`${KC.board.nets.length} nets · ${KC.board.pads.length} pad entries · Imported in ${KC.lastImportSeconds.toFixed(2)} s${timing?' · colouring '+timing.colour_seconds.toFixed(2)+' s':''}.`);
    if(typeof workspaceMarkChanged==='function')workspaceMarkChanged();
  } catch(e) {if(version===KC.version)kcProgress(e.message,true);} finally {if(version===KC.version)kcBusy(false);}
}
function kcRenderNets() {
  if(!KC.board)return;
  const query=$('kcNetSearch').value.toLowerCase();
  $('kcNets').innerHTML=KC.board.nets.filter(n=>n.name.toLowerCase().includes(query)).map(n=>`<button type="button" class="kc-net ${KC.net===n.name?'active':''}" style="--net-colour:${n.colour||'var(--accent)'}" title="${esc(n.colour_source||'Automatic colour')}" data-net="${esc(n.name)}" ${KC.busy?'disabled':''}><strong><span class="kc-net-dot" aria-hidden="true"></span>${esc(n.name)}</strong><small>${n.pads} pads · ${n.tracks} tracks · ${n.vias} vias</small></button>`).join('')||'<p class="muted">No matching nets.</p>';
  $('kcNets').querySelectorAll('[data-net]').forEach(b=>b.onclick=()=>kcSelectNet(b.dataset.net));
  const active=$('kcNets').querySelector('.active');if(active)active.scrollIntoView({block:'nearest'});
}
async function kcSelectNet(net) {
  if(KC.busy||!KC.board)return;
  KC.net=net;KC.pads=KC.board.pads.filter(p=>p.net===net);KC.input.clear();KC.output.clear();KC.exportId=null;KC.version++;KC.allNets=false;
  $('kcHandoff').hidden=true;$('kcNetName').textContent=net;
  const info=KC.board.nets.find(n=>n.name===net);
  $('kcNetInfo').textContent=`${info.pads} pads · ${info.tracks} tracks · ${info.vias} vias · ${info.zones} zones`;
  kcBusy(true);kcRenderNets();kcRenderPads();kcRenderSelections();kcDraw();
  if(KC.layers.top&&KC.layers.bottom) {
    KC.previewReady=true;kcBusy(false);kcProgress('Net highlighted instantly. Click pads on either side or use the pad list.');if(typeof workspaceMarkChanged==='function')workspaceMarkChanged();return;
  }
  try {
    const response=await api(kcBase()+'/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({net})});
    await kcWait(response.job_id);KC.exportId=response.export_id;
    kcDraw();kcProgress('Net highlighted. Click pads on either side or use the pad list.');
  } catch(e){kcProgress(e.message,true);}finally{kcBusy(false);}
}
function kcAssign(id,role) {
  if(!KC.pads.some(p=>p.id===id))return;
  const target=KC[role];if(target.has(id))target.delete(id);else{target.add(id);KC[role==='input'?'output':'input'].delete(id);}
  $('kcHandoff').hidden=true;kcRenderPads();kcRenderSelections();kcDraw();kcBusy(KC.busy);
  if(typeof workspaceMarkChanged==='function')workspaceMarkChanged();
}
function kcRenderPads() {
  const query=$('kcPadSearch').value.toLowerCase();
  const pads=KC.pads.filter(p=>(p.label+' '+p.net).toLowerCase().includes(query));
  $('kcPads').innerHTML=pads.length?pads.map(p=>`<div class="kc-pad-row"><div><strong>${esc(p.label)}</strong><small>${esc(p.sides.join(' / '))} · ${esc(p.net)}</small></div><div><button type="button" data-pad="${esc(p.id)}" data-role="input" class="${KC.input.has(p.id)?'is-input':''}">${KC.input.has(p.id)?'IN ✓':'+ IN'}</button><button type="button" data-pad="${esc(p.id)}" data-role="output" class="${KC.output.has(p.id)?'is-output':''}">${KC.output.has(p.id)?'OUT ✓':'+ OUT'}</button></div></div>`).join(''):'<p class="muted">Select a net to see its real pad names.</p>';
  $('kcPads').querySelectorAll('[data-pad]').forEach(b=>b.onclick=()=>kcAssign(b.dataset.pad,b.dataset.role));
}
function kcRenderSelections() {
  for(const role of ['input','output']) {
    $('kc'+(role==='input'?'Inputs':'Outputs')).innerHTML=[...KC[role]].map(id=>{const p=KC.pads.find(p=>p.id===id);return `<button type="button" class="kc-chip" data-remove-pad="${esc(id)}" data-role="${role}" title="Remove ${esc(p.label)}">${esc(p.label)} ×</button>`;}).join('')||'None selected';
  }
  document.querySelectorAll('[data-remove-pad]').forEach(b=>b.onclick=()=>kcAssign(b.dataset.removePad,b.dataset.role));
}
function kcDraw() {
  $('kcAllNets').setAttribute('aria-pressed',String(KC.allNets));
  const netByKey=new Map((KC.board?.nets||[]).map(net=>[net.plot_key,net]));
  for(const side of ['top','bottom']) {
    const svg=$(side==='top'?'kcTop':'kcBottom');
    const canonical=side==='top'?'F.Cu':'B.Cu';
    const layerLabel=svg.closest('.kc-layer').querySelector('.kc-layer-head span');
    layerLabel.textContent=(KC.board?.details?.layer_display_names?.[canonical]||canonical)+(side==='bottom'?' · mirrored':'');
    if(!KC.board){svg.innerHTML='<text x="50%" y="50%" text-anchor="middle" fill="currentColor" opacity=".4" font-size="12">Board preview</text>';continue;}
    const b=KC.board.bounds_mm, initial=[b[0],b[1],b[2]-b[0],b[3]-b[1]];
    if(!KC.views[side])KC.views[side]=[...initial];
    svg.setAttribute('viewBox',KC.views[side].join(' '));
    const imageTransform=side==='bottom'?`translate(${b[0]+b[2]} 0) scale(-1 1)`:'';
    const plot=KC.board.plots[side], size=plot.viewbox;
    const image=(url,cls)=>`<image class="${cls}" href="${url}" x="${size[0]}" y="${size[1]}" width="${size[2]}" height="${size[3]}" transform="${imageTransform}" pointer-events="none"/>`;
    const colours=KC.layers[side]?'':KC.board.nets.filter(n=>n.plot_key).map(n=>{
      const id='net-'+side+'-'+n.plot_key,opacity=KC.allNets||n.name===KC.net?1:.075;
      return `<g class="kc-net-copper" data-colour-net="${esc(n.name)}" opacity="${opacity}" pointer-events="none"><defs><filter id="${id}" x="0" y="0" width="100%" height="100%" color-interpolation-filters="sRGB"><feFlood flood-color="${n.colour}"/><feComposite in2="SourceAlpha" operator="in"/></filter></defs><image href="${kcBase()+'/nets/'+n.plot_key+'/'+side+'.svg'}" x="${size[0]}" y="${size[1]}" width="${size[2]}" height="${size[3]}" transform="${imageTransform}" filter="url(#${id})"/></g>`;
    }).join('');
    const foreground=KC.layers[side]?`<g class="kc-colour-layer" transform="${imageTransform}">${KC.layers[side]}</g>`:colours||(KC.exportId?image(kcBase()+'/exports/'+KC.exportId+'/highlight/'+side+'.svg','kc-highlight'):'');
    const pads=KC.pads.filter(p=>p.sides.includes(side));
    const markers=pads.map(p=>{const x=side==='bottom'?b[0]+b[2]-p.x_mm:p.x_mm;
      const radius=Math.max(...p.size_mm)/2; const [w,h]=p.size_mm; const angle=(side==='bottom'?1:-1)*(p.angle_deg||0); const shape=p.shape==='circle'||p.shape==='oval'?`<ellipse class="kc-pad-shape" rx="${w/2}" ry="${h/2}"/>`:`<rect class="kc-pad-shape" x="${-w/2}" y="${-h/2}" width="${w}" height="${h}" rx="${p.shape==='roundrect'?Math.min(w,h)*.18:0}"/>`;
      const selected=KC.input.has(p.id)?'is-input':KC.output.has(p.id)?'is-output':'';
      return `<g class="kc-pad-hit ${selected}" data-pad-id="${esc(p.id)}" tabindex="0" role="button" aria-label="Assign ${esc(p.label)} on ${side}" transform="translate(${x} ${p.y_mm})"><title>${esc(p.label)} · ${esc(p.net)} · ${side}</title><g transform="rotate(${angle})">${shape}</g><text y="${-radius-.35}" text-anchor="middle">${esc(p.reference+'.'+p.number)}</text></g>`;}).join('');
    if(!KC.layers[side]||svg.dataset.boardId!==KC.boardId||!svg.querySelector('.kc-markers')) {
      svg.innerHTML=image(kcBase()+'/full/'+side+'.svg','kc-native')+foreground+'<g class="kc-markers"></g>';
      svg.dataset.boardId=KC.boardId;
    }
    svg.querySelector('.kc-markers').innerHTML=markers;
    svg.querySelectorAll('[data-net-key]').forEach(group=>{
      const net=netByKey.get(group.dataset.netKey);if(!net)return;
      group.classList.add('kc-net-copper');group.dataset.colourNet=net.name;group.style.color=net.colour;
      group.style.opacity=KC.allNets||KC.net===net.name?'1':'.075';
    });
    svg.querySelectorAll('[data-pad-id]').forEach(p=>{p.onclick=()=>kcAssign(p.dataset.padId,KC.role);p.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();kcAssign(p.dataset.padId,KC.role);}};});
  }
}
for(const side of ['top','bottom']) {
  const svg=$(side==='top'?'kcTop':'kcBottom');let drag=null;
  const point=e=>new DOMPoint(e.clientX,e.clientY).matrixTransform(svg.getScreenCTM().inverse());
  svg.addEventListener('wheel',e=>{if(!KC.board)return;e.preventDefault();const v=KC.views[side],factor=Math.exp(Math.max(-.3,Math.min(.3,e.deltaY*.0015))),width=v[2]*factor;if(width<1||width>500)return;const p=point(e);v[0]=p.x-(p.x-v[0])*factor;v[1]=p.y-(p.y-v[1])*factor;v[2]*=factor;v[3]*=factor;svg.setAttribute('viewBox',v.join(' '));},{passive:false});
  svg.onpointerdown=e=>{if(e.target.closest('[data-pad-id]')||!KC.board)return;svg.setPointerCapture(e.pointerId);drag={x:e.clientX,y:e.clientY};};
  svg.onpointermove=e=>{if(!drag)return;const v=KC.views[side],before=point({clientX:drag.x,clientY:drag.y}),after=point(e);v[0]-=after.x-before.x;v[1]-=after.y-before.y;drag={x:e.clientX,y:e.clientY};svg.setAttribute('viewBox',v.join(' '));};
  svg.onpointerup=svg.onpointercancel=()=>{drag=null;};
}
async function kcPrepare() {
  if(KC.busy||!KC.input.size||!KC.output.size)return;
  const version=KC.version;kcBusy(true);$('kcHandoff').hidden=true;
  try {
    const response=await api(kcBase()+'/prepare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({net:KC.net,input_ids:[...KC.input],output_ids:[...KC.output]})});
    await kcWait(response.job_id,version);if(version!==KC.version)return;
    state.workspaceModelIds.add(response.model_id);
    const prefix=kcBase()+'/exports/'+response.export_id;
    const result=await api(prefix+'/handoff.json');
    $('kcHandoff').innerHTML=`<h3>✓ Named copper prepared</h3><p><strong>${esc(result.net)}</strong><br>${result.volumes} solid volumes · ${result.named_surface_groups} named electrode groups</p><ul>${result.terminals.map(t=>`<li>${esc(t.role.toUpperCase())}: ${esc(t.label)}</li>`).join('')}</ul><a href="${prefix}/copper.xao" download>Download selected-net XAO ↗</a><a href="${prefix}/handoff.json" target="_blank" rel="noopener">Inspect terminal manifest ↗</a><p>Geometry handoff verified. Continue in the existing Geometry workbench with your simulation settings.</p>`;
    const openWorkbench=async()=>{
      await selectModel(response.model_id);
      if(state.model?.id!==response.model_id)throw Error('Could not open the prepared geometry.');
      state.input=new Set(state.model.inventory.default_input_tags);
      state.output=new Set(state.model.inventory.default_output_tags);
      renderSolids();renderGroups();updateStatusBar();draw();
      location.hash='#setup';
    };
    $('kcHandoff').insertAdjacentHTML('afterbegin','<button type="button" id="kcReviewGeometry" class="button secondary">Open Geometry workbench ↗</button>');
    $('kcReviewGeometry').onclick=()=>openWorkbench().catch(e=>toast(e.message));
    $('kcHandoff').hidden=false;
    await openWorkbench();await loadModels();
    if(typeof workspaceMarkChanged==='function')workspaceMarkChanged();
    kcProgress('Copper opened in Geometry with your input/output pads. Simulation settings retained.');
  }catch(e){if(version===KC.version)kcProgress(e.message,true);}finally{if(version===KC.version)kcBusy(false);}
}
async function kcProject(file) {
  if(!KC.board||KC.busy) {kcProgress('Import a board first, then add its .kicad_pro file.',true);return;}
  kcBusy(true);
  try {
    if(file.size>1024*1024)throw Error('Choose a KiCad project file smaller than 1 MiB.');
    const project=JSON.parse(await file.text());
    const result=await api(kcBase()+'/colours',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(project)});
    KC.board=result.board;kcRenderNets();kcDraw();kcRenderDetails();
    if(typeof workspaceMarkChanged==='function')workspaceMarkChanged();
    kcProgress(result.imported?`${result.imported} nets use saved KiCad PCB colours. Other nets keep automatic colours.`:'No custom PCB colours saved in this project. Using automatic net colours.');
  }catch(e){kcProgress(e.message,true);}finally{kcBusy(false);}
}
async function kcFiles(files) {
  if(KC.busy)return;
  const list=[...files],board=list.find(f=>f.name.toLowerCase().endsWith('.kicad_pcb')),project=list.find(f=>f.name.toLowerCase().endsWith('.kicad_pro'));
  if(board) {await kcUpload(board);if(KC.filename!==board.name)return;}
  if(project)await kcProject(project);
  if(!board&&!project)kcProgress('Choose a .kicad_pcb board and optionally its .kicad_pro project.',true);
}
$('kcFile').onchange=e=>{kcFiles(e.target.files);e.target.value='';};
$('kcProjectFile').onchange=e=>{if(e.target.files[0])kcProject(e.target.files[0]);e.target.value='';};
$('kcDrop').ondragover=e=>{e.preventDefault();};$('kcDrop').ondrop=e=>{e.preventDefault();kcFiles(e.dataTransfer.files);};
$('kcDrop').onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();$('kcFile').click();}};
$('kcDemo').onclick=async()=>{if(KC.busy)return;try{const r=await fetch('/api/kicad/example');if(!r.ok)throw Error('The local USB-UART example is unavailable.');const file=new File([await r.blob()],r.headers.get('Content-Disposition')?.match(/filename="([^"]+)"/)?.[1]||'example.kicad_pcb');await kcUpload(file);const p=await fetch('/api/kicad/example-project');if(p.ok)await kcProject(new File([await p.blob()],'USB-UART.kicad_pro'));}catch(e){kcProgress(e.message,true);}};
$('kcNetSearch').oninput=kcRenderNets;$('kcPadSearch').oninput=kcRenderPads;
$('kcPickInput').onclick=()=>{KC.role='input';$('kcPickInput').setAttribute('aria-pressed','true');$('kcPickOutput').setAttribute('aria-pressed','false');};
$('kcPickOutput').onclick=()=>{KC.role='output';$('kcPickInput').setAttribute('aria-pressed','false');$('kcPickOutput').setAttribute('aria-pressed','true');};
$('kcClear').onclick=()=>{KC.input.clear();KC.output.clear();kcRenderPads();kcRenderSelections();kcDraw();kcBusy(KC.busy);$('kcHandoff').hidden=true;};
$('kcFit').onclick=()=>{KC.views={};kcDraw();};$('kcPrepare').onclick=kcPrepare;
$('kcAllNets').onclick=()=>{KC.allNets=!KC.allNets;kcDraw();};
$('kcFocus').onclick=()=>{const focused=$('kcSelectionPanel').classList.toggle('board-focus');$('kcFocus').setAttribute('aria-pressed',String(focused));$('kcFocus').textContent=focused?'Show panels':'Focus board';};
$('kcLayout').onclick=()=>{const grid=document.querySelector('.kc-layer-grid');const columns=grid.classList.toggle('side-by-side');$('kcLayout').textContent=columns?'Stack views':'Side by side';};
api('/api/kicad/status').then(s=>{$('kcDownloadExample').hidden=!s.example_archive_available;$('kcRuntime').textContent=s.available?'● KiCad '+s.version+' · Mac':'KiCad setup needed';$('kcRuntime').title=s.available?s.bundled?'Using bundled KiCad':'Using installed KiCad':s.error;}).catch(()=>{$('kcRuntime').textContent='KiCad unavailable';});
kcDraw();
