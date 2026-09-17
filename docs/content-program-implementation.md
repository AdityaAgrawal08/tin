# Amendable content programs

Contributor reference for `content.plan`, its durable program and amendment contract.

## ELI5

Choose an audit and keyword research. Tin proposes a roadmap for two weeks to
six months. It lives in Files and stays in My system. Each week Tin prepares the
next batch; it does not publish anything. Edit future topics yourself, or ask
Tin for a revision and review it before applying. Prepared work keeps its copy.

## Contract

- Native `content.plan`, ordinary runs, saved `project_workflows`, Temporal
  Schedule. No new engine, node graph, or executable system taxonomy.
- Default six calendar months, minimum two weeks, explicit fixed start/end dates.
  Dates and research are pinned from the first run, including while it is active.
  Weekly planning cadence and batch capacity are independent. Capacity is a
  ceiling, not a quota. No claim that Google penalizes publication volume.
- One editable `content/plans/{project_workflow_id}/plan.json`. Markdown reports
  are immutable run receipts, not a competing editable plan. Stable batch/item IDs.
- First run builds the full roadmap. Later ticks prepare one earliest due,
  unprepared batch against an exact file revision. No automatic model call,
  audit rerun, keyword purchase, article generation, or publication on a tick.
  Empty batches are valid. Catch-up never drains the entire backlog at once.
- Successful audit and keyword publications must match project, host, market,
  English language, original revisions and receipt hashes. Never substitute HEAD.
- This slice uses frozen evidence plus selected project files, with no fresh
  page crawl. Existing-page candidates are hypotheses. Fresh page inspection,
  factual verification and capability confirmation remain prerequisites before
  generation. Groups/exclusions are fallible, unknown demand is not zero, and
  unsupported capabilities or fabricated claims must not become briefs.
- One bounded, receipted structured model call per initial plan or requested AI
  revision. Deterministic validation/rendering. No paid repair loop; uncertain
  provider acceptance is not repurchased. Planner spending is separately disabled
  until configured. Weekly preparation uses no provider calls.

## Amendments and concurrency

Files own editable content. Postgres owns program/pending-revision facts and
batch reservations with immutable source references. Program operations share a
lock. Reserve the stable batch/item IDs and exact source revision before publishing;
manual, scheduled and retry executions cannot prepare the same batch twice.

Direct UI/MCP edits use ordinary project-file commits with stable request IDs and
expected HEAD. The editor exposes only future batches. Files stays format-agnostic:
invalid external edits fail preparation visibly, never fall back to the old plan.
Reserved item IDs cannot reappear in future batches. Prepared snapshots remain
authoritative even if the working file's old sections are subsequently edited.

An AI amendment is a normal `content.plan` run bound to a durable request. Before
calling the model, pin the base revision, selected future batch IDs and selected
project-file references. Hold those batches. Validate that only that scope changed.
Publish an immutable preview and finish the run; no 24-hour dispatcher is held
open for weeks awaiting approval. Apply/Discard are separate authenticated,
idempotent actions. Apply requires the exact preview, an unchanged base plan,
and the current HEAD the reviewer inspected. The preview's own report commit can
advance HEAD without invalidating its unchanged plan. Concurrent edits still fail
the final compare-and-swap. Discard clears the hold, including failed previews.

## Dashboard and MCP

Registry setup uses real successful research-run selectors, dates/duration,
capacity and optional project-file selection, not raw UUIDs. Save and run creates
the persistent My system configuration. Expanded card:

1. Upcoming work: one batch selector, compact topic title/brief/action/destination
   fields, add/move/defer/remove, and Open full plan.
2. Ask for revision: instructions, next/selected/all remaining scope, file picker
   with removable chips. Preview, then Apply or Discard.
3. Secondary schedule/capacity controls using existing light/dark design tokens.

Explain: “Applies to batches that haven't started. Prepared batches remain
unchanged.” Show pending holds, invalid files, stale edits and program completion.
No fake generation button. Operational polling reads Postgres; opening the editor
explicitly loads the versioned file. HTTP/MCP share services and membership checks.

## Delivery and verification

1. Pure contracts, finite schedules, source validation and deterministic tests.
2. Native planner and batch preparation, retry-safe reservations/publication,
   exact pinned registry contract, safe failure/stop behavior.
3. Direct edits and reviewed AI revisions with HTTP/MCP parity.
4. Narrow My system adapter and accessible source/file pickers.
5. Isolated Postgres, mocked providers, race/retry/stale/malformed-file tests,
   Temporal tests, full Python and browser checks.
6. Validate additive migration on a development branch before production apply.
   Preserve live secrets and unrelated agents' work. Deploy verified code without
   implicitly enabling a paid run or a six-month production schedule.

[Temporal ScheduleSpec](https://python.temporal.io/temporalio.client.ScheduleSpec.html)
supports finite bounds. [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
constrains output shape; application validation remains necessary.

## Verification and operational limits

The implementation has passed isolated Postgres publication/retry, held-scope/apply/discard,
stale/malformed/missing-file, duplicate file-write, funding and unknown-model tests. A local
Temporal retry/replay carries only the run ID. HTTP and MCP exercise the same edit service
with denied-membership tests. Chromium covers editing, prepared receipts and reviewed previews
in light/dark mode and at phone width. Existing diagram/comparison checks remain green.
