"""The original DESIGN.md task on the shared API procedure runner.

Keep the public workflow identity, Temporal commands and canonical publication
unchanged. The controller context is pinned with the sandbox-creation receipt.
"""

from tin_lite.procedures import PinnedCodexProcedure, SandboxProfile


def procedure(timeout_seconds=900):
    instructions = (
        "Analyze this repository and create a concrete, concise DESIGN.md describing its "
        "product design, information architecture, visual system, key user flows, component "
        "structure, responsive behavior, and accessibility requirements. Write or replace "
        "DESIGN.md only. Do not modify any other file. Distinguish observed implementation "
        "from recommendations; do not invent repository features."
    )
    return PinnedCodexProcedure(
        workflow_key="content.design_md",
        prompt=instructions,
        entry_skill="project-design",
        skill_files={
            "project-design/SKILL.md": (
                "---\nname: project-design\ndescription: Document the project's design.\n---\n\n"
                + instructions
            ).encode(),
        },
        output_path="DESIGN.md",
        output_media_type="text/markdown",
        output_max_bytes=1_000_000,
        sandbox=SandboxProfile(timeout_seconds=timeout_seconds),
    )
