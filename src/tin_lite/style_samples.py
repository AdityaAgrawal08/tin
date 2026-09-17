"""Bounded document-to-text conversion. No durable binary storage or external fetches."""

from __future__ import annotations

from io import BytesIO
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from tin_lite.style_capture import MAX_SOURCE_BYTES

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def extract_sample(filename: str, content: bytes) -> dict:
    if not 0 < len(content) <= MAX_UPLOAD_BYTES:
        raise ValueError("Choose a non-empty file no larger than 5 MiB.")
    name = PurePosixPath(filename.replace("\\", "/")).name[:160]
    extension = PurePosixPath(name).suffix.lower()
    warnings = []
    try:
        if extension in {".txt", ".md"}:
            text = content.decode("utf-8-sig")
        elif extension == ".docx":
            with ZipFile(BytesIO(content)) as archive:
                entries = archive.infolist()
                if len(entries) > 2000 or sum(x.file_size for x in entries) > 20 * 1024 * 1024:
                    raise ValueError("This document expands beyond the conversion limit.")
                if any(x.flag_bits & 1 for x in entries):
                    raise ValueError("Use an unencrypted DOCX export.")
                entry = archive.getinfo("word/document.xml")
                if entry.file_size > 2 * 1024 * 1024:
                    raise ValueError("Choose a shorter document.")
                xml = archive.read(entry).decode("utf-8-sig")
            if "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
                raise ValueError("Unsupported document XML.")
            root = ET.fromstring(xml)  # noqa: S314 — DTD/entity input rejected; bounded XML only
            changes = {W + tag for tag in ("ins", "del", "moveFrom", "moveTo", "altChunk")}
            if any(node.tag in changes for node in root.iter()):
                raise ValueError("Accept tracked changes and export a clean DOCX before using it.")
            for parent in root.iter():
                for node in list(parent):
                    if node.tag == W + "r" and any(
                        node.find(f"{W}rPr/{W}{tag}") is not None for tag in ("vanish", "webHidden")
                    ):
                        parent.remove(node)
            text = "\n\n".join(
                "".join(node.text or "" for node in paragraph.iter(W + "t"))
                for paragraph in root.iter(W + "p")
            )
            warnings = [
                "Text only. Comments, headers, footnotes and document formatting are not included."
            ]
        else:
            raise ValueError("Use .md, .txt or .docx. PDF and legacy .doc are not supported yet.")
    except (BadZipFile, KeyError, ET.ParseError, UnicodeError, RuntimeError, NotImplementedError):
        raise ValueError(
            "This file could not be read. Export it as UTF-8 text or a clean DOCX."
        ) from None
    text = text.strip()
    if not text or "\x00" in text:
        raise ValueError("No usable writing was found in this file.")
    if len(text.encode()) > MAX_SOURCE_BYTES:
        raise ValueError("Select shorter passages; extracted writing exceeds 100 KB.")
    return {"label": name, "text": text, "warnings": warnings}
