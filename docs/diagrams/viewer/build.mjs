// A static viewer packaged as one Cloudflare-compatible worker, without a framework.
import fs from 'node:fs/promises';
import path from 'node:path';
const root = import.meta.dirname;
const entries = [];
for (const [url, name, mime] of [
  ['/', 'index.html', 'text/html; charset=utf-8'],
  ['/viewer.css', 'viewer.css', 'text/css; charset=utf-8'],
  ['/viewer.js', 'viewer.js', 'text/javascript; charset=utf-8'],
  ...['how-it-is-built','one-run'].flatMap(id => ['light','dark'].map(theme => [`/assets/${id}-${theme}.svg`, `assets/${id}-${theme}.svg`, 'image/svg+xml; charset=utf-8'])),
]) entries.push([url, {mime, body: await fs.readFile(path.join(root, name), 'utf8')}]);
await fs.mkdir(path.join(root, 'dist/server'), {recursive: true});
await fs.writeFile(path.join(root, 'dist/server/index.js'), `const files = new Map(${JSON.stringify(entries)});
export default {fetch(request) {
  const file = files.get(new URL(request.url).pathname);
  if (!file) return new Response('Not found', {status:404});
  if (!['GET','HEAD'].includes(request.method)) return new Response('Method not allowed', {status:405});
  return new Response(request.method === 'HEAD' ? null : file.body, {headers: {
    'Content-Type':file.mime, 'Cache-Control':'no-cache', 'X-Content-Type-Options':'nosniff',
    'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; object-src 'none'; base-uri 'none'"
  }});
}};
`);
console.log('Built static Tin diagram viewer.');
