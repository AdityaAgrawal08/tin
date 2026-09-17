from __future__ import annotations

from uuid import UUID

import httpx
import pytest
from raw_file_security_fixture import PROJECT_ID, REVISION, fixture


@pytest.mark.asyncio
async def test_untrusted_raw_files_and_artifacts_are_sandboxed_without_changing_bytes():
    app, token, files, runs = fixture("http://test")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        cookies={"__session": token},
    ) as client:
        for name, content in files.items():
            run = next(run for run in runs.values() if run.artifact_path == name)
            sources = [
                (f"/api/projects/{PROJECT_ID}/files/raw", {"path": name, "revision": REVISION}),
                (f"/api/workflows/runs/{run.id}/artifact", {}),
            ]
            if run.retained_output:
                sources.append((sources[1][0], {"source": "retained"}))
            for url, params in sources:
                response = await client.get(url, params=params)
                assert response.status_code == 200, response.text
                assert response.content == content
                inline = name in {"safe.png", "disguised.png", "notes.md", "notes.txt"}
                disposition = "inline" if inline else "attachment"
                assert response.headers["Content-Disposition"].startswith(disposition + ";")
                assert response.headers["Content-Security-Policy"] == (
                    "sandbox; default-src 'none'; base-uri 'none'; "
                    "form-action 'none'; frame-ancestors 'none'"
                )
                assert response.headers["X-Content-Type-Options"] == "nosniff"
                assert response.headers["Cache-Control"] == "private, no-store"
                assert response.headers["Referrer-Policy"] == "no-referrer"
                if "files/raw" in url:
                    downloaded = await client.get(url, params={**params, "download": True})
                    assert downloaded.headers["Content-Disposition"].startswith("attachment;")
                    assert downloaded.content == content

        # Existing membership/revision checks still precede any raw bytes.
        url = f"/api/projects/{PROJECT_ID}/files/raw"
        assert (
            await client.get(url, params={"path": "attack.html", "revision": "b" * 40})
        ).status_code == 404
        foreign = f"/api/projects/{UUID(int=999)}/files/raw"
        assert (
            await client.get(foreign, params={"path": "attack.html", "revision": REVISION})
        ).status_code == 404
        client.cookies.clear()
        assert (
            await client.get(url, params={"path": "attack.html", "revision": REVISION})
        ).status_code == 401
        assert (await client.get(sources[1][0])).status_code == 401
