"""以真实解码结果校验图片，不依赖文件名或客户端声明。"""

import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 50_000_000
MIN_SIDE = 32
ALLOWED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
EXTENSIONS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}


class ImageRejected(Exception):
    pass


@dataclass(frozen=True)
class ImageMeta:
    image_format: str
    content_type: str
    extension: str
    width: int
    height: int
    size_bytes: int
    has_alpha: bool


def probe(data: bytes) -> ImageMeta:
    if not data:
        raise ImageRejected("文件为空")
    if len(data) > MAX_FILE_BYTES:
        raise ImageRejected("文件超过 20 MB 上限")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image_format = image.format or ""
            width, height = image.size
            if image_format not in ALLOWED_FORMATS:
                raise ImageRejected("仅支持 JPG、PNG 与 WebP")
            if min(width, height) < MIN_SIDE:
                raise ImageRejected("图片过小，最短边需不小于 32 像素")
            if width * height > MAX_PIXELS:
                raise ImageRejected("图片像素总量过大")
            has_alpha = image.mode in {"RGBA", "LA", "PA"} or "transparency" in image.info
            image.load()
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
        Image.DecompressionBombError,
    ) as exc:
        raise ImageRejected("文件已损坏或不是受支持的图片") from exc
    return ImageMeta(
        image_format,
        ALLOWED_FORMATS[image_format],
        EXTENSIONS[image_format],
        width,
        height,
        len(data),
        has_alpha,
    )
