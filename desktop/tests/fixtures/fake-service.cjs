'use strict';
const readline=require('node:readline');let boot=false;
const mode=process.argv[2];const rl=readline.createInterface({input:process.stdin});
rl.on('line',line=>{const message=JSON.parse(line);if(!boot){boot=true;if(!message.session_secret||!message.data_dir)process.exit(3);if(mode==='bad-origin'){console.log(JSON.stringify({type:'ready',origin:'http://evil.test:49222'}));return;}if(mode==='crash'){process.exit(19);}console.log(JSON.stringify({type:'ready',origin:'http://127.0.0.1:49222'}));return;}
if(message.type==='activity'){console.log(JSON.stringify({type:'activity',request_id:message.request_id,busy:false,activity:{state:'idle'},pid:process.pid}));}
if(message.type==='shutdown'){console.log(JSON.stringify({type:'shutdown',request_id:message.request_id,status:'stopped'}));setTimeout(()=>process.exit(0),20);}
});rl.on('close',()=>process.exit(0));
