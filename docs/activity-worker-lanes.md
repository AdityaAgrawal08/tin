# Activity worker lanes

## Why this change

Long sandbox activities must not block independent saves, review updates or projections.
Tin keeps their worker capacity separate.

## Small runtime boundary

- The existing queue remains the workflow queue and the **four-slot Codex lane**.
  Both sandbox-create activities, procedure persistence/execution, design execution,
  and task turns stay there. Projects can execute concurrently through the protected API route;
  four is worker capacity, not an account-level serialization rule.
- One activity-only worker polls `<existing queue>-trusted`, with four activity slots.
  An explicit allowlist covers trusted preparation, native work, publication,
  approvals and projections. New activities must be classified at runtime startup;
  unknown activity names never receive trusted routing.
- Both workers live in the existing switchboard process and share its lifecycle.
  Workers shut down before their provider clients/database are closed.
- There are no waiting semaphores consuming the trusted slots, no new service,
  database table, version picker or execution engine.

## Project-scoped execution

`tin.project_codex_execution` is one internal Temporal child workflow, not a catalog
template or a product run. Its stable ID is `tin.project-codex:<project_id>`. Temporal
allows only one active execution of that ID, even across workers. The project ID is
resolved from the authorized run by a trusted activity, never supplied by a caller.

The child holds the position from sandbox creation through execution/checkpoint
cleanup. A task holds it for one active turn. Save, review, paused tasks and questions
do not hold it. All entry points (HTTP, MCP, schedules and parent workflows) use the
same executors, so they acquire the same position. Existing product-task admission
and billing concurrency/spending policies still apply before execution.

Contenders wait with durable timers (backoff from one to thirty seconds), consuming
no compute activity slot, sandbox or database connection. This is mutual exclusion,
not strict FIFO or a queue-position UI. Waiting is bounded at four hours to keep
history finite; a timeout fails without starting compute and can be retried normally.
Activity retry budgets are unchanged. A failed compute child is never mistaken for
queue contention or automatically purchased again. Cancellation waits for activity
cleanup before the child releases its ID. Stopping a queued task wakes its wait.

The outbound interceptor changes only activity routing options, not command order,
activity names, payloads, retries, definitions or effect keys. Routing is a pure
function of the recorded workflow queue and code-defined allowlist; it reads no
environment, database or mutable configuration during replay. Eager trusted
execution on the workflow worker is disabled.

## Upgrade and operations

The original worker retains **all** activity registrations. Activities already
scheduled onto the original queue stay there and drain normally. Newly scheduled
trusted activities use the new lane, including later steps of existing workflows.
Keeping the old queue is essential: moving all registrations would strand pending
activities. Codex remains on the original queue; trusted work retains its own capacity.

New Codex execution uses protected API controllers. The pooled-login broker and local
auth cache are removed; project execution gates remain distributed through Temporal.

Workflow patches preserve old histories. **For the first gate deployment, drain old
compute and verify no pending pre-gate compute before increasing the original worker's
slots.** Do not perform a mixed old/new worker rollout. Idle review runs are safe;
paused tasks patch each future turn separately and acquire the gate when resumed.

Four trusted slots are bounded, not a promise of zero queueing. Native work can still
fill them; project-state locks intentionally serialize conflicting writes. A future
observed multi-tenant backlog may justify separating native compute further and
adding Temporal Task Queue Fairness. That optional capability is not
enabled by this fix; it also cannot preempt a running long task. See the
[Temporal Python SDK's interceptor contract](https://github.com/temporalio/sdk-python)
for the underlying routing mechanism.

The future [Agents API](https://developers.openai.com/api/docs/guides/agents-api/overview)
migration changes execution/authentication, not this project-level coordination
contract. No Agents API route, key or model migration is included here.

## Honest progress and retry behavior

Planned drafts say “Ready to draft” while waiting for the writing worker, then
“Writing” only when execution is about to begin. Persistence atomically records
“The result is saved. Finishing delivery.” with its existing receipt. Canonical
publication, review, approval and completion advance the same Postgres projection.
HTTP, MCP and dashboard continue reading Postgres, never Temporal history.

Late persistence/publication retries cannot replace review or terminal progress
with an earlier phase. Repeating a review request after approval cannot move the
run back into `needs_input`. Review remains required; 3/3 describes finished output
work, not approval or website publication.

## Verification

- Real local Temporal test: eight queued Codex tasks, one held open; independent
  save and review complete before release, and maximum concurrent Codex work is one.
- Full mocked procedure travels through preparation, execution, save, review and
  completion on the intended queues.
- An activity scheduled by the old worker drains from the old queue after upgrade;
  its next step uses the trusted queue. Both old and new histories replay.
- Accepted production-history replay includes the new routing interceptor.
- Mixed procedures, design runs and task turns in one project serialize across
  independent workers; another project completes while that project's backlog waits.
- Review releases the project position; cancellation releases it only after cleanup.
- Worker restart, failed compute, cancelled queue entries and a pre-upgrade paused
  task resuming through the gate are covered by real local Temporal tests.
- Database tests exercise save/review progress, late duplicate deliveries,
  approved-review retries, atomic projection failure and terminal monotonicity.

These queue tests use no paid provider calls. Production verification must separately
check both pollers, replay actual draft histories, and run idempotent review
projection checks through the deployed trusted worker. Never regenerate, approve,
or publish a user's draft merely to test routing.
