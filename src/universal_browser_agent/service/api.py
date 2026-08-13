"""FastAPI control plane for approval-gated browser-agent runs."""

from __future__ import annotations

import hmac
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from ..agent import BrowserRuntimeRouter, BrowserWorkflowPlanner, RoutingContext
from .config import ServiceSettings
from .orchestrator import RunOrchestrator, ServiceRequestError
from .store import RunNotFoundError, RunStateError, RunStore


class RunCreateRequest(BaseModel):
    business_profile: str
    task_spec: str
    source: str = Field(default="api", min_length=2, max_length=40)


class ClientRunCreateRequest(BaseModel):
    task_id: str = Field(min_length=3, max_length=80)
    source: str = Field(default="api", min_length=2, max_length=40)


class ApprovalRequest(BaseModel):
    kind: str = Field(default="blueprint")
    decision: str
    actor: str = Field(min_length=1, max_length=160)
    details: dict[str, Any] = Field(default_factory=dict)


class RunRoutingRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=160)
    agentic_navigation: bool = False
    require_request_level_get_head_only: bool = False


class PlanRequest(BaseModel):
    objective: str = Field(min_length=12, max_length=1_000)
    approved_domains: list[str] = Field(min_length=1, max_length=50)
    start_urls: list[str] = Field(min_length=1, max_length=50)


class BrowserWorkflowPlanRequest(PlanRequest):
    requested_capabilities: list[str] = Field(
        default_factory=lambda: ["navigate", "extract"],
        min_length=1,
        max_length=25,
    )


class BrowserRuntimeRouteRequest(BaseModel):
    mode: str = Field(default="research-only", min_length=2, max_length=40)
    requested_capabilities: list[str] = Field(
        default_factory=lambda: ["navigate", "extract"],
        min_length=1,
        max_length=25,
    )
    selectors_present: bool = False
    output_formats: list[str] = Field(
        default_factory=lambda: ["json", "markdown", "screenshots"],
        min_length=1,
        max_length=10,
    )
    agentic_navigation: bool = False
    require_request_level_get_head_only: bool = False


def create_app(settings: Optional[ServiceSettings] = None) -> FastAPI:
    resolved = settings or ServiceSettings.from_env()
    resolved.require_api_token()
    store = RunStore(resolved.database_path)
    orchestrator = RunOrchestrator(resolved, store)
    workflow_planner = BrowserWorkflowPlanner()
    runtime_router = BrowserRuntimeRouter()
    app = FastAPI(
        title="Tharhtet Browser Agent",
        version="0.6.2",
        description=(
            "Approval-gated API for validated browser-agent planning, durable "
            "runtime routing, and public read-only execution. State-changing "
            "browser actions remain unsupported."
        ),
    )

    def require_token(authorization: Optional[str] = Header(default=None)) -> None:
        expected = f"Bearer {resolved.api_token}"
        if authorization is None or not hmac.compare_digest(authorization, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Valid bearer token required",
            )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": "0.6.2"}

    @app.get("/v1/clients", dependencies=[Depends(require_token)])
    def list_clients() -> dict[str, Any]:
        try:
            clients = [workspace.to_dict() for workspace in orchestrator.list_workspaces()]
        except (ServiceRequestError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"clients": clients}

    @app.get(
        "/v1/clients/{client_id}",
        dependencies=[Depends(require_token)],
    )
    def get_client(client_id: str) -> dict[str, Any]:
        try:
            return {"client": orchestrator.get_workspace(client_id).to_dict()}
        except ServiceRequestError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get(
        "/v1/clients/{client_id}/runs",
        dependencies=[Depends(require_token)],
    )
    def list_client_runs(client_id: str, limit: int = 100) -> dict[str, Any]:
        try:
            orchestrator.get_workspace(client_id)
            runs = store.list_runs(client_id=client_id, limit=limit)
        except ServiceRequestError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"runs": [record.to_dict() for record in runs]}

    @app.post(
        "/v1/clients/{client_id}/runs",
        dependencies=[Depends(require_token)],
        status_code=status.HTTP_202_ACCEPTED,
    )
    def create_client_run(
        client_id: str,
        request: ClientRunCreateRequest,
        idempotency_key: str = Header(alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        try:
            record, created = orchestrator.create_client_run(
                client_id=client_id,
                task_id=request.task_id,
                idempotency_key=idempotency_key,
                source=request.source,
            )
        except RunStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ServiceRequestError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"created": created, "run": record.to_dict()}

    @app.post(
        "/v1/runs",
        dependencies=[Depends(require_token)],
        status_code=status.HTTP_202_ACCEPTED,
    )
    def create_run(
        request: RunCreateRequest,
        idempotency_key: str = Header(alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        try:
            record, created = orchestrator.create_run(
                idempotency_key=idempotency_key,
                source=request.source,
                business_path=request.business_profile,
                task_path=request.task_spec,
            )
        except RunStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ServiceRequestError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
        return {"created": created, "run": record.to_dict()}

    @app.get("/v1/runs/{run_id}", dependencies=[Depends(require_token)])
    def get_run(run_id: str) -> dict[str, Any]:
        try:
            record = store.get_run(run_id)
            return {
                "run": record.to_dict(),
                "events": store.list_events(run_id),
            }
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc

    @app.post(
        "/v1/runs/{run_id}/routing",
        dependencies=[Depends(require_token)],
    )
    def configure_run_routing(
        run_id: str,
        request: RunRoutingRequest,
    ) -> dict[str, Any]:
        try:
            record = orchestrator.configure_run_routing(
                run_id=run_id,
                actor=request.actor,
                agentic_navigation=request.agentic_navigation,
                require_request_level_get_head_only=(
                    request.require_request_level_get_head_only
                ),
            )
            return {
                "status": "routing-persisted",
                "executable": False,
                "run": record.to_dict(),
                "notice": (
                    "The routing decision is durable but is not executable until "
                    "blueprint approval locks the selected route."
                ),
            }
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        except RunStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ServiceRequestError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post(
        "/v1/runs/{run_id}/approvals",
        dependencies=[Depends(require_token)],
    )
    def approve_run(run_id: str, request: ApprovalRequest) -> dict[str, Any]:
        try:
            record = orchestrator.approve_run(
                run_id=run_id,
                approval_kind=request.kind,
                decision=request.decision,
                actor=request.actor,
                details=request.details,
            )
            return {"run": record.to_dict()}
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        except (RunStateError, ServiceRequestError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/v1/routes/browser-runtime",
        dependencies=[Depends(require_token)],
    )
    def route_browser_runtime(
        request: BrowserRuntimeRouteRequest,
    ) -> dict[str, Any]:
        decision = runtime_router.decide(
            RoutingContext(
                mode=request.mode,
                requested_capabilities=tuple(request.requested_capabilities),
                selectors_present=request.selectors_present,
                output_formats=tuple(request.output_formats),
                agentic_navigation=request.agentic_navigation,
                require_request_level_get_head_only=(
                    request.require_request_level_get_head_only
                ),
            )
        )
        return {
            "status": "blocked" if decision.route == "blocked" else "routed",
            "executable": False,
            "decision": decision.to_dict(),
            "notice": (
                "Routing is deterministic and non-executing. The decision cannot "
                "grant blueprint approval or action approval and does not start a browser."
            ),
        }

    @app.post(
        "/v1/plans/browser-workflow",
        dependencies=[Depends(require_token)],
    )
    def plan_browser_workflow(
        request: BrowserWorkflowPlanRequest,
    ) -> dict[str, Any]:
        try:
            proposal = workflow_planner.plan(
                objective=request.objective,
                approved_domains=request.approved_domains,
                start_urls=request.start_urls,
                requested_capabilities=request.requested_capabilities,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "status": proposal["status"],
            "executable": False,
            "planner": "langgraph-deterministic-v0.5",
            "proposal": proposal,
            "notice": (
                "This plan cannot authorize execution. Create or update a "
                "validated task specification and complete the existing approval "
                "flow before any runtime action."
            ),
        }

    @app.post(
        "/v1/plans/browser-workflow/ai-preview",
        dependencies=[Depends(require_token)],
    )
    async def preview_ai_browser_workflow(
        request: PlanRequest,
    ) -> dict[str, Any]:
        try:
            proposal = await orchestrator.propose_ai_workflow(
                objective=request.objective,
                approved_domains=request.approved_domains,
                start_urls=request.start_urls,
            )
        except (ServiceRequestError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        policy_plan = proposal["policy_plan"]
        return {
            "status": policy_plan["status"],
            "executable": False,
            "planner": "openrouter-intent+langgraph-policy-v0.5.1",
            "proposal": proposal,
            "notice": (
                "AI output is an untrusted intent draft. Operator-controlled "
                "domains and URLs remain fixed, and deterministic policy decides "
                "risk. This endpoint never authorizes execution."
            ),
        }

    @app.post(
        "/v1/plans/extraction-preview",
        dependencies=[Depends(require_token)],
    )
    async def preview_plan(request: PlanRequest) -> dict[str, Any]:
        try:
            proposal = await orchestrator.propose_extraction(
                objective=request.objective,
                approved_domains=request.approved_domains,
                start_urls=request.start_urls,
            )
        except (ServiceRequestError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "status": "draft",
            "executable": False,
            "proposal": proposal,
            "notice": (
                "This OpenRouter output is an untrusted draft. Copy it into a "
                "task specification, validate it, and approve the blueprint "
                "before creating a run."
            ),
        }

    return app


def main() -> None:
    import uvicorn

    uvicorn.run(
        "universal_browser_agent.service.api:create_app",
        factory=True,
        host="0.0.0.0",
        port=8000,
        proxy_headers=True,
    )


if __name__ == "__main__":
    main()
