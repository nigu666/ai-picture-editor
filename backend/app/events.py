"""跨进程即时通知仅提示重新查库；不作为持久状态或历史消息存储。"""

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import Settings

logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self, settings: Settings):
        self.client = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=20,
        )
        self.prefix = settings.queue_name + ":events:"

    def channel(self, run_id: uuid.UUID) -> str:
        return self.prefix + str(run_id)

    async def notify(self, run_id: uuid.UUID) -> bool:
        try:
            async with asyncio.timeout(1.5):
                await self.client.publish(self.channel(run_id), "changed")
            return True
        except (RedisError, OSError, TimeoutError):
            # 通知失败不能反向把已提交的成功任务改成失败；SSE 定时查库补核。
            logger.warning("任务通知不可用 run=%s", run_id)
            return False

    @asynccontextmanager
    async def subscribe(self, run_id: uuid.UUID):
        pubsub = self.client.pubsub()
        ready = False
        try:
            try:
                async with asyncio.timeout(1.5):
                    await pubsub.subscribe(self.channel(run_id))
                    while True:
                        ack = await pubsub.get_message(timeout=1)
                        if ack and ack["type"] == "subscribe":
                            ready = True
                            break
            except (RedisError, OSError, TimeoutError):
                logger.warning("任务订阅不可用 run=%s", run_id)
            yield pubsub if ready else None
        finally:
            await pubsub.aclose()

    async def close(self):
        await self.client.aclose()
