"""只由服务端读取、固定并验证选区；遮罩不进入模型或公开计划。"""

import base64
import copy
import hashlib

from fastapi import HTTPException
from redis.asyncio import Redis

from app.services.selections import SelectionStore

TOOLS = {"erase_region", "replace_region"}


async def capture(row, settings):
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        state = await SelectionStore(client, settings.queue_name).get(row)
    finally:
        await client.aclose()
    if not state["selected_pixels"] or not state["png"]:
        return None
    return {
        "user_id": str(row.user_id),
        "session_id": str(row.id),
        "revision": row.revision,
        "asset_id": str(row.current_asset_id),
        "document": copy.deepcopy(row.document),
        "version": state["version"],
        "selected_pixels": state["selected_pixels"],
        "png": state["png"],
        "sha256": hashlib.sha256(base64.b64decode(state["png"])).hexdigest(),
    }


def summary(binding):
    return {key: binding[key] for key in ("revision", "version", "selected_pixels")}


def checked(binding, row, version):
    if (
        binding.get("user_id") != str(row.user_id)
        or binding.get("session_id") != str(row.id)
        or binding.get("asset_id") != str(row.current_asset_id)
        or binding.get("revision") != row.revision
        or binding.get("document") != row.document
        or binding.get("version") != version
    ):
        raise HTTPException(409, "计划绑定的画布已变化，请重新规划选区编辑")
    try:
        mask = base64.b64decode(binding["png"], validate=True)
        valid = hashlib.sha256(mask).hexdigest() == binding["sha256"]
        valid = valid and binding["selected_pixels"] > 0
    except (KeyError, ValueError, TypeError):
        valid = False
    if not valid:
        raise HTTPException(422, "计划选区快照无效，请重新选择并规划")
    return binding
