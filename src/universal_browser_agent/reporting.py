"""Evidence report and artifact writers for browser runs."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import RuntimeTask


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunReport:
    run_id: str
    task_id: str
    started_at: str
    completed_at: str | None = None
    status: str = "running"
    items: list[dict[str, Any]] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    blocked_requests: list[dict[str, Any]] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)

    def finish(self) -> None:
        self.completed_at = utc_now()
        if self.failures and not self.items:
            self.status = "failed"
        elif self.failures:
            self.status = "completed-with-errors"
        else:
            self.status = "completed"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ArtifactWriter:
    def __init__(self, repo_root: Path, task: RuntimeTask, run_id: str) -> None:
        self.base_directory = task.resolve_destination(repo_root) / run_id
        self.base_directory.mkdir(parents=True, exist_ok=False)
        self.screenshot_directory = self.base_directory / "screenshots"

    def screenshot_path(self, index: int) -> Path:
        self.screenshot_directory.mkdir(parents=True, exist_ok=True)
        return self.screenshot_directory / f"{index:04d}.png"

    def trace_path(self) -> Path:
        return self.base_directory / "trace.zip"

    def write(self, report: RunReport, formats: tuple[str, ...]) -> dict[str, str]:
        artifacts: dict[str, str] = {}
        if "json" in formats:
            artifacts["json"] = str(self.base_directory / "report.json")
        if "csv" in formats:
            artifacts["csv"] = str(self.base_directory / "items.csv")
        if "markdown" in formats:
            artifacts["markdown"] = str(self.base_directory / "report.md")
        if self.screenshot_directory.exists():
            artifacts["screenshots"] = str(self.screenshot_directory)
        if self.trace_path().exists():
            artifacts["trace"] = str(self.trace_path())
        report.artifacts.update(artifacts)

        if "json" in formats:
            path = Path(artifacts["json"])
            path.write_text(
                json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

        if "csv" in formats:
            path = Path(artifacts["csv"])
            self._write_csv(path, report.items)

        if "markdown" in formats:
            path = Path(artifacts["markdown"])
            path.write_text(self._render_markdown(report), encoding="utf-8")
        return artifacts

    @staticmethod
    def _write_csv(path: Path, items: list[dict[str, Any]]) -> None:
        fields = sorted({key for item in items for key in item})
        with path.open("w", encoding="utf-8", newline="") as stream:
            if not fields:
                stream.write("")
                return
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(items)

    @staticmethod
    def _render_markdown(report: RunReport) -> str:
        lines = [
            f"# Browser run: {report.task_id}",
            "",
            f"- Run ID: `{report.run_id}`",
            f"- Status: `{report.status}`",
            f"- Started: `{report.started_at}`",
            f"- Completed: `{report.completed_at}`",
            f"- Items: `{len(report.items)}`",
            f"- Failures: `{len(report.failures)}`",
            f"- Blocked requests: `{len(report.blocked_requests)}`",
            "",
            "## Results",
            "",
        ]
        for index, item in enumerate(report.items, start=1):
            lines.append(f"### {index}. {item.get('name') or item.get('source_url')}")
            lines.append("")
            for key, value in item.items():
                lines.append(f"- **{key}:** {value}")
            lines.append("")

        if report.failures:
            lines.extend(["## Failures", ""])
            for failure in report.failures:
                lines.append(
                    f"- `{failure.get('url', 'unknown')}`: {failure.get('error')}"
                )
        return "\n".join(lines).rstrip() + "\n"
