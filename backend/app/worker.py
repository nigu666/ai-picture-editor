"""独立执行进程：python -m app.worker；Windows 也不注册 Unix 信号。"""

import argparse
import asyncio
import logging
from pathlib import Path

from arq.worker import Worker

from app.config import Settings
from app.db import create_engine, create_session_factory
from app.events import EventBus
from app.queue import redis_settings
from app.storage import ObjectStorage
from app.tasks.generation import generate_task


async def serve(
    settings: Settings,
    *,
    burst=False,
    stop_file: Path | None = None,
    provider_factory=None,
    shutdown_event: asyncio.Event | None = None,
) -> None:
    engine = create_engine(settings.database_url)
    store = ObjectStorage(settings)
    bus = EventBus(settings)
    ctx = {
        "settings": settings,
        "session_factory": create_session_factory(engine),
        "store": store,
        "events": bus,
    }
    if provider_factory:
        ctx["provider_factory"] = provider_factory
    worker = Worker(
        functions=[generate_task],
        redis_settings=redis_settings(settings),
        queue_name=settings.queue_name,
        ctx=ctx,
        burst=burst,
        handle_signals=False,
        max_jobs=2,
        job_timeout=600,
        max_tries=1,
        retry_jobs=False,
        keep_result=3600,
        log_results=False,
        poll_delay=0.1,
    )
    task = asyncio.create_task(worker.async_run())
    try:
        while not task.done():
            if shutdown_event and shutdown_event.is_set():
                break
            if stop_file and stop_file.exists():
                break
            await asyncio.wait({task}, timeout=0.1)
        if task.done():
            await task
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        active = list(worker.tasks.values())
        for job in active:
            job.cancel()
        await asyncio.gather(*active, return_exceptions=True)
        # ARQ 0.28 的 close(handle_signals=False) 用 SIGUSR1；Windows 没有该信号。
        # 这里显式收尾，不调用 Unix 信号路径，不改第三方库。
        if worker.pool is not None:
            await worker.pool.delete(worker.health_check_key)
            await worker.pool.aclose()
        await asyncio.to_thread(store.close)
        await bus.close()
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="修图任务独立 Worker")
    parser.add_argument("--burst", action="store_true", help="队列排空后退出，用于本地验证")
    parser.add_argument("--stop-file", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(serve(Settings(), burst=args.burst, stop_file=args.stop_file))
