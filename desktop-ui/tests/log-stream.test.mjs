import test from 'node:test';
import assert from 'node:assert/strict';
import {LogSession} from '../src/domain/controllers.ts';

test('events show partial lines, preserve split ANSI and CRLF, and deduplicate replay',()=>{
 const log=new LogSession(),g=log.attach(42);
 log.acceptEvent(g,{sid:42,seq:1,kind:'text',text:'半行\u001b['});
 assert.deepEqual(log.lines,['半行']);
 log.acceptEvent(g,{sid:42,seq:2,kind:'text',text:'31m红\u001b[0m\r'});
 assert.deepEqual(log.lines,['半行红']);
 log.acceptEvent(g,{sid:42,seq:3,kind:'text',text:'完成\r'});
 log.acceptEvent(g,{sid:42,seq:4,kind:'text',text:'\nEOF'});
 assert.deepEqual(log.lines,['完成','EOF']);
 assert.equal(log.acceptEvent(g,{sid:42,seq:4,kind:'text',text:'duplicate'}),false);
 assert.throws(()=>log.acceptEvent(g,{sid:42,seq:6,kind:'text',text:'gap'}),/序列/);
 assert.equal(log.sequence,4);
});
test('events from previous sid or generation never change current log',()=>{
 const log=new LogSession(),old=log.attach(7),now=log.attach(9);
 assert.equal(log.acceptEvent(old,{sid:7,seq:1,kind:'text',text:'old'}),false);
 assert.equal(log.acceptEvent(now,{sid:7,seq:1,kind:'text',text:'wrong sid'}),false);
 assert.equal(log.sequence,0);assert.deepEqual(log.lines,[]);
});
test('display is bounded even for a single huge line; full archive lives on server',()=>{
 const log=new LogSession(),g=log.attach(1);log.acceptEvent(g,{sid:1,seq:1,kind:'text',text:'x'.repeat(100000)});
 assert.ok(log.lines.join('').length<=32768);
 for(let seq=2;seq<4000;seq++)log.acceptEvent(g,{sid:1,seq,kind:'text',text:'\na'});
 assert.ok(log.lines.length<=3000);assert.ok(log.dropped>0);
});

test('SSE reader preserves fragmented Unicode, batches events and sends exact reconnect cursor',async()=>{
 const {readLogStream}=await import('../src/shared/logStream.ts');const original=globalThis.fetch;let request;
 const packets=': connected\n\nid: 3\nevent: output\ndata: '+JSON.stringify({sid:2,seq:3,kind:'text',text:'中文'})+'\n\nevent: complete\ndata: {"seq":3}\n\n';
 const raw=new TextEncoder().encode(packets);globalThis.fetch=async(url,options)=>{request={url,options};return new Response(new ReadableStream({start(controller){for(let i=0;i<raw.length;i+=3)controller.enqueue(raw.slice(i,i+3));controller.close();}}),{headers:{'content-type':'text/event-stream'}});};
 try{const batches=[];const signal=new AbortController().signal;assert.equal(await readLogStream(2,2,signal,events=>batches.push(events)),'complete');assert.deepEqual(batches.flat(),[{sid:2,seq:3,kind:'text',text:'中文'}]);assert.match(request.url,/sid=2&after=2$/);assert.equal(request.options.credentials,'same-origin');assert.equal(request.options.signal,signal);}finally{globalThis.fetch=original;}
});
test('SSE reader surfaces a gap from a batched callback without advancing sequence',async()=>{
 const {readLogStream}=await import('../src/shared/logStream.ts');const original=globalThis.fetch;
 globalThis.fetch=async()=>new Response(new ReadableStream({start(controller){controller.enqueue(new TextEncoder().encode('event: output\ndata: {"sid":2,"seq":2,"kind":"text","text":"gap"}\n\n'));}}),{headers:{'content-type':'text/event-stream'}});
 const log=new LogSession(),g=log.attach(2);
 try{await assert.rejects(readLogStream(2,0,new AbortController().signal,events=>events.forEach(event=>log.acceptEvent(g,event))),/序列/);assert.equal(log.sequence,0);}finally{globalThis.fetch=original;}
});

test('display also caps total text across many long lines',()=>{const log=new LogSession(),g=log.attach(1);for(let seq=1;seq<=80;seq++)log.acceptEvent(g,{sid:1,seq,kind:'text',text:'x'.repeat(20000)+'\n'});assert.ok(log.lines.join('').length<=1048576);assert.ok(log.dropped>0);});
