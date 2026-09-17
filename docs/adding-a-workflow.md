# Adding a workflow

A Codex procedure combines a prompt and skills with a workflow contract. The skills use the ordinary `SKILL.md` format.

## The shape

A procedure workflow is a directory:

```text
codex_procedures/<workflow>/
├── PROMPT.md              what the run is asked to do, and what it must not do
└── skills/
    └── <entry-skill>/
        ├── SKILL.md       the same format Claude Code and Codex already load
        └── resources      optional text the skill refers to
```

The contract is one catalog entry in `src/tin_lite/catalog.py`: the workflow key, typed inputs as a JSON schema, allowed outputs and their size limits, which steps are yours to decide, the integrations it needs with their exact capabilities, and optionally a small diagram of its steps for the setup panel.

Catalog sync publishes the definition, prompt, and skill files as one immutable revision. A run reads only the revision it pinned, so editing a skill never changes a run that already started.

Text workflows that need no sandbox use the same skill format under `workflow_skills/<workflow>/`, as ordered packages a trusted step reads in sequence.

## What the contract gives you

Registering a supported workflow makes it available through the normal catalog and run services. The definition controls which inputs and outputs it accepts, which integrations it can call, whether it supports scheduling, and whether the result requires approval. Registration alone does not enable missing provider access or execution settings.

## Project-owned skills

Skills that belong to one project, not to a workflow, live in that project's repository at `.agents/skills/<name>/SKILL.md`. A workflow loads the skills it declares. These declarations control context selection, not permissions between members of the same project. Brand voice, a client's standing rules, and a house style belong here.

## Today

Built-in procedures are contributed through this repository. There is also an operator-enabled pilot for private packages stored in project Files:

```text
workflow_packages/custom.research_digest/
├── workflow.json
├── PROMPT.md
└── skills/research-digest/SKILL.md
```

Use `get_workflow_authoring_guide` over MCP for the supported contract. Commit the package to project Files, validate that exact revision, and explicitly activate it. Editing a file does not activate it. Existing runs and saved configurations keep their selected version.

The pilot supports on-demand isolated procedures that produce a project artifact or an unmerged GitHub PR. It also supports [bounded Python workflows](code-workflows.md), with optional [managed model steps](code-model-workflows.md), [project API connections](project-api-connections.md), and [eligible daily/weekly schedules](code-workflow-schedules.md). Code workflows produce a bounded text artifact; private procedure schedules and arbitrary native executors are not supported. Projects must still be enabled by the operator. See [feature status](feature-status.md) for rollout and billing boundaries.
