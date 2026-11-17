/** Stateful terminal text only: CSI/OSC escapes never become HTML. */
export class TerminalText {
 completed:string[]=[]; current=''; dropped=0; carriage=false; escape=''; maxLines=3000; maxColumns=32768; maxCharacters=1048576; completedCharacters=0;
 feed(text:string){
  for(const char of text){
   if(this.escape){
    if(this.escape==='esc'){this.escape=char==='['?'csi':char===']'?'osc':'';continue;}
    if(this.escape==='csi'){if(char>='@'&&char<='~')this.escape='';continue;}
    if(this.escape==='osc'){if(char==='\x07')this.escape='';else if(char==='\x1b')this.escape='osc-esc';continue;}
    if(this.escape==='osc-esc'){this.escape=char==='\\'?'':'osc';continue;}
   }
   if(char==='\x1b'){this.escape='esc';continue;}
   if(char==='\r'){this.carriage=true;continue;}
   if(char==='\n'){this.completed.push(this.current);this.completedCharacters+=this.current.length;this.current='';this.carriage=false;this.trim();continue;}
   if(char==='\b'){this.current=this.current.slice(0,-1);continue;}
   if(char<' '&&char!=='\t')continue;
   if(this.carriage){this.current='';this.carriage=false;}
   this.current=(this.current+char).slice(-this.maxColumns);
  }
  this.trim();
 }
 trim(){while(this.completed.length&&(this.completed.length>=this.maxLines||this.completedCharacters+this.current.length>this.maxCharacters)){this.completedCharacters-=this.completed.shift()!.length;this.dropped++;}}
 get lines(){return this.current?[...this.completed,this.current]:[...this.completed];}
}
