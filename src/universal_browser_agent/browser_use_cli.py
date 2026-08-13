"""CLI for the optional Browser Use public read-only adapter."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from .adapters.browser_use_readonly import (
    BrowserUseAdapterError,
    BrowserUseReadOnlyAdapter,
)
from .models import RuntimeTask
from .policy import PolicyViolation
from .validation import load_validated_configuration


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run an approved public research task with the experimental "
            "Browser Use read-only adapter"
        )
    )
    parser.add_argument("--business", type=Path, required=True)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--model",
        default=os.environ.get(
            "UBA_BROWSER_USE_MODEL",
            os.environ.get("UBA_OPENROUTER_MODEL", "openai/gpt-4.1-mini"),
        ),
        help="OpenRouter model used by Browser Use",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=20,
        help="Maximum Browser Use agent steps (1-50)",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show the browser window; headless mode is the default",
    )
    return parser


async def run_from_args(args: argparse.Namespace) -> int:
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
        objective = str(task_data.get("objective", "")).strip()
        adapter = BrowserUseReadOnlyAdapter(
            repo_root,
            task,
            objective=objective,
            model=args.model,
            headless=not args.headed,
            max_steps=args.max_steps,
        )
        summary = await adapter.run()
    except (ValueError, OSError, BrowserUseAdapterError, PolicyViolation) as exc:
        print(f"Browser Use adapter error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(summary.to_dict(), indent=2, ensure_ascii=False))
    return 0 if summary.status != "failed" else 1


def main() -> int:
    return asyncio.run(run_from_args(build_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
