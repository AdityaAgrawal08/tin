// Packaged UI with synthetic APIs. No live credentials or projects.
// A browser sign-up whose project has no workflow yet sees the locked dashboard; a project
// with one workflow, or the setting turned off, renders System as before.
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import test from "node:test";
import { chromium } from "playwright";

const assets = path.resolve("src/tin_lite/static");

async function serve({ lockEnabled, projectWorkflows }) {
  const project = {id: "project-1", name: "QA’s project", workspace_id: "ws", workspace_name: "QA", member_count: 1, hidden: false};
  const writes = [];
  const server = http.createServer(async (request, response) => {
    const url = new URL(request.url, "http://localhost");
    const send = value => {response.setHeader("Content-Type", "application/json"); response.end(JSON.stringify(value));};
    if (["/", "/system", "/decisions"].includes(url.pathname)) {
      response.setHeader("Content-Type", "text/html");
      const html = (await fs.readFile(path.join(assets, "index.html"), "utf8"))
        .replaceAll("{{ASSET_VERSION}}", "test").replaceAll("{{CLERK_PUBLISHABLE_KEY}}", "")
        .replaceAll("{{BROWSER_LOCK_ENABLED}}", String(lockEnabled)).replaceAll("{{MCP_URL}}", "https://app.tin.test/mcp");
      return response.end(html);
    }
    if (url.pathname.startsWith("/assets/")) {
      const file = path.join(assets, url.pathname.slice(8));
      try {
        const body = await fs.readFile(file);
        response.setHeader("Content-Type", file.endsWith(".js") ? "text/javascript" : file.endsWith(".css") ? "text/css" : "application/octet-stream");
        return response.end(body);
      } catch {response.writeHead(404).end(); return;}
    }
    if (request.method !== "GET") {
      let raw = ""; for await (const chunk of request) raw += chunk;
      writes.push({path: url.pathname, body: JSON.parse(raw || "{}")});
      response.statusCode = 204; return response.end();
    }
    if (url.pathname === "/api/projects") return send([project]);
    if (url.pathname === "/api/projects/project-1/workflows") return send(projectWorkflows);
    if (url.pathname.endsWith("/system")) return send({workflow_count: projectWorkflows.length, running_count: 0, waiting_count: 0, runs_this_month: 0});
    if (url.pathname.startsWith("/api/")) return send([]);
    response.writeHead(404).end();
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  return {server, writes, base: `http://127.0.0.1:${server.address().port}`};
}

async function open(browser, base, {viewport = {width: 1440, height: 900}, url = "/system"} = {}) {
  const errors = [];
  const context = await browser.newContext({viewport});
  await context.route("**/*", route => route.request().url().startsWith(base) ? route.continue() : route.abort());
  await context.addInitScript(() => {
    window.Clerk = {load: async () => {}, isSignedIn: true, user: {id: "member", firstName: "QA"}, session: {getToken: async () => "synthetic"}};
    localStorage.setItem("tin-lite:theme", "light");
  });
  const page = await context.newPage(); page.on("pageerror", error => errors.push(error.message));
  await page.goto(base + url);
  return {page, context, errors};
}

test("lock page: no workflow yet locks the rail and sends the person to their coding agent", async () => {
  const {server, writes, base} = await serve({lockEnabled: true, projectWorkflows: []});
  const browser = await chromium.launch({headless: true});
  try {
    const {page, context, errors} = await open(browser, base, {url: "/decisions"});
    await page.locator(".lock-page").waitFor();
    assert.equal(await page.locator(".lock-page h1").textContent(), "Set up Tin from your coding agent");
    assert.equal(await page.locator(".lock-page p strong").textContent(), "Browser setup is not available yet.");
    // Every rail item is dimmed and dead; the coding-agent block is gone because the page is that block.
    assert.deepEqual(await page.locator(".nav-list .nav-item").evaluateAll(items => items.map(item => item.disabled)), [true, true, true, true, true]);
    assert.equal(await page.locator("#agent-rail").isHidden(), true);
    assert.equal(await page.locator("#project-switcher").isDisabled(), false);
    // Codex first, like the website hero; one line, no comment lines.
    assert.equal(await page.locator('[data-lock-tab][aria-selected="true"]').getAttribute("data-lock-tab"), "codex");
    assert.equal(await page.locator("#lock-page-command").textContent(), "codex mcp add tin --url https://app.tin.test/mcp");
    await page.locator('[data-lock-tab="claude"]').click();
    assert.equal(await page.locator("#lock-page-command").textContent(), "claude mcp add -t http tin https://app.tin.test/mcp");
    await page.locator('[data-lock-tab="api"]').click();
    assert.equal(await page.locator("#lock-page-command").textContent(), "https://app.tin.test/api/workflows?project_id={project_id}");
    await page.locator('[data-lock-tab="codex"]').click();
    await context.grantPermissions(["clipboard-read", "clipboard-write"], {origin: base});
    await page.locator("#copy-lock-command").click();
    assert.equal(await page.evaluate(() => navigator.clipboard.readText()), "codex mcp add tin --url https://app.tin.test/mcp");
    await page.waitForTimeout(150);
    assert.deepEqual(writes.map(item => item.body), [
      {action: "viewed", agent: null, project_id: "project-1"},
      {action: "install_copied", agent: "codex", project_id: "project-1"},
    ]);
    // Centered in the pane at desktop width.
    const box = await page.locator(".lock-page-column").boundingBox();
    const pane = await page.locator("#main").boundingBox();
    assert.ok(Math.abs((box.x + box.width / 2) - (pane.x + pane.width / 2)) < 2, "column is horizontally centered");
    assert.ok(box.y > 150 && box.y + box.height < pane.height - 150, "column sits in the middle of the pane");
    assert.deepEqual(errors, []);
    await context.close();
    // Narrow: the rail is a top strip and the page still fits without a horizontal scroll.
    const narrow = await open(browser, base, {viewport: {width: 390, height: 844}});
    await narrow.page.locator(".lock-page").waitFor();
    assert.equal(await narrow.page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    assert.deepEqual(narrow.errors, []);
    await narrow.context.close();
  } finally {
    await browser.close();
    server.close();
  }
});

test("lock page: one workflow, or the setting off, renders System as before", async () => {
  const workflow = {id: "cfg-1", workflow_id: "wf-1", name: "Audit AI visibility", status: "active", schedule: null, inputs: {}};
  const browser = await chromium.launch({headless: true});
  try {
    for (const scenario of [{lockEnabled: true, projectWorkflows: [workflow]}, {lockEnabled: false, projectWorkflows: []}]) {
      const {server, writes, base} = await serve(scenario);
      try {
        const {page, context, errors} = await open(browser, base);
        await page.locator(".system-view").waitFor();
        assert.equal(await page.locator(".lock-page").count(), 0);
        assert.equal(await page.locator("#agent-rail").isVisible(), true);
        assert.deepEqual(await page.locator(".nav-list .nav-item").evaluateAll(items => items.map(item => item.disabled)), [false, false, false, false, false]);
        assert.deepEqual(writes.filter(item => item.path === "/api/events/lock-page"), []);
        assert.deepEqual(errors, []);
        await context.close();
      } finally {
        server.close();
      }
    }
  } finally {
    await browser.close();
  }
});
