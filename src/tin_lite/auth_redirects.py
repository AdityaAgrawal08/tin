"""Bound Clerk sign-in continuation to this Tin instance and its OAuth authority."""

from urllib.parse import urlsplit

from tin_lite.product_urls import product_origins


def auth_return_url(settings, value: str | None) -> tuple[str, bool]:
    if value is None:
        return "", False
    if (
        not value
        or len(value) > 16_384
        or "\\" in value
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise ValueError("Invalid sign-in return address")
    try:
        target = urlsplit(value)
        authority = urlsplit(settings.clerk_frontend_api_url)
        origins = product_origins(settings)
        products = {urlsplit(origin).netloc for origin in origins}
        if target.username or target.password or target.fragment:
            raise ValueError("Invalid sign-in return address")
        local_product = (
            target.scheme == "http"
            and target.hostname in {"localhost", "127.0.0.1", "::1"}
            and f"http://{target.netloc}" in origins
        )
        if not local_product and (target.scheme != "https" or target.port not in (None, 443)):
            raise ValueError("Invalid sign-in return address")
        if target.hostname == authority.hostname and target.path in {
            "/oauth/authorize",
            "/oauth/authorize/continue",
        }:
            return value, True
        if target.netloc in products:
            if target.path.rstrip("/") in {"/sign-in", "/sign-up"} or target.path.startswith(
                ("/sign-in/", "/sign-up/")
            ):
                raise ValueError("Sign-in return address would repeat sign-in")
            return value, target.path.rstrip("/") == "/mcp/consent"
        # Also preserve an in-flight return to the hosted consent page while the
        # shared instance's custom page settings are rolled forward or back.
        if authority.hostname and authority.hostname.startswith("clerk."):
            portal = "accounts." + authority.hostname.removeprefix("clerk.")
            if target.hostname == portal and target.path == "/oauth-consent":
                return value, True
        # The production Clerk instance is shared with the parent Tin website.
        # Preserve its explicit returns when its configured sign-in page is Tin Lite.
        parent = authority.hostname.removeprefix("clerk.") if authority.hostname else ""
        if (
            authority.hostname
            and authority.hostname.startswith("clerk.")
            and target.hostname == parent
        ):
            return value, False
    except (AttributeError, ValueError) as exc:
        raise ValueError("Invalid sign-in return address") from exc
    raise ValueError("Invalid sign-in return address")
