from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

MAX_SCAN_BYTES = 100_000
MAX_SCAN_SOURCE_BYTES = 200_000


class ResponsesClient(Protocol):
    async def create(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class ScanProtocolError(RuntimeError):
    """The scan model returned a response outside the report contract."""


@dataclass(frozen=True)
class ScanSource:
    label: str
    artifact_ref: str
    content: str


class ScanReporter:
    def __init__(self, *, responses: ResponsesClient, skill_suite: str) -> None:
        self._responses = responses
        self._skill_suite = skill_suite

    async def report(self, *, project_name: str, sources: list[ScanSource]) -> bytes:
        source_bytes = sum(len(source.content.encode()) for source in sources)
        if source_bytes > MAX_SCAN_SOURCE_BYTES:
            raise ValueError(f"scan sources exceed {MAX_SCAN_SOURCE_BYTES} bytes")
        payload = {
            "project_name": project_name,
            "sources": [
                {
                    "label": source.label,
                    "artifact_ref": source.artifact_ref,
                    "content": source.content,
                }
                for source in sources
            ],
        }
        response = await self._responses.create(
            {
                "instructions": self._skill_suite,
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": json.dumps(payload, separators=(",", ":")),
                            }
                        ],
                    }
                ],
                "store": False,
                "text": {"verbosity": "low"},
            }
        )
        content = _output_text(response).encode()
        validate_scan_report(content, sources=sources)
        return content


def validate_scan_report(content: bytes, *, sources: list[ScanSource]) -> None:
    if not content or len(content) > MAX_SCAN_BYTES:
        raise ValueError(f"scan report must contain between 1 and {MAX_SCAN_BYTES} bytes")
    text = content.decode("utf-8")
    if not text.startswith("# ") or "\n## Sources\n" not in text:
        raise ValueError("scan report must be Markdown with a Sources section")
    if any(source.artifact_ref not in text for source in sources):
        raise ValueError("scan report omitted a durable source reference")


def _output_text(response: dict[str, Any]) -> str:
    output = response.get("output")
    if not isinstance(output, list):
        raise ScanProtocolError("scan reporter response has no output list")
    fragments: list[str] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and part.get("type") == "output_text":
                text = part.get("text")
                if isinstance(text, str):
                    fragments.append(text)
    result = "\n".join(fragments).strip()
    if not result:
        raise ScanProtocolError("scan reporter returned no Markdown")
    return result + "\n"
