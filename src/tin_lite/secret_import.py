"""Explicit local env selection, sent straight to Tin. Never source an env file."""

import argparse
import getpass
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import httpx


def parse_env(text):
    if len(text.encode()) > 128_000:
        raise ValueError("env file exceeds 128 KB")
    result = {}
    for line in text.removeprefix("\ufeff").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"(?:export\s+)?([A-Z][A-Z0-9_]{0,63})\s*=\s*(.*)", line)
        if not match or match[1] in result:
            raise ValueError("use unique uppercase NAME=value entries, one per line")
        name, value = match.groups()
        if value.startswith(("'", '"')):
            end = value.rfind(value[0])
            if end == 0 or not re.fullmatch(r"\s*(?:#.*)?", value[end + 1 :]):
                raise ValueError("multiline or invalid quoted values are not supported")
            value = value[1:end]
        else:
            value = re.sub(r"\s+#.*$", "", value).strip()
        if (
            not value
            or len(value.encode()) > 8000
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
        ):
            raise ValueError("values must be single-line text under 8 KB")
        result[name] = value
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=UUID, required=True)
    parser.add_argument(
        "--file",
        type=Path,
        required=True,
        help="explicit env file; never discovers agent credentials",
    )
    parser.add_argument(
        "--name", action="append", required=True, help="select a name; repeat to select several"
    )
    parser.add_argument("--url", default="https://app.tin.computer")
    parser.add_argument(
        "--token-file",
        type=Path,
        help="explicit Clerk OAuth/session token file; otherwise hidden prompt",
    )
    parser.add_argument(
        "--replace", action="store_true", help="allow replacement of selected existing names"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="show selected names only; no auth or upload"
    )
    args = parser.parse_args()
    try:
        if args.file.stat().st_size > 128_000:
            raise ValueError("env file exceeds 128 KB")
        values = parse_env(args.file.read_text())
        selected = list(dict.fromkeys(args.name))
        if any(name not in values for name in selected) or len(selected) > 32:
            raise ValueError("select 1-32 names present in the env file")
        print("Selected: " + ", ".join(f"{name}=••••••••" for name in selected))
        if args.dry_run:
            return
        url = urlsplit(args.url)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.path not in {"", "/"}
            or url.query
            or url.fragment
        ):
            raise ValueError("use the Tin HTTPS origin")
        token = (
            args.token_file.read_text().strip()
            if args.token_file
            else getpass.getpass("Tin OAuth/session token (hidden): ")
        )
        endpoint = args.url.rstrip("/") + f"/api/projects/{args.project}/connections/secrets"
        with httpx.Client(
            trust_env=False,
            follow_redirects=False,
            timeout=30,
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            response = client.get(endpoint)
            if response.status_code != 200:
                raise ValueError("authentication or project access failed; nothing uploaded")
            current = {s["name"]: s["revision"] for s in response.json()}
            replaced = [name for name in selected if name in current]
            if replaced and not args.replace:
                raise ValueError("existing names require --replace: " + ", ".join(replaced))
            response = client.put(
                endpoint,
                json={
                    "entries": [
                        {
                            "name": name,
                            "value": values[name],
                            "expected_revision": current.get(name),
                        }
                        for name in selected
                    ]
                },
            )
            if response.status_code != 200:
                raise ValueError("import rejected; refresh metadata and retry (values withheld)")
        print("Saved selected secrets. No provider request was made.")
    except (OSError, ValueError, httpx.HTTPError, KeyError, TypeError, json.JSONDecodeError):
        # In particular, never print an httpx exception with its request or response.
        parser.exit(
            1,
            "Import failed. Check the selected names, replacement flag, authentication "
            "and HTTPS origin. Values were not printed.\n",
        )


if __name__ == "__main__":
    main()
