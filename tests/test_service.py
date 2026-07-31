from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from universal_browser_agent.adapters.notion import NotionRunPublisher
from universal_browser_agent.adapters.openrouter import (
    OpenRouterPlanner,
    OpenRouterResponseError,
)
from universal_browser_agent.adapters.webhook import SignedWebhookPublisher
from universal_browser_agent.service.config import ServiceSettings
from universal_browser_agent.service.api import create_app
from universal_browser_agent.service.orchestrator import (
    RunOrchestrator,
    ServiceRequestError,
)
from universal_browser_agent.service.store import RunStateError, RunStore
from universal_browser_agent.workspaces import (
    WorkspaceRegistry,
    WorkspaceValidationError,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


class RunStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = RunStore(
            Path(self.temporary_directory.name) / "service.sqlite3"
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_idempotent_creation_and_blueprint_approval(self) -> None:
        first, created = self.store.create_run(
            idempotency_key="notion-task:12345",
            source="notion",
            business_path="configs/example-business/business-profile.json",
            task_path="templates/competitor-research/task.json",
        )
        duplicate, duplicate_created = self.store.create_run(
            idempotency_key="notion-task:12345",
            source="notion",
            business_path="configs/example-business/business-profile.json",
            task_path="templates/competitor-research/task.json",
        )

        self.assertTrue(created)
        self.assertFalse(duplicate_created)
        self.assertEqual(first.run_id, duplicate.run_id)
        self.assertEqual(first.status, "awaiting-blueprint-approval")

        with self.assertRaisesRegex(RunStateError, "different request"):
            self.store.create_run(
                idempotency_key="notion-task:12345",
                source="make",
                business_path="configs/example-business/business-profile.json",
                task_path="templates/competitor-research/task.json",
            )

        approved = self.store.record_approval(
            run_id=first.run_id,
            approval_kind="blueprint",
            decision="approved",
            actor="owner@example.invalid",
            details={
                "objective_reviewed": True,
                "domains_reviewed": True,
            },
        )
        self.assertEqual(approved.status, "queued")
        claimed = self.store.claim_next_run()
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.status, "running")

    def test_action_approval_is_fail_closed(self) -> None:
        run, _ = self.store.create_run(
            idempotency_key="api-task:123456",
            source="api",
            business_path="configs/example-business/business-profile.json",
            task_path="templates/competitor-research/task.json",
        )
        with self.assertRaisesRegex(RunStateError, "future"):
            self.store.record_approval(
                run_id=run.run_id,
                approval_kind="action",
                decision="approved",
                actor="owner",
                details={"action": "publish"},
            )

    def test_stale_running_job_is_requeued_with_an_audit_event(self) -> None:
        run, _ = self.store.create_run(
            idempotency_key="api-stale:123456",
            source="api",
            business_path="configs/example-business/business-profile.json",
            task_path="templates/competitor-research/task.json",
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
        claimed = self.store.claim_next_run()
        self.assertEqual(claimed.status, "running")
        stale_time = (
            datetime.now(timezone.utc) - timedelta(hours=9)
        ).isoformat()
        with self.store._connection() as connection:
            connection.execute(
                "UPDATE runs SET updated_at = ? WHERE run_id = ?",
                (stale_time, run.run_id),
            )

        count = self.store.requeue_stale_runs(older_than_minutes=480)

        self.assertEqual(count, 1)
        self.assertEqual(self.store.get_run(run.run_id).status, "queued")
        self.assertIn(
            "run.requeued-after-stale-lease",
            {
                event["event_type"]
                for event in self.store.list_events(run.run_id)
            },
        )

    def test_existing_database_is_migrated_for_client_identity(self) -> None:
        database_path = Path(self.temporary_directory.name) / "legacy.sqlite3"
        with sqlite3.connect(database_path) as connection:
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
        migrated = RunStore(database_path)
        with migrated._connection() as connection:
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(runs)"
                ).fetchall()
            }
        self.assertIn("client_id", columns)
        self.assertIn("workspace_path", columns)


class WorkspaceRegistryTests(unittest.TestCase):
    def test_example_workspace_is_valid_and_client_scoped(self) -> None:
        workspace = WorkspaceRegistry(REPO_ROOT).load("example-client")
        self.assertEqual(workspace.owner_id, "owner")
        self.assertEqual(
            workspace.artifact_root,
            "artifacts/clients/example-client",
        )
        self.assertEqual(
            workspace.get_task("example-client-public-research").path,
            "clients/example-client/tasks/public-research.json",
        )

    def test_workspace_rejects_output_crossing_client_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(REPO_ROOT / "schemas", root / "schemas")
            shutil.copytree(
                REPO_ROOT / "clients",
                root / "clients",
            )
            task_path = (
                root
                / "clients/example-client/tasks/public-research.json"
            )
            task = json.loads(task_path.read_text(encoding="utf-8"))
            task["outputs"]["destination"] = (
                "artifacts/clients/another-client/stolen/"
            )
            task_path.write_text(json.dumps(task), encoding="utf-8")

            with self.assertRaisesRegex(
                WorkspaceValidationError,
                "output must remain under",
            ):
                WorkspaceRegistry(root).load("example-client")

    def test_workspace_rejects_parent_directory_output_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(REPO_ROOT / "schemas", root / "schemas")
            shutil.copytree(REPO_ROOT / "clients", root / "clients")
            task_path = (
                root
                / "clients/example-client/tasks/public-research.json"
            )
            task = json.loads(task_path.read_text(encoding="utf-8"))
            task["outputs"]["destination"] = (
                "artifacts/clients/example-client/../another-client/"
            )
            task_path.write_text(json.dumps(task), encoding="utf-8")

            with self.assertRaisesRegex(
                WorkspaceValidationError,
                "repository-relative path",
            ):
                WorkspaceRegistry(root).load("example-client")


class RunOrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.settings = ServiceSettings(
            repo_root=REPO_ROOT,
            database_path=(
                Path(self.temporary_directory.name) / "service.sqlite3"
            ),
            api_token="a" * 32,
        )
        self.store = RunStore(self.settings.database_path)
        self.orchestrator = RunOrchestrator(self.settings, self.store)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_validated_run_stops_for_blueprint_approval(self) -> None:
        record, created = self.orchestrator.create_run(
            idempotency_key="api-example:12345",
            source="api",
            business_path="configs/example-business/business-profile.json",
            task_path="templates/competitor-research/task.json",
        )
        self.assertTrue(created)
        self.assertEqual(record.status, "awaiting-blueprint-approval")

    def test_configuration_path_escape_is_rejected(self) -> None:
        with self.assertRaisesRegex(ServiceRequestError, "repository"):
            self.orchestrator.create_run(
                idempotency_key="api-example:escape",
                source="api",
                business_path="../../outside.json",
                task_path="templates/competitor-research/task.json",
            )

    def test_client_run_uses_manifest_paths_and_owner_approval(self) -> None:
        record, created = self.orchestrator.create_client_run(
            client_id="example-client",
            task_id="example-client-public-research",
            idempotency_key="client-example:12345",
            source="api",
        )
        self.assertTrue(created)
        self.assertEqual(record.client_id, "example-client")
        self.assertEqual(
            record.workspace_path,
            "clients/example-client/workspace.json",
        )
        with self.assertRaisesRegex(ServiceRequestError, "workspace owner"):
            self.orchestrator.approve_run(
                run_id=record.run_id,
                approval_kind="blueprint",
                decision="approved",
                actor="another-user",
                details={
                    "objective_reviewed": True,
                    "domains_reviewed": True,
                },
            )
        approved = self.orchestrator.approve_run(
            run_id=record.run_id,
            approval_kind="blueprint",
            decision="approved",
            actor="owner",
            details={
                "objective_reviewed": True,
                "domains_reviewed": True,
            },
        )
        self.assertEqual(approved.status, "queued")

    def test_client_integration_allowlist_blocks_global_notion_output(self) -> None:
        settings = ServiceSettings(
            repo_root=REPO_ROOT,
            database_path=(
                Path(self.temporary_directory.name) / "outputs.sqlite3"
            ),
            api_token="a" * 32,
            notion_api_key="configured-key",
            notion_database_id="configured-database",
        )
        store = RunStore(settings.database_path)
        orchestrator = RunOrchestrator(settings, store)
        record, _ = orchestrator.create_client_run(
            client_id="example-client",
            task_id="example-client-public-research",
            idempotency_key="client-output:12345",
            source="api",
        )

        with patch(
            "universal_browser_agent.service.orchestrator.NotionRunPublisher"
        ) as publisher:
            asyncio.run(orchestrator._publish_outputs(record))

        publisher.assert_not_called()

    def test_worker_records_runtime_result(self) -> None:
        record, _ = self.orchestrator.create_run(
            idempotency_key="api-worker:12345",
            source="api",
            business_path="configs/example-business/business-profile.json",
            task_path="templates/competitor-research/task.json",
        )
        self.orchestrator.approve_run(
            run_id=record.run_id,
            approval_kind="blueprint",
            decision="approved",
            actor="owner",
            details={
                "objective_reviewed": True,
                "domains_reviewed": True,
            },
        )

        class FakeReport:
            status = "completed"

            @staticmethod
            def to_dict() -> dict:
                return {
                    "run_id": "runtime_test",
                    "status": "completed",
                    "items": [],
                    "failures": [],
                    "artifacts": {},
                }

        class FakeRuntime:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            async def run(self) -> FakeReport:
                return FakeReport()

        with patch(
            "universal_browser_agent.service.orchestrator."
            "ReadOnlyPlaywrightRuntime",
            FakeRuntime,
        ):
            completed = asyncio.run(self.orchestrator.execute_next())

        self.assertIsNotNone(completed)
        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.result["run_id"], "runtime_test")


class ServiceAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.token = "test-token-with-more-than-24-characters"
        settings = ServiceSettings(
            repo_root=REPO_ROOT,
            database_path=(
                Path(self.temporary_directory.name) / "service.sqlite3"
            ),
            api_token=self.token,
        )
        self.client = TestClient(create_app(settings))
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self) -> None:
        self.client.close()
        self.temporary_directory.cleanup()

    def test_health_is_public_but_run_data_requires_authentication(self) -> None:
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(
            self.client.get("/v1/runs/run_missing").status_code,
            401,
        )

    def test_create_approve_and_read_a_run(self) -> None:
        response = self.client.post(
            "/v1/runs",
            headers={
                **self.headers,
                "Idempotency-Key": "api-test:123456",
            },
            json={
                "business_profile": (
                    "configs/example-business/business-profile.json"
                ),
                "task_spec": "templates/competitor-research/task.json",
                "source": "api",
            },
        )
        self.assertEqual(response.status_code, 202, response.text)
        body = response.json()
        self.assertTrue(body["created"])
        run_id = body["run"]["run_id"]
        self.assertEqual(
            body["run"]["status"],
            "awaiting-blueprint-approval",
        )

        duplicate = self.client.post(
            "/v1/runs",
            headers={
                **self.headers,
                "Idempotency-Key": "api-test:123456",
            },
            json={
                "business_profile": (
                    "configs/example-business/business-profile.json"
                ),
                "task_spec": "templates/competitor-research/task.json",
                "source": "api",
            },
        )
        self.assertFalse(duplicate.json()["created"])
        self.assertEqual(duplicate.json()["run"]["run_id"], run_id)

        approval = self.client.post(
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
        self.assertEqual(approval.status_code, 200, approval.text)
        self.assertEqual(approval.json()["run"]["status"], "queued")

        fetched = self.client.get(
            f"/v1/runs/{run_id}",
            headers=self.headers,
        )
        self.assertEqual(fetched.status_code, 200)
        event_types = {
            event["event_type"] for event in fetched.json()["events"]
        }
        self.assertIn("run.created", event_types)
        self.assertIn("approval.approved", event_types)

    def test_list_client_create_run_and_filter_history(self) -> None:
        clients = self.client.get("/v1/clients", headers=self.headers)
        self.assertEqual(clients.status_code, 200, clients.text)
        self.assertEqual(
            clients.json()["clients"][0]["client_id"],
            "example-client",
        )

        created = self.client.post(
            "/v1/clients/example-client/runs",
            headers={
                **self.headers,
                "Idempotency-Key": "client-api:123456",
            },
            json={
                "task_id": "example-client-public-research",
                "source": "api",
            },
        )
        self.assertEqual(created.status_code, 202, created.text)
        self.assertEqual(
            created.json()["run"]["client_id"],
            "example-client",
        )

        history = self.client.get(
            "/v1/clients/example-client/runs",
            headers=self.headers,
        )
        self.assertEqual(history.status_code, 200, history.text)
        self.assertEqual(len(history.json()["runs"]), 1)


class AdapterTests(unittest.TestCase):
    @staticmethod
    def _completed_run() -> dict:
        return {
            "run_id": "run_123",
            "status": "completed",
            "source": "api",
            "task_path": "templates/example.json",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:01:00+00:00",
            "result": {
                "run_id": "runtime_123",
                "status": "completed",
                "items": [{"private-looking-field": "must-not-be-forwarded"}],
                "failures": [],
                "artifacts": {"json": "/app/artifacts/report.json"},
            },
            "error": None,
        }

    def test_openrouter_output_is_strictly_validated(self) -> None:
        def transport(
            url: str,
            payload: dict,
            *,
            headers: dict[str, str],
        ) -> dict:
            self.assertTrue(url.startswith("https://"))
            self.assertIn("Authorization", headers)
            self.assertEqual(
                payload["response_format"]["type"],
                "json_schema",
            )
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "selectors": {"price": ".price"},
                                    "required_fields": ["price"],
                                    "notes": "Public data only.",
                                }
                            )
                        }
                    }
                ]
            }

        planner = OpenRouterPlanner(
            "test-key",
            "test-model",
            transport=transport,
        )
        proposal = planner.propose_extraction(
            objective="Collect public product pricing",
            approved_domains=["example.com"],
            start_urls=["https://example.com/"],
        )
        self.assertEqual(proposal["selectors"], {"price": ".price"})

        with self.assertRaises(OpenRouterResponseError):
            planner._validate_proposal(
                {
                    "selectors": {},
                    "required_fields": [],
                    "notes": "",
                    "start_urls": ["https://unapproved.invalid"],
                }
            )

    def test_webhook_payload_is_signed(self) -> None:
        captured: dict = {}

        def transport(
            url: str,
            payload: dict,
            *,
            headers: dict[str, str],
        ) -> dict:
            captured.update(
                {"url": url, "payload": payload, "headers": headers}
            )
            return {"accepted": True}

        publisher = SignedWebhookPublisher(
            "https://hook.example.invalid/uba",
            secret="shared-secret",
            transport=transport,
        )
        publisher.publish(
            "run.completed",
            self._completed_run(),
        )
        self.assertNotIn("result", captured["payload"]["run"])
        self.assertEqual(
            captured["payload"]["run"]["result_summary"]["item_count"],
            1,
        )
        self.assertNotIn(
            "private-looking-field",
            json.dumps(captured["payload"]),
        )
        canonical = json.dumps(
            captured["payload"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        expected = hmac.new(
            b"shared-secret",
            canonical,
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(
            captured["headers"]["X-UBA-Signature-256"],
            f"sha256={expected}",
        )

    def test_notion_receives_summary_not_extracted_items(self) -> None:
        captured: dict = {}

        def transport(
            url: str,
            payload: dict,
            *,
            headers: dict[str, str],
        ) -> dict:
            captured.update({"payload": payload, "headers": headers})
            return {"id": "page_123"}

        publisher = NotionRunPublisher(
            "notion-test-key",
            "database-test-id",
            transport=transport,
        )
        publisher.publish(self._completed_run())
        rendered = json.dumps(captured["payload"])
        code_content = captured["payload"]["children"][0]["code"]["rich_text"][0][
            "text"
        ]["content"]
        self.assertEqual(json.loads(code_content)["item_count"], 1)
        self.assertNotIn("private-looking-field", rendered)


if __name__ == "__main__":
    unittest.main()
