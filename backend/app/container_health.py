"""容器内部轻量探针；不运行模型，不把连接信息输出到日志。"""

import asyncio
import json
import sys
from urllib.request import urlopen


async def worker_health():
    from redis.asyncio import Redis

    from app.config import Settings

    settings = Settings()
    client = Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
    try:
        return bool(
            await client.ping() and await client.exists(settings.queue_name + ":health-check")
        )
    finally:
        await client.aclose()


def main():
    try:
        if sys.argv[1] == "worker":
            ready = asyncio.run(worker_health())
        else:
            with urlopen("http://127.0.0.1:7302/api/health", timeout=3) as response:
                ready = json.load(response).get("database") == "ok"
    except Exception:
        ready = False
    raise SystemExit(0 if ready else 1)


if __name__ == "__main__":
    main()
