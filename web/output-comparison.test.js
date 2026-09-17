import assert from "node:assert/strict";
import test from "node:test";
import { parseHTML } from "linkedom";
import { buildComparison, mountDiff } from "./output-comparison.js";

export function fixture(current = "Current\n", saved = "Saved\n", starting = "Original\n") {
  return { run_id: "11111111-1111-4111-8111-111111111111", project_id: "project", path: "reports/ARTICLE.md", media_type: "text/markdown",
    complete: true, identical: current === saved, allowed_actions: ["keep_current", "use_saved"], resolution: null,
    current: { content: current, revision: "b".repeat(40), presence: current === null ? "missing" : "file" },
    saved: { content: saved, revision: "c".repeat(40) },
    starting: { content: starting, revision: "a".repeat(40), available: true, presence: starting === null ? "missing" : "file" } };
}

test("line diff reconstructs both exact bodies, including whitespace, CRLF, Unicode, and EOF", () => {
  for (const [current, saved] of [["a  b\r\nlast", "a b\nlast\n"], ["", "\n"], ["<script>🚀</script>\n", "你好\t世界"], [null, "a\n"]]) {
    const model = buildComparison(fixture(current, saved));
    assert.equal(model.rows.filter((row) => row.side !== "saved").map((row) => row.text).join(""), current ?? "");
    assert.equal(model.rows.filter((row) => row.side !== "current").map((row) => row.text).join(""), saved);
  }
});

test("warnings mark affected blocks, not unrelated run edits in shared context", () => {
  const base = "Old intro\n\nHeading\n\n12 pages\nNumbers are medians\n\nclosing\n";
  const current = base.replace("12 pages", "9 pages").replace("Numbers are medians", "Caveat");
  const saved = base.replace("Old intro", "New intro");
  const model = buildComparison(fixture(current, saved, base));
  assert.deepEqual(model.blocks.map((block) => block.marked), [false, true]);
  assert(model.rows.find((row) => row.side === "saved" && row.text === "Numbers are medians\n").marked);
  assert(!model.rows.find((row) => row.text === "New intro\n").marked);
});

test("restoring text removed after start is marked even without any removed current line", () => {
  const model = buildComparison(fixture("a\nc\n", "a\nb\nc\n", "a\nb\nc\n"));
  assert.equal(model.blocks[0].marked, true);
  assert.equal(model.rows.filter((row) => row.side === "current").length, 0);
});

test("absent starting file is known; unavailable starting file is not absence of later edits", () => {
  const comparison = fixture("human addition\n", "saved\n", null);
  assert(buildComparison(comparison).blocks[0].marked);
  comparison.starting = { available: false, content: null };
  const model = buildComparison(comparison);
  assert.equal(model.annotationsAvailable, false);
  assert.equal(model.blocks[0].marked, false);
});

test("renderer escapes markup and exposes side and EOF without strikethrough", () => {
  const { document } = parseHTML('<div id="diff"></div>');
  const root = document.getElementById("diff");
  mountDiff(root, buildComparison(fixture("<img src=x onerror=alert(1)>", "<script>bad</script>\n")));
  assert.equal(root.querySelectorAll("img,script,del,s").length, 0);
  assert.match(root.textContent, /Current file, would be removed/);
  assert.match(root.textContent, /Saved result, would be added/);
  assert.match(root.textContent, /No newline at end of file/);
});

test("folding retains one line of context and reveals no more than 20 per Show", () => {
  const base = Array.from({ length: 60 }, (_, i) => `${i}\n`).join("");
  const model = buildComparison(fixture(base, base.replace("30\n", "changed\n"), base));
  assert.equal(model.visible.size, 4);
  const { document, window } = parseHTML('<div id="diff"></div>');
  const root = document.getElementById("diff");
  const renderer = mountDiff(root, model, { numbered: true });
  root.querySelector("button").dispatchEvent(new window.Event("click", { bubbles: true }));
  assert.equal(model.visible.size, 24);
  assert(root.querySelector(".compare-line-number"));
  renderer.destroy();
});

test("an incomplete response cannot be presented as a shortened comparison", () => {
  assert.throws(() => buildComparison({ ...fixture(), complete: false }), /complete comparison/);
});
