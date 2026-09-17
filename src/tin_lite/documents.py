from __future__ import annotations

import math
import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from pathlib import PurePosixPath
from urllib.parse import urlparse

import mistune
from mistune.renderers.html import HTMLRenderer
from mistune.util import escape as escape_text
from mistune.util import safe_entity, striptags

WORDS_PER_MINUTE = 220
_WORD = re.compile(r"[\w]+(?:['’\-][\w]+)*", re.UNICODE)
_SLUG_SEPARATOR = re.compile(r"[^\w]+", re.UNICODE)
_SAFE_INLINE_HTML = {"<br>", "<br/>", "<sub>", "</sub>"}


@dataclass(frozen=True)
class MarkdownHeading:
    id: str
    title: str


@dataclass(frozen=True)
class RenderedMarkdown:
    markdown: str
    html: str
    headings: tuple[MarkdownHeading, ...]
    word_count: int
    reading_minutes: int


class _TinHTMLRenderer(HTMLRenderer):
    def __init__(self) -> None:
        # Raw HTML is handled explicitly below. This lets existing reports keep their harmless
        # <br>/<sub> formatting while every other tag is shown as text instead of executed.
        super().__init__(escape=False)
        self.headings: list[MarkdownHeading] = []
        self._slug_counts: dict[str, int] = {}

    def heading(self, text: str, level: int, **attrs: object) -> str:
        title = unescape(striptags(text)).strip()
        base = _heading_slug(title)
        count = self._slug_counts.get(base, 0) + 1
        self._slug_counts[base] = count
        heading_id = base if count == 1 else f"{base}-{count}"
        if level == 2:
            self.headings.append(MarkdownHeading(id=heading_id, title=title))
        return f'<h{level} id="{escape_text(heading_id)}">{text}</h{level}>\n'

    def link(self, text: str, url: str, title: str | None = None) -> str:
        rendered = f'<a href="{self.safe_url(url)}"'
        if title:
            rendered += f' title="{safe_entity(title)}"'
        return f'{rendered} rel="noreferrer">{text}</a>'

    def image(self, text: str, url: str, title: str | None = None) -> str:
        alt = striptags(text)
        filename = PurePosixPath(urlparse(url).path).name or "image"
        rendered = (
            f'<img src="{self.safe_url(url)}" alt="{safe_entity(alt)}" '
            f'data-fallback-name="{safe_entity(filename)}"'
        )
        if title:
            rendered += f' title="{safe_entity(title)}"'
        return rendered + " />"

    def block_code(self, code: str, info: str | None = None) -> str:
        language = ""
        if info:
            language = info.strip().split(None, 1)[0]
        language_attr = f' data-language="{safe_entity(language)}"' if language else ""
        code_class = f' class="language-{safe_entity(language)}"' if language else ""
        return (
            f'<div class="md-code-block"{language_attr}><pre><code{code_class}>'
            f"{escape_text(code)}</code></pre></div>\n"
        )

    def inline_html(self, html: str) -> str:
        compact = re.sub(r"\s+", "", html).lower()
        if compact in _SAFE_INLINE_HTML:
            return "<br />" if compact in {"<br>", "<br/>"} else compact
        return escape_text(html)

    def block_html(self, html: str) -> str:
        return f"<p>{escape_text(html.strip())}</p>\n"


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def render_markdown(markdown: str) -> RenderedMarkdown:
    renderer = _TinHTMLRenderer()
    parser = mistune.create_markdown(
        renderer=renderer,
        plugins=["strikethrough", "table", "task_lists", "url"],
    )
    # Plain scalar frontmatter is source metadata, not article copy. Keep it accessible
    # without a workflow-specific reader or interpreting YAML tags/objects. Unsupported
    # frontmatter stays visible as ordinary Markdown; raw source is always unchanged.
    match = re.match(r"\A---\r?\n([\s\S]{1,16000}?)\r?\n---(?:\r?\n|\Z)", markdown)
    metadata = ""
    body = markdown
    if (
        match
        and all(
            re.fullmatch(r"[A-Za-z_][\w.-]*:[^\r\n]*", line)
            for line in match[1].splitlines()
            if line.strip()
        )
        and match[1].strip()
    ):
        metadata = (
            '<details class="md-document-metadata"><summary>Document metadata</summary>'
            f"<pre><code>{escape_text(match[1])}</code></pre></details>\n"
        )
        body = markdown[match.end() :]
    rendered = parser(body)
    visible = _VisibleText()
    visible.feed(rendered)
    word_count = len(_WORD.findall(" ".join(visible.parts)))
    return RenderedMarkdown(
        markdown=markdown,
        html=rendered + metadata,
        headings=tuple(renderer.headings),
        word_count=word_count,
        reading_minutes=max(1, math.ceil(word_count / WORDS_PER_MINUTE)),
    )


def _heading_slug(title: str) -> str:
    slug = _SLUG_SEPARATOR.sub("-", title.casefold()).strip("-_")
    return slug or "section"
