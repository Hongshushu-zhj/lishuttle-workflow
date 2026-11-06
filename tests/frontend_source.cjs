const fs = require('node:fs');
const path = require('node:path');
module.exports = function frontendSource() {
  const root = path.join(__dirname, '../platform/frontend');
  const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
  return [...html.matchAll(/<script\s+src="([^"]+)"\s*><\/script>/g)]
    .map(match => fs.readFileSync(path.join(root, match[1]), 'utf8')).join('\n')
    .replace(/init\(\);\s*$/, '');
};
