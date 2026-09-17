from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_procedure_publication import publication_db as publication_db
from test_visibility_audit import FakeAuditor, activity_fixture, adjudication, panel

from tin_lite.activities import TinActivities
from tin_lite.domain import RunStatus, SideEffectConflictError
from tin_lite.visibility import validate_visibility_artifacts, visibility_publication_facts


async def seeded_visibility(db, *, legacy=False):
    project = await db.create_project(
        name="Visibility proof", state_repo_id="projects/visibility-proof"
    )
    _, run = activity_fixture()
    run = replace(run, project_id=project.id, status=RunStatus.RUNNING)
    await db.pool.execute(
        """INSERT INTO workflows (id,key,title,executor,definition_repo_id,definition_path,
           current_commit_sha,version_label,definition)
           VALUES ($1,'visibility.audit','Visibility audit','visibility.audit','registry/workflows',
                   'visibility.json',$2,'1.1.0','{}')""",
        run.workflow_id,
        run.definition_commit_sha,
    )
    await db.pool.execute(
        """INSERT INTO workflow_runs (id,project_id,workflow_id,executor,definition_commit_sha,
           temporal_workflow_id,thread_id,generation,fencing_token,status)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)""",
        run.id,
        run.project_id,
        run.workflow_id,
        run.executor,
        run.definition_commit_sha,
        run.temporal_workflow_id,
        run.thread_id,
        run.generation,
        run.fencing_token,
        run.status.value,
    )
    evidence_path = f"reports/visibility/{run.id}/evidence.json"
    report, evidence = FakeAuditor().build_artifacts(
        run_id=str(run.id),
        evidence_path=evidence_path,
        panel=panel(),
        measurements=[{}] * 5,
        adjudication=adjudication(),
        source_refs=[],
    )
    result = {
        "canonical_commit_sha": "a" * 40,
        "artifact_path": "reports/AI_VISIBILITY.md",
        "evidence_path": evidence_path,
    }
    if not legacy:
        result["publication"] = visibility_publication_facts(
            run=run, canonical_sha="a" * 40, report=report, evidence=evidence
        )
    key = f"{run.id}:visibility_commit"
    async with db.effect_lock(key, "visibility_commit") as (conn, _):
        await db.start_effect(conn, execution_key=key, operation="visibility_commit")
        await db.complete_effect(conn, execution_key=key, result=result)

    class Storage:
        reads = 0
        unavailable = not legacy

        async def read_canonical_artifact(self, *, repo_id, commit_sha, path):
            self.reads += 1
            if self.unavailable:
                raise ConnectionError("storage unavailable after commit")
            assert repo_id == project.state_repo_id and commit_sha == "a" * 40
            return {"reports/AI_VISIBILITY.md": report, evidence_path: evidence}[path]

    storage = Storage()
    activities = TinActivities(
        database=db, storage=storage, sandboxes=SimpleNamespace(), settings=SimpleNamespace()
    )
    return activities, storage, run, result


@pytest.mark.asyncio
async def test_projection_succeeds_without_storage_and_duplicate_has_one_event(publication_db):
    activities, storage, run, _ = await seeded_visibility(publication_db)
    await asyncio.gather(*(activities.project_visibility_result(str(run.id)) for _ in range(3)))
    projected = await publication_db.get_run(run.id)
    assert projected.status == RunStatus.SUCCEEDED
    assert projected.canonical_commit_sha == "a" * 40
    assert storage.reads == 0
    assert (
        await publication_db.pool.fetchval(
            "SELECT count(*) FROM activity_events "
            "WHERE run_id=$1 AND event_type='visibility_audit_ready'",
            run.id,
        )
        == 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_at", ["event", "receipt"])
async def test_projection_rollback_then_retry_without_storage(publication_db, monkeypatch, fail_at):
    activities, storage, run, _ = await seeded_visibility(publication_db)
    method = "add_activity" if fail_at == "event" else "complete_effect"
    original = getattr(publication_db, method)

    async def fail(*args, **kwargs):
        await original(*args, **kwargs)
        raise ConnectionError("transaction interrupted")

    monkeypatch.setattr(publication_db, method, fail)
    with pytest.raises(ConnectionError):
        await activities.project_visibility_result(str(run.id))
    assert (await publication_db.get_run(run.id)).status == RunStatus.RUNNING
    assert (await publication_db.get_effect(f"{run.id}:visibility_projection")).status == "failed"
    assert (
        await publication_db.pool.fetchval(
            "SELECT count(*) FROM activity_events WHERE run_id=$1", run.id
        )
        == 0
    )
    monkeypatch.setattr(publication_db, method, original)
    await activities.project_visibility_result(str(run.id))
    assert (await publication_db.get_run(run.id)).status == RunStatus.SUCCEEDED
    assert storage.reads == 0


@pytest.mark.asyncio
async def test_legacy_validation_is_once_and_never_rewrites_commit_receipt(
    publication_db, monkeypatch
):
    activities, storage, run, original_result = await seeded_visibility(publication_db, legacy=True)
    original_complete = publication_db.complete_visibility_projection

    async def fail(*args, **kwargs):
        raise ConnectionError("database interruption")

    monkeypatch.setattr(publication_db, "complete_visibility_projection", fail)
    with pytest.raises(ConnectionError):
        await activities.project_visibility_result(str(run.id))
    assert storage.reads == 2
    storage.unavailable = True
    monkeypatch.setattr(publication_db, "complete_visibility_projection", original_complete)
    await activities.project_visibility_result(str(run.id))
    assert storage.reads == 2
    assert (
        await publication_db.get_effect(f"{run.id}:visibility_commit")
    ).result == original_result
    assert (await publication_db.get_run(run.id)).status == RunStatus.SUCCEEDED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("artifact_path", "wiki/OTHER.md"),
        ("evidence_path", "reports/visibility/other/evidence.json"),
        ("publication", {}),
    ],
)
async def test_invalid_receipt_fails_before_storage(publication_db, field, value):
    activities, storage, run, result = await seeded_visibility(publication_db)
    result[field] = value
    await publication_db.pool.execute(
        "UPDATE effect_receipts SET result=$2::jsonb WHERE execution_key=$1",
        f"{run.id}:visibility_commit",
        json.dumps(result),
    )
    with pytest.raises(ValueError):
        await activities.project_visibility_result(str(run.id))
    assert storage.reads == 0
    assert (await publication_db.get_run(run.id)).status == RunStatus.RUNNING


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,review", [("failed", False), ("stopped", False), ("needs_input", True)]
)
async def test_projection_cannot_revive_terminal_run_or_bypass_review(
    publication_db, status, review
):
    activities, storage, run, _ = await seeded_visibility(publication_db)
    await publication_db.pool.execute(
        "UPDATE workflow_runs SET status=$2,review_required=$3 WHERE id=$1", run.id, status, review
    )
    with pytest.raises(SideEffectConflictError):
        await activities.project_visibility_result(str(run.id))
    assert (await publication_db.get_run(run.id)).status.value == status
    assert storage.reads == 0


@pytest.mark.asyncio
async def test_committed_generation_retry_never_rereads_sources_or_calls_models(publication_db):
    activities, storage, run, _ = await seeded_visibility(publication_db)
    activities._visibility_auditor = SimpleNamespace()
    await activities.generate_visibility_audit(str(run.id))
    assert storage.reads == 0


@pytest.mark.parametrize(
    "damage", ["report", "foreign_run", "evidence_json", "missing_measurements"]
)
def test_invalid_output_pair_is_rejected_before_publication(damage):
    _, run = activity_fixture()
    evidence_path = f"reports/visibility/{run.id}/evidence.json"
    report, evidence = FakeAuditor().build_artifacts(
        run_id=str(run.id),
        evidence_path=evidence_path,
        panel=panel(),
        measurements=[{}] * 5,
        adjudication=adjudication(),
        source_refs=[],
    )
    if damage == "report":
        report = b"Incomplete report"
    elif damage == "evidence_json":
        evidence = b"not JSON"
    else:
        value = json.loads(evidence)
        value["run_id" if damage == "foreign_run" else "measurements"] = "another run"
        evidence = json.dumps(value).encode()
    with pytest.raises(ValueError):
        validate_visibility_artifacts(
            report, evidence, run_id=str(run.id), evidence_path=evidence_path
        )
