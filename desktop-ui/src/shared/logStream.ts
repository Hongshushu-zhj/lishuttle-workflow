export type StreamEvent={sid:number|string;seq:number;kind:'text'|'end';text?:string};
/** Fetch keeps credentials in HttpOnly cookies and gives explicit abort ownership. */
export async function readLogStream(sid:number|string,after:number,signal:AbortSignal,onEvents:(events:StreamEvent[])=>void):Promise<'legacy'|'complete'|'stopping'|'failed'>{
 const response=await fetch('/api/output_stream?'+new URLSearchParams({sid:String(sid),after:String(after)}),{credentials:'same-origin',signal});
 if(!response.ok)throw Error('日志连接失败（'+response.status+'）');
 if(!response.headers.get('content-type')?.startsWith('text/event-stream')){const data=await response.json();if(data.legacy)return 'legacy';throw Error(data.error||'日志流不可用');}
 if(!response.body)throw Error('日志流不可读');
 const reader=response.body.getReader(),decoder=new TextDecoder();let callbackError:unknown;let buffer='',pending:StreamEvent[]=[],timer:ReturnType<typeof setTimeout>|undefined;
 const flush=()=>{clearTimeout(timer);timer=undefined;if(pending.length){const batch=pending;pending=[];onEvents(batch);}};
 try{
  while(true){
   const {done,value}=await reader.read();if(callbackError)throw callbackError;buffer+=decoder.decode(value,{stream:!done});
   let boundary:number;
   while((boundary=buffer.indexOf('\n\n'))>=0){
    const packet=buffer.slice(0,boundary);buffer=buffer.slice(boundary+2);const lines=packet.split('\n');
    const name=lines.find(line=>line.startsWith('event:'))?.slice(6).trim();
    const data=lines.filter(line=>line.startsWith('data:')).map(line=>line.slice(5).trimStart()).join('\n');
    if(name==='output'){pending.push(JSON.parse(data));if(pending.length>=128)flush();else if(!timer)timer=setTimeout(()=>{try{flush();}catch(error){callbackError=error;void reader.cancel();}},50);}
    else if(name==='complete'||name==='stopping'||name==='failed'){flush();return name;}
   }
   if(buffer.length>131072)throw Error('日志事件超过限制');
   if(done){flush();throw Error('日志连接中断，正在重新连接');}
  }
 }finally{clearTimeout(timer);await reader.cancel().catch(()=>{});}
}
