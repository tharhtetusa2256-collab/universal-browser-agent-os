"""FastAPI control plane for approval-gated browser-agent runs."""

from __future__ import annotations

import hmac
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

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


class PlanRequest(BaseModel):
    objective: str = Field(min_length=12, max_length=1_000)
    approved_domains: list[str] = Field(min_length=1, max_length=50)
    start_urls: list[str] = Field(min_length=1, max_length=50)


def create_app(settings: Optional[ServiceSettings] = None) -> FastAPI:
    resolved = settings or ServiceSettings.from_env()
    resolved.require_api_token()
    store = RunStore(resolved.database_path)
    orchestrator = RunOrchestrator(resolved, store)
    app = FastAPI(
        title="Universal Browser Agent OS",
        version="0.4.0",
        description=(
            "Approval-gated API for validated public-page browser tasks. "
            "State-changing browser actions remain unsupported."
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
        return {"status": "ok", "version": "0.4.0"}

    @app.get("/v1/clients", dependencies=[Depends(require_token)])
    def list_clients() -> dict[str, Any]:
        try:
            clients = [
                workspace.to_dict()
                for workspace in orchestrator.list_workspaces()
            ]
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
