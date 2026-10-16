"""Standalone worker entrypoint: python -m nexus.workers.app"""

from __future__ import annotations

import asyncio

from nexus.config import settings
from nexus.workers.runner import worker_main

if __name__ == "__main__":
    asyncio.run(worker_main(settings.worker_poll_interval))
