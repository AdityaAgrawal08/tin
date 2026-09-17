from __future__ import annotations

import pytest

from tin_lite.catalog import BUILTIN_WORKFLOWS
from tin_lite.domain import CONTENT_DIAGRAM_WORKFLOW_NAME
from tin_lite.procedures import PinnedCodexProcedure, validate_procedure_artifact
from tin_lite.workflow_diagrams import validate_workflow_diagram


def test_builtin_presentation_flows_use_the_small_validated_vocabulary() -> None:
    presented = {
        workflow.key: workflow.definition["presentation"]["flow"]
        for workflow in BUILTIN_WORKFLOWS
        if workflow.presentation
    }

    assert set(presented) == {
        "outreach.email_campaign",
        "project.weekly_brief",
        "site.health_improve",
    }
    for flow in presented.values():
        validate_workflow_diagram(flow)

    campaign_edges = presented["outreach.email_campaign"]["edges"]
    assert [(edge["from"], edge["to"]) for edge in campaign_edges] == [
        ("snapshot", "approval"),
        ("approval", "send"),
        ("send", "wait"),
        ("wait", "follow_up"),
        ("follow_up", "receipt"),
    ]


def test_workflow_diagram_rejects_disconnected_presentation_nodes() -> None:
    with pytest.raises(ValueError, match="connected"):
        validate_workflow_diagram(
            {
                "direction": "LR",
                "nodes": [
                    {"id": "one", "kind": "step", "label": "one"},
                    {"id": "two", "kind": "step", "label": "two"},
                    {"id": "lost", "kind": "ghost", "label": "lost"},
                ],
                "edges": [{"from": "one", "to": "two", "kind": "call"}],
            }
        )


def test_content_diagram_resolves_one_safe_project_path_and_validates_source() -> None:
    workflow = next(item for item in BUILTIN_WORKFLOWS if item.key == CONTENT_DIAGRAM_WORKFLOW_NAME)
    procedure = workflow.procedure
    assert procedure is not None
    definition, _files = workflow.definition_and_resource_files()
    assert definition["procedure"]["output"]["path_template"] == "diagrams/{slug}.mmd"

    pinned = PinnedCodexProcedure(
        workflow_key=CONTENT_DIAGRAM_WORKFLOW_NAME,
        prompt="Draw it.",
        entry_skill="content-diagram",
        skill_files={"content-diagram/SKILL.md": b"instructions"},
        output_path_template="diagrams/{slug}.mmd",
        output_media_type="text/vnd.mermaid",
        output_validator="tin-diagram.v1",
        output_max_bytes=64_000,
    ).resolve_inputs({"slug": "how-tin-runs"})
    assert pinned.output_path == "diagrams/how-tin-runs.mmd"
    validate_procedure_artifact(
        b'graph LR\n  ask["founder asks<br/>one question"]:::step\n'
        b'  answer["receipt<br/>durable result"]:::receipt\n  ask --> answer\n',
        spec=pinned,
    )


@pytest.mark.parametrize("slug", ["../secret", "Too-Loud", "a/b", ""])
def test_content_diagram_rejects_unsafe_output_slugs(slug: str) -> None:
    procedure = PinnedCodexProcedure(
        workflow_key=CONTENT_DIAGRAM_WORKFLOW_NAME,
        prompt="Draw it.",
        entry_skill="content-diagram",
        skill_files={},
        output_path_template="diagrams/{slug}.mmd",
    )
    with pytest.raises(ValueError, match="slug"):
        procedure.resolve_inputs({"slug": slug})


def test_content_diagram_rejects_mermaid_outside_tin_vocabulary() -> None:
    procedure = PinnedCodexProcedure(
        workflow_key=CONTENT_DIAGRAM_WORKFLOW_NAME,
        prompt="Draw it.",
        entry_skill="content-diagram",
        skill_files={},
        output_path="diagrams/unsafe.mmd",
        output_media_type="text/vnd.mermaid",
        output_validator="tin-diagram.v1",
    )
    with pytest.raises(ValueError, match="outside"):
        validate_procedure_artifact(
            b"graph LR\n  A[unsafe] --> B[unsafe]\n  click A javascript:alert(1)\n",
            spec=procedure,
        )
    with pytest.raises(ValueError, match="node label"):
        validate_procedure_artifact(
            b'graph LR\n  one["&lt;script&gt;"]:::step\n  two["done"]:::receipt\n  one --> two\n',
            spec=procedure,
        )
