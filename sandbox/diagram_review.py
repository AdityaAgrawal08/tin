"""Bounded Codex render/inspect/repair loop. Previews are temporary, never artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

VALIDATOR = "tin-diagram.reviewed.v1"
CHECKER = "/opt/tin-lite/diagram/scripts/check_diagram.mjs"


class DiagramReview:
    def __init__(self, candidate: Path):
        self.candidate = candidate
        self.directory = Path(tempfile.mkdtemp(prefix="tin-diagram-review-"))
        self.directory.chmod(0o1777)  # noqa: S103 — worker creates previews, sticky controller root
        self.inspected_sha = None
        self.candidates = 0
        self.turns = 0
        self.report = None

    def check(self):
        output = self.directory / str(self.turns)
        command = [
            "/usr/bin/env",
            "node",
            CHECKER,
            "check",
            str(self.candidate),
            "--out",
            str(output),
        ]
        if os.environ.get("TIN_PROCEDURE_ISOLATED") == "1":
            command = [
                "/usr/bin/sudo",
                "-n",
                "/opt/tin-lite/isolated-procedure",
                "diagram-check",
                str(self.candidate),
                str(output),
            ]
        completed = subprocess.run(  # noqa: S603 — fixed checker, bounded paths, no project code
            command,
            capture_output=True,
            text=True,
            timeout=90,
        )
        if completed.returncode not in (0, 1) or len(completed.stdout) > 64000:
            raise RuntimeError("Diagram checker is unavailable")
        try:
            report = json.loads(completed.stdout)
        except ValueError as exc:
            raise RuntimeError("Diagram checker did not produce diagnostics") from exc
        if report.get("checker") != "tin-diagram-check.v1":
            raise RuntimeError("Diagram checker version is unavailable")
        return report

    def next_input(self, result: dict):
        self.turns += 1
        if self.turns > 6:
            raise RuntimeError("Diagram inspection exhausted its bounded repair attempts")
        report = self.check()
        sha = report["source_sha256"]
        if (
            report["passed"]
            and self.inspected_sha == sha
            and result.get("inspected_sha256") == sha
            and result.get("accepted") is True
        ):
            self.report = {
                key: report[key]
                for key in (
                    "checker",
                    "source_sha256",
                    "source_bytes",
                    "renderer_sha256",
                    "browser_version",
                )
            }
            self.report.update({"candidates": self.candidates, "visual_inspection": True})
            return None
        if self.inspected_sha is not None and self.inspected_sha == sha:
            # The inspector requested changes without making them. The next turn
            # must repair; it does not get to approve the same rejected candidate.
            self.inspected_sha = None
            if self.candidates >= 3:
                raise RuntimeError("Diagram still needs repairs after two revisions")
            return [
                {
                    "type": "text",
                    "text": (
                        "Repair the diagram according to your visual inspection now. Preserve "
                        "the facts. This is a bounded repair attempt, not another planning turn. "
                        "Set accepted=false and inspected_sha256='' after editing."
                    ),
                }
            ]
        self.candidates += 1
        if self.candidates > 3:
            raise RuntimeError("Diagram still fails after two repair attempts")
        if not report["passed"]:
            if self.candidates == 3:
                raise RuntimeError(
                    "Diagram failed final visual validation: "
                    + "; ".join(report["issues"][:3])[:700]
                )
            return [
                {
                    "type": "text",
                    "text": "The actual candidate failed Tin's offline check. Repair its "
                    "grammar/layout without deleting required facts. Diagnostics: "
                    + json.dumps(report["issues"])[:10000]
                    + ". Set accepted=false and inspected_sha256='' after editing.",
                }
            ]
        self.inspected_sha = sha
        directory = self.directory / str(self.turns)
        return [
            {
                "type": "text",
                "text": (
                    f"Inspect these actual light/dark renders of candidate SHA-256 {sha}. "
                    f"Read natural-scale detail-*.png tiles in {directory} with the image viewer "
                    "if present. Overviews alone do not establish readable labels. Check meaning "
                    "against the brief and project sources: grouping, reading order, parallel "
                    "work, return paths, labels, and unsupported claims. Follow the main sequence "
                    "from its entry to any actual terminal outcome; check consecutive axes, "
                    "balanced equivalent branches, unnecessary bends, and wasted space. "
                    "These advisory measurements describe geometry, not semantic correctness: "
                    + json.dumps(
                        [
                            {"theme": theme.get("theme"), "quality": theme["quality"]}
                            for theme in report.get("themes", [])
                            if "quality" in theme
                        ]
                    )[:4000]
                    + ". Fit scale uses a fixed 1200 by 800 viewport. Smaller is harder to read; "
                    "never chase fewer bends by making the overview much smaller. "
                    "Geometry passed; that "
                    "does NOT establish semantic quality. If genuinely clear and faithful, do "
                    "not edit: set accepted=true and inspected_sha256 "
                    f"to {sha}. Otherwise repair the .mmd and return accepted=false, "
                    "inspected_sha256=''. Only two repaired candidates are allowed. "
                    "Do not write previews into project state. Return source_paths naming "
                    "only project documents you actually used, never a guessed citation."
                ),
            },
            *[{"type": "localImage", "path": preview} for preview in report["previews"]],
        ]

    def source_evidence(self, paths, workspace):
        if not isinstance(paths, list) or len(paths) > 12:
            raise RuntimeError("Diagram source references exceed their bound")
        revision = subprocess.check_output(  # noqa: S603 — pinned checkout metadata
            ["/usr/bin/git", "-C", str(workspace), "rev-parse", "HEAD"], text=True
        ).strip()
        if revision != os.environ.get("TIN_PROCEDURE_PROJECT_REVISION"):
            raise RuntimeError("Diagram source checkout moved from its captured revision")
        sources = []
        for value in dict.fromkeys(paths):
            p = Path(value)
            if p.is_absolute() or ".." in p.parts or not p.parts or p.parts[0] == ".git":
                raise RuntimeError("Invalid diagram source reference")
            raw = subprocess.check_output(  # noqa: S603 — immutable Git blob, never executable
                ["/usr/bin/git", "-C", str(workspace), "show", f"{revision}:{value}"]
            )
            if len(raw) > 1_000_000:
                raise RuntimeError("Diagram source reference exceeds its bound")
            sources.append(
                {"path": value, "revision": revision, "sha256": hashlib.sha256(raw).hexdigest()}
            )
        return sources
