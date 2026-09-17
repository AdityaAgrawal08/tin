"""Regenerate with uv run --no-project --with fonttools --with brotli python <this file>."""

import json
from pathlib import Path

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
metrics = {}
vertical = {}
for face, filename in (
    ("regular", "geist-sans-regular"),
    ("bold", "geist-sans-bold"),
    ("mono", "geist-mono-regular"),
    ("monoBold", "geist-mono-bold"),
):
    font = TTFont(ROOT / f"src/tin_lite/static/fonts/{filename}.woff2")
    cmap = font.getBestCmap()
    units = font["head"].unitsPerEm
    vertical[face] = {
        "ascent": round(font["hhea"].ascent / units, 4),
        "descent": round(-font["hhea"].descent / units, 4),
    }
    if face in ("regular", "bold"):
        metrics[face] = {
            chr(code): round(font["hmtx"][cmap[code]][0] / units, 4)
            for code in range(32, 384)
            if code in cmap
        }

(ROOT / "web/diagram-font-metrics.js").write_text(
    "// Advance widths in em from the packaged Geist Sans faces (U+0020–017F).\n"
    "// Kept with the fonts so layout is deterministic before browser font loading.\n"
    f"export const FONT_ADVANCES = {json.dumps(metrics, ensure_ascii=True, indent=2)};\n"
    f"export const FONT_VERTICAL = {json.dumps(vertical, indent=2)};\n"
)
