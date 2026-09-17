"""The bounded tin-diagram.v2 source grammar, shared with web/diagram-contract.js.

This validates presentation only. Groups arrange a figure; they carry no runtime
workflow behavior. v1 remains registered separately for pinned historical runs.
"""

from __future__ import annotations

import re
from typing import Any

from tin_lite.workflow_diagrams import validate_workflow_diagram

_NODE = re.compile(
    r'([a-z][a-z0-9_]*)(?:\[\("([^"]+)"\)\]|\["([^"]+)"\])'
    r":::(step|surface|store|wait|gate|receipt|ghost)"
)
_EDGE = re.compile(r"([a-z][a-z0-9_]*)\s*(-->|-\.->)(?:\|([^|]+)\|)?\s*([a-z][a-z0-9_]*)")
_GROUP = re.compile(r'subgraph ([a-z][a-z0-9_]*)(?:\["([^"]+)"\])?')


def _text(value: str, limit: int, *, empty: bool = False) -> None:
    # JS string lengths count UTF-16 code units, including two per astral glyph.
    length = len(value.encode("utf-16-le")) // 2
    if (
        (not value and not empty)
        or value != value.strip()
        or length > limit
        or re.search(r'[&<>"`{|};\r\n]', value)
    ):
        raise ValueError("Diagram text is invalid")


def parse_diagram_v2(content: str) -> dict[str, Any]:
    if len(content.encode("utf-16-le")) // 2 > 64_000:
        raise ValueError("Diagram source is too large")
    lines = content.replace("\r\n", "\n").replace("\r", "\n").rstrip().split("\n")
    header = re.fullmatch(r"graph (LR|TD|RL|BT)", lines.pop(0).strip())
    if header is None:
        raise ValueError("Diagram direction is invalid")
    flow: dict[str, Any] = {"direction": header[1], "nodes": [], "edges": []}
    stack: list[dict[str, Any]] = []
    layout: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if (
            line == "%% tin:composition"
            and "groups" not in flow
            and not flow["nodes"]
            and not flow["edges"]
        ):
            flow.update(groups=[], layout=layout)
            continue
        group = _GROUP.fullmatch(line)
        if group and "groups" in flow:
            item = {
                "id": group[1],
                "label": group[2] or "",
                "direction": flow["direction"],
                "kind": "frame" if group[2] else "layout",
                "children": [],
            }
            (stack[-1]["children"] if stack else layout).append(item["id"])
            flow["groups"].append(item)
            stack.append(item)
            continue
        if line == "end" and stack:
            stack.pop()
            continue
        direction = re.fullmatch(r"direction (LR|TD|RL|BT)", line)
        if direction and stack and not stack[-1]["children"]:
            stack[-1]["direction"] = direction[1]
            continue
        kind = re.fullmatch(r"%% tin:group (frame|lane|layout)", line)
        if kind and stack and not stack[-1]["children"]:
            stack[-1]["kind"] = kind[1]
            continue
        node = _NODE.fullmatch(line)
        if node:
            if (node[4] == "store") != (node[2] is not None):
                raise ValueError("Diagram stores must use the cylinder shape")
            parts = re.split(r"<br\s*/>", node[2] or node[3], flags=re.IGNORECASE)
            if len(parts) > 2:
                raise ValueError("Diagram nodes may have at most two logical lines")
            flow["nodes"].append(
                {
                    "id": node[1],
                    "kind": node[4],
                    "label": parts[0],
                    "fact": parts[1] if len(parts) == 2 else "",
                }
            )
            (stack[-1]["children"] if stack else layout).append(node[1])
            continue
        edge = _EDGE.fullmatch(line)
        if edge and not stack:
            flow["edges"].append(
                {
                    "from": edge[1],
                    "to": edge[4],
                    "kind": "signal" if edge[2] == "-.->" else "call",
                    "label": edge[3] or "",
                }
            )
            continue
        raise ValueError("Diagram source uses syntax outside the Tin diagram vocabulary")
    if stack:
        raise ValueError("Diagram group is not closed")
    if "groups" not in flow:
        validate_workflow_diagram(flow)
        return flow
    if not 2 <= len(flow["nodes"]) <= 32 or not 1 <= len(flow["edges"]) <= 48:
        raise ValueError("Diagram node or edge count is invalid")
    if not 1 <= len(flow["groups"]) <= 16:
        raise ValueError("Diagram group count is invalid")
    ids: set[str] = set()
    for node in flow["nodes"]:
        if node["id"] in ids:
            raise ValueError("Diagram node is duplicated")
        ids.add(node["id"])
        _text(node["label"], 80)
        _text(node["fact"], 240, empty=True)
    for group in flow["groups"]:
        if group["id"] in ids or not group["children"]:
            raise ValueError("Diagram group is invalid")
        ids.add(group["id"])
        _text(group["label"], 80, empty=group["kind"] == "layout")
    groups = {group["id"]: group for group in flow["groups"]}
    visited: set[str] = set()

    def visit(items: list[str], depth: int) -> None:
        if depth > 4:
            raise ValueError("Diagram groups exceed four levels")
        for item_id in items:
            if item_id not in ids or item_id in visited:
                raise ValueError("Diagram layout has duplicate or unknown children")
            visited.add(item_id)
            if item_id in groups:
                visit(groups[item_id]["children"], depth + 1)

    visit(layout, 0)
    if visited != ids:
        raise ValueError("Every diagram item must belong to the layout")
    endpoints = {node["id"] for node in flow["nodes"]}
    pairs: set[tuple[str, str]] = set()
    for edge in flow["edges"]:
        pair = (edge["from"], edge["to"])
        if pair in pairs or not set(pair) <= endpoints:
            raise ValueError("Diagram edge is invalid")
        pairs.add(pair)
        _text(edge["label"], 96, empty=True)
    return flow
