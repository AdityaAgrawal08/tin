from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tin_lite.diagram_compositions import parse_diagram_v2
from tin_lite.procedures import PinnedCodexProcedure, validate_procedure_artifact

STUDIES = Path(__file__).parents[1] / "docs" / "diagram-studies"
SOURCES = [file.read_text() for file in sorted(STUDIES.glob("*.mmd"))]
SMALL = """graph TD
  %% tin:composition
  subgraph lane["Input"]
    direction RL
    %% tin:group lane
    a["Ask"]:::step
    b["Done"]:::receipt
  end
  a --> b
"""
INVALID = [
    SMALL.replace("  end\n", ""),
    SMALL.replace("a --> b", "a --> lane"),
    SMALL.replace("a --> b", "a --> missing"),
    SMALL + "  click a javascript:alert(1)",
    SMALL.replace(":::receipt", ":::unknown"),
    SMALL.replace("%% tin:group lane", "%% tin:group unsafe"),
    SMALL.replace('b["Done"]', 'a["Done"]'),
    SMALL.replace("%% tin:composition", "%% arbitrary comment"),
    SMALL.replace('a["Ask"]', 'a["' + "x" * 81 + '"]'),
    SMALL.replace("a --> b", "a --> b\n  a --> b"),
]


@pytest.mark.parametrize("source", SOURCES)
def test_reference_studies_publish_only_through_v2(source: str) -> None:
    assert parse_diagram_v2(source)["groups"]
    for version in ("tin-diagram.v1", "tin-diagram.v2"):
        spec = PinnedCodexProcedure(
            workflow_key="content.diagram",
            prompt="Draw it.",
            entry_skill="content-diagram",
            skill_files={},
            output_path_template="diagrams/{slug}.mmd",
            output_media_type="text/vnd.mermaid",
            output_validator=version,
            output_max_bytes=64_000,
        ).resolve_inputs({"slug": "reference-study"})
        if version.endswith("v1"):
            with pytest.raises(ValueError):
                validate_procedure_artifact(source.encode(), spec=spec)
        else:
            validate_procedure_artifact(source.encode(), spec=spec)


@pytest.mark.parametrize("source", INVALID)
def test_compositions_reject_unsupported_source(source: str) -> None:
    with pytest.raises(ValueError):
        parse_diagram_v2(source)


def test_browser_and_server_agree_on_reference_sources_and_rejections() -> None:
    sources = SOURCES + [SMALL] + INVALID
    node = shutil.which("node")
    assert node is not None
    result = subprocess.run(  # noqa: S603 — fixed script; sources travel only through stdin
        [
            node,
            "--input-type=module",
            "-e",
            """
import fs from "node:fs";
import {parseSource} from "./web/diagram-contract.js";
console.log(JSON.stringify(JSON.parse(fs.readFileSync(0,"utf8")).map(source => {
  try { return parseSource(source); } catch { return null; }
})));""",
        ],
        input=json.dumps(sources),
        text=True,
        capture_output=True,
        check=True,
        cwd=STUDIES.parents[1],
    )
    expected = [parse_diagram_v2(source) for source in SOURCES + [SMALL]]
    assert json.loads(result.stdout) == expected + [None] * len(INVALID)


def test_composition_limits_bound_content_and_nesting() -> None:
    nodes = [f'n{i}["Node {i}<br/>{"x" * 240}"]:::step' for i in range(32)]
    edges = [f"n{i} --> n{(i + 1) % 32}" for i in range(32)]
    edges += [f"n{i} -.-> n{(i + 2) % 32}" for i in range(16)]
    source = "graph TD\n%% tin:composition\nsubgraph items\n" + "\n".join(nodes)
    source += "\nend\n" + "\n".join(edges)
    assert len(parse_diagram_v2(source)["nodes"]) == 32
    for invalid in (
        source.replace("\nend", '\nn32["Extra"]:::step\nend'),
        source + "\nn16 -.-> n18",
        SMALL.replace('a["Ask"]', 'a["Ask<br/>' + "x" * 241 + '"]'),
        SMALL.replace(
            'subgraph lane["Input"]',
            "subgraph a_group\nsubgraph b_group\nsubgraph c_group\n"
            'subgraph d_group\nsubgraph lane["Input"]',
        ).replace("  end", "end\nend\nend\nend\nend"),
    ):
        with pytest.raises(ValueError):
            parse_diagram_v2(invalid)
