export class RoutingError extends Error {}
export const inflate = (r, n) => ({
  x: r.x - n,
  y: r.y - n,
  width: r.width + 2 * n,
  height: r.height + 2 * n,
});
export const overlaps = (a, b, gap = 0) =>
  a.x < b.x + b.width + gap &&
  a.x + a.width + gap > b.x &&
  a.y < b.y + b.height + gap &&
  a.y + a.height + gap > b.y;
export function hits(a, b, r) {
  if (Math.abs(a.x - b.x) < 0.01)
    return (
      a.x > r.x &&
      a.x < r.x + r.width &&
      Math.max(a.y, b.y) > r.y &&
      Math.min(a.y, b.y) < r.y + r.height
    );
  return (
    a.y > r.y &&
    a.y < r.y + r.height &&
    Math.max(a.x, b.x) > r.x &&
    Math.min(a.x, b.x) < r.x + r.width
  );
}
export function simplify(points) {
  const result = [];
  for (const p of points) {
    const previous = result.at(-1);
    if (previous && Math.hypot(p.x - previous.x, p.y - previous.y) < 0.01)
      continue;
    const before = result.at(-2);
    if (
      before &&
      ((Math.abs(before.x - previous.x) < 0.01 &&
        Math.abs(previous.x - p.x) < 0.01 &&
        (previous.y - before.y) * (p.y - previous.y) >= 0) ||
        (Math.abs(before.y - previous.y) < 0.01 &&
          Math.abs(previous.y - p.y) < 0.01 &&
          (previous.x - before.x) * (p.x - previous.x) >= 0))
    )
      result.pop();
    result.push(p);
  }
  return result;
}
export const segments = (points) =>
  points.slice(1).map((b, i) => [points[i], b]);
export function routeQuality(graph) {
  let cost = 0;
  for (const e of graph.edges) {
    cost += (e.points.length - 2) * 28;
    for (const [i, [a, b]] of segments(e.points).entries()) {
      const length = Math.abs(a.x - b.x) + Math.abs(a.y - b.y);
      cost += length * 0.012;
      if (i > 0 && i < e.points.length - 2 && length < 16)
        cost += 300 + (16 - length) * 10;
      if ((i === 0 || i === e.points.length - 2) && length < 24) cost += 150;
    }
  }
  for (let i = 0; i < graph.edges.length; i++)
    for (let j = i + 1; j < graph.edges.length; j++) {
      for (const [a, b] of segments(graph.edges[i].points))
        for (const [c, d] of segments(graph.edges[j].points)) {
          const h = a.y === b.y,
            k = c.y === d.y;
          if (h === k) continue;
          const [u, v, w, z] = h ? [a, b, c, d] : [c, d, a, b];
          if (
            w.x > Math.min(u.x, v.x) &&
            w.x < Math.max(u.x, v.x) &&
            u.y > Math.min(w.y, z.y) &&
            u.y < Math.max(w.y, z.y)
          )
            cost += 60;
        }
    }
  return cost + graph.width * graph.height * 0.00003;
}
