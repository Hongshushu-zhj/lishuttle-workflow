'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
let security = {}; try { security = require('../security.cjs'); } catch (e) { if (e.code !== 'MODULE_NOT_FOUND') throw e; }
test('only a canonical loopback random service origin is accepted', () => {
  assert.equal(typeof security.validateServiceOrigin, 'function');
  assert.equal(security.validateServiceOrigin('http://127.0.0.1:49152'), 'http://127.0.0.1:49152');
  for (const value of ['https://127.0.0.1:1234','http://localhost:1234','http://127.0.0.1:22','http://127.0.0.1:1234/x','http://user@127.0.0.1:1234','http://2130706433:1234','http://127.0.0.1:1234/','http://127.0.0.1:1234?secret=x']) assert.throws(() => security.validateServiceOrigin(value), /origin/i);
});
test('IPC trusts only the bound window top frame at exact service origin', () => {
  assert.equal(typeof security.assertTrustedSender, 'function');
  const frame={url:'http://127.0.0.1:49152/index.html'};
  const contents={mainFrame:frame,id:7};
  const window={webContents:contents,isDestroyed:()=>false};
  security.assertTrustedSender({sender:contents,senderFrame:frame},window,'http://127.0.0.1:49152');
  assert.throws(()=>security.assertTrustedSender({sender:contents,senderFrame:{...frame}},window,'http://127.0.0.1:49152'),/trusted/i);
  frame.url='http://127.0.0.1:49153/'; assert.throws(()=>security.assertTrustedSender({sender:contents,senderFrame:frame},window,'http://127.0.0.1:49152'),/trusted/i);
});
test('native bridge argument validators reject injection and oversized writes',()=>{
  assert.equal(typeof security.validateDialogOptions,'function');
  assert.deepEqual(security.validateDialogOptions({title:'Choose XML',extensions:['xml']},true),{title:'Choose XML',extensions:['xml']});
  for(const options of [{extensions:['../exe']},{title:'a\nb'},{defaultPath:'https://host/x'},{extensions:['xml'],command:'powershell'}]) assert.throws(()=>security.validateDialogOptions(options,true));
  assert.throws(()=>security.validateSaveText({suggestedName:'../escape.txt',text:'a'}));
  assert.throws(()=>security.validateSaveText({suggestedName:'safe.txt',text:'a'.repeat(16*1024*1024+1)}));
  assert.deepEqual(security.validateSaveText({suggestedName:'日志.txt',text:'test'}),{suggestedName:'日志.txt',text:'test'});
});
test('navigation permits only current origin and no popup',()=>{
  assert.equal(typeof security.isAllowedNavigation,'function');
  assert.equal(security.isAllowedNavigation('http://127.0.0.1:49152/#settings','http://127.0.0.1:49152'),true);
  for(const url of ['file:///C:/secret','javascript:alert(1)','https://example.test','http://127.0.0.1:49152.evil/']) assert.equal(security.isAllowedNavigation(url,'http://127.0.0.1:49152'),false);
});
