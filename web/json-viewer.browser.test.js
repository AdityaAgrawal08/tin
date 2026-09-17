// Real packaged shell/assets with isolated HTTP fixtures and a synthetic identity.
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import test from "node:test";
import { chromium } from "playwright";

const assets = path.resolve("src/tin_lite/static");
const revision = "a1b2c3d" + "a".repeat(33);
const planPath = "content/plans/ef0cd960-831a-43ea-997a-c4b8642d4a70/plan.json";
const plan = JSON.stringify({
  audit_run_id: "3c9c9799-75d3-4951-989f-bae3a6252653", created_at: "2026-09-08T14:02:11Z", site: "virvid.app",
  batches: [{ id: "b-01", due_date: "2026-09-09", status: "open", tasks: [
    { id: "t-104", title: "Add canonical tags to the six comparison pages that still point at the pricing page instead of themselves", effort: "small", pages: 6 },
    { id: "t-105", title: "Rewrite the 14 meta descriptions over 160 characters", effort: "small", pages: 14 },
  ] }, { id: "b-02", due_date: "2026-09-10", status: "open", tasks: [] }],
  notes: "Batches are ordered by expected traffic impact. The third batch depends on the GitHub connection being restored before 2026-09-12.",
  totals: { tasks: 11, pages_touched: 38, estimated_hours: 6.5 }, source: null,
});
const tenKb = JSON.stringify({ plan: JSON.parse(plan),
  long_value: "https://example.com/" + "a".repeat(9500), escaped: '<script>alert("file")</script>😀' });
const fixtures = new Map([
  [planPath, plan],
  ["ten-kb.json", tenKb],
  ["invalid.json", '{"audit_run_id":"3c9c9799-75d3-4951-989f-bae3a6252653","title":"' + "unfinished ".repeat(80) + '",}'],
  ["audit.json", JSON.stringify({ site: "virvid.app", pages: Array.from({ length: 2500 }, (_, id) => ({ id, title: "Page " + id })),
    findings: Array.from({ length: 1000 }, (_, id) => ({ id, found: false })), totals: { pages: 2500 } })],
  ["oversize.json", '"' + "x".repeat(1_000_001) + '"'],
  ["notes.txt", "plain text " + "long/unbroken/".repeat(200)],
  ["events.jsonl", '{"event":"first"}\n{"event":"' + "x".repeat(1000) + '"}\n'],
  ["raw-bytes.json", ' \r\n{ "message": "é😀", "literal": "<img src=x onerror=alert(1)>", "items": [1,2] }\t\r\n'],
  ["data.csv", "id,note\n1," + "long ".repeat(300) + "\n"],
]);

test("Files JSON reader: Paper states, responsive themes, raw fidelity, folds and reopen", async () => {
  const requests = [];
  const project = { id: "project", name: "Virvid", workspace_id: "workspace", workspace_name: "QA", member_count: 1, timezone: "UTC" };
  const server = http.createServer(async (request, response) => {
    const url = new URL(request.url, "http://localhost");
    const send = (value, type = "application/json") => {
      response.setHeader("Content-Type", type);
      const body = type === "application/json" && !Buffer.isBuffer(value) ? JSON.stringify(value) : value;
      response.setHeader("Content-Length", Buffer.byteLength(body));
      response.end(body);
    };
    if (url.pathname.startsWith("/assets/")) {
      const file = path.resolve(assets, url.pathname.slice(8));
      if (!file.startsWith(`${assets}/`)) return response.writeHead(404).end();
      try { send(await fs.readFile(file), file.endsWith(".css") ? "text/css" : file.endsWith(".js") ? "text/javascript" : "application/octet-stream"); }
      catch { response.writeHead(404).end(); }
      return;
    }
    if (url.pathname === "/") {
      const html = (await fs.readFile(path.join(assets, "index.html"), "utf8"))
        .replace(/<script\b[^>]*src="\{\{CLERK[^>]+>[\s\S]*?<\/script>/g, "").replaceAll("{{ASSET_VERSION}}", "test");
      return send(html, "text/html");
    }
    if (url.pathname.startsWith("/api/")) requests.push({ method: request.method, url: url.pathname + url.search });
    if (url.pathname === "/api/projects") return send([project]);
    if (url.pathname.endsWith("/system")) return send({ waiting_count: 0, running_count: 0, workflow_count: 0 });
    if (url.pathname.endsWith("/files/raw")) {
      assert.equal(url.searchParams.get("revision"), revision);
      const filename = url.searchParams.get("path");
      if (!fixtures.has(filename)) return response.writeHead(404).end();
      return send(Buffer.from(fixtures.get(filename)), filename.endsWith(".json") ? "application/json"
        : filename.endsWith(".csv") ? "text/csv" : "application/octet-stream");
    }
    if (url.pathname.endsWith("/files")) return send({ revision, files: [...fixtures.keys()].map((name) => ({ path: name })) });
    if (url.pathname.startsWith("/api/")) return send([]);
    response.writeHead(404).end();
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({ headless: true });
  const screenshotDir = process.env.TIN_JSON_SCREENSHOTS_DIR;
  if (screenshotDir) await fs.mkdir(screenshotDir, { recursive: true });
  try {
    for (const theme of ["light", "dark"]) {
      const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, permissions: ["clipboard-read", "clipboard-write"] });
      await context.route("**/*", (route) => route.request().url().startsWith(base) ? route.continue() : route.abort());
      await context.addInitScript((value) => {
        window.Clerk = { load: async () => {}, isSignedIn: true, user: { id: "member", firstName: "QA" }, session: { getToken: async () => "synthetic-test-only" } };
        localStorage.setItem("tin-lite:theme", value);
      }, theme);
      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await page.goto(`${base}/#files`);
      await page.locator(".files-view").waitFor();
      async function open(filename) {
        await page.evaluate(({ filename, revision }) => {
          goToRoute(`file?${new URLSearchParams({ path: filename, revision })}`);
        }, { filename, revision });
        await page.waitForFunction((name) => document.querySelector(".project-file-path")?.textContent === name, filename);
      }
      async function noOverflow(label) {
        const overflow = await page.evaluate(() => [...document.querySelectorAll("html, body, main, .project-file-view, .project-file-context, .project-file-text, .project-file-text pre, .project-json-row")]
          .filter((node) => node.scrollWidth > node.clientWidth + 1)
          .map((node) => ({ node: node.className || node.tagName, width: node.clientWidth, scroll: node.scrollWidth })));
        assert.deepEqual(overflow, [], `${theme}: ${label}`);
      }
      async function screenshot(name, width) {
        if (screenshotDir) await page.screenshot({ path: path.join(screenshotDir, `${theme}-${width}-${name}.png`) });
      }
      for (const width of [1440, 768, 390]) {
        await page.setViewportSize({ width, height: 1000 });
        await open(planPath);
        await noOverflow(`formatted ${width}`);
        const style = await page.locator(".project-json-tree").evaluate((node) => {
          const style = getComputedStyle(node);
          return { fontSize: style.fontSize, lineHeight: style.lineHeight, color: style.color, border: style.borderTopColor, background: style.backgroundColor, width: node.clientWidth };
        });
        assert.equal(style.fontSize, width === 390 ? "11.5px" : "12.5px");
        assert.equal(style.lineHeight, width === 390 ? "18px" : "20px");
        assert.equal(style.background, theme === "dark" ? "rgb(27, 25, 23)" : "rgb(253, 252, 248)");
        assert.equal(style.border, theme === "dark" ? "rgba(246, 241, 231, 0.08)" : "rgba(38, 35, 26, 0.14)");
        assert.ok(style.width <= 760);
        await screenshot("formatted", width);
        await page.getByRole("button", { name: "view raw", exact: true }).click();
        assert.equal(await page.locator(".project-file-text pre").textContent(), plan);
        await noOverflow(`raw ${width}`);
        await screenshot("raw", width);
        await page.getByRole("button", { name: "view formatted", exact: true }).click();
        await open("ten-kb.json");
        await noOverflow(`10 kb long value ${width}`);
        await page.getByRole("button", { name: "view raw", exact: true }).click();
        await noOverflow(`10 kb raw ${width}`);
        for (const [filename, name] of [["invalid.json", "invalid"], ["audit.json", "large"], ["oversize.json", "cap"], ["notes.txt", "text"], ["events.jsonl", "jsonl"]]) {
          await open(filename);
          await noOverflow(`${name} ${width}`);
          if (filename === "invalid.json") {
            assert.match(await page.locator(".project-file-facts").textContent(), /not valid JSON, shown as text/);
            assert.equal(await page.locator(".project-file-mode-toggle").count(), 0);
          }
          if (filename === "audit.json") {
            assert.ok(await page.locator(".project-json-row").count() < 400);
            assert.match(await page.locator(".project-file-facts").textContent(), /folded/);
          }
          if (filename === "oversize.json") {
            assert.equal(await page.locator(".project-file-mode-toggle, .project-json-copy, .project-json-tree").count(), 0);
            assert.match(await page.locator(".project-file-facts").textContent(), /977 kb · too large to preview/);
            assert.ok(await page.getByRole("button", { name: "Download raw", exact: true }).isVisible());
          }
          if (filename === "events.jsonl") {
            assert.equal(await page.locator(".project-file-text pre").textContent(), fixtures.get(filename));
            assert.equal(await page.locator(".project-file-mode-toggle").count(), 0);
          }
          await screenshot(name, width);
        }
      }
      await page.setViewportSize({ width: 1440, height: 1000 });
      await open("audit.json");
      await page.getByRole("button", { name: "Expand pages", exact: true }).focus();
      await page.keyboard.press("Enter");
      assert.ok(await page.locator(".project-json-row").count() > 10_000);
      assert.equal(await page.getByRole("button", { name: "Expand findings", exact: true }).getAttribute("aria-expanded"), "false");
      assert.equal(await page.evaluate(() => document.activeElement?.getAttribute("aria-label")), "Collapse pages");
      await page.keyboard.press("Space");
      assert.ok(await page.locator(".project-json-row").count() < 400);
      await open("raw-bytes.json");
      for (const mode of ["formatted", "raw"]) {
        if (mode === "raw") await page.getByRole("button", { name: "view raw", exact: true }).click();
        await page.getByRole("button", { name: "Copy", exact: true }).click();
        await page.waitForFunction(() => document.querySelector(".toast")?.textContent === "Raw file copied.");
        assert.equal(await page.evaluate(() => navigator.clipboard.readText()), fixtures.get("raw-bytes.json"));
        const downloaded = page.waitForEvent("download");
        await page.getByRole("button", { name: "Download raw", exact: true }).click();
        const download = await downloaded;
        assert.equal(download.suggestedFilename(), "raw-bytes.json");
        assert.equal(await fs.readFile(await download.path(), "utf8"), fixtures.get("raw-bytes.json"));
      }
      await page.getByRole("button", { name: "← files", exact: true }).click();
      await page.locator(".files-view").waitFor();
      await open("raw-bytes.json");
      assert.ok(await page.getByRole("button", { name: "view raw", exact: true }).isVisible());
      await open("audit.json");
      assert.ok(await page.getByRole("button", { name: "Expand pages", exact: true }).isVisible());
      await open("data.csv");
      assert.ok(await page.locator(".project-delimited-table").isVisible());
      await page.getByRole("button", { name: "view raw", exact: true }).click();
      await noOverflow("CSV raw fallback");
      assert.deepEqual(errors, []);
      await context.close();
    }
    assert.ok(requests.every((request) => request.method === "GET"), "The reader must have no file mutation effects");
  } finally {
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
});
