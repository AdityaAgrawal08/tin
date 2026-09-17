// Deliberately varied examples of the supported dialect. Review assets, never
// catalog entries or executable workflow definitions.
const node = (id, kind, label, fact = "") => ({ id, kind, label, fact });
const edge = (from, to, label = "", kind = "call") => ({ from, to, label, kind });
const chain = (nodes) => nodes.slice(1).map((item, i) => edge(nodes[i].id, item.id));
const example = (id, title, nodes, edges = chain(nodes)) => ({ id, title, flow: { nodes, edges } });

const examples = [
  example("minimal", "Short labels · one line", [node("go", "step", "Go"), node("ok", "receipt", "OK")]),
  example("vocabulary", "Every primitive · mixed line counts", [
    node("source", "store", "Project state", "durable evidence"), node("draft", "step", "Draft", "one bounded call"),
    node("review", "gate", "Needs you", "Approve the draft"), node("send", "surface", "Gmail"),
    node("wait", "wait", "Wait", "follow-up window"), node("receipt", "receipt", "Receipt", "sent · 12"),
    node("future", "ghost", "Future step", "not configured"),
  ]),
  example("wide", "Maximum text · wide glyphs", [
    node("source", "store", "WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW", "WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW"),
    node("check", "gate", "WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW", "WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW"),
    node("result", "receipt", "WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW", "WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW"),
  ]),
  example("narrow", "Maximum text · narrow glyphs", [
    node("source", "surface", "iiiiiiiiiiiiiiiiiiiiiiiiiiiiiiii", "llllllllllllllllllllllllllllllllllllllllllllllll"),
    node("check", "step", "iiiiiiiiiiiiiiiiiiiiiiiiiiiiiiii", "llllllllllllllllllllllllllllllllllllllllllllllll"),
    node("result", "ghost", "iiiiiiiiiiiiiiiiiiiiiiiiiiiiiiii", "llllllllllllllllllllllllllllllllllllllllllllllll"),
  ]),
  example("editorial", "Long readable copy · different type roles", [
    node("source", "store", "Customer research and evidence", "Read the latest interviews and project notes"),
    node("draft", "step", "Write the strongest answer", "One reviewed question and its supporting sources"),
    node("review", "gate", "Confirm the final draft", "The owner checks claims before delivery"),
    node("publish", "surface", "A reviewable website proposal", "The pull request stays open for your team"),
  ]),
  example("fan_out", "Three branches · merge into a receipt", [
    node("source", "store", "Project state", "shared context"), node("a", "step", "Research", "buyer questions"),
    node("b", "step", "Audit", "current visibility"), node("c", "surface", "Website", "public pages"),
    node("merge", "receipt", "Evidence ready", "three sources"),
  ], [edge("source", "a"), edge("source", "b"), edge("source", "c"), edge("a", "merge"), edge("b", "merge"), edge("c", "merge")]),
  example("fan_in", "Four inputs · one human decision", [
    node("a", "store", "Memory"), node("b", "surface", "Website", "live copy"),
    node("c", "receipt", "Prior audit", "complete"), node("d", "step", "Research", "new evidence"),
    node("review", "gate", "Needs you", "Choose a direction"), node("result", "receipt", "Decision recorded"),
  ], [edge("a", "review"), edge("b", "review"), edge("c", "review"), edge("d", "review"), edge("review", "result")]),
  example("revision", "Review loop · labeled return path", [
    node("draft", "step", "Draft", "bounded change"), node("review", "gate", "Needs you", "Review the draft"),
    node("ready", "receipt", "Approved", "ready to use"),
  ], [edge("draft", "review"), edge("review", "draft", "request changes", "signal"), edge("review", "ready", "approved")]),
  example("signals", "Waits · signals · alternate exits", [
    node("send", "surface", "Gmail", "paced initial sends"), node("wait", "wait", "Wait", "until the next send window"),
    node("reply", "receipt", "Reply received", "cancel follow-up"), node("follow", "step", "Follow up", "only without a reply"),
    node("done", "receipt", "Delivery ledger", "one receipt per touch"),
  ], [edge("send", "wait"), edge("send", "reply", "reply", "signal"), edge("wait", "follow", "timer", "signal"), edge("reply", "done"), edge("follow", "done")]),
  example("edge_labels", "Long connector labels · competing routes", [
    node("start", "step", "Start"), node("review", "gate", "Review", "Check the evidence"),
    node("wait", "wait", "Wait", "until the next eligible day"), node("done", "receipt", "Done"),
  ], [edge("start", "review", "all required evidence has been collected"), edge("review", "wait", "waiting for next eligible send window", "signal"),
    edge("review", "done", "owner approved the exact proposed change"), edge("wait", "start", "recheck current state before retrying", "signal")]),
  example("cycle", "Cycle · asymmetric node sizes", [
    node("a", "step", "Inspect"), node("b", "store", "Evidence", "durable project context"),
    node("c", "gate", "Review", "Approve or request another pass"),
  ], [edge("a", "b"), edge("b", "c"), edge("c", "a", "another pass", "signal")]),
  example("unicode", "Accents · combining marks · fallback scripts", [
    node("a", "step", "Crème brûlée · déjà vu", "naïve · façade · piñata"),
    node("b", "store", "Cafe\u0301 and re\u0301sume\u0301", "東京 · 顧客の調査と証拠"),
    node("c", "receipt", "完了 · Ready ✓", "🧪 evidence · 🚀 delivery"),
  ]),
  example("dense", "Eight nodes · twelve connectors", [
    node("a", "store", "Project state", "durable sources"), node("b", "step", "Research"), node("c", "surface", "Website"),
    node("d", "step", "Draft", "one bounded change"), node("e", "gate", "Needs you", "Check the claims"),
    node("f", "wait", "Wait", "until approved"), node("g", "receipt", "Delivered", "one effect"), node("h", "ghost", "Later", "not configured"),
  ], [edge("a", "b"), edge("a", "c"), edge("b", "d"), edge("c", "d"), edge("b", "e"), edge("d", "e"),
    edge("e", "d", "revise", "signal"), edge("e", "f"), edge("e", "g", "approve"), edge("f", "g", "ready", "signal"), edge("g", "h"), edge("c", "h", "later", "signal")]),
  example("long_chain", "Eight steps · alternating one and two lines", Array.from({ length: 8 }, (_, i) =>
    node(`n${i}`, ["step", "surface", "store", "gate", "wait", "step", "receipt", "ghost"][i],
      ["Inspect", "Website", "Context", "Needs you", "Wait", "Verify", "Receipt", "Later"][i], i % 2 ? "supporting detail" : ""))),
];

export const diagramFixtures = examples.flatMap((item) => ["LR", "TD"].map((direction) => ({
  id: `${item.id}-${direction.toLowerCase()}`, title: `${item.title} · ${direction}`,
  flow: { ...item.flow, direction },
})));
