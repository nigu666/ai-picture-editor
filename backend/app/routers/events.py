"""短会话鉴权/快照 + SSE；先订阅再取快照，定时查库弥补通知丢失。"""

import asyncio
import json
import uuid

from fastapi import APIRouter, Cookie, HTTPException, Request
from fastapi.responses import StreamingResponse
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from app.db import session_scope
from app.security import SESSION_COOKIE, read_token
from app.services import auth, runs

router = APIRouter(prefix="/events", tags=["events"])
HEARTBEAT_SECONDS = 15.0
MAX_STREAM_SECONDS = 600.0
TERMINAL = {"succeeded", "failed"}


def frame(payload: dict, event: str | None = None) -> str:
    prefix = f"event: {event}\n" if event else ""
    return prefix + "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


async def read_snapshot(request: Request, run_id: uuid.UUID, token: str | None) -> dict:
    settings = request.app.state.settings
    user_id = read_token(token, settings.jwt_secret) if token else None
    if user_id is None:
        raise HTTPException(401, "未登录或会话已过期")
    # 每次读取都结束并释放会话，不随长连接一直占用数据库连接。
    async with session_scope(request.app.state.session_factory) as session:
        if await auth.get_by_id(session, user_id) is None:
            raise HTTPException(401, "未登录或会话已过期")
        run = await runs.get_for_user(session, user_id, run_id)
        if run is None:
            raise HTTPException(404, "任务不存在")
        return {
            "id": str(run.id),
            "tool": run.tool,
            "status": run.status.value,
            "progress": run.progress,
            "stage": run.stage,
            "error": run.error,
            "result": run.result,
            "provider": run.params["provider"],
        }


@router.get("/runs/{run_id}")
async def stream_run(
    request: Request,
    run_id: uuid.UUID,
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
):
    try:
        await read_snapshot(request, run_id, session)
    except SQLAlchemyError:
        raise HTTPException(503, "任务状态暂不可用") from None

    async def stream():
        bus = request.app.state.event_bus
        deadline = asyncio.get_running_loop().time() + MAX_STREAM_SECONDS
        async with bus.subscribe(run_id) as pubsub:
            last = None
            while True:
                if await request.is_disconnected():
                    return
                try:
                    latest = await read_snapshot(request, run_id, session)
                except HTTPException as exc:
                    name = "session_expired" if exc.status_code == 401 else "unavailable"
                    yield frame({"detail": exc.detail}, event=name)
                    return
                except SQLAlchemyError:
                    yield frame({"detail": "任务状态暂不可用，请重新连接核对"}, event="unavailable")
                    return
                encoded = json.dumps(latest, ensure_ascii=False, sort_keys=True)
                if encoded != last:
                    yield frame(latest)
                    last = encoded
                else:
                    yield ": ping\n\n"
                if latest["status"] in TERMINAL:
                    return
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    return
                tick = min(HEARTBEAT_SECONDS, remaining)
                if pubsub is None:
                    await asyncio.sleep(tick)
                else:
                    try:
                        # 收到的消息只作提示，不直接把 Redis 载荷当业务状态发给用户。
                        await pubsub.get_message(ignore_subscribe_messages=True, timeout=tick)
                    except (RedisError, OSError, TimeoutError):
                        pubsub = None

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
