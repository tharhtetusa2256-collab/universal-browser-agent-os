"""Application service that binds validation, approvals, runtime, and outputs."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from ..adapters.notion import NotionRunPublisher
from ..adapters.openrouter import OpenRouterPlanner
from ..adapters.webhook import SignedWebhookPublisher
from ..models import RuntimeTask
from ..playwright_runtime import ReadOnlyPlaywrightRuntime
from ..policy import DomainPolicy
from ..validation import (
    find_secret_like_keys,
    is_valid_domain,
    load_validated_configuration,
)
from ..workspaces import (
    ClientWorkspace,
    WorkspaceNotFoundError,
    WorkspaceRegistry,
    WorkspaceValidationError,
)
from .config import ServiceSettings
from .store import RunRecord, RunStore


IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9._:-]{8,160}$")
SOURCE_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")


class ServiceRequestError(ValueError):
    """Raised when a service request cannot safely be accepted."""


class RunOrchestrator:
    def __init__(self, settings: ServiceSettings, store: RunStore) -> None:
        self.settings = settings
        self.store = store
        self.workspaces = WorkspaceRegistry(settings.repo_root)

    def list_workspaces(self) -> list[ClientWorkspace]:
        return self.workspaces.list()

    def get_workspace(self, client_id: str) -> ClientWorkspace:
        try:
            return self.workspaces.load(client_id)
        except (WorkspaceNotFoundError, WorkspaceValidationError) as exc:
            raise ServiceRequestError(str(exc)) from exc

    def _resolve_json_path(
        self,
        value: str,
        *,
        allowed_roots: tuple[str, ...],
    ) -> Path:
        if not value.endswith(".json"):
            raise ServiceRequestError("Configuration path must end in .json")
        candidate = (self.settings.repo_root / value).resolve()
        repo_root = self.settings.repo_root.resolve()
        try:
            relative = candidate.relative_to(repo_root)
        except ValueError as exc:
            raise ServiceRequestError(
                "Configuration path must remain inside the repository"
            ) from exc
        if not any(
            relative == Path(root) or Path(root) in relative.parents
            for root in allowed_roots
        ):
            raise ServiceRequestError(
                f"Configuration path must be under {', '.join(allowed_roots)}"
            )
        if not candidate.is_file():
            raise ServiceRequestError(f"Configuration file does not exist: {value}")
        return candidate

    def create_run(
        self,
        *,
        idempotency_key: str,
        source: str,
        business_path: str,
        task_path: str,
    ) -> tuple[RunRecord, bool]:
        if not IDEMPOTENCY_RE.fullmatch(idempotency_key):
            raise ServiceRequestError(
                "Idempotency-Key must contain 8-160 safe characters"
            )
        if not SOURCE_RE.fullmatch(source):
            raise ServiceRequestError("source must be a lowercase slug")

        business = self._resolve_json_path(
            business_path,
            allowed_roots=("configs",),
        )
        task = self._resolve_json_path(
            task_path,
            allowed_roots=("configs", "templates"),
        )
        _, task_data = load_validated_configuration(
            business,
            task,
            self.settings.repo_root,
        )
        RuntimeTask.from_dict(task_data)
        return self.store.create_run(
            idempotency_key=idempotency_key,
            source=source,
            business_path=str(business.relative_to(self.settings.repo_root)),
            task_path=str(task.relative_to(self.settings.repo_root)),
        )

    def create_client_run(
        self,
        *,
        client_id: str,
        task_id: str,
        idempotency_key: str,
        source: str,
    ) -> tuple[RunRecord, bool]:
        if not IDEMPOTENCY_RE.fullmatch(idempotency_key):
            raise ServiceRequestError(
                "Idempotency-Key must contain 8-160 safe characters"
            )
        if not SOURCE_RE.fullmatch(source):
            raise ServiceRequestError("source must be a lowercase slug")
        workspace = self.get_workspace(client_id)
        if workspace.status != "active":
            raise ServiceRequestError(
                f"Client workspace is not active: {workspace.status}"
            )
        task_entry = workspace.get_task(task_id)
        business = self.settings.repo_root / workspace.business_path
        task = self.settings.repo_root / task_entry.path
        _, task_data = load_validated_configuration(
            business,
            task,
            self.settings.repo_root,
        )
        RuntimeTask.from_dict(task_data)
        return self.store.create_run(
            idempotency_key=idempotency_key,
            source=source,
            business_path=workspace.business_path,
            task_path=task_entry.path,
            client_id=workspace.client_id,
            workspace_path=workspace.manifest_path,
        )

    def approve_run(
        self,
        *,
        run_id: str,
        approval_kind: str,
        decision: str,
        actor: str,
        details: dict[str, Any],
    ) -> RunRecord:
        if not actor.strip() or len(actor) > 160:
            raise ServiceRequestError("actor must be a non-empty identifier")
        record = self.store.get_run(run_id)
        if record.client_id is not None:
            workspace = self.get_workspace(record.client_id)
            if workspace.status != "active":
                raise ServiceRequestError(
                    f"Client workspace is not active: {workspace.status}"
                )
            if actor.strip() != workspace.owner_id:
                raise ServiceRequestError(
                    "Only the configured workspace owner may approve this run"
                )
        if approval_kind == "blueprint" and decision == "approved":
            required = {"objective_reviewed", "domains_reviewed"}
            if not required.issubset(details):
                raise ServiceRequestError(
                    "Blueprint approval must confirm objective_reviewed and "
                    "domains_reviewed"
                )
            if (
                details["objective_reviewed"] is not True
                or details["domains_reviewed"] is not True
            ):
                raise ServiceRequestError(
                    "Blueprint approval confirmations must both be true"
                )
        secret_keys = find_secret_like_keys(details)
        if secret_keys:
            raise ServiceRequestError(
                f"Approval details contain prohibited secret-like fields: {secret_keys}"
            )
        return self.store.record_approval(
            run_id=run_id,
            approval_kind=approval_kind,
            decision=decision,
            actor=actor.strip(),
            details=details,
        )

    async def propose_extraction(
        self,
        *,
        objective: str,
        approved_domains: list[str],
        start_urls: list[str],
    ) -> dict[str, Any]:
        if not self.settings.openrouter_api_key:
            raise ServiceRequestError("OpenRouter is not configured")
        if (
            not approved_domains
            or len(approved_domains) != len(set(approved_domains))
            or not all(is_valid_domain(domain) for domain in approved_domains)
        ):
            raise ServiceRequestError(
                "approved_domains must contain unique valid public domains"
            )
        if not start_urls:
            raise ServiceRequestError("start_urls must not be empty")
        policy = DomainPolicy(tuple(approved_domains))
        for url in start_urls:
            await policy.validate_url(url)
        planner = OpenRouterPlanner(
            self.settings.openrouter_api_key,
            self.settings.openrouter_model,
        )
        return await asyncio.to_thread(
            planner.propose_extraction,
            objective=objective,
            approved_domains=approved_domains,
            start_urls=start_urls,
        )

    async def execute_next(self) -> RunRecord | None:
        record = self.store.claim_next_run()
        if record is None:
            return None
        try:
            if record.client_id is not None:
                workspace = self.get_workspace(record.client_id)
                if workspace.status != "active":
                    raise ServiceRequestError(
                        f"Client workspace is not active: {workspace.status}"
                    )
                if record.workspace_path != workspace.manifest_path:
                    raise ServiceRequestError(
                        "Stored run workspace no longer matches the registry"
                    )
                registered_paths = {
                    task.path for task in workspace.tasks if task.enabled
                }
                if (
                    record.business_path != workspace.business_path
                    or record.task_path not in registered_paths
                ):
                    raise ServiceRequestError(
                        "Stored run configuration is no longer enabled by the "
                        "client workspace"
                    )
            business_path = self.settings.repo_root / record.business_path
            task_path = self.settings.repo_root / record.task_path
            _, task_data = load_validated_configuration(
                business_path,
                task_path,
                self.settings.repo_root,
            )
            task = RuntimeTask.from_dict(task_data)
            runtime = ReadOnlyPlaywrightRuntime(self.settings.repo_root, task)
            report = await runtime.run()
            completed = self.store.complete_run(
                record.run_id,
                result=report.to_dict(),
                succeeded=report.status != "failed",
            )
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"[:2_000]
            completed = self.store.fail_run(record.run_id, message)

        await self._publish_outputs(completed)
        return completed

    async def _publish_outputs(self, record: RunRecord) -> None:
        run = record.to_dict()
        publishers: list[tuple[str, Any]] = []
        allowed_integrations: set[str] | None = None
        if record.client_id is not None:
            workspace = self.get_workspace(record.client_id)
            allowed_integrations = set(workspace.allowed_integrations)

        def integration_allowed(name: str) -> bool:
            return allowed_integrations is None or name in allowed_integrations

        if (
            integration_allowed("notion")
            and self.settings.notion_api_key
            and self.settings.notion_database_id
        ):
            publishers.append(
                (
                    "notion",
                    NotionRunPublisher(
                        self.settings.notion_api_key,
                        self.settings.notion_database_id,
                        title_property=self.settings.notion_title_property,
                    ),
                )
            )
        if (
            integration_allowed("webhook")
            and self.settings.outbound_webhook_url
        ):
            publishers.append(
                (
                    "webhook",
                    SignedWebhookPublisher(
                        self.settings.outbound_webhook_url,
                        secret=self.settings.outbound_webhook_secret,
                    ),
                )
            )

        for name, publisher in publishers:
            try:
                if name == "notion":
                    await asyncio.to_thread(publisher.publish, run)
                else:
                    await asyncio.to_thread(
                        publisher.publish,
                        f"run.{record.status}",
                        run,
                    )
                self.store.append_event(
                    record.run_id,
                    f"output.{name}.delivered",
                    {},
                )
            except Exception as exc:
                self.store.append_event(
                    record.run_id,
                    f"output.{name}.failed",
                    {"error": f"{type(exc).__name__}: {exc}"[:1_000]},
                )
