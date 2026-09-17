// Advisory measurements, not a claim about meaning or a pass/fail beauty score.
// Accepts either a routed graph or geometry read back from the painted SVG.
export function diagramQuality(graph) {
  const round = (n) => Math.round(n * 100) / 100;
  const distance = (a, b) => Math.abs(a.x - b.x) + Math.abs(a.y - b.y);
  const nodes = new Map(graph.children.map((n) => [n.id, n]));
  const edges = graph.edges;
  let bends = 0, length = 0, shortJogs = 0, crossings = 0, longestDetour = 1;
  const segments = [];
  for (const [id, edge] of edges.entries()) {
    const points = edge.points;
    let routed = 0;
    bends += Math.max(0, points.length - 2);
    for (let i = 1; i < points.length; i++) {
      const a = points[i - 1], b = points[i], size = distance(a, b);
      routed += size;
      if (i > 1 && i < points.length - 1 && size < 15.9) shortJogs++;
      segments.push({ id, a, b, horizontal: Math.abs(a.y - b.y) < 0.01 });
    }
    length += routed;
    longestDetour = Math.max(longestDetour, routed / Math.max(32, distance(points[0], points.at(-1))));
  }
  for (let i = 0; i < segments.length; i++) for (let j = i + 1; j < segments.length; j++) {
    const a = segments[i], b = segments[j];
    if (a.id === b.id || a.horizontal === b.horizontal) continue;
    const [h, v] = a.horizontal ? [a, b] : [b, a];
    if (v.a.x > Math.min(h.a.x, h.b.x) && v.a.x < Math.max(h.a.x, h.b.x) &&
        h.a.y > Math.min(v.a.y, v.b.y) && h.a.y < Math.max(v.a.y, v.b.y)) crossings++;
  }
  const center = (n, axis) => n[axis] + n[axis === "x" ? "width" : "height"] / 2;
  // Measure only locally unambiguous, monotonic call chains. A return, signal,
  // or fork does not tell us which path the author considers primary.
  let chainDrift = 0, chainJoints = 0;
  for (const node of nodes.values()) for (const axis of ["x", "y"]) for (const sign of [-1, 1]) {
    const cross = axis === "x" ? "y" : "x";
    const forward = (edge) => {
      const a = nodes.get(edge.data.from), b = nodes.get(edge.data.to);
      return edge.data.kind !== "signal" && a.id !== b.id &&
        sign * (center(b, axis) - center(a, axis)) > 0 &&
        Math.abs(center(b, cross) - center(a, cross)) <= 24;
    };
    const incoming = edges.filter((e) => e.data.to === node.id && forward(e));
    const outgoing = edges.filter((e) => e.data.from === node.id && forward(e));
    if (incoming.length !== 1 || outgoing.length !== 1) continue;
    const a = incoming[0].points, b = outgoing[0].points;
    if (Math.abs(a.at(-1)[cross] - a.at(-2)[cross]) > .01 || Math.abs(b[0][cross] - b[1][cross]) > .01) continue;
    chainJoints++;
    chainDrift += Math.abs(a.at(-1)[cross] - b[0][cross]);
  }
  // Only equivalent peers (identical directed, typed neighbors) count as a
  // balanced fork. Different conditional branches may intentionally be unequal.
  const peers = new Map();
  for (const node of nodes.values()) {
    const signature = edges.filter((e) => e.data.from === node.id || e.data.to === node.id)
      .map(({ data: e }) => `${e.from === node.id ? "out" : "in"}:${e.kind}:${e.from === node.id ? e.to : e.from}`).sort().join("|");
    if (!signature) continue;
    if (!peers.has(signature)) peers.set(signature, []);
    peers.get(signature).push(node);
  }
  let branchImbalance = 0, peerBands = 0;
  for (const band of peers.values()) {
    if (band.length < 2) continue;
    for (const axis of ["x", "y"]) {
      const cross = axis === "x" ? "y" : "x", size = axis === "x" ? "width" : "height";
      if (Math.max(...band.map((n) => center(n, cross))) - Math.min(...band.map((n) => center(n, cross))) > .1) continue;
      const mid = (Math.min(...band.map((n) => n[axis])) + Math.max(...band.map((n) => n[axis] + n[size]))) / 2;
      const connected = edges.filter((e) => e.data.from === band[0].id || e.data.to === band[0].id);
      for (const { data: e } of connected) {
        if (e.kind === "signal") continue;
        const hub = nodes.get(e.from === band[0].id ? e.to : e.from);
        if (band.includes(hub) || Math.abs(center(hub, cross) - center(band[0], cross)) < 24) continue;
        peerBands++;
        branchImbalance += Math.abs(mid - center(hub, axis));
      }
    }
  }
  return { width: round(graph.width), height: round(graph.height), bends, crossings, shortJogs,
    routeLength: round(length), longestDetour: round(longestDetour), chainJoints, chainDrift: round(chainDrift),
    peerBands, branchImbalance: round(branchImbalance),
    fitScale: round(Math.min(1, 1200 / graph.width, 800 / graph.height)) };
}

export function compositionPreference(graph) {
  const q = diagramQuality(graph);
  return q.chainDrift * .3 + q.branchImbalance * .5;
}

// A new candidate cannot buy fewer bends with a substantially smaller overview,
// additional crossings, or tiny jogs. The original valid layout stays available.
export function acceptableRefinement(candidate, baseline) {
  const a = diagramQuality(candidate), b = diagramQuality(baseline);
  const fit = (g) => Math.min(1, 1200 / g.width, 800 / g.height);
  return a.crossings <= b.crossings && a.shortJogs <= b.shortJogs &&
    a.chainDrift <= b.chainDrift + 0.1 && fit(candidate) >= fit(baseline) * 0.97 &&
    a.routeLength <= b.routeLength * 1.05;
}

// Self-contained so Playwright can evaluate this against actual rendered DOM;
// also works with saved portable SVGs in the before/after comparison tool.
export function readDiagramGeometry(document = globalThis.document) {
  return [...document.querySelectorAll("svg")].map((svg) => {
    const [, , width, height] = svg.getAttribute("viewBox").split(/\s+/).map(Number);
    const rect = (el) => Object.fromEntries(["x", "y", "width", "height"].map((key) => [key, Number(el.getAttribute(key))]));
    return { id: svg.closest("section")?.id || "diagram", width, height,
      children: [...svg.querySelectorAll("g.node")].map((n) => ({ id: n.getAttribute("data-id"), ...rect(n.querySelector("rect")) })),
      edges: [...svg.querySelectorAll("polyline.edge")].map((e) => ({
        data: { from: e.getAttribute("data-from"), to: e.getAttribute("data-to"), kind: e.hasAttribute("stroke-dasharray") ? "signal" : "call" },
        points: e.getAttribute("points").trim().split(/\s+/).map((p) => { const [x, y] = p.split(",").map(Number); return { x, y }; }),
      })),
    };
  });
}
