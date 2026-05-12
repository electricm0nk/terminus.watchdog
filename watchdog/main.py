"""Entrypoint stub for Terminus Watchdog Agent."""

from __future__ import annotations

import asyncio
import logging

from pythonjsonlogger import jsonlogger

from watchdog.config import Settings


def _configure_logging() -> None:
    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


async def main() -> None:
    _configure_logging()
    logger = logging.getLogger(__name__)
    settings = Settings()
    logger.info("terminus-watchdog starting", extra={"config": repr(settings)})
    # TODO: initialize clients, detectors, event loop — Story 1.2+


if __name__ == "__main__":
    asyncio.run(main())
