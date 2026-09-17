// Same facts under different arrangements; no executable workflow semantics.
const nodes = ["creating", "running", "stopping", "snapshotting", "stopped", "forked", "deleted"]
  .map((id) => ({ id, kind: "step", label: id[0].toUpperCase() + id.slice(1) }));
const edges = [
  ["creating", "running"], ["running", "stopping", "Stop or deadline"],
  ["running", "snapshotting", "Snapshot"], ["stopping", "snapshotting"],
  ["snapshotting", "stopped"], ["stopped", "creating", "Resume"],
  ["stopped", "forked", "Fork"], ["forked", "creating"],
  ["running", "deleted", "Delete"], ["stopped", "deleted", "Delete"],
].map(([from, to, label]) => ({ from, to, kind: "call", ...(label ? { label } : {}) }));
export const designerFixtures = [
  { id: "designer-lifecycle-flat", title: "Designer lifecycle · flat", flow: { direction: "TD", nodes, edges } },
  { id: "designer-lifecycle-composed", title: "Designer lifecycle · ordered column", flow: {
    direction: "TD", nodes, edges, layout: ["lifecycle"],
    groups: [{ id: "lifecycle", kind: "layout", direction: "TD", children: nodes.map((n) => n.id) }],
  } },
  ...["LR", "RL", "TD", "BT"].map((direction) => ({
    id: `designer-peers-${direction.toLowerCase()}`,
    title: `Equivalent branches with unequal cards · ${direction}`,
    flow: {
      direction: ["LR", "RL"].includes(direction) ? "TD" : "LR",
      nodes: [
        { id: "request", kind: "step", label: "Request" },
        { id: "short", kind: "step", label: "Check" },
        { id: "long", kind: "step", label: "Read the durable project evidence", fact: "Use the pinned revision. This peer needs a longer explanation and a larger measured card." },
        { id: "medium", kind: "step", label: "Verify constraints", fact: "Membership and revision" },
        { id: "finish", kind: "receipt", label: "Collected evidence" },
      ],
      layout: ["request", "peers", "finish"],
      groups: [{ id: "peers", kind: "layout", direction, children: ["short", "long", "medium"] }],
      edges: ["short", "long", "medium"].flatMap((id) => [
        { from: "request", to: id, kind: "call" }, { from: id, to: "finish", kind: "call" },
      ]),
    },
  })),
  { id: "designer-continuous-loop", title: "An ongoing loop has no invented terminal", flow: {
    direction: "LR", nodes: nodes.slice(0, 3), layout: ["cycle"],
    groups: [{ id: "cycle", kind: "layout", direction: "LR", children: nodes.slice(0, 3).map((n) => n.id) }],
    edges: [{ from: "creating", to: "running", kind: "call" }, { from: "running", to: "stopping", kind: "call" }, { from: "stopping", to: "creating", kind: "signal", label: "Continue next cycle" }],
  } },
];
