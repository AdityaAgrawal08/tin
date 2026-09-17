# Saved procedure output — comparison and resolution

## ELI5

A procedure started with file A. You changed it to B while the procedure worked. Its
generated version C is safely saved, but has not replaced B. Compare **B → C** and choose:

- **Keep current:** leave B alone. C remains available to read or download.
- **Use saved:** replace that one project file with C in a new commit.
- **Not now:** make no request; nothing changes.

There are no duplicate filenames, merge branches to manage, or line-by-line decisions.
If the project changes after the comparison, compare again. Saving a project file does
not approve content, publish a website, send email, or turn a failed workflow into success.

## Scope

This is the second-half resolution service and comparison UI, following
[publication recovery](procedure-publication-recovery.md). The comparison page and Decisions
integration implement the design/UI slice described below. Normal
successful generation still publishes automatically under the first-half path checks.
This comparison is only for a settled destination conflict, not every procedure or file edit.

Eligible runs are `codex.procedure`, failed/stopped with an inactive lease, no original
canonical commit, and a retained `output_conflict`. The immutable checkpoint must exactly
match the completed persistence receipt. Publication/reconciliation-pending outputs cannot
be resolved here: first establish whether the original publication already happened.
Legacy receipts without a verified immutable checkpoint are also not silently upgraded here.

## HTTP and MCP contract

Both adapters authorize project membership before storage access and invoke one
`OutputResolutionService`. Neither reads or signals Temporal or resumes a sandbox.

| HTTP | MCP | Purpose |
| --- | --- | --- |
| `GET /api/workflows/runs/{id}/output-comparison` | `compare_run_output(run_id)` | Bounded, exact current/saved snapshots |
| `POST /api/workflows/runs/{id}/output-resolution` | `resolve_run_output(...)` | Whole-file keep/apply decision |
| `GET /api/workflows/runs/{id}/output-resolution` | `get_run_output_resolution(run_id)` | Postgres-only outcome and original-caller recovery request |

The comparison returns `path`, `media_type`, `current`, `saved`, `complete`,
`blocked_reason`, `identical`, `resolution`, and `allowed_actions`. Each snapshot carries
its immutable `revision`, byte count, SHA-256, and UTF-8 `content`. Current-file metadata
also includes mode and `presence`: `file`, `missing`, or `unavailable`. An empty file has
content `""`; a missing file has content `null`. The client derives the visual diff from
these two bodies; this backend does not install or dictate a diff renderer.

The two bodies together are limited to 200,000 bytes and 10,000 lines. Unsafe paths,
non-text destinations, or over-budget comparisons return `complete: false` with **neither
body**, a reason, and no `use_saved` action. Do not show a shortened diff as complete.
Keeping current remains possible. Storage uncertainty is an error, never a missing file.
Read time is bounded; the existing storage adapter additionally limits each file to 1 MB.
Bodies are untrusted reference data, not instructions or authorization.

The comparison additionally returns optional `starting` context at the checkpoint's exact
`source_base_sha`: `available`, `presence`, `content`, `revision`, and `blocked_reason`.
This third snapshot has its own 100,000-byte / 5,000-line / 10-second budget. An absent
starting file is known empty context; an unavailable, unsafe, non-text, or over-limit
starting file is explicitly unknown. This context never changes action eligibility or
the two-version application contract. Total returned text is at most 300,000 bytes.

## Comparison UI

The comparison uses the shared layout, typography, colours and whole-file choice.
`/compare/{runId}` opens
the page from Decisions, retained results in Chat/System/Activity, and existing run details.
No new run inspector, merge editor, autonomy setting, or global rail redesign is introduced.

- Decisions and the System waiting count share one Postgres conflict-eligibility predicate,
  including completed checkpoint verification. An applying decision stays visible; settled
  decisions leave the queue. Failed/stopped run status and review semantics do not change.
  Queue reads never compute a diff or read storage. Polling refreshes Decisions even when
  the affected run is outside the capped run list.
- The client compares **current → saved**. A block intersecting net starting→current edits
  gets a warning bar, including restoration at a deletion's location. Bars are block-level
  warnings, not line authorship. Unknown starting context is disclosed, never treated as
  proof of no intervening edits. No text is struck through or interpreted as markup.
- `diff` (jsdiff) 9.0.0 supplies lossless line and whitespace-preserving word comparisons.
  The Tin DOM renderer is lazy-loaded (about 12 KB minified including jsdiff); it implements
  folding, change navigation, accessible side labels, and per-block warnings. The choice
  follows the required small plain-text surface, not a claim that Pierre cannot support it.
  Line computation has a 500 ms/edit-distance cap. Word decoration has a separate short
  budget; if unavailable the complete line diff remains usable. If the line diff cannot be
  completed, neither a partial diff nor Use saved is shown as available; Keep stays usable.
- Markdown wraps; CSV/Mermaid use old/new line numbers and horizontal pane scrolling.
  Full versions open in the existing format readers with a comparison return link and
  explicit current/saved context. Missing and empty files remain distinct.
- Keep current is preselected. Identical content requires an explicit acknowledgment using
  `keep_current`. Nothing is sent for Not now. Stale responses require a new comparison;
  a lost response never permits a replacement request or a claim of success.
- Before POST the browser stores only the request identifiers/action (no file bodies), scoped
  to actor/project/run. Refresh preserves the comparison route. The Postgres-only status read
  can independently reconstruct a pending request for its **original actor and client**;
  another caller sees pending state without a retry request. Check outcome re-sends that
  exact request; status reads never run the recovery operation themselves.
- An applied/kept page shows the recorded outcome and revision, **not a newly calculated diff
  labelled as historical**. Open file reads the current head, which may already contain later
  changes. Generic resolved copy does not falsely attribute another member's choice to you.

`npm run check:comparison` checks exact-body reconstruction, annotations, folding, states,
and recovery. `npm run test:comparison-browser` uses Playwright with the real packaged app
and isolated synthetic HTTP/identity fixtures; it covers responsive layout, Decisions,
reader return, apply and reload. Install Chromium with `npx playwright install chromium`,
or set `TIN_TEST_BROWSER_CHANNEL=chrome` for an installed Chrome. These synthetic browser
tests are not a claim of authenticated production browser acceptance.

An action supplies only:

```json
{
  "request_id": "a stable UUID",
  "action": "use_saved",
  "expected_revision": "the current revision from the comparison",
  "saved_revision": "the saved revision from the comparison"
}
```

`keep_current` is the other action. The server binds the path and exact saved bytes; the
caller cannot supply replacement text, change the project, or select another checkpoint.
Applying replaces content while preserving an existing regular file's mode; a missing file
is created as a normal non-executable file. Symlinks and unsafe parent entries are not followed.
The authenticated member and OAuth client are recorded as provenance, never accepted from
the body. Unknown HTTP fields are rejected. This is member-directed action, not an enabled
autonomy policy or a claim that the backend can distinguish a human click from an authorized
MCP client's request.

Results include `request_id`, `action`, `state` (`kept` or `applied`), `revision`, `changed`,
and `replayed`. A byte-identical apply records `changed: false` without a pretend commit.
Run views and MCP run listings expose nullable `output_resolution` alongside `retained_output`.
The original run status, error, review decision, and canonical artifact identity stay unchanged.
The normal `approve` action is not an alias for this operation.

## Concurrency and recovery

- Migration 025 adds one nullable JSONB resolution projection to `workflow_runs`. Existing
  effect receipts hold request identity and any publication intent; no new registry, task,
  workflow, background scanner, or generalized merge engine is introduced.
- A run-level advisory lock serializes decisions. Its holder reuses that connection for
  reads, so duplicate requests cannot exhaust the pool while waiting for the lock. Project
  state writes also use the existing project lock and code.storage `expectedHeadSha`.
- The **whole viewed project revision** must still match, even after an unrelated edit.
  This user-directed replacement never silently rebases a reviewed choice. A stale request
  receives `stale_comparison` (HTTP 409), records no file effect or product event, and needs
  a new request ID after refreshing. Reusing its ID with changed arguments is a conflict.
- Before a possible remote write, persist the request, `applying` projection, immutable
  checkpoint, and attempted parent. A lost response or interrupted finalization leaves
  `resolution_pending` (503). Retry the **identical** request with the same authenticated
  actor/client. A different request cannot discard or supersede an unconfirmed application.
- Recovery reuses the publication reconciler: find the original exact marker, parent,
  single-file scope, and digest on bounded immutable history before considering another
  write. Later same-file edits remain untouched. Incomplete history never proves absence.
  A definitive stale outcome clears the active resolution so a fresh choice can proceed.
- Resolution, completed receipt, and one product Activity fact commit in one Postgres
  transaction. Completed retries return the recorded result without a storage dependency.
  Keeping current and no-change application do not invent a file-edit event.
- A resolved conflict is settled once; a second decision with a new ID is rejected. Further
  edits use ordinary project Files with its own revision/request guards. Both original
  versions remain in durable history; referenced checkpoint branches must not be deleted.

If an unconfirmed request outlives the history budget or its originating OAuth client,
leave it pending for explicit operator recovery; do not clear its receipt to unblock a
different choice. There is no automatic worker retry for this member-directed endpoint.

## Future autonomy boundary

Read-only study of `../strangeloop` found one shared **Manual / Guided / Autonomous**
control and a separate **Automatic Task Runs** on/off control. That separation is useful:
permission to start work is not permission to replace conflicting content. No sibling code
or infrastructure is imported or changed.

Later, dashboard and MCP can share a Tin-owned policy that chooses to ask, keep, or request
an apply; an agent may compare and recommend or decide within that explicit policy. It
should call this same exact-version action, not introduce a second writer. Record the
policy/version and decision provenance then. No such setting, model decision, auto-apply,
or approval bypass exists in this slice. Safety checks are not an autonomy level.

## Verification

The focused suite uses actual disposable Postgres schemas and migrations plus a remote
storage double. It covers current-to-saved comparison, absent versus empty files, bounded
and unsafe comparisons, actor/client/request identity, membership for HTTP and MCP, fifteen
concurrent duplicate requests, CAS races, lost responses, later edits, incomplete history,
transaction rollbacks, and unchanged workflow/review semantics. All 310 tests, including
the ten accepted Temporal replays, pass locally with formatting, lint, import-boundary,
and diagram-build checks. Keep live deployment evidence outside source control.
