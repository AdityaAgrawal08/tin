from __future__ import annotations

from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from tin_lite.domain import Project


class ProjectDatabase(Protocol):
    async def list_projects_for_user(self, clerk_user_id: str) -> list[Project]: ...

    async def bootstrap_personal_project(
        self,
        *,
        workspace_id: UUID,
        workspace_name: str,
        project_id: UUID,
        name: str,
        state_repo_id: str,
        clerk_user_id: str,
        reuse_existing: bool,
    ) -> Project: ...

    async def has_workspace_access(self, *, workspace_id: UUID, clerk_user_id: str) -> bool: ...

    async def create_workspace_project(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        name: str,
        state_repo_id: str,
        clerk_user_id: str,
        request_id: UUID,
    ) -> Project: ...


class ProjectStorage(Protocol):
    async def ensure_repo(self, repo_id: str, *, initial_readme: str) -> object: ...


class ProjectProvisioningError(RuntimeError):
    pass


class ProjectCreationConflictError(RuntimeError):
    pass


def normalize_project_name(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > 80:
        raise ValueError("project name must contain between 1 and 80 characters")
    return normalized


PERSONAL_PROJECT_SUFFIXES = ("\u2019s project", "'s project")


def is_personal_project(name: str | None) -> bool:
    """The bootstrap "<name>'s project" / "My project" a new account starts with."""
    lowered = (name or "").strip().lower()
    return lowered == "my project" or lowered.endswith(PERSONAL_PROJECT_SUFFIXES)


def can_delete_project(project: Project, actor: str) -> bool:
    """Only the creator deletes a business project; rows without a creator allow any member."""
    if is_personal_project(project.name) or project.id == personal_project_id(actor):
        return False
    creator = project.created_by_clerk_user_id
    return creator is None or creator == actor


def personal_workspace_name(project_name: str) -> str:
    lowered = project_name.casefold()
    if lowered.endswith("'s project") or lowered.endswith("’s project"):
        return f"{project_name[:-7]}workspace"
    if lowered == "my project":
        return "My workspace"
    candidate = f"{project_name} workspace"
    return candidate if len(candidate) <= 80 else project_name


def personal_project_id(clerk_user_id: str) -> UUID:
    # Immutable UUID namespace, not a network URL. Changing the historic hostname
    # would change users' identities during a domain migration.
    return uuid5(
        NAMESPACE_URL,
        f"https://lite.tin.computer/users/{clerk_user_id}/personal-project",
    )


def personal_workspace_id(clerk_user_id: str) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"https://lite.tin.computer/users/{clerk_user_id}/personal-workspace",
    )


def workspace_project_id(workspace_id: UUID, request_id: UUID) -> UUID:
    return uuid5(workspace_id, f"projects/{request_id}")


async def provision_personal_project(
    *,
    database: ProjectDatabase,
    storage: ProjectStorage,
    clerk_user_id: str,
    name: str,
    reuse_existing: bool = True,
) -> Project:
    if reuse_existing:
        existing = await database.list_projects_for_user(clerk_user_id)
        if existing:
            return existing[0]

    normalized_name = normalize_project_name(name)
    workspace_id = personal_workspace_id(clerk_user_id)
    project_id = personal_project_id(clerk_user_id)
    state_repo_id = f"projects/{project_id}"
    try:
        await storage.ensure_repo(
            state_repo_id,
            initial_readme=(
                f"# {normalized_name}\n\nThis project state repository is managed by Tin.\n"
            ),
        )
    except Exception as exc:
        raise ProjectProvisioningError("project storage could not be prepared") from exc
    return await database.bootstrap_personal_project(
        workspace_id=workspace_id,
        workspace_name=personal_workspace_name(normalized_name),
        project_id=project_id,
        name=normalized_name,
        state_repo_id=state_repo_id,
        clerk_user_id=clerk_user_id,
        reuse_existing=reuse_existing,
    )


async def provision_workspace_project(
    *,
    database: ProjectDatabase,
    storage: ProjectStorage,
    workspace_id: UUID,
    clerk_user_id: str,
    name: str,
    request_id: UUID,
) -> Project:
    if not await database.has_workspace_access(
        workspace_id=workspace_id,
        clerk_user_id=clerk_user_id,
    ):
        raise LookupError("workspace not found")

    normalized_name = normalize_project_name(name)
    project_id = workspace_project_id(workspace_id, request_id)
    state_repo_id = f"projects/{project_id}"
    try:
        await storage.ensure_repo(
            state_repo_id,
            initial_readme=(
                f"# {normalized_name}\n\nThis project state repository is managed by Tin.\n"
            ),
        )
    except Exception as exc:
        raise ProjectProvisioningError("project storage could not be prepared") from exc
    return await database.create_workspace_project(
        workspace_id=workspace_id,
        project_id=project_id,
        name=normalized_name,
        state_repo_id=state_repo_id,
        clerk_user_id=clerk_user_id,
        request_id=request_id,
    )
