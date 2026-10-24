"""Redis临时选区；画布修订和选区版本分别校验，重试同一请求不重复记历史。"""

import asyncio
import base64
import copy
import hashlib
import json

from fastapi import HTTPException
from redis.exceptions import RedisError

from app.edits.selection import rasterize
from app.schemas.selection import PointsIn, SelectionAction, StrokeIn
from app.services import sessions

TTL = 24 * 3600
HISTORY_LIMIT = 20
MAX_POINTS = 8000
MAX_STATE_BYTES = 2 * 1024 * 1024
CAS = """
local current = redis.call('GET', KEYS[1]) or ''
if current ~= ARGV[1] then return 0 end
redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
return 1
"""


class SelectionStore:
    def __init__(self, client, namespace):
        self.client, self.namespace = client, namespace

    def key(self, row):
        return f"{self.namespace}:selection:{row.user_id}:{row.id}"

    async def raw(self, row):
        try:
            async with asyncio.timeout(3):
                return await self.client.get(self.key(row))
        except (RedisError, OSError, TimeoutError):
            raise HTTPException(503, "选区暂存服务不可用，画布和原图未改动") from None

    def state(self, row, raw):
        data = json.loads(raw) if raw else None
        if data is None or data.get("revision") != row.revision:
            return {
                "revision": row.revision,
                "version": 0,
                "states": [[]],
                "cursor": 0,
                "requests": [],
                "png": None,
                "selected_pixels": 0,
            }
        return data

    def public(self, row, data):
        operations = data["states"][data["cursor"]]
        return {
            "revision": row.revision,
            "version": data["version"],
            "width": row.document["width"],
            "height": row.document["height"],
            "has_selection": data["selected_pixels"] > 0,
            "selected_pixels": data["selected_pixels"],
            "can_undo": data["cursor"] > 0,
            "can_redo": data["cursor"] < len(data["states"]) - 1,
            "history_limit": HISTORY_LIMIT,
            "sam_prompts": operations[-1].get("prompts", []) if operations else [],
        }

    async def get(self, row):
        return self.state(row, await self.raw(row))

    def repeated(self, data, request_id, fingerprint):
        for item in data["requests"]:
            if item["id"] == request_id:
                if item["hash"] != fingerprint:
                    raise HTTPException(409, "此选区请求编号已用于其他内容，请重新读取")
                return True
        return False

    async def change(self, db, row, body: StrokeIn | SelectionAction | PointsIn, make_mask=None):
        sessions.check_version(row, body.revision)
        raw = await self.raw(row)
        state = self.state(row, raw)
        fingerprint = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
        request_id = str(body.request_id)
        if self.repeated(state, request_id, fingerprint):
            return self.public(row, state)
        if body.version != state["version"]:
            raise HTTPException(409, "选区已在其他页面更新，请重新读取选区")
        width, height = row.document["width"], row.document["height"]
        data = copy.deepcopy(state)
        # 推理/绘制前释放行锁；保存前仍需重新锁定并校验revision。
        await db.commit()
        if isinstance(body, PointsIn):
            assert make_mask is not None
            png = await make_mask()
            # 点选重算当前物体轮廓，替换当前选区；先前选区仍可撤销恢复。
            current = [{"mask": base64.b64encode(png).decode(),
                        "prompts": body.model_dump(mode="json")["prompts"]}]
        elif isinstance(body, StrokeIn):
            current = [
                *data["states"][data["cursor"]],
                body.model_dump(include={"points", "radius", "mode"}, mode="json"),
            ]
            if sum(len(s.get("points", [])) for s in current) > MAX_POINTS or len(current) > 80:
                raise HTTPException(422, "当前选区笔迹过多，请清除后重新选择")
        elif body.action == "clear":
            current = []
        else:
            step = -1 if body.action == "undo" else 1
            cursor = data["cursor"] + step
            if not 0 <= cursor < len(data["states"]):
                raise HTTPException(409, "没有可撤销或重做的选区记录")
            data["cursor"] = cursor
            current = data["states"][cursor]
        if isinstance(body, (StrokeIn, PointsIn)) or body.action == "clear":
            data["states"] = [*data["states"][: data["cursor"] + 1], current]
            data["states"] = data["states"][-(HISTORY_LIMIT + 1) :]
            data["cursor"] = len(data["states"]) - 1
        png, pixels = await asyncio.to_thread(rasterize, width, height, current)
        data.update(
            version=state["version"] + 1,
            png=base64.b64encode(png).decode(),
            selected_pixels=pixels,
            requests=[*data["requests"][-19:], {"id": request_id, "hash": fingerprint}],
        )
        serialized = json.dumps(data, separators=(",", ":"))
        if len(serialized.encode()) > MAX_STATE_BYTES:
            raise HTTPException(422, "选区历史过大，请清除后重新选择")
        await db.refresh(row, with_for_update=True)
        sessions.check_version(row, body.revision)
        try:
            async with asyncio.timeout(3):
                saved = await self.client.eval(CAS, 1, self.key(row), raw or "", serialized, TTL)
        except (RedisError, OSError, TimeoutError):
            raise HTTPException(503, "选区保存未确认，请重新读取核对，可用同一请求重试") from None
        if not saved:
            latest = await self.get(row)
            if self.repeated(latest, request_id, fingerprint):
                return self.public(row, latest)
            raise HTTPException(409, "选区已变化，请重新读取后再操作")
        return self.public(row, data)
