// Real Chromium, packaged setup UI, synthetic authentication and API responses.
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import test from "node:test";
import { chromium } from "playwright";

const shots = process.env.TIN_CONNECTION_SCREENSHOTS;
// Headless Chromium hides scrollbars by default; keep them so the always-visible case is what gets checked and captured.
const launch = () => chromium.launch({ headless: true, ignoreDefaultArgs: ["--hide-scrollbars"] });

for (const theme of ["light", "dark"]) test(`secure project API setup: selected import, replacement, ${theme}`, async () => {
  const browser = await launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1100, height: 1100 } });
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.route("http://localhost/connections-test", route => route.fulfill({ body: "<!doctype html><html><body></body></html>", contentType: "text/html" }));
    await page.goto("http://localhost/connections-test");
    await page.evaluate(theme => { document.documentElement.dataset.theme = theme; }, theme);
    await page.addStyleTag({ content: await fs.readFile("src/tin_lite/static/app.css", "utf8") });
    await page.addScriptTag({ path: "src/tin_lite/static/project-connections.js" });
    await page.evaluate(async () => {
      window.writes = []; window.done = false;
      await TinProjectConnections.open({ projectId: "project-1", done: async () => { window.done = true; }, api: async (path, options) => {
        if (!options) return [{ name: "CRM_KEY", revision: "old-revision" }];
        window.writes.push({ path, body: JSON.parse(options.body) });
        return path.endsWith("/secrets") ? [{ name: "CRM_KEY", revision: "new-revision" }] : { status: "saved" };
      } });
    });
    assert.equal(await page.evaluate(() => document.activeElement.name), "name");
    await page.locator('[name="name"]').fill("crm");
    await page.locator('[name="origin"]').fill("https://api.example.com");
    await page.locator('[name="secret_name"]').fill("CRM_KEY");
    await page.locator('[name="env_file"]').setInputFiles({ name: ".env", mimeType: "text/plain", buffer: Buffer.from('CRM_KEY="literal-$(never-execute)"\nUNSELECTED=must-not-upload\n') });
    await page.locator('[data-import-index="0"]').waitFor();
    assert.equal(await page.locator('[data-import-index="0"]').isChecked(), false);
    assert.equal(await page.locator('[data-import-index="1"]').isChecked(), false);
    assert.doesNotMatch(await page.locator("body").innerText(), /must-not-upload|literal-\$\(/);
    await page.locator('[data-import-index="0"]').check();
    await page.locator('[type="submit"]').click();
    assert.match(await page.locator("[data-error]").innerText(), /Confirm.*replacements/);
    assert.equal(await page.evaluate(() => writes.length), 0);
    // Short viewport: the form is the only scroller, the actions and status stay in reach, nothing scrolls sideways.
    await page.setViewportSize({ width: 1100, height: 520 });
    const short = await page.evaluate(() => {
      const dialog = document.querySelector("dialog");
      const form = dialog.querySelector("form");
      const scrollers = [dialog, ...dialog.querySelectorAll("*")].filter(el => el.scrollHeight > el.clientHeight && /auto|scroll/.test(getComputedStyle(el).overflowY));
      const within = el => { const rect = el.getBoundingClientRect(); return rect.top >= 0 && rect.bottom <= innerHeight; };
      return {
        scrollers: scrollers.map(el => el.tagName), gutter: form.offsetWidth - form.clientWidth,
        horizontal: form.scrollWidth <= form.clientWidth && document.documentElement.scrollWidth <= innerWidth,
        reachable: within(form.querySelector('[type="submit"]')) && within(form.querySelector("[data-error]")),
        fits: dialog.getBoundingClientRect().height <= innerHeight - 48,
      };
    });
    assert.deepEqual(short.scrollers, ["FORM"]);
    assert.equal(short.gutter > 0 && short.gutter <= 8, true, `slim scrollbar, got ${short.gutter}px`);
    assert.equal(short.horizontal, true);
    assert.equal(short.reachable && short.fits, true);
    // Keyboard focus scrolls a field clear of the sticky footer instead of underneath it.
    await page.locator('[name="idempotency"]').focus();
    assert.equal(await page.evaluate(() => {
      const field = document.activeElement.getBoundingClientRect(), footer = document.querySelector(".custom-api-footer").getBoundingClientRect();
      return document.activeElement.name === "idempotency" && field.bottom <= footer.top;
    }), true);
    if (shots) await page.screenshot({ path: `${shots}/connections-${theme}-short.png` });
    await page.setViewportSize({ width: 1100, height: 1100 });
    for (const width of [1100, 390]) {
      await page.setViewportSize({ width, height: 1100 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      if (shots) await page.screenshot({ path: `${shots}/connections-${theme}-${width}.png`, fullPage: true });
    }
    await page.locator('[name="replace"]').check();
    await page.locator('[type="submit"]').click();
    await page.waitForFunction(() => window.done);
    const writes = await page.evaluate(() => window.writes);
    assert.equal(writes.length, 2);
    assert.deepEqual(writes[0].body.entries, [{ name: "CRM_KEY", value: "literal-$(never-execute)", expected_revision: "old-revision" }]);
    assert.equal(writes[1].body.configuration.secret_name, "CRM_KEY");
    assert.doesNotMatch(JSON.stringify(writes), /must-not-upload/);
    await page.locator("dialog").waitFor({ state: "detached" });
    assert.deepEqual(await page.evaluate(() => [localStorage.length, sessionStorage.length]), [0, 0]);
    assert.deepEqual(errors, []);
    const parsed = await page.evaluate(() => TinProjectConnections.parseEnv("export TEST='${DO_NOT_EVALUATE}' # literal\nOTHER=plain # comment"));
    assert.deepEqual(parsed, [{ name: "TEST", value: "${DO_NOT_EVALUATE}" }, { name: "OTHER", value: "plain" }]);
    for (const text of ["BAD=one\nBAD=two", "lower=bad", "BAD='unclosed", "BAD=\u0000"]) {
      assert.equal(await page.evaluate(text => { try { TinProjectConnections.parseEnv(text); return false; } catch { return true; } }, text), true);
    }
  } finally { await browser.close(); }
});

// The packaged Integrations page: header centerline, the Custom API row as entry point, focus and Escape.
for (const theme of ["light", "dark"]) test(`integrations header and Custom API row: ${theme}`, async () => {
  const assets = path.resolve("src/tin_lite/static");
  const project = { id: "main", name: "Tin Lite", workspace_id: "tin", workspace_name: "Tin Lite", can_create_project_in_workspace: true, member_count: 2, hidden: false };
  const integrations = [
    { key: "custom.api.crm", name: "Crm", badge: "API", description: "Project API connection. Credentials stay in Tin.", unlocks: ["Private code workflows"], connection_id: "c1", status: "connected", configured: true, external_account_label: "api.example.com", last_checked_at: null,
      configuration: { origin: "https://api.example.com", auth: "header", header: "X-API-Key", secret_name: "CRM_KEY", methods: ["GET", "POST"], idempotency_header: null, access_verified: false, revision: "r1" } },
    { key: "infra.github", name: "GitHub", badge: "GH", description: "Repositories and pull requests", unlocks: ["code.review"], connection_id: "c2", status: "connected", configured: true, external_account_label: "tin", last_checked_at: "2026-09-13T10:00:00Z", configuration: { selected_repository: "tin/app" } },
    { key: "analytics.gsc", name: "Search Console", badge: "SC", description: "Search performance", unlocks: ["seo.keyword-research"], connection_id: null, status: "available", configured: true },
  ];
  const errors = [];
  const server = http.createServer(async (request, response) => {
    const url = new URL(request.url, "http://localhost");
    const send = value => { response.setHeader("Content-Type", "application/json"); response.end(JSON.stringify(value)); };
    if (url.pathname === "/") {
      response.setHeader("Content-Type", "text/html");
      return response.end((await fs.readFile(path.join(assets, "index.html"), "utf8")).replaceAll("{{ASSET_VERSION}}", "test").replaceAll("{{CLERK_PUBLISHABLE_KEY}}", "").replaceAll("{{BILLING_ENABLED}}", "false"));
    }
    if (url.pathname.startsWith("/assets/")) {
      try {
        const file = path.join(assets, url.pathname.slice(8));
        const body = await fs.readFile(file);
        response.setHeader("Content-Type", file.endsWith(".js") ? "text/javascript" : file.endsWith(".css") ? "text/css" : file.endsWith(".woff2") ? "font/woff2" : "application/octet-stream");
        return response.end(body);
      } catch { response.writeHead(404).end(); return; }
    }
    if (request.method !== "GET") { for await (const _chunk of request) { /* drain */ } return send({}); }
    if (url.pathname === "/api/projects") return send([project]);
    if (url.pathname.endsWith("/system")) return send({ workflow_count: 0, running_count: 0, waiting_count: 0, runs_this_month: 0 });
    if (url.pathname.endsWith("/integrations")) return send(integrations);
    if (url.pathname.endsWith("/connections/secrets")) return send([{ name: "CRM_KEY", revision: "old" }]);
    if (url.pathname.startsWith("/api/")) return send([]);
    response.writeHead(404).end();
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  const browser = await launch();
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    await context.route("**/*", route => route.request().url().startsWith(base) ? route.continue() : route.abort());
    await context.addInitScript(value => {
      window.Clerk = { load: async () => {}, isSignedIn: true, user: { id: "member", firstName: "QA" }, session: { getToken: async () => "synthetic" } };
      localStorage.setItem("tin-lite:theme", value);
    }, theme);
    const page = await context.newPage();
    page.on("pageerror", error => errors.push(error.message));
    await page.goto(`${base}/#integrations`);
    const header = page.locator(".integrations-view .workspace-header");
    await header.waitFor();
    await page.evaluate(() => document.fonts.ready);
    const connect = page.locator('[data-integration-connect="custom.api"]');
    const dialog = page.locator("dialog.custom-api-dialog");
    const shot = async name => { if (shots) await page.screenshot({ path: `${shots}/${name}-${theme}.png` }); };

    // The header is the title and the search field on one centerline, box and optical (cap height).
    assert.equal(await header.locator("button, [data-custom-api]").count(), 0);
    const line = await page.evaluate(() => {
      const view = document.querySelector(".integrations-view .workspace-header");
      const canvas = document.createElement("canvas").getContext("2d");
      const measure = el => {
        const style = getComputedStyle(el), rect = el.getBoundingClientRect();
        canvas.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
        const glyph = canvas.measureText("H");
        const box = rect.top + rect.height / 2;
        return { box, cap: box + (glyph.fontBoundingBoxAscent - glyph.fontBoundingBoxDescent) / 2 - glyph.actualBoundingBoxAscent / 2 };
      };
      return { title: measure(view.querySelector("h1")), search: measure(view.querySelector(".search-field input")) };
    });
    assert.equal(Math.abs(line.title.box - line.search.box) <= 0.5, true, JSON.stringify(line));
    assert.equal(Math.abs(line.title.cap - line.search.cap) <= 1.5, true, JSON.stringify(line));

    // Custom API is the last available row and counts like one; saved connections are ordinary rows above it.
    const cards = page.locator(".integration-card");
    assert.equal(await cards.count(), 4);
    assert.match(await cards.last().innerText(), /Custom API[\s\S]*custom\.api[\s\S]*would unlock private code workflows[\s\S]*Connect/);
    assert.match(await cards.first().innerText(), /Crm[\s\S]*custom\.api\.crm[\s\S]*api\.example\.com[\s\S]*saved · not verified[\s\S]*Configure/);
    assert.match(await page.locator(".integration-filters").innerText(), /All 4[\s\S]*Available 2/);
    await page.locator('[data-integration-filter="available"]').click();
    assert.equal(await cards.count(), 2);
    assert.equal(await connect.count(), 1);
    await page.locator('[data-integration-filter="all"]').click();
    await page.locator("#integration-search").fill("custom");
    assert.equal(await cards.count(), 2);
    await page.locator("#integration-search").fill("");
    await shot("integrations-1440");

    // Connect opens the form with focus in the first field; Escape closes, clears, and returns focus to the row.
    await connect.click();
    await dialog.waitFor();
    assert.equal(await page.evaluate(() => document.activeElement.name), "name");
    assert.equal(await dialog.evaluate(el => document.getElementById(el.getAttribute("aria-labelledby")).textContent), "Custom API");
    await page.locator('[name="secret"]').fill("dummy-secret-value");
    await shot("custom-api-1440x900");
    await page.setViewportSize({ width: 1440, height: 560 });
    assert.deepEqual(await dialog.evaluate(el => {
      const form = el.querySelector("form");
      return [form.scrollHeight > form.clientHeight, form.offsetWidth - form.clientWidth <= 8, el.getBoundingClientRect().height <= innerHeight - 48];
    }), [true, true, true]);
    await dialog.locator("form").evaluate(form => { form.scrollTop = 240; });
    await shot("custom-api-1440x560");
    await page.setViewportSize({ width: 390, height: 700 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await shot("custom-api-390x700");
    await page.keyboard.press("Escape");
    await dialog.waitFor({ state: "detached" });
    assert.equal(await page.evaluate(() => document.activeElement.dataset.integrationConnect), "custom.api");
    assert.equal(await page.evaluate(() => [...Object.entries(localStorage), ...Object.entries(sessionStorage)].some(pair => /dummy-secret-value/.test(pair.join()))), false);

    // Mobile: the search wraps under the title, nothing scrolls sideways, the row is still the entry point.
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => {
      const title = document.querySelector(".integrations-view h1").getBoundingClientRect(), search = document.querySelector(".integrations-view .search-field").getBoundingClientRect();
      return search.top >= title.bottom && document.documentElement.scrollWidth <= innerWidth;
    }), true);
    assert.equal(await connect.count(), 1);
    await shot("integrations-390");

    // Configure on a saved connection edits it: locked name, header auth visible, disconnect available.
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.locator('[data-integration-expand="custom.api.crm"]').click();
    await dialog.waitFor();
    assert.deepEqual(await dialog.evaluate(el => [el.querySelector('[name="name"]').value, el.querySelector('[name="name"]').readOnly, el.querySelector('[name="auth"]').value, el.querySelector("[data-header]").hidden, el.querySelector('[name="header"]').value, el.querySelector('[name="method"][value="POST"]').checked, el.querySelectorAll("[data-disconnect]").length]), ["crm", true, "header", false, "X-API-Key", true, 1]);
    assert.equal(await page.evaluate(() => document.activeElement.name), "origin");
    await shot("custom-api-edit-1440x900");
    await page.keyboard.press("Escape");
    await dialog.waitFor({ state: "detached" });
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
});
