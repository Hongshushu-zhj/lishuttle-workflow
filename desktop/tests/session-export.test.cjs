'use strict';
const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const os=require('node:os');const path=require('node:path');const http=require('node:http');
const {streamSessionExport}=require('../session-export.cjs');
test('trusted export streams more than 16 MiB and authenticates without URL secrets',async t=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'log-export-'));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const chunk=Buffer.alloc(1024*1024,'x');let received;
 const server=http.createServer((request,response)=>{received=request;response.writeHead(200,{'Content-Type':'text/plain; charset=utf-8'});let n=0;function write(){while(n<18){n++;if(!response.write(chunk)){response.once('drain',write);return;}}response.end('EOF');}write();});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));t.after(()=>server.close());
 const origin='http://127.0.0.1:'+server.address().port,target=path.join(root,'large.log');
 await streamSessionExport({origin,cookieName:'fixture',secret:'private',sid:123,target});
 assert.equal(fs.statSync(target).size,18*1024*1024+3);assert.equal(received.url,'/api/export_log?sid=123');assert.equal(received.headers.cookie,'fixture=private');assert.equal(received.headers.origin,origin);
});
test('failed export preserves an existing chosen file and removes temporary output',async t=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'log-export-fail-'));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const target=path.join(root,'prior.log');fs.writeFileSync(target,'keep');
 const server=http.createServer((_q,r)=>{r.writeHead(401);r.end('no');});await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));t.after(()=>server.close());
 await assert.rejects(streamSessionExport({origin:'http://127.0.0.1:'+server.address().port,cookieName:'fixture',secret:'x',sid:1,target}));assert.equal(fs.readFileSync(target,'utf8'),'keep');assert.deepEqual(fs.readdirSync(root),['prior.log']);
});

test('interrupted length-delimited export preserves previous file',async t=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'log-export-cut-'));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));const target=path.join(root,'prior.log');fs.writeFileSync(target,'keep');
 const server=http.createServer((_q,r)=>{r.writeHead(200,{'Content-Type':'text/plain','Content-Length':'1000000'});r.write('partial');setImmediate(()=>r.destroy());});await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));t.after(()=>server.close());
 await assert.rejects(streamSessionExport({origin:'http://127.0.0.1:'+server.address().port,cookieName:'fixture',secret:'x',sid:1,target}));assert.equal(fs.readFileSync(target,'utf8'),'keep');assert.deepEqual(fs.readdirSync(root),['prior.log']);
});
