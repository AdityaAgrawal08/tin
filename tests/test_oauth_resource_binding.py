"""Synthetic Clerk responses exercise the shared OAuth admission boundary."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, HTTPException
from pydantic import SecretStr

from tin_lite.auth import AuthContext, ClerkAuth
from tin_lite.mcp_server import ClerkOAuthTokenVerifier, create_mcp_app
from tin_lite.project_connections_api import router
from tin_lite.settings import Settings

RESOURCE = "https://tin.test/mcp"
ISSUER = "https://clerk.tin.test"
CLIENT = "registered_tin_client"
CIMD = "https://agent.example/oauth/client.json"
NOW = 1_800_000_000
USER = "user_Synthetic"


def verified_payload(**changes):
    return {
        "object": "clerk_idp_oauth_access_token",
        "subject": USER,
        "client_id": CLIENT,
        "scopes": ["openid"],
        "revoked": False,
        "expired": False,
        "expiration": NOW + 300,
        **changes,
    }


@asynccontextmanager
async def identity(payload, clients=frozenset({CLIENT, CIMD}), *, status_code=200, token=None):
    settings = SimpleNamespace(
        clerk_secret_key=SecretStr("synthetic-clerk-key"),
        clerk_jwt_key=None,
        clerk_authorized_parties=("https://tin.test",),
        mcp_oauth_client_ids=clients,
        switchboard_public_url="https://tin.test/",
        clerk_frontend_api_url=ISSUER,
    )
    auth = ClerkAuth(settings)
    await auth.close()

    def verify(request):
        assert str(request.url) == "https://api.clerk.com/oauth_applications/access_tokens/verify"
        assert request.headers["authorization"] == "Bearer synthetic-clerk-key"
        assert json.loads(request.content) == {"access_token": token or "synthetic-access-token"}
        return httpx.Response(status_code, json=payload)

    auth._client = httpx.AsyncClient(  # noqa: SLF001 -- synthetic upstream transport
        transport=httpx.MockTransport(verify),
        headers={"Authorization": "Bearer synthetic-clerk-key"},
    )
    try:
        yield auth, settings
    finally:
        await auth.close()


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr("tin_lite.auth.time.time", lambda: NOW)


@pytest.mark.parametrize(
    "claims",
    [
        {},
        {"client_id": CIMD},
        {"aud": RESOURCE},
        {"audience": [RESOURCE]},
        {"aud": ["https://another.test/mcp", RESOURCE], "resource": RESOURCE},
        {"aud": RESOURCE, "iss": ISSUER, "azp": CLIENT},
        {"expiration": None},
        {"expiration": float(NOW + 300)},
    ],
)
async def test_explicit_client_policy_binds_verified_tokens_to_tin(claims):
    async with identity(verified_payload(**claims)) as (auth, _):
        result = await ClerkOAuthTokenVerifier(auth, resource=RESOURCE).verify_token(
            "synthetic-access-token"
        )
    assert result is not None
    assert result.client_id == claims.get("client_id", CLIENT)
    assert result.subject == USER
    assert result.resource == RESOURCE
    assert result.expires_at == (None if claims.get("expiration", 1) is None else NOW + 300)


@pytest.mark.parametrize(
    "claims",
    [
        {"client_id": "unknown"},
        {"client_id": None},
        {"client_id": [CLIENT]},
        {"client_id": CLIENT.upper()},
        {"client_id": CIMD + "/"},
        {"client_id": "https://agent.example/another-client.json"},
        {"aud": "https://another.test/mcp"},
        {"resource": "https://another.test/mcp"},
        {"aud": RESOURCE, "resource": "https://another.test/mcp"},
        {"aud": RESOURCE + "/"},
        {"aud": RESOURCE + "?resource=other"},
        {"aud": "https://legacy.tin.test/mcp"},
        {"aud": None},
        {"aud": []},
        {"aud": [RESOURCE, 123]},
        {"aud": {"resource": RESOURCE}},
        {"audience": False},
        {"iss": "https://another-clerk.test"},
        {"iss": ISSUER, "issuer": "https://another-clerk.test"},
        {"azp": "unknown"},
        {"revoked": True},
        {"revoked": 0},
        {"expired": True},
        {"expired": "false"},
        {"active": False},
        {"active": 1},
        {"expiration": NOW},
        {"expiration": NOW - 1},
        {"expiration": True},
        {"expiration": "1800000300"},
        {"expires_at": NOW - 1},
        {"exp": False},
        {"scopes": ["profile"]},
        {"subject": "org_Synthetic"},
    ],
)
async def test_invalid_binding_or_token_state_is_rejected(claims):
    async with identity(verified_payload(**claims)) as (auth, _):
        assert await auth.authenticate_oauth_token("synthetic-access-token") is None


@pytest.mark.parametrize("missing", ["revoked", "expired", "expiration", "client_id"])
async def test_incomplete_verified_response_fails_closed(missing):
    payload = verified_payload()
    del payload[missing]
    async with identity(payload) as (auth, _):
        assert await auth.authenticate_oauth_token("synthetic-access-token") is None


@pytest.mark.parametrize("status_code", [401, 403, 429, 500])
async def test_upstream_verification_errors_fail_closed(status_code):
    async with identity(verified_payload(), status_code=status_code) as (auth, _):
        assert await auth.authenticate_oauth_token("synthetic-access-token") is None


async def test_unconfigured_legacy_policy_rejects_unbound_tokens():
    async with identity(verified_payload(), clients=frozenset()) as (auth, _):
        assert await auth.authenticate_oauth_token("synthetic-access-token") is None


@pytest.mark.parametrize("client_id", ["fresh_dynamic_client", CIMD])
async def test_trusted_introspection_binding_needs_no_operator_enrollment(client_id):
    async with identity(
        verified_payload(client_id=client_id, aud=RESOURCE), clients=frozenset()
    ) as (auth, _):
        result = await auth.authenticate_oauth_token("synthetic-access-token")
    assert result is not None
    assert result.client_id == client_id
    assert result.resource == RESOURCE


@pytest.mark.parametrize("resource", [None, "https://another.test/mcp"])
async def test_mcp_adapter_never_assigns_a_missing_or_different_resource(resource):
    context = AuthContext(USER, "oauth_token", client_id=CLIENT, resource=resource)  # noqa: S106
    auth = SimpleNamespace(authenticate_oauth_token=AsyncMock(return_value=context))
    assert await ClerkOAuthTokenVerifier(auth, resource=RESOURCE).verify_token("synthetic") is None


def test_legacy_client_setting_preserves_exact_identity_and_defaults_to_empty():
    assert Settings.model_construct().mcp_oauth_client_ids == frozenset()
    settings = Settings.model_construct(mcp_oauth_client_ids_raw=f" {CLIENT}, {CIMD}/, {CIMD}, ")
    assert settings.mcp_oauth_client_ids == frozenset({CLIENT, CIMD, CIMD + "/"})


@pytest.mark.parametrize(
    "claims", [{}, {"client_id": "unknown"}, {"resource": "https://other.test/mcp"}]
)
async def test_mcp_http_applies_real_verifier_before_dispatch(claims):
    async with identity(verified_payload(**claims)) as (auth, settings):
        _, app = create_mcp_app(settings=settings, auth=auth, runtime=lambda: SimpleNamespace())
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://tin.test"
            ) as client,
        ):
            response = await client.post(
                "/mcp",
                headers={
                    "Authorization": "Bearer synthetic-access-token",
                    "Accept": "application/json, text/event-stream",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "synthetic", "version": "1"},
                    },
                },
            )
    assert response.status_code == (401 if claims else 200)


@pytest.mark.parametrize(
    "claims",
    [{}, {"client_id": "unknown"}, {"resource": "https://other.test/mcp"}, {"expired": True}],
)
async def test_connection_setup_uses_same_binding_before_effects(claims):
    project_id = uuid4()
    async with identity(verified_payload(**claims)) as (auth, _):
        auth.authenticate_session = AsyncMock(side_effect=HTTPException(status_code=401))
        record = AsyncMock()
        secrets = AsyncMock(return_value=[])
        app = FastAPI()
        app.state.auth = auth
        app.state.runtime = SimpleNamespace(
            database=SimpleNamespace(record_tin_user=record),
            integrations=SimpleNamespace(custom=SimpleNamespace(secrets=secrets)),
        )
        app.include_router(router)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://spoofed.test"
        ) as client:
            response = await client.get(
                f"/api/projects/{project_id}/connections/secrets",
                headers={"Authorization": "Bearer synthetic-access-token"},
            )
    assert response.status_code == (401 if claims else 200)
    if claims:
        record.assert_not_awaited()
        secrets.assert_not_awaited()
    else:
        record.assert_awaited_once_with(USER)
        secrets.assert_awaited_once_with(project_id, USER)


async def test_browser_session_setup_does_not_require_oauth_client_admission():
    context = AuthContext(USER, "session_token")  # noqa: S106
    auth = SimpleNamespace(
        authenticate_session=AsyncMock(return_value=context),
        authenticate_oauth_token=AsyncMock(side_effect=AssertionError("OAuth must not run")),
    )
    app = FastAPI()
    app.state.auth = auth
    app.state.runtime = SimpleNamespace(
        database=SimpleNamespace(record_tin_user=AsyncMock()),
        integrations=SimpleNamespace(custom=SimpleNamespace(secrets=AsyncMock(return_value=[]))),
    )
    app.include_router(router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://tin.test"
    ) as client:
        response = await client.get(f"/api/projects/{uuid4()}/connections/secrets")
    assert response.status_code == 200


@pytest.fixture(scope="module")
def signing_keys():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = (
        private.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private, public


@pytest.mark.parametrize("client_id", ["fresh_dynamic_client", CIMD])
@pytest.mark.parametrize("token_type", ["JWT", "at+jwt"])
async def test_signed_resource_binding_survives_introspection_omitting_audience(
    signing_keys, client_id, token_type
):
    private, public = signing_keys
    token = jwt.encode(
        {"iss": ISSUER, "sub": USER, "client_id": client_id, "aud": RESOURCE, "exp": NOW + 200},
        private,
        algorithm="RS256",
        headers={"typ": token_type},
    )
    async with identity(
        verified_payload(client_id=client_id), clients=frozenset(), token=token
    ) as (auth, _):
        auth._jwt_key = public  # noqa: SLF001
        result = await auth.authenticate_oauth_token(token)
    assert result is not None
    assert result.resource == RESOURCE
    assert result.expires_at == NOW + 200


@pytest.mark.parametrize(
    "changes",
    [
        {"aud": None},
        {"aud": []},
        {"aud": [RESOURCE, 1]},
        {"aud": "https://other.test/mcp"},
        {"aud": RESOURCE + "/"},
        {"resource": "https://other.test/mcp"},
        {"issuer": "https://other.test"},
        {"iss": "https://other-clerk.test"},
        {"sub": "user_Other"},
        {"client_id": "another_client"},
        {"azp": "another_client"},
        {"sid": "sess_synthetic"},
        {"exp": 1},
        {"exp": None},
        {"exp": True},
    ],
)
async def test_signed_claim_conflicts_cannot_be_overridden(signing_keys, changes):
    private, public = signing_keys
    token = jwt.encode(
        {
            "iss": ISSUER,
            "sub": USER,
            "client_id": CLIENT,
            "aud": RESOURCE,
            "exp": NOW + 300,
            **changes,
        },
        private,
        algorithm="RS256",
    )
    # Even explicit legacy admission and a good introspection audience cannot
    # override a conflicting signed claim or turn a session into an access token.
    async with identity(verified_payload(aud=RESOURCE), token=token) as (auth, _):
        auth._jwt_key = public  # noqa: SLF001
        assert await auth.authenticate_oauth_token(token) is None


@pytest.mark.parametrize("missing", ["aud", "iss", "sub", "client_id", "exp"])
async def test_new_clients_need_complete_signed_binding(signing_keys, missing):
    private, public = signing_keys
    claims = {"iss": ISSUER, "sub": USER, "client_id": CLIENT, "aud": RESOURCE, "exp": NOW + 300}
    del claims[missing]
    token = jwt.encode(claims, private, algorithm="RS256")
    async with identity(verified_payload(), clients=frozenset(), token=token) as (auth, _):
        auth._jwt_key = public  # noqa: SLF001
        assert await auth.authenticate_oauth_token(token) is None


async def test_forged_resource_claim_is_not_authority(signing_keys):
    _, public = signing_keys
    forged = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(
        {"iss": ISSUER, "sub": USER, "client_id": CLIENT, "aud": RESOURCE, "exp": NOW + 300},
        forged,
        algorithm="RS256",
    )
    async with identity(verified_payload(), clients=frozenset(), token=token) as (auth, _):
        auth._jwt_key = public  # noqa: SLF001
        assert await auth.authenticate_oauth_token(token) is None


@pytest.mark.parametrize("revoked", [False, True])
async def test_fresh_dynamic_client_through_mcp_http(signing_keys, revoked):
    private, public = signing_keys
    token = jwt.encode(
        {
            "iss": ISSUER,
            "sub": USER,
            "client_id": "new_dcr_client",
            "aud": RESOURCE,
            "exp": NOW + 300,
        },
        private,
        algorithm="RS256",
        headers={"kid": "synthetic-key"},
    )
    async with identity(
        verified_payload(client_id="new_dcr_client", revoked=revoked),
        clients=frozenset(),
        token=token,
    ) as (auth, settings):
        auth._jwt_key = public  # noqa: SLF001
        _, app = create_mcp_app(settings=settings, auth=auth, runtime=lambda: SimpleNamespace())
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://tin.test"
            ) as client,
        ):
            response = await client.post(
                "/mcp",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json, text/event-stream",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "synthetic", "version": "1"},
                    },
                },
            )
    assert response.status_code == (401 if revoked else 200)


async def test_jwt_keys_only_come_from_configured_clerk_issuer(signing_keys, monkeypatch):
    private, _ = signing_keys
    token = jwt.encode(
        {"iss": ISSUER, "sub": USER, "client_id": CLIENT, "aud": RESOURCE, "exp": NOW + 300},
        private,
        algorithm="RS256",
        headers={"kid": "synthetic-key", "jku": "https://untrusted.test/jwks"},
    )
    key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    key["kid"] = "synthetic-key"
    async with identity(verified_payload(), clients=frozenset(), token=token) as (auth, _):
        assert auth._oauth_jwks.uri == f"{ISSUER}/.well-known/jwks.json"  # noqa: SLF001
        monkeypatch.setattr(auth._oauth_jwks, "fetch_data", lambda: {"keys": [key]})  # noqa: SLF001
        assert await auth.authenticate_oauth_token(token) is not None


@pytest.mark.parametrize("transport", ["bearer", "cookie"])
@pytest.mark.parametrize(
    "claims, token_type, accepted",
    [
        ({"sid": "sess_synthetic", "azp": "https://tin.test"}, "JWT", True),
        ({"sid": "sess_synthetic"}, "JWT", True),
        ({"client_id": "unknown", "scope": "openid"}, "JWT", False),
        ({"client_id": CLIENT, "scope": "openid"}, "JWT", False),
        ({"sid": None}, "JWT", False),
        ({"sid": ""}, "JWT", False),
        ({"sid": "not_a_session"}, "JWT", False),
        ({"sid": "sess_synthetic"}, "at+jwt", False),
    ],
)
async def test_signed_jwt_cannot_bypass_oauth_policy_as_a_session(
    signing_keys, transport, claims, token_type, accepted
):
    private, public = signing_keys
    token = jwt.encode(
        {"iss": ISSUER, "sub": USER, "exp": NOW + 300, **claims},
        private,
        algorithm="RS256",
        headers={"typ": token_type},
    )
    payload = verified_payload(client_id=claims.get("client_id", "unknown"))
    async with identity(payload, token=token) as (auth, _):
        auth._jwt_key = public  # noqa: SLF001 -- real SDK verifies the synthetic signature
        auth.authenticate_oauth_token = AsyncMock(wraps=auth.authenticate_oauth_token)
        record = AsyncMock()
        secrets = AsyncMock(return_value=[])
        app = FastAPI()
        app.state.auth = auth
        app.state.runtime = SimpleNamespace(
            database=SimpleNamespace(record_tin_user=record),
            integrations=SimpleNamespace(custom=SimpleNamespace(secrets=secrets)),
        )
        app.include_router(router)
        headers = (
            {"Authorization": f"Bearer {token}"}
            if transport == "bearer"
            else {"Cookie": f"__session={token}"}
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://tin.test"
        ) as client:
            response = await client.get(
                f"/api/projects/{uuid4()}/connections/secrets", headers=headers
            )
    session_accepted = accepted and (transport == "bearer" or "azp" in claims)
    oauth_accepted = transport == "bearer" and claims.get("client_id") == CLIENT
    assert response.status_code == (200 if session_accepted or oauth_accepted else 401)
    if transport == "bearer" and not session_accepted:
        auth.authenticate_oauth_token.assert_awaited_once_with(token)
    else:
        auth.authenticate_oauth_token.assert_not_awaited()
    if not (session_accepted or oauth_accepted):
        record.assert_not_awaited()
        secrets.assert_not_awaited()
