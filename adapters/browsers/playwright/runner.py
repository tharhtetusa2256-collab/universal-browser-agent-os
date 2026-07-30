from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .domain_policy import DomainPolicy, DomainPolicyError


class ReadOnlyTaskError(ValueError):
    """Raised when a task requests behavior outside the v0.2 read-only boundary."""


REQUIRED_PROHIBITIONS = {
    "login",
    "send",
    "publish",
    "purchase",
    "delete",
    "change-permissions",
    "upload-confidential-data",
    "bypass-access-controls",
}
READ_ONLY_MODES = {"research-only", "test"}


@dataclass(slots=True)
class PageEvidence:
    requested_url: str
    final_url: str | None
    title: str | None
    accessed_at: str
    status_code: int | None
    text_excerpt: str | None
    screenshot: str | None
    error: str | None


@dataclass(slots=True)
class RunReport:
    task_id: str
    status: str
    started_at: str
    completed_at: str
    pages: list[PageEvidence]
    blocked_requests: list[str]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_task(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReadOnlyTaskError(f"task file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ReadOnlyTaskError(f"invalid task JSON: {exc}") from exc

    if not isinstance(value, dict):
        raise ReadOnlyTaskError("task JSON must contain an object")
    return value


def validate_read_only_task(task: Mapping[str, Any]) -> None:
    """Apply runtime safety checks independently of control-plane validation."""
    errors: list[str] = []

    task_id = task.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        errors.append("task_id must be a non-empty string")

    mode = task.get("mode")
    if mode not in READ_ONLY_MODES:
        errors.append(f"mode must be one of {sorted(READ_ONLY_MODES)}")

    domains = task.get("approved_domains")
    if not isinstance(domains, list) or not domains or not all(
        isinstance(domain, str) and domain.strip() for domain in domains
    ):
        errors.append("approved_domains must be a non-empty array of strings")
    else:
        try:
            DomainPolicy.from_domains(domains)
        except DomainPolicyError as exc:
            errors.append(str(exc))

    prohibited_value = task.get("prohibited_actions", [])
    if not isinstance(prohibited_value, list):
        errors.append("prohibited_actions must be an array")
        prohibited: set[str] = set()
    else:
        prohibited = {item for item in prohibited_value if isinstance(item, str)}
    missing_prohibitions = sorted(REQUIRED_PROHIBITIONS - prohibited)
    if missing_prohibitions:
        errors.append(
            "read-only runtime requires prohibited_actions to include: "
            + ", ".join(missing_prohibitions)
        )

    approval = task.get("approval_policy")
    if not isinstance(approval, Mapping):
        errors.append("approval_policy must be an object")
    else:
        consequential = approval.get("consequential_actions")
        if consequential != []:
            errors.append("consequential_actions must be an empty array")
        if approval.get("require_blueprint_confirmation") is not True:
            errors.append("blueprint confirmation must be required")

    limits = task.get("limits")
    if not isinstance(limits, Mapping):
        errors.append("limits must be an object")
    else:
        max_items = limits.get("max_items")
        timeout_minutes = limits.get("timeout_minutes")
        if not isinstance(max_items, int) or not 1 <= max_items <= 100:
            errors.append("read-only pilot limits.max_items must be between 1 and 100")
        if not isinstance(timeout_minutes, int) or not 1 <= timeout_minutes <= 60:
            errors.append("read-only pilot limits.timeout_minutes must be between 1 and 60")

    inputs = task.get("inputs")
    if not isinstance(inputs, Mapping):
        errors.append("inputs must be an object")
    else:
        urls = inputs.get("urls")
        if urls is not None and (
            not isinstance(urls, list)
            or not urls
            or not all(isinstance(url, str) and url.strip() for url in urls)
        ):
            errors.append("inputs.urls must be a non-empty array of URL strings when provided")

    outputs = task.get("outputs")
    if not isinstance(outputs, Mapping):
        errors.append("outputs must be an object")
    elif not isinstance(outputs.get("destination"), str) or not outputs["destination"].strip():
        errors.append("outputs.destination must be a non-empty string")

    if errors:
        raise ReadOnlyTaskError("read-only task rejected:\n- " + "\n- ".join(errors))


def target_urls(task: Mapping[str, Any]) -> list[str]:
    inputs = task.get("inputs", {})
    configured = inputs.get("urls") if isinstance(inputs, Mapping) else None
    if isinstance(configured, list) and configured:
        targets = list(dict.fromkeys(url.strip() for url in configured))
    else:
        targets = [f"https://{domain.strip().rstrip('/')}/" for domain in task["approved_domains"]]

    max_items = int(task["limits"]["max_items"])
    return targets[:max_items]


def _resolve_output_dir(
    task: Mapping[str, Any],
    *,
    repo_root: Path,
    output_dir: Path | None,
) -> Path:
    if output_dir is not None:
        return output_dir.expanduser().resolve()

    destination = Path(str(task["outputs"]["destination"]))
    candidate = (repo_root / destination).resolve()
    try:
        candidate.relative_to(repo_root)
    except ValueError as exc:
        raise ReadOnlyTaskError("task output destination must remain inside the repository") from exc
    return candidate


def _safe_filename(index: int, url: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9.-]+", "-", url).strip("-")[:80] or "page"
    return f"{index:03d}-{slug}.png"


def _write_reports(output_dir: Path, report: RunReport) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = asdict(report)

    (output_dir / "report.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    with (output_dir / "report.csv").open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "requested_url",
            "final_url",
            "title",
            "accessed_at",
            "status_code",
            "text_excerpt",
            "screenshot",
            "error",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for page in report.pages:
            writer.writerow(asdict(page))

    lines = [
        f"# Browser Agent Evidence: {report.task_id}",
        "",
        f"- Status: **{report.status}**",
        f"- Started: `{report.started_at}`",
        f"- Completed: `{report.completed_at}`",
        f"- Pages: `{len(report.pages)}`",
        f"- Blocked requests: `{len(report.blocked_requests)}`",
        "",
    ]
    for index, page in enumerate(report.pages, start=1):
        lines.extend(
            [
                f"## {index}. {page.title or page.requested_url}",
                "",
                f"- Requested URL: `{page.requested_url}`",
                f"- Final URL: `{page.final_url or 'unavailable'}`",
                f"- Accessed: `{page.accessed_at}`",
                f"- HTTP status: `{page.status_code if page.status_code is not None else 'unavailable'}`",
                f"- Screenshot: `{page.screenshot or 'not captured'}`",
                f"- Error: `{page.error or 'none'}`",
                "",
                page.text_excerpt or "_No text extracted._",
                "",
            ]
        )
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


async def run_read_only_task(
    task: Mapping[str, Any],
    *,
    repo_root: Path | None = None,
    output_dir: Path | None = None,
    headless: bool = True,
) -> RunReport:
    """Visit approved public pages without login, clicks, forms, or state changes."""
    validate_read_only_task(task)
    root = (repo_root or Path.cwd()).resolve()
    destination = _resolve_output_dir(task, repo_root=root, output_dir=output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    policy = DomainPolicy.from_domains(task["approved_domains"])
    targets = target_urls(task)
    for target in targets:
        policy.validate_url(target, resolve_dns=True)

    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise ReadOnlyTaskError(
            "Playwright is not installed. Run: pip install -r requirements-runtime.txt "
            "and then: playwright install chromium"
        ) from exc

    started_at = _utc_now()
    pages: list[PageEvidence] = []
    blocked_requests: list[str] = []
    timeout_ms = min(int(task["limits"]["timeout_minutes"]) * 60_000, 60_000)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=headless)
        context = await browser.new_context(
            accept_downloads=False,
            service_workers="block",
        )
        context.set_default_timeout(timeout_ms)
        context.set_default_navigation_timeout(timeout_ms)

        async def enforce_request_scope(route: Any) -> None:
            request_url = route.request.url
            if request_url.startswith(("about:", "data:", "blob:")):
                await route.continue_()
                return
            try:
                policy.validate_url(request_url, resolve_dns=True)
            except DomainPolicyError:
                blocked_requests.append(request_url)
                await route.abort("blockedbyclient")
                return
            await route.continue_()

        await context.route("**/*", enforce_request_scope)

        for index, requested_url in enumerate(targets, start=1):
            page = await context.new_page()
            page.on("popup", lambda popup: asyncio.create_task(popup.close()))
            screenshot_name = _safe_filename(index, requested_url)
            screenshot_path = destination / screenshot_name
            screenshot_captured = False
            final_url: str | None = None
            title: str | None = None
            status_code: int | None = None
            text_excerpt: str | None = None
            error: str | None = None

            try:
                response = await page.goto(requested_url, wait_until="domcontentloaded")
                final_url = page.url
                policy.validate_url(final_url, resolve_dns=True)
                status_code = response.status if response is not None else None
                title = (await page.title()).strip() or None
                try:
                    body_text = await page.locator("body").inner_text(timeout=5_000)
                    text_excerpt = " ".join(body_text.split())[:4_000] or None
                except Exception:
                    text_excerpt = None
                await page.screenshot(path=str(screenshot_path), full_page=False)
                screenshot_captured = screenshot_path.exists()
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                try:
                    await page.screenshot(path=str(screenshot_path), full_page=False)
                    screenshot_captured = screenshot_path.exists()
                except Exception:
                    screenshot_captured = False
            finally:
                pages.append(
                    PageEvidence(
                        requested_url=requested_url,
                        final_url=final_url,
                        title=title,
                        accessed_at=_utc_now(),
                        status_code=status_code,
                        text_excerpt=text_excerpt,
                        screenshot=screenshot_name if screenshot_captured else None,
                        error=error,
                    )
                )
                await page.close()

        await context.close()
        await browser.close()

    status = "completed" if pages and all(page.error is None for page in pages) else "completed-with-errors"
    report = RunReport(
        task_id=str(task["task_id"]),
        status=status,
        started_at=started_at,
        completed_at=_utc_now(),
        pages=pages,
        blocked_requests=list(dict.fromkeys(blocked_requests)),
    )
    _write_reports(destination, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a safe read-only Playwright task")
    parser.add_argument("--task", type=Path, required=True, help="Validated browser task JSON")
    parser.add_argument("--output", type=Path, help="Optional output directory override")
    parser.add_argument("--headed", action="store_true", help="Show the Chromium window")
    args = parser.parse_args()

    task = load_task(args.task)
    try:
        report = asyncio.run(
            run_read_only_task(
                task,
                output_dir=args.output,
                headless=not args.headed,
            )
        )
    except (ReadOnlyTaskError, DomainPolicyError) as exc:
        parser.error(str(exc))

    print(json.dumps(asdict(report), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
