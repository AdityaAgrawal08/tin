import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import test from "node:test";
import { chromium } from "playwright";

async function choose(page, name, value) {
  const dropdown = page.locator(`[name="input:${name}"]`).locator("..");
  await dropdown.locator("[data-tin-select-trigger]").click();
  await dropdown.locator(`[data-tin-select-value="${value}"]`).click();
}

test("planned draft: shared controls, hidden revisions, empty/errors, late responses and replay", async () => {
  const documentHtml = execFileSync("uv", ["run", "python", "-c", "from tin_lite.documents import render_markdown; print(render_markdown('---\\nrevision: ' + 'a' * 64 + '\\nnote: <script>bad()</script>\\n---\\n# Readable article\\n\\nUseful copy.').html)"], {encoding: "utf8"});
  const browser = await chromium.launch({headless: true});
  try {
    for (const theme of ["light", "dark"]) {
      const page = await browser.newPage({viewport: {width: 1100, height: 1000}});
      const errors = [];
      page.on("pageerror", error => errors.push(error.message));
      await page.route("http://localhost/draft-test", r => r.fulfill({body: "<!doctype html><html><body></body></html>", contentType: "text/html"}));
      await page.goto("http://localhost/draft-test");
      await page.setContent(`<html data-theme="${theme}"><body><main class="workspace"><form class="system-template-card is-open workflow-config-form"><div class="system-template-setup-body" id="fields"></div></form></main></body></html>`);
      await page.addStyleTag({content: await fs.readFile("src/tin_lite/static/app.css", "utf8")});
      const app = await fs.readFile("src/tin_lite/static/app.js", "utf8");
      const controls = app.slice(app.indexOf("function tinCounterControl("), app.indexOf("function bindWorkflowFieldValidation("));
      await page.addScriptTag({content: `${app.match(/^function escapeHtml\([\s\S]*?^}/m)[0]}\n${controls}`});
      await page.addScriptTag({path: "src/tin_lite/static/content-draft.js"});
      await page.evaluate(() => {
        window.calls = []; window.mode = "normal";
        document.querySelector("#fields").innerHTML = TinContentDraft.fields();
        window.api = async path => {
          calls.push(path);
          if (mode === "error") throw new Error("Service unavailable.");
          if (!path.includes("?")) return {programs: mode === "empty" ? [] : [{id: "program", name: "ClawMessenger roadmap"}, {id: "other", name: "Another roadmap"}]};
          if (mode === "late") return await new Promise(resolve => {window.releaseOld = resolve;});
          return {plan_revision: "a".repeat(40),
            next: {item_id: mode === "complete" ? null : "one", available: !["hold", "complete"].includes(mode), reason: mode === "hold" ? "Finish the pending revision for the next batch before drafting." : mode === "complete" ? "All non-deferred articles have drafts." : ""},
            progress: {total: 3, drafted: 0, awaiting_review: 1, drafting: 0, deferred: 1, already_covered: mode === "assessment" ? 1 : 0},
            items: [
              {id: "one", title: "Receive an agent reply", action: "new_page", brief: '<script>bad()</script> Explain the mechanism.', intent: "A useful buyer task", verification: ["Check actual capabilities"], due_date: "2026-09-11", readiness: "needs_verification", available: mode !== "hold", held: mode === "hold"},
              {id: "deferred", title: "Deferred topic", readiness: "deferred", available: false},
              ...(mode === "assessment" ? [{id: "covered", title: "Existing quickstart", action: "update_page", brief: "Improve setup", intent: "Get started", verification: ["Inspect current docs"], due_date: "2026-09-12", readiness: "needs_verification", available: false, can_rewrite: true, draft: {stage: "already_covered", has_output: false, run_id: "assessment-run", assessment: {rationale: "The docs already cover this setup. <script>bad()</script>"}}}] : []),
              {id: "done", title: "An existing article", action: "new_page", brief: "Earlier draft.", intent: "Buyer task", verification: ["Check sources"], due_date: "2026-09-18", readiness: "needs_verification", available: false, can_rewrite: mode !== "retained", brief_changed: true, draft: {stage: mode === "retained" ? "saved_result" : "awaiting_review", output_source: mode === "retained" ? "retained" : "canonical", has_output: true, run_id: "prior-run"}},
            ]};
        };
        TinContentDraft.mount(document.body, {api, projectId: "project"});
      });
      await choose(page, "program_id", "program");
      assert.equal(await page.locator('[name="input:item_id"]').inputValue(), "");
      assert.match(await page.getByRole("button", {name: "Article to draft", exact: true}).innerText(), /Next article in plan/);
      assert.match(await page.locator("[data-draft-preview]").innerText(), /Receive an agent reply/);
      assert.match(await page.locator("[data-draft-progress]").innerText(), /1 of 3 articles drafted/);
      assert.equal(await page.locator('[name="input:plan_revision"]').inputValue(), "");
      assert.equal(await page.evaluate(() => {TinContentDraft.prepare(document.querySelector("form")); return true;}), true);
      await choose(page, "item_id", "one");
      assert.equal(await page.locator('[name="input:plan_revision"]').isVisible(), false);
      assert.equal(await page.locator("[data-draft-preview] script").count(), 0);
      assert.equal(await page.locator('[data-tin-select-value="deferred"]').count(), 0);
      assert.match(await page.locator("[data-draft-preview]").innerText(), /Explain the mechanism/);
      assert.equal(await page.evaluate(() => {TinContentDraft.prepare(document.querySelector("form")); return true;}), true);
      const replay = await page.evaluate(() => {
        const form = document.querySelector("form"), input = {program_id: "program", item_id: "one"};
        const first = TinContentDraft.requestId(form, input), second = TinContentDraft.requestId(form, input);
        return {same: first === second, different: first !== TinContentDraft.requestId(form, {...input, direction: "new"})};
      });
      assert.deepEqual(replay, {same: true, different: true});
      await choose(page, "item_id", "done");
      assert.equal(await page.evaluate(() => {try {TinContentDraft.prepare(document.querySelector("form")); return false;} catch {return true;}}), true);
      assert.match(await page.locator("[data-draft-preview] a").getAttribute("href"), /\/document\/prior-run\?project=project/);
      assert.match(await page.locator("[data-draft-preview]").innerText(), /plan changed/);
      await page.getByRole("button", {name: "Write new draft", exact: true}).click();
      assert.equal(await page.locator('[name="input:rewrite"]').inputValue(), "true");
      assert.equal(await page.evaluate(() => {TinContentDraft.prepare(document.querySelector("form")); return true;}), true);
      await choose(page, "item_id", "");
      assert.equal(await page.locator('[name="input:rewrite"]').inputValue(), "false");
      assert.equal(await page.locator('[name="input:plan_revision"]').inputValue(), "");
      await choose(page, "item_id", "done");
      assert.equal(await page.locator('[name="input:rewrite"]').inputValue(), "false");
      for (const width of [1100, 390]) {
        await page.setViewportSize({width, height: 1000});
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
        if (process.env.TIN_DRAFT_SCREENSHOTS) await page.screenshot({path: `${process.env.TIN_DRAFT_SCREENSHOTS}/draft-${theme}-${width}.png`, fullPage: true});
      }
      await page.evaluate(() => {mode = "hold";});
      await choose(page, "program_id", "other");
      assert.match(await page.locator("[data-draft-message]").innerText(), /pending revision/);
      assert.equal(await page.evaluate(() => {try {TinContentDraft.prepare(document.querySelector("form")); return false;} catch {return true;}}), true);
      assert.equal(await page.evaluate(() => {TinContentDraft.prepare(document.querySelector("form"), {forRun: false}); return true;}), true);
      await page.evaluate(() => {mode = "complete";});
      await choose(page, "program_id", "program");
      assert.match(await page.locator("[data-draft-message]").innerText(), /All non-deferred/);
      assert.equal(await page.evaluate(() => {try {TinContentDraft.prepare(document.querySelector("form")); return false;} catch {return true;}}), true);
      assert.equal(await page.evaluate(() => {TinContentDraft.prepare(document.querySelector("form"), {forRun: false}); return true;}), true);
      await page.evaluate(() => {mode = "retained";});
      await choose(page, "program_id", "other");
      await choose(page, "item_id", "done");
      assert.match(await page.locator('[data-draft-preview] a').getAttribute("href"), /source=retained/);
      assert.match(await page.locator("[data-draft-message]").innerText(), /Resolve the saved result/);
      assert.equal(await page.locator("[data-draft-rewrite]").isVisible(), false);
      await page.evaluate(() => {mode = "assessment";});
      await choose(page, "program_id", "program");
      await choose(page, "item_id", "covered");
      assert.match(await page.locator("[data-draft-progress]").innerText(), /1 already covered/);
      assert.match(await page.locator("[data-draft-preview]").innerText(), /Already covered/);
      assert.equal(await page.locator("[data-draft-preview] script").count(), 0);
      assert.equal(await page.getByRole("link", {name: "Read saved draft →"}).count(), 0);
      assert.match(await page.getByRole("link", {name: "Read assessment →"}).getAttribute("href"), /assessment-run/);
      assert.equal(await page.evaluate(() => {try {TinContentDraft.prepare(document.querySelector("form")); return false;} catch {return true;}}), true);
      await page.getByRole("button", {name: "Recheck this brief", exact: true}).click();
      assert.equal(await page.evaluate(() => {TinContentDraft.prepare(document.querySelector("form")); return true;}), true);
      await choose(page, "item_id", "one");
      assert.equal(await page.locator('[name="input:rewrite"]').inputValue(), "false");
      await page.evaluate(() => {mode = "late";});
      await choose(page, "program_id", "program");
      await page.evaluate(() => {
        document.querySelector("#fields").innerHTML = TinContentDraft.fields();
        mode = "empty";
        TinContentDraft.mount(document.body, {api, projectId: "new-project"});
        releaseOld({plan_revision: "b".repeat(40), items: []});
      });
      await page.waitForFunction(() => document.querySelector("[data-draft-message]").textContent.includes("Create a content plan first"));
      assert.equal(await page.locator('[name="input:plan_revision"]').inputValue(), "");
      await page.evaluate(() => {
        document.querySelector("#fields").innerHTML = TinContentDraft.fields(); mode = "error";
        TinContentDraft.mount(document.body, {api, projectId: "project"});
      });
      await page.waitForFunction(() => document.querySelector("[data-draft-message]").textContent.includes("Service unavailable"));
      assert.equal(await page.evaluate(() => {try {TinContentDraft.prepare(document.querySelector("form")); return false;} catch {return true;}}), true);
      await page.evaluate(html => {document.body.innerHTML = `<main class="workspace"><article class="markdown-document">${html}</article></main>`;}, documentHtml);
      assert.equal(await page.locator(".md-document-metadata pre").isVisible(), false);
      assert.equal(await page.locator(".markdown-document h1").innerText(), "Readable article");
      assert.equal(await page.locator(".markdown-document").evaluate(article => article.lastElementChild.matches(".md-document-metadata")), true);
      const metadataToggle = page.locator(".md-document-metadata summary");
      const closedDisclosure = await metadataToggle.evaluate(summary => {
        const style = getComputedStyle(summary), arrow = getComputedStyle(summary, "::before");
        return {display: style.display, gap: style.columnGap, marker: style.listStyleType, line: arrow.borderRightWidth, transform: arrow.transform};
      });
      assert.equal(closedDisclosure.display, "inline-flex");
      assert.equal(closedDisclosure.gap, "8px");
      assert.equal(closedDisclosure.marker, "none");
      assert.notEqual(closedDisclosure.line, "0px");
      if (process.env.TIN_DRAFT_SCREENSHOTS) await page.screenshot({path: `${process.env.TIN_DRAFT_SCREENSHOTS}/metadata-collapsed-${theme}-390.png`, fullPage: true});
      await metadataToggle.focus();
      await page.keyboard.press("Enter");
      assert.equal(await page.locator(".md-document-metadata pre").isVisible(), true);
      assert.notEqual(await metadataToggle.evaluate(summary => getComputedStyle(summary, "::before").transform), closedDisclosure.transform);
      await page.keyboard.press("Space");
      assert.equal(await page.locator(".md-document-metadata pre").isVisible(), false);
      await page.locator(".md-document-metadata summary").click();
      assert.equal(await page.locator(".md-document-metadata pre").isVisible(), true);
      assert.equal(await page.locator(".md-document-metadata script").count(), 0);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      if (process.env.TIN_DRAFT_SCREENSHOTS) await page.screenshot({path: `${process.env.TIN_DRAFT_SCREENSHOTS}/metadata-${theme}-390.png`, fullPage: true});
      await page.addScriptTag({path: "src/tin_lite/static/markdown-viewer.js"});
      await page.evaluate(() => {
        TinMarkdownViewer.mount(document.querySelector("main"), {
          filename: "article.md", html: "<h1>Clean public article</h1><p>Only useful reader-facing copy.</p>",
          word_count: 8, reading_minutes: 1, headings: [],
          related_documents: [{label: "Generation notes", url: "/?project=project#file?path=article.generation.md&revision=" + "a".repeat(40)},
                              {label: "Unsafe link", url: "javascript:alert(1)"}],
        }, {mode: "in-app", primaryAction: {label: "Approve draft", onActivate: () => {}}});
      });
      assert.equal(await page.getByRole("link", {name: "Generation notes"}).count(), 1);
      assert.equal(await page.getByRole("link", {name: "Generation notes"}).evaluate(link => getComputedStyle(link).backgroundColor), "rgba(0, 0, 0, 0)");
      assert.equal(await page.getByRole("link", {name: "Unsafe link"}).count(), 0);
      assert.equal(await page.getByRole("button", {name: "Approve draft"}).count(), 1);
      assert.doesNotMatch(await page.locator(".markdown-document").innerText(), /Generation notes|Verification notes/);
      for (const width of [1100, 390]) {
        await page.setViewportSize({width, height: 1000});
        await page.evaluate(() => window.scrollTo(0, 0));
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
        if (process.env.TIN_DRAFT_SCREENSHOTS) await page.screenshot({path: `${process.env.TIN_DRAFT_SCREENSHOTS}/clean-article-${theme}-${width}.png`, fullPage: true});
      }
      assert.deepEqual(errors, []);
      await page.close();
    }
  } finally {await browser.close();}
});
