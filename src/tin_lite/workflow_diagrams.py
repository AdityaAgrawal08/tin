from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

DIAGRAM_NODE_KINDS = frozenset({"step", "surface", "store", "wait", "gate", "receipt", "ghost"})
DIAGRAM_EDGE_KINDS = frozenset({"call", "signal"})
_NODE_ID = re.compile(r"^[a-z][a-z0-9_]*$")
_SAFE_TEXT = re.compile(r'^[^&<>"`{|};\r\n]+$')


@dataclass(frozen=True)
class DiagramNode:
    id: str
    kind: str
    label: str
    fact: str = ""

    def definition(self) -> dict[str, str]:
        value = {"id": self.id, "kind": self.kind, "label": self.label}
        if self.fact:
            value["fact"] = self.fact
        return value


@dataclass(frozen=True)
class DiagramEdge:
    source: str
    target: str
    kind: str = "call"
    label: str = ""

    def definition(self) -> dict[str, str]:
        value = {"from": self.source, "to": self.target, "kind": self.kind}
        if self.label:
            value["label"] = self.label
        return value


@dataclass(frozen=True)
class WorkflowDiagram:
    nodes: tuple[DiagramNode, ...]
    edges: tuple[DiagramEdge, ...]
    direction: str = "LR"

    def definition(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "direction": self.direction,
            "nodes": [node.definition() for node in self.nodes],
            "edges": [edge.definition() for edge in self.edges],
        }
        validate_workflow_diagram(value)
        return value


def validate_workflow_diagram(value: object) -> None:
    """Validate the deliberately small visual vocabulary stored in a workflow definition."""
    if not isinstance(value, dict) or set(value) != {"direction", "nodes", "edges"}:
        raise ValueError("workflow diagram must contain direction, nodes, and edges")
    if value["direction"] not in {"LR", "TD"}:
        raise ValueError("workflow diagram direction must be LR or TD")
    nodes = value["nodes"]
    edges = value["edges"]
    if not isinstance(nodes, list) or not 2 <= len(nodes) <= 8:
        raise ValueError("workflow diagram must contain 2-8 nodes")
    if not isinstance(edges, list) or not 1 <= len(edges) <= 12:
        raise ValueError("workflow diagram must contain 1-12 edges")

    node_ids: set[str] = set()
    adjacency: dict[str, set[str]] = {}
    for node in nodes:
        if not isinstance(node, dict) or not {"id", "kind", "label"} <= set(node) <= {
            "id",
            "kind",
            "label",
            "fact",
        }:
            raise ValueError("workflow diagram node is invalid")
        node_id = node["id"]
        if not isinstance(node_id, str) or not _NODE_ID.fullmatch(node_id):
            raise ValueError("workflow diagram node ID is invalid")
        if node_id in node_ids:
            raise ValueError("workflow diagram node IDs must be unique")
        if node["kind"] not in DIAGRAM_NODE_KINDS:
            raise ValueError("workflow diagram node kind is invalid")
        _validate_text(node["label"], field="node label", max_length=32)
        if "fact" in node:
            _validate_text(node["fact"], field="node fact", max_length=48, allow_empty=True)
        node_ids.add(node_id)
        adjacency[node_id] = set()

    seen_edges: set[tuple[str, str]] = set()
    for edge in edges:
        if not isinstance(edge, dict) or not {"from", "to", "kind"} <= set(edge) <= {
            "from",
            "to",
            "kind",
            "label",
        }:
            raise ValueError("workflow diagram edge is invalid")
        source = edge["from"]
        target = edge["to"]
        if source not in node_ids or target not in node_ids or source == target:
            raise ValueError("workflow diagram edge endpoints are invalid")
        if edge["kind"] not in DIAGRAM_EDGE_KINDS:
            raise ValueError("workflow diagram edge kind is invalid")
        if "label" in edge:
            _validate_text(edge["label"], field="edge label", max_length=40, allow_empty=True)
        pair = (source, target)
        if pair in seen_edges:
            raise ValueError("workflow diagram edges must be unique")
        seen_edges.add(pair)
        adjacency[source].add(target)
        adjacency[target].add(source)

    visited: set[str] = set()
    pending = [next(iter(node_ids))]
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        pending.extend(adjacency[current] - visited)
    if visited != node_ids:
        raise ValueError("workflow diagram must be connected")


def _validate_text(
    value: object, *, field: str, max_length: int, allow_empty: bool = False
) -> None:
    if not isinstance(value, str) or value != value.strip() or len(value) > max_length:
        raise ValueError(f"workflow diagram {field} is invalid")
    if not value and allow_empty:
        return
    if not value or not _SAFE_TEXT.fullmatch(value):
        raise ValueError(f"workflow diagram {field} is invalid")
