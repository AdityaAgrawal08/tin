"""Optional licensed web typography; public builds never need a private font."""

from html import escape


def private_font_stylesheet(settings) -> str:
    url = getattr(settings, "private_fonts_stylesheet_url", None)
    if not url:
        return ""
    return f'<link rel="stylesheet" href="{escape(url, quote=True)}" crossorigin="anonymous" />'
