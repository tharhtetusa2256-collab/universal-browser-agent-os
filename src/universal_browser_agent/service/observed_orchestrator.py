"""Worker execution orchestration with durable normalized runtime metrics."""

from __future__ import annotations

import time
from typing import Any

from ..adapters.browser_use_observed import ObservedBrowserUseReadOnlyAdapter
from ..playwright_runtime import ReadOnlyPlaywrightRuntime
from .metrics import build_runtime_metrics
from .orchestrator import RunOrchestrator, ServiceRequestError
from .store import RunRecord


class ObservedRunOrchestrator(RunOrchestrator):
    """Run the approved route and persist one normalized final-run metrics snapshot."""

    def _attempt_counters(self, run_id: str) -> tuple[int, int]:
        events = self.store.list_events(run_id)
        worker_attempt_count = sum(
            event["event_type"] == "run.started" for event in events
        )
        stale_requeue_count = sum(
            event["event_type"] == "run.requeued-after-stale-lease"
            for event in events
        )
        return worker_attempt_count, stale_requeue_count

    @staticmethod
    def _attach_attempt_counters(
        metrics: dict[str, Any],
        *,
        worker_attempt_count: int,
        stale_requeue_count: int,
    ) -> dict[str, Any]:
        metrics["worker_attempt_count"] = worker_attempt_count
        metrics["stale_requeue_count"] = stale_requeue_count
        return metrics

    async def execute_next(self) -> RunRecord | None:
        record = self.store.claim_next_run()
        if record is None:
            return None

        started = time.perf_counter()
        route = str((record.routing or {}).get("route") or "unknown")
        worker_attempt_count, stale_requeue_count = self._attempt_counters(record.run_id)

        try:
            if not record.routing or not record.route_locked_at:
                raise ServiceRequestError(
                    "Claimed run is missing a locked runtime routing decision"
                )
            task_data, task = self._load_record_task(record)
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
                runtime = ObservedBrowserUseReadOnlyAdapter(
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
            succeeded = report.status != "failed"
            duration_ms = max(0, round((time.perf_counter() - started) * 1000))
            metrics = build_runtime_metrics(
                route=route,
                result=result,
                duration_ms=duration_ms,
                succeeded=succeeded,
            ).to_dict()
            result["runtime_metrics"] = self._attach_attempt_counters(
                metrics,
                worker_attempt_count=worker_attempt_count,
                stale_requeue_count=stale_requeue_count,
            )
            completed = self.store.complete_run(
                record.run_id,
                result=result,
                succeeded=succeeded,
            )
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"[:2_000]
            duration_ms = max(0, round((time.perf_counter() - started) * 1000))
            failed_result: dict[str, Any] = {
                "status": "failed",
                "error": message,
                "runtime_route": route,
                "routing_router": (record.routing or {}).get("router"),
                "route_locked_at": record.route_locked_at,
            }
            metrics = build_runtime_metrics(
                route=route,
                result=failed_result,
                duration_ms=duration_ms,
                succeeded=False,
                error=message,
            ).to_dict()
            failed_result["runtime_metrics"] = self._attach_attempt_counters(
                metrics,
                worker_attempt_count=worker_attempt_count,
                stale_requeue_count=stale_requeue_count,
            )
            completed = self.store.complete_run(
                record.run_id,
                result=failed_result,
                succeeded=False,
            )

        self.store.append_event(
            record.run_id,
            "metrics.recorded",
            {
                "runtime_route": route,
                "duration_ms": completed.result.get("runtime_metrics", {}).get(
                    "duration_ms"
                )
                if completed.result
                else None,
                "succeeded": completed.status == "completed",
            },
        )
        await self._publish_outputs(completed)
        return completed
