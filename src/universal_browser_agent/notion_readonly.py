"""Fail-closed Notion data-source reader with a client-scoped allowlist."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

from .adapters.http import request_json
from .validation import (
    ConfigurationValidationError,
    find_secret_like_keys,
    load_json,
    validate_against_schema,
)


class NotionReadOnlyError(ValueError):
    """Raised when a Notion read would exceed the approved connector scope."""


@dataclass(frozen=True)
class NotionDataSource:
    key: str
    name: str
    data_source_id: str
    allowed_properties: tuple[str, ...]


@dataclass(frozen=True)
class NotionReadOnlyConfig:
    client_id: str
    notion_api_version: str
    max_page_size: int
    data_sources: tuple[NotionDataSource, ...]

    def require_source(self, key: str) -> NotionDataSource:
        for source in self.data_sources:
            if source.key == key:
                return source
        raise NotionReadOnlyError(
            f"Notion data source is not allowlisted for {self.client_id}: {key}"
        )


def load_notion_readonly_config(
    path: Path,
    schema_path: Path,
) -> NotionReadOnlyConfig:
    data = load_json(path)
    errors = validate_against_schema(data, schema_path, "notion_readonly")
    secret_keys = find_secret_like_keys(data)
    if secret_keys:
        errors.append(
            f"notion_readonly secret-like fields are prohibited: {secret_keys}"
        )

    entries = data.get("data_sources", [])
    keys: set[str] = set()
    ids: set[str] = set()
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("key", ""))
            source_id = str(entry.get("data_source_id", ""))
            if key in keys:
                errors.append(f"duplicate Notion data-source key: {key}")
            if source_id in ids:
                errors.append(f"duplicate Notion data-source ID: {source_id}")
            keys.add(key)
            ids.add(source_id)

    if errors:
        raise ConfigurationValidationError(errors)

    return NotionReadOnlyConfig(
        client_id=data["client_id"],
        notion_api_version=data["notion_api_version"],
        max_page_size=data["max_page_size"],
        data_sources=tuple(
            NotionDataSource(
                key=entry["key"],
                name=entry["name"],
                data_source_id=entry["data_source_id"],
                allowed_properties=tuple(entry["allowed_properties"]),
            )
            for entry in entries
        ),
    )


class NotionReadOnlyClient:
    """Expose only schema retrieval and data-source query operations."""

    API_ROOT = "https://api.notion.com/v1"
    SCHEMA_FIELDS = frozenset({"object", "id", "title", "properties"})
    PAGE_FIELDS = frozenset(
        {"object", "id", "created_time", "last_edited_time", "url", "properties"}
    )
    QUERY_FIELDS = frozenset({"object", "results", "has_more", "next_cursor"})

    def __init__(
        self,
        read_token: str,
        config: NotionReadOnlyConfig,
        *,
        transport: Callable[..., dict[str, Any]] = request_json,
    ) -> None:
        if not read_token.strip():
            raise ValueError("Notion read token is required")
        self._read_token = read_token
        self.config = config
        self._transport = transport

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._read_token}",
            "Notion-Version": self.config.notion_api_version,
        }

    def retrieve_schema(self, source_key: str) -> dict[str, Any]:
        source = self.config.require_source(source_key)
        response = self._transport(
            "GET",
            f"{self.API_ROOT}/data_sources/{source.data_source_id}",
            headers=self._headers,
        )
        returned_id = str(response.get("id", "")).replace("-", "").lower()
        expected_id = source.data_source_id.replace("-", "").lower()
        if returned_id != expected_id:
            raise NotionReadOnlyError(
                "Notion returned a data source outside the approved identity"
            )
        filtered = {
            key: value
            for key, value in response.items()
            if key in self.SCHEMA_FIELDS
        }
        properties = response.get("properties")
        if isinstance(properties, dict):
            approved = set(source.allowed_properties)
            filtered["properties"] = {
                key: value for key, value in properties.items() if key in approved
            }
        return filtered

    def query(
        self,
        source_key: str,
        *,
        page_size: int | None = None,
        start_cursor: str | None = None,
    ) -> dict[str, Any]:
        source = self.config.require_source(source_key)
        resolved_size = (
            self.config.max_page_size if page_size is None else page_size
        )
        if not 1 <= resolved_size <= self.config.max_page_size:
            raise NotionReadOnlyError(
                f"page_size must be between 1 and {self.config.max_page_size}"
            )
        if start_cursor is not None and (
            not start_cursor.strip() or len(start_cursor) > 500
        ):
            raise NotionReadOnlyError("start_cursor is invalid")

        query = urlencode(
            [("filter_properties[]", value) for value in source.allowed_properties]
        )
        payload: dict[str, Any] = {
            "page_size": resolved_size,
            "result_type": "page",
        }
        if start_cursor is not None:
            payload["start_cursor"] = start_cursor
        response = self._transport(
            "POST",
            (
                f"{self.API_ROOT}/data_sources/{source.data_source_id}/query"
                f"?{query}"
            ),
            headers=self._headers,
            payload=payload,
        )
        if response.get("object") != "list" or not isinstance(
            response.get("results"), list
        ):
            raise NotionReadOnlyError("Notion returned an invalid query response")
        filtered = {
            key: value
            for key, value in response.items()
            if key in self.QUERY_FIELDS
        }
        approved = set(source.allowed_properties)
        filtered_results: list[Any] = []
        for result in response["results"]:
            if not isinstance(result, dict):
                raise NotionReadOnlyError(
                    "Notion returned a non-object query result"
                )
            filtered_result = {
                key: value
                for key, value in result.items()
                if key in self.PAGE_FIELDS
            }
            properties = result.get("properties")
            if isinstance(properties, dict):
                filtered_result["properties"] = {
                    key: value
                    for key, value in properties.items()
                    if key in approved
                }
            filtered_results.append(filtered_result)
        filtered["results"] = filtered_results
        return filtered
