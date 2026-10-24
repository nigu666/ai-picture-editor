"""认证阶段只检查 API 与数据库查询，不冒充完整修图链路健康。"""

import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.deps import SessionDep

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", responses={503: {"description": "数据库查询失败或超时"}})
async def health(session: SessionDep) -> JSONResponse:
    report = {
        "api": "ok",
        "database": "ok",
        "storage": "not_checked",
        "redis": "not_checked",
        "worker": "not_checked",
    }
    try:
        await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=3)
    except (SQLAlchemyError, TimeoutError, OSError):
        report["database"] = "error"
        return JSONResponse(report, status_code=503)
    return JSONResponse(report)
