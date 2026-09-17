// Refine measured rows/columns using the connections between them. A move is a
// translation of a whole subtree along its parent's cross axis; authored order,
// sibling gaps, frame padding, and all text measurements remain intact.
export function alignComposition(
  flow,
  root,
  boxes,
  graph,
  descendants,
  feedback,
  balance = false,
) {
  const parent = new Map(),
    order = [];
  function visit(item) {
    for (const child of item.children || []) {
      parent.set(child.id, item.id);
      order.push(child.id);
      visit(child);
    }
  }
  visit(root);
  const groups = new Map(flow.groups.map((g) => [g.id, g]));
  // A row/column of peer inputs or outputs is one visual unit. Keep its common
  // centerline when every leaf has the same external connections; nudging each
  // leaf for its own port otherwise turns a deliberate column into a staircase.
  const peerGroups = new Set();
  for (const group of flow.groups) {
    if (
      group.children.length < 2 ||
      group.children.some((id) => groups.has(id))
    )
      continue;
    const signatures = group.children.map((id) =>
      flow.edges
        .filter((e) => e.from === id || e.to === id)
        .map((e) =>
          [
            e.from === id ? "out" : "in",
            e.kind,
            e.from === id ? e.to : e.from,
          ].join(":"),
        )
        .sort()
        .join("|"),
    );
    if (signatures[0] && signatures.every((value) => value === signatures[0]))
      peerGroups.add(group.id);
  }
  const degree = new Map(flow.nodes.map((n) => [n.id, 0]));
  for (const edge of flow.edges)
    for (const id of [edge.from, edge.to]) degree.set(id, degree.get(id) + 1);
  const center = (r, axis) =>
    r[axis] + r[axis === "x" ? "width" : "height"] / 2;
  const priorNodes = new Map((feedback?.children || []).map((n) => [n.id, n]));
  function desiredShift(e, members, axis) {
    const insideId = members.has(e.from) ? e.from : e.to,
      outsideId = members.has(e.from) ? e.to : e.from;
    const inside = boxes.get(insideId),
      outside = boxes.get(outsideId);
    if (balance && !feedback) {
      // Equivalent leaf branches stay a unit. Align the hub to their visible
      // envelope rather than letting the first individually attractive edge win.
      const peerId = peerGroups.has(parent.get(outsideId)) ? parent.get(outsideId) :
        peerGroups.has(parent.get(insideId)) ? parent.get(insideId) : null;
      if (peerId) {
        const group = groups.get(peerId), h = ["LR", "RL"].includes(group.direction);
        if ((h ? "x" : "y") === axis) {
          const peers = group.children.map((id) => boxes.get(id));
          const size = axis === "x" ? "width" : "height";
          const middle = (Math.min(...peers.map((n) => n[axis])) + Math.max(...peers.map((n) => n[axis] + n[size]))) / 2;
          return members.has(insideId) && parent.get(insideId) === peerId
            ? center(outside, axis) - middle : middle - center(inside, axis);
        }
      }
    }
    const edge = feedback?.edges.find(
      (edge) => edge.data.from === e.from && edge.data.to === e.to,
    );
    if (edge) {
      const runs = edge.points
        .slice(1)
        .map((b, i) => ({
          a: edge.points[i],
          b,
          length: Math.hypot(b.x - edge.points[i].x, b.y - edge.points[i].y),
        }))
        .filter((r) => Math.abs(r.a[axis] - r.b[axis]) < 0.01)
        .sort((a, b) => b.length - a.length);
      if (runs.length) {
        const end = insideId === e.from ? edge.points[0] : edge.points.at(-1);
        return (
          runs[0].a[axis] +
          outside[axis] -
          priorNodes.get(outsideId)[axis] -
          end[axis] -
          inside[axis] +
          priorNodes.get(insideId)[axis]
        );
      }
    }
    return center(outside, axis) - center(inside, axis);
  }
  const original = new Map(
    [...boxes].map(([id, r]) => [id, { x: r.x, y: r.y }]),
  );
  for (let pass = 0; pass < 2; pass++)
    for (const id of order) {
      const item = boxes.get(id),
        parentId = parent.get(id),
        p = boxes.get(parentId);
      const direction =
        parentId === "@root" ? flow.direction : groups.get(parentId).direction;
      const axis = ["LR", "RL"].includes(direction) ? "y" : "x",
        size = axis === "x" ? "width" : "height";
      const pad = p.kind === "frame" ? 24 : 0,
        header = axis === "y" ? p.header : 0;
      let low = p[axis] + pad + header,
        high = p[axis] + p[size] - pad - item[size];
      // The outer canvas may grow for a short entry row. Large structural bands
      // and lane headings stay anchored to their common editorial margin.
      if (parentId === "@root") {
        if (item.kind === "lane" || item[size] > p[size] * 0.8) continue;
        const allowance = Math.min(320, p[size] * 0.25);
        low -= allowance;
        high += allowance;
      }
      if (
        high - low < 1 ||
        item.kind === "lane" ||
        p.kind === "frame" ||
        peerGroups.has(parentId)
      )
        continue;
      const members = descendants.get(id);
      const links = flow.edges
        .filter((e) => members.has(e.from) !== members.has(e.to))
        .filter((e) => {
          const a = boxes.get(e.from),
            b = boxes.get(e.to);
          return axis === "x"
            ? a.y + a.height <= b.y || b.y + b.height <= a.y
            : a.x + a.width <= b.x || b.x + b.width <= a.x;
        });
      if (!links.length) continue;
      const candidates = new Set([item[axis]]);
      for (const e of links) {
        candidates.add(
          Math.max(
            low,
            Math.min(high, item[axis] + desiredShift(e, members, axis)),
          ),
        );
      }
      const cost = (value) => {
        const shift = value - item[axis];
        let result = Math.abs(value - original.get(id)[axis]) * 0.08;
        for (const e of links) {
          const delta = Math.abs(shift - desiredShift(e, members, axis));
          const weight =
            (e.kind === "signal" ? 0.45 : 1) /
            Math.sqrt(degree.get(e.from) * degree.get(e.to));
          result +=
            weight * (Math.max(0, delta - 24) * 0.3 + (delta > 24 ? 100 : 0));
        }
        return result;
      };
      const best = [...candidates].sort((a, b) => cost(a) - cost(b))[0],
        shift = best - item[axis];
      if (Math.abs(shift) < 0.1) continue;
      for (const child of members) boxes.get(child)[axis] += shift;
    }
  const painted = [...graph.children, ...graph.groups];
  const dx = 64 - Math.min(...painted.map((r) => r.x)),
    dy = 64 - Math.min(...painted.map((r) => r.y));
  for (const [id, r] of boxes)
    if (id !== "@root") {
      r.x += dx;
      r.y += dy;
    }
  graph.width = Math.max(...painted.map((r) => r.x + r.width)) + 64;
  graph.height = Math.max(...painted.map((r) => r.y + r.height)) + 64;
}
