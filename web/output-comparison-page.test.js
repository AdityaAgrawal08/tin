import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import vm from "node:vm";
import { parseHTML } from "linkedom";
import * as renderer from "./output-comparison.js";

const source = fs.readFileSync(new URL("../src/tin_lite/static/output-comparison-page.js", import.meta.url), "utf8");
const RUN = "11111111-1111-4111-8111-111111111111";
const REQUEST = "22222222-2222-4222-8222-222222222222";
const comparison = () => ({ run_id: RUN, project_id: "project", path: "report.md", media_type: "text/markdown", complete: true, identical: false,
  allowed_actions: ["keep_current", "use_saved"], resolution: null,
  current: { presence: "file", revision: "b".repeat(40), content: "Current\n" },
  saved: { revision: "c".repeat(40), content: "Saved\n" },
  starting: { available: true, content: "Original\n" } });
const flush = async () => { for (let i = 0; i < 8; i += 1) await new Promise(setImmediate); };

async function page({ compare = comparison(), handler, storage = new Map(), session = {} } = {}) {
  const { document, window } = parseHTML('<main id="main"></main>');
  const calls = [];
  vm.runInNewContext(source, { window, localStorage: {
    getItem: (key) => storage.get(key), setItem: (key, value) => storage.set(key, value), removeItem: (key) => storage.delete(key),
  }, crypto: { randomUUID: () => REQUEST } });
  const root = document.getElementById("main");
  const controller = window.TinOutputComparisonPage.mount(root, {
    runId: RUN, projectId: "project", actorId: "member", session,
    async api(path, options) {
      calls.push({ path, options });
      if (handler) { const result = await handler(path, options); if (result !== undefined) return result; }
      if (path.endsWith("output-comparison")) return structuredClone(compare);
      return { project_id: "project", path: "report.md", resolution: null, retry_request: null };
    },
    loadRenderer: async () => renderer,
    onRead() {}, onReturn() {}, onOutcome() {}, onFiles() {}, onActivity() {},
  });
  await flush();
  return { root, calls, controller, window, storage, async click(action) {
    root.querySelector(`[data-compare-action="${action}"]`).dispatchEvent(new window.Event("click", { bubbles: true }));
    await flush();
  } };
}

test("ready defaults to keep; choosing saved changes copy; one confirm sends exact pinned revisions", async () => {
  const result = await page({ handler: (path, options) => options?.method === "POST"
    ? { state: "applied", changed: true, revision: "d".repeat(40) } : undefined });
  assert(result.root.querySelector('input[value="keep_current"]').hasAttribute("checked"));
  const radio = result.root.querySelector('input[value="use_saved"]');
  radio.dispatchEvent(new result.window.Event("change", { bubbles: true }));
  assert.match(result.root.textContent, /replaces the whole file/);
  await result.click("confirm");
  const writes = result.calls.filter((call) => call.options?.method === "POST");
  assert.equal(writes.length, 1);
  assert.deepEqual(JSON.parse(writes[0].options.body), { request_id: REQUEST, action: "use_saved", expected_revision: "b".repeat(40), saved_revision: "c".repeat(40) });
  assert.match(result.root.textContent, /may have changed again/);
  assert.equal(result.root.querySelector(".compare-diff"), null);
  assert.equal(result.storage.size, 0);
});

test("lost response and refresh recover the identical request, never a new choice", async () => {
  const storage = new Map();
  const first = await page({ storage, handler: (path, options) => {
    if (options?.method === "POST") throw new Error("Connection lost");
  } });
  await first.click("confirm");
  const original = first.calls.find((call) => call.options?.method === "POST").options.body;
  assert.match(first.root.textContent, /hasn't confirmed/);
  first.controller.destroy();
  const second = await page({ storage, handler: (path, options) => options?.method === "POST" ? { state: "kept", changed: false, revision: "b".repeat(40) } : undefined });
  assert(!second.calls.some((call) => call.path.endsWith("output-comparison")));
  await second.click("check");
  assert.equal(second.calls.find((call) => call.options?.method === "POST").options.body, original);
  assert.match(second.root.textContent, /current file was kept/);
});

test("another caller sees a pending decision but cannot generate a replacement request", async () => {
  const result = await page({ handler: (path) => path.endsWith("output-resolution")
    ? { project_id: "project", resolution: { state: "applying", request_id: REQUEST }, retry_request: null } : undefined });
  assert.match(result.root.textContent, /original caller/);
  await result.click("check");
  assert.equal(result.calls.filter((call) => call.options?.method === "POST").length, 0);
  assert(result.root.querySelector('[data-compare-action="confirm"]').hasAttribute("disabled"));
});

test("reopened applied decision is a Postgres receipt, not today's diff mislabelled as history", async () => {
  const result = await page({ handler: (path) => path.endsWith("output-resolution")
    ? { project_id: "project", path: "report.md", resolution: { state: "applied", revision: "d".repeat(40), changed: true } } : undefined });
  assert.equal(result.calls.length, 1);
  assert.match(result.root.textContent, /ddddddd/);
  assert.equal(result.root.querySelector(".compare-diff"), null);
  assert.doesNotMatch(result.root.textContent, /comparison above is what was applied/);
});

test("oversized/unsafe comparisons still allow keep, never use saved or a partial diff", async () => {
  for (const reason of ["comparison_limit", "unsafe_destination", "non_text_destination"]) {
    const compare = comparison();
    Object.assign(compare, { complete: false, blocked_reason: reason, allowed_actions: ["keep_current"] });
    compare.current.content = compare.saved.content = null;
    const result = await page({ compare });
    assert.equal(result.root.querySelector(".compare-diff"), null);
    assert(result.root.querySelector('input[value="use_saved"]').hasAttribute("disabled"));
    assert(!result.root.querySelector('[data-compare-action="confirm"]').hasAttribute("disabled"));
  }
});

test("identical waits for acknowledgment; stale comparison clears the request and requires refresh", async () => {
  const compare = comparison(); compare.identical = true; compare.saved.content = compare.current.content;
  const identical = await page({ compare });
  assert.match(identical.root.textContent, /Acknowledge/);
  assert.equal(identical.calls.filter((call) => call.options).length, 0);
  const stale = await page({ handler: (path, options) => {
    if (options?.method === "POST") throw Object.assign(new Error("Changed"), { code: "stale_comparison", status: 409 });
  } });
  await stale.click("confirm");
  assert.match(stale.root.textContent, /project changed/);
  assert.equal(stale.storage.size, 0);
  assert(stale.root.querySelector('[data-compare-action="confirm"]').hasAttribute("disabled"));
  await stale.click("refresh");
  assert(!stale.root.querySelector('[data-compare-action="confirm"]').hasAttribute("disabled"));
});

test("leaving while a response is pending never renders into the next project", async () => {
  let finish;
  const result = await page({ handler: (path, options) => options?.method === "POST" ? new Promise((resolve) => { finish = resolve; }) : undefined });
  await result.click("confirm");
  result.controller.destroy();
  result.root.innerHTML = "Other project";
  finish({ state: "kept", changed: false });
  await flush();
  assert.equal(result.root.textContent, "Other project");
});
