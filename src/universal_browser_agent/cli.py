"""Command-line interface for validated read-only browser execution."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .models import RuntimeTask
from .playwright_runtime import ReadOnlyPlaywrightRuntime
from .validation import load_validated_configuration


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a validated task with the read-only Playwright adapter"
    )
    parser.add_argument("--business", type=Path, required=True)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show the browser window; headless mode is the default",
    )
    return parser


async def run_from_args(args: argparse.Namespace) -> int:
    repo_root = args.repo_root.resolve()
    business_path = (
        args.business
        if args.business.is_absolute()
        else repo_root / args.business
    )
    task_path = args.task if args.task.is_absolute() else repo_root / args.task
    try:
        _, task_data = load_validated_configuration(
            business_path,
            task_path,
            repo_root,
        )
        task = RuntimeTask.from_dict(task_data)
        runtime = ReadOnlyPlaywrightRuntime(
            repo_root,
            task,
            headless=not args.headed,
        )
        report = await runtime.run()
    except (ValueError, OSError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "run_id": report.run_id,
                "status": report.status,
                "items": len(report.items),
                "failures": len(report.failures),
                "artifacts": report.artifacts,
            },
            indent=2,
        )
    )
    return 0 if report.status != "failed" else 1


def main() -> int:
    return asyncio.run(run_from_args(build_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
