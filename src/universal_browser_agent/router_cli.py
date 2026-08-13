"""CLI for deterministic browser-runtime routing decisions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agent.router import BrowserRuntimeRouter, RoutingContext
from .models import RuntimeConfigurationError, RuntimeTask
from .validation import load_validated_configuration


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Choose Playwright, Browser Use, or blocked using deterministic "
            "policy. This command never starts a browser."
        )
    )
    parser.add_argument("--business", type=Path, required=True)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--capability",
        action="append",
        dest="capabilities",
        help=(
            "Requested abstract capability. Repeat for multiple values. "
            "Defaults to navigate + extract."
        ),
    )
    parser.add_argument(
        "--agentic-navigation",
        action="store_true",
        help=(
            "Explicitly opt in to Browser Use when the validated task is otherwise "
            "eligible. Without this flag, Playwright remains the safe default."
        ),
    )
    parser.add_argument(
        "--require-strict-network",
        action="store_true",
        help=(
            "Require the existing Playwright request-level GET/HEAD-only policy."
        ),
    )
    return parser


def run_from_args(args: argparse.Namespace) -> int:
    repo_root = args.repo_root.resolve()
    business_path = args.business if args.business.is_absolute() else repo_root / args.business
    task_path = args.task if args.task.is_absolute() else repo_root / args.task

    try:
        _, task_data = load_validated_configuration(
            business_path,
            task_path,
            repo_root,
        )
        task = RuntimeTask.from_dict(task_data)
        context = RoutingContext(
            mode=task.mode,
            requested_capabilities=tuple(
                args.capabilities or ["navigate", "extract"]
            ),
            selectors_present=bool(task.selectors),
            output_formats=task.output_formats,
            agentic_navigation=bool(args.agentic_navigation),
            require_request_level_get_head_only=bool(args.require_strict_network),
        )
        decision = BrowserRuntimeRouter().decide(context)
    except (ValueError, OSError, RuntimeConfigurationError) as exc:
        print(f"Runtime router error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(decision.to_dict(), indent=2, ensure_ascii=False))
    return 1 if decision.route == "blocked" else 0


def main() -> int:
    return run_from_args(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
