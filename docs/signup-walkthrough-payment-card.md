# Optional one-run payment card

Starting **Walk the signup as a new user** from the Registry or a saved workflow opens
a start dialog. Leave **Add a card for this run** unchecked to run without one. A
card-required trial then becomes a reported wall; free paths remain available.

Checking it reveals card number, name, MM/YY expiry, security code and billing address.
Only a trial with $0 due now is allowed. The procedure submits once, cancels before
finishing, and puts a failed cancellation at the top of its report.

The browser clears the form on submit or cancel and does not persist its values. Saving
a configuration does not collect a card. Every later manual start asks again. Scheduled,
MCP and retry starts inherit no card from earlier runs.

## Runtime contract

The optional `payment_card` object is a separate top-level field on the direct run-start
request and the saved workflow's manual run-start request. Its keys are `number`, `name`,
`expiry`, `security_code`, and `billing_address`, all strings. Never put payment details
in `inputs`, notes, a project file, a reusable workflow definition, or an agent conversation.
The server accepts this field only for the built-in `qa.signup_walkthrough` workflow.

After project authorization, the switchboard validates the fields without echoing their
values. The existing integration AES-GCM key encrypts the card with project and run IDs
as authenticated context. Migration `038_run_payment_cards.sql` stores the ciphertext
atomically with the run. A duplicate start returns the same run and cannot replace an
active run's card. No card value enters ordinary run inputs, saved configurations,
Temporal arguments, effect receipts, or product responses.

The worker decrypts the card into the private sandbox context. It redacts card fields
from returned messages, including three-digit security codes. Card-bearing runs do not
retain diagnostic Codex rollouts. A shared guard rejects payment fields in the report
before the sandbox pushes its branch and again before trusted publication. The report
refers only to the “supplied test card”. These checks protect stored output; they are not
a guarantee that a website's trial or cancellation will succeed.

A database trigger deletes the encrypted row when the run succeeds, fails, stops, or is
superseded. Project/run deletion cascades to it as well. Pending or active runs retain it
for recovery; operators should stop abandoned runs. Database backups follow the
operator's existing retention policy. Changing the encryption key while a run is active
without preserving access makes its card unavailable and fails the run closed.

## Activation

Apply migration 038, rebuild the browser sandbox template, then deploy the switchboard
and workers and sync the catalog to publish walkthrough version **1.3.0**. The new sandbox
image contains the payment instruction and the shared output guard. Do not enable the
form against an old sandbox image.

Saved configurations pin their definition revision: recreate old walkthrough configurations
from the current Registry to use the updated prompt. Historical registry revisions and Git
history are not rewritten by this change. The old hardcoded card has been removed from
the current source tree; historical copies require separate cleanup.
