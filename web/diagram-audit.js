// Runs in the real browser, after packaged fonts load. Measures the rendered
// result rather than trusting the renderer's text-width estimates.
export function auditDiagrams() {
  const issues = [];
  const measurements = [];
  const gap = (p, b) => Math.hypot(Math.max(b.x - p.x, 0, p.x - b.x - b.width), Math.max(b.y - p.y, 0, p.y - b.y - b.height));
  const overlap = (a, b, inset = 0) => a.x + a.width > b.x + inset && b.x + b.width > a.x + inset && a.y + a.height > b.y + inset && b.y + b.height > a.y + inset;
  const points = (line) => [...line.points].map(({ x, y }) => ({ x, y }));
  for (const svg of document.querySelectorAll(".tin-diagram svg")) {
    const id = svg.closest("section")?.id || "diagram";
    const fail = (message) => issues.push(`${id}: ${message}`);
    const nodes = [...svg.querySelectorAll("g.node")];
    const view = svg.viewBox.baseVal;
    for (const paint of svg.querySelectorAll(" .tin-diagram-group, .node, .edge, .tin-diagram-arrow, .edge-label")) {
      const box = paint.getBBox();
      if (box.x < view.x || box.y < view.y || box.x + box.width > view.x + view.width || box.y + box.height > view.y + view.height) fail("paint outside the SVG viewBox");
    }
    const boxes = new Map(nodes.map((n) => [n.dataset.id, n.querySelector("rect").getBBox()]));
    for (const node of nodes) {
      const box = boxes.get(node.dataset.id);
      const text = node.querySelector("text").getBBox();
      const store = node.classList.contains("tin-diagram-store");
      const mark = node.querySelector("circle");
      const padding = { left: text.x - box.x, right: box.x + box.width - text.x - text.width,
        top: text.y - box.y - (store ? 12 : 0), bottom: box.y + box.height - text.y - text.height };
      measurements.push({ diagram: id, node: node.dataset.id, padding });
      if (padding.left < 19 || padding.right < 19) fail(`${node.dataset.id} horizontal padding ${JSON.stringify(padding)}`);
      if (padding.top < 12 || padding.bottom < 12) fail(`${node.dataset.id} vertical padding ${JSON.stringify(padding)}`);
      if (Math.abs(padding.top - padding.bottom) > 3) fail(`${node.dataset.id} unbalanced vertical padding ${JSON.stringify(padding)}`);
      if (mark && gap({ x: mark.cx.baseVal.value + mark.r.baseVal.value, y: mark.cy.baseVal.value }, text) < 7) fail(`${node.dataset.id} mark crowds text`);
      const lines = [...node.querySelectorAll("tspan")].map((line) => line.getBBox());
      for (let i = 1; i < lines.length; i++) if (lines[i].y - lines[i - 1].y - lines[i - 1].height < 3) fail(`${node.dataset.id} lines squeezed together`);
    }
    for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
      if (overlap(boxes.get(nodes[i].dataset.id), boxes.get(nodes[j].dataset.id))) fail("nodes overlap");
    }
    const headers = [...svg.querySelectorAll(".tin-diagram-group")].map((group) => {
      const text = group.querySelector("text").getBBox(), frame = group.querySelector("rect")?.getBBox();
      if (frame && (text.x - frame.x < 23 || frame.x + frame.width - text.x - text.width < 23 || text.y - frame.y < 20)) fail("group title padding");
      for (const [id, box] of boxes) if (overlap(text, box)) fail(`group title overlaps ${id}`);
      if(frame) {
        const fill=getComputedStyle(group.querySelector("rect")).fill;
        if(fill === "none" || fill === "rgba(0, 0, 0, 0)" || fill === getComputedStyle(document.body).backgroundColor) fail("frame has no distinct fill");
      }
      return text;
    });
    const arrows = [...svg.querySelectorAll(".tin-diagram-arrow")];
    for (const line of svg.querySelectorAll(".edge")) {
      const route = points(line);
      const arrow = arrows.find((a) => a.dataset.from === line.dataset.from && a.dataset.to === line.dataset.to);
      const style = getComputedStyle(line);
      const arrowStyle = getComputedStyle(arrow);
      if (style.stroke !== arrowStyle.stroke || style.strokeWidth !== arrowStyle.strokeWidth) fail("connector shaft/head paint differs");
      if (arrowStyle.fill !== "none") fail("arrowhead is filled");
      if (/rgba.*,[\s]*0\./.test(style.stroke) || style.stroke.includes(" / ")) fail("connector paint is translucent at joins");
      if (Math.abs(gap(route[0], boxes.get(line.dataset.from)) - 6) > 0.1) fail(`${line.dataset.from} source clearance`);
      if (Math.abs(gap(points(arrow)[1], boxes.get(line.dataset.to)) - 10) > 0.1) fail(`${line.dataset.to} target clearance`);
      for (let i = 1; i < route.length; i++) {
        const a = route[i - 1], b = route[i];
        if (Math.abs(a.x-b.x) > .01 && Math.abs(a.y-b.y) > .01) fail("connector is not orthogonal");
        if (svg.dataset.composed === "true" && i > 1 && i < route.length-1 && Math.hypot(a.x-b.x,a.y-b.y) < 15.9) fail("connector has a tiny interior jog");
        const segment = { x: Math.min(a.x, b.x) - 0.5, y: Math.min(a.y, b.y) - 0.5, width: Math.abs(a.x - b.x) + 1, height: Math.abs(a.y - b.y) + 1 };
        for (const header of headers) if (overlap(segment, header, 0.5)) fail("connector crosses group title");
        for (const [nodeId, box] of boxes) if (overlap(segment, box, 0.5)) fail(`connector crosses ${nodeId}`);
      }
    }
    const labels = [...svg.querySelectorAll(".edge-label")];
    for (let i = 0; i < labels.length; i++) {
      const box = labels[i].querySelector("rect").getBBox();
      const text = labels[i].querySelector("text").getBBox();
      if (text.x - box.x < 7 || box.x + box.width - text.x - text.width < 7 || text.y - box.y < 4 || box.y + box.height - text.y - text.height < 4) fail("connector label padding");
      for (const header of headers) if (overlap(box, header)) fail("connector label overlaps group title");
      for (const [nodeId, nodeBox] of boxes) if (overlap(box, nodeBox)) fail(`connector label overlaps ${nodeId}`);
      for (let j = i + 1; j < labels.length; j++) if (overlap(box, labels[j].querySelector("rect").getBBox())) fail("connector labels overlap");
      for (const arrow of arrows) if (overlap(box, arrow.getBBox())) fail("connector label hides arrowhead");
      for (const line of svg.querySelectorAll(".edge")) {
        if (line.dataset.from === labels[i].dataset.from && line.dataset.to === labels[i].dataset.to) continue;
        const route = points(line);
        for (let j = 1; j < route.length; j++) {
          const a = route[j - 1], b = route[j];
          if (overlap(box, { x: Math.min(a.x, b.x) - 0.5, y: Math.min(a.y, b.y) - 0.5, width: Math.abs(a.x - b.x) + 1, height: Math.abs(a.y - b.y) + 1 })) fail("connector label hides an unrelated route");
        }
      }
    }
  }
  return { issues, measurements };
}
