import {TerminalText} from '../shared/terminalText.ts';
export type Json = Record<string, any>;
export type ReadToken = {epoch:number;key:string;sequence:number};
export class Scope {
  project=''; revision=''; machineRevision=''; epoch=0; sequences=new Map<string,number>();
  update(project:string,revision:string,machineRevision:string){if(project!==this.project||revision!==this.revision||machineRevision!==this.machineRevision){this.epoch++;this.sequences.clear();}this.project=project;this.revision=revision;this.machineRevision=machineRevision;}
  context(){return {_project:this.project,_revision:this.revision,_machine_revision:this.machineRevision};}
  read(key:string):ReadToken {const sequence=(this.sequences.get(key)||0)+1;this.sequences.set(key,sequence);return {epoch:this.epoch,key,sequence};}
  current(token:ReadToken){return token.epoch===this.epoch&&token.sequence===this.sequences.get(token.key);}
  invalidate(key:string){this.read(key);}
}
export class EditorLedger {
  drafts=new Map<string,{value:string;sequence:number}>(); sequence=0;
  edit(key:string,value:string){this.drafts.set(key,{value,sequence:++this.sequence});}
  capture(key:string){const value=this.drafts.get(key);return {key,value:value?.value||'',sequence:value?.sequence||0};}
  saved(token:{key:string;sequence:number}){if(this.drafts.get(token.key)?.sequence===token.sequence)this.drafts.delete(token.key);}
  value(key:string){return this.drafts.get(key)?.value;}
  get dirty(){return this.drafts.size>0;}
  discard(){this.drafts.clear();this.sequence++;}
}
export class LogSession {
  sequence=0; terminal=new TerminalText();
  sid:number|string=0; generation=0; cursor=0;lines:string[]=[]; maxLines=3000; dropped=0;
  attach(sid:number|string){this.sid=sid;this.generation++;this.cursor=0;this.sequence=0;this.terminal=new TerminalText();this.lines=[];this.dropped=0;return this.generation;}
  acceptEvent(generation:number,event:Json){
    if(generation!==this.generation||String(event.sid)!==String(this.sid))return false;
    if(!Number.isSafeInteger(event.seq)||event.seq<1)throw Error('日志事件序列无效');
    if(event.seq<=this.sequence)return false;
    if(event.seq!==this.sequence+1)throw Error('日志事件序列不连续');
    if(event.kind!=='text'&&event.kind!=='end')throw Error('日志事件类型无效');
    if(event.kind==='text'){
      if(typeof event.text!=='string')throw Error('日志事件文本无效');
      this.terminal.maxLines=this.maxLines;this.terminal.feed(event.text);
      this.lines=this.terminal.lines;this.dropped=this.terminal.dropped;
    }
    this.sequence=event.seq;return true;
  }

  accept(generation:number,page:Json){if(generation!==this.generation)return false;const lines=page.lines||[];const next=Number.isFinite(page.next_since)?page.next_since:this.cursor+lines.length;if(next<this.cursor||(page.has_more&&next<=this.cursor))throw Error('日志分页游标无效');this.cursor=next;this.lines.push(...lines);if(this.lines.length>this.maxLines){const remove=this.lines.length-this.maxLines;this.lines.splice(0,remove);this.dropped+=remove;}return true;}
}
export function fingerprint(value:any):string {if(Array.isArray(value))return '['+value.map(fingerprint).join(',')+']';if(value&&typeof value==='object')return '{'+Object.keys(value).sort().filter(k=>value[k]!==undefined).map(k=>JSON.stringify(k)+':'+fingerprint(value[k])).join(',')+'}';return JSON.stringify(value);}
export class PreviewGate {
  record:{key:string;token:string;body:Json;report?:Json}|null=null;
  set(context:Json,token:string,body:Json,report?:Json){this.record={key:fingerprint(context),token,body:JSON.parse(JSON.stringify(body)),report};}
  valid(context:Json){return !!this.record&&this.record.key===fingerprint(context);}
  clear(){this.record=null;}
}
export class Workflow {
  key='';assembledKey='';content=0;checkKey='';checkContent=-1;report:Json|null=null;
  update(input:Json){this.key=fingerprint(input);}
  assembled(){this.assembledKey=this.key;this.report=null;}
  checked(report:Json){this.report=report;this.checkKey=this.key;this.checkContent=this.content;}
  contentChanged(){this.content++;}
  get assemblyCurrent(){return !!this.assembledKey&&this.assembledKey===this.key;}
  get canRun(){return this.assemblyCurrent&&this.checkKey===this.key&&this.checkContent===this.content&&this.report?.ok===true;}
  reset(){this.assembledKey='';this.report=null;this.content++;}
}
export function resultPresentation(report:Json):{type:'success'|'danger'|'warning';label:string}{const verdicts:Record<string,string>={success:'成功',partial:'部分成功',no_update:'无模型更新',unconfirmed:'未确认',failed:'失败',cancelled:'已取消',pending:'处理中'};const verdict=report.historical_verdict||report.verdict;const current=report.current_files?.status;const descriptions:Record<string,string>={changed:'已变化',missing:'已缺失',unconfirmed:'未确认',unknown:'未确认'};if(report.historical&&current&&current!=='matching'&&current!=='matched'&&current!=='unchanged')return {type:'warning',label:'当时'+(verdicts[verdict]||'未确认')+'，当前文件'+(descriptions[current]||'需核对')};return {type:verdict==='success'?'success':['failed','cancelled'].includes(verdict)?'danger':'warning',label:(report.historical?'当时':'')+(verdicts[verdict]||'未确认')};}
export function rebaseDraft(saved:Json,draft:Json,latest:Json):Json{const result={...latest};for(const key of Object.keys(draft)){if(fingerprint(draft[key])!==fingerprint(saved[key]))result[key]=draft[key];}return result;}
export function logFollowKey(log:Pick<LogSession,'generation'|'cursor'> & {sequence?:number}){return [log.generation,log.cursor,log.sequence||0];}
export function clampLogHeight(requested:number,viewportHeight:number){const maximum=Math.max(80,Math.min(600,Math.floor(viewportHeight*.42),viewportHeight-250));const minimum=Math.min(viewportHeight<500?96:150,maximum);return Math.round(Math.max(minimum,Math.min(maximum,Number(requested)||250)));}
