from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from universal_browser_agent.adapters.openrouter import (
    OpenRouterResponseError,
    OpenRouterWorkflowIntentPlanner,
)
from universal_browser_agent.agent import BrowserWorkflowPlanner
from universal_browser_agent.service.api import create_app
from universal_browser_agent.service.config import ServiceSettings


REPO_ROOT = Path(__file__).resolve().parents[1]


class OpenRouterWorkflowIntentPlannerTests(unittest.TestCase):
    def test_structured_intent_is_normalized_without_execution_authority(self) -> None:
        captured: dict = {}

        def transport(url: str, body: dict, *, headers: dict) -> dict:
            captured["url"] = url
            captured["body"] = body
            captured["headers"] = headers
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "task_summary": "Collect public product details",
                                    "requested_capabilities": [
                                        "Navigate",
                                        "Extract",
                                    ],
                                    "notes": "Public research only.",
                                }
                            )
                        }
                    }
                ]
            }

        planner = OpenRouterWorkflowIntentPlanner(
            "test-key",
            "test/model",
            transport=transport,
        )
        intent = planner.propose_intent(
            objective="Collect public product details from the approved website",
            approved_domains=["example.com"],
            start_urls=["https://example.com/"],
        )

        self.assertEqual(intent["requested_capabilities"], ["navigate", "extract"])
        self.assertEqual(
            captured["body"]["response_format"]["json_schema"]["name"],
            "browser_workflow_intent",
        )
        self.assertEqual(
            captured["body"]["messages"][1]["content"].count("example.com"),
            2,
        )

    def test_unexpected_model_fields_are_rejected(self) -> None:
        def transport(url: str, body: dict, *, headers: dict) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "task_summary": "Research website",
                                    "requested_capabilities": ["navigate"],
                                    "notes": "",
                                    "execution_authorized": True,
                                }
                            )
                        }
                    }
                ]
            }

        planner = OpenRouterWorkflowIntentPlanner(
            "test-key",
            "test/model",
            transport=transport,
        )
        with self.assertRaisesRegex(OpenRouterResponseError, "unexpected fields"):
            planner.propose_intent(
                objective="Research the approved public website only",
                approved_domains=["example.com"],
                start_urls=["https://example.com/"],
            )

    def test_model_suggested_publish_is_fail_closed_by_langgraph_policy(self) -> None:
        def transport(url: str, body: dict, *, headers: dict) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "task_summary": "Prepare a publishing workflow",
                                    "requested_capabilities": [
                                        "navigate",
                                        "fill",
                                        "publish",
                                    ],
                                    "notes": "Publishing would change external state.",
                                }
                            )
                        }
                    }
                ]
            }

        intent = OpenRouterWorkflowIntentPlanner(
            "test-key",
            "test/model",
            transport=transport,
        ).propose_intent(
            objective="Prepare a workflow to publish approved content to the website",
            approved_domains=["example.com"],
            start_urls=["https://example.com/"],
        )
        policy_plan = BrowserWorkflowPlanner().plan(
            objective="Prepare a workflow to publish approved content to the website",
            approved_domains=["example.com"],
            start_urls=["https://example.com/"],
            requested_capabilities=intent["requested_capabilities"],
        )

        self.assertEqual(policy_plan["risk_level"], "high")
        self.assertTrue(policy_plan["requires_human_approval"])
        self.assertEqual(policy_plan["status"], "approval-required")
        self.assertFalse(policy_plan["execution_authorized"])


class AIWorkflowPreviewAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.token = "test-token-with-more-than-24-characters"
        settings = ServiceSettings(
            repo_root=REPO_ROOT,
            database_path=(
                Path(self.temporary_directory.name) / "ai-planning.sqlite3"
            ),
            api_token=self.token,
        )
        self.client = TestClient(create_app(settings))
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.payload = {
            "objective": "Research the approved website and summarize public products",
            "approved_domains": ["example.com"],
            "start_urls": ["https://example.com/"],
        }

    def tearDown(self) -> None:
        self.client.close()
        self.temporary_directory.cleanup()

    def test_ai_preview_requires_authentication(self) -> None:
        response = self.client.post(
            "/v1/plans/browser-workflow/ai-preview",
            json=self.payload,
        )
        self.assertEqual(response.status_code, 401)

    def test_ai_preview_fails_closed_when_provider_is_not_configured(self) -> None:
        response = self.client.post(
            "/v1/plans/browser-workflow/ai-preview",
            headers=self.headers,
            json=self.payload,
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("OpenRouter is not configured", response.text)

    def test_ai_preview_returns_policy_result_as_non_executable(self) -> None:
        proposed = {
            "model_intent": {
                "task_summary": "Research products",
                "requested_capabilities": ["navigate", "extract"],
                "notes": "Public research only.",
            },
            "policy_plan": {
                "status": "ready-for-blueprint-review",
                "risk_level": "low",
                "requires_human_approval": False,
                "execution_authorized": False,
                "steps": [],
                "warnings": [],
            },
            "execution_authorized": False,
        }
        with patch(
            "universal_browser_agent.service.orchestrator."
            "RunOrchestrator.propose_ai_workflow",
            new=AsyncMock(return_value=proposed),
        ):
            response = self.client.post(
                "/v1/plans/browser-workflow/ai-preview",
                headers=self.headers,
                json=self.payload,
            )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(
            body["planner"],
            "openrouter-intent+langgraph-policy-v0.5.1",
        )
        self.assertFalse(body["executable"])
        self.assertFalse(body["proposal"]["execution_authorized"])
        self.assertFalse(
            body["proposal"]["policy_plan"]["execution_authorized"]
        )


if __name__ == "__main__":
    unittest.main()
