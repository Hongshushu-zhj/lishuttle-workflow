const fs = require('node:fs');
const path = require('node:path');
module.exports = function frontendSource() {
  const root = path.join(__dirname, '../platform/frontend');
  const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
  // Older VM fixtures use minimal elements. Give the new select controls the
  // native DOM primitives they need, while retaining each fixture's own nodes.
  const runtimeControls = ['runtime-config-select','runtime-config-mode','runtime-config-status',
    'runtime-config-details','runtime-existing-panel','runtime-import-panel','runtime-import-preview',
    'runtime-import-candidate','task-catalogs','assembly-input-files','assembly-resource-options'];
  const fixtureDOM = `(function () {
    if (typeof Option === 'undefined') globalThis.Option = function(text,value) { this.text=text;this.value=value; };
    ${JSON.stringify(runtimeControls)}.forEach(function(id) {
      const node=document.getElementById(id);if(!node)return;
      if(!node.replaceChildren)node.replaceChildren=function(){this.innerHTML='';this.value=arguments[0]?.value || '';};
      if(!node.add)node.add=function(){};
      if(node.classList && !node.classList.toggle)node.classList.toggle=function(c,on){this[on?'add':'remove'](c);};
    });
  }());\n`;
  return fixtureDOM + [...html.matchAll(/<script\s+src="([^"]+)"\s*><\/script>/g)]
    .map(match => fs.readFileSync(path.join(root, match[1]), 'utf8')).join('\n')
    .replace(/init\(\);\s*$/, '');
};
