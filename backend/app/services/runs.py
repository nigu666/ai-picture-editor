"""任务状态只依据实际阶段推进；排队、执行、素材提交分别记录。"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RunStatus, ToolRun


async def create(
    session: AsyncSession,
    user_id: uuid.UUID,
    params: dict,
    *,
    commit: bool = True,
    tool: str = "generate",
) -> ToolRun:
    run = ToolRun(user_id=user_id, tool=tool, params=params)
    session.add(run)
    await session.flush()
    if commit:
        await session.commit()
    await session.refresh(run)
    return run


async def get_for_user(session: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID):
    return await session.scalar(
        select(ToolRun).where(ToolRun.id == run_id, ToolRun.user_id == user_id)
    )


async def claim(session: AsyncSession, run_id: uuid.UUID) -> ToolRun | None:
    # 只有一个消费者能将同一记录从 queued 改成 running。
    run = await session.scalar(
        update(ToolRun)
        .where(ToolRun.id == run_id, ToolRun.status == RunStatus.QUEUED)
        .values(
            status=RunStatus.RUNNING,
            progress=5,
            stage="开始执行",
            error=None,
            started_at=datetime.now(UTC),
        )
        .returning(ToolRun)
    )
    await session.commit()
    return run


async def report(session: AsyncSession, run: ToolRun, value: int, stage: str) -> None:
    run.progress = max(run.progress, min(99, max(0, value)))
    run.stage = stage[:64]
    await session.commit()


async def finish(session: AsyncSession, run: ToolRun, error: str | None = None) -> None:
    run.status = RunStatus.FAILED if error else RunStatus.SUCCEEDED
    run.error = error
    run.finished_at = datetime.now(UTC)
    run.stage = (
        "执行失败"
        if error
        else "结果已保存（Mock）"
        if run.params["provider"] == "mock"
        else "结果已保存"
    )
    if error is None:
        run.progress = 100
    await session.commit()


async def submission_uncertain(session: AsyncSession, run_id: uuid.UUID) -> None:
    await session.execute(
        update(ToolRun)
        .where(ToolRun.id == run_id, ToolRun.status == RunStatus.QUEUED)
        .values(stage="投递未确认", error="Redis 投递未确认，请查询任务状态后核对")
    )
    await session.commit()
