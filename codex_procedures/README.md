# Codex procedures

Each directory here is the source package for one registry workflow executed by the explicit
`codex.procedure` Temporal implementation. A package contains:

```text
<workflow>/
├── PROMPT.md
└── skills/
    └── <entry-skill>/
        ├── SKILL.md
        └── optional text resources
```

The corresponding `BuiltinWorkflow` declares the entry skill, one Markdown output path, its byte
limit, and any exact project-skill dependencies. Catalog synchronization publishes the definition,
prompt, and declared skill files atomically to `registry/workflows`; runs never read this mutable
source tree directly.

Project-specific skills do not belong here. They remain in each project's code.storage state at
`.agents/skills/<name>/SKILL.md` and are made available only when the immutable procedure contract
declares them.
