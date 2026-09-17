import {
  RoutingError,
  hits,
  inflate,
  segments,
  simplify,
} from "./diagram-geometry.js";
const STEP = 28,
  INSET = 12;
const center = (r, axis) => r[axis] + r[axis === "x" ? "width" : "height"] / 2;
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const normals = {
  left: { x: -1, y: 0, dir: 4 },
  right: { x: 1, y: 0, dir: 8 },
  top: { x: 0, y: -1, dir: 1 },
  bottom: { x: 0, y: 1, dir: 2 },
};
function point(r, side, value) {
  if (side === "top" || side === "bottom")
    return {
      x: value ?? center(r, "x"),
      y: r.y + (side === "bottom" ? r.height : 0),
      side,
    };
  return {
    x: r.x + (side === "right" ? r.width : 0),
    y: value ?? center(r, "y"),
    side,
  };
}
const extend = (p, step = STEP) => ({
  x: p.x + normals[p.side].x * step,
  y: p.y + normals[p.side].y * step,
});

// Consecutive near-collinear calls should read as one continuous line. Pairwise
// midpoint ports otherwise drift a few pixels at every differently sized node.
// Infer only an unambiguous, monotone chain with a clear common corridor; this
// supplies a preference, never a constraint on placement or obstacle routing.
function chainAxes(graph, flow, headers) {
  const boxes = new Map(graph.children.map((n) => [n.id, n]));
  const preferred = new Map();
  for (const axis of ["x", "y"]) {
    const size = axis === "x" ? "width" : "height",
      along = axis === "x" ? "y" : "x",
      length = axis === "x" ? "height" : "width";
    const links = flow.edges.flatMap((e, index) => {
      if (e.kind !== "call" || e.from === e.to) return [];
      const a = boxes.get(e.from), b = boxes.get(e.to);
      if (Math.abs(center(a, axis) - center(b, axis)) > 24) return [];
      const sign = a[along] + a[length] <= b[along] ? 1
        : b[along] + b[length] <= a[along] ? -1 : 0;
      return sign ? [{ ...e, index, sign }] : [];
    });
    const incoming = (id, sign) => links.filter((e) => e.to === id && e.sign === sign);
    const outgoing = (id, sign) => links.filter((e) => e.from === id && e.sign === sign);
    const next = new Map(), previous = new Set();
    for (const e of links) {
      const after = outgoing(e.to, e.sign);
      if (incoming(e.to, e.sign).length === 1 && after.length === 1) {
        next.set(e.index, after[0]);
        previous.add(after[0].index);
      }
    }
    for (const first of links.filter((e) => !previous.has(e.index))) {
      const chain = [first];
      while (next.has(chain.at(-1).index)) chain.push(next.get(chain.at(-1).index));
      if (chain.length < 2) continue;
      const nodes = [boxes.get(first.from), ...chain.map((e) => boxes.get(e.to))];
      const low = Math.max(...nodes.map((n) => n[axis] + INSET)),
        high = Math.min(...nodes.map((n) => n[axis] + n[size] - INSET));
      if (low > high) continue;
      const sides = axis === "x" ? ["bottom", "top"] : ["right", "left"];
      if (first.sign < 0) sides.reverse();
      const centers = nodes.map((n) => center(n, axis));
      const values = [...new Set([centers.reduce((a, b) => a + b, 0) / centers.length, ...centers]
        .map((v) => clamp(Math.round(v * 2) / 2, low, high)))];
      const value = values
        .filter((v) => chain.every((e) => {
          const a = point(boxes.get(e.from), sides[0], v),
            b = point(boxes.get(e.to), sides[1], v);
          return ![...graph.children.filter((n) => n.id !== e.from && n.id !== e.to), ...headers]
            .some((n) => hits(a, b, inflate(n, 24)));
        }))
        .sort((a, b) => centers.reduce((s, c) => s + (a - c) ** 2 - (b - c) ** 2, 0))[0];
      if (value === undefined) continue;
      for (const e of chain) preferred.set(e.index, { axis, value, sides });
    }
  }
  return preferred;
}

// Jointly choose a small set of attachment candidates. This is composition
// policy, not path search: libavoid still finds and separates obstacle-free paths.
export function planPorts(graph, flow, headers) {
  const boxes = new Map(graph.children.map((n) => [n.id, n])),
    used = new Map(),
    result = [],
    spines = chainAxes(graph, flow, headers);
  const degree = new Map(graph.children.map((n) => [n.id, 0]));
  for (const e of flow.edges)
    for (const id of [e.from, e.to]) degree.set(id, degree.get(id) + 1);
  const occupied = (id, p) =>
    (used.get(id) || []).some(
      (q) => q.side === p.side && Math.hypot(q.x - p.x, q.y - p.y) < 15.9,
    );
  for (const [index, e] of flow.edges.entries()) {
    const a = boxes.get(e.from),
      b = boxes.get(e.to),
      options = [],
      spine = spines.get(index);
    const obstacles = [
      ...graph.children
        .filter((n) => n !== a && n !== b)
        .map((n) => inflate(n, 24)),
      ...headers.map((h) => inflate(h, 24)),
    ];
    function add(start, end, route) {
      route = simplify(route);
      if (occupied(e.from, start) || occupied(e.to, end)) return;
      // Stubs must depart outward and stay clear of the other endpoint's body.
      if (
        segments(route).some(
          ([u, v]) =>
            hits(u, v, inflate(a, -0.1)) || hits(u, v, inflate(b, -0.1)),
        )
      )
        return;
      const bends = route.length - 2,
        length = segments(route).reduce(
          (s, [u, v]) => s + Math.abs(u.x - v.x) + Math.abs(u.y - v.y),
          0,
        );
      const clashes = obstacles.filter((n) =>
        segments(route).some(([u, v]) => hits(u, v, n)),
      ).length;
      const deviation = [start, end].reduce(
        (s, p, i) =>
          s +
          Math.abs(
            p.side === "top" || p.side === "bottom"
              ? p.x - center(i ? b : a, "x")
              : p.y - center(i ? b : a, "y"),
          ),
        0,
      );
      const short = segments(route).filter(
        ([u, v]) => Math.hypot(u.x - v.x, u.y - v.y) < 24,
      ).length;
      options.push({
        start,
        end,
        cost:
          clashes * 1500 +
          short * 300 +
          bends * 100 +
          length * 0.05 +
          deviation * 0.35 +
          // Worth less than even one extra bend. Occupied ports and obstacle
          // clearance still take precedence over a continuous visual axis.
          (spine ? Math.min(40,
            (Math.abs(start[spine.axis] - spine.value) + Math.abs(end[spine.axis] - spine.value)) * 4
          ) : 0),
      });
    }
    if (spine) {
      const s = point(a, spine.sides[0], spine.value),
        t = point(b, spine.sides[1], spine.value);
      add(s, t, [s, t]);
    }
    // A shared axis is more valuable than independently centered endpoints.
    if (e.from !== e.to)
      for (const [axis, size, sides] of [
        ["y", "height", a.x < b.x ? ["right", "left"] : ["left", "right"]],
        ["x", "width", a.y < b.y ? ["bottom", "top"] : ["top", "bottom"]],
      ]) {
        const low = Math.max(a[axis] + INSET, b[axis] + INSET),
          high = Math.min(a[axis] + a[size] - INSET, b[axis] + b[size] - INSET);
        if (low > high) continue;
        const mid = clamp((center(a, axis) + center(b, axis)) / 2, low, high);
        for (const value of [
          mid,
          mid - 16,
          mid + 16,
          mid - 32,
          mid + 32,
        ].filter((v) => v >= low && v <= high)) {
          const s = point(a, sides[0], value),
            t = point(b, sides[1], value);
          // Only use facing sides when the corresponding rectangles are separated.
          if (
            axis === "y"
              ? a.x + a.width <= b.x || b.x + b.width <= a.x
              : a.y + a.height <= b.y || b.y + b.height <= a.y
          )
            add(s, t, [s, t]);
        }
      }
    if (e.from === e.to)
      for (const side of ["bottom", "top"]) {
        const s = point(a, side, a.x + INSET),
          t = point(a, side, a.x + a.width - INSET);
        add(s, t, [s, extend(s), extend(t), t]);
      }
    for (const from of Object.keys(normals))
      for (const to of Object.keys(normals)) {
        if (e.from === e.to) continue;
        const av = from === "top" || from === "bottom" ? "x" : "y",
          bv = to === "top" || to === "bottom" ? "x" : "y";
        const asize = av === "x" ? "width" : "height",
          bsize = bv === "x" ? "width" : "height";
        const pressure = degree.get(e.from) > 8 || degree.get(e.to) > 8;
        const offsets = (size) => [
          0,
          ...Array.from(
            { length: Math.floor((size / 2 - INSET) / 16) },
            (_, i) => [-(i + 1) * 16, (i + 1) * 16],
          ).flat(),
        ];
        for (const sourceShift of pressure
          ? offsets(a[asize])
          : [0, -16, 16, -32, 32]) {
          for (const targetShift of pressure
            ? offsets(b[bsize])
            : [sourceShift]) {
            if (
              Math.abs(sourceShift) > a[asize] / 2 - INSET ||
              Math.abs(targetShift) > b[bsize] / 2 - INSET
            )
              continue;
            const s = point(a, from, center(a, av) + sourceShift),
              t = point(b, to, center(b, bv) + targetShift);
            if (occupied(e.from, s) || occupied(e.to, t)) continue;
            for (const step of [28, 48]) {
              const u = extend(s, step),
                v = extend(t, step);
              add(s, t, [s, u, { x: v.x, y: u.y }, v, t]);
              add(s, t, [s, u, { x: u.x, y: v.y }, v, t]);
              add(s, t, [
                s,
                u,
                { x: (u.x + v.x) / 2, y: u.y },
                { x: (u.x + v.x) / 2, y: v.y },
                v,
                t,
              ]);
              add(s, t, [
                s,
                u,
                { x: u.x, y: (u.y + v.y) / 2 },
                { x: v.x, y: (u.y + v.y) / 2 },
                v,
                t,
              ]);
            }
          }
        }
      }
    const chosen = options.sort((a, b) => a.cost - b.cost)[0];
    if (!chosen)
      throw new RoutingError(
        `No spaced attachment points: ${e.from} → ${e.to}`,
      );
    for (const [id, p] of [
      [e.from, chosen.start],
      [e.to, chosen.end],
    ]) {
      if (!used.has(id)) used.set(id, []);
      used.get(id).push(p);
    }
    result.push({
      id: `@edge:${index}`,
      data: e,
      start: chosen.start,
      end: chosen.end,
      fromDir: normals[chosen.start.side].dir,
      toDir: normals[chosen.end.side].dir,
    });
  }
  return result;
}
