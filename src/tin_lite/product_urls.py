"""Configured canonical origins and optional, temporary inbound compatibility."""

from typing import Any
from urllib.parse import urlsplit


def dashboard_url(settings: Any) -> str:
    return str(getattr(settings, "app_url", None) or settings.switchboard_public_url).rstrip("/")


def product_origins(settings: Any) -> frozenset[str]:
    return frozenset(
        str(origin).rstrip("/")
        for origin in (
            settings.switchboard_public_url,
            dashboard_url(settings),
            getattr(settings, "legacy_public_url", None),
        )
        if origin
    )


def validate_origin(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or "\\" in value
            or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)
            or (
                parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            )
        ):
            raise ValueError
        _ = parsed.port  # Validate malformed ports too.
    except ValueError as exc:
        raise ValueError(
            "The app URL must be an HTTPS origin (HTTP is allowed for localhost)"
        ) from exc
    return value.rstrip("/")
