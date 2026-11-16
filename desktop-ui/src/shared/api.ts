import type {Json} from '../domain/controllers.ts';
import {Scope} from '../domain/controllers.ts';
export class ApiError extends Error {data:Json; constructor(data:Json){super(data.message||data.error||'操作未完成');this.data=data;}}
export class UnknownOutcomeError extends Error {operation:string;constructor(operation:string){super('请求已发出，但未收到可靠响应。操作结果待核对，请刷新状态、核对文件或运行记录后再手动操作；不会自动重试。');this.operation=operation;}}
export class ApiClient {
  scope=new Scope();
  async request(name:string,body?:Json,method=body?'POST':'GET'):Promise<Json>{
    const data={...(['state','runtime_state','output'].includes(name)?{}:this.scope.context()),...(body||{})};const query=new URLSearchParams();Object.entries(data).forEach(([k,v])=>{if(v!==undefined&&v!==null&&v!=='')query.set(k,String(v));});
    let response:Response;try{response=await fetch('/api/'+name+(method==='GET'?'?'+query:''),{method,credentials:'same-origin',headers:method==='POST'?{'Content-Type':'application/json'}:undefined,body:method==='POST'?JSON.stringify(data):undefined});}catch(error){if(method==='POST')throw new UnknownOutcomeError(name);throw error;}
    let result:Json;try{result=await response.json();}catch{if(method==='POST')throw new UnknownOutcomeError(name);throw Error('服务响应无法读取');}
    if(!response.ok||result.error||(result.ok===false&&!['preflight','validate_setup'].includes(name)))throw new ApiError(result);return result;
  }
  get(name:string,query:Json={}){return this.request(name,query,'GET');}
  post(name:string,body:Json={}){return this.request(name,body,'POST');}
}
