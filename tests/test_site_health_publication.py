"""Site health publication: a generic no-change result skips the PR but keeps a receipt."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_procedure_publication import activity_fixture
from test_procedure_publication import publication_db as publication_db

from tin_lite.procedures import (
    GITHUB_PULL_REQUEST_RESULT,
    GITHUB_REPOSITORY_WORKSPACE,
    PinnedCodexProcedure,
    procedure_checkpoint_path,
)


def site_manifest(*, no_change: bool) -> dict:
    return {
        "repository": "owner/site",
        "default_branch": "main",
        "head_sha": "b" * 40,
        "title": "No change: metadata is complete" if no_change else "Add a page description",
        "body": "Inspected the homepage; nothing bounded to fix." if no_change else "One fix.",
        "files": [] if no_change else [{"path": "app/layout.tsx", "content": "export {}\n"}],
        "outcome": "no_change" if no_change else "patch",
        "verification": ["git diff --check"],
    }


@pytest.mark.parametrize("no_change", [False, True])
async def test_site_health_publication_skips_pr_for_no_change(
    publication_db, monkeypatch, no_change
):
    db = publication_db
    activities, storage, run, _checkpoint = await activity_fixture(db)
    await db.pool.execute(
        "UPDATE workflows SET key='site.health_improve' WHERE id=$1", run.workflow_id
    )
    await db.pool.execute("UPDATE workflow_runs SET lease_active=true WHERE id=$1", run.id)
    await db.pool.execute(
        "UPDATE effect_receipts SET result=$2::jsonb WHERE execution_key=$1",
        f"{run.id}:procedure_artifact_persist",
        json.dumps({"ephemeral_commit_sha": "e" * 40, "summary": "untrusted model summary"}),
    )
    contract = PinnedCodexProcedure(
        workflow_key="site.health_improve",
        prompt="Improve the site.",
        entry_skill="site-health-improvement",
        skill_files={},
        result_kind=GITHUB_PULL_REQUEST_RESULT,
        workspace_kind=GITHUB_REPOSITORY_WORKSPACE,
        provider_key="infra.github",
        output_max_files=3,
        receipt_path_template="reports/site-health/{run_id}.md",
        verification_commands=("git diff --check",),
        allow_no_change=True,
    )
    monkeypatch.setattr(
        activities,
        "_pinned_codex_procedure",
        AsyncMock(
            return_value=(
                SimpleNamespace(key="site.health_improve", title="Improve site health"),
                contract,
            )
        ),
    )
    read_checkpoint = AsyncMock(
        return_value=json.dumps(site_manifest(no_change=no_change)).encode()
    )
    monkeypatch.setattr(storage, "read_ephemeral_artifact", read_checkpoint)
    publisher = AsyncMock(return_value=("f" * 40, True))
    monkeypatch.setattr(storage, "publish_state_document", publisher)
    create_pr = AsyncMock(
        return_value=SimpleNamespace(
            url="https://github.com/owner/site/pull/1",
            number=1,
            repository="owner/site",
            branch="tin/site-health",
        )
    )
    activities._integrations = SimpleNamespace(github_create_pull_request=create_pr)

    await activities.commit_codex_procedure_artifact(str(run.id))
    await activities.commit_codex_procedure_artifact(str(run.id))

    assert read_checkpoint.await_args.kwargs["path"] == procedure_checkpoint_path(run.id)
    assert publisher.await_count == 1
    assert publisher.await_args.kwargs["path"] == f"reports/site-health/{run.id}.md"
    receipt = publisher.await_args.kwargs["content"].decode()
    assert create_pr.await_count == (0 if no_change else 1)
    saved = await db.get_effect(f"{run.id}:procedure_canonical_commit")
    assert saved.status == "completed"
    if no_change:
        assert saved.result["summary"] != "untrusted model summary"
        assert saved.result["outcome"] == "no_change"
        assert saved.result["repository"] == "owner/site"
        assert saved.result["summary"].startswith("No change proposed")
        assert "external_url" not in saved.result
        assert "No change proposed; no pull request was opened." in receipt
        assert "**No change: metadata is complete**" in receipt
        events = await db.pool.fetch(
            "SELECT event_type FROM activity_events WHERE run_id=$1 ORDER BY id", run.id
        )
        assert [e["event_type"] for e in events].count("codex_procedure_no_change") == 1
    else:
        assert "outcome" not in saved.result
        assert saved.result["external_url"] == "https://github.com/owner/site/pull/1"
        assert "- `app/layout.tsx`" in receipt
        assert create_pr.await_args.kwargs["expected_base_sha"] == "b" * 40
    assert not (await db.get_run(run.id)).lease_active
