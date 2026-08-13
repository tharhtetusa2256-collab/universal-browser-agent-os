from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from universal_browser_agent.service.api import create_app
from universal_browser_agent.service.config import ServiceSettings
from universal_browser_agent.service.metrics import build_runtime_metrics
from universal_browser_agent.service.metrics_reporting import RuntimeMetricsReader
from universal_browser_agent.service.observed_orchestrator import ObservedRunOrchestrator
from universal_browser_agent.service.store import RunStore


REPO_ROOT = Path(__file__).resolve().parents[1]


def routing(route: str = "playwright") -> dict:
    return {
        "router": "test-router",
        "route": route,
        "reasons": ["test"],
        "blockers": [],
        "normalized_capabilities": ["navigate", "extract"],
        "normalized_output_formats": ["json", "markdown", "screenshots"],
        "browser_use_eligible": route == "browser-use",
        "execution_authorized": False,
    }


class RuntimeMetricsNormalizationTests(unittest.TestCase):
    def test_playwright_is_zero_model_cost_and_counts_evidence(self) -> None:
        metrics = build_runtime_metrics(
            route="playwright",
            result={
                "status": "completed-with-errors",
                "items": [{"name": "one"}, {"name": "two"}],
                "failures": [{"error": "HTTP 404"}],
                "blocked_requests": [{"url": "https://blocked.invalid"}],
            },
            duration_ms=1234,
            succeeded=True,
        )
        self.assertEqual(metrics.item_count, 2)
        self.assertEqual(metrics.failure_count, 1)
        self.assertEqual(metrics.blocked_request_count, 1)
        self.assertEqual(metrics.total_tokens, 0)
        self.assertEqual(metrics.estimated_cost_usd, 0.0)
        self.assertEqual(metrics.error_category, "partial-errors")

    def test_browser_use_reads_provider_reported_usage(self) -> None:
        metrics = build_runtime_metrics(
            route="browser-use",
            result={
                "status": "completed",
                "model": "test/model",
                "extracted_content": ["one"],
                "errors": [],
                "step_count": 4,
                "usage": {
                    "total_prompt_tokens": 120,
                    "total_completion_tokens": 30,
                    "total_tokens": 150,
                    "total_cost": 0.0125,
                },
            },
            duration_ms=2500,
            succeeded=True,
        )
        self.assertEqual(metrics.step_count, 4)
        self.assertEqual(metrics.prompt_tokens, 120)
        self.assertEqual(metrics.completion_tokens, 30)
        self.assertEqual(metrics.total_tokens, 150)
        self.assertEqual(metrics.estimated_cost_usd, 0.0125)

    def test_intervention_is_categorized_without_raw_reasoning(self) -> None:
        metrics = build_runtime_metrics(
            route="browser-use",
            result={"status": "failed", "errors": []},
            duration_ms=100,
            succeeded=False,
            error="Browser run stopped because CAPTCHA requires human takeover",
        )
        self.assertTrue(metrics.human_intervention_required)
        self.assertEqual(metrics.intervention_reason, "captcha")
        self.assertEqual(metrics.error_category, "human-intervention-captcha")

    def test_unknown_route_failure_still_produces_metrics(self) -> None:
        metrics = build_runtime_metrics(
            route="future-unknown-runtime",
            result={"status": "failed"},
            duration_ms=10,
            succeeded=False,
            error="Locked runtime route is not executable",
        )
        self.assertEqual(metrics.runtime_route, "future-unknown-runtime")
        self.assertIsNone(metrics.estimated_cost_usd)
        self.assertEqual(metrics.error_category, "runtime")


class RuntimeMetricsReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = RunStore(Path(self.tempdir.name) / "metrics.sqlite3")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _completed_run(self, key: str, route: str, metrics: dict) -> str:
        run, _ = self.store.create_run(
            idempotency_key=key,
            source="api",
            business_path="configs/example-business/business-profile.json",
            task_path="templates/competitor-research/task.json",
            routing=routing(route),
        )
        self.store.record_approval(
            run_id=run.run_id,
            approval_kind="blueprint",
            decision="approved",
            actor="owner",
            details={"objective_reviewed": True, "domains_reviewed": True},
        )
        claimed = self.store.claim_next_run()
        self.assertIsNotNone(claimed)
        self.store.complete_run(
            claimed.run_id,
            result={"status": "completed", "runtime_metrics": metrics},
            succeeded=True,
        )
        return run.run_id

    def test_summary_compares_routes_and_cost_coverage(self) -> None:
        self._completed_run(
            "metrics-playwright:0001",
            "playwright",
            {
                "runtime_route": "playwright",
                "succeeded": True,
                "duration_ms": 1000,
                "human_intervention_required": False,
                "worker_attempt_count": 1,
                "stale_requeue_count": 0,
                "item_count": 2,
                "failure_count": 0,
                "blocked_request_count": 0,
                "total_tokens": 0,
                "estimated_cost_usd": 0.0,
                "error_category": None,
            },
        )
        browser_run = self._completed_run(
            "metrics-browser-use:0002",
            "browser-use",
            {
                "runtime_route": "browser-use",
                "succeeded": True,
                "duration_ms": 2000,
                "human_intervention_required": False,
                "worker_attempt_count": 1,
                "stale_requeue_count": 0,
                "item_count": 1,
                "failure_count": 0,
                "blocked_request_count": 0,
                "total_tokens": 300,
                "estimated_cost_usd": 0.02,
                "error_category": None,
            },
        )

        reader = RuntimeMetricsReader(self.store)
        summary = reader.summary()
        self.assertEqual(summary["overall"]["run_count"], 2)
        self.assertEqual(summary["overall"]["success_rate"], 1.0)
        self.assertEqual(summary["overall"]["total_tokens"], 300)
        self.assertEqual(summary["by_route"]["playwright"]["run_count"], 1)
        self.assertEqual(summary["by_route"]["browser-use"]["run_count"], 1)
        self.assertEqual(reader.for_run(browser_run)["runtime_route"], "browser-use")


class ObservedWorkerMetricsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.settings = ServiceSettings(
            repo_root=REPO_ROOT,
            database_path=Path(self.tempdir.name) / "worker.sqlite3",
            api_token="runtime-metrics-test-token-123456",
        )
        self.store = RunStore(self.settings.database_path)
        self.orchestrator = ObservedRunOrchestrator(self.settings, self.store)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_playwright_worker_persists_metrics_and_audit_event(self) -> None:
        record, _ = self.orchestrator.create_run(
            idempotency_key="observed-worker:0001",
            source="api",
            business_path="configs/example-business/business-profile.json",
            task_path="templates/competitor-research/task.json",
        )
        self.orchestrator.approve_run(
            run_id=record.run_id,
            approval_kind="blueprint",
            decision="approved",
            actor="owner",
            details={"objective_reviewed": True, "domains_reviewed": True},
        )

        class FakeReport:
            status = "completed"

            @staticmethod
            def to_dict() -> dict:
                return {
                    "run_id": "runtime_metrics_fake",
                    "status": "completed",
                    "items": [{"name": "example"}],
                    "failures": [],
                    "blocked_requests": [],
                    "artifacts": {},
                }

        class FakeRuntime:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            async def run(self) -> FakeReport:
                return FakeReport()

        with patch(
            "universal_browser_agent.service.observed_orchestrator."
            "ReadOnlyPlaywrightRuntime",
            FakeRuntime,
        ):
            completed = asyncio.run(self.orchestrator.execute_next())

        self.assertIsNotNone(completed)
        metrics = completed.result["runtime_metrics"]
        self.assertEqual(metrics["runtime_route"], "playwright")
        self.assertTrue(metrics["succeeded"])
        self.assertEqual(metrics["worker_attempt_count"], 1)
        self.assertEqual(metrics["total_tokens"], 0)
        self.assertEqual(metrics["estimated_cost_usd"], 0.0)
        event_types = {
            event["event_type"] for event in self.store.list_events(record.run_id)
        }
        self.assertIn("metrics.recorded", event_types)


class RuntimeMetricsAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.token = "runtime-metrics-api-token-123456"
        self.settings = ServiceSettings(
            repo_root=REPO_ROOT,
            database_path=Path(self.tempdir.name) / "api.sqlite3",
            api_token=self.token,
        )
        store = RunStore(self.settings.database_path)
        run, _ = store.create_run(
            idempotency_key="metrics-api-run:0001",
            source="api",
            business_path="configs/example-business/business-profile.json",
            task_path="templates/competitor-research/task.json",
            routing=routing("playwright"),
        )
        store.record_approval(
            run_id=run.run_id,
            approval_kind="blueprint",
            decision="approved",
            actor="owner",
            details={"objective_reviewed": True, "domains_reviewed": True},
        )
        claimed = store.claim_next_run()
        store.complete_run(
            claimed.run_id,
            result={
                "status": "completed",
                "runtime_metrics": {
                    "runtime_route": "playwright",
                    "succeeded": True,
                    "duration_ms": 50,
                    "human_intervention_required": False,
                    "worker_attempt_count": 1,
                    "stale_requeue_count": 0,
                    "item_count": 1,
                    "failure_count": 0,
                    "blocked_request_count": 0,
                    "total_tokens": 0,
                    "estimated_cost_usd": 0.0,
                    "error_category": None,
                },
            },
            succeeded=True,
        )
        self.run_id = run.run_id
        self.client = TestClient(create_app(self.settings))
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self) -> None:
        self.client.close()
        self.tempdir.cleanup()

    def test_metrics_endpoints_require_authentication(self) -> None:
        self.assertEqual(self.client.get("/v1/metrics/runtime").status_code, 401)

    def test_run_metrics_and_summary_are_available(self) -> None:
        per_run = self.client.get(
            f"/v1/runs/{self.run_id}/metrics",
            headers=self.headers,
        )
        self.assertEqual(per_run.status_code, 200, per_run.text)
        self.assertEqual(per_run.json()["metrics"]["runtime_route"], "playwright")

        summary = self.client.get("/v1/metrics/runtime", headers=self.headers)
        self.assertEqual(summary.status_code, 200, summary.text)
        self.assertEqual(summary.json()["overall"]["run_count"], 1)
        self.assertEqual(summary.json()["overall"]["success_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
