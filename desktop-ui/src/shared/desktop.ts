export interface DesktopBridge {
 pickDirectory(options:{title?:string;defaultPath?:string}):Promise<string|null>;
 pickFile(options:{title?:string;defaultPath?:string;extensions?:string[]}):Promise<string|null>;
 exportSessionLog(options:{sid:number|string}):Promise<{saved:boolean;path?:string}>;
 saveText(options:{suggestedName:string;text:string}):Promise<{saved:boolean;path?:string}>;
 openPath(path:string):Promise<void>;
 info():Promise<{version:string;channel:string;dataDir:string;resourceRoot:string}>;
 setDirty(dirty:boolean):void;
}
declare global {interface Window {desktop?:DesktopBridge;}}
export async function pickPath(kind:'directory'|'file',current='',extensions?:string[]){if(!window.desktop)return null;return kind==='directory'?window.desktop.pickDirectory({title:'选择本机资源目录',defaultPath:current}):window.desktop.pickFile({title:'选择本机文件',defaultPath:current,extensions});}
export async function openPath(path:string){if(path&&window.desktop)await window.desktop.openPath(path);}
export async function saveText(suggestedName:string,text:string){if(window.desktop)return window.desktop.saveText({suggestedName,text});const blob=new Blob(['\uFEFF',text],{type:'text/plain;charset=utf-8'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=suggestedName;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);return {saved:true};}

export async function exportSessionLog(sid:number|string){
 if(window.desktop)return window.desktop.exportSessionLog({sid});
 const link=document.createElement('a');link.href='/api/export_log?'+new URLSearchParams({sid:String(sid)});link.download='lishuttle-session-'+sid+'.log';link.click();return {saved:true};
}
