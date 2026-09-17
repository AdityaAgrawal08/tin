import { hits, inflate, overlaps, segments } from "./diagram-geometry.js";

export function placeLabels(graph, labelBlocks, headers) {
  const placed = [];
  const ports = graph.edges.flatMap((e) =>
    [e.points[0], e.points.at(-1)].map((p) => ({
      x: p.x - 22,
      y: p.y - 22,
      width: 44,
      height: 44,
    })),
  );
  const obstacles = [
    ...graph.children.map((n) => inflate(n, 10)),
    ...headers.map((h) => inflate(h, 8)),
    ...ports,
  ];
  const order = graph.edges
    .filter((e) => e.data.label)
    .sort((a, b) => labelBlocks.get(b.id).width - labelBlocks.get(a.id).width);
  for (const edge of order) {
    const block = labelBlocks.get(edge.id),
      width = block.width + 20,
      height = block.height + 12;
    const candidates = [];
    for (const [a, b] of segments(edge.points)) {
      const horizontal = Math.abs(a.y - b.y) < 0.01,
        length = Math.abs(a.x - b.x) + Math.abs(a.y - b.y);
      if (length < (horizontal ? width : height) + 24) continue;
      const fractions = [0.5, 0.35, 0.65, 0.2, 0.8];
      for (const f of fractions) {
        const x = a.x + (b.x - a.x) * f - width / 2,
          y = a.y + (b.y - a.y) * f - height / 2;
        const rank = (horizontal ? 0 : 30) + Math.abs(f - 0.5) * 10;
        candidates.push({ x, y, width, height, rank });
        if (horizontal)
          candidates.push(
            { x, y: y - height / 2 - 8, width, height, rank: rank + 10 },
            { x, y: y + height / 2 + 8, width, height, rank: rank + 10 },
          );
        else
          candidates.push(
            { x: x - width / 2 - 8, y, width, height, rank: rank + 10 },
            { x: x + width / 2 + 8, y, width, height, rank: rank + 10 },
          );
      }
    }
    const chosen = candidates
      .sort((a, b) => a.rank - b.rank)
      .find(
        (r) =>
          ![...obstacles, ...placed.map((p) => inflate(p, 8))].some((o) =>
            overlaps(r, o),
          ) &&
          !graph.edges.some(
            (other) =>
              other !== edge &&
              segments(other.points).some(([a, b]) =>
                hits(a, b, inflate(r, 6)),
              ),
          ),
      );
    if (!chosen) return edge;
    const { rank, ...rect } = chosen;
    edge.labels = [{ ...rect, text: edge.data.label }];
    placed.push(rect);
  }
  return null;
}
