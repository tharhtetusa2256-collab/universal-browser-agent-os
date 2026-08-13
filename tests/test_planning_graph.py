from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from universal_browser_agent.agent import BrowserWorkflowPlanner
from universal_browser_agent.service.api import create_app
from universal_browser_agent.service.config import ServiceSettings


REPO_ROOT = Path(__file__).resolve().parents[1]


class BrowserWorkflowPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.planner = BrowserWorkflowPlanner()

    def test_read_only_plan_reaches_blueprint_review_without_execution_authority(self) -> None:
        plan = self.planner.plan(
            objective="Research the approved public website and extract its title",
            approved_domains=["example.com"],
            start_urls=["https://example.com/"],
            requested_capabilities=["navigate", "extract", "screenshot"],
        )

        self.assertEqual(plan["risk_level"], "low")
        self.assertFalse(plan["requires_human_approval"])
        self.assertFalse(plan["execution_authorized"])
        self.assertEqual(plan["status"], "ready-for-blueprint-review")
        self.assertIn(
            "readonly-runtime",
            {step["id"] for step in plan["steps"]},
        )

    def test_consequential_capability_is_fail_closed(self) -> None:
        plan = self.planner.plan(
            objective="Prepare a workflow that could submit an approved web form",
            approved_domains=["example.com"],
            start_urls=["https://example.com/"],
            requested_capabilities=["navigate", "fill", "submit"],
        )

        self.assertEqual(plan["risk_level"], "high")
        self.assertTrue(plan["requires_human_approval"])
        self.assertFalse(plan["execution_authorized"])
        self.assertEqual(plan["status"], "approval-required")
        self.assertIn(
            "action-approval",
            {step["id"] for step in plan["steps"]},
        )

    def test_start_url_outside_allowlist_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside approved_domains"):
            self.planner.plan(
                objective="Research only the explicitly approved public website",
                approved_domains=["example.com"],
                start_urls=["https://www.example.com/"],
            )

    def test_unknown_capability_requires_review(self) -> None:
        plan = self.planner.plan(
            objective="Review an unknown future capability without executing it",
            approved_domains=["example.com"],
            start_urls=["https://example.com/"],
            requested_capabilities=["navigate", "future-capability"],
        )

        self.assertEqual(plan["risk_level"], "medium")
        self.assertTrue(plan["requires_human_approval"])
        self.assertFalse(plan["execution_authorized"])


class BrowserWorkflowPlanningAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.token = "test-token-with-more-than-24-characters"
        settings = ServiceSettings(
            repo_root=REPO_ROOT,
            database_path=(
                Path(self.temporary_directory.name) / "planning.sqlite3"
            ),
            api_token=self.token,
        )
        self.client = TestClient(create_app(settings))
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self) -> None:
        self.client.close()
        self.temporary_directory.cleanup()

    def test_planning_endpoint_is_authenticated_and_non_executable(self) -> None:
        payload = {
            "objective": "Research the approved public website and extract its title",
            "approved_domains": ["example.com"],
            "start_urls": ["https://example.com/"],
            "requested_capabilities": ["navigate", "extract"],
        }

        unauthorized = self.client.post(
            "/v1/plans/browser-workflow",
            json=payload,
        )
        self.assertEqual(unauthorized.status_code, 401)

        response = self.client.post(
            "/v1/plans/browser-workflow",
            headers=self.headers,
            json=payload,
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["planner"], "langgraph-deterministic-v0.5")
        self.assertFalse(body["executable"])
        self.assertFalse(body["proposal"]["execution_authorized"])

    def test_planning_endpoint_rejects_unapproved_start_host(self) -> None:
        response = self.client.post(
            "/v1/plans/browser-workflow",
            headers=self.headers,
            json={
                "objective": "Research only the explicitly approved public website",
                "approved_domains": ["example.com"],
                "start_urls": ["https://other.example/"],
                "requested_capabilities": ["navigate", "extract"],
            },
        )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
