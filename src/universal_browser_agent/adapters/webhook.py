"""Signed outbound webhook adapter for Make.com and similar tools."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Callable

from .http import post_json


class SignedWebhookPublisher:
    def __init__(
        self,
        url: str,
        *,
        secret: str | None = None,
        transport: Callable[..., dict[str, Any]] = post_json,
    ) -> None:
        if not url.startswith("https://"):
            raise ValueError("Outbound webhook URL must use HTTPS")
        self.url = url
        self.secret = secret
        self.transport = transport

    def publish(self, event_type: str, run: dict[str, Any]) -> dict[str, Any]:
        result = run.get("result") or {}
        items = result.get("items")
        failures = result.get("failures")
        payload = {
            "event": event_type,
            "run": {
                "run_id": run["run_id"],
                "status": run["status"],
                "source": run["source"],
                "task_path": run["task_path"],
                "created_at": run["created_at"],
                "updated_at": run["updated_at"],
                "result_summary": {
                    "runtime_run_id": result.get("run_id"),
                    "runtime_status": result.get("status"),
                    "item_count": (
                        len(items) if isinstance(items, list) else None
                    ),
                    "failure_count": (
                        len(failures) if isinstance(failures, list) else None
                    ),
                    "artifacts": result.get("artifacts", {}),
                },
                "error": run.get("error"),
            },
        }
        headers: dict[str, str] = {}
        if self.secret:
            canonical = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            signature = hmac.new(
                self.secret.encode("utf-8"),
                canonical,
                hashlib.sha256,
            ).hexdigest()
            headers["X-UBA-Signature-256"] = f"sha256={signature}"
        return self.transport(self.url, payload, headers=headers)
