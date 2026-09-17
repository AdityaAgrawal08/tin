from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from tin_lite.api import router
from tin_lite.fonts import private_font_stylesheet
from tin_lite.mcp_oauth import router as consent_router
from tin_lite.settings import Settings


@pytest.mark.parametrize("url", [None, "https://cdn.example/v1/fonts.css?theme=1&v=2"])
def test_optional_private_font_url(url):
    assert Settings.validate_private_fonts_stylesheet(url) == url
    markup = private_font_stylesheet(SimpleNamespace(private_fonts_stylesheet_url=url))
    if url:
        assert 'crossorigin="anonymous"' in markup
        assert "theme=1&amp;v=2" in markup
    else:
        assert markup == ""


@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://cdn.example/fonts.css",
        "//cdn.example/fonts.css",
        "javascript:alert(1)",
        "data:text/css,body{}",
        "https://cdn.example/#x",
        "https://user:secret@cdn.example/fonts.css",
        'https://cdn.example/"onload="x',
        "https://cdn.example/\nfonts.css",
        "https://cdn.example/\\fonts.css",
    ],
)
def test_reject_unsafe_private_font_url(url):
    with pytest.raises(ValueError):
        Settings.validate_private_fonts_stylesheet(url)


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/sign-in",
        "/sign-up",
        "/mcp/consent?client_id=test",
        "/documents/runs/00000000-0000-0000-0000-000000000001",
    ],
)
async def test_all_product_pages_use_operator_font_setting_only(path, enabled):
    app = FastAPI()
    app.state.settings = SimpleNamespace(
        switchboard_public_url="https://tin.test",
        app_url=None,
        clerk_publishable_key="pk_test_placeholder",
        clerk_frontend_api_url="https://clerk.tin.test",
        private_fonts_stylesheet_url="https://cdn.example/v1/fonts.css" if enabled else None,
    )
    app.include_router(router)
    app.include_router(consent_router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://tin.test"
    ) as client:
        response = await client.get(path)
    assert response.status_code == 200
    assert "<!--PRIVATE_FONTS_STYLESHEET-->" not in response.text
    assert ("https://cdn.example/v1/fonts.css" in response.text) == enabled
    assert "fonts.tin.computer" not in response.text  # No hosted-font default for self-hosts.
    if enabled:
        assert response.text.index("/assets/app.css") < response.text.index("https://cdn.example")
        assert '&lt;link rel="stylesheet"' not in response.text


def test_packaged_font_files_are_open_source():
    assets = Path("src/tin_lite/static")
    names = {p.name for p in (assets / "fonts").glob("*.woff2")}
    assert names == {
        "geist-sans-regular.woff2",
        "geist-sans-bold.woff2",
        "geist-mono-regular.woff2",
        "geist-mono-bold.woff2",
    }
    for file in [assets / "app.css", assets / "auth.css", Path("sandbox/template.py")]:
        assert "fk-grotesk" not in file.read_text()
    assert (assets / "fonts/Geist-OFL.txt").is_file()
    assert Path("third_party/licenses/geist-sans-OFL.txt").is_file()
