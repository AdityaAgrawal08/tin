from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from tin_lite import analytics
from tin_lite.analytics import PAYLOAD_CAP, Analytics, clip, redact
from tin_lite.mcp_server import analytics_middleware


def test_redact_hides_secret_looking_keys_recursively() -> None:
    value = {"api_key": "x", "nested": [{"Authorization": "y", "name": "ok"}], "token_count": 3}
    assert redact(value) == {
        "api_key": "[redacted]",
        "nested": [{"Authorization": "[redacted]", "name": "ok"}],
        "token_count": "[redacted]",
    }


def test_clip_keeps_small_values_and_cuts_large_ones() -> None:
    small, facts = clip({"a": 1})
    assert small == {"a": 1} and facts == {"bytes": 8, "truncated": False}
    big, facts = clip("x" * (PAYLOAD_CAP + 10))
    assert isinstance(big, str) and len(big) == PAYLOAD_CAP
    assert facts["truncated"] is True and facts["bytes"] == PAYLOAD_CAP + 12


def test_disabled_client_drops_everything() -> None:
    client = Analytics(None)
    client.capture("x", distinct_id="p")
    assert not client.enabled and client.sent == 0


@pytest.mark.asyncio
async def test_capture_batches_to_posthog() -> None:
    posted: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        posted.append(json.loads(request.content))
        return httpx.Response(200, json={"status": 1})

    client = Analytics("phc_test", "https://ph.example", source="test")
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client.capture(
        "mcp_tool_called",
        distinct_id="11111111-1111-4111-8111-111111111111",
        project_id="11111111-1111-4111-8111-111111111111",
        properties={"tool": "get_run", "arguments": {"token": "secret"}},
    )
    await client.flush()
    assert client.sent == 1 and posted[0]["api_key"] == "phc_test"
    event = posted[0]["batch"][0]
    assert event["event"] == "mcp_tool_called"
    assert event["properties"]["$groups"] == {"project": "11111111-1111-4111-8111-111111111111"}
    assert "arguments" not in event["properties"]
    assert event["properties"]["source"] == "test"
    await client.aclose()


@pytest.mark.asyncio
async def test_middleware_records_tool_calls_and_session_start(monkeypatch) -> None:
    client = analytics.configure("phc_test", "https://ph.example", source="test")
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        client,
        "capture",
        lambda event, **kw: calls.append((event, kw)),
    )
    monkeypatch.setattr(
        "tin_lite.mcp_server.get_access_token",
        lambda: SimpleNamespace(subject="user_1", client_id="client_1"),
    )
    session = SimpleNamespace(
        client_params=SimpleNamespace(client_info=SimpleNamespace(name="claude-code", version="2"))
    )
    result = SimpleNamespace(structured_content={"status": "succeeded"}, content=[], is_error=False)

    async def call_next(ctx):
        return result

    ctx = SimpleNamespace(
        method="tools/call",
        params={"name": "get_run", "arguments": {"project_id": "p1", "run_id": "r1"}},
        session=session,
    )
    assert await analytics_middleware(ctx, call_next) is result
    event, kw = calls[-1]
    assert event == "mcp_tool_called" and kw["distinct_id"] == "p1"
    props = kw["properties"]
    assert props["tool"] == "get_run" and "result" not in props and "arguments" not in props
    assert props["client_name"] == "claude-code" and props["clerk_user_id"] == "user_1"
    assert props["is_error"] is False and props["error_type"] is None

    async def failing(ctx):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await analytics_middleware(ctx, failing)
    assert calls[-1][1]["properties"]["error_type"] == "RuntimeError"

    init = SimpleNamespace(
        method="initialize",
        params={"clientInfo": {"name": "codex", "version": "1"}, "protocolVersion": "2025-06-18"},
        session=session,
    )
    await analytics_middleware(init, call_next)
    event, kw = calls[-1]
    assert event == "mcp_session_started" and kw["distinct_id"] == "user_1"
    assert kw["properties"]["client_name"] == "codex"

    other = SimpleNamespace(method="tools/list", params=None, session=session)
    before = len(calls)
    await analytics_middleware(other, call_next)
    assert len(calls) == before
    analytics.configure(None, "")


def test_large_structured_values_are_redacted_before_clipping():
    clipped, size = clip({"password": "SYNTHETIC_SECRET", "notes": "x" * (PAYLOAD_CAP + 10)})
    assert size["truncated"]
    assert "SYNTHETIC_SECRET" not in json.dumps(clipped)


@pytest.mark.asyncio
async def test_analytics_excludes_tool_content_errors_and_activity_prose(monkeypatch):
    client = Analytics("synthetic", "https://unused.invalid")
    monkeypatch.setattr(client, "_ensure_flusher", lambda: None)
    monkeypatch.setattr(analytics, "_current", client)
    monkeypatch.setattr(
        "tin_lite.mcp_server.get_access_token",
        lambda: SimpleNamespace(subject="member", client_id="client"),
    )
    ctx = SimpleNamespace(
        method="tools/call",
        params={
            "name": "read_project_file",
            "arguments": {
                "project_id": "project",
                "content": "PRIVATE_REQUEST",
                "password": "PRIVATE_SECRET",
                "notes": "PRIVATE_NOTE" * 7000,
            },
        },
        session=None,
    )

    async def content(_):
        return SimpleNamespace(structured_content={"content": "PRIVATE_RESPONSE"}, is_error=False)

    async def failure(_):
        raise RuntimeError("PRIVATE_ERROR")

    await analytics_middleware(ctx, content)
    with pytest.raises(RuntimeError):
        await analytics_middleware(ctx, failure)
    client.capture(
        "activity_ready",
        distinct_id="project",
        properties={
            "run_id": "run",
            "summary": "PRIVATE_SUMMARY",
            "details": {"text": "PRIVATE_DETAILS"},
            "view": "PRIVATE_PLAN",
            "connections": {"note": "PRIVATE_REASON"},
        },
    )
    assert "PRIVATE_" not in json.dumps(list(client._queue))
    assert client._queue[0]["properties"]["result_bytes"] > 0
    assert client._queue[-1]["properties"]["run_id"] == "run"
