"""Operator CLI for allowlisted, read-only Notion data-source access."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Sequence

from .notion_readonly import NotionReadOnlyClient
from .workspaces import WorkspaceRegistry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read allowlisted Notion data sources without write operations."
    )
    parser.add_argument("operation", choices=("list", "schema", "query"))
    parser.add_argument("--client", required=True, help="Client workspace ID")
    parser.add_argument("--source", help="Allowlisted data-source key")
    parser.add_argument("--page-size", type=int)
    parser.add_argument("--start-cursor")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root (defaults to the current directory)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = WorkspaceRegistry(args.repo_root).load_notion_readonly(args.client)

    if args.operation == "list":
        print(
            json.dumps(
                {
                    "client_id": config.client_id,
                    "notion_api_version": config.notion_api_version,
                    "max_page_size": config.max_page_size,
                    "data_sources": [
                        {
                            "key": source.key,
                            "name": source.name,
                            "data_source_id": source.data_source_id,
                            "allowed_properties": list(source.allowed_properties),
                        }
                        for source in config.data_sources
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if not args.source:
        parser.error("--source is required for schema and query")
    token = os.environ.get("UBA_NOTION_READ_TOKEN", "")
    if not token:
        parser.error("UBA_NOTION_READ_TOKEN is required for Notion API reads")
    client = NotionReadOnlyClient(token, config)
    if args.operation == "schema":
        result = client.retrieve_schema(args.source)
    else:
        result = client.query(
            args.source,
            page_size=args.page_size,
            start_cursor=args.start_cursor,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
