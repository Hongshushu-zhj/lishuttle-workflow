import test from 'node:test';
import assert from 'node:assert/strict';
import {Scope,Workflow,LogSession,PreviewGate} from '../src/domain/controllers.ts';
import {createProject} from '../src/app/useProject.ts';

function fixture(){
 const config={PRESET:'release',BUILD_SUBDIR:'out/release',DLL_ROOT:'ThirdPart/Dll',DLL_SRC:'ThirdPart/Dll/Release'};
 const s={state:{project:'C:/engine',profile_revision:'1',machine_revision:'1',project_config:{...config},machine_config:{},build_workflow:{presets:{debug:{build_type:'Debug',values:{PRESET:'debug',BUILD_SUBDIR:'out/debug',DLL_ROOT:'ThirdPart/Dll',DLL_SRC:'ThirdPart/Dll/Debug'}}}}},draft:{...config},runtime:{busy:false},pending:0,func:'pred',detection:null};
 const scope=new Scope();scope.update('C:/engine','1','1');
 const calls=[];
 const h={s,api:{scope,post:async(name,body)=>{calls.push({name,body});if(name==='preview_build_target')return {build_values:{DLL_SRC:body.values.DLL_ROOT+'/Debug'},dll:{root:body.values.DLL_ROOT,source:body.values.DLL_ROOT+'/Debug',mode:'Debug'}};if(name==='apply_build_target')return {...s.state,project_config:{...s.state.project_config,PRESET:body.preset,DLL_ROOT:body.values.DLL_ROOT,DLL_SRC:body.values.DLL_ROOT+'/Debug'}};if(name==='dll_status')return {revision:'diff-1',pending:2};if(name==='dll_sync')return {revision:'diff-2',updated:2,pending:0};return {sid:3,build_values:{PRESET:body.preset,DLL_ROOT:body.values?.DLL_ROOT,DLL_SRC:body.values?.DLL_ROOT+'/Debug'}};}},guard:()=>true,run:async(_,fn)=>fn(),flow:new Workflow(),log:new LogSession(),preview:new PreviewGate(),importPreview:new PreviewGate(),resetEditors(){},sync(){}};
 return {h,s,calls,p:createProject(h)};
}

test('preset changes preserve edited DLL root and preview through backend resolver',async()=>{
 const {p,s,calls}=fixture();s.draft.DLL_ROOT='D:/custom Dll';
 await p.selectPreset('debug');
 assert.equal(s.draft.DLL_ROOT,'D:/custom Dll');
 assert.equal(s.draft.DLL_SRC,'D:/custom Dll/Debug');
 assert.equal(calls[0].name,'preview_build_target');
 assert.equal(s.dllPreview.mode,'Debug');
});
test('build sends root draft and existing target uses the same backend preparation API',async()=>{
 const {p,s,calls}=fixture();s.draft.DLL_ROOT='../custom';s.draft.PRESET='debug';
 await p.toolkit('build');
 assert.equal(calls[0].body.values.DLL_ROOT,'../custom');
 s.draft.DLL_ROOT='../another';
 await p.useExecutable();
 assert.equal(calls[1].name,'apply_build_target');
 assert.equal(calls[1].body.values.DLL_ROOT,'../another');
 assert.equal(s.state.project_config.DLL_ROOT,'../another');
});
test('late DLL preview cannot overwrite a newer project or root draft',async()=>{
 const {p,s,h}=fixture();let resolve;
 h.api.post=async()=>new Promise(r=>{resolve=r;});
 const pending=p.previewDll();
 s.draft.DLL_ROOT='../new draft';
 resolve({build_values:{DLL_SRC:'stale/Debug'},dll:{source:'stale/Debug'}});
 await pending;
 assert.notEqual(s.draft.DLL_SRC,'stale/Debug');
});
test('DLL compare is explicit and sync submits the compared content revision',async()=>{
 const {p,s,calls}=fixture();
 await p.compareDlls();assert.equal(s.dllStatus.pending,2);
 await p.syncDlls();
 assert.deepEqual(calls.map(c=>c.name),['dll_status','dll_sync']);
 assert.equal(calls[1].body.revision,'diff-1');
 assert.equal(s.dllStatus.pending,0);
 assert.match(s.notice,/2/);
});
test('unsaved root requires apply before comparing or replacing current Bin DLLs',async()=>{
 const {p,s,calls}=fixture();s.draft.DLL_ROOT='../edited';
 await p.compareDlls();await p.syncDlls();
 assert.equal(calls.length,0);
 assert.match(s.error,/应用/);
});
test('build refresh preserves an intentionally cleared root draft',async()=>{
 const {p,s,h}=fixture();s.draft.DLL_ROOT='';
 h.api.post=async name=>name==='build_status'?{build_values:{DLL_ROOT:'ThirdPart/Dll',DLL_SRC:'ThirdPart/Dll/Release'}}:{};
 await p.refreshBuild();
 assert.equal(s.draft.DLL_ROOT,'');
});
