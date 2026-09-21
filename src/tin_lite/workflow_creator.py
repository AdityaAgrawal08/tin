"""A repo-owned creator package, activated through the existing private pilot lifecycle."""

from pathlib import Path


def creator_files():
    root = Path(__file__).with_name("workflow_creator_package")
    prefix = "workflow_packages/custom.workflow_create"
    return {
        f"{prefix}/{path.relative_to(root).as_posix()}": path.read_text()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
