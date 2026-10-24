"""只读导出已保存画布；原尺寸合成，不创建素材或编辑历史。"""

import asyncio
import copy
import hashlib
import io
import json
import re
import zipfile
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import quote

from fastapi import HTTPException, Response
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.edits.render import render_document
from app.schemas.generation import SIZES
from app.services import sessions
from app.services.layer_documents import keys_for_document, read_sources

MAX_EXPORT_BYTES = 64 * 1024 * 1024


class ExportTooLarge(Exception):
    pass


class ExportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1, strict=True)
    format: Literal["png", "jpeg"] = "png"
    jpeg_quality: int = Field(default=92, ge=50, le=100, strict=True)
    background: str = Field(default="#FFFFFF", pattern=r"^#[0-9a-fA-F]{6}$")


class BundleInput(ExportInput):
    ratios: list[Literal["1:1", "4:5", "3:4", "9:16", "16:9"]] = Field(
        default_factory=lambda: ["1:1", "4:5", "9:16"], min_length=1, max_length=5
    )
    include_original: bool = Field(default=True, strict=True)
    allow_upscale: bool = Field(default=False, strict=True)

    @field_validator("ratios")
    @classmethod
    def unique(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("同一比例不能重复选择")
        return value


def encode_image(image: Image.Image, options: ExportInput) -> bytes:
    output = io.BytesIO()
    if options.format == "png":
        image.save(output, format="PNG")
    else:
        background = Image.new("RGBA", image.size, options.background)
        background.alpha_composite(image)
        background.convert("RGB").save(
            output, format="JPEG", quality=options.jpeg_quality, subsampling=0
        )
    if output.tell() > MAX_EXPORT_BYTES:
        raise ExportTooLarge
    return output.getvalue()


def encode(sources, document, options: ExportInput) -> bytes:
    return encode_image(render_document(sources, document), options)


def fit(image: Image.Image, size: tuple[int, int], allow_upscale: bool):
    width, height = size
    scale = min(width / image.width, height / image.height)
    if not allow_upscale:
        scale = min(1, scale)
    placed_size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    picture = (
        image if placed_size == image.size else image.resize(placed_size, Image.Resampling.LANCZOS)
    )
    x, y = (width - picture.width) // 2, (height - picture.height) // 2
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    canvas.alpha_composite(picture, (x, y))
    return canvas, {"x": x, "y": y, "width": picture.width, "height": picture.height}


def pack(sources, document, title: str, options: BundleInput) -> bytes:
    image = render_document(sources, document)
    extension = "png" if options.format == "png" else "jpg"
    items, archive, total = [], io.BytesIO(), 0
    targets = ([(None, image.size)] if options.include_original else []) + [
        (ratio, SIZES[ratio]) for ratio in options.ratios
    ]
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as zipped:
        for index, (ratio, size) in enumerate(targets, 1):
            if ratio is None:
                picture, placement = (
                    image,
                    {"x": 0, "y": 0, "width": image.width, "height": image.height},
                )
            else:
                picture, placement = fit(image, size, options.allow_upscale)
            raw = encode_image(picture, options)
            total += len(raw)
            if total > MAX_EXPORT_BYTES:
                raise ExportTooLarge
            slug = ratio.replace(":", "x") if ratio else "original"
            name = f"images/{index:02d}-{slug}-{size[0]}x{size[1]}.{extension}"
            zipped.writestr(name, raw)
            items.append(
                {
                    "file": name,
                    "ratio": ratio,
                    "width": size[0],
                    "height": size[1],
                    "placement": placement,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            )
        manifest = {
            "schema_version": 1,
            "created_at_utc": datetime.now(UTC).isoformat(),
            "source": {
                "title": title,
                "revision": options.revision,
                "width": image.width,
                "height": image.height,
            },
            "options": {
                "format": options.format,
                "background": options.background if options.format == "jpeg" else "transparent",
                "jpeg_quality": options.jpeg_quality if options.format == "jpeg" else None,
                "allow_upscale": options.allow_upscale,
                "fit": "contain_center_no_crop",
            },
            "items": items,
        }
        zipped.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    if archive.tell() > MAX_EXPORT_BYTES:
        raise ExportTooLarge
    return archive.getvalue()


def filename_header(title: str, revision: int, extension: str) -> str:
    title = re.sub(r'[\x00-\x1f\x7f<>:"/\\|?*]', "_", title).strip(" .")[:60] or "画布"
    name = quote(f"{title}-r{revision}.{extension}", safe="")
    return f"attachment; filename=\"canvas-r{revision}.{extension}\"; filename*=UTF-8''{name}"


async def download(db, store, owner, session_id, options: ExportInput):
    bundle = isinstance(options, BundleInput)
    row = await sessions.load(db, owner, session_id)
    sessions.check_version(row, options.revision)
    document, title = copy.deepcopy(row.document), row.title
    keys = await keys_for_document(db, owner, document)
    await db.rollback()
    try:
        async with asyncio.timeout(60 if bundle else 45):
            sources = await read_sources(store, keys)
            raw = (
                await asyncio.to_thread(pack, sources, document, title, options)
                if bundle
                else await asyncio.to_thread(encode, sources, document, options)
            )
    except ExportTooLarge:
        raise HTTPException(422, "导出文件超过64MB，请减少输出内容或使用JPG格式") from None
    except Exception:
        raise HTTPException(503, "导出暂时无法完成，请重试；原画布与编辑记录保留") from None
    # 合成时不持有数据库锁；若期间另一个页面改过画布，拒绝下载过期画面。
    row = await sessions.load(db, owner, session_id)
    sessions.check_version(row, options.revision)
    await db.rollback()
    extension = "zip" if bundle else "png" if options.format == "png" else "jpg"
    extra = (
        {"X-Export-File-Count": str(len(options.ratios) + int(options.include_original))}
        if bundle
        else {
            "X-Export-Width": str(document["width"]),
            "X-Export-Height": str(document["height"]),
        }
    )
    return Response(
        raw,
        media_type="application/zip"
        if bundle
        else "image/png"
        if options.format == "png"
        else "image/jpeg",
        headers={
            "Content-Disposition": filename_header(title, options.revision, extension),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Canvas-Revision": str(options.revision),
            **extra,
        },
    )
