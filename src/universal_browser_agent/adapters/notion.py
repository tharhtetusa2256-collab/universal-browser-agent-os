"""Optional Notion output adapter for evidence-backed run summaries."""

from __future__ import annotations

import json
from typing import Any, Callable

from .http import post_json


class NotionRunPublisher:
    ENDPOINT = "https://api.notion.com/v1/pages"

    def __init__(
        self,
        api_key: str,
        database_id: str,
        *,
        title_property: str = "Name",
        transport: Callable[..., dict[str, Any]] = post_json,
    ) -> None:
        if not api_key or not database_id:
            raise ValueError("Notion API key and database ID are required")
        self.api_key = api_key
        self.database_id = database_id
        self.title_property = title_property
        self.transport = transport

    def publish(self, run: dict[str, Any]) -> dict[str, Any]:
        result = run.get("result") or {}
        items = result.get("items")
        failures = result.get("failures")
        summary = {
            "run_id": run["run_id"],
            "status": run["status"],
            "task_path": run["task_path"],
            "runtime_status": result.get("status"),
            "item_count": len(items) if isinstance(items, list) else None,
            "failure_count": (
                len(failures) if isinstance(failures, list) else None
            ),
            "artifacts": result.get("artifacts", {}),
        }
        code = json.dumps(summary, ensure_ascii=False, indent=2)[:1_900]
        payload = {
            "parent": {"database_id": self.database_id},
            "properties": {
                self.title_property: {
                    "title": [
                        {
                            "text": {
                                "content": (
                                    f"Browser Agent {run['run_id'][:20]} "
                                    f"— {run['status']}"
                                )
                            }
                        }
                    ]
                }
            },
            "children": [
                {
                    "object": "block",
                    "type": "code",
                    "code": {
                        "language": "json",
                        "rich_text": [{"type": "text", "text": {"content": code}}],
                    },
                }
            ],
        }
        return self.transport(
            self.ENDPOINT,
            payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Notion-Version": "2022-06-28",
            },
        )
