const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map();
function el(id){
  if(!nodes.has(id)){
    const classes=new Set(['hidden']);
    nodes.set(id,{value:'',innerHTML:'',textContent:'',style:{},dataset:{},checked:false,disabled:false,
      setAttribute(key,value){this[key]=value;},removeAttribute(key){delete this[key];},
      focus(){this.focused=true;},scrollIntoView(){this.scrolled=true;},addEventListener(){},
      classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),contains:x=>classes.has(x),toggle(){}},querySelectorAll:()=>[]});
  }return nodes.get(id);
}
const ctx=vm.createContext({document:{getElementById:el,querySelectorAll:()=>[],querySelector:()=>null},setTimeout(){}});
vm.runInContext(fs.readFileSync('platform/frontend/app.js','utf8').replace(/init\(\);\s*$/,''),ctx);
const run=code=>vm.runInContext(code,ctx);
run(`S.project='/project';S.profileId='project';S.profileRevision='1';S.projectEpoch=1;
  S.projectConfig={};S.projectDraft={};S.configTouched=new Set();S.projectManualFields=new Set();
  S.buildWorkflow={presets:{debug:{mode:'debug',build_type:'Debug',directory_exists:false,built:false,values:{PRESET:'debug',BUILD_SUBDIR:'out/debug',EXE_NAME:'auto.exe'}},
  release:{mode:'release',build_type:'RelWithDebInfo',directory_exists:false,built:false,values:{PRESET:'release',BUILD_SUBDIR:'out/release',EXE_NAME:'auto.exe'}}},modes:{debug:['debug'],release:['release']}};
  S.projectDetection={presets:S.buildWorkflow.presets,fields:{}};`);
(async()=>{
  run('renderProjectConfig()');
  const fields=el('project-config-fields').innerHTML;
  assert.ok(!fields.includes('CASE_ROOT'),'CLI case directory is removed');
  assert.ok(!fields.includes('data-config-key="EXE_NAME"'),'program filename is automatic');
  assert.ok(!fields.includes('data-config-key="BUILD_SUBDIR"'),'build directory comes from preset');
  assert.match(el('build-mode').innerHTML,/Debug/);
  assert.match(el('build-mode').innerHTML,/Release/);
  run("chooseBuildMode('debug')");
  assert.equal(run('S.projectDraft.PRESET'),'debug');
  assert.equal(run('S.projectDraft.BUILD_SUBDIR'),'out/debug');
  assert.match(el('build-summary').textContent,/尚未生成/);
  assert.match(el('workflow-steps').innerHTML,/编译/);
  ctx.reply={ok:false,issues:[{key:'OUT_ROOT',target:'config-OUT_ROOT',section:'project',message:'请填写结果根目录'}]};
  run('api=async()=>reply');
  await run('doRender()');
  assert.equal(el('project-config-form').classList.contains('hidden'),false);
  assert.equal(el('config-OUT_ROOT').focused,true);
  assert.equal(el('config-OUT_ROOT')['aria-invalid'],'true');
  assert.match(el('setup-validation').textContent,/结果根目录/);
  run(`focusSetupIssue({key:'CMAKE',target:'config-CMAKE',section:'machine',message:'缺少 CMake'})`);
  assert.equal(el('machine-config-form').classList.contains('hidden'),false);
  assert.equal(el('config-CMAKE').focused,true);
  run(`S.projectConfig={PRESET:'release',BUILD_SUBDIR:'out/release'};
    S.projectDraft={PRESET:'debug',BUILD_SUBDIR:'out/debug',DLL_SRC:'custom/dll'};
    S.configTouched.add('PRESET');
    applyBuildStatus({build_values:{PRESET:'release',BUILD_SUBDIR:'out/release',DLL_SRC:'dll/release'},build_workflow:{}},
      {PRESET:'release',BUILD_SUBDIR:'out/release',DLL_SRC:'dll/release'});`);
  assert.equal(run('S.projectDraft.PRESET'),'debug','late build status preserves a newer mode selection');
  assert.equal(run('S.projectDraft.BUILD_SUBDIR'),'out/debug');
  assert.equal(run('S.projectDraft.DLL_SRC'),'custom/dll');
  assert.equal(run('S.projectConfig.PRESET'),'release','saved baseline tracks actual build');
  let startReply;
  ctx.started = new Promise(resolve=>{startReply=resolve;});
  ctx.finished = {build_values:{PRESET:'release',BUILD_SUBDIR:'out/release',DLL_SRC:'dll/release'},build_workflow:{}};
  run(`S.projectDraft={PRESET:'release',BUILD_SUBDIR:'out/release',DLL_SRC:'dll/release'};
    S.projectConfig={...S.projectDraft};S.pollTimer=null;S.pendingRequests=0;
    api=async name=>name==='toolkit' ? started : finished;
    attachConsole=(sid,title,done)=>{S.buildDone=done};switchTab=()=>{};`);
  const pendingBuild=run("toolkit('build')");
  run("chooseBuildMode('debug');editProjectConfig('DLL_SRC','custom/new-dll')");
  startReply({sid:7,...ctx.finished});await pendingBuild;
  assert.equal(run('S.projectDraft.PRESET'),'debug');
  await run('S.buildDone()');
  assert.equal(run('S.projectDraft.PRESET'),'debug','completion preserves changes made before start reply');
  assert.equal(run('S.projectDraft.BUILD_SUBDIR'),'out/debug');
  assert.equal(run('S.projectDraft.DLL_SRC'),'custom/new-dll');
  run(`S.projectConfig={PRESET:'release',CONFIG_SRC:'',DLL_SRC:'dll/release'};
    S.projectDraft={PRESET:'release',CONFIG_SRC:'custom/config',DLL_SRC:'custom/dll'};
    S.configTouched.add('CONFIG_SRC');S.configTouched.add('DLL_SRC');
    applyBuildStatus({build_values:{PRESET:'release',CONFIG_SRC:'ThirdPart/Config',DLL_SRC:'dll/release'}},{...S.projectDraft});`);
  assert.equal(run('S.projectDraft.CONFIG_SRC'),'custom/config','pre-build resource drafts remain editable');
  assert.equal(run('S.projectDraft.DLL_SRC'),'custom/dll');
  assert.equal(run("S.configTouched.has('CONFIG_SRC')"),true);
  console.log('PASS: simplified settings, Debug/Release choices, build status, guide and required-field focus');
})().catch(e=>{console.error(e);process.exitCode=1;});
