# Contributed workflow packages

This folder holds contributed **text-only Codex procedure packages** in the format Tin
already runs. CI validates every package without executing its instructions. Merging one
does not register, activate, schedule or run it, or make it available to other projects.

For the built-in workflows and how a catalog entry works, read
[Adding a workflow](../docs/adding-a-workflow.md).
Deterministic code workflows and code workflows with managed model steps use the separate
[code workflow](../docs/code-workflows.md) and [managed model](../docs/code-model-workflows.md)
contracts; this contribution lane does not accept uploaded Python or shell implementations.

## What a procedure contributes

A workflow is a job a founder would hand to someone: find the thing, write the thing, check the
thing. Here, you describe that job and its method for a bounded Codex run. Other Tin workflows
can be deterministic or use explicit model steps; not every workflow is an agent session.
Private trials of these procedure packages are manual, not scheduled.

## The files

```text
workflow_packages/<your.workflow_key>/
├── workflow.json    the contract: inputs, output, which skill to start from
├── PROMPT.md        what the run is asked to do, and what it must not do
└── skills/
    └── <entry-skill>/
        └── SKILL.md the method, in the ordinary skill format
```

The key uses a family and a name, like `growth.reddit_teardown`. The folder name and the `key`
in the manifest have to match. A skill's `name` has to match its own folder name.

Skills may carry extra text beside `SKILL.md`, as `.md`, `.json`, `.txt`, `.yaml` or `.yml`.
List every one of them in `skill_files`. Contributed packages hold text a reviewer can read, so
they do not carry `.py` or `.sh`.

## The manifest

This one validates. Copy it and change the parts that describe your workflow.

```json
{
  "package_format": "tin-workflow-package-v1",
  "definition": {
    "key": "growth.example_play",
    "title": "Name the workflow the way a founder would say it",
    "description": "One sentence: who runs this, and what they have at the end.",
    "executor": "codex.procedure",
    "version": "1.0.0",
    "schedule_modes": ["on_demand"],
    "input_schema": {
      "type": "object",
      "additionalProperties": false,
      "required": ["project_id"],
      "properties": {
        "project_id": { "type": "string", "format": "uuid" },
        "focus": {
          "type": "string",
          "title": "What to look at",
          "maxLength": 2000,
          "default": "",
          "x-tin-ui": { "control": "textarea", "order": 10 }
        }
      }
    },
    "procedure": {
      "prompt_path": "PROMPT.md",
      "skills_path": "skills",
      "skill_files": ["skills/example-play/SKILL.md"],
      "entry_skill": "example-play",
      "workspace": { "kind": "project.state" },
      "sandbox": { "profile": "isolated", "egress": "fenced", "timeout_seconds": 900 },
      "output": {
        "kind": "project.artifact",
        "path": "reports/EXAMPLE_PLAY.md",
        "media_type": "text/markdown",
        "max_bytes": 250000
      }
    }
  }
}
```

Every text input needs a `maxLength`, every array a `maxItems`, and `project_id` stays as it is.
A package declares one output: either a file in the project, as above, or a GitHub pull request.

For a complete minimal example, save this as `PROMPT.md`:

```markdown
Read the project context and the optional focus input. Follow the example-play skill and
write reports/EXAMPLE_PLAY.md. Do not publish, send messages or change other files.
```

Save this as `skills/example-play/SKILL.md`:

```markdown
---
name: example-play
description: Identify one useful next action from existing project evidence.
---

Read relevant project files. Recommend one concrete next action, cite the project paths
that support it, and distinguish evidence from assumptions. If context is insufficient,
explain what is missing instead of inventing facts. Write only the declared report.
```

## Check your work

```bash
uv python install 3.12
uv sync --frozen
uv run tin-lite validate-community
```

It names the package, the check that failed and where to fix it. CI runs the same command on
your pull request. `--root /path/to/checkout` selects another checkout (not its package folder).
Missing manifests, symlinks and invalid roots fail the check; a README-only folder passes.
Validation checks the contract and resources, not the quality or safety of executing instructions.

## Try it on a project

Use a project you are authorized to test. Ask its coding agent for
`get_workflow_authoring_guide(project_id)` first: private execution must be operator-enabled.
Normal run billing and integration requirements still apply; validation and activation do not
purchase a model run.

1. Copy the three example files into a **project-local copy** under
   `workflow_packages/custom.example_play/`. Change the manifest key to `custom.example_play`
   to match that folder. Keep `on_demand` and the explicit isolated, fenced sandbox above.
   Leave the contributed source package unchanged.
2. Use `list_project_files` and `commit_project_changes` through MCP to save the copy in project
   Files against the current project revision. Keep the returned commit SHA.
3. Call `validate_workflow_package(project_id, path, revision)` with
   `path: workflow_packages/custom.example_play/workflow.json` and that exact SHA. Resolve
   diagnostics before continuing. Other contributions may need further adaptations to meet
   [private activation policy](../docs/private-workflow-activation.md); a passing contribution
   check alone does not guarantee private activation.
4. Explicitly call `activate_workflow_package` with the same project, path and revision,
   a fresh UUID `request_id`, and `expected_revision: null` for a new workflow. For updates,
   use its currently activated revision instead. Activation does **not** run the workflow.
5. Inspect the returned workflow using `get_workflow`, then explicitly `start_workflow` if you
   want to execute it. Read `reports/EXAMPLE_PLAY.md` from the resulting run. Review the actual
   output before recommending the package; successful validation is not an execution test.

There is no automatic import, public activation or catalog promotion in this contribution lane.

## What we look for

A workflow a founder would want to run, rather than a summary of marketing advice. Say where
the insight came from. If you ran it yourself, say what happened.

## What happens next

A maintainer reads it. Merging a package puts it in this folder, where an operator can read it
and try it on a project. Workflows that earn it become built-in ones later, which needs a
catalog entry we write.
