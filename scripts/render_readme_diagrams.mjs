// README export adapter: layout stays in the shared Tin renderer checkout.
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { execFileSync } from "node:child_process";

const renderer = path.resolve(process.argv[2] || "../tin-lite-diagram-chain-alignment");
const rendererRevision = "52344467a4b6d9eed302207a560bc640e0f3ca0c";
assert.equal(
  execFileSync("git", ["-C", renderer, "rev-parse", "HEAD"], {
    encoding: "utf8",
  }).trim(),
  rendererRevision,
  "Use the documented renderer revision for these exports.",
);
assert.equal(
  execFileSync(
    "git",
    ["-C", renderer, "status", "--porcelain", "--untracked-files=no"],
    { encoding: "utf8" },
  ).trim(),
  "",
  "Render from a clean checkout.",
);
const repo = path.resolve(import.meta.dirname, "..");
const output = path.join(repo, "docs/diagrams");
const qa = path.resolve(
  process.env.TIN_DIAGRAM_SCREENSHOTS || "/tmp/tin-readme-diagram-qa",
);
const assets = path.join(renderer, "src/tin_lite/static");
const { chromium } = await import(
  pathToFileURL(path.join(renderer, "node_modules/playwright/index.mjs"))
);
const { auditDiagrams } = await import(
  pathToFileURL(path.join(renderer, "web/diagram-audit.js"))
);
const css = await fs.readFile(path.join(assets, "app.css"), "utf8");
const cases = [
  {
    id: "how-it-is-built",
    title: "How Tin is built",
    description:
      "The Tin web app and your coding agent call Tin's server. Temporal Cloud coordinates work executed by Tin's workers. Those workers create E2B sandboxes, where Codex can use a Camoufox browser. Project files and Postgres are durable; model API keys and integration credentials stay on Tin's server.",
  },
  {
    id: "one-run",
    title: "One Tin workflow run",
    description:
      "A trigger starts a pinned, project-bound run. It reads context, executes as a trusted step or sandbox, commits its result, and projects it to Postgres. Tin finishes automatic work; human decisions gate approved effects.",
  },
];
await fs.mkdir(qa, { recursive: true });
const scratch = await fs.mkdtemp(path.join(os.tmpdir(), "tin-readme-export-"));
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  if (url.pathname === "/")
    return res.end(
      `<!doctype html><html><head><style>${css}\nbody{margin:0;padding:24px;background:var(--paper-bg)}.tin-diagram{overflow:visible;width:max-content}svg text{font-kerning:none;font-variant-ligatures:none}</style></head><body><section id="review"><div class="tin-diagram"></div></section><script src="/assets/diagram-renderer.js"></script></body></html>`,
    );
  try {
    const base = url.pathname.startsWith("/export/") ? output : assets;
    const file = path.resolve(
      base,
      "." + url.pathname.replace(/^\/(assets|export)/, ""),
    );
    if (!file.startsWith(base + path.sep)) throw new Error("outside assets");
    res.setHeader(
      "Content-Type",
      file.endsWith(".js")
        ? "text/javascript"
        : file.endsWith(".wasm")
          ? "application/wasm"
          : file.endsWith(".svg")
            ? "image/svg+xml"
            : "font/woff2",
    );
    res.end(await fs.readFile(file));
  } catch {
    res.writeHead(404).end();
  }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({
    viewport: { width: 1200, height: 900 },
    deviceScaleFactor: 2,
  });
  await page.route("**/*", (route) =>
    route.request().url().startsWith(base) ? route.continue() : route.abort(),
  );
  await page.goto(base);
  for (const item of cases)
    for (const theme of ["light", "dark"]) {
      const source = await fs.readFile(
        path.join(output, `${item.id}.mmd`),
        "utf8",
      );
      await page.evaluate(
        async ({ source, theme }) => {
          document.documentElement.dataset.theme = theme;
          document.querySelector(".tin-diagram").innerHTML =
            await window.TinDiagramRenderer.renderSource(source);
          await Promise.all(
            [400, 700].flatMap((w) =>
              ["Sans", "Mono"].map((f) =>
                document.fonts.load(`${w} 12px "Tin Diagram ${f}"`),
              ),
            ),
          );
          await document.fonts.ready;
        },
        { source, theme },
      );
      const audit = await page.evaluate(auditDiagrams);
      assert.deepEqual(audit.issues, [], `${item.id}/${theme}`);
      if (item.centeredNodes) {
        const centers = await page.evaluate(
          (ids) =>
            ids.map((id) => {
              const box = document.querySelector(`.node[data-id="${id}"] rect`);
              return (
                Number(box.getAttribute("x")) +
                Number(box.getAttribute("width")) / 2
              );
            }),
          item.centeredNodes,
        );
        assert.ok(
          Math.max(...centers) - Math.min(...centers) < 0.001,
          `${item.id}: input centerlines drifted`,
        );
      }
      await fs.writeFile(
        path.join(qa, `${item.id}-${theme}-audit.json`),
        JSON.stringify(audit, null, 2),
      );
      await page
        .locator(".tin-diagram")
        .screenshot({ path: path.join(qa, `${item.id}-${theme}-text.png`) });
      const payload = await page.evaluate((item) => {
        const ns = "http://www.w3.org/2000/svg",
          svg = document.querySelector(".tin-diagram svg");
        const text = [...svg.querySelectorAll("text")].map((element, index) => {
          element.dataset.outlineId = String(index);
          const lines = [
            ...(element.querySelectorAll("tspan").length
              ? element.querySelectorAll("tspan")
              : [element]),
          ].map((line) => {
            const style = getComputedStyle(line),
              name = style.fontFamily.includes("Mono")
                ? "geist-mono"
                : "geist-sans",
              weight = Number(style.fontWeight) >= 700 ? "bold" : "regular";
            let offset = 0;
            const chars = [...line.textContent].map((char) => {
              const p = line.getStartPositionOfChar(offset);
              offset += char.length;
              return { char, x: p.x, y: p.y };
            });
            return {
              font: `${name}-${weight}.woff2`,
              size: parseFloat(style.fontSize),
              fill: style.fill,
              chars,
            };
          });
          return { id: String(index), label: element.textContent, lines };
        });
        for (const el of svg.querySelectorAll("*"))
          for (const attr of [...el.attributes])
            if (attr.value.includes("var("))
              el.setAttribute(
                attr.name,
                getComputedStyle(el).getPropertyValue(attr.name),
              );
        const width = svg.viewBox.baseVal.width + 48,
          height = svg.viewBox.baseVal.height + 48;
        svg.setAttribute("viewBox", `-24 -24 ${width} ${height}`);
        svg.setAttribute("width", String(width));
        svg.setAttribute("height", String(height));
        svg.setAttribute("aria-label", item.title);
        svg.removeAttribute("style");
        const title = document.createElementNS(ns, "title");
        title.textContent = item.title;
        const desc = document.createElementNS(ns, "desc");
        desc.textContent = item.description;
        svg.prepend(title, desc);
        return { svg: new XMLSerializer().serializeToString(svg), text };
      }, item);
      const input = path.join(scratch, `${item.id}-${theme}.json`),
        svgFile = path.join(output, `${item.id}-${theme}.svg`);
      await fs.writeFile(input, JSON.stringify(payload));
      execFileSync(
        "uv",
        [
          "run",
          "--no-project",
          "--with",
          "fonttools==4.59.0",
          "--with",
          "brotli==1.1.0",
          "python",
          path.join(repo, "scripts/outline_diagram_svg.py"),
          path.join(assets, "fonts"),
          input,
          svgFile,
        ],
        { stdio: "inherit" },
      );
      const svg = await fs.readFile(svgFile, "utf8");
      assert.doesNotMatch(
        svg,
        /<(?:text|tspan|style|script|image|foreignObject)\b|@font-face|data:|url\(|var\(/,
      );
      console.log(
        `${item.id}/${theme}: validated, outlined, ${Buffer.byteLength(svg)} bytes`,
      );
    }
  // Exercise the exact image embedding mode with fonts and networking unavailable.
  for (const theme of ["light", "dark"])
    for (const width of [830, 390]) {
      await page.emulateMedia({ colorScheme: theme });
      await page.setViewportSize({ width: width + 48, height: 900 });
      await page.setContent(
        `<style>body{margin:24px;background:${theme === "dark" ? "#0d1117" : "white"}}picture,img{display:block}img{max-width:100%;height:auto}figure{margin:0 0 32px}</style>${cases.map((c) => `<figure id="${c.id}"><picture><source media="(prefers-color-scheme: dark)" srcset="${base}/export/${c.id}-dark.svg"><img src="${base}/export/${c.id}-light.svg" alt="${c.description}"></picture></figure>`).join("")}`,
      );
      await page.evaluate(() =>
        Promise.all([...document.images].map((i) => i.decode())),
      );
      assert.ok(
        await page.evaluate(
          (theme) =>
            [...document.images].every(
              (i) =>
                i.currentSrc.endsWith(`-${theme}.svg`) && i.naturalWidth > 0,
            ),
          theme,
        ),
      );
      assert.ok(
        await page.evaluate(() =>
          [...document.images].every((img) => {
            const canvas = document.createElement("canvas");
            canvas.width = img.naturalWidth;
            canvas.height = img.naturalHeight;
            const context = canvas.getContext("2d");
            context.drawImage(img, 0, 0);
            return [
              [0, 0],
              [canvas.width - 1, 0],
              [0, canvas.height - 1],
              [canvas.width - 1, canvas.height - 1],
            ].every(([x, y]) => context.getImageData(x, y, 1, 1).data[3] === 0);
          }),
        ),
        "SVG backgrounds must stay transparent",
      );
      for (const item of cases)
        await page.locator(`#${item.id}`).screenshot({
          path: path.join(qa, `${item.id}-${theme}-${width}.png`),
        });
    }
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
  await fs.rm(scratch, { recursive: true, force: true });
}
