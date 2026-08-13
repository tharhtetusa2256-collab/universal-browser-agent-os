from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from universal_browser_agent.service.api import create_app
from universal_browser_agent.service.config import ServiceSettings
from universal_browser_agent.service.orchestrator import (
    RunOrchestrator,
    ServiceRequestError,
)
from universal_browser_agent.service.store import RunStateError, RunStore


REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTIC_TASK = "templates/agentic-public-research/task.json"
DETERMINISTIC_TASK = "templates/competitor-research/task.json"
BUSINESS = "configs/example-business/business-profile.json"


class PersistedRoutingStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "service.sqlite3"
        self.store = RunStore(self.database_path)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_safe_default_route_is_persisted_and_locked_with_blueprint(self) -> None:
        run, _ = self.store.create_run(
            idempotency_key="routing-store:123456",
            source="api",
            business_path=BUSINESS,
            task_path=DETERMINISTIC_TASK,
        )
        self.assertEqual(run.routing["route"], "playwright")
        self.assertFalse(run.routing["execution_authorized"])
        self.assertIsNone(run.route_locked_at)

        approved = self.store.record_approval(
            run_id=run.run_id,
            approval_kind="blueprint",
            decision="approved",
            actor="owner",
            details={
                "objective_reviewed": True,
                "domains_reviewed": True,
            },
        )
        self.assertEqual(approved.status, "queued")
        self.assertIsNotNone(approved.route_locked_at)
        self.assertEqual(approved.routing["route"], "playwright")

        events = {event["event_type"] for event in self.store.list_events(run.run_id)}
        self.assertIn("routing.selected", events)
        self.assertIn("routing.locked", events)

    def test_routing_cannot_change_after_blueprint_lock(self) -> None:
        run, _ = self.store.create_run(
            idempotency_key="routing-lock:123456",
            source="api",
            business_path=BUSINESS,
            task_path=DETERMINISTIC_TASK,
        )
        self.store.record_approval(
            run_id=run.run_id,
            approval_kind="blueprint",
            decision="approved",
            actor="owner",
            details={
                "objective_reviewed": True,
                "domains_reviewed": True,
            },
        )
        with self.assertRaisesRegex(RunStateError, "before blueprint approval"):
            self.store.set_routing_decision(
                run_id=run.run_id,
                actor="owner",
                routing={
                    "router": "test-router",
                    "route": "browser-use",
                    "reasons": ["test"],
                    "blockers": [],
                    "normalized_capabilities": ["navigate", "extract"],
                    "normalized_output_formats": ["json", "markdown"],
                    "browser_use_eligible": True,
                    "execution_authorized": False,
                },
            )

    def test_legacy_database_gets_safe_route_and_lock_for_queued_run(self) -> None:
        legacy = Path(self.temporary_directory.name) / "legacy-routing.sqlite3"
        with sqlite3.connect(legacy) as connection:
            connection.execute(
                """
                CREATE TABLE runs (
                    run_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    source TEXT NOT NULL,
                    business_path TEXT NOT NULL,
                    task_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT
                )
                """
            )
            connection.execute(
                """
                INSERT INTO runs (
                    run_id, idempotency_key, source, business_path, task_path,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "run_legacy",
                    "legacy-routing:123456",
                    "api",
                    BUSINESS,
                    DETERMINISTIC_TASK,
                    "queued",
                    "2026-08-13T00:00:00+00:00",
                    "2026-08-13T00:01:00+00:00",
                ),
            )

        migrated = RunStore(legacy)
        record = migrated.get_run("run_legacy")
        self.assertEqual(record.routing["route"], "playwright")
        self.assertIsNotNone(record.route_locked_at)
        claimed = migrated.claim_next_run()
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.status, "running")


class PersistedRoutingOrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.settings = ServiceSettings(
            repo_root=REPO_ROOT,
            database_path=Path(self.temporary_directory.name) / "service.sqlite3",
            api_token="a" * 32,
            openrouter_api_key="test-openrouter-key",
            browser_use_worker_enabled=True,
            browser_use_model="test-browser-use-model",
        )
        self.store = RunStore(self.settings.database_path)
        self.orchestrator = RunOrchestrator(self.settings, self.store)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _create_agentic_run(self, key: str):
        return self.orchestrator.create_run(
            idempotency_key=key,
            source="api",
            business_path=BUSINESS,
            task_path=AGENTIC_TASK,
        )[0]

    def test_browser_use_requires_explicit_persisted_opt_in_and_route_review(self) -> None:
        run = self._create_agentic_run("routing-agentic:123456")
        self.assertEqual(run.routing["route"], "playwright")

        routed = self.orchestrator.configure_run_routing(
            run_id=run.run_id,
            actor="owner",
            agentic_navigation=True,
            require_request_level_get_head_only=False,
        )
        self.assertEqual(routed.routing["route"], "browser-use")
        self.assertIsNone(routed.route_locked_at)

        with self.assertRaisesRegex(ServiceRequestError, "runtime_route_reviewed"):
            self.orchestrator.approve_run(
                run_id=run.run_id,
                approval_kind="blueprint",
                decision="approved",
                actor="owner",
                details={
                    "objective_reviewed": True,
                    "domains_reviewed": True,
                },
            )

        approved = self.orchestrator.approve_run(
            run_id=run.run_id,
            approval_kind="blueprint",
            decision="approved",
            actor="owner",
            details={
                "objective_reviewed": True,
                "domains_reviewed": True,
                "runtime_route_reviewed": True,
            },
        )
        self.assertEqual(approved.status, "queued")
        self.assertEqual(approved.routing["route"], "browser-use")
        self.assertIsNotNone(approved.route_locked_at)

    def test_csv_task_stays_on_playwright_even_with_agentic_opt_in(self) -> None:
        run, _ = self.orchestrator.create_run(
            idempotency_key="routing-csv:123456",
            source="api",
            business_path=BUSINESS,
            task_path=DETERMINISTIC_TASK,
        )
        routed = self.orchestrator.configure_run_routing(
            run_id=run.run_id,
            actor="owner",
            agentic_navigation=True,
            require_request_level_get_head_only=False,
        )
        self.assertEqual(routed.routing["route"], "playwright")
        self.assertIn(
            "browser-use-output-gap:csv",
            routed.routing["reasons"],
        )

    def test_browser_use_route_cannot_be_selected_when_worker_is_disabled(self) -> None:
        disabled_settings = ServiceSettings(
            repo_root=REPO_ROOT,
            database_path=Path(self.temporary_directory.name) / "disabled.sqlite3",
            api_token="a" * 32,
            openrouter_api_key="test-openrouter-key",
            browser_use_worker_enabled=False,
        )
        disabled = RunOrchestrator(
            disabled_settings,
            RunStore(disabled_settings.database_path),
        )
        run, _ = disabled.create_run(
            idempotency_key="routing-disabled:123456",
            source="api",
            business_path=BUSINESS,
            task_path=AGENTIC_TASK,
        )
        with self.assertRaisesRegex(ServiceRequestError, "disabled"):
            disabled.configure_run_routing(
                run_id=run.run_id,
                actor="owner",
                agentic_navigation=True,
                require_request_level_get_head_only=False,
            )

    def test_worker_dispatches_locked_browser_use_route_and_records_metadata(self) -> None:
        run = self._create_agentic_run("routing-worker:123456")
        self.orchestrator.configure_run_routing(
            run_id=run.run_id,
            actor="owner",
            agentic_navigation=True,
            require_request_level_get_head_only=False,
        )
        self.orchestrator.approve_run(
            run_id=run.run_id,
            approval_kind="blueprint",
            decision="approved",
            actor="owner",
            details={
                "objective_reviewed": True,
                "domains_reviewed": True,
                "runtime_route_reviewed": True,
            },
        )

        class FakeReport:
            status = "completed"

            @staticmethod
            def to_dict() -> dict:
                return {
                    "run_id": "browser_use_runtime_test",
                    "status": "completed",
                    "report_path": "artifacts/test/report.json",
                    "visited_urls": ["https://example.com/"],
                    "action_names": ["navigate", "extract", "done"],
                    "errors": [],
                }

        class FakeBrowserUseRuntime:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            async def run(self) -> FakeReport:
                return FakeReport()

        with patch(
            "universal_browser_agent.service.orchestrator.BrowserUseReadOnlyAdapter",
            FakeBrowserUseRuntime,
        ):
            completed = asyncio.run(self.orchestrator.execute_next())

        self.assertIsNotNone(completed)
        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.result["runtime_route"], "browser-use")
        self.assertEqual(
            completed.result["run_id"],
            "browser_use_runtime_test",
        )
        self.assertIsNotNone(completed.result["route_locked_at"])
        dispatch_events = [
            event
            for event in self.store.list_events(run.run_id)
            if event["event_type"] == "runtime.dispatched"
        ]
        self.assertEqual(len(dispatch_events), 1)
        self.assertEqual(dispatch_events[0]["payload"]["route"], "browser-use")


class PersistedRoutingAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.token = "routing-api-token-with-more-than-24-characters"
        settings = ServiceSettings(
            repo_root=REPO_ROOT,
            database_path=Path(self.temporary_directory.name) / "service.sqlite3",
            api_token=self.token,
            openrouter_api_key="test-openrouter-key",
            browser_use_worker_enabled=True,
        )
        self.client = TestClient(create_app(settings))
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self) -> None:
        self.client.close()
        self.temporary_directory.cleanup()

    def test_persist_route_then_approval_locks_it(self) -> None:
        created = self.client.post(
            "/v1/runs",
            headers={
                **self.headers,
                "Idempotency-Key": "routing-api:123456",
            },
            json={
                "business_profile": BUSINESS,
                "task_spec": AGENTIC_TASK,
                "source": "api",
            },
        )
        self.assertEqual(created.status_code, 202, created.text)
        run_id = created.json()["run"]["run_id"]
        self.assertEqual(created.json()["run"]["routing"]["route"], "playwright")

        routed = self.client.post(
            f"/v1/runs/{run_id}/routing",
            headers=self.headers,
            json={
                "actor": "owner",
                "agentic_navigation": True,
                "require_request_level_get_head_only": False,
            },
        )
        self.assertEqual(routed.status_code, 200, routed.text)
        self.assertEqual(routed.json()["run"]["routing"]["route"], "browser-use")
        self.assertIsNone(routed.json()["run"]["route_locked_at"])

        missing_review = self.client.post(
            f"/v1/runs/{run_id}/approvals",
            headers=self.headers,
            json={
                "kind": "blueprint",
                "decision": "approved",
                "actor": "owner",
                "details": {
                    "objective_reviewed": True,
                    "domains_reviewed": True,
                },
            },
        )
        self.assertEqual(missing_review.status_code, 409)

        approved = self.client.post(
            f"/v1/runs/{run_id}/approvals",
            headers=self.headers,
            json={
                "kind": "blueprint",
                "decision": "approved",
                "actor": "owner",
                "details": {
                    "objective_reviewed": True,
                    "domains_reviewed": True,
                    "runtime_route_reviewed": True,
                },
            },
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(approved.json()["run"]["status"], "queued")
        self.assertIsNotNone(approved.json()["run"]["route_locked_at"])

        reroute = self.client.post(
            f"/v1/runs/{run_id}/routing",
            headers=self.headers,
            json={
                "actor": "owner",
                "agentic_navigation": False,
            },
        )
        self.assertEqual(reroute.status_code, 409)


if __name__ == "__main__":
    unittest.main()
