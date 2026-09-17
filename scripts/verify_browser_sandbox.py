"""Live acceptance probe for the browser sandbox profile.

Creates one `tin-lite-codex-browser` sandbox with open egress and proves, as the unprivileged
user, that the shared `warp-up` script registers and connects Cloudflare WARP, that the WARP
SOCKS proxy reaches an IPv6-only host, that the Tin-owned `camoufox-mcp` server renders a
public page through WARP, and that the same server completes a Cloudflare Turnstile form:
the widget loads, issues a token, and the demo backend validates it. The sandbox is always
killed. Run from the switchboard's configured runtime environment:

    uv run python scripts/verify_browser_sandbox.py

The default Turnstile page is Cloudflare's own demo, which uses the always-pass test sitekey.
It proves the widget script, the challenge iframe, and its IPv6-only dependencies load and that
a token round-trips, not that Cloudflare's bot scoring accepts the browser. Point
`--turnstile-url` at a page with a real sitekey for that; the probe stops after the widget
reports a token when `--turnstile-marker` is empty.
"""

from __future__ import annotations

import argparse
import asyncio
from textwrap import dedent

from e2b import AsyncSandbox

from tin_lite.settings import get_settings

# Runs inside the sandbox with the cfx-venv python. It drives /opt/tin-lite/camoufox-mcp over
# stdio exactly as Codex does, so the acceptance exercises the real tool surface.
PROBE_CLIENT = dedent(
    r"""
    import asyncio
    import os
    import sys

    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    def fail(message):
        print(message, file=sys.stderr)
        raise SystemExit(72)

    async def call(session, tool, **arguments):
        result = await session.call_tool(tool, arguments)
        text = "\n".join(
            block.text for block in result.content if getattr(block, "type", "") == "text"
        )
        if getattr(result, "is_error", False) or getattr(result, "isError", False):
            fail(f"{tool} failed: {text[:2000]}")
        return text

    async def evidence(session):
        for name in ("console_messages", "network_failures"):
            print(f"--- {name}\n{await call(session, name)}", file=sys.stderr)

    async def main():
        env = {
            "TIN_BROWSER_PROFILE_DIR": os.environ["TIN_PROBE_PROFILE_DIR"],
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
        }
        if "TIN_BROWSER_PROXY" in os.environ:
            env["TIN_BROWSER_PROXY"] = os.environ["TIN_BROWSER_PROXY"]
        params = StdioServerParameters(
            command=os.environ["TIN_PROBE_MCP_PYTHON"],
            args=[os.environ["TIN_PROBE_MCP_SCRIPT"]],
            env=env,
            cwd=os.environ["TIN_PROBE_PROFILE_DIR"],
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                text = await call(session, "navigate", url=os.environ["TIN_PROBE_URL"])
                if os.environ["TIN_PROBE_MARKER"] not in text:
                    await evidence(session)
                    fail("camoufox-mcp did not render the probe page")
                print("CAMOUFOX_OK=true", flush=True)

                await call(session, "navigate", url=os.environ["TIN_TURNSTILE_URL"])
                if os.environ["TIN_TURNSTILE_MARKER"]:
                    # Cloudflare's demo form: a free-text user field and a read-only password.
                    await call(session, "fill", selector="#user", value="tin-probe")
                state = ""
                for attempt in range(6):
                    state = await call(session, "turnstile_state")
                    if '"token_present": true' in state:
                        break
                    if attempt == 2 and '"widget_present": true' in state:
                        state = await call(session, "click_turnstile", timeout_seconds=30)
                        if '"token_present": true' in state:
                            break
                    await asyncio.sleep(5)
                if '"token_present": true' not in state:
                    await evidence(session)
                    fail(f"Turnstile issued no token: {state}")
                print("TURNSTILE_TOKEN_OK=true", flush=True)

                if os.environ["TIN_TURNSTILE_MARKER"]:
                    await call(session, "click_role", role="button", name="Sign in")
                    text = await call(session, "wait_for", text=os.environ["TIN_TURNSTILE_MARKER"])
                    if os.environ["TIN_TURNSTILE_MARKER"] not in text:
                        await evidence(session)
                        fail("the Turnstile demo backend did not validate the token")
                print("TURNSTILE_OK=true", flush=True)

    asyncio.run(main())
    """
).strip()

VERIFY_SCRIPT = dedent(
    r"""
    #!/usr/bin/env bash
    set -euo pipefail
    umask 077

    if [[ "$(id -u)" -eq 0 ]]; then
      echo 'browser probe must run as the unprivileged sandbox user' >&2
      exit 70
    fi

    # warp-up is the same script the procedure runner uses.
    /opt/tin-lite/warp-up /tmp/warp
    code="$(curl --socks5-hostname 127.0.0.1:40000 -sS -o /dev/null \
      -w '%{http_code}' --max-time 20 https://ipv6.google.com/)" || true
    if [[ "${code}" == "200" ]]; then
      echo 'WARP_IPV6_OK=true'
    else
      echo "WARP SOCKS proxy did not reach an IPv6-only host (status ${code:-none})" >&2
      exit 71
    fi

    mkdir -p /tmp/cfx-profile
    TIN_PROBE_PROFILE_DIR=/tmp/cfx-profile \
    TIN_PROBE_MCP_PYTHON=/opt/tin-lite/cfx-venv/bin/python \
    TIN_PROBE_MCP_SCRIPT=/opt/tin-lite/camoufox-mcp \
      /opt/tin-lite/cfx-venv/bin/python /home/user/cfx-probe.py
    """
).strip()

REQUIRED_MARKERS = {"WARP_OK=true", "WARP_IPV6_OK=true", "CAMOUFOX_OK=true", "TURNSTILE_OK=true"}


async def verify(*, url: str, marker: str, turnstile_url: str, turnstile_marker: str) -> None:
    settings = get_settings()
    sandbox = await AsyncSandbox.create(
        settings.e2b_browser_template,
        timeout=420,
        metadata={"purpose": "tin-lite-browser-acceptance", "profile": "browser"},
        lifecycle={"on_timeout": "pause", "auto_resume": False},
        network=None,
        api_key=settings.e2b_api_key.get_secret_value(),
    )
    try:
        script_path = "/home/user/verify-browser"
        await sandbox.files.write(script_path, VERIFY_SCRIPT)
        await sandbox.files.write("/home/user/cfx-probe.py", PROBE_CLIENT)
        await sandbox.commands.run(f"chmod 700 {script_path}", timeout=20)
        result = await sandbox.commands.run(
            script_path,
            envs={
                "TIN_PROBE_URL": url,
                "TIN_PROBE_MARKER": marker,
                "TIN_TURNSTILE_URL": turnstile_url,
                "TIN_TURNSTILE_MARKER": turnstile_marker,
            },
            timeout=360,
        )
        observed = set(result.stdout.splitlines())
        if not REQUIRED_MARKERS <= observed:
            raise RuntimeError("browser acceptance markers were not produced")
    finally:
        await sandbox.kill()

    print(
        "live browser acceptance: PASS "
        "(warp-up registration and connect as user, WARP SOCKS egress with IPv6 reachability, "
        "camoufox-mcp rendered a public page through WARP, Turnstile widget loaded and its "
        "token validated through the same MCP tools, sandbox kill)"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="https://example.com/")
    parser.add_argument("--marker", default="Example Domain")
    parser.add_argument("--turnstile-url", default="https://demo.turnstile.workers.dev/")
    parser.add_argument(
        "--turnstile-marker",
        default="Turnstile token successfuly validated",
        help="text expected after submit; empty stops after the widget issues a token",
    )
    args = parser.parse_args()
    asyncio.run(
        verify(
            url=args.url,
            marker=args.marker,
            turnstile_url=args.turnstile_url,
            turnstile_marker=args.turnstile_marker,
        )
    )


if __name__ == "__main__":
    main()
