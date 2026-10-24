"""显式恢复失败步骤；只重试已回滚的本地操作或读取同一图片任务。"""

import copy
import uuid

from fastapi import HTTPException
from sqlalchemy import select

from app.models import RunStatus, ToolRun
from app.providers.base import ProviderError
from app.providers.region import NAME, configured
from app.queue import QueueUnavailable, enqueue
from app.services import sessions
from app.services.region_binding import TOOLS

# 这些工具在Agent中使用commit=False，所有画布副作用位于同一savepoint。
LOCAL_TOOLS = {
    "transform_canvas",
    "crop_canvas",
    "layout_canvas",
    "adjust_colors",
    "edit_layer",
    "adopt_candidate",
    "undo_canvas",
    "redo_canvas",
}


def offer(step, run, *, local_started=False, error=None):
    if run is not None:
        if run.status == RunStatus.SUCCEEDED:
            return dict(
                mode="read_result", note="原任务已完成，只重新核对并挂接已有素材，不重新生成。"
            )
        if (
            step["tool"] in TOOLS
            and run.result.get("recoverable")
            and run.result.get("remote_task_id")
        ):
            return dict(
                mode="query_original",
                note="继续查询同一云端任务，不重新提交生成；此前完成步骤保留。",
            )
    if (
        local_started
        and step["tool"] in LOCAL_TOOLS
        and (not isinstance(error, HTTPException) or error.status_code >= 500)
    ):
        return dict(
            mode="retry_step",
            note="本地失败步骤已回滚；明确重试后从这一步继续，此前完成步骤不重复。",
        )
    return None


async def retry(db, record, turn, settings, *, revision, request_id):
    steps = copy.deepcopy(turn.steps)
    # 同一操作回执丢失后的重发，仅返回最新状态；不再次重置步骤或投递队列。
    receipts = [receipt for step in steps for receipt in step.get("_retry_receipts", [])]
    # 兼容早期仅保存最近一次回执的检查点。
    receipts.extend(
        dict(request_id=step["_retry_request_id"], revision=step.get("_retry_revision"))
        for step in steps
        if step.get("_retry_request_id")
    )
    previous = next(
        (receipt for receipt in receipts if receipt["request_id"] == str(request_id)), None
    )
    if previous:
        if previous.get("revision") != revision:
            raise HTTPException(409, "同一重试编号不能用于不同画布版本")
        return turn
    sessions.check_version(record, revision)
    if record.revision != turn.expected_revision:
        raise HTTPException(409, "画布已变化，请重新规划；未重试原计划")
    if turn.status != "failed":
        raise HTTPException(409, "仅未完成的计划可恢复；已停止、已完成或执行中的计划不会重新开始")
    step = next((item for item in steps if item["status"] != "succeeded"), None)
    mode = (step.get("recovery") or {}).get("mode") if step else None
    if (
        step is None
        or step["status"] != "failed"
        or mode not in {"retry_step", "query_original", "read_result"}
    ):
        raise HTTPException(409, "此失败没有可安全重试的检查点，请核对原因后重新规划")
    run = None
    if mode == "retry_step":
        if (
            step.get("run_id")
            or step["tool"] not in LOCAL_TOOLS
            or not step.get("_local_failure_rolled_back")
        ):
            raise HTTPException(409, "本地操作缺少回滚检查点，未重试")
        step.update(status="pending", stage="已确认重试，等待执行失败步骤")
    else:
        run = await db.scalar(
            select(ToolRun)
            .where(ToolRun.id == uuid.UUID(step["run_id"]), ToolRun.user_id == turn.user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        expected = "generate" if step["tool"] == "generate_image" else step["tool"]
        if (
            run is None
            or run.tool != expected
            or (
                run.params.get("session_id") is not None
                and run.params["session_id"] != str(record.id)
            )
        ):
            raise HTTPException(409, "原图片任务归属或工具不符，未恢复")
        if mode == "read_result":
            if run.status != RunStatus.SUCCEEDED:
                raise HTTPException(409, "原图片任务尚未完成，不能重新挂接结果")
        else:
            if (
                step["tool"] not in TOOLS
                or not run.result.get("remote_task_id")
                or run.params.get("session_id") != str(record.id)
            ):
                raise HTTPException(409, "原云端任务编号未确认，不会重复提交生成")
            try:
                configured(settings)
            except ProviderError as exc:
                raise HTTPException(503, str(exc)) from None
            if (
                run.params.get("provider") != NAME
                or run.params.get("model") != settings.region_model
            ):
                raise HTTPException(409, "原任务模型配置与当前不符，请先核对配置")
            if run.status == RunStatus.FAILED and run.result.get("recoverable"):
                run.status, run.stage, run.error, run.finished_at = (
                    RunStatus.QUEUED,
                    "等待继续查询原任务",
                    None,
                    None,
                )
                run.result = {**run.result, "query_attempt": run.result.get("query_attempt", 0) + 1}
            elif run.status not in {RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.SUCCEEDED}:
                raise HTTPException(409, "原任务已确定失败，不能通过恢复查询重新生成")
        step.update(status="running", stage="正在核对原图片任务", progress=run.progress)
    step.update(
        _retry_request_id=str(request_id),
        _retry_revision=revision,
        retry_count=step.get("retry_count", 0) + 1,
    )
    step["_retry_receipts"] = [
        *step.get("_retry_receipts", []),
        dict(request_id=str(request_id), revision=revision),
    ]
    step.pop("recovery", None)
    turn.steps, turn.status = steps, "running"
    turn.message = "已确认从失败检查点继续；此前完成步骤不重复执行。"
    await db.commit()
    if run is not None and run.status == RunStatus.QUEUED:
        try:
            await enqueue(settings, run.id, attempt=run.result.get("query_attempt", 0))
        except QueueUnavailable:
            turn.message = "原任务恢复投递未确认；编号已保留，重新读取只投递同一编号。"
            await db.commit()
    return turn
