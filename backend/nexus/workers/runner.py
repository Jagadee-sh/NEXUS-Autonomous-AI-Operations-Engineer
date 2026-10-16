"""Worker runner: claim queued tasks from the database and execute workflows."""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from nexus.database.models import Task
from nexus.database.session import get_session_factory
from nexus.logging_config import get_logger
from nexus.orchestration.engine import run_workflow

log = get_logger("nexus.worker")


async def process_next_queued_task(task_id: str | None = None) -> bool:
    factory = get_session_factory()
    async with factory() as session:
        if task_id:
            task = await session.get(Task, task_id)
            if not task or task.status != "queued":
                return False
        else:
            result = await session.execute(
                select(Task).where(Task.status == "queued").order_by(Task.created_at).limit(1)
            )
            task = result.scalars().first()
            if not task:
                return False
        target_id = task.id

    try:
        async with factory() as session:
            await run_workflow(session, target_id)
        return True
    except Exception:  # noqa: BLE001
        log.exception("failed executing task %s", target_id)
        async with factory() as session:
            t = await session.get(Task, target_id)
            if t and t.status == "running":
                t.status = "failed"
                t.error = "Worker crashed while executing task"
                await session.commit()
        return True


async def drain_queue(max_tasks: int = 100) -> int:
    """Process all currently queued tasks (used by tests and inline mode)."""
    count = 0
    for _ in range(max_tasks):
        processed = await process_next_queued_task()
        if not processed:
            break
        count += 1
    return count


async def worker_main(poll_interval: float = 0.5) -> None:
    from nexus.database.session import init_db
    from nexus.logging_config import setup_logging
    from nexus.workers.queue import get_queue

    setup_logging()
    await init_db()
    queue = get_queue()
    await queue.start(lambda _tid: asyncio.sleep(0), poll_interval=poll_interval)
    log.info("NEXUS worker started (poll=%.2fs)", poll_interval)
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        await queue.stop()
        raise
