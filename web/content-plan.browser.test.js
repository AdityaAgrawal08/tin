import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";
import { chromium } from "playwright";

async function choose(page, marker, value) {
  const dropdown = page.locator(marker).locator("..");
  await dropdown.locator("[data-tin-select-trigger]").click();
  await dropdown.locator(`[data-tin-select-value="${value}"]`).click();
}

async function loadSharedControls(page) {
  const app = await fs.readFile("src/tin_lite/static/app.js", "utf8");
  const controls = app.slice(app.indexOf("function tinCounterControl("), app.indexOf("function bindWorkflowFieldValidation("));
  const escape = app.match(/^function escapeHtml\([\s\S]*?^}/m)[0];
  await page.addScriptTag({content: `${escape}\n${controls}`});
}

test("content program editor: future edits, holds, preview and both themes", async () => {
  const browser = await chromium.launch({headless: true});
  try {
    for (const theme of ["light", "dark"]) {
      const page = await browser.newPage({viewport: {width: 1200, height: 1000}});
      const errors = [];
      page.on("pageerror", error => errors.push(error.message));
      await page.route("http://localhost/content-test", route => route.fulfill({body: "<!doctype html><html><body></body></html>", contentType: "text/html"}));
      await page.goto("http://localhost/content-test");
      await page.setContent(`<html data-theme="${theme}"><body><div class="content-program-panel" data-content-program="program"></div></body></html>`);
      await page.addStyleTag({content: await fs.readFile("src/tin_lite/static/app.css", "utf8")});
      await loadSharedControls(page);
      await page.addScriptTag({path: "src/tin_lite/static/content-plan.js"});
      assert.equal(await page.evaluate(() => window.TinContentPlan.endDate("2026-08-31", "6_months")), "2027-02-28");
      await page.evaluate(async () => {
        const makeItem = id => ({id, title: id, brief: "Explain a useful buyer task.", intent: "Buyer question", action: "new_page", destination: "", source_ids: [], verification: ["Verify current page coverage"], readiness: "needs_verification"});
        window.plan = {program_id: "program", host: "example.com", start_date: "2026-09-08", end_date: "2026-09-22", strategy: "Useful evidence",
          batches: [{id: "week_01", due_date: "2026-09-08", items: [makeItem("prepared")]}, {id: "week_02", due_date: "2026-09-15", items: [makeItem("future")]}]};
        window.pending = null; window.writes = []; window.opened = [];
        window.read = () => ({revision: "a".repeat(40), plan: structuredClone(window.plan)});
        window.api = async (path, options) => {
          if (options?.method) {
            const payload = JSON.parse(options.body); window.writes.push({path, payload});
            if (path.endsWith("/plan")) window.plan = payload.plan;
            else if (path.endsWith("/revisions")) window.pending = {id: "revision", batch_ids: ["week_02"], run_id: "run", preview_revision: "b".repeat(40)};
            else {window.pending = null; if (payload.action === "apply") window.plan.batches[1].items[0].brief = "Preview proposed brief.";}
            return {};
          }
          if (path.includes("/files/raw?")) {const plan = structuredClone(window.plan); plan.batches[1].items[0].brief = "Preview proposed brief."; return plan;}
          if (path.endsWith("/files")) return {files: [{path: "notes/product.md"}, {path: "notes/file,with,commas.md"}]};
          if (path.endsWith("/plan")) return window.read();
          return {initialized: true, plan_path: "content/plans/program/plan.json", batches: [{batch_id: "week_01", run_id: "prepared-run", item_ids: ["prepared"], status: "prepared"}], pending_revision: window.pending};
        };
        await window.TinContentPlan.mount(document.body, {api: window.api, projectId: "project", toast: () => {}, openFile: path => window.opened.push(path), openRun: id => window.opened.push(id), poll: () => {}});
      });
      await page.locator('.content-topic > summary').click();
      await page.locator('[data-item-field="title"]').fill('<img src=x onerror="alert(1)">Useful title');
      await page.locator('[data-save-plan]').click();
      await page.waitForFunction(() => window.writes.length === 1);
      assert.equal(await page.locator(".content-program-panel img").count(), 0);
      assert.equal(await page.evaluate(() => window.writes[0].payload.plan.batches[0].items[0].title), "prepared");
      await choose(page, '[data-batch-select]', "week_01");
      assert.equal(await page.locator('[data-item-field="title"]').count(), 0);
      await page.locator('[data-read-prepared]').click();
      assert.deepEqual(await page.evaluate(() => window.opened), ["prepared-run"]);
      await choose(page, '[data-batch-select]', "week_02");
      await page.locator('.content-revision > summary').click();
      await page.locator('[data-revision-instruction]').fill("Improve the short brief.");
      await choose(page, '[data-file-choice]', "notes/file,with,commas.md");
      await page.locator('[data-add-context]').click();
      await page.locator('[data-request-revision]').click();
      await page.waitForSelector('[data-view-preview]');
      assert.deepEqual(await page.evaluate(() => window.writes[1].payload.context_paths), ["notes/file,with,commas.md"]);
      assert.equal(await page.locator('[data-item-field="title"]').isDisabled(), true);
      assert.equal(await page.locator('[data-apply-preview]').isDisabled(), true);
      await page.locator('[data-view-preview]').click();
      await page.waitForSelector('.content-preview-columns');
      assert.match(await page.locator('[data-preview-summary]').innerText(), /1 edited/);
      if (process.env.TIN_CONTENT_PLAN_SCREENSHOTS) await page.screenshot({path: `${process.env.TIN_CONTENT_PLAN_SCREENSHOTS}/content-plan-${theme}.png`, fullPage: true});
      await page.locator('[data-apply-preview]').click();
      await page.waitForSelector('[data-request-revision]', {state: "attached"});
      assert.equal(await page.locator('[data-item-field="brief"]').inputValue(), "Preview proposed brief.");
      await page.setViewportSize({width: 390, height: 850});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      assert.deepEqual(errors, []);
      await page.close();
    }
  } finally { await browser.close(); }
});
