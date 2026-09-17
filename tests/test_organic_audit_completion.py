import json
from copy import deepcopy
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from test_organic_audit import activities_fixture, page_fixture, panel_fixture, response
from test_procedure_publication import activity_fixture
from test_procedure_publication import publication_db as publication_db

from tin_lite.organic_audit import (
    V7_AUDIT_POLICY,
    audit_paths,
    build_documents,
    digest,
    normalize_pages,
)
from tin_lite.organic_audit_activities import OrganicAuditActivities
from tin_lite.organic_audit_ai import classify_absent_target, read_response, summarize
from tin_lite.organic_audit_completion import KIND, completion_seed, prepare_completion


def source_fixture(source_id=None, project_id=None):
    source_id, project_id = source_id or str(uuid4()), project_id or str(uuid4())
    scope = {
        "url": "https://example.com/",
        "host": "example.com",
        "market": "US",
        "started_at": "2026-09-15T00:00:00Z",
        "policy_version": V7_AUDIT_POLICY["version"],
        "max_cost_usd": "7",
    }
    panel = {"status": "completed", **panel_fixture(), "planned_observations": 8}
    answer = {"status": "completed", "value": read_response(response(), search=True)}
    observations = [
        {
            "status": "completed",
            "index": i,
            "question_index": i // 2,
            "repetition": i % 2 + 1,
            "answer": answer,
            "classification": classify_absent_target(answer["value"], panel),
        }
        for i in range(7)
    ]
    observations.append(
        {
            "status": "unavailable",
            "index": 7,
            "question_index": 3,
            "repetition": 2,
            "failure_stage": "answer",
            "reason": "provider_result_unavailable",
            "answer": {"status": "unknown", "reason": "provider_result_unavailable"},
        }
    )
    crawl = {"status": "completed", "pages": normalize_pages([page_fixture()], "example.com")}
    ai = summarize(panel, observations, policy_version=V7_AUDIT_POLICY["version"])
    stages = {
        "scope": scope,
        "crawl": crawl,
        "panel": panel,
        "crawl_submit": {"status": "completed", "value": {"task_id": "source-task"}},
        "brand_checks": {"status": "observed", "observations": []},
        **{f"observation:{i}": o for i, o in enumerate(observations)},
    }
    docs = build_documents(
        run_id=source_id,
        project_id=project_id,
        definition_sha="d" * 40,
        scope=scope,
        crawl=crawl,
        ai=ai,
        spending={},
        policy_version=V7_AUDIT_POLICY["version"],
    )
    artifacts = {path: content.decode() for path, content in docs.items()}
    stages.update(
        artifacts=artifacts,
        publish={
            "canonical_commit_sha": "a" * 40,
            "documents_sha256": digest(artifacts),
            "artifact_path": audit_paths(source_id)["AUDIT.md"],
        },
    )
    return {
        "source_id": source_id,
        "project_id": project_id,
        "revision": "a" * 40,
        "definition_sha": "d" * 40,
        "stages": stages,
        "requested_at": "2026-09-15T01:00:00Z",
    }


def test_completion_retains_all_successes_and_original_failure_without_reusing_money():
    source = source_fixture()
    before = deepcopy(source)
    seed = completion_seed(**source)
    assert source == before
    assert "observation:7" not in seed
    assert not {"budget", "publish", "artifacts", "projection", "answer:7"}.intersection(seed)
    assert (
        seed["scope"]["completion"]["original_missing_observation"]
        == source["stages"]["observation:7"]
    )
    for i in range(7):
        assert seed[f"observation:{i}"] == source["stages"][f"observation:{i}"]


@pytest.mark.parametrize("change", ["project", "revision", "artifact", "grade", "observation"])
def test_completion_rejects_wrong_proof_or_existing_answer(change):
    source = source_fixture()
    if change == "project":
        source["project_id"] = str(uuid4())
    elif change == "revision":
        source["revision"] = "b" * 40
    elif change == "artifact":
        source["stages"]["artifacts"][audit_paths(source["source_id"])["AUDIT.md"]] += "changed"
    elif change == "grade":
        evidence_path = audit_paths(source["source_id"])["evidence.json"]
        evidence = json.loads(source["stages"]["artifacts"][evidence_path])
        evidence["ai_visibility"]["observations"][7]["failure_stage"] = "grading"
        source["stages"]["artifacts"][evidence_path] = json.dumps(evidence)
        source["stages"]["publish"]["documents_sha256"] = digest(source["stages"]["artifacts"])
    else:
        source["stages"]["observation:0"] = {"status": "changed"}
    with pytest.raises(ValueError):
        completion_seed(**source)


@pytest.mark.asyncio
async def test_normal_execution_only_purchases_missing_answer_and_publishes_once():
    source = source_fixture()
    seed = completion_seed(**source)
    activities, db, storage, provider = await activities_fixture()
    run_id = str(db.run.id)
    db.effects.clear()
    for stage, result in seed.items():
        await activities._save(run_id, stage, result)
    activities.responses = type("Responses", (), {"create": AsyncMock(return_value=response())})()
    for _ in range(2):
        await activities.organic_prepare(run_id)
        await activities.organic_start_crawl(run_id)
        assert await activities.organic_poll_crawl(run_id)
        await activities.organic_end_crawl(run_id)
        assert await activities.organic_prepare_panel(run_id) == 8
        for index in range(8):
            await activities.organic_observe({"run_id": run_id, "index": index})
        await activities.organic_brand_checks(run_id)
        await activities.organic_publish(run_id)
    assert activities.responses.create.await_count == 1
    sent = activities.responses.create.await_args.args[0]
    assert sent["timeout"] == 180
    provider.submit.assert_not_awaited()
    provider.pages.assert_not_awaited()
    artifacts = await activities._result(run_id, "artifacts")
    evidence = json.loads(artifacts[audit_paths(run_id)["evidence.json"]])
    assert evidence["ai_visibility"]["completed"] == 8
    assert evidence["ai_visibility"]["status"] == "completed"
    assert "explicitly retried the one missing answer" in artifacts[audit_paths(run_id)["AUDIT.md"]]
    assert storage.repo.writes == 1


@pytest.mark.asyncio
async def test_preparation_seeds_atomically_and_replays_with_real_postgres(publication_db):
    from types import SimpleNamespace

    db = publication_db
    _, storage, source, _ = await activity_fixture(db)
    data = source_fixture(str(source.id), str(source.project_id))
    await db.pool.execute(
        "UPDATE workflow_runs SET executor='organic.audit',status='succeeded', "
        "canonical_commit_sha=$2,lease_active=false WHERE id=$1",
        source.id,
        "a" * 40,
    )
    await db.pool.execute(
        "UPDATE workflows SET key='organic.audit',executor='organic.audit' WHERE id=$1",
        source.workflow_id,
    )
    await db.pool.execute(
        "INSERT INTO project_memberships(project_id,clerk_user_id) VALUES($1,'user_completion')",
        source.project_id,
    )
    activities = OrganicAuditActivities(database=db, storage=storage, settings=SimpleNamespace())
    for stage, result in data["stages"].items():
        await activities._save(str(source.id), stage, result)
    run, _ = await db.create_run(
        project_id=source.project_id,
        workflow_id=source.workflow_id,
        started_by_clerk_user_id="user_completion",
        prerequisite_evidence={
            "kind": KIND,
            "source_run_id": str(source.id),
            "source_revision": "a" * 40,
        },
    )
    await prepare_completion(activities, run)
    await prepare_completion(activities, run)
    assert (await db.get_run(run.id)).status.value == "running"
    assert await activities._result(str(run.id), "observation:7") is None
    assert await activities._result(str(run.id), "observation:0") == data["stages"]["observation:0"]
    assert (
        await activities._result(str(source.id), "observation:7") == data["stages"]["observation:7"]
    )
