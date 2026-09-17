from unittest.mock import Mock

from tin_lite import cli


def test_serve_bounds_connection_drain_without_logging_oauth_urls(monkeypatch):
    serve = Mock()
    monkeypatch.setattr(cli.uvicorn, "run", serve)
    monkeypatch.setattr("sys.argv", ["tin-lite", "serve"])
    cli.main()
    serve.assert_called_once_with(
        "tin_lite.main:app",
        host="0.0.0.0",  # noqa: S104
        port=8000,
        access_log=False,
        timeout_graceful_shutdown=20,
    )
