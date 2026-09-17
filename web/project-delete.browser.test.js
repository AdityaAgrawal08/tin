// Packaged UI with synthetic APIs. No live credentials, projects or supplier calls.
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import test from "node:test";
import { chromium } from "playwright";

const assets = path.resolve("src/tin_lite/static");
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

for (const theme of ["light", "dark"]) test(`project deletion: ${theme}, typed name, refusal, then removal`, async () => {
  const main = {id: "main", name: "Tin Lite", workspace_id: "tin", workspace_name: "Tin Lite", can_create_project_in_workspace: true, member_count: 2, can_delete: true};
  const personal = {...main, id: "personal", name: "QA’s project", member_count: 1, can_delete: false};
  let projects = [main, personal];
  const errors = [], deletes = [];
  let rejectDelete = true;
  const server = http.createServer(async (request, response) => {
    const url = new URL(request.url, "http://localhost");
    const send = (value, status = 200) => {response.statusCode = status; response.setHeader("Content-Type", "application/json"); response.end(JSON.stringify(value));};
    if (url.pathname === "/") {
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
    if (request.method === "DELETE" && url.pathname.startsWith("/api/projects/")) {
      deletes.push({path: url.pathname, params: Object.fromEntries(url.searchParams)});
      if (rejectDelete) return send({detail: "confirm_name does not match the project name"}, 409);
      const id = url.pathname.split("/")[3];
      projects = projects.filter(item => item.id !== id);
      return send({project_id: id, name: "Tin Lite", deleted_at: "2026-09-16T12:00:00Z", stopped_runs: 1, removed_schedules: 2, disconnected: 1, repo_deleted: true});
    }
    if (request.method !== "GET") {let raw = ""; for await (const chunk of request) raw += chunk; return send({});}
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
      localStorage.setItem("tin-lite:project:member", "main");
    }, theme);
    const page = await context.newPage(); page.on("pageerror", error => errors.push(error.message));
    const menu = page.locator("#project-menu");
    const dialog = page.locator("#project-delete-dialog");
    const confirm = dialog.locator("[data-confirm-project-delete]");
    const open = async () => {
      await page.locator("#project-switcher:not(:disabled)").waitFor();
      if (!await menu.isVisible()) await page.locator("#project-switcher").click();
    };
    await page.goto(`${base}/?project=main#workflows`);
    await open();
    assert.equal(await menu.locator(".project-menu-item").count(), 2);
    assert.equal(await menu.getByRole("button", {name: "Delete project →"}).count(), 1);
    assert.doesNotMatch(await menu.innerText(), /hidden|Hide this project|Restore this project/i);

    // The personal project offers no deletion.
    await menu.locator(".project-menu-item[data-project-id='personal']").click();
    await page.getByText("Switched to QA’s project.", {exact: true}).waitFor();
    await open();
    assert.equal(await menu.getByRole("button", {name: "Delete project →"}).count(), 0);
    await menu.locator(".project-menu-item[data-project-id='main']").click();
    await page.getByText("Switched to Tin Lite.", {exact: true}).waitFor();

    await open();
    await menu.getByRole("button", {name: "Delete project →"}).click();
    await dialog.waitFor({state: "visible"});
    assert.match(await dialog.innerText(), /Deleting Tin Lite stops its running work/);
    assert.match(await dialog.innerText(), /Billing history stays\./);
    assert.equal(await dialog.locator("#project-delete-prompt").innerText(), "Type Tin Lite to confirm");
    assert.equal(await dialog.locator("#project-delete-prompt strong").innerText(), "Tin Lite");
    assert.equal(await dialog.locator("#project-delete-name").getAttribute("placeholder"), "Tin Lite");
    assert.equal(await confirm.isDisabled(), true);
    await dialog.locator("#project-delete-name").fill("Tin");
    assert.equal(await confirm.isDisabled(), true);
    await dialog.locator("#project-delete-name").fill("Tin Lite");
    assert.equal(await confirm.isDisabled(), false);
    for (const width of [1440, 390]) {
      await page.setViewportSize({width, height: 1000});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      if (process.env.TIN_PROJECT_DELETE_SCREENSHOTS) await page.screenshot({path: `${process.env.TIN_PROJECT_DELETE_SCREENSHOTS}/delete-${theme}-${width}.png`});
    }
    await page.setViewportSize({width: 1440, height: 1000});

    // A refusal keeps the dialog usable and the project in place.
    await confirm.click();
    await page.getByText("Could not delete Tin Lite: confirm_name does not match the project name", {exact: true}).waitFor();
    assert.equal(deletes.length, 1);
    assert.equal(deletes[0].path, "/api/projects/main");
    assert.equal(deletes[0].params.confirm_name, "Tin Lite");
    assert.match(deletes[0].params.request_id, UUID);
    assert.equal(await dialog.isVisible(), true);
    assert.equal(await confirm.isDisabled(), false);
    assert.equal(await confirm.innerText(), "Delete project");

    // Success: one request with the same request id, the project gone, another loaded.
    rejectDelete = false;
    await confirm.click();
    await page.getByText("Tin Lite deleted. 1 running run stopped.", {exact: true}).waitFor();
    assert.equal(deletes.length, 2);
    assert.equal(deletes[1].params.request_id, deletes[0].params.request_id);
    assert.equal(await dialog.isVisible(), false);
    assert.doesNotMatch(page.url(), /project=main/);
    assert.match(page.url(), /project=personal/);
    assert.equal(await page.evaluate(() => localStorage.getItem("tin-lite:project:member")), "personal");
    await open();
    assert.equal(await menu.locator(".project-menu-item").count(), 1);
    assert.equal(await menu.getByRole("button", {name: "Delete project →"}).count(), 0);
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
});
