"""认证、素材及异步生成 API 工厂；迁移和 Worker 由独立入口管理。"""

import asyncio
from pathlib import Path
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.db import create_engine, create_session_factory
from app.events import EventBus
from app.routers import (
    agent,
    assets,
    auth,
    background,
    color,
    events,
    generations,
    health,
    layers,
    layout,
    outpainting,
    planning,
    promote,
    region,
    selections,
    sessions,
    split,
    text,
    tools,
    upscaling,
)
from app.storage import ObjectStorage


def create_app(settings: Settings | None = None, *, frontend_dir: Path | None = None) -> FastAPI:
    selected = settings if settings is not None else get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(selected.database_url)
        app.state.session_factory = create_session_factory(engine)
        store = (
            ObjectStorage(selected) if selected.s3_access_key and selected.s3_secret_key else None
        )
        app.state.object_storage = store
        app.state.event_bus = EventBus(selected)
        try:
            yield
        finally:
            await app.state.event_bus.close()
            if store is not None:
                await asyncio.to_thread(store.close)
            await engine.dispose()

    app = FastAPI(
        title="AI 修图智能体 · 第6章本地画布工具阶段",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = selected
    app.include_router(auth.router, prefix="/api")
    app.include_router(health.router, prefix="/api")
    app.include_router(assets.router, prefix="/api")
    app.include_router(generations.router, prefix="/api")
    app.include_router(sessions.router, prefix="/api")
    app.include_router(selections.router, prefix="/api")
    app.include_router(tools.router, prefix="/api")
    app.include_router(color.router, prefix="/api")
    app.include_router(layout.router, prefix="/api")
    app.include_router(layers.router, prefix="/api")
    app.include_router(split.router, prefix="/api")
    app.include_router(promote.router, prefix="/api")
    app.include_router(text.router, prefix="/api")
    app.include_router(background.router, prefix="/api")
    app.include_router(outpainting.router, prefix="/api")
    app.include_router(upscaling.router, prefix="/api")
    app.include_router(region.router, prefix="/api")
    app.include_router(planning.router, prefix="/api")
    app.include_router(agent.router, prefix="/api")
    # 独立路径便于代理对事件流关闭缓冲。
    app.include_router(events.router)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # 校验错误只暴露位置和原因，不把输入密码回显给客户端。
        errors = [{key: item[key] for key in ("loc", "msg", "type")} for item in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})

    if frontend_dir is not None:
        from app.frontend import mount_frontend

        mount_frontend(app, frontend_dir)
    return app
