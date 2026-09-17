"""Optional write-only payment details, encrypted and scoped to a single run."""

import json
import re
from dataclasses import dataclass, field

from tin_lite.domain import QA_SIGNUP_WALKTHROUGH_WORKFLOW_NAME
from tin_lite.usage_capture import borrowed_connection
from tin_lite.workflow_inputs import WorkflowInputError


@dataclass(repr=False)
class RunPaymentCard:
    card: dict = field(repr=False)
    cipher: object = field(repr=False)

    async def store(self, conn, *, run_id, project_id):
        ciphertext = self.cipher.encrypt(
            json.dumps(self.card), context=f"run-payment-card:{project_id}:{run_id}"
        )
        await conn.execute(
            "INSERT INTO run_payment_cards (run_id, ciphertext, encryption_key_id) "
            "VALUES ($1, $2, $3)",
            run_id,
            ciphertext,
            self.cipher.key_id,
        )

    async def check_retry(self, conn, *, run):
        if run["status"] in {"succeeded", "failed", "stopped", "superseded"}:
            return  # Return the original receipt; never attach another card.
        row = await conn.fetchrow("SELECT * FROM run_payment_cards WHERE run_id=$1", run["id"])
        if row is None or row["encryption_key_id"] != self.cipher.key_id:
            raise WorkflowInputError("This start request cannot change its payment card.")
        original = json.loads(
            self.cipher.decrypt(
                row["ciphertext"], context=f"run-payment-card:{run['project_id']}:{run['id']}"
            )
        )
        if original != self.card:
            raise WorkflowInputError("This start request cannot change its payment card.")


def prepare(value, *, workflow, integrations):
    if value is None:
        return None
    if workflow.key != QA_SIGNUP_WALKTHROUGH_WORKFLOW_NAME or workflow.project_id is not None:
        raise WorkflowInputError("Payment details are only supported for the signup walkthrough.")
    fields = {"number", "name", "expiry", "security_code", "billing_address"}
    if not isinstance(value, dict) or set(value) != fields:
        raise WorkflowInputError("Complete all five payment card fields, or omit the card.")
    if any(
        not isinstance(v, str) or not v.strip() or len(v) > 500 or any(ord(c) < 32 for c in v)
        for v in value.values()
    ):
        raise WorkflowInputError("Payment card fields are invalid.")
    card = {k: v.strip() for k, v in value.items()}
    card["number"] = re.sub(r"[ -]", "", card["number"])
    if (
        not re.fullmatch(r"[0-9]{13,19}", card["number"])
        or not re.fullmatch(r"(0[1-9]|1[0-2])/[0-9]{2}", card["expiry"])
        or not re.fullmatch(r"[0-9]{3,4}", card["security_code"])
    ):
        raise WorkflowInputError("Check the card number, MM/YY expiry and security code.")
    cipher = getattr(integrations, "_cipher", None)
    if cipher is None:
        raise WorkflowInputError("Payment card encryption is not configured.")
    return RunPaymentCard(card, cipher)


async def load(database, integrations, *, run_id):
    row = await (borrowed_connection(database) or database.pool).fetchrow(
        "SELECT c.*, r.project_id FROM run_payment_cards c "
        "JOIN workflow_runs r ON r.id=c.run_id WHERE c.run_id=$1",
        run_id,
    )
    if row is None:
        return None
    cipher = getattr(integrations, "_cipher", None)
    if cipher is None or cipher.key_id != row["encryption_key_id"]:
        raise RuntimeError("Run payment card encryption key is unavailable.")
    return json.loads(
        cipher.decrypt(row["ciphertext"], context=f"run-payment-card:{row['project_id']}:{run_id}")
    )
