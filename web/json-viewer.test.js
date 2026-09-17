import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";
import { parseHTML } from "linkedom";

const source = await fs.readFile(new URL("../src/tin_lite/static/json-viewer.js", import.meta.url), "utf8");
const { document } = parseHTML("<html><body><main></main></body></html>");
const context = { window: {}, document, TextDecoder, Uint8Array };
vm.runInNewContext(source, context);
const viewer = context.window.TinJsonViewer;

function mount(text) {
  const file = { text, bytes: Buffer.byteLength(text), json: viewer.parseText(text) };
  const view = viewer.createViewState(file);
  const container = document.createElement("main");
  viewer.mount(container, file, { view, contextLabel: "plan.json", sizeLabel: "10 kb",
    revisionLabel: "a1b2c3d", onReturn() {}, onCopy() {}, onDownload() {} });
  return { container, view, file };
}

test("all JSON root types render valid complete JSON, with safe escaped content", () => {
  for (const value of [null, true, false, 42, "hello\nworld", [], {}, [1, false, null, {}, []],
    { 'a"<b>': { items: ["<img src=x onerror=alert(1)>", { empty: [] }] }, last: true }]) {
    const { container, file } = mount(JSON.stringify(value));
    const lines = [...container.querySelectorAll(".project-json-text")].map((row) => row.textContent);
    assert.deepEqual(JSON.parse(lines.join("\n")), value);
    assert.equal(file.json.lines, lines.length);
    assert.equal(container.querySelector("img"), null);
    assert.equal(container.querySelectorAll(".project-json-caret").length,
      file.json.nodes.filter((node) => node.children.length).length);
  }
});

test("folds and summaries preserve siblings, punctuation, and the expanded line count", () => {
  const { container, file, view } = mount('{"first":{"id":"t-104","tasks":[1,2]},"last":7}');
  const button = [...container.querySelectorAll("button")].find((node) => node.getAttribute("aria-label") === "Collapse first");
  button.click();
  assert.match(container.querySelector(".project-json-tree").textContent, /\{ "id": "t-104" … 2 keys \},/);
  assert.match(container.querySelector(".project-json-tree").textContent, /"last": 7/);
  assert.match(container.querySelector(".project-file-facts").textContent, new RegExp(`${file.json.lines} lines · folded`));
  assert.equal(view.folded.size, 1);
  container.querySelector('[aria-label="Expand first"]').click();
  assert.equal(view.folded.size, 0);
  assert.equal(container.querySelectorAll(".project-json-row").length, file.json.lines);
});

test("400-line threshold folds arrays from the top, leaving objects open", () => {
  const atLimit = viewer.parseText(JSON.stringify(Array.from({ length: 398 }, (_, i) => i)));
  assert.equal(atLimit.lines, 400);
  assert.equal(atLimit.defaultFolded.length, 0);
  const { container, file } = mount(JSON.stringify({ site: "virvid.app",
    pages: Array.from({ length: 2500 }, (_, id) => ({ id, title: "Page" })),
    totals: { pages: 2500 }, findings: [1, 2] }));
  assert.ok(file.json.lines > 10_000);
  assert.ok(container.querySelectorAll(".project-json-row").length < 400);
  assert.equal(container.querySelector('[aria-label="Expand pages"]').getAttribute("aria-expanded"), "false");
  assert.equal(container.querySelector('[aria-label="Collapse totals"]').getAttribute("aria-expanded"), "true");
  assert.equal(container.querySelector('[aria-label="Collapse findings"]').getAttribute("aria-expanded"), "true");
});

test("raw mode and malformed JSON retain stored whitespace and reset per opening", () => {
  const text = ' \r\n{ "a": "é😀", "n": [1,2] }\t';
  const { container } = mount(text);
  const toggle = container.querySelector(".project-file-mode-toggle");
  toggle.click();
  assert.equal(container.querySelector("pre").textContent, text);
  assert.equal(toggle.textContent, "view formatted");
  toggle.click();
  assert.ok(container.querySelector(".project-json-tree"));
  assert.equal(mount(text).view.mode, "formatted");
  const bad = mount('{"a":1,}').container;
  assert.equal(bad.querySelector("pre").textContent, '{"a":1,}');
  assert.equal(bad.querySelector(".project-file-mode-toggle"), null);
  assert.match(bad.querySelector(".project-file-facts").textContent, /not valid JSON, shown as text/);
});

test("response reader preserves split UTF-8, BOMs and byte counts", async () => {
  const bytes = new TextEncoder().encode(' {"text":"😀é"}\r\n');
  const file = await viewer.readResponse(new Response(new ReadableStream({ start(controller) {
    for (const byte of bytes) controller.enqueue(Uint8Array.of(byte));
    controller.close();
  } })));
  assert.equal(file.bytes, bytes.length);
  assert.equal(file.text, ' {"text":"😀é"}\r\n');
  assert.equal(file.json.nodes[1].value, "😀é");
  const bom = await viewer.readResponse(new Response('\uFEFF{"a":1}'));
  assert.equal(bom.text, '\uFEFF{"a":1}');
  assert.ok(bom.json.error);
  const binary = await viewer.readResponse(new Response(Uint8Array.of(0xff)));
  assert.equal(binary.text, null);
});

test("size cap avoids parsing and cancels both declared and unbounded large responses", async () => {
  let cancelled = false;
  const declared = await viewer.readResponse(new Response(new ReadableStream({ cancel() { cancelled = true; } }),
    { headers: { "Content-Length": String(viewer.MAX_INLINE_BYTES + 1) } }));
  assert.equal(cancelled, true);
  assert.equal(declared.tooLarge, true);
  assert.equal(declared.text, null);
  assert.equal(declared.json, null);
  assert.equal(declared.exactSize, true);
  const streamed = await viewer.readResponse(new Response('"' + 'x'.repeat(viewer.MAX_INLINE_BYTES) + '"'));
  assert.equal(streamed.tooLarge, true);
  assert.equal(streamed.exactSize, false);
  const atCap = await viewer.readResponse(new Response('"' + 'x'.repeat(viewer.MAX_INLINE_BYTES - 2) + '"'));
  assert.equal(atCap.tooLarge, false);
  assert.equal(atCap.bytes, viewer.MAX_INLINE_BYTES);
});

test("deep nesting and wide objects are indexed without call-stack exhaustion", () => {
  const deep = viewer.parseText('['.repeat(12_000) + '0' + ']'.repeat(12_000));
  assert.equal(deep.lines, 24_001);
  assert.equal(deep.defaultFolded.length, 1);
  const wide = viewer.parseText(JSON.stringify(Object.fromEntries(Array.from({ length: 70_000 }, (_, id) => [id, 0]))));
  assert.equal(wide.lines, 70_002);
  assert.equal(wide.defaultFolded.length, 0);
});
