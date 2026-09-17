import { alignComposition } from "./diagram-alignment.js";
import {
  routeQuality,
  hits,
  segments,
  RoutingError,
} from "./diagram-geometry.js";
import { createRouter } from "./diagram-routing.js";
import { placeLabels } from "./diagram-labels.js";
import { acceptableRefinement, compositionPreference } from "./diagram-quality.js";
const PAD = 24,
  HEADER = 48;
const horizontal = (direction) => ["LR", "RL"].includes(direction);
const reverse = (direction) => ["RL", "BT"].includes(direction);

export async function layoutComposition(
  flow,
  measureNode,
  labelBlocks,
  measureTitle,
) {
  const definitions = new Map(
    [...flow.nodes, ...flow.groups].map((item) => [item.id, item]),
  );
  const degree = new Map(flow.nodes.map((n) => [n.id, 0]));
  for (const e of flow.edges)
    for (const id of [e.from, e.to]) degree.set(id, degree.get(id) + 1);
  const descendants = new Map();
  function members(id) {
    if (descendants.has(id)) return descendants.get(id);
    const item = definitions.get(id),
      ids = new Set([id]);
    for (const child of item.children || []) {
      for (const sub of members(child)) ids.add(sub);
    }
    descendants.set(id, ids);
    return ids;
  }
  for (const id of flow.layout) members(id);
  function measure(id, compact) {
    const data = definitions.get(id);
    if (!data.children) {
      const size = measureNode(data);
      // A self-loop needs a readable horizontal return, not a tiny corner curl.
      const loopWidths = flow.edges.flatMap((e, i) =>
        e.from === id && e.to === id
          ? [(labelBlocks.get(`@edge:${i}`)?.width || 0) + 68]
          : [],
      );
      const height =
        degree.get(id) > 8
          ? Math.max(size.height, (degree.get(id) - 1) * 16 + 24)
          : size.height;
      return {
        id,
        ...size,
        height,
        width: Math.max(
          size.width,
          Math.ceil(Math.max(0, ...loopWidths) / 8) * 8,
        ),
      };
    }
    return arrange(id, data.children, data.direction, data.kind, compact);
  }
  function arrange(id, ids, direction, kind = "layout", compact = false) {
    const children = ids.map((id) => measure(id, compact)),
      h = horizontal(direction),
      pad = kind === "frame" ? PAD : 0,
      header = kind === "layout" ? 0 : kind === "lane" ? 64 : HEADER;
    const gaps = children.slice(1).map((_, i) => {
      const left = new Set(ids.slice(0, i + 1).flatMap((n) => [...members(n)])),
        right = new Set(ids.slice(i + 1).flatMap((n) => [...members(n)]));
      const crossing = flow.edges
        .map((e, index) => ({ e, index }))
        .filter(
          ({ e }) =>
            (left.has(e.from) && right.has(e.to)) ||
            (right.has(e.from) && left.has(e.to)),
        );
      const labelSpace = Math.max(
        0,
        ...crossing.filter(({ e }) => !compact ||
          (members(ids[i]).has(e.from) && members(ids[i + 1]).has(e.to)) ||
          (members(ids[i]).has(e.to) && members(ids[i + 1]).has(e.from))).map(({ index }) => {
          const block = labelBlocks.get(`@edge:${index}`);
          return block ? (h ? block.width + 20 : block.height + 12) : 0;
        }),
      );
      return (
        Math.ceil(
          Math.max(
            72,
            labelSpace ? labelSpace + (compact ? 48 : 88) : 0,
            Math.min(160, crossing.length * 14 + 48),
          ) / 8,
        ) * 8
      );
    });
    const along =
        children.reduce((n, c) => n + (h ? c.width : c.height), 0) +
        gaps.reduce((a, b) => a + b, 0),
      across = Math.max(...children.map((c) => (h ? c.height : c.width)));
    let width = (h ? along : across) + pad * 2,
      height = (h ? across : along) + pad * 2 + header;
    if (kind !== "layout")
      width = Math.max(
        width,
        measureTitle(definitions.get(id).label) + pad * 2 + 24,
      );
    let cursor = 0;
    for (const [i, child] of children.entries()) {
      const position = reverse(direction)
        ? along - cursor - (h ? child.width : child.height)
        : cursor;
      child.x =
        pad +
        (h
          ? position
          : child.kind === "lane"
            ? 0
            : (width - pad * 2 - child.width) / 2);
      child.y = pad + header + (h ? (across - child.height) / 2 : position);
      cursor += (h ? child.width : child.height) + (gaps[i] || 0);
    }
    return { id, width, height, children, kind, header };
  }
  async function compose(refine, feedback, compact = false, balance = false) {
    const root = arrange("@root", flow.layout, flow.direction, "layout", compact),
      graph = {
        width: root.width + 128,
        height: root.height + 128,
        children: [],
        groups: [],
        edges: [],
      },
      boxes = new Map();
    function place(item, x, y) {
      const rect = { ...item, x: x + (item.x || 0), y: y + (item.y || 0) };
      boxes.set(item.id, rect);
      if (item.children) {
        if (item.id !== "@root" && item.kind !== "layout")
          graph.groups.push(
            Object.assign(rect, { label: definitions.get(item.id).label }),
          );
        for (const child of item.children) place(child, rect.x, rect.y);
      } else graph.children.push(rect);
    }
    place(root, 64, 64);
    if (refine)
      alignComposition(flow, root, boxes, graph, descendants, feedback, balance);

    const headers = graph.groups.map((g) => ({
      x: g.x + (g.kind === "frame" ? PAD : 0),
      y: g.y + (g.kind === "frame" ? 22 : 6),
      width: measureTitle(g.label),
      height: 18,
    }));
    const router = await createRouter(graph, flow, headers);
    try {
      const exterior = new Set(),
        checkpoints = new Map();
      for (let attempt = 0; attempt <= flow.edges.length; attempt++) {
        graph.edges = router.routes();
        const repairGroups = new Map();
        for (const edge of graph.edges) {
          const foreign = graph.groups.filter(
            (g) =>
              g.kind === "frame" &&
              !descendants.get(g.id).has(edge.data.from) &&
              !descendants.get(g.id).has(edge.data.to),
          );
          const key = foreign.map((f) => f.id).join("/");
          if (!key) continue;
          if (!repairGroups.has(key))
            repairGroups.set(key, { foreign, edges: [] });
          repairGroups.get(key).edges.push(edge);
        }
        for (const { foreign, edges } of repairGroups.values()) {
          const crosses = (edge) =>
            foreign.some((frame) =>
              segments(edge.points).some(([a, b]) => hits(a, b, frame)),
            );
          if (!edges.some(crosses)) continue;
          const plans = router.plans.filter((p) =>
            edges.some((e) => e.id === p.id),
          );
          const repair = await createRouter(
            graph,
            { edges: edges.map((e) => e.data) },
            headers,
            foreign,
            plans,
          );
          try {
            for (const p of plans)
              if (checkpoints.has(p.id))
                repair.checkpoint(
                  Number(p.id.split(":")[1]),
                  checkpoints.get(p.id),
                );
            const routes = repair.routes();
            for (const edge of edges)
              edge.points = routes.find((r) => r.id === edge.id).points;
          } finally {
            repair.dispose();
          }
          if (edges.some(crosses))
            throw new RoutingError("Connector crosses an unrelated frame.");
        }
        const missing = placeLabels(graph, labelBlocks, headers);
        if (!missing) break;
        if (exterior.has(missing.id))
          throw new RoutingError(
            `No clear label corridor: ${missing.data.label}`,
          );
        exterior.add(missing.id);
        const block = labelBlocks.get(missing.id),
          width = block.width + 20,
          height = block.height + 12;
        const y = graph.height + height / 2 + 32;
        const center = Math.max(
          64 + width / 2,
          (missing.points[0].x + missing.points.at(-1).x) / 2,
        );
        const left = { x: center - width / 2 - 32, y },
          right = { x: center + width / 2 + 32, y };
        const corridor =
          missing.points[0].x <= missing.points.at(-1).x
            ? [left, right]
            : [right, left];
        checkpoints.set(missing.id, corridor);
        router.checkpoint(Number(missing.id.split(":")[1]), corridor);
        graph.height = y + height / 2 + 64;
        graph.width = Math.max(graph.width, center + width / 2 + 96);
      }
    } finally {
      router.dispose();
    }
    // The router may use an exterior corridor. Include its geometry in the canvas.
    const paint = [
      ...graph.children,
      ...graph.groups,
      ...graph.edges.flatMap((e) => e.labels),
      ...graph.edges.flatMap((e) => e.points),
    ];
    const dx = Math.max(0, 32 - Math.min(...paint.map((r) => r.x))),
      dy = Math.max(0, 32 - Math.min(...paint.map((r) => r.y)));
    for (const r of [
      ...graph.children,
      ...graph.groups,
      ...graph.edges.flatMap((e) => e.labels),
      ...graph.edges.flatMap((e) => e.points),
    ]) {
      r.x += dx;
      r.y += dy;
    }
    graph.width = Math.max(
      graph.width + dx,
      ...paint.map((r) => r.x + (r.width || 0) + 32),
    );
    graph.height = Math.max(
      graph.height + dy,
      ...paint.map((r) => r.y + (r.height || 0) + 32),
    );
    for (const edge of graph.edges)
      edge.sections = [
        {
          startPoint: edge.points[0],
          bendPoints: edge.points.slice(1, -1),
          endPoint: edge.points.at(-1),
        },
      ];
    return graph;
  }
  const candidates = [],
    failures = [];
  async function candidate(refine, feedback, compact = false, balance = false) {
    try {
      const graph = await compose(refine, feedback, compact, balance);
      candidates.push(graph);
      return graph;
    } catch (error) {
      if (!(error instanceof RoutingError)) throw error;
      failures.push(error);
    }
  }
  const initial = await candidate(false);
  await candidate(true);
  if (initial) await candidate(true, initial);
  if (!candidates.length) throw failures[0];
  const baseline = candidates.sort((a, b) => routeQuality(a) - routeQuality(b))[0];
  // Three extra placement candidates keep refinement bounded.
  // Distant return labels need not reserve their full width in every crossed gap.
  const balanced = await candidate(true, undefined, false, true);
  const measuredCompact = await candidate(false, undefined, true);
  const compact = await candidate(true, undefined, true, true);
  return [baseline, balanced, measuredCompact, compact]
    .filter((g) => g && (g === baseline || acceptableRefinement(g, baseline)))
    .sort((a, b) => routeQuality(a) + compositionPreference(a) - routeQuality(b) - compositionPreference(b))[0];
}
