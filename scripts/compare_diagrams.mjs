// Compare exact-source, portable SVGs from two review:diagrams runs. No network.
import fs from "node:fs/promises";
import path from "node:path";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { DOMParser } from "linkedom";
import { diagramQuality, readDiagramGeometry } from "../web/diagram-quality.js";

const [before, after, output] = process.argv.slice(2).map((p) => path.resolve(p));
if (!output) throw new Error("Usage: node scripts/compare_diagrams.mjs BEFORE AFTER OUTPUT");
await fs.mkdir(output, { recursive: true });
const names = (await fs.readdir(before)).filter((f) => f.endsWith("-light.svg") && !f.startsWith("tin-workflows-"));
assert.ok(names.length, "before gallery contains diagrams");
const records = [];
for (const name of names) {
  const id = name.slice(0, -10), sources = await Promise.all([before, after].map((d) => fs.readFile(path.join(d, `${id}.mmd`))));
  assert.ok(sources[0].equals(sources[1]), `${id}: before/after must use identical source bytes`);
  const record = { id, source_sha256: createHash("sha256").update(sources[0]).digest("hex") };
  for (const [side, directory] of [["before", before], ["after", after]]) {
    for (const theme of ["light", "dark"]) {
      const filename = `${id}-${theme}.svg`, svg = await fs.readFile(path.join(directory, filename), "utf8");
      const doc = new DOMParser().parseFromString(svg, "image/svg+xml");
      const [geometry] = readDiagramGeometry(doc);
      const quality = diagramQuality(geometry);
      if (theme === "light") {
        record[side] = quality;
        record[`${side}_identity`] = {
          nodes: [...doc.querySelectorAll("g.node")].map((n) => [n.getAttribute("data-id"), n.getAttribute("aria-label"), n.textContent]),
          edges: [...doc.querySelectorAll(".edge")].map((e) => [e.getAttribute("data-from"), e.getAttribute("data-to"), e.getAttribute("stroke-dasharray")]),
          labels: [...doc.querySelectorAll(".edge-label")].map((e) => [e.getAttribute("data-from"), e.getAttribute("data-to"), e.textContent]),
          groups: [...doc.querySelectorAll(".tin-diagram-group")].map((g) => [g.getAttribute("data-group-id"), g.textContent]),
        };
      } else assert.deepEqual(quality, record[side], `${id}: theme geometry differs`);
      await fs.mkdir(path.join(output, side), { recursive: true });
      await fs.copyFile(path.join(directory, filename), path.join(output, side, filename));
    }
  }
  assert.deepEqual(record.before_identity, record.after_identity, `${id}: changed facts or connectivity`);
  delete record.before_identity; delete record.after_identity;
  record.changed = JSON.stringify(record.before) !== JSON.stringify(record.after);
  records.push(record);
}
await fs.writeFile(path.join(output, "comparison.json"), JSON.stringify(records, null, 2));
const escape = (s) => s.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll('"', "&quot;");
records.sort((a, b) => Number(b.changed) - Number(a.changed) || a.id.localeCompare(b.id));
const options = records.map((r) => `<option value="${escape(r.id)}">${r.changed ? "Improved / changed · " : "Preserved · "}${escape(r.id)}</option>`).join("");
await fs.writeFile(path.join(output, "index.html"), `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Tin diagram comparison</title>
<style>*{box-sizing:border-box}body{margin:0;background:#141210;color:#f6f1e7;font:14px system-ui,sans-serif}header{padding:20px 24px;display:flex;gap:12px;align-items:center;flex-wrap:wrap;border-bottom:1px solid #7776}h1{font-size:18px;margin:0 16px 0 0}button,select{font:inherit;color:inherit;background:transparent;border:1px solid #7778;border-radius:6px;padding:8px}select{max-width:460px}option{background:#25221c;color:#f6f1e7}main{display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:20px 24px}article{min-width:0}h2{font-size:16px;margin:0 0 10px}p{margin:0 0 14px;color:#99958c;line-height:1.5}.viewport{height:calc(100vh - 220px);min-height:300px;overflow:auto;display:grid;place-items:safe center;border:1px solid #7776;border-radius:8px;background:#141210}img{display:block}a{color:inherit}footer{padding:0 24px 20px;color:#99958c}.light{background:#f7f5ef;color:#26231c}.light .viewport{background:#f7f5ef}@media(max-width:750px){main{grid-template-columns:1fr}.viewport{height:55vh}}</style>
<header><h1>Tin · Before / after</h1><select id="case" aria-label="Diagram">${options}</select><button id="theme">Light mode</button><button id="out" aria-label="Zoom out">−</button><button id="fit">Fit</button><button id="in" aria-label="Zoom in">+</button><span id="zoom"></span></header>
<main>${["before", "after"].map((side) => `<article><h2>${side === "before" ? "Before · baseline" : "After · composition refinements"}</h2><p id="${side}-metrics"></p><div class="viewport"><img id="${side}" alt="${side} diagram"></div><p><a id="${side}-link" target="_blank">Open full SVG</a></p></article>`).join("")}</main>
<footer>${records.length} identical-source comparisons, both themes. ${records.filter((r) => r.changed).length} changed layouts; all other layouts preserved. Metrics are diagnostic, not a beauty score. Seven architecture studies are historical references; ClawMessenger is a saved proposed diagnostic, not live messaging proof. <a href="comparison.json">Measurements</a></footer>
<script type="module">const records=await(await fetch('comparison.json')).json();let dark=true,zoom=1;const select=document.querySelector('#case');function size(){for(const side of ['before','after']){const img=document.getElementById(side),box=img.parentElement;if(!img.naturalWidth)continue;const fit=Math.min(1,(box.clientWidth-24)/img.naturalWidth,(box.clientHeight-24)/img.naturalHeight);img.style.width=img.naturalWidth*fit*zoom+'px';img.style.height=img.naturalHeight*fit*zoom+'px'}document.querySelector('#zoom').textContent=Math.round(zoom*100)+'% of fit'}function show(){const r=records.find(r=>r.id===select.value);for(const side of ['before','after']){const q=r[side],img=document.getElementById(side);img.onload=size;img.src=side+'/'+r.id+'-'+(dark?'dark':'light')+'.svg';document.getElementById(side+'-link').href=img.src;document.getElementById(side+'-metrics').textContent=q.width+' × '+q.height+' · '+q.bends+' bends · '+q.crossings+' crossings · '+Math.round(q.routeLength)+'px of paths'}size()}select.onchange=()=>{zoom=1;show()};document.querySelector('#theme').onclick=()=>{dark=!dark;document.body.classList.toggle('light',!dark);document.querySelector('#theme').textContent=dark?'Light mode':'Dark mode';show()};document.querySelector('#fit').onclick=()=>{zoom=1;size();document.querySelectorAll('.viewport').forEach(n=>n.scrollTo(0,0))};document.querySelector('#in').onclick=()=>{zoom=Math.min(8,zoom*1.4);size()};document.querySelector('#out').onclick=()=>{zoom=Math.max(.25,zoom/1.4);size()};window.onresize=size;show();</script></html>`);
for (const record of records.filter((r) => r.changed)) console.log(record.id, JSON.stringify({ before: record.before, after: record.after }));
console.log(`${records.length} identical sources and identities, ${records.filter((r) => r.changed).length} changed layouts; both themes agree.`);
