# Onboarding through MCP

`get_started`, `get_run` for `growth.onboarding`, and `record_onboarding_picks`
return an additive handoff contract (`onboarding_contract_version: 1`). Existing
workflow identifiers, progress, report text, and project links remain available.
Project membership is checked before these fields are assembled.

| Field | Client behavior |
| --- | --- |
| `access_needs` | Recommend each connection through its benefit, permission label, and resource selection. Distinguish required access from recommended access and respect recorded declines. Obtain the founder's choice before using the supplied connection call. |
| `first_deliverables` | Explain what will arrive first, why it helps, its estimated time and current status. A proposed workflow or saved schedule is not a completed result. |
| `delivery_destination` | Tell the founder where to receive reports and review drafts. Advertise only `supported_channels` and the actual notification status. |
| `result_links` | Link directly to existing run documents, including drafts awaiting review. Keep the project overview as a secondary link. |
| `incomplete_setup` | Surface failed or missing setup items with their reason and next action. Do not bury these in an otherwise successful handoff. |
| `setup_status` | Distinguish work not started, work in progress, selection, complete setup, partial setup, and unknown legacy state. A completed orchestration run can still have partial setup. |

`connection_batch` supplies a ready-to-call `start_integration_connections` request
for relevant, unconnected providers that have not been declined. It is a proposal,
not authorization. Unknown repository details should prompt discovery when GitHub
would make the selected work useful. Mailbox access is offered for selected workflows
that require it, rather than requested by default. `measurement_needs` identifies
missing analytics context without pretending a data source has been connected.

Reports currently arrive inside Tin's Files and drafts in Decisions. The only
supported result destination is `tin`; there are no email or Slack result notifications
in this contract. A connected mailbox does not enable audit notifications. Individual
documents use `/document/{run_id}?project={project_id}` on the configured app origin;
links are emitted only when a durable artifact revision exists. The document reader
continues to enforce its own membership checks.

The planner receives workflow input schemas, including enum and length constraints.
Before presenting the plan, Tin checks proposed inputs and schedule shapes. Approval
validates selected workflows again, before sealing the plan or creating schedules.
An invalid selection returns `invalid_plan`; the plan can be corrected and approved
again. Valid approval receipts remain immutable and replayable.

Setup still attempts independently valid actions if availability changes after approval.
Its durable receipt and report distinguish partial setup, blocked first admissions and
delivery configuration failures. `get_run` also reconciles those receipts against saved
schedule state and the current first-run projections. It does not start or retry work.
Use these live facts over an older report when status has changed.

Approval is not website publication. Approved content remains in Tin unless repository
delivery is configured. GitHub delivery opens an unmerged pull request; connecting an
account alone does not change already saved delivery settings.

The onboarding conversation should lead with a concrete experiment and first useful
result, then explain access, review control and delivery. Close with what is running,
what arrives next and when, where the result will be received, and the next decision.
Do not read a long catalog or optimistic outlook in place of that handoff.
