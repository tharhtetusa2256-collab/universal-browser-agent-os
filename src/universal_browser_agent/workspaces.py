"""Repository-native client workspaces for one operator serving many clients."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .models import RuntimeTask
from .validation import (
    ConfigurationValidationError,
    find_secret_like_keys,
    load_json,
    load_validated_configuration,
    validate_against_schema,
)


class WorkspaceValidationError(ValueError):
    """Raised when a client workspace violates isolation or its contract."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


class WorkspaceNotFoundError(KeyError):
    """Raised when a requested client workspace does not exist."""


@dataclass(frozen=True)
class WorkspaceTask:
    task_id: str
    path: str
    enabled: bool


@dataclass(frozen=True)
class ClientWorkspace:
    client_id: str
    display_name: str
    status: str
    owner_id: str
    manifest_path: str
    business_path: str
    artifact_root: str
    tasks: tuple[WorkspaceTask, ...]
    allowed_integrations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def get_task(self, task_id: str) -> WorkspaceTask:
        for task in self.tasks:
            if task.task_id == task_id:
                if not task.enabled:
                    raise WorkspaceValidationError(
                        [f"Task is disabled for client {self.client_id}: {task_id}"]
                    )
                return task
        raise WorkspaceValidationError(
            [f"Unknown task for client {self.client_id}: {task_id}"]
        )


class WorkspaceRegistry:
    """Discovers and validates client manifests below ``clients/``."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root.resolve()
        self.clients_root = (self.repo_root / "clients").resolve()

    @staticmethod
    def _safe_child(base: Path, relative_value: str, label: str) -> Path:
        relative = Path(relative_value)
        if relative.is_absolute() or ".." in relative.parts:
            raise WorkspaceValidationError(
                [f"{label} must be a safe workspace-relative path"]
            )
        candidate = (base / relative).resolve()
        try:
            candidate.relative_to(base.resolve())
        except ValueError as exc:
            raise WorkspaceValidationError(
                [f"{label} must remain inside the client workspace"]
            ) from exc
        return candidate

    def _manifest_path(self, client_id: str) -> Path:
        if not client_id or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789-"
            for character in client_id
        ):
            raise WorkspaceNotFoundError(client_id)
        path = (self.clients_root / client_id / "workspace.json").resolve()
        try:
            path.relative_to(self.clients_root)
        except ValueError as exc:
            raise WorkspaceNotFoundError(client_id) from exc
        if not path.is_file():
            raise WorkspaceNotFoundError(client_id)
        return path

    def list(self) -> list[ClientWorkspace]:
        if not self.clients_root.is_dir():
            return []
        workspaces = []
        for manifest in sorted(self.clients_root.glob("*/workspace.json")):
            workspaces.append(self.load(manifest.parent.name))
        return workspaces

    def load(self, client_id: str) -> ClientWorkspace:
        manifest_path = self._manifest_path(client_id)
        workspace_root = manifest_path.parent.resolve()
        data = load_json(manifest_path)
        errors = validate_against_schema(
            data,
            self.repo_root / "schemas/client-workspace.schema.json",
            "workspace",
        )
        secret_keys = find_secret_like_keys(data)
        if secret_keys:
            errors.append(f"workspace secret-like fields are prohibited: {secret_keys}")
        if data.get("client_id") != client_id:
            errors.append("workspace client_id must match its directory name")
        expected_artifact_root = f"artifacts/clients/{client_id}"
        if data.get("artifact_root") != expected_artifact_root:
            errors.append(
                f"artifact_root must be exactly {expected_artifact_root!r}"
            )

        try:
            business_path = self._safe_child(
                workspace_root,
                str(data.get("business_profile", "")),
                "business_profile",
            )
        except WorkspaceValidationError as exc:
            errors.extend(exc.errors)
            business_path = workspace_root / "missing-business-profile.json"

        task_entries = data.get("tasks", [])
        task_ids: set[str] = set()
        task_paths: set[str] = set()
        tasks: list[WorkspaceTask] = []
        if isinstance(task_entries, list):
            for index, entry in enumerate(task_entries):
                if not isinstance(entry, dict):
                    continue
                task_id = str(entry.get("task_id", ""))
                task_path_value = str(entry.get("path", ""))
                if task_id in task_ids:
                    errors.append(f"duplicate task_id in workspace: {task_id}")
                if task_path_value in task_paths:
                    errors.append(f"duplicate task path in workspace: {task_path_value}")
                task_ids.add(task_id)
                task_paths.add(task_path_value)
                try:
                    task_path = self._safe_child(
                        workspace_root,
                        task_path_value,
                        f"tasks[{index}].path",
                    )
                except WorkspaceValidationError as exc:
                    errors.extend(exc.errors)
                    continue
                if not task_path.is_file():
                    errors.append(f"workspace task does not exist: {task_path_value}")
                    continue
                try:
                    _, task_data = load_validated_configuration(
                        business_path,
                        task_path,
                        self.repo_root,
                    )
                    runtime_task = RuntimeTask.from_dict(task_data)
                except (ConfigurationValidationError, ValueError) as exc:
                    errors.append(f"invalid workspace task {task_id}: {exc}")
                    continue
                if runtime_task.task_id != task_id:
                    errors.append(
                        f"manifest task_id {task_id!r} does not match task file "
                        f"{runtime_task.task_id!r}"
                    )
                destination = Path(runtime_task.destination)
                artifact_root = Path(expected_artifact_root)
                if destination.is_absolute() or ".." in destination.parts:
                    errors.append(
                        f"task {task_id!r} output must be a safe "
                        "repository-relative path"
                    )
                elif not (
                    destination == artifact_root
                    or artifact_root in destination.parents
                ):
                    errors.append(
                        f"task {task_id!r} output must remain under "
                        f"{expected_artifact_root}/"
                    )
                tasks.append(
                    WorkspaceTask(
                        task_id=task_id,
                        path=str(task_path.relative_to(self.repo_root)),
                        enabled=entry.get("enabled") is True,
                    )
                )

        if not business_path.is_file():
            errors.append("workspace business profile does not exist")
        else:
            business_data = load_json(business_path)
            business_id = business_data.get("business", {}).get("id")
            if business_id != client_id:
                errors.append("business.id must match workspace client_id")

        if errors:
            raise WorkspaceValidationError(errors)

        return ClientWorkspace(
            client_id=client_id,
            display_name=data["display_name"],
            status=data["status"],
            owner_id=data["owner_id"],
            manifest_path=str(manifest_path.relative_to(self.repo_root)),
            business_path=str(business_path.relative_to(self.repo_root)),
            artifact_root=expected_artifact_root,
            tasks=tuple(tasks),
            allowed_integrations=tuple(data.get("allowed_integrations", [])),
        )
