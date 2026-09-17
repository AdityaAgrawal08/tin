"""Project only completed managed operations, never an invented workflow percentage."""


async def project_completed_steps(conn, run_id):
    rows = await conn.fetch(
        """SELECT result->>'step' AS step FROM effect_receipts
           WHERE operation IN ('code_model_call_v1','code_service_call_v1')
             AND result->>'run_id'=$1 AND status='completed'
             AND result ? 'response' AND NOT result ? 'error'
           ORDER BY updated_at, execution_key LIMIT 16""",
        str(run_id),
    )
    if not rows:
        return
    step = rows[-1]["step"]
    summary = f"Completed {len(rows)} managed {'step' if len(rows) == 1 else 'steps'} · {step}"
    await conn.execute(
        """UPDATE workflow_runs SET progress_mode='indeterminate', progress_step=$2,
           progress_current=NULL, progress_total=NULL, progress_percent=NULL,
           progress_summary=$3, progress_updated_at=now(), heartbeat_at=now()
           WHERE id=$1 AND status IN ('pending','running')""",
        run_id,
        step,
        summary[:240],
    )
