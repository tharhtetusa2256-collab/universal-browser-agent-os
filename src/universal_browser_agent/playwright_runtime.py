"""Safety-gated, read-only browser execution through Playwright."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from uuid import uuid4

from playwright.async_api import (
    BrowserContext,
    Error as PlaywrightError,
    Page,
    Request,
    Route,
    TimeoutError as PlaywrightTimeoutError,
    WebSocketRoute,
    async_playwright,
)

from .models import RuntimeTask
from .policy import DomainPolicy, PolicyViolation
from .reporting import ArtifactWriter, RunReport, utc_now


class RuntimeExecutionError(RuntimeError):
    """Raised when a read-only run cannot safely continue."""


class ReadOnlyPlaywrightRuntime:
    def __init__(
        self,
        repo_root: Path,
        task: RuntimeTask,
        *,
        headless: bool = True,
        allow_private_network: bool = False,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.task = task
        self.headless = headless
        self.policy = DomainPolicy(
            task.approved_domains,
            allow_private_network=allow_private_network,
        )
        self.report = RunReport(
            run_id=self._new_run_id(),
            task_id=task.task_id,
            started_at=utc_now(),
        )
        self.writer = ArtifactWriter(self.repo_root, task, self.report.run_id)
        self._seen_duplicates: set[str] = set()

    async def run(self) -> RunReport:
        deadline = time.monotonic() + (self.task.timeout_minutes * 60)
        trace_started = False

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=self.headless)
            context = await browser.new_context(
                accept_downloads=False,
                service_workers="block",
            )
            try:
                await context.tracing.start(
                    screenshots=True,
                    snapshots=True,
                    sources=False,
                )
                trace_started = True
                await self._install_read_only_policy(context)
                page = await context.new_page()
                page.on(
                    "dialog",
                    lambda dialog: asyncio.create_task(dialog.dismiss()),
                )
                await self._visit_pages(page, deadline)
            except Exception as exc:
                self.report.failures.append(
                    {
                        "url": None,
                        "error": f"{type(exc).__name__}: {exc}",
                        "attempt": None,
                    }
                )
            finally:
                if trace_started:
                    try:
                        await context.tracing.stop(path=str(self.writer.trace_path()))
                    except Exception as exc:
                        self.report.failures.append(
                            {
                                "url": None,
                                "error": f"Trace capture failed: {exc}",
                                "attempt": None,
                            }
                        )
                await context.close()
                await browser.close()

        self.report.finish()
        self.writer.write(self.report, self.task.output_formats)
        return self.report

    async def _install_read_only_policy(self, context: BrowserContext) -> None:
        async def enforce(route: Route, request: Request) -> None:
            try:
                if request.method not in {"GET", "HEAD"}:
                    raise PolicyViolation(
                        f"HTTP method is prohibited: {request.method}"
                    )
                await self.policy.validate_url(request.url)
                response = await route.fetch(
                    max_redirects=0,
                    timeout=30_000,
                )
                location = response.headers.get("location")
                if 300 <= response.status < 400 and location:
                    redirect_url = urljoin(request.url, location)
                    await self.policy.validate_url(redirect_url)
            except PolicyViolation as exc:
                if len(self.report.blocked_requests) < 200:
                    self.report.blocked_requests.append(
                        {
                            "url": request.url,
                            "method": request.method,
                            "resource_type": request.resource_type,
                            "reason": str(exc),
                        }
                    )
                await route.abort("blockedbyclient")
                return
            except PlaywrightError:
                await route.abort("failed")
                return
            await route.fulfill(response=response)

        await context.route("**/*", enforce)

        async def block_web_socket(web_socket: WebSocketRoute) -> None:
            if len(self.report.blocked_requests) < 200:
                self.report.blocked_requests.append(
                    {
                        "url": web_socket.url,
                        "method": "WEBSOCKET",
                        "resource_type": "websocket",
                        "reason": "WebSocket connections are prohibited",
                    }
                )
            await web_socket.close(code=1008, reason="Read-only policy")

        await context.route_web_socket("**/*", block_web_socket)

    async def _visit_pages(self, page: Page, deadline: float) -> None:
        urls = self.task.start_urls[: self.task.max_items]
        for index, url in enumerate(urls, start=1):
            if time.monotonic() >= deadline:
                raise RuntimeExecutionError("Task timeout exceeded")

            item = await self._visit_with_retries(page, url, index, deadline)
            if item is None:
                continue
            duplicate_value = item.get(self.task.duplicate_key)
            if duplicate_value is not None:
                duplicate_text = str(duplicate_value)
                if duplicate_text in self._seen_duplicates:
                    self.report.failures.append(
                        {
                            "url": item.get("source_url", url),
                            "error": (
                                "Duplicate result rejected for "
                                f"{self.task.duplicate_key}"
                            ),
                            "attempt": None,
                        }
                    )
                    continue
                self._seen_duplicates.add(duplicate_text)
            self.report.items.append(item)

    async def _visit_with_retries(
        self,
        page: Page,
        url: str,
        index: int,
        deadline: float,
    ) -> dict[str, Any] | None:
        last_error: Exception | None = None
        for attempt in range(1, self.task.max_retries + 2):
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            timeout_ms = min(remaining_ms, 30_000)
            try:
                await self.policy.validate_url(url)
                response = await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=timeout_ms,
                )
                await self.policy.validate_url(page.url)
                if response is not None and response.status >= 400:
                    raise RuntimeExecutionError(
                        f"HTTP {response.status} while loading {page.url}"
                    )
                item = await self._extract(page)
                if "screenshots" in self.task.output_formats:
                    screenshot = self.writer.screenshot_path(index)
                    await page.screenshot(path=str(screenshot), full_page=True)
                    item["screenshot"] = str(screenshot)
                return self._handle_missing_fields(item, url, attempt)
            except (
                PolicyViolation,
                PlaywrightError,
                PlaywrightTimeoutError,
                RuntimeExecutionError,
            ) as exc:
                last_error = exc
                if attempt <= self.task.max_retries and time.monotonic() < deadline:
                    continue
                break

        self.report.failures.append(
            {
                "url": url,
                "error": f"{type(last_error).__name__}: {last_error}",
                "attempt": self.task.max_retries + 1,
            }
        )
        return None

    async def _extract(self, page: Page) -> dict[str, Any]:
        accessed_at = datetime.now(timezone.utc).isoformat()
        title = (await page.title()).strip()
        heading = await self._first_text(page, "h1")
        description = await self._first_attribute(
            page,
            'meta[name="description"]',
            "content",
        )
        body = await self._first_text(page, "body", limit=1_000)

        item: dict[str, Any] = {
            "name": title or heading,
            "summary": description or heading or body,
            "source_url": page.url,
            "accessed_at": accessed_at,
        }
        for field, selector in self.task.selectors.items():
            item[field] = await self._first_text(page, selector)
        for field in self.task.required_fields:
            item.setdefault(field, None)
        return item

    def _handle_missing_fields(
        self,
        item: dict[str, Any],
        url: str,
        attempt: int,
    ) -> dict[str, Any] | None:
        missing = [
            field
            for field in self.task.required_fields
            if item.get(field) in {None, ""}
        ]
        if not missing:
            return item

        error = f"Missing required fields: {missing}"
        if self.task.on_missing_data == "fail":
            raise RuntimeExecutionError(error)
        self.report.failures.append(
            {
                "url": item.get("source_url", url),
                "error": error,
                "attempt": attempt,
            }
        )
        if self.task.on_missing_data == "skip-and-report":
            return None
        return item

    @staticmethod
    async def _first_text(
        page: Page,
        selector: str,
        *,
        limit: int = 2_000,
    ) -> str | None:
        locator = page.locator(selector)
        if await locator.count() == 0:
            return None
        value = (await locator.first.inner_text(timeout=5_000)).strip()
        return value[:limit] or None

    @staticmethod
    async def _first_attribute(
        page: Page,
        selector: str,
        attribute: str,
    ) -> str | None:
        locator = page.locator(selector)
        if await locator.count() == 0:
            return None
        value = await locator.first.get_attribute(attribute, timeout=5_000)
        return value.strip() if value and value.strip() else None

    @staticmethod
    def _new_run_id() -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return f"{timestamp}-{uuid4().hex[:8]}"
