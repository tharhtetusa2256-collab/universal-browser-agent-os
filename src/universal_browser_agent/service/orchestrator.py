"""Application service that binds validation, approvals, routing, runtime, and outputs."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from ..adapters.browser_use_readonly import BrowserUseReadOnlyAdapter
from ..adapters.notion import NotionRunPublisher
from ..adapters.openrouter import (
    OpenRouterPlanner,
    OpenRouterWorkflowIntentPlanner,
)
from ..adapters.webhook import SignedWebhookPublisher
from ..agent import (
    BrowserRuntimeRouter,
    BrowserWorkflowPlanner,
    RoutingContext,
)
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
        self.runtime_router = BrowserRuntimeRouter()

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

    def _routing_for_task(
        self,
        task: RuntimeTask,
        *,
        agentic_navigation: bool = False,
        require_request_level_get_head_only: bool = False,
    ) -> dict[str, Any]:
        decision = self.runtime_router.decide(
            RoutingContext(
                mode=task.mode,
                requested_capabilities=("navigate", "extract"),
                selectors_present=bool(task.selectors),
                output_formats=task.output_formats,
                agentic_navigation=agentic_navigation,
                require_request_level_get_head_only=(
                    require_request_level_get_head_only
                ),
            )
        )
        return decision.to_dict()

    def _validate_record_workspace(self, record: RunRecord) -> None:
        if record.client_id is None:
            return
        workspace = self.get_workspace(record.client_id)
        if workspace.status != "active":
            raise ServiceRequestError(
                f"Client workspace is not active: {workspace.status}"
            )
        if record.workspace_path != workspace.manifest_path:
            raise ServiceRequestError(
                "Stored run workspace no longer matches the registry"
            )
        registered_paths = {task.path for task in workspace.tasks if task.enabled}
        if (
            record.business_path != workspace.business_path
            or record.task_path not in registered_paths
        ):
            raise ServiceRequestError(
                "Stored run configuration is no longer enabled by the client workspace"
            )

    def _load_record_task(self, record: RunRecord) -> tuple[dict[str, Any], RuntimeTask]:
        self._validate_record_workspace(record)
        business_path = self.settings.repo_root / record.business_path
        task_path = self.settings.repo_root / record.task_path
        _, task_data = load_validated_configuration(
            business_path,
            task_path,
            self.settings.repo_root,
        )
        return task_data, RuntimeTask.from_dict(task_data)

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
        runtime_task = RuntimeTask.from_dict(task_data)
        routing = self._routing_for_task(runtime_task)
        return self.store.create_run(
            idempotency_key=idempotency_key,
            source=source,
            business_path=str(business.relative_to(self.settings.repo_root)),
            task_path=str(task.relative_to(self.settings.repo_root)),
            routing=routing,
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
        runtime_task = RuntimeTask.from_dict(task_data)
        routing = self._routing_for_task(runtime_task)
        return self.store.create_run(
            idempotency_key=idempotency_key,
            source=source,
            business_path=workspace.business_path,
            task_path=task_entry.path,
            client_id=workspace.client_id,
            workspace_path=workspace.manifest_path,
            routing=routing,
        )

    def configure_run_routing(
        self,
        *,
        run_id: str,
        actor: str,
        agentic_navigation: bool,
        require_request_level_get_head_only: bool,
    ) -> RunRecord:
        actor = actor.strip()
        if not actor or len(actor) > 160:
            raise ServiceRequestError("actor must be a non-empty identifier")
        record = self.store.get_run(run_id)
        if record.client_id is not None:
            workspace = self.get_workspace(record.client_id)
            if actor != workspace.owner_id:
                raise ServiceRequestError(
                    "Only the configured workspace owner may change runtime routing"
                )
        _, task = self._load_record_task(record)
        routing = self._routing_for_task(
            task,
            agentic_navigation=agentic_navigation,
            require_request_level_get_head_only=(
                require_request_level_get_head_only
            ),
        )
        if routing["route"] == "browser-use":
            if not self.settings.browser_use_worker_enabled:
                raise ServiceRequestError(
                    "Browser Use worker dispatch is disabled. Set "
                    "UBA_BROWSER_USE_WORKER_ENABLED=true before selecting this route."
                )
            if not self.settings.openrouter_api_key:
                raise ServiceRequestError(
                    "Browser Use worker dispatch requires OPENROUTER_API_KEY"
                )
        return self.store.set_routing_decision(
            run_id=run_id,
            routing=routing,
            actor=actor,
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
            routing = record.routing or {}
            if routing.get("route") == "browser-use":
                if details.get("runtime_route_reviewed") is not True:
                    raise ServiceRequestError(
                        "Browser Use blueprint approval must confirm "
                        "runtime_route_reviewed=true"
                    )
                if not self.settings.browser_use_worker_enabled:
                    raise ServiceRequestError(
                        "Browser Use worker dispatch is disabled"
                    )
                if not self.settings.openrouter_api_key:
                    raise ServiceRequestError(
                        "Browser Use worker dispatch requires OPENROUTER_API_KEY"
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

    async def _validate_plan_scope(
        self,
        *,
        approved_domains: list[str],
        start_urls: list[str],
    ) -> None:
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

    async def propose_extraction(
        self,
        *,
        objective: str,
        approved_domains: list[str],
        start_urls: list[str],
    ) -> dict[str, Any]:
        if not self.settings.openrouter_api_key:
            raise ServiceRequestError("OpenRouter is not configured")
        await self._validate_plan_scope(
            approved_domains=approved_domains,
            start_urls=start_urls,
        )
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

    async def propose_ai_workflow(
        self,
        *,
        objective: str,
        approved_domains: list[str],
        start_urls: list[str],
    ) -> dict[str, Any]:
        """Use AI for intent drafting, then enforce deterministic LangGraph policy."""
        if not self.settings.openrouter_api_key:
            raise ServiceRequestError("OpenRouter is not configured")
        await self._validate_plan_scope(
            approved_domains=approved_domains,
            start_urls=start_urls,
        )
        intent_planner = OpenRouterWorkflowIntentPlanner(
            self.settings.openrouter_api_key,
            self.settings.openrouter_model,
        )
        intent = await asyncio.to_thread(
            intent_planner.propose_intent,
            objective=objective,
            approved_domains=approved_domains,
            start_urls=start_urls,
        )
        policy_plan = BrowserWorkflowPlanner().plan(
            objective=objective,
            approved_domains=approved_domains,
            start_urls=start_urls,
            requested_capabilities=intent["requested_capabilities"],
        )
        return {
            "model_intent": intent,
            "policy_plan": policy_plan,
            "execution_authorized": False,
        }

    async def execute_next(self) -> RunRecord | None:
        record = self.store.claim_next_run()
        if record is None:
            return None
        try:
            if not record.routing or not record.route_locked_at:
                raise ServiceRequestError(
                    "Claimed run is missing a locked runtime routing decision"
                )
            task_data, task = self._load_record_task(record)
            route = record.routing.get("route")
            self.store.append_event(
                record.run_id,
                "runtime.dispatched",
                {
                    "route": route,
                    "router": record.routing.get("router"),
                },
            )
            if route == "playwright":
                runtime = ReadOnlyPlaywrightRuntime(self.settings.repo_root, task)
                report = await runtime.run()
            elif route == "browser-use":
                if not self.settings.browser_use_worker_enabled:
                    raise ServiceRequestError(
                        "Browser Use worker dispatch is disabled"
                    )
                if not self.settings.openrouter_api_key:
                    raise ServiceRequestError(
                        "Browser Use worker dispatch requires OPENROUTER_API_KEY"
                    )
                runtime = BrowserUseReadOnlyAdapter(
                    self.settings.repo_root,
                    task,
                    objective=str(task_data.get("objective", "")).strip(),
                    model=self.settings.browser_use_model,
                )
                report = await runtime.run()
            else:
                raise ServiceRequestError(
                    f"Locked runtime route is not executable: {route}"
                )

            result = report.to_dict()
            result["runtime_route"] = route
            result["routing_router"] = record.routing.get("router")
            result["route_locked_at"] = record.route_locked_at
            completed = self.store.complete_run(
                record.run_id,
                result=result,
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
