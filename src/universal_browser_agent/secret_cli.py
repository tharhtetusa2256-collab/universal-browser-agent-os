"""Operator CLI for client-scoped secret metadata and brokered adapter runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .secret_broker import CredentialBrokerError, OnePasswordSecretBroker
from .workspaces import WorkspaceRegistry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect secret metadata or run an allowlisted client adapter."
    )
    subparsers = parser.add_subparsers(dest="operation", required=True)
    for operation in ("list", "run"):
        subparser = subparsers.add_parser(operation)
        subparser.add_argument("--client", required=True)
        subparser.add_argument("--repo-root", type=Path, default=Path.cwd())
        if operation == "run":
            subparser.add_argument("--adapter", required=True)
            subparser.add_argument("arguments", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = WorkspaceRegistry(args.repo_root).load_credential_references(args.client)
    if args.operation == "list":
        print(
            json.dumps(
                {
                    "client_id": config.client_id,
                    "environment": config.environment,
                    "provider": config.provider_type,
                    "service_identity": config.service_identity,
                    "allowed_vaults": list(config.allowed_vaults),
                    "bindings": [
                        {
                            "capability": item.capability,
                            "environment_variable": item.environment_variable,
                            "vault": item.vault,
                        }
                        for item in config.bindings
                    ],
                    "adapters": [
                        {
                            "adapter_id": item.adapter_id,
                            "command": item.command,
                            "required_capabilities": list(item.required_capabilities),
                        }
                        for item in config.adapters
                    ],
                },
                indent=2,
            )
        )
        return 0

    arguments = list(args.arguments)
    if arguments[:1] == ["--"]:
        arguments = arguments[1:]
    try:
        return OnePasswordSecretBroker(args.repo_root, config).run(
            args.adapter, arguments
        )
    except CredentialBrokerError as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
