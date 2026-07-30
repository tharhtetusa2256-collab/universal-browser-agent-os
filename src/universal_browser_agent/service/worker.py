"""Durable polling worker for validated browser runs."""

from __future__ import annotations

import argparse
import asyncio
import signal

from .config import ServiceSettings
from .orchestrator import RunOrchestrator
from .store import RunStore


async def worker_loop(settings: ServiceSettings, *, once: bool = False) -> int:
    store = RunStore(settings.database_path)
    store.requeue_stale_runs(
        older_than_minutes=settings.stale_run_minutes,
    )
    orchestrator = RunOrchestrator(settings, store)
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_name, stopping.set)
        except NotImplementedError:
            pass

    while not stopping.is_set():
        record = await orchestrator.execute_next()
        if once:
            return 0
        if record is None:
            try:
                await asyncio.wait_for(
                    stopping.wait(),
                    timeout=settings.poll_seconds,
                )
            except asyncio.TimeoutError:
                pass
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Universal Browser Agent durable worker"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Claim at most one queued run and exit",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    settings = ServiceSettings.from_env()
    return asyncio.run(worker_loop(settings, once=args.once))


if __name__ == "__main__":
    raise SystemExit(main())
