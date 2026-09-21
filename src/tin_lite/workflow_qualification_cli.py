"""Local static checks and an explicit live-case client for the existing Tin runtime."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from tin_lite.community import CheckoutStorage, ContributedPackage, validate
from tin_lite.workflow_packages import decode_workflow_source
from tin_lite.workflow_qualification import (
    Qualification,
    assess_output,
    check_package,
    inspect_candidate,
    qualification_path,
    read_json,
)


async def check_checkout(root, path, *, fixtures=None):
    storage = CheckoutStorage(root)
    raw = storage._read(path)
    source = decode_workflow_source(raw, definition_path=path)
    package = ContributedPackage(source.definition["key"], root / Path(path).parent)
    await validate(package, root=root)
    files = {p: storage._read(p) for p in [path, *source.resource_paths.values()]}
    contract = Qualification.model_validate(
        read_json(storage._read(qualification_path(package.key)))
    )
    report = await check_package(files, path, contract)
    if fixtures is not None:
        data = read_json(fixtures)
        known = {case.id for case in contract.cases}
        if not isinstance(data, dict) or set(data) - known:
            raise ValueError("fixtures must name declared cases")
        results = []
        for case in contract.cases:
            if case.id not in data:
                results.append({"id": case.id, "status": "not_run"})
                continue
            item = data[case.id]
            if (
                not isinstance(item, dict)
                or set(item) != {"status", "content"}
                or item["status"] not in {"succeeded", "failed"}
                or (item["content"] is not None and not isinstance(item["content"], str))
            ):
                raise ValueError("fixture must have status and text content (or null)")
            content = item["content"].encode() if item["content"] is not None else None
            results.append(
                {"id": case.id, **assess_output(case, status=item["status"], content=content)}
            )
        report["evaluation"].update(
            mode="fixture_outputs",
            cases=results,
            status="failed"
            if any(r["status"] == "failed" for r in results)
            else "incomplete"
            if any(r["status"] == "not_run" for r in results)
            else "fixture_assertions_passed",
            note="Checks canned outputs against assertions. Does not execute candidate code, "
            "test a model/provider or establish measured cost.",
        )
    return report


def save_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


async def run_cases(
    client,
    *,
    project_id,
    workflow_id,
    path,
    revision,
    maximum_usd,
    directory,
    wait_seconds=1800,
    poll_seconds=5,
):
    """Member-authorized client orchestration; retries reuse each persisted start request ID."""
    base = f"/api/projects/{project_id}/workflow-packages"
    selection = {"path": path, "revision": revision}

    async def request(method, url, **kwargs):
        response = await client.request(method, url, **kwargs)
        response.raise_for_status()
        return response.json()

    report = await request("POST", base + "/qualify", json=selection)
    ceiling = Decimal(report["cost"]["configured_ceiling_usd"])
    count = len(report["evaluation"]["cases"])
    limit = Decimal(maximum_usd)
    if not limit.is_finite() or limit < 0:
        raise ValueError("use a finite, non-negative evaluation maximum")
    identity = {
        **selection,
        "project_id": project_id,
        "workflow_id": workflow_id,
        "package_digest": report["package_digest"],
        "qualification_digest": report["qualification_digest"],
        "maximum_usd": maximum_usd,
        "origin": str(client.base_url),
    }
    journal = directory / "runs.json"
    if journal.exists():
        state = read_json(journal.read_bytes())
        if state["identity"] != identity:
            raise ValueError("evaluation journal belongs to a different candidate, cases or budget")
        ceiling = Decimal(state["case_maximum_usd"])
    else:
        if count * ceiling > limit:
            raise ValueError("sum of case ceilings exceeds the authorized evaluation maximum")
        directory.mkdir(parents=True, exist_ok=False, mode=0o700)
        state = {
            "identity": identity,
            "case_maximum_usd": str(ceiling),
            "cases": [
                {"case_id": c["id"], "request_id": str(uuid4()), "run_id": None}
                for c in report["evaluation"]["cases"]
            ],
        }
        save_json(journal, state)
    for case in state["cases"]:
        if case["run_id"] is None:
            # The UUID is durable before the request. A lost acknowledgement can only
            # recover this start, never generate another paid attempt under a fresh ID.
            started = await request(
                "POST",
                base + "/evaluate",
                json={
                    **selection,
                    "workflow_id": workflow_id,
                    "case_id": case["case_id"],
                    "request_id": case["request_id"],
                    "maximum_usd": str(ceiling),
                },
            )
            case["run_id"] = started["run_id"]
            save_json(journal, state)
        deadline = time.monotonic() + wait_seconds
        while True:
            run = await request("GET", f"/api/workflows/runs/{case['run_id']}")
            if run["status"] in {"succeeded", "failed", "stopped", "superseded"}:
                break
            if run["status"] == "needs_input":
                raise ValueError(
                    "case is waiting for human review; resolve it in Tin, then resume this journal"
                )
            if time.monotonic() >= deadline:
                raise TimeoutError("run still active; resume this evaluation journal to continue")
            await asyncio.sleep(poll_seconds)
    evidence = [{"case_id": case["case_id"], "run_id": case["run_id"]} for case in state["cases"]]
    report = await request("POST", base + "/qualify", json={**selection, "runs": evidence})
    save_json(directory / "qualification.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="static package/case checks; no candidate execution")
    check.add_argument("path", help="workflow_packages/<key>/workflow.json")
    check.add_argument("--root", type=Path, default=Path.cwd())
    check.add_argument(
        "--fixtures", type=Path, help="optional synthetic output fixtures; not live evidence"
    )
    candidate = commands.add_parser(
        "candidate", help="inspect a saved candidate JSON; no file writes"
    )
    candidate.add_argument("file", type=Path)
    live = commands.add_parser(
        "run", help="LIVE: start the pinned cases through Tin, with real usage"
    )
    for name in ("url", "project-id", "workflow-id", "path", "revision", "maximum-usd"):
        live.add_argument("--" + name, required=True)
    live.add_argument(
        "--token-file",
        type=Path,
        required=True,
        help="explicit Tin access token file; never a provider key",
    )
    live.add_argument(
        "--out",
        type=Path,
        required=True,
        help="new output directory, or an existing evaluation journal to resume",
    )
    args = parser.parse_args()

    async def execute():
        if args.command == "candidate":
            return await inspect_candidate(CheckoutStorage(args.file.parent)._read(args.file.name))
        if args.command == "check":
            fixtures = (
                CheckoutStorage(args.fixtures.parent)._read(args.fixtures.name)
                if args.fixtures
                else None
            )
            return await check_checkout(args.root, args.path, fixtures=fixtures)
        url = urlsplit(args.url)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.path not in ("", "/")
            or url.query
            or url.fragment
        ):
            raise ValueError("use the exact HTTPS Tin origin without a path or credentials")
        token = CheckoutStorage(args.token_file.parent)._read(args.token_file.name).decode().strip()
        if not token or len(token) > 16_000 or "\n" in token:
            raise ValueError("invalid access token file")
        async with httpx.AsyncClient(
            base_url=args.url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            return await run_cases(
                client,
                project_id=args.project_id,
                workflow_id=args.workflow_id,
                path=args.path,
                revision=args.revision,
                maximum_usd=args.maximum_usd,
                directory=args.out,
            )

    try:
        report = asyncio.run(execute())
    except (ValueError, KeyError, OSError, httpx.HTTPError, TimeoutError) as exc:
        # Do not print HTTP bodies, headers, submitted source or Pydantic input echoes.
        parser.exit(1, f"Qualification stopped ({type(exc).__name__}). No automatic retry.\n")
    print(json.dumps(report, indent=2))
    if report.get("evaluation", {}).get("status") in {"failed", "incomplete"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
