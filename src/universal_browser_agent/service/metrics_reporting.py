"""Read and aggregate normalized runtime metrics from durable run results."""

from __future__ import annotations

from collections import Counter
from statistics import mean
from typing import Any

from .store import RunNotFoundError, RunRecord, RunStore


def _snapshot(record: RunRecord) -> dict[str, Any] | None:
    result = record.result or {}
    metrics = result.get("runtime_metrics")
    if not isinstance(metrics, dict):
        return None
    return {
        "run_id": record.run_id,
        "client_id": record.client_id,
        "task_path": record.task_path,
        "run_status": record.status,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        **metrics,
    }


def _percentile_95(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, (95 * len(ordered) + 99) // 100 - 1))
    return ordered[index]


def _aggregate(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    durations = [
        int(value["duration_ms"])
        for value in snapshots
        if isinstance(value.get("duration_ms"), int)
    ]
    costs = [
        float(value["estimated_cost_usd"])
        for value in snapshots
        if isinstance(value.get("estimated_cost_usd"), (int, float))
        and not isinstance(value.get("estimated_cost_usd"), bool)
    ]
    token_values = [
        int(value["total_tokens"])
        for value in snapshots
        if isinstance(value.get("total_tokens"), int)
        and not isinstance(value.get("total_tokens"), bool)
    ]
    succeeded = sum(value.get("succeeded") is True for value in snapshots)
    interventions = sum(
        value.get("human_intervention_required") is True for value in snapshots
    )
    error_categories = Counter(
        str(value["error_category"])
        for value in snapshots
        if value.get("error_category")
    )
    total = len(snapshots)
    return {
        "run_count": total,
        "success_count": succeeded,
        "success_rate": round(succeeded / total, 4) if total else None,
        "average_duration_ms": round(mean(durations)) if durations else None,
        "p95_duration_ms": _percentile_95(durations),
        "human_intervention_count": interventions,
        "human_intervention_rate": round(interventions / total, 4) if total else None,
        "total_worker_attempts": sum(
            int(value.get("worker_attempt_count", 0) or 0) for value in snapshots
        ),
        "total_stale_requeues": sum(
            int(value.get("stale_requeue_count", 0) or 0) for value in snapshots
        ),
        "total_items": sum(int(value.get("item_count", 0) or 0) for value in snapshots),
        "total_failures": sum(
            int(value.get("failure_count", 0) or 0) for value in snapshots
        ),
        "total_blocked_requests": sum(
            int(value.get("blocked_request_count", 0) or 0) for value in snapshots
        ),
        "total_tokens": sum(token_values) if token_values else 0,
        "token_reporting_runs": len(token_values),
        "total_estimated_cost_usd": round(sum(costs), 8) if costs else 0.0,
        "average_estimated_cost_usd": round(mean(costs), 8) if costs else None,
        "cost_reporting_runs": len(costs),
        "unknown_cost_runs": total - len(costs),
        "error_categories": dict(sorted(error_categories.items())),
    }


class RuntimeMetricsReader:
    """Pilot-scale metrics reader over the latest durable run records."""

    def __init__(self, store: RunStore) -> None:
        self.store = store

    def for_run(self, run_id: str) -> dict[str, Any]:
        record = self.store.get_run(run_id)
        snapshot = _snapshot(record)
        if snapshot is None:
            raise RunNotFoundError(f"Runtime metrics not available for {run_id}")
        return snapshot

    def list(
        self,
        *,
        client_id: str | None = None,
        route: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if route is not None and route not in {"playwright", "browser-use"}:
            raise ValueError("route must be playwright or browser-use")
        records = self.store.list_runs(client_id=client_id, limit=limit)
        snapshots = [snapshot for record in records if (snapshot := _snapshot(record))]
        if route is not None:
            snapshots = [
                snapshot
                for snapshot in snapshots
                if snapshot.get("runtime_route") == route
            ]
        return snapshots

    def summary(
        self,
        *,
        client_id: str | None = None,
        route: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        snapshots = self.list(client_id=client_id, route=route, limit=limit)
        by_route: dict[str, Any] = {}
        for runtime_route in ("playwright", "browser-use"):
            selected = [
                snapshot
                for snapshot in snapshots
                if snapshot.get("runtime_route") == runtime_route
            ]
            by_route[runtime_route] = _aggregate(selected)
        return {
            "scope": {
                "client_id": client_id,
                "route": route,
                "limit": limit,
            },
            "overall": _aggregate(snapshots),
            "by_route": by_route,
        }
