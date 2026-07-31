"""Operator CLI for discovering and validating client workspaces."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .workspaces import WorkspaceNotFoundError, WorkspaceRegistry, WorkspaceValidationError


def main() -> int:
    parser = argparse.ArgumentParser(
        description="List or validate repository-native client workspaces."
    )
    parser.add_argument(
        "command",
        choices=("list", "validate"),
        help="Operation to perform",
    )
    parser.add_argument("--client", help="Client ID for validate")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root (defaults to the current directory)",
    )
    args = parser.parse_args()
    registry = WorkspaceRegistry(args.repo_root)

    try:
        if args.command == "list":
            payload = {
                "workspaces": [
                    workspace.to_dict() for workspace in registry.list()
                ]
            }
        else:
            if not args.client:
                parser.error("--client is required for validate")
            payload = {"workspace": registry.load(args.client).to_dict()}
    except (WorkspaceNotFoundError, WorkspaceValidationError, ValueError) as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}, indent=2))
        return 1

    print(json.dumps({"status": "valid", **payload}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
