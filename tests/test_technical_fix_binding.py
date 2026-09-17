from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from tin_lite.integrations import (
    GITHUB_PROVIDER,
    IntegrationAuthorizationError,
    IntegrationError,
    IntegrationService,
    IntegrationUpstreamError,
)


@pytest.fixture
async def binding_fixture():
    project_id = uuid4()
    connection = SimpleNamespace(
        id=uuid4(),
        project_id=project_id,
        provider_key=GITHUB_PROVIDER,
        status="connected",
        external_account_id="123",
        updated_at=datetime.now(UTC),
        configuration={
            "selected_repository": "owner/site",
            "write_opted_in": True,
            "permissions": {"contents": "write", "pull_requests": "write"},
        },
    )
    db = SimpleNamespace(get_integration_connection=AsyncMock(return_value=connection))
    requests = []
    payloads = {
        "/repos/owner/site": {"id": 456, "full_name": "owner/site", "default_branch": "main"},
        "/repos/owner/site/git/ref/heads/main": {"object": {"type": "commit", "sha": "b" * 40}},
    }

    def handler(request):
        requests.append(request)
        assert request.method == "GET"
        assert request.headers["authorization"] == "Bearer synthetic-token"
        return httpx.Response(200, json=payloads[request.url.path])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = IntegrationService(
            database=db,
            settings=SimpleNamespace(integration_credential_key=None),
            client=client,
        )
        service._github_installation_token = AsyncMock(return_value="synthetic-token")
        yield SimpleNamespace(
            project_id=project_id,
            connection=connection,
            db=db,
            requests=requests,
            payloads=payloads,
            service=service,
        )


async def bind(f, repository="owner/site"):
    return await f.service.github_repository_binding(
        project_id=f.project_id,
        expected_repository=repository,
    )


async def test_binding_captures_provider_identity_and_pinned_base_without_checkout_or_writes(
    binding_fixture,
):
    f = binding_fixture
    result = await bind(f)
    assert result.connection_id == f.connection.id
    assert (result.installation_id, result.repository_id) == (123, 456)
    assert (result.repository, result.default_branch, result.head_sha) == (
        "owner/site",
        "main",
        "b" * 40,
    )
    assert len(f.requests) == 2
    assert f.db.get_integration_connection.await_count == 2
    f.service._github_installation_token.assert_awaited_once_with(123)


@pytest.mark.parametrize(
    "repository",
    [
        "other/site",
        "owner/other",
        "owner",
        "owner/a/b",
        "../site",
        "owner/..",
        "owner/.",
        "owner/site?token=x",
        "owner/site\n",
        "owner/site#ref",
        "owner/site%2felse",
    ],
)
async def test_mismatched_or_unsafe_selection_fails_before_token_or_github_reads(
    binding_fixture, repository
):
    f = binding_fixture
    with pytest.raises(IntegrationAuthorizationError):
        await bind(f, repository)
    assert f.requests == []
    f.service._github_installation_token.assert_not_awaited()


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "project",
        "provider",
        "disconnected",
        "opt_out",
        "read_only",
        "no_pr",
        "permissions_shape",
        "bad_installation",
        "zero_installation",
    ],
)
async def test_missing_or_insufficient_connection_fails_before_provider_reads(
    binding_fixture, change
):
    f = binding_fixture
    c = f.connection
    if change == "missing":
        f.db.get_integration_connection.return_value = None
    elif change == "project":
        c.project_id = uuid4()
    elif change == "provider":
        c.provider_key = "workspace.google"
    elif change == "disconnected":
        c.status = "disconnected"
    elif change == "opt_out":
        c.configuration["write_opted_in"] = False
    elif change == "read_only":
        c.configuration["permissions"]["contents"] = "read"
    elif change == "no_pr":
        c.configuration["permissions"].pop("pull_requests")
    elif change == "permissions_shape":
        c.configuration["permissions"] = []
    elif change == "bad_installation":
        c.external_account_id = "bad"
    else:
        c.external_account_id = "0"
    with pytest.raises(IntegrationAuthorizationError):
        await bind(f)
    assert f.requests == []
    f.service._github_installation_token.assert_not_awaited()


@pytest.mark.parametrize(
    "change",
    [
        "repository_id",
        "boolean_id",
        "name",
        "branch",
        "branch_control",
        "archived",
        "disabled",
        "head",
        "non_commit",
        "malformed_object",
    ],
)
async def test_malformed_or_wrong_provider_identity_never_becomes_a_binding(
    binding_fixture, change
):
    f = binding_fixture
    repo = f.payloads["/repos/owner/site"]
    target = f.payloads["/repos/owner/site/git/ref/heads/main"]
    if change == "repository_id":
        repo["id"] = "456"
    elif change == "boolean_id":
        repo["id"] = True
    elif change == "name":
        repo["full_name"] = "different/site"
    elif change == "branch":
        repo["default_branch"] = "../main"
    elif change == "branch_control":
        repo["default_branch"] = "main\n"
    elif change == "archived":
        repo["archived"] = True
    elif change == "disabled":
        repo["disabled"] = True
    elif change == "head":
        target["object"]["sha"] = "not-a-sha"
    elif change == "non_commit":
        target["object"]["type"] = "tag"
    else:
        target["object"] = []
    with pytest.raises(IntegrationUpstreamError):
        await bind(f)


@pytest.mark.parametrize(
    "change",
    ["connection", "installation", "selection", "opt_out", "permission", "revision", "removed"],
)
async def test_connection_changes_during_reads_invalidate_preview(binding_fixture, change):
    f = binding_fixture
    current = deepcopy(f.connection)
    if change == "connection":
        current.id = uuid4()
    elif change == "installation":
        current.external_account_id = "999"
    elif change == "selection":
        current.configuration["selected_repository"] = "owner/another"
    elif change == "opt_out":
        current.configuration["write_opted_in"] = False
    elif change == "permission":
        current.configuration["permissions"]["contents"] = "read"
    elif change == "revision":
        current.updated_at += timedelta(seconds=1)
    else:
        current = None
    f.db.get_integration_connection.side_effect = [f.connection, current]
    with pytest.raises(IntegrationAuthorizationError):
        await bind(f)
    assert len(f.requests) == 2


@pytest.mark.parametrize("stage", ["token", "read"])
async def test_network_errors_do_not_expose_auth_or_provider_details(
    binding_fixture, stage, monkeypatch
):
    f = binding_fixture
    error = httpx.ConnectError("Authorization: synthetic-token upstream-private-details")
    if stage == "token":
        f.service._github_installation_token.side_effect = error
    else:
        monkeypatch.setattr(f.service._client, "get", AsyncMock(side_effect=error))
    with pytest.raises(IntegrationError) as failure:
        await bind(f)
    assert "synthetic-token" not in str(failure.value)
    assert "upstream-private-details" not in str(failure.value)
