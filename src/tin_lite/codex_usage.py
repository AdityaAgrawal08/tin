"""Attempt receipts for isolated Codex OAuth execution, not native API billing."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from tin_lite.db import Database

OPERATION = "isolated_codex_attempt_v1"


async def record_codex_attempt[T](
    *,
    db: Database,
    conn,
    run,
    execution_key: str,
    sandbox_id: str,
    timeout_seconds: int,
    call: Callable[[Callable[[dict[str, Any]], Awaitable[None]]], Awaitable[T]],
) -> T:
    """Reuse the activity connection and prevent purchasing an ambiguous attempt twice.

    Durable artifact recovery runs before this function. No provider cost is inferred
    from tokens, and wall time is an observation, not an E2B invoice.
    """
    key = f"{execution_key}:isolated-codex-attempt"
    async with db.effect_lock(key, OPERATION, conn=conn) as (locked, existing):
        if existing is not None:
            raise RuntimeError(
                "Codex attempt already exists; recover its checkpoint before retrying"
            )
        record = {
            "version": 1,
            "execution_kind": "codex_chatgpt_oauth",
            "run_id": str(run.id),
            "project_id": str(run.project_id),
            "definition_commit_sha": run.definition_commit_sha,
            "generation": run.generation,
            "sandbox_id": sandbox_id,
            "attempted_at": datetime.now(UTC).isoformat(),
            "timeout_seconds": timeout_seconds,
            "outcome": "unconfirmed",
            "usage": None,
            "supplier_cost": None,
            "elapsed_seconds": None,
        }
        terms = None
        if db.billing is not None:
            terms = await db.billing.begin_operation(
                locked,
                run_id=run.id,
                operation_id=key,
                kind="isolated_codex",
                maximum=lambda terms: terms["maximum_nanos"] - terms["execution_fee_nanos"],
            )
        await db.start_effect(locked, execution_key=key, operation=OPERATION)
        await db.save_effect_progress(locked, execution_key=key, result=record)
        started = time.monotonic()

        async def observed(value: dict[str, Any]) -> None:
            # Called only by the trusted isolated E2B controller stream, not tools/API input.
            record["usage"] = value
            await db.save_effect_progress(locked, execution_key=key, result=record)

        async def bill_observed():
            if terms is None or not isinstance(record["usage"], dict):
                return
            from tin_lite.billing_contracts import receipt_charge

            priced = receipt_charge(terms, "isolated_codex", record)
            if priced is not None:
                await db.billing.observe_operation(
                    locked, operation_id=key, nanos=priced[0], observation=priced[1]
                )

        try:
            result = await call(observed)
        except BaseException as exc:
            # A lost transport/kill response remains uncertain even if partial usage exists.
            # Keep the already durable observations; do not call absence "zero tokens".
            record.update(
                outcome="cancelled" if isinstance(exc, asyncio.CancelledError) else "failed",
                elapsed_seconds=round(time.monotonic() - started, 3),
                finished_at=datetime.now(UTC).isoformat(),
            )
            try:
                await asyncio.wait_for(
                    db.save_effect_progress(locked, execution_key=key, result=record), timeout=5
                )
                await asyncio.wait_for(bill_observed(), timeout=5)
            except BaseException:  # noqa: S110 — no raw exception/credentials; retain original failure
                # Preserve the original failure and previously durable observations.
                pass
            raise
        else:
            record.update(
                outcome="checkpoint_returned",
                elapsed_seconds=round(time.monotonic() - started, 3),
                finished_at=datetime.now(UTC).isoformat(),
            )
            await db.complete_effect(locked, execution_key=key, result=record)
            await bill_observed()
            return result
