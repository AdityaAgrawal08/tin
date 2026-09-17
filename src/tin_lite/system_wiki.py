from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tin_lite.code_storage import CodeStorage

SYSTEM_WIKI_REPO_ID = "wiki/system"
SYSTEM_WIKI_BRANCH = "main"
PROJECT_SCANNING_PATH = "growth/project-scanning.md"


@dataclass(frozen=True)
class SystemWikiRef:
    repo_id: str
    path: str
    commit_sha: str

    @property
    def artifact_ref(self) -> str:
        return f"code.storage://{self.repo_id}@{self.commit_sha}/{self.path}"


async def sync_system_wiki(*, storage: CodeStorage, source_root: Path) -> SystemWikiRef:
    """Publish the one system-wiki proof document and return its immutable reference."""
    path = source_root / PROJECT_SCANNING_PATH
    content = path.read_bytes()
    validate_system_wiki_document(content)
    commit_sha = await storage.publish_system_wiki_document(
        repo_id=SYSTEM_WIKI_REPO_ID,
        branch=SYSTEM_WIKI_BRANCH,
        path=PROJECT_SCANNING_PATH,
        content=content,
        commit_message="Publish project scanning principles",
    )
    return SystemWikiRef(
        repo_id=SYSTEM_WIKI_REPO_ID,
        path=PROJECT_SCANNING_PATH,
        commit_sha=commit_sha,
    )


async def read_system_wiki_document(
    *, storage: CodeStorage, commit_sha: str
) -> tuple[SystemWikiRef, str]:
    ref = SystemWikiRef(
        repo_id=SYSTEM_WIKI_REPO_ID,
        path=PROJECT_SCANNING_PATH,
        commit_sha=commit_sha,
    )
    content = await storage.read_canonical_artifact(
        repo_id=ref.repo_id,
        commit_sha=ref.commit_sha,
        path=ref.path,
    )
    validate_system_wiki_document(content)
    return ref, content.decode("utf-8")


def validate_system_wiki_document(content: bytes) -> None:
    if not content or len(content) > 100_000:
        raise ValueError("system wiki document must contain between 1 and 100000 bytes")
    text = content.decode("utf-8")
    if not text.startswith("# "):
        raise ValueError("system wiki document must be Markdown")
