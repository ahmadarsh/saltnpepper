// Test the actual workspace controller with simulated native endpoint responses.
// The real Windows picker is verified separately on a Windows desktop.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('pcb_simulator/static/workspace.js','utf8');
const definitions=source.slice(0,source.indexOf("$('workspaceNew').onclick"));
function setup(native=true,result={status:'saved',name:'Chosen board',filename:'Chosen board.pepper',native_file_token:'chosen-file-token'}){
  const nodes=new Map(),requests=[],messages=[];
  const state={workspaceStarted:true,workspaceName:'Untitled',workspaceBoardId:null,model:{id:'a'.repeat(32)},input:new Set([1]),output:new Set([2])};
  const $=id=>{if(!nodes.has(id))nodes.set(id,{value:'mint',elements:[],open:false,showModal(){this.open=true},focus(){},select(){}});return nodes.get(id)};
  const context=vm.createContext({state,$,location:{hash:'#setup'},document:{documentElement:{dataset:{theme:'salt'}},createElement(){throw Error('Native save must not trigger a browser download')}},toast:value=>messages.push(value),fetch:async(url,options)=>{requests.push({url,options});return {ok:result.status!=='error'||url.includes('capabilities'),json:async()=>url.includes('capabilities')?{native_save:native}:(result.status==='opened'&&url.endsWith('/save-native')?{...result,status:'saved'}:result)}},Set,JSON,Error,Promise,URL});
  vm.runInContext(definitions,context);vm.runInContext('workspaceUI.dirty=true',context);
  return {context,state,$,requests,messages,eval:code=>vm.runInContext(code,context)};
}
(async()=>{
  for(const action of ['workspaceSave()','workspaceDialog()']){
    const test=setup();await test.eval(action);
    assert.equal(test.requests.filter(r=>r.url.endsWith('/save-native')).length,1);
    assert.equal(test.$('saveWorkspaceDialog').open,false);
    assert.equal(test.state.workspaceName,'Chosen board');assert.equal(test.eval('workspaceUI.dirty'),false);
    const first=JSON.parse(test.requests.find(r=>r.url.endsWith('/save-native')).options.body);
    assert.equal(first.save_as,action==='workspaceDialog()');assert.equal(first.file_token,null);
    // Subsequent Save carries the existing file token, so the backend updates it.
    await test.eval('workspaceSave()');assert.equal(test.requests.filter(r=>r.url.endsWith('/save-native')).length,2);
    const second=JSON.parse(test.requests.filter(r=>r.url.endsWith('/save-native'))[1].options.body);
    assert.equal(second.file_token,'chosen-file-token');assert.equal(second.save_as,false);
    await test.eval('workspaceDialog()');const fork=JSON.parse(test.requests.filter(r=>r.url.endsWith('/save-native'))[2].options.body);
    assert.equal(fork.save_as,true);assert.equal(fork.file_token,'chosen-file-token');
  }
  const cancelled=setup(true,{status:'cancelled'});await cancelled.eval('workspaceSave()');
  assert.equal(cancelled.state.workspaceName,'Untitled');assert.equal(cancelled.eval('workspaceUI.dirty'),true);assert.equal(cancelled.eval('workspaceUI.hasFile'),false);assert.equal(cancelled.eval('workspaceUI.busy'),false);
  const failed=setup(true,{status:'error',error:'Write denied'});await failed.eval('workspaceDialog()');
  assert.equal(failed.eval('workspaceUI.dirty'),true);assert.equal(failed.eval('workspaceUI.hasFile'),false);assert.ok(failed.messages.includes('Write denied'));
  const browser=setup(false);await browser.eval('workspaceDialog()');assert.equal(browser.$('saveWorkspaceDialog').open,true);assert.equal(browser.requests.length,1);
  const opened=setup(true,{status:'opened',name:'Opened',filename:'Opened.pepper',native_file_token:'original-file-token'});
  opened.eval('workspaceApply=async restored=>{workspaceUI.nativeFileToken=restored.native_file_token;state.workspaceName=restored.name}');
  await opened.eval('workspaceChooseOpen()');assert.ok(opened.requests.some(r=>r.url.endsWith('/open-native')));
  assert.equal(opened.eval('workspaceUI.nativeFileToken'),'original-file-token');
  await opened.eval('workspaceSave()');assert.equal(JSON.parse(opened.requests.find(r=>r.url.endsWith('/save-native')).options.body).file_token,'original-file-token');
  opened.eval('workspaceReset()');assert.equal(opened.eval('workspaceUI.nativeFileToken'),null);
  console.log('PASS: native Open retains original file; Save reuses its token; Save As chooses a new path; cancel/error preserve state; New clears association; browser fallback retained.');
})().catch(error=>{console.error(error);process.exitCode=1});
