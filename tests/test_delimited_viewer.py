from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
VIEWER = ROOT / "src" / "tin_lite" / "static" / "delimited-viewer.js"


def run_viewer_javascript(body: str) -> dict[str, object]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for browser parser contract tests")
    script = f"""
global.window = global;
require({json.dumps(str(VIEWER))});
(async () => {{
{body}
}})().catch((error) => {{ console.error(error); process.exit(1); }});
"""
    result = subprocess.run(  # noqa: S603
        [node, "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_delimited_viewer_parses_rfc4180_and_sniffs_supported_delimiters() -> None:
    result = run_viewer_javascript(
        r"""
const csv = TinDelimitedViewer.parseText(
  'id,name,note\r\n1,Ana,"hello, world"\r\n2,Bo,"said ""hello""\nand left"\r\n'
);
const tsv = TinDelimitedViewer.parseText('id\tname\n1\tAna\n');
const semicolon = TinDelimitedViewer.parseText('id;name\n1;Ana\n');
console.log(JSON.stringify({csv, tsv, semicolon}));
"""
    )

    assert result["csv"] == {
        "delimiter": ",",
        "delimiterLabel": "csv",
        "headers": ["id", "name", "note"],
        "rows": [["1", "Ana", "hello, world"], ["2", "Bo", 'said "hello"\nand left']],
        "totalRows": 2,
        "truncated": False,
    }
    assert result["tsv"]["delimiterLabel"] == "tsv"  # type: ignore[index]
    assert result["semicolon"]["delimiterLabel"] == "csv · semicolon"  # type: ignore[index]


def test_delimited_viewer_fails_closed_for_ambiguous_or_malformed_text() -> None:
    result = run_viewer_javascript(
        r"""
console.log(JSON.stringify({
  plain: TinDelimitedViewer.parseText('not a table\n'),
  ragged: TinDelimitedViewer.parseText('id,name\n1\n'),
  quote: TinDelimitedViewer.parseText('id,name\n1,"unfinished\n'),
  ambiguous: TinDelimitedViewer.parseText('a,b;c\n1,2;3\n'),
}));
"""
    )

    failure = {"error": "Tin couldn't read this as a table"}
    assert result == {
        "plain": failure,
        "ragged": failure,
        "quote": failure,
        "ambiguous": failure,
    }


def test_delimited_viewer_streams_large_files_and_keeps_only_visible_rows() -> None:
    result = run_viewer_javascript(
        r"""
const rows = ['id,note'];
for (let index = 0; index < 520; index += 1) {
  rows.push(`${index},${'x'.repeat(4100)}`);
}
const source = `${rows.join('\n')}\n`;
const bytes = new TextEncoder().encode(source);
const split = Math.floor(bytes.length / 2);
const stream = new ReadableStream({
  start(controller) {
    controller.enqueue(bytes.slice(0, split));
    controller.enqueue(bytes.slice(split));
    controller.close();
  },
});
const response = new Response(stream, {headers: {'content-type': 'text/csv'}});
const file = await TinDelimitedViewer.readResponse(response);
console.log(JSON.stringify({
  kind: file.kind,
  bytes: file.bytes,
  rawText: file.rawText,
  visibleRows: file.table.rows.length,
  totalRows: file.table.totalRows,
  truncated: file.table.truncated,
}));
"""
    )

    assert result["kind"] == "delimited"
    assert result["bytes"] > 2 * 1024 * 1024  # type: ignore[operator]
    assert result["rawText"] is None
    assert result["visibleRows"] == 500
    assert result["totalRows"] == 520
    assert result["truncated"] is True
