"""Convert measured FK/Geist glyphs to paths for dependency-free GitHub SVG images.

Invoked by render_readme_diagrams.mjs with pinned fontTools and Brotli via uv.
Text positions come from the browser after the real fonts load. No font binaries,
remote font requests, script, or CSS are needed by the exported figure.
"""

import json
import sys
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree as ET

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", NS)
font_dir, input_path, output_path = map(Path, sys.argv[1:])
payload = json.loads(input_path.read_text())
# The pinned local renderer creates this SVG; arbitrary SVG input is not accepted.
root = ET.fromstring(payload["svg"])  # noqa: S314


@lru_cache
def face(name):
    font = TTFont(font_dir / name)
    return font.getGlyphSet(), font.getBestCmap(), font["head"].unitsPerEm


for group in payload["text"]:
    element = next(e for e in root.iter() if e.get("data-outline-id") == group["id"])
    parent = next(p for p in root.iter() if element in list(p))
    replacement = ET.Element(f"{{{NS}}}g", {"aria-label": group["label"]})
    for line in group["lines"]:
        glyphs, cmap, upem = face(line["font"])
        pen = SVGPathPen(glyphs, ntos=lambda n: f"{n:.3f}".rstrip("0").rstrip("."))
        scale = line["size"] / upem
        for char in line["chars"]:
            glyph_name = cmap.get(ord(char["char"]))
            if glyph_name is None:
                raise ValueError(f"Missing glyph {char['char']!r} in {line['font']}")
            transform = TransformPen(pen, (scale, 0, 0, -scale, char["x"], char["y"]))
            glyphs[glyph_name].draw(transform)
        if pen.getCommands():
            ET.SubElement(
                replacement, f"{{{NS}}}path", {"d": pen.getCommands(), "fill": line["fill"]}
            )
    parent.insert(list(parent).index(element), replacement)
    parent.remove(element)

ET.indent(root, space="  ")
output_path.write_text(ET.tostring(root, encoding="unicode") + "\n")
