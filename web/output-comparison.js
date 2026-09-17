import { diffLines, diffWordsWithSpace } from "diff";

// A read-only renderer. No patch application, Markdown interpretation, or file writes.
const lines = (text) => text.match(/[^\n]*\n|[^\n]+$/g) || [];
const escape = (text) => String(text).replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
})[char]);

function changes(before, after, timeout = 500) {
  const result = diffLines(before, after, { timeout, maxEditLength: 10000 });
  if (!result) throw new Error("This comparison is too complex to show completely. Read the complete files instead.");
  return result;
}

function laterEdits(starting, current) {
  if (!starting?.available) return null;
  const edits = [];
  let position = 0;
  let removed = false;
  for (const part of changes(starting.content ?? "", current)) {
    if (part.removed) {
      removed = true;
    } else if (part.added) {
      edits.push({ start: position, end: position + part.count });
      position += part.count;
      removed = false;
    } else {
      if (removed) edits.push({ start: position, end: position });
      removed = false;
      position += part.count;
    }
  }
  if (removed) edits.push({ start: position, end: position });
  return edits;
}

function wordMarks(before, after, deadline) {
  if (Date.now() > deadline || before.length + after.length > 20000) return null;
  const parts = diffWordsWithSpace(before, after, { timeout: 20, maxEditLength: 1500 });
  if (!parts) return null; // Complete line diff remains usable without word decoration.
  const spans = { current: [], saved: [] };
  const offsets = { current: 0, saved: 0 };
  for (const part of parts) {
    for (const side of ["current", "saved"]) {
      if ((side === "current" && part.added) || (side === "saved" && part.removed)) continue;
      if (part.added || part.removed) spans[side].push([offsets[side], offsets[side] + part.value.length]);
      offsets[side] += part.value.length;
    }
  }
  return spans;
}

export function buildComparison(comparison) {
  if (!comparison.complete || typeof comparison.saved.content !== "string"
      || (comparison.current.presence === "file" && typeof comparison.current.content !== "string")) {
    throw new Error("A complete comparison is unavailable.");
  }
  const current = comparison.current.content ?? "";
  const saved = comparison.saved.content;
  let edits = null;
  try { edits = laterEdits(comparison.starting, current); } catch { /* Unknown, never unmarked certainty. */ }
  const parts = changes(current, saved);
  const rows = [];
  const blocks = [];
  let oldLine = 0;
  let newLine = 0;
  const deadline = Date.now() + 150;
  for (let index = 0; index < parts.length;) {
    const part = parts[index];
    if (!part.added && !part.removed) {
      for (const text of lines(part.value)) rows.push({ side: "both", text, oldLine: ++oldLine, newLine: ++newLine });
      index += 1;
      continue;
    }
    let before = "";
    let after = "";
    while (index < parts.length && (parts[index].added || parts[index].removed)) {
      if (parts[index].removed) before += parts[index].value;
      else after += parts[index].value;
      index += 1;
    }
    const start = oldLine;
    const end = start + lines(before).length;
    const marked = edits?.some((edit) => edit.start === edit.end
      ? after.length > 0 && start <= edit.start && edit.start <= end
      : Math.max(start, edit.start) < Math.min(end, edit.end)) || false;
    const block = { start: rows.length, marked };
    const highlights = wordMarks(before, after, deadline);
    for (const [side, text] of [["current", before], ["saved", after]]) {
      let offset = 0;
      for (const value of lines(text)) {
        rows.push({
          side, text: value, marked,
          oldLine: side === "current" ? ++oldLine : null,
          newLine: side === "saved" ? ++newLine : null,
          marks: highlights?.[side].map(([a, b]) => [Math.max(0, a - offset), Math.min(value.length, b - offset)])
            .filter(([a, b]) => a < b) || [],
        });
        offset += value.length;
      }
    }
    block.end = rows.length;
    blocks.push(block);
  }
  const visible = new Set();
  const hunks = [];
  for (const block of blocks) {
    const previous = hunks.at(-1);
    if (previous && block.start - previous.end <= 2) previous.end = block.end;
    else hunks.push({ start: block.start, end: block.end });
    for (let i = Math.max(0, block.start - 1); i < Math.min(rows.length, block.end + 1); i += 1) visible.add(i);
  }
  return { rows, blocks, hunks, visible, annotationsAvailable: edits !== null };
}

function rowHtml(row, index, numbered, editorial) {
  // Keep whitespace and CRLF/EOF differences explicit. Never use <del>/<s> or parsed markup.
  const text = row.text.replace(/\n$/, "");
  let offset = 0;
  let content = "";
  for (const [start, end] of row.marks || []) {
    content += escape(text.slice(offset, start));
    content += `<mark>${escape(text.slice(start, end))}</mark>`;
    offset = end;
  }
  content += escape(text.slice(offset));
  content = content.replace(/\r/g, '<span class="compare-eol" title="Carriage return">␍</span>');
  const sign = row.side === "current" ? "−" : row.side === "saved" ? "+" : " ";
  const label = row.side === "current" ? (editorial ? "Previous version: " : "Current file, would be removed: ") : row.side === "saved" ? (editorial ? "Revised version: " : "Saved result, would be added: ") : "Unchanged: ";
  return `<div class="compare-line is-${row.side}${row.marked ? " is-later" : ""}" data-compare-line="${index}">
    <span class="sr-only">${row.marked ? "This change would replace later edits. " : ""}${label}</span>
    ${numbered ? `<span class="compare-line-number" aria-hidden="true">${row.oldLine ?? ""}</span><span class="compare-line-number" aria-hidden="true">${row.newLine ?? ""}</span>` : ""}
    <span class="compare-sign" aria-hidden="true">${sign}</span><span class="compare-line-text">${content}</span>
    ${row.side !== "both" && !row.text.endsWith("\n") ? '<span class="compare-eol">No newline at end of file</span>' : ""}
  </div>`;
}

export function mountDiff(root, model, { numbered = false, onNavigate = () => {}, editorial = false } = {}) {
  let active = 0;
  function render() {
    const html = [];
    for (let i = 0; i < model.rows.length;) {
      if (model.visible.has(i)) {
        html.push(rowHtml(model.rows[i], i, numbered, editorial));
        i += 1;
      } else {
        const start = i;
        while (i < model.rows.length && !model.visible.has(i)) i += 1;
        const count = i - start;
        html.push(`<div class="compare-fold"><span>${count} unchanged ${count === 1 ? "line" : "lines"}${i === model.rows.length ? " to the end" : ""}</span> <button type="button" data-fold-start="${start}" data-fold-end="${i}">Show<span class="sr-only"> up to 20 unchanged lines</span></button></div>`);
      }
    }
    root.innerHTML = html.join("");
  }
  function navigate(delta) {
    if (!model.hunks.length) return;
    active = Math.max(0, Math.min(model.hunks.length - 1, active + delta));
    const row = root.querySelector(`[data-compare-line="${model.hunks[active].start}"]`);
    row?.scrollIntoView({ block: "center", behavior: "instant" });
    onNavigate(active + 1, model.hunks.length);
  }
  function onClick(event) {
    const button = event.target.closest("[data-fold-start]");
    if (!button) return;
    const start = Number(button.dataset.foldStart);
    const end = Number(button.dataset.foldEnd);
    const first = start === 0 ? Math.max(start, end - 20) : start;
    for (let i = first; i < Math.min(first + 20, end); i += 1) model.visible.add(i);
    render();
    const revealed = root.querySelector(`[data-compare-line="${first}"]`);
    if (revealed) { revealed.tabIndex = -1; revealed.focus({ preventScroll: true }); }
  }
  root.addEventListener("click", onClick);
  render();
  return { navigate, destroy: () => root.removeEventListener("click", onClick) };
}
