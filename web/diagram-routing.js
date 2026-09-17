import { AvoidLib } from "libavoid-js";
import { planPorts } from "./diagram-ports.js";
import {
  RoutingError,
  hits,
  inflate,
  segments,
  simplify,
} from "./diagram-geometry.js";

// Capture the bundle's location while its script is executing. Exports remain
// standalone SVG; only composed source rendering loads this replaceable WASM.
const bundleUrl =
  typeof document !== "undefined"
    ? new URL(document.currentScript?.src || document.baseURI)
    : undefined;
const wasmUrl = bundleUrl
  ? new URL(`diagram-routing.wasm${bundleUrl.search}`, bundleUrl).href
  : undefined;
let ready;
async function kernel() {
  ready ||= AvoidLib.load(wasmUrl)
    .then(() => AvoidLib.getInstance())
    .catch((error) => {
      ready = undefined;
      throw error;
    });
  return ready;
}

export async function createRouter(
  graph,
  flow,
  headers,
  frames = [],
  providedPlans,
) {
  const A = await kernel();
  const router = new A.Router(A.RouterFlag.OrthogonalRouting.value);
  const transient = [];
  const hold = (o) => (transient.push(o), o);
  try {
    for (const [key, value] of [
      ["segmentPenalty", 100],
      ["shapeBufferDistance", 24],
      ["idealNudgingDistance", 16],
    ])
      router.setRoutingParameter(A.RoutingParameter[key], value);
    const shapes = new Map();
    let shapeId = 1;
    function shape(r) {
      const a = hold(new A.Point(r.x, r.y)),
        b = hold(new A.Point(r.x + r.width, r.y + r.height));
      return new A.ShapeRef(router, hold(new A.Rectangle(a, b)), shapeId++);
    }
    const contains = (outer, inner) =>
      inner.x >= outer.x &&
      inner.y >= outer.y &&
      inner.x + inner.width <= outer.x + outer.width &&
      inner.y + inner.height <= outer.y + outer.height;
    const boundaries = frames.filter(
      (f) => !frames.some((other) => other !== f && contains(other, f)),
    );
    // Route around the outer boundary as one obstacle. Redundant nested shapes
    // confuse libavoid's overlapping-shape visibility calculation.
    const covered = (r) => boundaries.some((f) => contains(f, r));
    for (const n of graph.children) if (!covered(n)) shapes.set(n.id, shape(n));
    for (const r of [...headers.filter((h) => !covered(h)), ...boundaries])
      shape(r);
    const boxes = new Map(graph.children.map((n) => [n.id, n]));
    const plans = providedPlans || planPorts(graph, flow, headers);
    const refs = plans.map((plan, index) => {
      const { data: e, start, end, fromDir, toDir } = plan;
      const a = boxes.get(e.from),
        b = boxes.get(e.to),
        classId = index + 1;
      new A.ShapeConnectionPin(
        shapes.get(e.from),
        classId * 2,
        (start.x - a.x) / a.width,
        (start.y - a.y) / a.height,
        true,
        0,
        fromDir,
      );
      new A.ShapeConnectionPin(
        shapes.get(e.to),
        classId * 2 + 1,
        (end.x - b.x) / b.width,
        (end.y - b.y) / b.height,
        true,
        0,
        toDir,
      );
      const src = hold(new A.ConnEnd(shapes.get(e.from), classId * 2)),
        dst = hold(new A.ConnEnd(shapes.get(e.to), classId * 2 + 1));
      return {
        id: plan.id,
        data: e,
        ref: new A.ConnRef(router, src, dst, 1000 + index),
      };
    });
    // These inputs are copied by libavoid. Router owns shapes, pins and connectors.
    for (const value of transient.splice(0).reverse()) value.delete();
    return {
      plans,
      routes() {
        router.processTransaction();
        return refs.map(({ id, data, ref }) => {
          const route = ref.displayRoute(); // Borrowed from its connector.
          // Polygon.at() returns a borrowed Point reference too; copy coordinates only.
          const points = simplify(
            Array.from({ length: route.size() }, (_, i) => {
              const p = route.at(i);
              return { x: p.x, y: p.y };
            }),
          );
          if (
            points.length < 2 ||
            points.some(
              (p) => !Number.isFinite(p.x) || !Number.isFinite(p.y),
            ) ||
            segments(points).some(
              ([a, b]) =>
                Math.abs(a.x - b.x) > 0.01 && Math.abs(a.y - b.y) > 0.01,
            )
          )
            throw new RoutingError(
              `Invalid orthogonal route: ${data.from} → ${data.to} ${JSON.stringify(points)}`,
            );
          for (const n of graph.children)
            if (segments(points).some(([a, b]) => hits(a, b, inflate(n, -0.1))))
              throw new RoutingError(
                `Connector intersects ${n.id}: ${data.from} → ${data.to}`,
              );
          for (const h of headers)
            if (segments(points).some(([a, b]) => hits(a, b, h)))
              throw new RoutingError(
                `Connector intersects a group title: ${data.from} → ${data.to}`,
              );
          return { id, data, points, labels: [] };
        });
      },
      checkpoint(index, points) {
        const vector = new A.CheckpointVector();
        try {
          for (const p of points) {
            const point = new A.Point(p.x, p.y),
              check = new A.Checkpoint(point);
            vector.push_back(check);
            check.delete();
            point.delete();
          }
          refs
            .find((e) => e.id === `@edge:${index}`)
            .ref.setRoutingCheckpoints(vector);
        } finally {
          vector.delete();
        }
      },
      dispose() {
        router.delete();
      },
    };
  } catch (error) {
    for (const value of transient.reverse()) value.delete();
    router.delete();
    throw error;
  }
}
