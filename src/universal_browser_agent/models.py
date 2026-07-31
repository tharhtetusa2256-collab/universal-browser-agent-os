"""Typed runtime configuration derived from a validated browser task."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


class RuntimeConfigurationError(ValueError):
    """Raised when a valid generic task cannot be executed by this adapter."""


@dataclass(frozen=True)
class RuntimeTask:
    task_id: str
    mode: str
    approved_domains: tuple[str, ...]
    start_urls: tuple[str, ...]
    selectors: dict[str, str]
    required_fields: tuple[str, ...]
    output_formats: tuple[str, ...]
    destination: str
    max_items: int
    max_retries: int
    timeout_minutes: int
    duplicate_key: str
    on_missing_data: str

    @classmethod
    def from_dict(cls, task: dict[str, Any]) -> "RuntimeTask":
        if task["mode"] not in {"research-only", "test"}:
            raise RuntimeConfigurationError(
                "The read-only Playwright adapter accepts only research-only or test mode"
            )

        inputs = task["inputs"]
        start_urls = inputs.get("start_urls")
        if (
            not isinstance(start_urls, list)
            or not start_urls
            or not all(isinstance(url, str) and url.strip() for url in start_urls)
        ):
            raise RuntimeConfigurationError(
                "inputs.start_urls must be a non-empty array of URLs"
            )

        selectors = inputs.get("selectors", {})
        if not isinstance(selectors, dict) or not all(
            isinstance(field, str)
            and field
            and isinstance(selector, str)
            and selector
            for field, selector in selectors.items()
        ):
            raise RuntimeConfigurationError(
                "inputs.selectors must map output field names to CSS selectors"
            )

        formats = tuple(task["outputs"]["formats"])
        unsupported = sorted(set(formats) - {"json", "csv", "markdown", "screenshots"})
        if unsupported:
            raise RuntimeConfigurationError(
                f"Unsupported read-only runtime output formats: {unsupported}"
            )

        return cls(
            task_id=task["task_id"],
            mode=task["mode"],
            approved_domains=tuple(
                domain.lower().rstrip(".") for domain in task["approved_domains"]
            ),
            start_urls=tuple(start_urls),
            selectors=dict(selectors),
            required_fields=tuple(task["outputs"].get("required_fields", [])),
            output_formats=formats,
            destination=task["outputs"]["destination"],
            max_items=task["limits"]["max_items"],
            max_retries=task["limits"]["max_retries"],
            timeout_minutes=task["limits"]["timeout_minutes"],
            duplicate_key=task["validation"]["duplicate_key"],
            on_missing_data=task["validation"]["on_missing_data"],
        )

    def resolve_destination(self, repo_root: Path) -> Path:
        destination = Path(self.destination)
        if destination.is_absolute():
            raise RuntimeConfigurationError("outputs.destination must be repository-relative")

        resolved = (repo_root / destination).resolve()
        try:
            relative = resolved.relative_to(repo_root.resolve())
        except ValueError as exc:
            raise RuntimeConfigurationError(
                "outputs.destination must remain inside the repository"
            ) from exc

        allowed_roots = {
            Path("artifacts"),
            Path("results"),
            Path("reports/generated"),
        }
        if not any(relative == root or root in relative.parents for root in allowed_roots):
            raise RuntimeConfigurationError(
                "outputs.destination must be under artifacts/, results/, "
                "or reports/generated/"
            )
        return resolved
