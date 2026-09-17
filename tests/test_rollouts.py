from __future__ import annotations

import asyncio
import base64
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from e2b import FileType, NotFoundException

from tin_lite import cli, e2b_runtime
from tin_lite.db import _run_rollout
from tin_lite.domain import RunRollout
from tin_lite.e2b_runtime import (
    E2BRuntime,
    SandboxProcedureInput,
    SandboxRunInput,
    SandboxTaskInput,
    collect_rollouts,
)
from tin_lite.rollouts import (
    RolloutCapture,
    parse_rollout_filename,
    redact_rollout,
    render_rollout_trace,
    sandbox_secrets,
)

THREAD = "01a067a2-adff-7cc1-96d8-7477d87f7eb2"
ROLLOUT_NAME = f"rollout-2026-09-04T10-00-00-{THREAD}.jsonl"
SESSIONS = "/home/user/.codex/sessions"


def entry(path: str, *, kind: FileType, size: int = 0) -> SimpleNamespace:
    return SimpleNamespace(name=path.rsplit("/", 1)[1], path=path, type=kind, size=size)


class FakeFiles:
    """A minimal stand-in for E2B's Filesystem with a YYYY/MM/DD tree."""

    def __init__(self, files: dict[str, bytes], *, failing: set[str] = frozenset()) -> None:
        self.files = files
        self.failing = failing
        self.calls: list[tuple[str, str]] = []

    async def write(self, path: str, data) -> None:
        self.calls.append(("write", path))

    async def list(self, path: str, *, depth: int = 1, request_timeout=None):
        self.calls.append(("list", path))
        assert depth == 1
        children: dict[str, SimpleNamespace] = {}
        found = False
        for file_path, content in self.files.items():
            if not file_path.startswith(path + "/"):
                continue
            found = True
            rest = file_path[len(path) + 1 :]
            head, _, tail = rest.partition("/")
            child = f"{path}/{head}"
            if tail:
                children[child] = entry(child, kind=FileType.DIR)
            else:
                children[child] = entry(child, kind=FileType.FILE, size=len(content))
        if not found:
            raise NotFoundException(path)
        return list(children.values())

    async def read(self, path: str, *, format: str = "text", request_timeout=None):
        self.calls.append(("read", path))
        assert format == "bytes"
        if path in self.failing:
            raise TimeoutError(path)
        return bytearray(self.files[path])


def rollout_bytes(*lines: dict) -> bytes:
    return "".join(json.dumps(line) + "\n" for line in lines).encode()


# --- filename parsing ---------------------------------------------------------------


def test_rollout_filename_parsing_accepts_only_codex_rollouts() -> None:
    assert parse_rollout_filename(ROLLOUT_NAME) == ("2026-09-04T10-00-00", THREAD)
    assert parse_rollout_filename("rollout-2026-09-04T10-00-00-nope.jsonl") is None
    assert parse_rollout_filename(f"../{ROLLOUT_NAME}") is None
    assert parse_rollout_filename("history.jsonl") is None


# --- secrets and redaction ------------------------------------------------------------


def test_sandbox_secrets_cover_every_form_the_sandbox_could_echo() -> None:
    blob = base64.b64encode(b"t:code-storage-token-value").decode()
    secrets = sandbox_secrets(
        canonical_auth_header=f"Authorization: Basic {blob}",
        ephemeral_auth_header=f"Authorization: Basic {blob}",
        proxy_url="http://warp:proxy-pass-word@proxy.test:3128",
        run_tools_grant="run-tools-grant-value",
        extra=("pw-secret-123", "broker-grant-value", ""),
    )
    assert f"Authorization: Basic {blob}" in secrets
    assert blob in secrets
    assert "t:code-storage-token-value" in secrets
    assert "code-storage-token-value" in secrets
    assert "http://warp:proxy-pass-word@proxy.test:3128" in secrets
    assert "proxy-pass-word" in secrets
    assert "warp:proxy-pass-word" in secrets
    assert "run-tools-grant-value" in secrets
    assert "pw-secret-123" in secrets
    assert "" not in secrets
    assert list(secrets) == sorted(secrets, key=len, reverse=True)


def test_redaction_removes_exact_secrets_and_escaped_forms_longest_first() -> None:
    blob = base64.b64encode(b"t:tok").decode()
    header = f"Authorization: Basic {blob}"
    content = json.dumps(
        {"output": f'env shows {header} and quoted "{blob}" and password pw"1'}
    ).encode()
    redacted, count = redact_rollout(content, (header, blob, 'pw"1'))
    text = redacted.decode()
    assert blob not in text
    assert "Authorization" not in text  # the whole header is one secret
    assert 'pw\\"1' not in text
    assert count >= 3


def test_redaction_catches_token_shapes_without_known_secrets() -> None:
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV"
    content = (
        f"Bearer {jwt}\n"
        'auth.json: {"access_token": "abcdefghijklmnop", "refresh_token": "qrstuvwxyz1234"}\n'
        'tool output: {\\"api_key\\": \\"sk-live-1234567890abcdef\\"}\n'
        "TIN_BROKER_GRANT=abc123def456 HTTPS_PROXY=http://u:p@proxy:3128\n"
        "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456 ya29.a0AfH6SMBxxxxxxxxxxxxxxxxxxxxxxxx\n"
    ).encode()
    redacted, count = redact_rollout(content, ())
    text = redacted.decode()
    for leaked in (
        jwt,
        "abcdefghijklmnop",
        "qrstuvwxyz1234",
        "sk-live-1234567890abcdef",
        "abc123def456",
        "http://u:p@proxy:3128",
        "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
        "ya29.a0AfH6SMB",
    ):
        assert leaked not in text, leaked
    assert "Bearer [redacted]" in text
    assert '"access_token": "[redacted]"' in text
    assert "TIN_BROKER_GRANT=[redacted]" in text
    assert count >= 8


def test_redaction_always_returns_valid_utf8() -> None:
    redacted, _ = redact_rollout(b"secret \xff\xfe tail", ("secret",))
    assert redacted.decode("utf-8") == "[redacted] �� tail"


# --- collector ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_collector_walks_the_dated_tree_sorts_and_redacts() -> None:
    older = f"rollout-2026-09-03T09-00-00-{THREAD}.jsonl"
    files = FakeFiles(
        {
            f"{SESSIONS}/2026/09/04/{ROLLOUT_NAME}": b'{"grant":"broker-grant-value"}\n',
            f"{SESSIONS}/2026/09/03/{older}": b"{}\n",
            f"{SESSIONS}/2026/09/03/history.jsonl": b"ignored\n",
        }
    )
    capture = await collect_rollouts(files, sandbox_id="sbx", redact=("broker-grant-value",))
    assert [file.filename for file in capture.files] == [older, ROLLOUT_NAME]
    assert capture.files[1].thread_id == THREAD
    assert capture.files[1].content == b'{"grant":"[redacted]"}\n'
    assert capture.files[1].redactions == 1
    assert capture.skipped == 0
    assert capture.error is None
    assert ("read", f"{SESSIONS}/2026/09/03/history.jsonl") not in files.calls


@pytest.mark.asyncio
async def test_collector_returns_empty_capture_when_codex_never_started() -> None:
    capture = await collect_rollouts(FakeFiles({}), sandbox_id="sbx", redact=())
    assert capture == RolloutCapture(sandbox_id="sbx", files=())


@pytest.mark.asyncio
async def test_collector_bounds_file_count_size_and_survives_a_failing_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(e2b_runtime, "ROLLOUT_FILE_MAX_BYTES", 8)
    monkeypatch.setattr(e2b_runtime, "ROLLOUT_TOTAL_MAX_BYTES", 12)
    monkeypatch.setattr(e2b_runtime, "ROLLOUT_MAX_FILES", 4)
    names = [f"rollout-2026-09-04T10-00-0{i}-{THREAD[:-1]}{i}.jsonl" for i in range(6)]
    tree = {f"{SESSIONS}/2026/09/04/{name}": b"12345\n" for name in names}
    tree[f"{SESSIONS}/2026/09/04/{names[1]}"] = b"this file is far too large\n"
    files = FakeFiles(tree, failing={f"{SESSIONS}/2026/09/04/{names[2]}"})

    capture = await collect_rollouts(files, sandbox_id="sbx", redact=())

    by_name = {file.filename: file for file in capture.files}
    assert names[0] in by_name and not by_name[names[0]].truncated
    assert by_name[names[1]].truncated and by_name[names[1]].content == b""
    assert names[2] not in by_name  # failing read
    assert capture.error == "TimeoutError"
    # names[3] fits (total 12), names[4]/names[5] are beyond ROLLOUT_MAX_FILES.
    assert names[4] not in by_name and names[5] not in by_name
    assert capture.skipped == 2


# --- runtime wiring --------------------------------------------------------------------


def base_values() -> dict:
    return dict(
        execution_key="run:persist",
        canonical_url="https://storage.test/canonical",
        canonical_auth_header="Authorization: Basic Y2Fub25pY2Fs",
        canonical_branch="main",
        ephemeral_url="https://storage.test/ephemeral",
        ephemeral_auth_header="Authorization: Basic ZXBoZW1lcmFs",
        ephemeral_branch="generations/run/1",
        proxy_url="http://proxy.test:8888",
        no_proxy="tin.test",
    )


def run_input(**overrides) -> SandboxRunInput:
    return SandboxRunInput(**base_values(), **overrides)


class RecordingSandbox:
    def __init__(self, stdout: str, files: FakeFiles) -> None:
        self.order: list[str] = []
        self.files = files
        self.commands = SimpleNamespace(run=self._run)
        self._stdout = stdout

    async def _run(self, *args, **kwargs):
        if args and args[0].endswith("isolated-procedure check"):
            return SimpleNamespace(stdout="TIN_ISOLATION_READY_V1")
        if args and args[0].endswith("run-task --check-api"):
            return SimpleNamespace(stdout="TIN_TASK_API_READY_V1")
        if args and args[0].endswith("codex_api_config.py --check"):
            return SimpleNamespace(stdout="TIN_CODEX_API_READY_V1")
        handle = SimpleNamespace(wait=self._wait)
        if kwargs.get("background"):
            return handle
        return await self._wait()

    async def _wait(self):
        return SimpleNamespace(stdout=self._stdout)

    async def kill(self) -> None:
        self.order.append("kill")


def runtime_with(monkeypatch: pytest.MonkeyPatch, sandbox) -> E2BRuntime:
    async def connect(*args, **kwargs):
        return sandbox

    monkeypatch.setattr("tin_lite.e2b_runtime.AsyncSandbox.connect", connect)
    return E2BRuntime(api_key="k", template="t", timeout_seconds=10, egress_allow_hosts=())


@pytest.mark.asyncio
async def test_procedure_run_hands_redacted_rollouts_to_the_sink_before_kill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = base64.b64encode(json.dumps({"summary": "done", "message": "ok"}).encode()).decode()
    files = FakeFiles(
        {
            f"{SESSIONS}/2026/09/04/{ROLLOUT_NAME}": (
                b'{"env":"TIN_EPHEMERAL_AUTH_HEADER=Authorization: Basic ZXBoZW1lcmFs '
                b'grant=broker-grant-value tools=run-tools-grant-value pw=pw-secret-123"}\n'
            )
        }
    )
    sandbox = RecordingSandbox(
        f"TIN_PROCEDURE_COMMIT_SHA={'c' * 40}\nTIN_PROCEDURE_RESULT={payload}\n", files
    )
    captures: list[RolloutCapture] = []

    async def sink(capture: RolloutCapture) -> None:
        sandbox.order.append("rollouts")
        captures.append(capture)

    runtime = runtime_with(monkeypatch, sandbox)
    result = await runtime.run_procedure_and_kill(
        sandbox_id="sbx",
        run_input=SandboxProcedureInput(
            **base_values(),
            context={},
            output_path="reports/X.md",
            output_max_bytes=1000,
            run_tools_url="https://tin.test/mcp",
            run_tools_grant="run-tools-grant-value",
            redact=("pw-secret-123",),
            rollout_sink=sink,
            isolated=True,
            usage_sink=AsyncMock(),
            api_url="https://tin.test/relay",
            api_grant="broker-grant-value",
        ),
    )
    assert result.summary == "done"
    assert sandbox.order == ["rollouts", "kill"]
    text = captures[0].files[0].content.decode()
    for leaked in ("ZXBoZW1lcmFs", "broker-grant-value", "run-tools-grant-value", "pw-secret-123"):
        assert leaked not in text, leaked


@pytest.mark.asyncio
async def test_task_run_captures_rollouts_and_redacts_the_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = base64.b64encode(
        json.dumps(
            {"outcome": "completed", "summary": "used broker-grant-value", "message": "m"}
        ).encode()
    ).decode()
    files = FakeFiles({f"{SESSIONS}/2026/09/04/{ROLLOUT_NAME}": b"{}\n"})
    sandbox = RecordingSandbox(f"TIN_TASK_HAS_CHANGES=0\nTIN_TASK_RESULT={payload}\n", files)
    seen: list[RolloutCapture] = []

    async def sink(capture: RolloutCapture) -> None:
        sandbox.order.append("rollouts")
        seen.append(capture)

    runtime = runtime_with(monkeypatch, sandbox)
    result = await runtime.run_task_and_kill(
        sandbox_id="sbx",
        run_input=SandboxTaskInput(
            **{**base_values()},
            run_id="run-1",
            context={},
            rollout_sink=sink,
            isolated=True,
            api_url="https://tin.test/relay",
            api_grant="broker-grant-value",
        ),
    )
    assert result.summary == "used [redacted]"
    assert sandbox.order == ["rollouts", "kill"]
    assert seen[0].files[0].filename == ROLLOUT_NAME


@pytest.mark.asyncio
async def test_capture_budget_never_blocks_the_kill_or_fails_the_run(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(e2b_runtime, "ROLLOUT_CAPTURE_BUDGET_SECONDS", 0.05)
    files = FakeFiles({f"{SESSIONS}/2026/09/04/{ROLLOUT_NAME}": b"{}\n"})
    payload = base64.b64encode(json.dumps({"summary": "done", "message": "ok"}).encode()).decode()
    sandbox = RecordingSandbox(
        f"TIN_PROCEDURE_COMMIT_SHA={'e' * 40}\nTIN_PROCEDURE_RESULT={payload}\n", files
    )

    async def slow_sink(capture: RolloutCapture) -> None:
        await asyncio.sleep(1)

    runtime = runtime_with(monkeypatch, sandbox)
    with caplog.at_level(logging.WARNING, logger="tin_lite.e2b_runtime"):
        result = await runtime.run_procedure_and_kill(
            sandbox_id="sbx",
            run_input=SandboxProcedureInput(
                **base_values(),
                context={},
                output_path="report.md",
                output_max_bytes=1000,
                isolated=True,
                usage_sink=AsyncMock(),
                api_url="https://tin.test/relay",
                api_grant="broker-grant-value",
                rollout_sink=slow_sink,
            ),
        )
    assert result.ephemeral_commit_sha == "e" * 40
    assert sandbox.order == ["kill"]
    record = next(r for r in caplog.records if r.getMessage() == "rollout capture failed")
    assert record.sandbox_id == "sbx"
    assert "broker-grant-value" not in caplog.text


@pytest.mark.asyncio
async def test_runs_without_a_sink_do_not_read_rollout_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files = FakeFiles({f"{SESSIONS}/2026/09/04/{ROLLOUT_NAME}": b"{}\n"})
    payload = base64.b64encode(json.dumps({"summary": "done", "message": "ok"}).encode()).decode()
    sandbox = RecordingSandbox(
        f"TIN_PROCEDURE_COMMIT_SHA={'e' * 40}\nTIN_PROCEDURE_RESULT={payload}\n", files
    )
    runtime = runtime_with(monkeypatch, sandbox)
    await runtime.run_procedure_and_kill(
        sandbox_id="sbx",
        run_input=SandboxProcedureInput(
            **base_values(),
            context={},
            output_path="report.md",
            output_max_bytes=1000,
            isolated=True,
            usage_sink=AsyncMock(),
            api_url="https://tin.test/relay",
            api_grant="broker-grant-value",
        ),
    )
    assert files.calls == [("write", e2b_runtime.CONTEXT_PATH)]
    assert sandbox.order == ["kill"]


# --- trace renderer ---------------------------------------------------------------------


def test_trace_renders_messages_calls_outputs_and_skips_noise() -> None:
    content = (
        rollout_bytes(
            {
                "timestamp": "2026-09-04T10:00:00.000Z",
                "type": "session_meta",
                "payload": {
                    "id": THREAD,
                    "cwd": "/w",
                    "cli_version": "0.147.0",
                    "originator": "app-server",
                },
            },
            {
                "timestamp": "2026-09-04T10:00:01.000Z",
                "type": "turn_context",
                "payload": {
                    "model": "gpt-5",
                    "approval_policy": "never",
                    "sandbox_policy": {"mode": "danger-full-access"},
                    "cwd": "/w",
                },
            },
            {
                "timestamp": "2026-09-04T10:00:02.000Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Do the thing"}],
                },
            },
            {
                "timestamp": "2026-09-04T10:00:03.000Z",
                "type": "response_item",
                "payload": {
                    "type": "reasoning",
                    "summary": [{"type": "summary_text", "text": "Plan it"}],
                    "content": [{"type": "reasoning_text", "text": "hidden"}],
                },
            },
            {
                "timestamp": "2026-09-04T10:00:04.000Z",
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "shell",
                    "call_id": "c1",
                    "arguments": json.dumps({"command": ["ls", "-la"]}),
                },
            },
            {
                "timestamp": "2026-09-04T10:00:05.000Z",
                "type": "response_item",
                "payload": {"type": "function_call_output", "call_id": "c1", "output": "x" * 30},
            },
            {
                "timestamp": "2026-09-04T10:00:06.000Z",
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "name": "exec",
                    "call_id": "c2",
                    "input": "await tools.web()",
                },
            },
            {
                "timestamp": "2026-09-04T10:00:07.000Z",
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": "c2",
                    "output": "line one\nline two",
                },
            },
            {
                "timestamp": "2026-09-04T10:00:08.000Z",
                "type": "event_msg",
                "payload": {"type": "token_count", "info": {}},
            },
            {
                "timestamp": "2026-09-04T10:00:09.000Z",
                "type": "event_msg",
                "payload": {"type": "task_complete", "last_agent_message": "Done."},
            },
            {
                "timestamp": "2026-09-04T10:00:10.000Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Finished"}],
                },
            },
        )
        + b"not json\n"
    )
    lines = list(render_rollout_trace(content, max_output_chars=20))
    assert lines[0].startswith(f"10:00:00 # session {THREAD} cwd=/w cli=0.147.0")
    assert "10:00:01 # turn model=gpt-5 approval=never sandbox=danger-full-access cwd=/w" in lines
    assert "10:00:02 USER: Do the thing" in lines
    assert "10:00:03 REASONING: Plan it" in lines
    assert "hidden" not in "\n".join(lines)
    assert "10:00:04 CALL shell#c1: ls -la" in lines
    assert "10:00:05 OUTPUT #c1: xxxxxxxxxxxxxxxxxxxx… [truncated 10 chars]" in lines
    assert "10:00:06 TOOL exec#c2: await tools.web()" in lines
    assert "10:00:07 TOOL OUTPUT #c2: line one" in lines
    assert "10:00:07     line two" in lines
    assert "10:00:07 TOOL OUTPUT #c2:" not in lines
    assert not any("token_count" in line for line in lines)
    assert "10:00:09 EVENT task_complete: Done." in lines
    assert "10:00:10 ASSISTANT: Finished" in lines
    assert lines[-1] == "# skipped 1 malformed line(s)"


# --- database mapper and CLI ---------------------------------------------------------------


def test_run_rollout_row_maps_without_content() -> None:
    run_id = uuid4()
    now = datetime.now(UTC)
    row = {
        "id": 7,
        "run_id": run_id,
        "generation": 2,
        "execution_key": "k",
        "activity_attempt": 1,
        "stage": "codex_procedure",
        "sandbox_id": "sbx",
        "thread_id": THREAD,
        "filename": ROLLOUT_NAME,
        "size_bytes": 10,
        "stored_bytes": 9,
        "sha256": "a" * 64,
        "truncated": False,
        "redactions": 3,
        "created_at": now,
        "content_gzip": b"never mapped",
    }
    rollout = _run_rollout(row)
    assert rollout == RunRollout(
        id=7,
        run_id=run_id,
        generation=2,
        execution_key="k",
        activity_attempt=1,
        stage="codex_procedure",
        sandbox_id="sbx",
        thread_id=THREAD,
        filename=ROLLOUT_NAME,
        size_bytes=10,
        stored_bytes=9,
        sha256="a" * 64,
        truncated=False,
        redactions=3,
        created_at=now,
    )
    assert not hasattr(rollout, "content_gzip")


@pytest.mark.asyncio
async def test_cli_rollouts_writes_files_and_prints_a_trace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_id = uuid4()
    rollout = RunRollout(
        id=3,
        run_id=run_id,
        generation=1,
        execution_key="k",
        activity_attempt=2,
        stage="codex_procedure",
        sandbox_id="sbx",
        thread_id=THREAD,
        filename=ROLLOUT_NAME,
        size_bytes=10,
        stored_bytes=10,
        sha256="a" * 64,
        truncated=False,
        redactions=0,
        created_at=datetime(2026, 9, 4, tzinfo=UTC),
    )
    content = rollout_bytes(
        {
            "timestamp": "2026-09-04T10:00:02.000Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "hi"}],
            },
        }
    )

    class FakeDatabase:
        def __init__(self, dsn: str) -> None:
            self.dsn = dsn

        async def connect(self) -> None:
            return None

        async def close(self) -> None:
            return None

        async def list_run_rollouts(self, requested: UUID):
            return [rollout] if requested == run_id else []

        async def read_run_rollout(self, rollout_id: int):
            return (rollout, content) if rollout_id == 3 else None

    monkeypatch.setattr(cli, "Database", FakeDatabase)
    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(runtime_dsn="postgres://x"))

    await cli._rollouts(run_id, out=tmp_path, trace=True, max_output_chars=100)

    written = tmp_path / "1-codex_procedure-attempt2-sbx" / ROLLOUT_NAME
    assert written.read_bytes() == content
    out = capsys.readouterr().out
    assert f"3 1 codex_procedure 2 sbx {ROLLOUT_NAME} 10 10 False 0" in out
    assert f"=== {ROLLOUT_NAME} (thread {THREAD}) ===" in out
    assert "10:00:02 USER: hi" in out

    with pytest.raises(SystemExit, match="no rollouts captured"):
        await cli._rollouts(uuid4(), out=None, trace=False, max_output_chars=100)
