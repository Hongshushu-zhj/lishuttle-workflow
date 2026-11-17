import {onUnmounted,watch} from 'vue';
import type {Common} from './useWorkbench';
import {exportSessionLog} from '../shared/desktop.ts';
import {readLogStream} from '../shared/logStream.ts';
export function createSession(h:Common){
 const {s,api,run,guard,flow,log}=h;let runtimeTimer:ReturnType<typeof setTimeout>|undefined,logTimer:ReturnType<typeof setTimeout>|undefined;let alive=true;let reading=false;let streamAbort:AbortController|undefined;
 const request=()=>({schema:s.job.schema,func:s.job.func,task_id:s.job.taskId});
 async function preflight(){if(!guard()||!s.job)return;h.sync();if(!flow.assemblyCurrent){s.error='任务输入已变化，请重新加载或装配运行 XML。';return;}const job=s.job,key=flow.key;await run('运行前检查',async()=>{const r=await api.post('preflight',request());if(job!==s.job||key!==flow.key)return;s.preflight=r;flow.checked(r);s.stage=4;s.notice=r.ok?'运行前检查已通过。':'检查发现需处理的问题，请核对报告。';});}
 async function startRun(){if(!guard()||!s.job)return;h.sync();if(!flow.canRun){s.error='请先完成当前版本的运行前检查。';return;}const job=s.job,key=flow.key;await run('启动计算',async()=>{const check=await api.post('preflight',request());if(job!==s.job||key!==flow.key)return;s.preflight=check;flow.checked(check);if(!check.ok)throw Error('运行前检查未通过');api.scope.invalidate('results');s.result=null;const r=await api.post('run',request());s.resultSid=r.sid;s.runContext=r.context;s.runtime=r.runtime||{busy:true,sid:r.sid};attachLog(r.sid);s.stage=5;s.notice='计算已启动，运行上下文和会话已固定。';});}
 async function cancel(){if(!s.runtime.busy||s.runtime.external||!s.runtime.sid)return;await run('请求取消当前任务',async()=>{await api.post('stop',{sid:s.runtime.sid});s.notice='取消请求已发出；进程收尾与归档完成前仍保持资源锁。';});}
 async function refreshRuntime(){try{const r=await api.get('runtime_state');if(!alive)return;const previous=s.runtime;s.runtime=r;if(r.busy&&!r.external&&r.sid&&(!log.sid||String(previous.sid)!==String(r.sid)))attachLog(r.sid);}catch(error){s.runtimeReadError=error instanceof Error?error.message:String(error);}}
 function startRuntimePoll(){const poll=async()=>{await refreshRuntime();if(alive)runtimeTimer=setTimeout(poll,1400);};void poll();}
 function attachLog(sid:number|string,historical=false){streamAbort?.abort();clearTimeout(logTimer);log.attach(sid);s.logOpen=true;s.logHistorical=historical;s.logStatus=historical?'正在读取固定历史会话':'正在连接运行日志';s.logPage=null;}
 function showRuntimeLog(){if(s.runtime.busy&&!s.runtime.external&&s.runtime.sid&&(String(log.sid)!==String(s.runtime.sid)||s.logHistorical))attachLog(s.runtime.sid);s.logOpen=true;}
 async function pollLog(generation:number){if(!alive||generation!==log.generation||!log.sid)return;if(reading){logTimer=setTimeout(()=>void pollLog(generation),250);return;}reading=true;let more=false;let terminal=false;try{const sid=log.sid,cursor=log.cursor;const r=await api.get('output',{sid,since:cursor,limit:500});if(!log.accept(generation,r))return;s.logPage=r;s.logStatus=r.has_more?'正在补读日志':r.cleanup_error?'正在等待进程收尾：'+r.cleanup_error:'日志已连接';more=!!r.has_more;terminal=['done','interrupted'].includes(r.status)&&!r.has_more;if(terminal){s.logStatus='完整日志已读取';if(!s.logHistorical&&!s.runtime.external&&s.runtime.sid===sid)s.runtime={busy:false,phase:'idle'};if(!s.logHistorical&&r.context?.func){s.resultSid=sid;s.runContext=r.context;s.result=r.result?{...r.result,historical:r.historical,context:r.context,current_files:r.current_files,archive:r.archive}:null;}if(!s.logHistorical)await h.onDone?.();}}catch(error){if(generation===log.generation)s.logStatus='日志连接中断，可继续补读：'+(error instanceof Error?error.message:String(error));}finally{reading=false;if(alive&&generation===log.generation&&!terminal)logTimer=setTimeout(()=>void pollLog(generation),more?50:800);}}
 async function streamLog(generation:number){
  const sid=log.sid;if(!alive||generation!==log.generation||!sid)return;
  streamAbort?.abort();const controller=new AbortController();streamAbort=controller;
  try{
   const outcome=await readLogStream(sid,log.sequence,controller.signal,events=>{
    if(!alive||generation!==log.generation||controller.signal.aborted)return;
    for(const event of events)log.acceptEvent(generation,event);
    s.logStatus='日志已实时连接';
   });
   if(!alive||generation!==log.generation||controller.signal.aborted)return;
   if(outcome==='legacy'){await pollLog(generation);return;}
   if(outcome==='stopping'){s.logStatus='本地服务正在关闭';return;}
   const r=await api.get('output',{sid,since:0,limit:1});
   if(!alive||generation!==log.generation||controller.signal.aborted)return;
   s.logPage=r;s.logStatus=outcome==='failed'?'日志归档不完整，请查看结果诊断':'完整日志已读取';
   if(!s.logHistorical&&!s.runtime.external&&s.runtime.sid===sid)s.runtime={busy:false,phase:'idle'};
   if(!s.logHistorical&&r.context?.func){s.resultSid=sid;s.runContext=r.context;s.result=r.result?{...r.result,historical:r.historical,context:r.context,current_files:r.current_files,archive:r.archive}:null;}
   if(!s.logHistorical)await h.onDone?.();
  }catch(error){
   if(!alive||generation!==log.generation||controller.signal.aborted)return;
   s.logStatus='日志连接中断，正在补读：'+(error instanceof Error?error.message:String(error));
   logTimer=setTimeout(()=>void streamLog(generation),800);
  }
 }
 watch(()=>log.generation,()=>{streamAbort?.abort();if(log.sid){clearTimeout(logTimer);void streamLog(log.generation);}},{flush:'post'});
 async function exportLog(){const sid=log.sid;if(!sid)return;await run('完整导出固定会话日志',async()=>{const result=await exportSessionLog(sid);if(result.saved)s.notice='日志已完整导出。';});}
 async function loadHistory(offset=0){const token=api.scope.read('history');const r=await api.get('history',{offset,limit:20});if(!api.scope.current(token))return;s.history={...r,offset,limit:20};}
 async function showHistory(){s.view='history';await run('读取运行记录',()=>loadHistory());}
 async function selectHistory(sid:number|string){s.result=null;s.resultSid=sid;await run('查看固定历史会话',async()=>{const token=api.scope.read('results');const r=await api.get('results',{sid});if(!api.scope.current(token))return;s.result=r;attachLog(sid,true);});}
 async function loadResults(){const sid=!s.directoryOnly?s.resultSid:0;const query=sid?{sid}:s.job?.mode==='existing'&&!s.resultJob?{schema:s.job.schema}:{job:s.resultJob||s.job?.name||''};if(!sid&&!query.job&&!query.schema){s.error='请先选择会话，或填写需要浏览的任务目录名。';return;}await run('读取结果与文件验证',async()=>{const token=api.scope.read('results');const r=await api.get('results',query);if(api.scope.current(token)){s.result=r;if(!sid&&r.associated===false)s.resultSid=0;}});}
 async function resumeLog(){if(log.sid){clearTimeout(logTimer);await streamLog(log.generation);}}
 onUnmounted(()=>{alive=false;streamAbort?.abort();clearTimeout(runtimeTimer);clearTimeout(logTimer);});
 return {preflight,startRun,cancel,refreshRuntime,startRuntimePoll,attachLog,showRuntimeLog,exportLog,loadHistory,showHistory,selectHistory,loadResults,resumeLog};
}
