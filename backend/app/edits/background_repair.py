"""背景补全的场景提示词快照；不改变模型、遮罩或已提交任务。"""

import hashlib
import re

from app.providers.base import ProviderError

POLICY = "background-scene-v2"
LOCAL_POLICY = "local-lama-v1"
ACTION_CLAUSE = re.compile(
    r"(?:^|[，,。.;；!?！？\n])\s*(?:(?:请|帮我|需要|只需)\s*)?"
    r"(?:移除|删除|去除|消除|抹掉|擦除|去掉|不要|不保留|不出现|禁止|remove\b|delete\b|erase\b|without\b|no\b)",
    re.IGNORECASE,
)


def is_local(params):
    return params.get("repair_policy") == LOCAL_POLICY


def configured(settings, *, local=None):
    if local is None:
        local = settings.background_repair_backend == "lama"
    if local:
        from app.services.inpainting import verify_model

        verify_model(settings.lama_model_path)
    else:
        from app.providers.region import configured as cloud_configured

        cloud_configured(settings)


def snapshot(description, *, local=False):
    scene = description.strip()
    if local:
        return dict(repair_policy=LOCAL_POLICY)
    if not 2 <= len(scene) <= 600 or ACTION_CLAUSE.search(scene):
        raise ProviderError(
            "请只描述移开物体后露出的背景，例如“浅灰墙面、连续木纹地板、柔和侧光”；"
            "删除动作由选区决定，描述中请去掉“移除、不要、no、remove”等动作或否定句"
        )
    prompt = (
        "完整的场景背景：" + scene + "。背景材质、纹理、光照和透视与周围可见背景连续，自然衔接。"
    )
    return dict(
        repair_policy=POLICY,
        repair_prompt=prompt,
        repair_prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
    )


def for_task(params):
    if "repair_policy" not in params:
        # 已存在任务沿用旧语义；不得在恢复时悄悄更换付费输入。
        from app.edits.split import prompt

        return prompt(params["request"]["prompt"])
    value = params.get("repair_prompt")
    if (
        params["repair_policy"] != POLICY
        or not isinstance(value, str)
        or not 2 <= len(value) <= 800
        or hashlib.sha256(value.encode()).hexdigest() != params.get("repair_prompt_sha256")
    ):
        raise ProviderError("背景补全提示词快照不完整，未提交新云端任务")
    return value
