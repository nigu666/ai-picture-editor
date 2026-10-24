"""自然饱和度、局部清晰度与按当前画布定位的暗角。"""

import math

from PIL import Image, ImageChops, ImageEnhance, ImageFilter

from app.services.images import MAX_PIXELS


def vibrance(rgb: Image.Image, amount: float) -> Image.Image:
    if not amount:
        return rgb
    red, green, blue = rgb.split()
    maximum = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    minimum = ImageChops.darker(ImageChops.darker(red, green), blue)
    chroma = ImageChops.subtract(maximum, minimum)
    mask = chroma.point([round(255 * abs(amount) * (1 - v / 255) ** 2) for v in range(256)])
    target = ImageEnhance.Color(rgb).enhance(2 if amount > 0 else 0)
    return Image.composite(target, rgb, mask)


def clarity(rgb: Image.Image, alpha: Image.Image, amount: float) -> Image.Image:
    if not amount:
        return rgb
    blurred = rgb.filter(ImageFilter.GaussianBlur(2))
    target = Image.blend(blurred, rgb, 1 + 0.8 * amount) if amount > 0 else blurred
    mask = rgb.convert("L").point(
        [round(255 * abs(amount) * 4 * (v / 255) * (1 - v / 255)) for v in range(256)]
    )
    if alpha.getextrema()[0] != alpha.getextrema()[1]:
        # 模糊邻域远宽于锐化；避开透明边缘，防止隐藏背景颜色混入主体。
        difference = ImageChops.difference(
            alpha.filter(ImageFilter.MaxFilter(17)), alpha.filter(ImageFilter.MinFilter(17))
        )
        interior = difference.point(lambda value: 0 if value else 255)
        mask = ImageChops.multiply(mask, interior)
    return Image.composite(target, rgb, mask)


def vignette_mask(size: tuple[int, int], amount: float) -> Image.Image:
    width, height = size
    if min(size) <= 0 or width * height > MAX_PIXELS:
        raise ValueError("invalid vignette dimensions")
    # 两个一维平方距离组合成椭圆遮罩，避免对每个大图像素执行 Python 循环。
    x = Image.frombytes(
        "L",
        (width, 1),
        bytes(
            round(255 * (2 * p / (width - 1) - 1) ** 2) if width > 1 else 0 for p in range(width)
        ),
    )
    y = Image.frombytes(
        "L",
        (1, height),
        bytes(
            round(255 * (2 * p / (height - 1) - 1) ** 2) if height > 1 else 0 for p in range(height)
        ),
    )
    radius = ImageChops.add(
        x.resize(size, Image.Resampling.NEAREST), y.resize(size, Image.Resampling.NEAREST), scale=2
    )
    return radius.point([round(255 * (1 - amount * (v / 255) ** 0.85)) for v in range(256)])


def vignette(rgb: Image.Image, amount: float, document: dict | None = None) -> Image.Image:
    if not amount:
        return rgb
    if document is None:
        mask = vignette_mask(rgb.size, amount)
    else:
        layer = document["layers"][0]
        t = layer["transform"]
        angle = math.radians(t["rotation"])
        a = round(math.cos(angle), 12) * t["scale_x"] * layer["width"] / rgb.width
        b = round(math.sin(angle), 12) * t["scale_x"] * layer["width"] / rgb.width
        c = -round(math.sin(angle), 12) * t["scale_y"] * layer["height"] / rgb.height
        d = round(math.cos(angle), 12) * t["scale_y"] * layer["height"] / rgb.height
        # 输出源图中的每个像素，采样它映射到当前画布的位置；预览仍可复用原图层变换。
        canvas_mask = vignette_mask((document["width"], document["height"]), amount)
        mask = canvas_mask.transform(
            rgb.size,
            Image.Transform.AFFINE,
            (a, c, t["x"], b, d, t["y"]),
            resample=Image.Resampling.BILINEAR,
            fillcolor=255,
        )
    return ImageChops.multiply(rgb, Image.merge("RGB", (mask, mask, mask)))
