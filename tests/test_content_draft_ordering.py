import asyncio
from uuid import UUID, uuid4

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError
from test_content_draft import fixture, start
from test_content_plan import item
from test_private_workflows import ACTOR, app, mcp, structured
from test_procedure_publication import publication_db as publication_db

from tin_lite import content_draft
from tin_lite.content_plan import plan_path
from tin_lite.organic_audit import canonical_json
from tin_lite.run_service import start_workflow_run
from tin_lite.workflow_inputs import WorkflowInputError


async def roadmap(f):
    plan = (await f.service.programs.read(project_id=f.project.id, program_id=f.configured.id))[
        "plan"
    ]
    # IDs are deliberately not lexicographic priority order; within-batch order matters too.
    plan["batches"][0]["items"] = [item("z_first"), item("a_second")]
    plan["batches"][2]["items"] = [item("m_third")]
    f.storage.repo.edit({plan_path(f.configured.id): canonical_json(plan)})
    f.inputs = {"program_id": str(f.configured.id)}
    return plan


async def draft_saved(f, run, *, status="needs_input"):
    # No model calls: simulate only the trusted publication projection for queue tests.
    await f.db.pool.execute(
        "UPDATE workflow_runs SET status=$2, canonical_commit_sha=$3, artifact_path=$4, "
        "lease_active=false WHERE id=$1",
        run.id,
        status,
        "a" * 40,
        f"content/drafts/{run.id}.md",
    )


async def discover(f):
    return await f.service.discover(project_id=f.project.id, program_id=f.configured.id)


async def test_next_is_ordered_and_receipted_before_dispatch_and_replay_never_advances(
    publication_db, monkeypatch
):
    f = await fixture(publication_db, monkeypatch)
    plan = await roadmap(f)
    key = str(uuid4())
    first = await start(f, key=key)
    chosen = await f.service.selection(first.id)
    assert chosen["item"]["id"] == "z_first" and chosen["mode"] == "next"
    assert first.input["item_id"] == "" and first.input["rewrite"] is False
    assert "z_first" in first.progress_summary
    assert (await discover(f))["progress"]["drafting"] == 1
    with pytest.raises(WorkflowInputError, match="already drafting"):
        await start(f, key=str(uuid4()))
    await draft_saved(f, first)
    assert (await discover(f))["next"]["item_id"] == "a_second"
    assert (await start(f, key=key)).id == first.id
    second = await start(f, key=str(uuid4()))
    assert (await f.service.selection(second.id))["item"]["id"] == "a_second"
    await draft_saved(f, second, status="succeeded")
    choices = await discover(f)
    assert choices["progress"] == {
        "total": 3,
        "drafted": 1,
        "awaiting_review": 1,
        "drafting": 0,
        "deferred": 0,
        "already_covered": 0,
        "needs_attention": 0,
    }
    assert choices["next"]["item_id"] == "m_third"
    assert (await f.service.programs.read(project_id=f.project.id, program_id=f.configured.id))[
        "plan"
    ] == plan


@pytest.mark.parametrize("same_request", [True, False])
async def test_concurrent_starts_commit_one_selection_and_one_run(
    publication_db, monkeypatch, same_request
):
    f = await fixture(publication_db, monkeypatch)
    await roadmap(f)
    key = str(uuid4())
    results = await asyncio.wait_for(
        asyncio.gather(
            *(start(f, key=key if same_request else str(uuid4())) for _ in range(8)),
            return_exceptions=True,
        ),
        timeout=20,
    )
    successes = [r for r in results if not isinstance(r, Exception)]
    assert len(successes) == (8 if same_request else 1)
    assert len({r.id for r in successes}) == 1
    assert all(isinstance(r, WorkflowInputError) for r in results if isinstance(r, Exception))
    assert (
        await f.db.pool.fetchval(
            "SELECT count(*) FROM workflow_runs WHERE workflow_id=$1", f.workflow.id
        )
        == 1
    )
    assert (
        await f.db.pool.fetchval(
            "SELECT count(*) FROM effect_receipts WHERE operation=$1",
            content_draft.SELECTION_OPERATION,
        )
        == 1
    )


async def test_default_holds_at_amendment_but_skips_intentional_deferrals(
    publication_db, monkeypatch
):
    f = await fixture(publication_db, monkeypatch)
    plan = await roadmap(f)
    request_id = uuid4()
    await f.service.programs.begin_revision(
        project_id=f.project.id,
        program_id=f.configured.id,
        request_id=request_id,
        expected_revision=f.storage.repo.head,
        batch_ids=["week_01"],
        instruction="Reconsider the upcoming topics.",
        context_paths=[],
        actor=ACTOR,
    )
    assert not (await discover(f))["next"]["available"]
    with pytest.raises(WorkflowInputError, match="pending revision"):
        await start(f)
    # An explicitly chosen later article remains an intentional override, not the default.
    later = await start(f, inputs={**f.inputs, "item_id": "m_third"})
    await draft_saved(f, later)
    await f.service.programs.resolve(
        project_id=f.project.id,
        program_id=f.configured.id,
        revision_id=request_id,
        action="discard",
        actor=ACTOR,
    )
    plan["batches"][0]["items"][0]["readiness"] = "deferred"
    f.storage.repo.edit({plan_path(f.configured.id): canonical_json(plan)})
    next_run = await start(f)
    assert (await f.service.selection(next_run.id))["item"]["id"] == "a_second"
    await draft_saved(f, next_run)
    assert (await discover(f))["next"]["item_id"] is None
    with pytest.raises(WorkflowInputError, match="All non-deferred"):
        await start(f)


async def test_amendment_race_is_rechecked_before_run_commit(publication_db, monkeypatch):
    f = await fixture(publication_db, monkeypatch)
    await roadmap(f)
    create = f.db.create_run

    async def raced(**kwargs):
        await f.service.programs.begin_revision(
            project_id=f.project.id,
            program_id=f.configured.id,
            request_id=uuid4(),
            expected_revision=f.storage.repo.head,
            batch_ids=["week_01"],
            instruction="Hold this batch.",
            context_paths=[],
            actor=ACTOR,
        )
        return await create(**kwargs)

    monkeypatch.setattr(f.db, "create_run", raced)
    with pytest.raises(WorkflowInputError, match="pending revision"):
        await start(f)
    assert (
        await f.db.pool.fetchval(
            "SELECT count(*) FROM workflow_runs WHERE workflow_id=$1", f.workflow.id
        )
        == 0
    )
    assert (
        await f.db.pool.fetchval(
            "SELECT count(*) FROM effect_receipts WHERE operation=$1",
            content_draft.SELECTION_OPERATION,
        )
        == 0
    )


async def test_changed_plan_is_not_silently_retargeted_after_admission(publication_db, monkeypatch):
    f = await fixture(publication_db, monkeypatch)
    plan = await roadmap(f)
    run = await start(f)
    plan["batches"][0]["items"][0]["brief"] = "New instructions after selection."
    f.storage.repo.edit({plan_path(f.configured.id): canonical_json(plan)})
    with pytest.raises(ValueError, match="changed after selection"):
        await f.service.prepare(run)
    assert (await f.service.selection(run.id))["item"]["id"] == "z_first"
    assert await f.service.saved(run.id) is None


async def test_rewrites_are_explicit_keep_prior_output_and_report_changed_brief(
    publication_db, monkeypatch
):
    f = await fixture(publication_db, monkeypatch)
    plan = await roadmap(f)
    first = await start(f)
    await draft_saved(f, first)
    with pytest.raises(WorkflowInputError, match="specific article"):
        await start(f, inputs={**f.inputs, "rewrite": True})
    with pytest.raises(WorkflowInputError, match="already has a draft"):
        await start(f, inputs={**f.inputs, "item_id": "z_first"})
    plan["batches"][0]["items"][0]["brief"] = "A revised angle for this article."
    f.storage.repo.edit({plan_path(f.configured.id): canonical_json(plan)})
    choice = (await discover(f))["items"][0]
    assert choice["brief_changed"] and choice["can_rewrite"] and not choice["available"]
    rewrite = await start(f, inputs={**f.inputs, "item_id": "z_first", "rewrite": True})
    assert rewrite.id != first.id
    assert (await f.service.selection(rewrite.id))["item"]["brief"].startswith("A revised")
    with pytest.raises(WorkflowInputError, match="Already drafting"):
        await start(f, inputs={**f.inputs, "item_id": "z_first", "rewrite": True})
    await f.db.project_failure(run_id=rewrite.id, error_message="A failed rewrite")
    choices = await discover(f)
    assert choices["items"][0]["draft"]["run_id"] == str(first.id)
    assert choices["next"]["item_id"] == "a_second"


async def test_failed_retry_pins_original_article_after_other_plan_items_move(
    publication_db, monkeypatch
):
    f = await fixture(publication_db, monkeypatch)
    plan = await roadmap(f)
    first = await start(f)
    await f.db.project_failure(run_id=first.id, error_message="Failed before compute")
    plan["batches"][0]["items"].reverse()
    f.storage.repo.edit({plan_path(f.configured.id): canonical_json(plan)})
    assert (await discover(f))["next"]["item_id"] == "a_second"
    retry = await start_workflow_run(
        runtime=f.runtime,
        settings=f.settings,
        workflow=f.workflow,
        project_id=f.project.id,
        started_by_clerk_user_id=ACTOR,
        input_payload=f.inputs,
        retry_of_run_id=first.id,
        start_idempotency_key=str(uuid4()),
    )
    assert (await f.service.selection(retry.id))["item"]["id"] == "z_first"


async def test_legacy_prepared_drafts_count_and_retained_results_block_repurchases(
    publication_db, monkeypatch
):
    f = await fixture(publication_db, monkeypatch)
    await roadmap(f)
    old = await start(f, inputs={**f.inputs, "item_id": "z_first"})
    await f.service.prepare(old)
    # Simulate a pre-feature run: only its original preparation receipt exists.
    await f.db.pool.execute(
        "DELETE FROM effect_receipts WHERE execution_key=$1", content_draft.selection_key(old.id)
    )
    await draft_saved(f, old)
    assert (await discover(f))["next"]["item_id"] == "a_second"
    second = await start(f)
    await f.db.pool.execute(
        "UPDATE workflow_runs SET status='failed', retained_output=$2::jsonb, "
        "lease_active=false WHERE id=$1",
        second.id,
        '{"reason":"output_conflict"}',
    )
    choices = await discover(f)
    assert choices["next"]["item_id"] == "a_second" and not choices["next"]["available"]
    assert choices["items"][1]["draft"]["output_source"] == "retained"
    for inputs in (f.inputs, {**f.inputs, "item_id": "a_second", "rewrite": True}):
        with pytest.raises(WorkflowInputError, match="saved result"):
            await start(f, inputs=inputs)


@pytest.mark.parametrize("resolution", ["applied", "kept"])
async def test_resolved_saved_output_does_not_block_next_article(
    publication_db, monkeypatch, resolution
):
    f = await fixture(publication_db, monkeypatch)
    await roadmap(f)
    run = await start(f)
    await f.db.pool.execute(
        "UPDATE workflow_runs SET status='failed', retained_output=$2::jsonb, "
        "output_resolution=$3::jsonb, lease_active=false WHERE id=$1",
        run.id,
        '{"reason":"output_conflict"}',
        '{"state":"' + resolution + '"}',
    )
    choices = await discover(f)
    assert choices["next"]["item_id"] == "a_second" and choices["next"]["available"]
    assert choices["items"][0]["can_rewrite"] and choices["progress"]["drafted"] == 1
    assert choices["items"][0]["draft"]["output_source"] == "retained"
    with pytest.raises(WorkflowInputError, match="already has a draft"):
        await start(f, inputs={**f.inputs, "item_id": "z_first"})
    await start(f, inputs={**f.inputs, "item_id": "z_first", "rewrite": True})


async def test_paused_program_cannot_draft_and_archived_program_is_not_discovered(
    publication_db, monkeypatch
):
    f = await fixture(publication_db, monkeypatch)
    await roadmap(f)
    await f.db.pool.execute(
        "UPDATE project_workflows SET status='paused' WHERE id=$1", f.configured.id
    )
    assert not (await discover(f))["next"]["available"]
    for inputs in (f.inputs, {**f.inputs, "item_id": "z_first"}):
        with pytest.raises(WorkflowInputError, match="Resume"):
            await start(f, inputs=inputs)
    await f.db.pool.execute(
        "UPDATE project_workflows SET status='archived' WHERE id=$1", f.configured.id
    )
    assert (await f.service.discover(project_id=f.project.id))["programs"] == []


async def test_saved_default_mcp_and_http_use_same_queue(publication_db, monkeypatch):
    f = await fixture(publication_db, monkeypatch)
    await roadmap(f)
    server = mcp(f, monkeypatch)
    saved = structured(
        await server.call_tool(
            "create_project_workflow",
            {
                "project_id": str(f.project.id),
                "workflow_id": str(f.workflow.id),
                "name": "Draft the next article",
                "inputs": f.inputs,
                "request_id": str(uuid4()),
            },
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(f)), base_url="https://tin.test"
    ) as client:
        first = await client.post(
            f"/api/projects/{f.project.id}/workflows/{saved['id']}/runs",
            headers={"Idempotency-Key": "first"},
        )
        assert first.status_code == 202, first.text
        run = await f.db.get_run(UUID(first.json()["id"]))
        assert (await f.service.selection(run.id))["item"]["id"] == "z_first"
        await draft_saved(f, run)
        second = structured(
            await server.call_tool(
                "start_project_workflow",
                {
                    "project_id": str(f.project.id),
                    "project_workflow_id": saved["id"],
                    "request_id": str(uuid4()),
                },
            )
        )
        assert (await f.service.selection(UUID(second["id"])))["item"]["id"] == "a_second"
        shown = structured(await server.call_tool("get_run", {"run_id": second["id"]}))
        assert shown["progress_mode"] == "steps" and shown["progress_total"] == 3
        assert "a_second" in shown["progress_summary"]
        with pytest.raises(ToolError, match="already drafting"):
            await server.call_tool(
                "start_workflow",
                {
                    "project_id": str(f.project.id),
                    "workflow_id": "content.generate",
                    "inputs": f.inputs,
                    "request_id": str(uuid4()),
                },
            )
    configured = await f.db.get_project_workflow(UUID(saved["id"]))
    assert configured.inputs["item_id"] == "" and configured.inputs["plan_revision"] == ""


async def test_selection_and_run_roll_back_if_billing_rejects(publication_db, monkeypatch):
    f = await fixture(publication_db, monkeypatch)
    await roadmap(f)

    class Reject:
        async def admit(self, *args, **kwargs):
            raise ValueError("Test budget rejection")

    f.db.billing = Reject()
    with pytest.raises(WorkflowInputError, match="budget rejection"):
        await start(f)
    assert (
        await f.db.pool.fetchval(
            "SELECT count(*) FROM workflow_runs WHERE workflow_id=$1", f.workflow.id
        )
        == 0
    )
    assert (
        await f.db.pool.fetchval(
            "SELECT count(*) FROM effect_receipts WHERE operation=$1",
            content_draft.SELECTION_OPERATION,
        )
        == 0
    )
