// Reproducible local visual review. Outputs are derived previews, outside git.
import fs from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { chromium } from "playwright";
import assert from "node:assert/strict";
import { diagramFixtures } from "../web/diagram-fixtures.js";
import { routingFixtures } from "../web/diagram-routing-fixtures.js";
import { auditDiagrams } from "../web/diagram-audit.js";
import { embeddedFonts, exportDiagrams } from "./diagram-review.mjs";
import { sourceForFlow } from "../web/diagram-contract.js";

const output = process.argv[2];
if (!output) throw new Error("Usage: node scripts/review_diagrams.mjs /absolute/review-directory");
await fs.mkdir(output, { recursive: true });
const qa = process.env.TIN_DIAGRAM_SCREENSHOTS || path.join(output, "qa");
await fs.mkdir(qa, { recursive: true });
// Local review only: compare a captured release's assets with the same sources.
const assets = path.resolve(process.env.TIN_DIAGRAM_REVIEW_ASSETS || "src/tin_lite/static");
const catalog = JSON.parse(execFileSync("uv", ["run", "--frozen", "python", "-c", [
  "import json", "from tin_lite.catalog import BUILTIN_WORKFLOWS",
  "print(json.dumps([{'id': w.key, 'title': w.title, 'flow': w.definition['presentation']['flow']} for w in BUILTIN_WORKFLOWS if w.presentation]))",
].join("\n")], { encoding: "utf8" }));
const studies = await Promise.all(JSON.parse(await fs.readFile("docs/diagram-studies/index.json", "utf8")).map(async (item) => ({ ...item, source: await fs.readFile(`docs/diagram-studies/${item.file}`, "utf8") })));
const extras = process.argv.slice(3);
const cases = [...studies, ...catalog, ...diagramFixtures, ...routingFixtures,
  ...await Promise.all(extras.map(async (file) => ({ id: path.basename(file, ".mmd"), title: path.basename(file, ".mmd"), source: await fs.readFile(file, "utf8") })))];
for (const item of cases) await fs.writeFile(path.join(output, `${item.id}.mmd`), item.source || sourceForFlow(item.flow));
const css = await fs.readFile(path.join(assets, "app.css"), "utf8");
const fontRules = await embeddedFonts(assets);
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  if (url.pathname === "/") return res.end(`<!doctype html><html><head><meta charset="utf-8"><style>${css}
    body{padding:32px;background:var(--paper-bg)}section{padding:28px 0;border-bottom:1px solid var(--card-border);width:max-content;min-width:1200px}h2{font:700 16px var(--diagram-sans);margin:0 0 24px;color:var(--ink-secondary)}.tin-diagram{overflow:visible}svg{margin:0!important}</style></head><body><main></main><script src="/diagram-renderer.js"></script></body></html>`);
  try {
    const root = url.pathname.startsWith("/review/") ? path.resolve(output) : assets;
    const file = path.resolve(root, `.${url.pathname.replace(/^\/(?:assets|review)\//, "/")}`);
    if (!file.startsWith(`${root}/`)) throw new Error("outside assets");
    res.setHeader("Content-Type", file.endsWith(".wasm") ? "application/wasm" : file.endsWith(".js") ? "text/javascript" : file.endsWith(".svg") ? "image/svg+xml" : file.endsWith(".html") ? "text/html" : "font/woff2");
    res.end(await fs.readFile(file));
  } catch { res.writeHead(404).end(); }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 }, deviceScaleFactor: 2 });
  const base = `http://127.0.0.1:${server.address().port}`;
  await page.goto(base);
  for (const theme of ["light", "dark"]) {
    await page.evaluate(async ({ cases, theme }) => {
      document.documentElement.dataset.theme = theme;
      document.querySelector("main").replaceChildren();
      for (const item of cases) {
        const section = document.createElement("section"); section.id = item.id;
        const heading = document.createElement("h2"); heading.textContent = item.title;
        const stage = document.createElement("div"); stage.className = "tin-diagram";
        stage.innerHTML = item.source ? await window.TinDiagramRenderer.renderSource(item.source) : (await window.TinDiagramRenderer.renderFlow(item.flow)).svg;
        section.append(heading, stage); document.querySelector("main").append(section);
      }
      await Promise.all([400, 700].flatMap((weight) => ["Tin Diagram Sans", "Tin Diagram Mono"].map((family) => document.fonts.load(`${weight} 12px "${family}"`))));
      await document.fonts.ready;
    }, { cases, theme });
    const audit = await page.evaluate(auditDiagrams);
    await fs.writeFile(path.join(qa, `${theme}-audit.json`), JSON.stringify(audit, null, 2));
    if (audit.issues.length) process.exitCode = 1;
    console.log(`${theme}: ${cases.length} diagrams, ${audit.issues.length} audit issues`);
    const exports = await page.evaluate(exportDiagrams, { fontRules });
    for (const item of exports) {
      await fs.writeFile(path.join(output, `${item.id}-${theme}.svg`), item.svg);
      await page.locator(`section[id="${item.id}"]`).screenshot({ path: path.join(qa, `${item.id}-${theme}.png`) });
    }
    const overview = await page.evaluate(({ exports, catalog, fontRules }) => {
      const ns = "http://www.w3.org/2000/svg";
      const svg = document.createElementNS(ns, "svg");
      const rows = catalog.map((item) => ({ ...item, svg: new DOMParser().parseFromString(exports.find((e) => e.id === item.id).svg, "image/svg+xml").documentElement }));
      const width = Math.max(960, ...rows.map((item) => Number(item.svg.getAttribute("width")))) + 64;
      const height = rows.reduce((total, item) => total + Number(item.svg.getAttribute("height")) + 64, 32);
      for (const [key, value] of Object.entries({ width, height, viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": "Tin workflows" })) svg.setAttribute(key, value);
      const style = document.createElementNS(ns, "style"); style.textContent = fontRules; svg.append(style);
      const background = document.createElementNS(ns, "rect");
      for (const [key, value] of Object.entries({ width, height, fill: getComputedStyle(document.body).backgroundColor })) background.setAttribute(key, value);
      svg.append(background);
      let y = 32;
      for (const row of rows) {
        const title = document.createElementNS(ns, "text"); title.textContent = row.title;
        for (const [key, value] of Object.entries({ x: 56, y: y + 18, fill: getComputedStyle(document.body).getPropertyValue("--ink").trim(), "font-family": "Tin Diagram Sans", "font-size": 18, "font-weight": 700 })) title.setAttribute(key, value);
        row.svg.querySelector("style").remove(); row.svg.setAttribute("x", 32); row.svg.setAttribute("y", y + 32);
        svg.append(title, row.svg); y += Number(row.svg.getAttribute("height")) + 64;
      }
      return new XMLSerializer().serializeToString(svg);
    }, { exports, catalog, fontRules });
    await fs.writeFile(path.join(output, `tin-workflows-${theme}.svg`), overview);
  }
  const escape = (s) => s.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll('"', "&quot;");
  const html = `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Tin diagram review</title><style>${fontRules}
    *{box-sizing:border-box}body{margin:0;padding:40px;background:#f7f5ef;color:#26231c;font:14px "Tin Diagram Sans",sans-serif}header{display:flex;gap:24px;align-items:center;flex-wrap:wrap}h1{font-size:26px;margin:0}p{color:#5f594c}button,select{font:inherit;padding:8px 12px;border:1px solid #c8c3b9;border-radius:6px;background:transparent;color:inherit}section{margin:40px 0}h2{font-size:16px;margin:0 0 12px}figure{margin:0;overflow:auto;border:1px solid #d9d5cc;border-radius:8px}img{display:block;max-width:none}a{color:inherit}.dark{background:#141210;color:#f6f1e7}.dark figure{border-color:#3d3831}.dark p{color:#b3aa9b}</style>
    <header><h1>Tin · Diagram studies</h1><button id="theme">Switch to coal</button><select id="direction"><option value="all">All layouts</option><option value="composition">Compositions</option><option value="lr">Left to right</option><option value="td">Top to bottom</option></select></header>
    <p>${cases.length} studies · seven screenshot reconstructions, real workflow definitions, and varied fixtures · Geist Sans + Geist Mono · vector artwork at natural size. Scroll wide diagrams; open an SVG to zoom.</p>
    <p>The seven composition studies preserve the supplied architecture references; they are not a description of the current deployed product.</p><p>Workflow overview: <a href="tin-workflows-light.svg">Paper SVG</a> · <a href="tin-workflows-dark.svg">Coal SVG</a></p>
    ${cases.map((item) => `<section data-direction="${(item.source || item.flow?.groups) ? "composition" : item.flow.direction.toLowerCase()}" data-study="${Boolean(item.source)}"><h2>${escape(item.title)} · <a data-id="${escape(item.id)}" href="${escape(item.id)}-light.svg">Open SVG</a> · <a href="${escape(item.id)}.mmd">Editable source</a></h2><figure><img data-id="${escape(item.id)}" src="${escape(item.id)}-light.svg" alt="${escape(item.title)}"></figure></section>`).join("\n")}
    <script>let dark=false;document.querySelector('#theme').onclick=()=>{dark=!dark;document.body.classList.toggle('dark',dark);document.querySelector('#theme').textContent=dark?'Switch to paper':'Switch to coal';for(const n of document.querySelectorAll('[data-id]'))n[n.tagName==='IMG'?'src':'href']=n.dataset.id+'-'+(dark?'dark':'light')+'.svg'};document.querySelector('#direction').onchange=e=>{for(const s of document.querySelectorAll('section'))s.hidden=e.target.value!=='all'&&s.dataset.direction!==e.target.value}</script></html>`;
  await fs.writeFile(path.join(output, "index.html"), html);
  const references = html.replace(/<section data-direction="[^"]*" data-study="false"[\s\S]*?<\/section>/g, "")
    .replace(`${cases.length} studies · seven screenshot reconstructions, real workflow definitions, and varied fixtures`, "Seven screenshot reconstructions")
    .replace(/<p>Workflow overview:[\s\S]*?<\/p>/, "")
    .replace(/<option value="lr">[\s\S]*?<\/select>/, "</select>");
  await fs.writeFile(path.join(output, "references.html"), references);
  // Verify portable exports without the product stylesheet or local font lookup.
  for (const theme of ["light", "dark"]) {
    await page.goto(`${base}/review/tin-workflows-${theme}.svg`);
    await page.evaluate(async () => {
      await Promise.all([400, 700].flatMap((weight) => ["Tin Diagram Sans", "Tin Diagram Mono"].map((family) => document.fonts.load(`${weight} 12px "${family}"`))));
      await document.fonts.ready;
    });
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("DOM.enable"); await cdp.send("CSS.enable");
    const { root } = await cdp.send("DOM.getDocument");
    const { nodeId } = await cdp.send("DOM.querySelector", { nodeId: root.nodeId, selector: "tspan" });
    const { fonts } = await cdp.send("CSS.getPlatformFontsForNode", { nodeId });
    assert.ok(fonts.some((font) => font.familyName === "Geist" && font.isCustomFont), "export must use embedded open-source Geist");
    await cdp.detach();
  }
  await page.goto(`${base}/review/index.html`);
  await page.evaluate(async () => { await Promise.all([...document.images].map((img) => img.decode())); await document.fonts.ready; });
  assert.equal(await page.locator("img").count(), cases.length);
  await page.screenshot({ path: path.join(qa, "gallery-light.png") });
  await page.locator("#theme").click();
  await page.evaluate(async () => { await Promise.all([...document.images].map((img) => img.decode())); });
  await page.screenshot({ path: path.join(qa, "gallery-dark.png") });
  await page.locator("#direction").selectOption("td");
  assert.equal(await page.locator("section:visible").count(), cases.filter((c) => !c.source && !c.flow.groups && c.flow.direction === "TD").length);
  console.log("Portable SVG fonts, gallery images, theme switch, and layout filter verified.");
} finally { await browser.close(); await new Promise((resolve) => server.close(resolve)); }
