// Composition regressions beyond the seven editorial reference studies.
import { parseSource } from "./diagram-contract.js";
import { designerFixtures } from "./diagram-designer-fixtures.js";

const step = (id, label = id) => ({ id, kind: "step", label });
const targetIds = Array.from({ length: 31 }, (_, i) => `target_${i}`);
// The README's branching run: projection → choice → review → effect should
// share a visual axis despite differently sized nodes and a side outcome.
const reviewChain = parseSource(`graph TD
  %% tin:composition
  subgraph start
    direction LR
    %% tin:group layout
    trigger["Trigger<br/>You · a schedule · your coding agent over MCP"]:::step
    switchboard["Switchboard<br/>Check project membership · pin the workflow revision · start a Temporal run"]:::step
  end
  subgraph context
    direction RL
    %% tin:group layout
    reads["Reads<br/>Project files and memory · system wiki at a pinned commit · connected data through typed adapters"]:::step
    executor["Executor"]:::step
  end
  subgraph execution
    direction LR
    %% tin:group layout
    trusted["Trusted step<br/>On the switchboard"]:::surface
    sandbox["One sandbox<br/>Created for this run · destroyed when it ends"]:::surface
  end
  subgraph publication
    direction LR
    %% tin:group layout
    commit["One commit<br/>To the project repository"]:::receipt
    projection[("Postgres projection<br/>Run status · Activity · Files · memory")]:::store
  end
  whose["Whose call?"]:::step
  subgraph outcomes
    direction LR
    %% tin:group layout
    done["Done<br/>The next run reads this output"]:::receipt
    subgraph review
      direction TD
      %% tin:group layout
      decisions["Decisions<br/>Read it · approve or not now"]:::gate
      effect["Effect leaves the machine<br/>Pull request · email · published artifact"]:::receipt
    end
  end
  trigger --> switchboard
  switchboard --> reads
  reads --> executor
  executor -->|procedure| sandbox
  executor -->|text workflow| trusted
  trusted --> commit
  sandbox --> commit
  commit --> projection
  projection --> whose
  whose -->|Tin's| done
  whose -->|yours| decisions
  decisions -->|approved| effect
`);
export const routingFixtures = [
  ...designerFixtures,
  {
    id: "composed-review-chain",
    title: "A continuous review chain with a side outcome",
    flow: reviewChain,
  },
  {
    id: "composed-fan-out",
    title: "A coordinator with 31 destinations",
    flow: {
      direction: "LR",
      nodes: [
        step("hub", "Coordinator"),
        ...targetIds.map((id, i) => step(id, `Replica ${i + 1}`)),
      ],
      groups: [
        { id: "targets", kind: "layout", direction: "TD", children: targetIds },
      ],
      layout: ["hub", "targets"],
      edges: targetIds.map((to) => ({ from: "hub", to, kind: "call" })),
    },
  },
  {
    id: "composed-foreign-frame",
    title: "Connections around an unrelated nested frame",
    flow: {
      direction: "LR",
      nodes: [
        step("source", "Request"),
        step("unrelated", "Other work"),
        step("waiting", "Pending"),
        step("target", "Result"),
      ],
      groups: [
        {
          id: "boundary",
          label: "Independent workspace",
          kind: "frame",
          direction: "TD",
          children: ["nested"],
        },
        {
          id: "nested",
          label: "Separate ownership",
          kind: "frame",
          direction: "BT",
          children: ["unrelated", "waiting"],
        },
      ],
      layout: ["source", "boundary", "target"],
      edges: [
        { from: "source", to: "target", kind: "call", label: "request" },
        {
          from: "target",
          to: "source",
          kind: "signal",
          label: "return the result",
        },
        { from: "waiting", to: "unrelated", kind: "call" },
      ],
    },
  },
];
