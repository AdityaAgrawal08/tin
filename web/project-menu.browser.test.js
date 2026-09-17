// Packaged UI with synthetic APIs. No live credentials, projects or supplier calls.
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import test from "node:test";
import { chromium } from "playwright";

const assets = path.resolve("src/tin_lite/static");
for (const theme of ["light", "dark"]) test(`project menu: ${theme}, no hiding controls, creation scope and mobile`, async () => {
  const main = {id: "main", name: "Tin Lite", workspace_id: "tin", workspace_name: "Tin Lite", can_create_project_in_workspace: true, member_count: 2, hidden: false};
  const acceptance = {...main, id: "acceptance", name: "Publication acceptance 2026-09-06", member_count: 1, hidden: true};
  const billing = {...main, id: "billing", name: "Billing test", workspace_id: "billing-workspace", workspace_name: "Billing test workspace", member_count: 1, hidden: true};
  const projects = [main], errors = [], writes = [];
  let rejectPreference = false;
  const server = http.createServer(async (request, response) => {
    const url = new URL(request.url, "http://localhost");
    const send = value => {response.setHeader("Content-Type", "application/json"); response.end(JSON.stringify(value));};
    if (["/", "/system"].includes(url.pathname)) {
      response.setHeader("Content-Type", "text/html");
      return response.end((await fs.readFile(path.join(assets, "index.html"), "utf8")).replaceAll("{{ASSET_VERSION}}", "test").replaceAll("{{CLERK_PUBLISHABLE_KEY}}", ""));
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
      const body = JSON.parse(raw || "{}"); writes.push({path: url.pathname, body});
      if (url.pathname.endsWith("/list-preference")) {
        if (rejectPreference) {response.statusCode = 503; return send({detail: "Try again"});}
        const project = projects.find(item => item.id === url.pathname.split("/")[3]);
        project.hidden = body.hidden; return send({hidden: project.hidden});
      }
      return send({});
    }
    if (url.pathname === "/api/projects") return send(projects);
    if (url.pathname.endsWith("/system")) return send({workflow_count: 0, running_count: 0, waiting_count: 0, runs_this_month: 0});
    if (url.pathname.startsWith("/api/")) return send([]);
    response.writeHead(404).end();
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({headless: true});
  try {
    const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
    await context.route("**/*", route => route.request().url().startsWith(base) ? route.continue() : route.abort());
    await context.addInitScript(value => {
      window.Clerk = {load: async () => {}, isSignedIn: true, user: {id: "member", firstName: "QA"}, session: {getToken: async () => "synthetic"}};
      localStorage.setItem("tin-lite:theme", value);
      localStorage.setItem("tin-lite:project:member", "acceptance");
    }, theme);
    const page = await context.newPage(); page.on("pageerror", error => errors.push(error.message));
    const menu = page.locator("#project-menu");
    const open = async () => {
      await page.locator("#project-switcher:not(:disabled)").waitFor();
      if (!await menu.isVisible()) await page.locator("#project-switcher").click();
    };
    await page.goto(`${base}/#system`);
    await open();
    assert.match(page.url(), /project=main/); // A hidden remembered project isn't the default.
    assert.equal(await menu.locator(".project-menu-item").count(), 1);
    assert.equal(await menu.getByRole("button", {name: /^New project/}).count(), 1);
    assert.equal(await menu.locator(".project-menu-heading").count(), 0);
    for (const width of [1440, 390]) {
      await page.setViewportSize({width, height: 1000});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      if (process.env.TIN_PROJECT_MENU_SCREENSHOTS) await page.screenshot({path: `${process.env.TIN_PROJECT_MENU_SCREENSHOTS}/projects-${theme}-${width}.png`});
    }
    assert.doesNotMatch(await menu.innerText(), /hidden|Hide this project|Restore this project/i);
    assert.equal(await menu.locator(".project-menu-preferences").count(), 0);
    projects.push(acceptance, billing);
    await page.reload();
    await open();
    assert.equal(await menu.locator(".project-menu-item").count(), 3);
    assert.equal(await menu.getByRole("button", {name: /^New project/}).count(), 2);
    assert.equal(await menu.locator(".project-menu-actions").getByRole("button", {name: /^New project/}).count(), 0);
    assert.match(await menu.locator(".project-menu-heading").last().innerText(), /Workspace · Billing test workspace/);
    await menu.locator(".project-menu-group").last().getByRole("button", {name: "New project", exact: true}).click();
    assert.match(await page.locator("#project-create-dialog").innerText(), /Create it in Billing test workspace/);
    await page.locator("#project-create-dialog").evaluate(dialog => dialog.close());
    await open();
    assert.doesNotMatch(await menu.innerText(), /hidden|Hide this project|Restore this project/i);
    assert.equal(writes.some(write => /bootstrap/.test(write.path)), false);
    await page.setViewportSize({width: 1440, height: 1000});
    if (await menu.isVisible()) await page.locator("#project-switcher").click();
    await page.evaluate(() => {
      window.copiedCommands = []; window.failCopy = false;
      Object.defineProperty(navigator, "clipboard", {configurable: true, value: {writeText: async text => {
        if (window.failCopy) throw new Error("Clipboard unavailable");
        window.copiedCommands.push(text);
      }}});
    });
    await page.locator("#agent-rail-toggle").click();
    await page.getByRole("tab", {name: "Codex", exact: true}).click();
    const command = await page.locator("#agent-command").textContent();
    await page.locator("#copy-agent-command").click();
    await page.locator("#copy-agent-command").click();
    assert.deepEqual(await page.evaluate(() => window.copiedCommands), [command, command]);
    assert.match(await page.locator("#agent-command").textContent(), /Run it, then ask your coding agent/);
    await page.getByRole("tab", {name: "API", exact: true}).click();
    await page.locator("#copy-agent-command").click();
    assert.match(await page.locator("#agent-command").textContent(), /^POST /);
    await page.evaluate(() => {window.failCopy = true;});
    await page.locator("#copy-agent-command").click();
    await page.getByText("Copy did not work. Select the command and copy it from here.", {exact: true}).waitFor();
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
});
