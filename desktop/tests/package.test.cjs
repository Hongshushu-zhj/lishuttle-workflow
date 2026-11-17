'use strict';
const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const os=require('node:os');const path=require('node:path');
let pkg={};try{pkg=require('../../scripts/package-verify.cjs');}catch(e){if(e.code!=='MODULE_NOT_FOUND')throw e;}
let build={};try{build=require('../../scripts/desktop-build.cjs');}catch(e){if(e.code!=='MODULE_NOT_FOUND')throw e;}
test('workflow whitelist excludes real state and build tools at any depth',()=>{
 assert.equal(typeof pkg.isAllowedWorkflowFile,'function');
 for(const file of ['platform/backend/core.py','platform/backend/params_spec.json','scripts/build_local.bat','scripts/render_schema.py','templates/runtimeschema.xml.tpl','desktop-ui/dist/index.html','desktop-ui/dist/assets/index-abc.js'])assert.equal(pkg.isAllowedWorkflowFile(file),true,file);
 for(const file of ['env/local-win.env','jobs/example.env','platform/backend/__pycache__/core.pyc','scripts/desktop-build.cjs','outputs/result.csv','desktop-ui/dist/assets/source.js.map','platform/backend/id_rsa','platform/backend/secrets.json','scripts/private.py','../core.py'])assert.equal(pkg.isAllowedWorkflowFile(file),false,file);
});
test('packaged application includes the native session log exporter',()=>{
 const configuration=fs.readFileSync(path.join(__dirname,'../../electron-builder.yml'),'utf8');
 assert.match(configuration,/^  - desktop\/session-export\.cjs\s*$/m);
});
test('resource verification catches personal files and changed immutable resources',t=>{
 assert.equal(typeof pkg.verifyManifestTree,'function');const directory=fs.mkdtempSync(path.join(os.tmpdir(),'lishuttle-package-'));t.after(()=>fs.rmSync(directory,{recursive:true,force:true}));
 fs.mkdirSync(path.join(directory,'scripts'));fs.writeFileSync(path.join(directory,'scripts','render_schema.py'),'safe');
 const manifest=pkg.hashTree(directory);assert.equal(pkg.verifyManifestTree(directory,manifest,pkg.isAllowedWorkflowFile),1);
 fs.writeFileSync(path.join(directory,'scripts','render_schema.py'),'changed');assert.throws(()=>pkg.verifyManifestTree(directory,manifest,pkg.isAllowedWorkflowFile),/hash|changed/i);
 fs.writeFileSync(path.join(directory,'scripts','render_schema.py'),'safe');fs.mkdirSync(path.join(directory,'env'));fs.writeFileSync(path.join(directory,'env','local-win.env'),'personal');assert.throws(()=>pkg.verifyManifestTree(directory,manifest,pkg.isAllowedWorkflowFile),/not allowed|unexpected/i);
});
test('release target identifiers and artifacts stay separated by channel',()=>{
 assert.equal(typeof build.resolveBuildTarget,'function');const stable=build.resolveBuildTarget({mode:'dist',channel:'stable',version:'0.1.0'}),dev=build.resolveBuildTarget({mode:'dist',channel:'dev',version:'0.1.0'});
 assert.notEqual(stable.appId,dev.appId);assert.notEqual(stable.output,dev.output);assert.equal(stable.productName,'LiShuttle Workflow');assert.equal(dev.productName,'LiShuttle Workflow (Dev)');assert.throws(()=>build.resolveBuildTarget({mode:'oops',channel:'stable',version:'0.1.0'}));assert.throws(()=>build.resolveBuildTarget({mode:'dist',channel:'canary',version:'0.1.0'}));
});
test('a patch release preserves the previous version output directory',()=>{
 const old=build.resolveBuildTarget({mode:'dist',channel:'stable',version:'0.1.0'});
 const next=build.resolveBuildTarget({mode:'dist',channel:'stable',version:'0.1.1'});
 assert.notEqual(next.output,old.output);
 assert.equal(next.output,'release/stable/0.1.1');
});
test('collects license notices for the exact locked UI dependencies including metadata-only MIT package',t=>{
 const directory=fs.mkdtempSync(path.join(os.tmpdir(),'lishuttle-notices-'));t.after(()=>fs.rmSync(directory,{recursive:true,force:true}));
 assert.equal(typeof build.createNotices,'function');const count=build.createNotices(directory);assert.equal(count>10,true);
 const notices=fs.readFileSync(path.join(directory,'licenses.txt'),'utf8');assert.match(notices,/lodash-unified 1\.0\.3/);assert.match(notices,/Jack Works/);assert.match(notices,/Permission is hereby granted/);
});
