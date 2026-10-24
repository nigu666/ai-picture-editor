"""提交端按需连接 Redis；数据库和 Redis 不构成同一个事务。"""

import asyncio
import uuid

from arq import create_pool
from arq.connections import RedisSettings
from redis.exceptions import RedisError

from app.config import Settings


class QueueUnavailable(Exception):
    pass


def redis_settings(settings: Settings) -> RedisSettings:
    config = RedisSettings.from_dsn(settings.redis_url)
    config.conn_retries = 0
    config.conn_timeout = 2
    return config


async def enqueue(settings: Settings, run_id: uuid.UUID, *, attempt: int = 0) -> bool:
    """True 是本次入队，False 是保留期内已有相同 job ID。"""
    pool = None
    try:
        async with asyncio.timeout(5):
            pool = await create_pool(redis_settings(settings))
            job = await pool.enqueue_job(
                "generate_task",
                str(run_id),
                _job_id=str(run_id) if attempt == 0 else f"{run_id}:resume:{attempt}",
                _queue_name=settings.queue_name,
            )
            return job is not None
    except (RedisError, OSError, TimeoutError) as exc:
        # 超时可能发生在 Redis 已接收之后，不能断言任务必然未入队。
        raise QueueUnavailable("任务投递未确认") from exc
    finally:
        if pool is not None:
            await pool.aclose()
