"""持久化计划、显式确认、可恢复推进。每次最多执行一个步骤。

固定按会话→计划顺序加行锁。同步副作用与步骤状态一起提交；队列任务先以
同一事务保存编号，再以该编号投递 Redis，重试不会创建第二个任务。
"""

import asyncio
import copy
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import or_, select

from app.agent.llm import PlannerUnavailable
from app.models import AgentTurn, RunStatus, ToolRun
from app.queue import QueueUnavailable, enqueue
from app.services import planning, sessions
from app.services.agent_progress import describe as describe_progress
from app.services.agent_recovery import offer
from app.services.layer_documents import require_tool
from app.services.region_binding import TOOLS
from app.tools import REGISTRY
from app.tools.base import ToolContext

ACTIVE = {"planning", "running"}


def public(turn):
    views, progress = describe_progress(turn)
    output = {
        key: getattr(turn, key)
        for key in (
            "id",
            "session_id",
            "request_id",
            "goal",
            "revision",
            "expected_revision",
            "status",
            "message",
            "analysis",
            "planner_source",
            "steps",
            "created_at",
        )
    }
    output["steps"] = [
        {**{k: v for k, v in step.items() if not k.startswith("_")}, "execution": view}
        for step, view in zip(turn.steps, views, strict=True)
    ]
    output["progress"] = progress
    return output


async def load(db, user_id, session_id, turn_id):
    record = await sessions.load(db, user_id, session_id)
    turn = await db.scalar(
        select(AgentTurn)
        .where(
            AgentTurn.id == turn_id,
            AgentTurn.user_id == user_id,
            AgentTurn.session_id == session_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if turn is None:
        raise HTTPException(404, "计划不存在")
    return record, turn


async def listing(db, user_id, session_id):
    await sessions.load(db, user_id, session_id)
    # 最近 50 条之外仍带回进行中的记录，避免旧计划因新消息增多而失去恢复入口。
    rows = list(
        await db.scalars(
            select(AgentTurn)
            .where(
                AgentTurn.user_id == user_id,
                AgentTurn.session_id == session_id,
            )
            .order_by(AgentTurn.created_at.desc(), AgentTurn.id.desc())
            .limit(50)
        )
    )
    active = list(
        await db.scalars(
            select(AgentTurn).where(
                AgentTurn.user_id == user_id,
                AgentTurn.session_id == session_id,
                or_(
                    AgentTurn.status.in_(ACTIVE),
                    (AgentTurn.status.in_(["cancelled", "stale"]))
                    & AgentTurn.steps.contains([{"status": "running"}]),
                ),
            )
        )
    )
    merged = {row.id: row for row in [*rows, *active]}
    return [
        public(row) for row in sorted(merged.values(), key=lambda row: (row.created_at, row.id))
    ]


async def create(db, user_id, session_id, body, settings, factory, store=None):
    record = await sessions.load(db, user_id, session_id)
    previous = await db.scalar(
        select(AgentTurn).where(
            AgentTurn.session_id == session_id,
            AgentTurn.request_id == body.request_id,
        )
    )
    if previous:
        if previous.goal != body.goal or previous.revision != body.revision:
            raise HTTPException(409, "同一请求编号不能用于不同指令")
        return public(previous)
    sessions.check_version(record, body.revision)
    turn = AgentTurn(
        user_id=user_id,
        session_id=session_id,
        request_id=body.request_id,
        goal=body.goal,
        revision=body.revision,
        expected_revision=body.revision,
        status="planning",
        message="指令已保存，正在规划；尚未执行。",
        steps=[],
        planning_deadline=datetime.now(UTC)
        + timedelta(seconds=settings.planner_timeout_seconds + 35),
    )
    db.add(turn)
    await db.commit()
    turn_id = turn.id
    # 此处不持有会话锁或数据库事务。
    try:
        result = await planning.plan(
            db, user_id, session_id, body.revision, body.goal, settings, factory, store
        )
        status = (
            "pending"
            if result.status in {"ready", "needs_confirmation"}
            else "clarification"
            if result.status == "clarification"
            else "failed"
        )
        message = (
            "计划已保存，请核对下方步骤后确认执行。" if status == "pending" else result.message
        )
        steps = [step.model_dump(mode="json") | {"status": "pending"} for step in result.steps]
        for step in steps:
            if step["tool"] in TOOLS:
                step["_selection_binding"] = copy.deepcopy(result.selection_binding)
        source = result.planner_source[:64]
        analysis = result.analysis
    except asyncio.CancelledError:
        # 保留 planning 记录；显式推进可在截止时间后将中断请求标为失败。
        raise
    except PlannerUnavailable as exc:
        status, message, steps, source = "failed", str(exc), [], ""
        analysis = ""
    except HTTPException as exc:
        if exc.status_code != 409:
            raise
        status, message, steps, source = "stale", "规划期间画布已变化，请重新发送指令。", [], ""
        analysis = ""
    record, turn = await load(db, user_id, session_id, turn_id)
    if turn.status == "planning":
        if record.revision != body.revision:
            status, message, steps = "stale", "规划期间画布已变化，请重新发送指令。", []
            analysis = ""
        turn.status, turn.message, turn.steps, turn.planner_source = status, message, steps, source
        turn.analysis = analysis
        await db.commit()
    return public(turn)


async def cancel(db, user_id, session_id, turn_id):
    record, turn = await load(db, user_id, session_id, turn_id)
    if turn.status in {"pending", "running"}:
        steps = copy.deepcopy(turn.steps)
        for step in steps:
            if step["status"] == "pending":
                step.update(status="cancelled", stage="尚未执行，已停止")
        turn.steps, turn.status = steps, "cancelled"
        turn.message = "后续步骤已停止；已完成的修改保留，已经提交的图片任务仍可能继续。"
    elif turn.status not in {"cancelled", "failed", "stale", "clarification"}:
        raise HTTPException(409, "此计划已经完成；需要恢复画布请使用撤销")
    if turn.status in {"cancelled", "stale"}:
        return await refresh_stopped(db, record, turn)
    return public(turn)


async def refresh_stopped(db, record, turn):
    """停止后的读取只核对旧任务，不执行工具、不投递队列、不改变画布。"""
    steps = copy.deepcopy(turn.steps)
    for step in steps:
        if step["status"] != "running" or not step.get("run_id"):
            continue
        run = await db.scalar(
            select(ToolRun)
            .where(ToolRun.id == uuid.UUID(step["run_id"]), ToolRun.user_id == turn.user_id)
            .execution_options(populate_existing=True)
        )
        expected_tool = "generate" if step["tool"] == "generate_image" else step["tool"]
        if (
            run is None
            or run.tool != expected_tool
            or (
                run.params.get("session_id") is not None
                and run.params["session_id"] != str(record.id)
            )
        ):
            step.update(status="failed", stage="原图片任务不存在或归属不符")
            continue
        step.update(progress=run.progress, stage=run.stage, provider=run.params["provider"])
        if run.status == RunStatus.FAILED:
            step.update(status="failed", stage=run.error or "原图片任务未完成")
        elif run.status == RunStatus.SUCCEEDED:
            try:
                ids = [uuid.UUID(value) for value in run.result.get("asset_ids", [])]
                if not ids:
                    raise HTTPException(422, "原图片任务未返回素材")
                assets = await sessions.owned_assets(db, turn.user_id, ids)
                step.update(status="succeeded", asset_ids=[str(item.id) for item in assets])
                try:
                    await sessions.attach(db, record, assets)
                except HTTPException as exc:
                    if exc.status_code != 422:
                        raise
                    step["stage"] = "素材已保存，候选区已满；可在素材库查看"
            except (HTTPException, ValueError):
                step.update(status="failed", stage="原任务素材尚未核对，请查看原图片任务")
    turn.steps = steps
    turn.message = ("画布已变化，原计划不再推进。" if turn.status == "stale" else "") + (
        "后续步骤已停止；已提交图片任务仍在处理，结果只保存为候选。停止后不会重投任务。"
        if any(step["status"] == "running" for step in steps)
        else "后续步骤已停止；已完成的修改与素材保留，可用撤销恢复画布。"
    )
    await db.commit()
    return public(turn)


async def advance(db, user_id, session_id, turn_id, settings, store, *, confirm=False):
    record, turn = await load(db, user_id, session_id, turn_id)
    if turn.status in {"cancelled", "stale"}:
        return await refresh_stopped(db, record, turn)
    if turn.status == "planning":
        if datetime.now(UTC) > turn.planning_deadline:
            turn.status, turn.message = "failed", "规划请求已中断或超时，请重新发送指令。"
            await db.commit()
        return public(turn)
    if turn.status == "pending" and confirm:
        turn.status = "running"
    elif turn.status != "running":
        return public(turn)
    if record.revision != turn.expected_revision:
        turn.status, turn.message = (
            "stale",
            "画布已变化，剩余步骤停止。请重新规划；此前完成的步骤仍保留。",
        )
        await db.commit()
        return public(turn)

    steps = copy.deepcopy(turn.steps)
    step = next((s for s in steps if s["status"] != "succeeded"), None)
    if step is None:
        turn.status, turn.message = "succeeded", "计划中的步骤已全部完成。"
        await db.commit()
        return public(turn)
    done = {s["id"] for s in steps if s["status"] == "succeeded"}
    run_id, run, local_started = None, None, False
    try:
        async with db.begin_nested():
            if not set(step["depends_on"]) <= done:
                raise HTTPException(422, "步骤依赖尚未完成，已停止执行")
            spec = REGISTRY.get(step["tool"])
            checked = spec.validate(step["params"])
            if step.get("run_id"):
                run = await db.scalar(
                    select(ToolRun)
                    .where(
                        ToolRun.id == uuid.UUID(step["run_id"]),
                        ToolRun.user_id == user_id,
                    )
                    .execution_options(populate_existing=True)
                )
                if run is None:
                    raise HTTPException(404, "图片任务不存在")
                step.update(progress=run.progress, stage=run.stage, provider=run.params["provider"])
                if run.status == RunStatus.FAILED:
                    raise HTTPException(422, run.error or "图片任务失败")
                if run.status == RunStatus.SUCCEEDED:
                    ids = [uuid.UUID(value) for value in run.result.get("asset_ids", [])]
                    if not ids:
                        raise HTTPException(422, "任务没有返回候选图片")
                    assets = await sessions.owned_assets(db, user_id, ids)
                    await sessions.attach(db, record, assets)
                    step.update(status="succeeded", asset_ids=[str(a.id) for a in assets])
                elif run.status == RunStatus.QUEUED:
                    run_id = run.id
            else:
                require_tool(record.document, step["tool"])
                binding = step.get("_selection_binding")
                if step["tool"] in TOOLS and binding is None:
                    raise HTTPException(422, "此局部计划缺少选区快照，请重新发送指令")
                local_started = not spec.queued
                result = await spec.handler(
                    ToolContext(
                        db, user_id, record, settings, store, commit=False, region_binding=binding
                    ),
                    checked,
                )
                if spec.queued:
                    run = result["run"]
                    run_id = run.id
                    step.update(
                        status="running",
                        run_id=str(run.id),
                        progress=0,
                        stage=run.stage,
                        provider=run.provider,
                    )
                else:
                    step["status"] = "succeeded"
            turn.expected_revision = record.revision
        turn.steps = steps
        if all(s["status"] == "succeeded" for s in steps):
            turn.status = "succeeded"
            turn.message = (
                "步骤已完成；处理结果已加入候选墙，未自动采用。"
                if any(s.get("run_id") for s in steps)
                else "计划中的步骤已全部完成。"
            )
        else:
            turn.message = (
                "正在等待图片任务；查询中断可在局部编辑面板继续查询原任务，再读取计划进度。"
                if step["tool"] in TOOLS and step.get("run_id")
                else "正在等待图片任务；结果以实际任务状态为准。"
                if step.get("run_id")
                else "当前步骤已保存，继续读取进度以执行下一步。"
            )
    except Exception as exc:
        # savepoint已退出并回滚。只为已回滚本地工具或已存在图片任务提供恢复入口。
        recovery = offer(step, run, local_started=local_started, error=exc)
        step["status"] = "failed"
        step.pop("recovery", None)
        if recovery:
            step["recovery"] = recovery
            if recovery["mode"] == "retry_step":
                step["_local_failure_rolled_back"] = True
        turn.steps, turn.status = steps, "failed"
        turn.message = (
            str(exc.detail)
            if isinstance(exc, HTTPException) and isinstance(exc.detail, str)
            else "步骤执行失败，已停止；此前完成的步骤仍保留。"
        )
    await db.commit()
    output = public(turn)
    if run_id:
        try:
            # 数据库已提交；同一编号的 ARQ 去重与 Worker claim 防止重复副作用。
            await enqueue(settings, run_id, attempt=run.result.get("query_attempt", 0))
        except QueueUnavailable:
            _, latest = await load(db, user_id, session_id, turn_id)
            if latest.status == "running":
                latest.message = "投递未确认，任务编号已保存；恢复连接后读取进度将重投同一编号。"
                await db.commit()
            output = public(latest)
    return output
