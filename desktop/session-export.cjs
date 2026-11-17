'use strict';
const http=require('node:http');
const fs=require('node:fs');
const promises=require('node:fs/promises');
const path=require('node:path');
const {randomUUID}=require('node:crypto');
const {pipeline}=require('node:stream/promises');
const {validateServiceOrigin,validateSessionExport,absolutePath}=require('./security.cjs');
/** Called only by main with its own backend credentials and native dialog path. */
async function streamSessionExport({origin,cookieName,secret,sid,target}){
 validateServiceOrigin(origin);({sid}=validateSessionExport({sid}));absolutePath(target);
 const temporary=path.join(path.dirname(target),'.lishuttle-log-'+randomUUID()+'.tmp');
 try{
  const response=await new Promise((resolve,reject)=>{
   const request=http.get(origin+'/api/export_log?'+new URLSearchParams({sid:String(sid)}),{headers:{Cookie:cookieName+'='+secret,Origin:origin}},resolve);
   request.on('error',reject);request.setTimeout(30000,()=>request.destroy(new Error('Log export timed out')));
  });
  if(response.statusCode!==200||!String(response.headers['content-type']).startsWith('text/plain')){response.resume();throw new Error('Log export failed ('+response.statusCode+')');}
  await pipeline(response,fs.createWriteStream(temporary,{flags:'wx'}));
  if(!response.complete)throw new Error('Log export was interrupted');
  await promises.rename(temporary,target);
 }finally{await promises.rm(temporary,{force:true});}
}
module.exports={streamSessionExport};
