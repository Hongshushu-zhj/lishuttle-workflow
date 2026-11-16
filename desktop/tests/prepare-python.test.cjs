'use strict';
const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const os=require('node:os');const path=require('node:path');
let prepare={};try{prepare=require('../../scripts/prepare-python.cjs');}catch(e){if(e.code!=='MODULE_NOT_FOUND')throw e;}
test('pinned Python archive rejects altered bytes',t=>{
 assert.equal(typeof prepare.verifyArchive,'function');const dir=fs.mkdtempSync(path.join(os.tmpdir(),'python-pin-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));const file=path.join(dir,'archive.zip');fs.writeFileSync(file,'altered');
 assert.throws(()=>prepare.verifyArchive(file),/SHA-256/);assert.match(prepare.PYTHON.sha256,/^[0-9a-f]{64}$/);assert.equal(prepare.PYTHON.version,'3.13.17');
});
test('embedded path files use portable correct backend and scripts paths without site',()=>{
 assert.equal(typeof prepare.pthContents,'function');
 const packaged=prepare.pthContents('packaged');assert.match(packaged,/\.\.\/workflow\/platform\/backend/);assert.match(packaged,/\.\.\/workflow\/scripts/);assert.equal(packaged.includes('import site'),false);
 const dev=prepare.pthContents('dev');assert.match(dev,/\.\.\/\.\.\/platform\/backend/);assert.match(dev,/\.\.\/\.\.\/scripts/);
 assert.equal(packaged.includes('D:'),false);
});
test('runtime extraction refuses locations outside its build scratch directory',()=>{
 assert.equal(typeof prepare.validateOutputDirectory,'function');
 assert.equal(prepare.validateOutputDirectory('C:\\source','C:\\source\\.desktop-build\\python'),path.resolve('C:\\source\\.desktop-build\\python'));
 for(const target of ['C:\\outside','C:\\source','C:\\source\\.desktop-build-other\\python'])assert.throws(()=>prepare.validateOutputDirectory('C:\\source',target),/build directory/);
});