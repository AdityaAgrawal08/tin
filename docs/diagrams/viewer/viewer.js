const viewport = document.querySelector('#viewport');
const diagram = document.querySelector('#diagram');
const scaleLabel = document.querySelector('#scale');
const notice = document.querySelector('#loading');
const media = matchMedia('(prefers-color-scheme: dark)');
const figures = {
  'how-it-is-built': {title: 'How Tin is built', alt: 'Browser, Chat and coding agents use the Switchboard. Temporal coordinates temporary sandboxes. The Switchboard writes project files and Postgres and calls integrations.'},
  'one-run': {title: 'One Tin workflow run', alt: 'A trigger starts a pinned workflow, reads context, runs a trusted step or sandbox, commits the result and updates Postgres. Automatic work completes; human approval releases external effects.'},
};
let theme = media.matches ? 'dark' : 'light';
let id, version = 0, ready = false, scale = 1, x = 0, y = 0;
const pointers = new Map();
const center = () => ({x: viewport.clientWidth / 2, y: viewport.clientHeight / 2});
const point = event => {const r = viewport.getBoundingClientRect(); return {x: event.clientX - r.left, y: event.clientY - r.top};};
function paint() {
  diagram.style.transform = `translate(${x}px, ${y}px) scale(${scale})`;
  scaleLabel.value = `${Math.round(scale * 100)}%`;
}
function zoom(next, at = center()) {
  if (!ready) return;
  next = Math.max(0.05, Math.min(8, next));
  x = at.x - (at.x - x) * next / scale;
  y = at.y - (at.y - y) * next / scale;
  scale = next; paint();
}
function fit() {
  if (!ready || !viewport.clientWidth || !viewport.clientHeight) return;
  scale = Math.max(0.05, Math.min((viewport.clientWidth - 32) / diagram.naturalWidth, (viewport.clientHeight - 32) / diagram.naturalHeight));
  x = (viewport.clientWidth - diagram.naturalWidth * scale) / 2;
  y = (viewport.clientHeight - diagram.naturalHeight * scale) / 2;
  paint();
}
async function show(reset = true) {
  id = Object.hasOwn(figures, location.hash.slice(1)) ? location.hash.slice(1) : 'how-it-is-built';
  const current = ++version;
  const src = `/assets/${id}-${theme}.svg`;
  document.documentElement.dataset.theme = theme;
  document.title = `${figures[id].title} · Tin`;
  document.querySelectorAll('nav a').forEach(a => a.setAttribute('aria-current', a.hash === `#${id}` ? 'page' : 'false'));
  document.querySelector('#theme').textContent = theme === 'dark' ? 'Light' : 'Dark';
  const download = document.querySelector('#download');
  download.href = src; download.download = `${id}-${theme}.svg`;
  ready = false; pointers.clear(); viewport.classList.remove('dragging');
  notice.hidden = false; notice.textContent = 'Loading diagram…';
  const preload = new Image(); preload.src = src;
  try {
    await preload.decode();
    if (current !== version) return;
    diagram.src = src; diagram.alt = figures[id].alt;
    await diagram.decode();
    if (current !== version) return;
    ready = true; diagram.hidden = false; notice.hidden = true;
    if (reset) fit(); else paint();
  } catch {
    if (current !== version) return;
    diagram.hidden = true;
    notice.textContent = 'The diagram could not load. Refresh to try again.';
  }
}
viewport.addEventListener('wheel', event => {
  event.preventDefault();
  const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? viewport.clientHeight : 1);
  zoom(scale * Math.exp(-Math.max(-150, Math.min(150, delta)) * 0.005), point(event));
}, {passive: false});
viewport.addEventListener('pointerdown', event => {
  if (!ready || (event.pointerType === 'mouse' && event.button !== 0)) return;
  viewport.focus({preventScroll: true});
  viewport.setPointerCapture(event.pointerId);
  pointers.set(event.pointerId, point(event)); viewport.classList.add('dragging');
});
viewport.addEventListener('pointermove', event => {
  if (!pointers.has(event.pointerId)) return;
  const before = [...pointers.values()];
  const old = pointers.get(event.pointerId), next = point(event);
  pointers.set(event.pointerId, next);
  if (pointers.size === 1) { x += next.x - old.x; y += next.y - old.y; paint(); }
  else if (pointers.size === 2) {
    const after = [...pointers.values()];
    const midpoint = p => ({x: (p[0].x + p[1].x) / 2, y: (p[0].y + p[1].y) / 2});
    const distance = p => Math.hypot(p[0].x - p[1].x, p[0].y - p[1].y);
    const a = midpoint(before), b = midpoint(after);
    if (distance(before) > 0) zoom(scale * distance(after) / distance(before), a);
    x += b.x - a.x; y += b.y - a.y; paint();
  }
});
for (const event of ['pointerup', 'pointercancel', 'lostpointercapture']) viewport.addEventListener(event, e => {
  pointers.delete(e.pointerId); if (!pointers.size) viewport.classList.remove('dragging');
});
viewport.addEventListener('keydown', event => {
  if (!ready) return;
  if (['+', '=', '-', '0', 'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) event.preventDefault();
  if (['+', '='].includes(event.key)) zoom(scale * 1.25);
  if (event.key === '-') zoom(scale / 1.25);
  if (event.key === '0') fit();
  if (event.key === 'ArrowLeft') x += 48;
  if (event.key === 'ArrowRight') x -= 48;
  if (event.key === 'ArrowUp') y += 48;
  if (event.key === 'ArrowDown') y -= 48;
  paint();
});
document.querySelector('#in').onclick = () => zoom(scale * 1.25);
document.querySelector('#out').onclick = () => zoom(scale / 1.25);
document.querySelector('#fit').onclick = fit;
document.querySelector('#actual').onclick = () => zoom(1);
document.querySelector('#theme').onclick = () => {theme = theme === 'dark' ? 'light' : 'dark'; show(false);};
const fullscreen = document.querySelector('#fullscreen');
fullscreen.hidden = !document.fullscreenEnabled;
fullscreen.onclick = async () => {
  try { if (document.fullscreenElement) await document.exitFullscreen(); else await document.documentElement.requestFullscreen(); }
  catch { fullscreen.hidden = true; }
};
document.addEventListener('fullscreenchange', () => {fullscreen.textContent = document.fullscreenElement ? 'Exit fullscreen' : 'Fullscreen';});
new ResizeObserver(fit).observe(viewport);
addEventListener('hashchange', () => show());
show();
