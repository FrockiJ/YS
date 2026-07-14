from __future__ import annotations

import asyncio
import logging
import signal

from src.main import prepare_database
from src.services.extract_jobs import run_extract_worker

logger = logging.getLogger(__name__)


async def _run() -> None:
    await prepare_database()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            logger.warning("Signal handlers unavailable for %s", sig)

    await run_extract_worker(stop_event)


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
