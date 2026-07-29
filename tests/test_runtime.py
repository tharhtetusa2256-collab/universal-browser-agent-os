from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from universal_browser_agent.models import (
    RuntimeConfigurationError,
    RuntimeTask,
)
from universal_browser_agent.playwright_runtime import ReadOnlyPlaywrightRuntime
from universal_browser_agent.policy import DomainPolicy, PolicyViolation


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_task() -> dict:
    return json.loads(
        (REPO_ROOT / "templates/competitor-research/task.json").read_text(
            encoding="utf-8"
        )
    )


class RuntimeTaskTests(unittest.TestCase):
    def test_task_requires_start_urls(self) -> None:
        task = load_task()
        task["inputs"].pop("start_urls", None)

        with self.assertRaisesRegex(
            RuntimeConfigurationError,
            "inputs.start_urls",
        ):
            RuntimeTask.from_dict(task)

    def test_destination_cannot_escape_repository(self) -> None:
        task = load_task()
        task["inputs"]["start_urls"] = ["https://example.com/"]
        task["outputs"]["destination"] = "../outside"
        runtime_task = RuntimeTask.from_dict(task)

        with self.assertRaisesRegex(
            RuntimeConfigurationError,
            "remain inside",
        ):
            runtime_task.resolve_destination(REPO_ROOT)


class DomainPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_approved_public_url_is_allowed(self) -> None:
        policy = DomainPolicy(("example.com",))

        hostname = await policy.validate_url("https://example.com/")

        self.assertEqual(hostname, "example.com")

    async def test_unapproved_subdomain_is_blocked(self) -> None:
        policy = DomainPolicy(("example.com",))

        with self.assertRaisesRegex(PolicyViolation, "not approved"):
            await policy.validate_url("https://www.example.com/")

    async def test_private_network_is_blocked_by_default(self) -> None:
        policy = DomainPolicy(("127.0.0.1",))

        with self.assertRaisesRegex(PolicyViolation, "non-public"):
            await policy.validate_url("http://127.0.0.1/")

    async def test_url_credentials_are_blocked(self) -> None:
        policy = DomainPolicy(("example.com",))

        with self.assertRaisesRegex(PolicyViolation, "Credentials"):
            await policy.validate_url("https://user:password@example.com/")


class FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        port = self.server.server_address[1]
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", f"http://localhost:{port}/")
            self.end_headers()
            return

        body = f"""<!doctype html>
<html>
  <head>
    <title>Fixture Product</title>
    <meta name="description" content="Evidence-backed fixture summary">
  </head>
  <body>
    <h1>Fixture Product</h1>
    <p class="price">100 USD</p>
    <script>new WebSocket("ws://127.0.0.1:{port}/socket");</script>
  </body>
</html>""".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


class PlaywrightRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.thread.start()
        self.temp_directory = tempfile.TemporaryDirectory()

    async def asyncTearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp_directory.cleanup()

    async def test_read_only_fixture_run_writes_evidence(self) -> None:
        port = self.server.server_address[1]
        task = RuntimeTask(
            task_id="fixture-run",
            mode="test",
            approved_domains=("127.0.0.1",),
            start_urls=(f"http://127.0.0.1:{port}/",),
            selectors={"price": ".price"},
            required_fields=(
                "name",
                "summary",
                "price",
                "source_url",
                "accessed_at",
            ),
            output_formats=("json", "csv", "markdown", "screenshots"),
            destination="artifacts/runtime-test",
            max_items=1,
            max_retries=0,
            timeout_minutes=1,
            duplicate_key="source_url",
            on_missing_data="fail",
        )
        runtime = ReadOnlyPlaywrightRuntime(
            Path(self.temp_directory.name),
            task,
            allow_private_network=True,
        )

        report = await runtime.run()

        self.assertEqual(report.status, "completed")
        self.assertEqual(len(report.items), 1)
        self.assertEqual(report.items[0]["name"], "Fixture Product")
        self.assertEqual(report.items[0]["price"], "100 USD")
        self.assertEqual(report.failures, [])
        self.assertTrue(
            any(
                blocked["resource_type"] == "websocket"
                for blocked in report.blocked_requests
            )
        )
        self.assertTrue(Path(report.artifacts["json"]).is_file())
        self.assertTrue(Path(report.artifacts["csv"]).is_file())
        self.assertTrue(Path(report.artifacts["markdown"]).is_file())
        self.assertTrue(Path(report.artifacts["trace"]).is_file())
        self.assertTrue(Path(report.artifacts["screenshots"]).is_dir())

    async def test_redirect_to_unapproved_domain_is_blocked(self) -> None:
        port = self.server.server_address[1]
        task = RuntimeTask(
            task_id="redirect-block",
            mode="test",
            approved_domains=("127.0.0.1",),
            start_urls=(f"http://127.0.0.1:{port}/redirect",),
            selectors={},
            required_fields=("source_url",),
            output_formats=("json",),
            destination="artifacts/redirect-test",
            max_items=1,
            max_retries=0,
            timeout_minutes=1,
            duplicate_key="source_url",
            on_missing_data="fail",
        )
        runtime = ReadOnlyPlaywrightRuntime(
            Path(self.temp_directory.name),
            task,
            allow_private_network=True,
        )

        report = await runtime.run()

        self.assertEqual(report.status, "failed")
        self.assertEqual(len(report.items), 0)
        self.assertTrue(
            any(
                "Domain is not approved: localhost" in blocked["reason"]
                for blocked in report.blocked_requests
            ),
            report.blocked_requests,
        )


if __name__ == "__main__":
    unittest.main()
