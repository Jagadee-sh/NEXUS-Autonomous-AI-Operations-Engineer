"""Task queue abstraction: in-process asyncio (default) + Redis-backed (optional)."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Awaitable, Callable

from nexus.config import settings
from nexus.logging_config import get_logger

log = get_logger("nexus.queue")

Handler = Callable[[str], Awaitable[None]]


class InProcessQueue:
    """Durable-enough for dev: tasks are also persisted in Postgres/SQLite with status=queued.

    The worker loop re-scans for queued tasks, so restarts do not lose work.
    """

    def __init__(self) -> None:
        self._wakeup = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._handler: Handler | None = None
        self._stopping = False

    async def enqueue(self, task_id: str) -> None:
        self._wakeup.set()

    async def start(self, handler: Handler, poll_interval: float | None = None) -> None:
        self._handler = handler
        self._stopping = False
        interval = poll_interval or settings.worker_poll_interval
        self._task = asyncio.create_task(self._loop(interval), name="nexus-inprocess-worker")

    async def stop(self) -> None:
        self._stopping = True
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self, interval: float) -> None:
        from nexus.workers.runner import process_next_queued_task

        while not self._stopping:
            try:
                processed = await process_next_queued_task()
                if not processed:
                    try:
                        await asyncio.wait_for(self._wakeup.wait(), timeout=interval)
                    except TimeoutError:
                        pass
                    self._wakeup.clear()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("worker loop error")
                await asyncio.sleep(interval)


class RedisQueue:
    """Redis list-backed queue. Falls back silently if Redis is unreachable at enqueue time."""

    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self._task: asyncio.Task | None = None
        self._stopping = False
        self._fallback = InProcessQueue()

    async def enqueue(self, task_id: str) -> None:
        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(self.redis_url, decode_responses=True)
            try:
                await client.lpush("nexus:tasks", task_id)
            finally:
                await client.aclose()
        except Exception as exc:  # noqa: BLE001
            log.warning("redis enqueue failed (%s); relying on DB polling", exc)
        self._fallback._wakeup.set()

    async def start(self, handler: Handler, poll_interval: float | None = None) -> None:
        interval = poll_interval or settings.worker_poll_interval
        self._stopping = False
        self._task = asyncio.create_task(self._loop(interval), name="nexus-redis-worker")

    async def stop(self) -> None:
        self._stopping = True
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _loop(self, interval: float) -> None:
        from nexus.workers.runner import process_next_queued_task

        while not self._stopping:
            try:
                task_id = None
                try:
                    import redis.asyncio as aioredis

                    client = aioredis.from_url(self.redis_url, decode_responses=True)
                    try:
                        task_id = await client.rpop("nexus:tasks")
                    finally:
                        await client.aclose()
                except Exception:  # noqa: BLE001
                    task_id = None
                if task_id:
                    await process_next_queued_task(task_id)
                else:
                    processed = await process_next_queued_task()
                    if not processed:
                        await asyncio.sleep(interval)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("redis worker error")
                await asyncio.sleep(interval)


_queue: InProcessQueue | RedisQueue | None = None


def get_queue():
    global _queue
    if _queue is None:
        _queue = RedisQueue(settings.redis_url) if settings.redis_url else InProcessQueue()
    return _queue


def reset_queue_for_tests() -> None:
    global _queue
    _queue = None


_ = json
