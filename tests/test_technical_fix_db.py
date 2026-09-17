from uuid import uuid4

from test_procedure_publication import activity_fixture
from test_procedure_publication import publication_db as publication_db

from tin_lite.technical_fix_sources import TechnicalFixSources


async def test_source_projection_uses_real_project_status_and_executor_filters(publication_db):
    db = publication_db
    _, _, run, _ = await activity_fixture(db)
    # No storage object is available: listing must be an ordinary Postgres projection.
    service = TechnicalFixSources(database=db, storage=None)
    assert (await service.list_sources(project_id=run.project_id))["sources"] == []
    await db.pool.execute(
        """UPDATE workflow_runs SET executor='organic.audit', status='succeeded',
        canonical_commit_sha=$2, input='{"site_url":"https://example.com/"}'::jsonb
        WHERE id=$1""",
        run.id,
        "a" * 40,
    )
    sources = (await service.list_sources(project_id=run.project_id))["sources"]
    assert len(sources) == 1
    assert sources[0]["id"] == run.id
    assert sources[0]["site_url"] == "https://example.com/"
    assert sources[0]["canonical_commit_sha"] == "a" * 40
    assert (await service.list_sources(project_id=uuid4()))["sources"] == []
    assert (await service.list_sources(project_id=run.project_id, offset=1))["sources"] == []
    await db.pool.execute("UPDATE workflow_runs SET status='failed' WHERE id=$1", run.id)
    assert (await service.list_sources(project_id=run.project_id))["sources"] == []
    await db.pool.execute(
        "UPDATE workflow_runs SET status='succeeded', canonical_commit_sha=NULL WHERE id=$1",
        run.id,
    )
    assert (await service.list_sources(project_id=run.project_id))["sources"] == []
