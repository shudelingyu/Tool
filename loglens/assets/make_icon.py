"""生成 LogLens 应用图标（PNG + 多尺寸 ICO）。

运行：
    python assets/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

BASE = Path(__file__).resolve().parent
SIZE = 1024
SS = 4  # 超采样倍数，保证小尺寸抗锯齿质量


def _lerp(a: int, b: int, t: float) -> int:
    return int(round(a + (b - a) * t))


def _gradient(top: tuple[int, int, int], bottom: tuple[int, int, int], size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for y in range(size):
        t = y / max(1, size - 1)
        color = (
            _lerp(top[0], bottom[0], t),
            _lerp(top[1], bottom[1], t),
            _lerp(top[2], bottom[2], t),
            255,
        )
        draw.line((0, y, size, y), fill=color)
    return image


def _rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=radius, fill=255
    )
    return mask


def build_icon() -> Image.Image:
    canvas_size = SIZE * SS
    canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))

    # 背景：深海军蓝渐变 + 圆角
    background = _gradient((23, 35, 61), (7, 13, 26), canvas_size)
    mask = _rounded_mask(canvas_size, 205 * SS)
    canvas.paste(background, (0, 0), mask)

    # 左上角柔光
    glow = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse(
        (-260 * SS, -320 * SS, 760 * SS, 700 * SS),
        fill=(56, 189, 248, 38),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(120 * SS))
    canvas.alpha_composite(Image.composite(glow, Image.new("RGBA", glow.size), mask))

    # 非常轻的内描边，提升卡片质感
    border = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    ImageDraw.Draw(border).rounded_rectangle(
        (6 * SS, 6 * SS, canvas_size - 6 * SS, canvas_size - 6 * SS),
        radius=200 * SS,
        outline=(148, 190, 255, 34),
        width=7 * SS,
    )
    canvas.alpha_composite(border)

    cx, cy, radius = 520 * SS, 500 * SS, 288 * SS
    ring_width = 66 * SS
    inner = radius - ring_width
    handle_width = 92 * SS

    # 放大镜阴影
    shadow = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.line(
        (cx + int(inner * 0.72), cy + int(inner * 0.72), 902 * SS, 884 * SS),
        fill=(0, 0, 0, 90),
        width=handle_width,
    )
    shadow_draw.ellipse(
        (cx + inner * 0.72 - handle_width // 2, cy + inner * 0.72 - handle_width // 2,
         cx + inner * 0.72 + handle_width // 2, cy + inner * 0.72 + handle_width // 2),
        fill=(0, 0, 0, 90),
    )
    shadow_draw.ellipse(
        (cx - radius + 10 * SS, cy - radius + 16 * SS,
         cx + radius + 10 * SS, cy + radius + 16 * SS),
        outline=(0, 0, 0, 70),
        width=ring_width,
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(18 * SS))
    canvas.alpha_composite(shadow)

    draw = ImageDraw.Draw(canvas)

    # 手柄
    draw.line(
        (cx + int(inner * 0.72), cy + int(inner * 0.72), 902 * SS, 884 * SS),
        fill=(226, 242, 255, 255),
        width=handle_width,
    )
    for hx, hy in ((cx + int(inner * 0.72), cy + int(inner * 0.72)), (902 * SS, 884 * SS)):
        draw.ellipse(
            (hx - handle_width // 2, hy - handle_width // 2,
             hx + handle_width // 2, hy + handle_width // 2),
            fill=(226, 242, 255, 255),
        )

    # 镜片底色
    draw.ellipse(
        (cx - inner, cy - inner, cx + inner, cy + inner),
        fill=(9, 18, 34, 255),
    )

    # 镜片内部径向微光（用同心圆叠加近似）
    lens_layer = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    lens_draw = ImageDraw.Draw(lens_layer)
    for index in range(28, 0, -1):
        ratio = index / 28
        r = int(inner * ratio)
        alpha = int(26 * (1 - ratio) + 4)
        lens_draw.ellipse(
            (cx - r, cy - r, cx + r, cy + r),
            fill=(56, 189, 248, alpha),
        )
    lens_layer = lens_layer.filter(ImageFilter.GaussianBlur(10 * SS))
    lens_mask = Image.new("L", (canvas_size, canvas_size), 0)
    ImageDraw.Draw(lens_mask).ellipse(
        (cx - inner, cy - inner, cx + inner, cy + inner), fill=255
    )
    canvas.alpha_composite(Image.composite(lens_layer, Image.new("RGBA", lens_layer.size), lens_mask))

    # 镜片里的日志行：不同级别颜色（裁剪到镜片内部）
    lines = [
        (396 * SS, 320 * SS, (56, 189, 248)),
        (470 * SS, 300 * SS, (148, 163, 184)),
        (544 * SS, 262 * SS, (251, 191, 36)),
        (618 * SS, 330 * SS, (251, 113, 133)),
    ]
    line_layer = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    line_draw = ImageDraw.Draw(line_layer)
    bar_height = 24 * SS
    dot_radius = 11 * SS
    for y, length, color in lines:
        line_draw.ellipse(
            (340 * SS - dot_radius, y - dot_radius,
             340 * SS + dot_radius, y + dot_radius),
            fill=color + (255,),
        )
        bar_x = 372 * SS
        line_draw.rounded_rectangle(
            (bar_x, y - bar_height // 2, bar_x + length, y + bar_height // 2),
            radius=bar_height // 2,
            fill=color + (235,),
        )
    line_mask = Image.new("L", (canvas_size, canvas_size), 0)
    ImageDraw.Draw(line_mask).ellipse(
        (cx - inner + 4 * SS, cy - inner + 4 * SS,
         cx + inner - 4 * SS, cy + inner - 4 * SS),
        fill=255,
    )
    canvas.alpha_composite(Image.composite(line_layer, Image.new("RGBA", line_layer.size), line_mask))

    # 镜框（在日志行之上）
    draw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        outline=(232, 245, 255, 255),
        width=ring_width,
    )

    # 高光弧
    highlight = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    highlight_draw = ImageDraw.Draw(highlight)
    highlight_draw.arc(
        (cx - radius + ring_width // 2, cy - radius + ring_width // 2,
         cx + radius - ring_width // 2, cy + radius - ring_width // 2),
        start=196,
        end=286,
        fill=(255, 255, 255, 130),
        width=7 * SS,
    )
    highlight = highlight.filter(ImageFilter.GaussianBlur(4 * SS))
    canvas.alpha_composite(highlight)

    # 镜框上的小星点，增加辨识度
    draw.ellipse(
        (cx + 150 * SS, cy - 250 * SS, cx + 186 * SS, cy - 214 * SS),
        fill=(125, 211, 252, 210),
    )

    icon = canvas.resize((SIZE, SIZE), Image.LANCZOS)
    return icon


def main() -> None:
    icon = build_icon()
    png_path = BASE / "loglens.png"
    ico_path = BASE / "loglens.ico"
    icon.resize((512, 512), Image.LANCZOS).save(png_path)
    icon.save(ico_path, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"written: {png_path}")
    print(f"written: {ico_path}")


if __name__ == "__main__":
    main()
