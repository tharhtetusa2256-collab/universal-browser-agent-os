from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from universal_browser_agent.notion_readonly import (
    NotionReadOnlyClient,
    NotionReadOnlyError,
    load_notion_readonly_config,
)
from universal_browser_agent.validation import ConfigurationValidationError
from universal_browser_agent.workspaces import WorkspaceRegistry


REPO_ROOT = Path(__file__).resolve().parents[1]


class TechPowerNotionConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = WorkspaceRegistry(REPO_ROOT)
        self.config = self.registry.load_notion_readonly("tech-power")

    def test_connector_only_workspace_is_valid(self) -> None:
        workspace = self.registry.load("tech-power")
        self.assertEqual(workspace.tasks, ())
        self.assertEqual(workspace.allowed_integrations, ("local-files",))
        self.assertEqual(
            workspace.notion_readonly_config,
            "clients/tech-power/notion-readonly.json",
        )

    def test_expected_data_sources_are_allowlisted(self) -> None:
        self.assertEqual(
            {source.key for source in self.config.data_sources},
            {
                "goal-requests",
                "workflow-blueprints",
                "approval-queue",
                "execution-runs",
                "test-verification",
                "marketing-intelligence",
            },
        )
        self.assertEqual(self.config.notion_api_version, "2026-03-11")
        self.assertEqual(self.config.max_page_size, 25)

    def test_duplicate_data_source_id_is_rejected(self) -> None:
        original = json.loads(
            (REPO_ROOT / "clients/tech-power/notion-readonly.json").read_text(
                encoding="utf-8"
            )
        )
        original["data_sources"][1]["data_source_id"] = original[
            "data_sources"
        ][0]["data_source_id"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notion-readonly.json"
            path.write_text(json.dumps(original), encoding="utf-8")
            with self.assertRaisesRegex(
                ConfigurationValidationError,
                "duplicate Notion data-source ID",
            ):
                load_notion_readonly_config(
                    path,
                    REPO_ROOT / "schemas/notion-readonly.schema.json",
                )


class NotionReadOnlyClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = WorkspaceRegistry(REPO_ROOT).load_notion_readonly(
            "tech-power"
        )

    def test_query_uses_only_allowlisted_source_and_properties(self) -> None:
        captured: dict = {}

        def transport(method: str, url: str, **kwargs: object) -> dict:
            captured.update({"method": method, "url": url, **kwargs})
            return {
                "object": "list",
                "results": [
                    {
                        "id": "page-1",
                        "created_by": {"id": "not-approved-metadata"},
                        "properties": {
                            "Goal": {"title": []},
                            "Private Unapproved Field": {"rich_text": []},
                        },
                    }
                ],
                "has_more": False,
                "next_cursor": None,
            }

        client = NotionReadOnlyClient(
            "read-only-test-token",
            self.config,
            transport=transport,
        )
        result = client.query("goal-requests", page_size=5)

        self.assertEqual(
            set(result["results"][0]["properties"]),
            {"Goal"},
        )
        self.assertNotIn("created_by", result["results"][0])
        self.assertEqual(captured["method"], "POST")
        parsed = urlparse(str(captured["url"]))
        self.assertEqual(
            parsed.path,
            "/v1/data_sources/f7d390db-8b62-4888-80f7-8fafdaa91d7d/query",
        )
        self.assertEqual(
            set(parse_qs(parsed.query)["filter_properties[]"]),
            set(self.config.require_source("goal-requests").allowed_properties),
        )
        self.assertEqual(
            captured["payload"],
            {"page_size": 5, "result_type": "page"},
        )
        self.assertEqual(
            captured["headers"]["Notion-Version"],
            "2026-03-11",
        )

    def test_unapproved_source_is_blocked_before_transport(self) -> None:
        called = False

        def transport(*args: object, **kwargs: object) -> dict:
            nonlocal called
            called = True
            return {}

        client = NotionReadOnlyClient(
            "read-only-test-token",
            self.config,
            transport=transport,
        )
        with self.assertRaisesRegex(NotionReadOnlyError, "not allowlisted"):
            client.query("unapproved-database")
        self.assertFalse(called)

    def test_page_size_cannot_exceed_client_limit(self) -> None:
        client = NotionReadOnlyClient(
            "read-only-test-token",
            self.config,
            transport=lambda *args, **kwargs: {},
        )
        with self.assertRaisesRegex(NotionReadOnlyError, "between 1 and 25"):
            client.query("goal-requests", page_size=26)
        with self.assertRaisesRegex(NotionReadOnlyError, "between 1 and 25"):
            client.query("goal-requests", page_size=0)

    def test_schema_identity_mismatch_is_rejected(self) -> None:
        client = NotionReadOnlyClient(
            "read-only-test-token",
            self.config,
            transport=lambda *args, **kwargs: {"id": "0" * 32},
        )
        with self.assertRaisesRegex(NotionReadOnlyError, "approved identity"):
            client.retrieve_schema("goal-requests")

    def test_client_exposes_no_write_operations(self) -> None:
        client = NotionReadOnlyClient("read-only-test-token", self.config)
        for method in (
            "create",
            "update",
            "delete",
            "publish",
            "create_page",
            "update_page",
        ):
            self.assertFalse(hasattr(client, method))


if __name__ == "__main__":
    unittest.main()
