'use strict';
// Portable workspace files are explicit: nothing reopens from a previous session.
const workspaceUI = { busy:false, dirty:false, hasFile:false, nativeSave:null, nativeFileToken:null };

function workspaceKiCad() {
  try { return typeof KC==='undefined' ? null : KC; } catch { return null; }
}
function workspaceCloseMenu() { if($('workspaceMenu'))$('workspaceMenu').open=false; }
function workspaceRefreshUI() {
  const started=!!state.workspaceStarted;
  const active=!!state.workspaceBoardId||!!state.model?.id;
  for(const id of ['workspaceSave','workspaceSaveAs'])if($(id))$(id).disabled=workspaceUI.busy||!active;
  for(const id of ['workspaceNew','workspaceOpen','workspaceAdd','clearWorkspace','example'])if($(id))$(id).disabled=workspaceUI.busy;
  if($('workspaceMenuName'))$('workspaceMenuName').textContent=started?(state.workspaceName||'Untitled')+(workspaceUI.dirty?' · unsaved changes':''):'No workspace open';
  if($('confirmSaveWorkspace'))$('confirmSaveWorkspace').disabled=workspaceUI.busy;
  if($('cancelSaveWorkspace'))$('cancelSaveWorkspace').disabled=workspaceUI.busy;
}
function workspaceMarkChanged() {
  workspaceUI.dirty=true;
  if(state.model?.id||state.workspaceBoardId)state.workspaceStarted=true;
  workspaceRefreshUI();
}
function workspaceReset() {
  state.workspaceBoardId=null;
  state.workspaceModelIds=new Set();state.workspaceRunIds=new Set();
  state.workspaceName='Untitled';state.workspaceStarted=false;state.autoSelect=false;
  workspaceUI.dirty=false;workspaceUI.hasFile=false;workspaceUI.nativeFileToken=null;
  const kc=workspaceKiCad();
  if(kc){
    kc.version++;kc.boardId=null;kc.board=null;kc.filename='';kc.net=null;kc.pads=[];
    kc.input.clear();kc.output.clear();kc.views={};kc.layers={};kc.exportId=null;
    kc.allNets=true;kc.previewReady=false;kc.busy=false;kc.role='input';
    $('kcPickInput').setAttribute('aria-pressed','true');$('kcPickOutput').setAttribute('aria-pressed','false');
    $('kcSelectionPanel').classList.remove('board-focus');document.querySelector('.kc-layer-grid').classList.remove('side-by-side');
    $('kcFocus').setAttribute('aria-pressed','false');$('kcFocus').textContent='Focus board';$('kcLayout').textContent='Side by side';
    $('kcDetails').innerHTML='<p class="muted">Import a board to inspect its pads, nets and stackup.</p>';
    if(typeof kcDetailsTab==='function')kcDetailsTab(false);
    $('kcBoardName').textContent='No board selected';$('kcNetName').textContent='Select a net';
    $('kcNetInfo').textContent='Copper on all required layers is retained for export.';
    $('kcNetSearch').value='';$('kcPadSearch').value='';$('kcHandoff').hidden=true;
    $('kcNets').innerHTML='<p class="muted">Import a board to list its nets.</p>';
    if($('kcImportTiming'))$('kcImportTiming').hidden=true;
    if(typeof kcRenderPads==='function')kcRenderPads();
    if(typeof kcRenderSelections==='function')kcRenderSelections();
    if(typeof kcRenderDetails==='function')kcRenderDetails();
    if(typeof kcDraw==='function')kcDraw();
    if(typeof kcBusy==='function')kcBusy(false);
    if(typeof kcProgress==='function')kcProgress('Import a KiCad board or try the example to begin.');
  }
  workspaceRefreshUI();
}
function workspaceNew() {
  if(workspaceUI.busy)return;
  workspaceCloseMenu();clearWorkspace();
  state.workspaceStarted=true;state.workspaceName='Untitled';
  location.hash='#setup';workspaceRefreshUI();toast('New workspace. Add a board to begin.');
}
function workspaceCapture() {
  const runForm={};
  for(const control of $('runForm').elements){
    if(!control.name)continue;
    runForm[control.name]=control.type==='checkbox'?control.checked:control.value;
  }
  const kc=workspaceKiCad(),v=state.viewer;
  const parts=location.hash.slice(1).split('/');
  return {
    run_form:runForm,
    model_input_tags:[...state.input],model_output_tags:[...state.output],
    active_model_id:state.model?.id||null,
    kicad:kc?.boardId?{net:kc.net,input_ids:[...kc.input],output_ids:[...kc.output],role:kc.role,all_nets:kc.allNets,views:JSON.parse(JSON.stringify(kc.views||{}))}:null,
    theme:document.documentElement.dataset.theme||'salt',accent:$('accentColour').value,
    view:parts[0]||'home',current_run_id:parts[0]==='results'?decodeURIComponent(parts[1]||''):null,
    camera:v?{yaw:v.yaw,pitch:v.pitch,zoom:v.zoom,pan:[...v.pan]}:null
  };
}
function workspaceName(value) { return String(value||'').trim().replace(/\.pepper$/i,'').trim(); }
async function workspaceNativeAvailable() {
  if(workspaceUI.nativeSave===null){
    const response=await fetch('/api/workspace/capabilities');
    if(!response.ok)throw Error('Could not check workspace saving support.');
    workspaceUI.nativeSave=!!(await response.json()).native_save;
  }
  return workspaceUI.nativeSave;
}
async function workspaceSaveNative(saveAs=false) {
  if(workspaceUI.busy)return;
  workspaceCloseMenu();workspaceUI.busy=true;workspaceRefreshUI();
  try {
    const response=await fetch('/api/workspace/save-native',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({board_id:state.workspaceBoardId||null,model_id:state.model?.id||null,name:state.workspaceName==='Untitled'?'Workspace':state.workspaceName,ui_state:workspaceCapture(),file_token:workspaceUI.nativeFileToken,save_as:saveAs})});
    const result=await response.json();
    if(!response.ok)throw Error(result.error||'Could not save the workspace.');
    if(result.status==='cancelled'){toast('Save cancelled.');return;}
    if(result.status!=='saved')throw Error('The desktop app did not confirm that the workspace was saved.');
    state.workspaceName=result.name;workspaceUI.dirty=false;workspaceUI.hasFile=true;workspaceUI.nativeFileToken=result.native_file_token||null;
    toast('Saved '+result.filename);
  } finally {workspaceUI.busy=false;workspaceRefreshUI();}
}
async function workspaceDialog() {
  if(workspaceUI.busy||(!state.model?.id&&!state.workspaceBoardId))return;
  try {if(await workspaceNativeAvailable()){await workspaceSaveNative(true);return;}}
  catch(error){toast(error.message);return;}
  workspaceCloseMenu();$('workspaceFileName').value=state.workspaceName==='Untitled'?'':workspaceName(state.workspaceName);
  $('workspaceSaveError').hidden=true;
  const dialog=$('saveWorkspaceDialog');if(!dialog.open)dialog.showModal();
  $('workspaceFileName').focus();$('workspaceFileName').select();
}
async function workspaceSaveNamed(name) {
  name=workspaceName(name);
  if(!name)throw Error('Enter a workspace name.');
  if(!state.workspaceBoardId&&!state.model?.id)throw Error('Add a board before saving a workspace.');
  workspaceUI.busy=true;workspaceRefreshUI();
  try {
    const response=await fetch('/api/workspace/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({board_id:state.workspaceBoardId||null,model_id:state.model?.id||null,name,ui_state:workspaceCapture()})});
    if(!response.ok){const error=await response.json().catch(()=>({}));throw Error(error.error||'Could not save the workspace.');}
    const blob=await response.blob();if(!blob.size)throw Error('The workspace file is empty.');
    const url=URL.createObjectURL(blob),link=document.createElement('a');
    link.href=url;link.download=name.replace(/[\\/:*?"<>|\x00-\x1f]/g,'_')+'.pepper';
    document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
    state.workspaceName=name;workspaceUI.dirty=false;workspaceUI.hasFile=true;
    if($('saveWorkspaceDialog').open)$('saveWorkspaceDialog').close();
    toast('Saved '+link.download);
  } finally {workspaceUI.busy=false;workspaceRefreshUI();}
}
async function workspaceSave() {
  if(workspaceUI.busy||(!state.model?.id&&!state.workspaceBoardId))return;
  workspaceCloseMenu();
  try {if(await workspaceNativeAvailable()){await workspaceSaveNative();return;}}
  catch(error){toast(error.message);return;}
  if(!workspaceUI.hasFile||!state.workspaceName||state.workspaceName==='Untitled'){workspaceDialog();return;}
  try {await workspaceSaveNamed(state.workspaceName);} catch(error){toast(error.message);}
}
function workspaceChooseBoard() {
  if(workspaceUI.busy)return;workspaceCloseMenu();$('addWorkspaceBoardFile').value='';$('addWorkspaceBoardFile').click();
}
function workspaceShowKiCad(event) {
  if(event)event.preventDefault();
  if(workspaceUI.busy)return;
  if(!state.workspaceStarted)workspaceNew();
  workspaceCloseMenu();location.hash='#kicad';
}
async function workspaceChooseOpen() {
  if(workspaceUI.busy)return;
  try {
    if(await workspaceNativeAvailable()){
      if(workspaceUI.busy)return;
      workspaceCloseMenu();workspaceUI.busy=true;workspaceRefreshUI();
      try {
        const response=await fetch('/api/workspace/open-native',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
        const restored=await response.json();if(!response.ok)throw Error(restored.error||'Could not open the workspace.');
        if(restored.status==='cancelled')return;
        await workspaceApply(restored);toast('Opened '+restored.filename);return;
      } finally {workspaceUI.busy=false;workspaceRefreshUI();}
    }
  } catch(error){toast(error.message);return;}
  if(workspaceUI.busy)return;workspaceCloseMenu();$('openWorkspaceFile').value='';$('openWorkspaceFile').click();
}
async function workspaceAddBoard(file) {
  if(!file||workspaceUI.busy)return;
  if(!/\.(?:kicad_pcb|step|stp)$/i.test(file.name)){toast('Choose a KiCad PCB or STEP file.');return;}
  if(!state.workspaceStarted)workspaceNew();
  if(/\.kicad_pcb$/i.test(file.name)){location.hash='#kicad';await kcUpload(file);}
  else {location.hash='#setup';await upload(file);}
  workspaceMarkChanged();
}
async function workspaceApply(restored) {
  const ui=restored.ui_state||{};
  clearWorkspace();
  const ids=values=>(values||[]).map(value=>typeof value==='string'?value:value?.id).filter(Boolean);
  state.workspaceBoardId=restored.board_id||null;
  state.workspaceModelIds=new Set(ids(restored.models));state.workspaceRunIds=new Set(ids(restored.runs));
  if(restored.model_id)state.workspaceModelIds.add(restored.model_id);
  state.workspaceName=restored.name||'Untitled';state.workspaceStarted=true;state.autoSelect=false;
  await loadModels();await loadRuns();
  const modelId=state.workspaceModelIds.has(ui.active_model_id)?ui.active_model_id:restored.model_id||[...state.workspaceModelIds][0];
  if(modelId){
    await selectModel(modelId);
    const known=new Set(state.inventory.map(row=>row.tag));
    if(Array.isArray(ui.model_input_tags))state.input=new Set(ui.model_input_tags.filter(tag=>known.has(tag)));
    if(Array.isArray(ui.model_output_tags))state.output=new Set(ui.model_output_tags.filter(tag=>known.has(tag)&&!state.input.has(tag)));
    renderSolids();renderGroups();updateStatusBar();
  }
  const selection=ui.kicad||{};
  if(state.workspaceBoardId&&typeof kcRestoreBoard==='function'){
    await kcRestoreBoard(state.workspaceBoardId,selection.net||null,selection.input_ids||[],selection.output_ids||[]);
    const kc=workspaceKiCad();
    if(kc){
      kc.allNets=typeof selection.all_nets==='boolean'?selection.all_nets:!selection.net;
      if(['input','output'].includes(selection.role))$(selection.role==='input'?'kcPickInput':'kcPickOutput').click();
      const views={};for(const side of ['top','bottom']){const value=selection.views?.[side];if(Array.isArray(value)&&value.length===4&&value.every(Number.isFinite)&&value[2]>0&&value[3]>0)views[side]=[...value];}
      kc.views=views;kcDraw();
    }
  }
  for(const [name,value] of Object.entries(ui.run_form||{})){
    const control=$('runForm').elements.namedItem(name);if(!control)continue;
    if(control.type==='checkbox')control.checked=!!value;else control.value=String(value);
  }
  if(['salt','pepper'].includes(ui.theme))setTheme(ui.theme);
  if([...$('accentColour').options].some(option=>option.value===ui.accent)){$('accentColour').value=ui.accent;$('accentColour').dispatchEvent(new Event('change'));}
  if(modelId&&ui.camera){
    for(let attempt=0;attempt<100;attempt++){
      if(state.viewer?.bodies.length&&$('previewMessage').style.display==='none')break;
      await new Promise(resolve=>setTimeout(resolve,100));
    }
    const v=state.viewer,camera=ui.camera;
    if(v&&['yaw','pitch','zoom'].every(key=>Number.isFinite(camera[key]))&&Array.isArray(camera.pan)&&camera.pan.length===2&&camera.pan.every(Number.isFinite)){
      v.yaw=camera.yaw;v.pitch=camera.pitch;v.zoom=Math.max(.1,Math.min(25,camera.zoom));v.pan=[...camera.pan];draw();
    }
  }
  const view=['setup','kicad','runs','results'].includes(ui.view)?ui.view:state.workspaceBoardId?'kicad':'setup';
  if(view==='results'&&state.workspaceRunIds.has(ui.current_run_id))location.hash='#results/'+encodeURIComponent(ui.current_run_id);
  else location.hash='#'+(view==='results'?'runs':view);
  workspaceUI.dirty=false;workspaceUI.hasFile=true;workspaceUI.nativeFileToken=restored.native_file_token||null;workspaceRefreshUI();
}
async function workspaceOpenFile(file) {
  if(!file||workspaceUI.busy)return;
  if(!/\.pepper$/i.test(file.name)){toast('Choose a .pepper workspace file.');return;}
  workspaceUI.busy=true;workspaceCloseMenu();workspaceRefreshUI();
  try {
    const response=await fetch('/api/workspace/import?filename='+encodeURIComponent(file.name),{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:file});
    const restored=await response.json();if(!response.ok)throw Error(restored.error||'Could not open the workspace.');
    await workspaceApply(restored);toast('Opened '+state.workspaceName+'.pepper');
  } catch(error){toast(error.message);} finally {workspaceUI.busy=false;workspaceRefreshUI();}
}
$('workspaceNew').onclick=workspaceNew;
$('newWorkspaceCard').onclick=event=>{event.preventDefault();workspaceNew();};
$('workspaceOpen').onclick=workspaceChooseOpen;
$('openWorkspaceCard').onclick=event=>{event.preventDefault();workspaceChooseOpen();};
$('workspaceAdd').onclick=workspaceChooseBoard;
$('setupKiCadImport').onclick=workspaceShowKiCad;
document.querySelector('[data-nav="kicad"]').onclick=workspaceShowKiCad;
$('workspaceSave').onclick=workspaceSave;
$('workspaceSaveAs').onclick=workspaceDialog;
$('cancelSaveWorkspace').onclick=()=>$('saveWorkspaceDialog').close();
$('saveWorkspaceForm').onsubmit=async event=>{
  event.preventDefault();$('workspaceSaveError').hidden=true;
  try {await workspaceSaveNamed($('workspaceFileName').value);}catch(error){$('workspaceSaveError').textContent=error.message;$('workspaceSaveError').hidden=false;}
};
$('openWorkspaceFile').onchange=event=>{const file=event.target.files[0];event.target.value='';workspaceOpenFile(file);};
$('addWorkspaceBoardFile').onchange=event=>{const file=event.target.files[0];event.target.value='';workspaceAddBoard(file).catch(error=>toast(error.message));};
$('runForm').addEventListener('change',workspaceMarkChanged);
workspaceRefreshUI();
