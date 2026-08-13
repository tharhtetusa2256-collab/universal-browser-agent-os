"""API coverage for the deterministic runtime router."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from universal_browser_agent.service.api import create_app
from universal_browser_agent.service.config import ServiceSettings


class RuntimeRouterApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        settings = ServiceSettings(
            repo_root=Path.cwd(),
            database_path=Path(self.tempdir.name) / "router-api.sqlite3",
            api_token="router-api-test-token-1234567890",
        )
        self.client = TestClient(create_app(settings))
        self.headers = {"Authorization": f"Bearer {settings.api_token}"}

    def tearDown(self) -> None:
        self.client.close()
        self.tempdir.cleanup()

    def test_health_reports_v062(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "version": "0.6.2"})

    def test_route_endpoint_requires_authentication(self) -> None:
        response = self.client.post(
            "/v1/routes/browser-runtime",
            json={"mode": "research-only"},
        )
        self.assertEqual(response.status_code, 401)

    def test_route_endpoint_selects_browser_use_only_with_explicit_opt_in(self) -> None:
        response = self.client.post(
            "/v1/routes/browser-runtime",
            headers=self.headers,
            json={
                "mode": "research-only",
                "requested_capabilities": ["navigate", "extract"],
                "selectors_present": False,
                "output_formats": ["json", "markdown", "screenshots"],
                "agentic_navigation": True,
                "require_request_level_get_head_only": False,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "routed")
        self.assertEqual(payload["decision"]["route"], "browser-use")
        self.assertFalse(payload["executable"])
        self.assertFalse(payload["decision"]["execution_authorized"])

    def test_route_endpoint_blocks_consequential_capability(self) -> None:
        response = self.client.post(
            "/v1/routes/browser-runtime",
            headers=self.headers,
            json={
                "mode": "research-only",
                "requested_capabilities": ["navigate", "submit"],
                "agentic_navigation": True,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["decision"]["route"], "blocked")
        self.assertIn(
            "consequential-capability:submit",
            payload["decision"]["blockers"],
        )
        self.assertFalse(payload["decision"]["execution_authorized"])


if __name__ == "__main__":
    unittest.main()
