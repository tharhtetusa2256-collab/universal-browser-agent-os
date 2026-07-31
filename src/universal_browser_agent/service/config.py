"""Environment-backed configuration for the v0.4 service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser().resolve() if value else default.resolve()


@dataclass(frozen=True)
class ServiceSettings:
    """Runtime settings with secrets loaded only from the environment."""

    repo_root: Path
    database_path: Path
    api_token: str
    poll_seconds: float = 2.0
    stale_run_minutes: int = 480
    openrouter_api_key: str | None = None
    openrouter_model: str = "openai/gpt-4.1-mini"
    notion_api_key: str | None = None
    notion_database_id: str | None = None
    notion_title_property: str = "Name"
    outbound_webhook_url: str | None = None
    outbound_webhook_secret: str | None = None

    @classmethod
    def from_env(cls) -> "ServiceSettings":
        repo_root = _env_path("UBA_REPO_ROOT", Path.cwd())
        database_path = _env_path(
            "UBA_DATABASE_PATH",
            repo_root / "service-data" / "browser-agent.sqlite3",
        )
        poll_value = os.environ.get("UBA_WORKER_POLL_SECONDS", "2")
        try:
            poll_seconds = float(poll_value)
        except ValueError as exc:
            raise ValueError("UBA_WORKER_POLL_SECONDS must be numeric") from exc
        if not 0.1 <= poll_seconds <= 300:
            raise ValueError("UBA_WORKER_POLL_SECONDS must be between 0.1 and 300")
        stale_value = os.environ.get("UBA_STALE_RUN_MINUTES", "480")
        try:
            stale_run_minutes = int(stale_value)
        except ValueError as exc:
            raise ValueError("UBA_STALE_RUN_MINUTES must be an integer") from exc
        if not 30 <= stale_run_minutes <= 1_440:
            raise ValueError(
                "UBA_STALE_RUN_MINUTES must be between 30 and 1440"
            )

        return cls(
            repo_root=repo_root,
            database_path=database_path,
            api_token=os.environ.get("UBA_API_TOKEN", ""),
            poll_seconds=poll_seconds,
            stale_run_minutes=stale_run_minutes,
            openrouter_api_key=os.environ.get("OPENROUTER_API_KEY"),
            openrouter_model=os.environ.get(
                "UBA_OPENROUTER_MODEL",
                "openai/gpt-4.1-mini",
            ),
            notion_api_key=os.environ.get("NOTION_API_KEY"),
            notion_database_id=os.environ.get("UBA_NOTION_DATABASE_ID"),
            notion_title_property=os.environ.get(
                "UBA_NOTION_TITLE_PROPERTY",
                "Name",
            ),
            outbound_webhook_url=os.environ.get("UBA_OUTBOUND_WEBHOOK_URL"),
            outbound_webhook_secret=os.environ.get(
                "UBA_OUTBOUND_WEBHOOK_SECRET"
            ),
        )

    def require_api_token(self) -> None:
        if (
            len(self.api_token) < 24
            or self.api_token.startswith("replace-with-")
        ):
            raise ValueError(
                "UBA_API_TOKEN must be a unique value with at least 24 characters"
            )
