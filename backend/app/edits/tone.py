"""局部明暗、简化白平衡与透明边界安全锐化；全部在 RGB 上运算。"""

from PIL import Image, ImageChops, ImageEnhance, ImageFilter


def tone(rgb: Image.Image, highlights: float, shadows: float) -> Image.Image:
    if not highlights and not shadows:
        return rgb
    # 两张遮罩均依据调整前的亮度，避免先调高光再改变阴影选区。
    luminance = rgb.convert("L")
    for value, light in ((highlights, True), (shadows, False)):
        if not value:
            continue
        weights = [
            round(
                255
                * 0.7
                * abs(value)
                * (max(0, (level - 128) / 127) if light else max(0, (128 - level) / 128)) ** 2
            )
            for level in range(256)
        ]
        mask = luminance.point(weights)
        target = Image.new("RGB", rgb.size, "white" if value > 0 else "black")
        rgb = Image.composite(target, rgb, mask)
    return rgb


def white_balance(rgb: Image.Image, temperature: float, tint: float) -> Image.Image:
    if not temperature and not tint:
        return rgb
    # 归一化冷暖与绿/洋红偏移，不是相机色温 Kelvin 或专业色彩空间转换。
    gains = (
        1 + 0.25 * temperature + 0.125 * tint,
        1 - 0.25 * tint,
        1 - 0.25 * temperature + 0.125 * tint,
    )
    table = [min(255, max(0, round(level * gain))) for gain in gains for level in range(256)]
    return rgb.point(table)


def sharpness(rgb: Image.Image, alpha: Image.Image, factor: float) -> Image.Image:
    if factor == 1:
        return rgb
    enhanced = ImageEnhance.Sharpness(rgb).enhance(factor)
    if alpha.getextrema() == (255, 255):
        return enhanced
    # 透明像素可能仍存有旧背景颜色。Alpha 有变化的邻域保留颜色，避免锐化引入边缘光晕。
    minimum, maximum = (
        alpha.filter(ImageFilter.MinFilter(3)),
        alpha.filter(ImageFilter.MaxFilter(3)),
    )
    interior = ImageChops.difference(maximum, minimum).point(lambda v: 0 if v else 255)
    return Image.composite(enhanced, rgb, interior)
