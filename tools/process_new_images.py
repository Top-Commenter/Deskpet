"""
处理新动作素材：裁剪水印、去背景、统一尺寸
"""
from pathlib import Path
from PIL import Image
import numpy as np

PROJECT = Path(__file__).resolve().parent.parent
ASSETS = PROJECT / "assets"

# 图片映射：(源文件, 输出目录, 输出名, 底部裁剪比例, 左上角裁剪比例)
# 底部裁剪比例 = 从底部裁掉多少（0-1）
# 左上角裁剪 = (x1, y1, x2, y2) 相对坐标，None 表示不裁
IMAGES = [
    # 大奶龙
    ("new_big_1.png", "big", "proud",   0.07, None),   # 叉腰大笑，底部浅水印
    ("new_big_2.png", "big", "stand",   0.10, None),   # 侧身站立，底部知乎水印
    ("new_big_3.png", "big", "think",   0.02, None),   # 托腮思考，中间斜水印
    # 小奶龙
    ("new_small_1.png", "small", "smile", 0.03, None), # 正面微笑，中间斜水印+浅灰背景
    ("new_small_2.png", "small", "shy",   0.0,  (0, 0, 0.18, 0.07)),  # 托脸害羞，左上角AI生成
]

CANVAS = 320


def remove_watermark_text(img: Image.Image) -> Image.Image:
    """
    去除中间斜水印 "qiubiaoqing.com"。
    方法：局部异常检测——水印文字会让局部蓝色通道比周围邻域明显升高，
    而肚子/眼睛是大面积均匀区域，不会被误判。
    """
    from PIL import ImageFilter
    arr = np.array(img.convert("RGBA")).astype(np.float32)
    r, g, b, a = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2], arr[:, :, 3]

    # 计算 B 通道的局部均值（大半径模糊）
    b_img = Image.fromarray(b.astype(np.uint8))
    b_blur = np.array(b_img.filter(ImageFilter.BoxBlur(15))).astype(np.float32)

    # 水印像素：B 通道比局部均值高 15 以上，且在角色区域（非背景）
    b_diff = b - b_blur
    text_mask = (b_diff > 15) & (a > 200) & (r > 150) & (r < 252)

    if not text_mask.any():
        return img

    # 掩码膨胀覆盖文字边缘
    mask_img = Image.fromarray((text_mask * 255).astype(np.uint8))
    mask_dilated = mask_img.filter(ImageFilter.MaxFilter(5))
    text_mask = np.array(mask_dilated) > 128

    print(f"  Detected {text_mask.sum()} watermark pixels")

    # 大半径模糊修复
    blurred = img.filter(ImageFilter.BoxBlur(10))
    blurred_arr = np.array(blurred).astype(np.float32)

    result = arr.copy()
    result[text_mask] = blurred_arr[text_mask]

    return Image.fromarray(result.astype(np.uint8), "RGBA")


def flood_remove_bg(img: Image.Image, tolerance: int = 50) -> Image.Image:
    """从四角泛洪去除近似白色/浅灰背景，最后清理半透明残留"""
    arr = np.array(img.convert("RGBA"))
    h, w = arr.shape[:2]
    visited = np.zeros((h, w), dtype=bool)
    from collections import deque

    seeds = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    seeds += [(w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2)]
    # 加更多边中点
    seeds += [(w // 4, 0), (3 * w // 4, 0), (w // 4, h - 1), (3 * w // 4, h - 1)]
    seeds += [(0, h // 4), (0, 3 * h // 4), (w - 1, h // 4), (w - 1, 3 * h // 4)]

    def is_bg(px):
        return all(c > 255 - tolerance for c in px[:3])

    q = deque()
    for sx, sy in seeds:
        if not visited[sy, sx] and is_bg(arr[sy, sx]):
            visited[sy, sx] = True
            q.append((sx, sy))

    while q:
        x, y = q.popleft()
        arr[y, x, 3] = 0
        for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and not visited[ny, nx]:
                if is_bg(arr[ny, nx]):
                    visited[ny, nx] = True
                    q.append((nx, ny))

    # 清理半透明残留：alpha < 100 的设为 0
    arr[arr[:, :, 3] < 100, 3] = 0

    return Image.fromarray(arr, "RGBA")


def trim_and_center(img: Image.Image, canvas_size: int = CANVAS) -> Image.Image:
    """裁掉透明边，居中放到正方形画布"""
    arr = np.array(img)
    alpha = arr[:, :, 3]
    rows = np.any(alpha > 10, axis=1)
    cols = np.any(alpha > 10, axis=0)
    if not rows.any() or not cols.any():
        return img
    y_min, y_max = np.where(rows)[0][[0, -1]]
    x_min, x_max = np.where(cols)[0][[0, -1]]
    cropped = img.crop((x_min, y_min, x_max + 1, y_max + 1))

    cw, ch = cropped.size
    scale = canvas_size * 0.88 / max(cw, ch)
    new_w, new_h = int(cw * scale), int(ch * scale)
    resized = cropped.resize((new_w, new_h), Image.LANCZOS)

    canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    offset_x = (canvas_size - new_w) // 2
    offset_y = canvas_size - new_h - int(canvas_size * 0.04)
    canvas.paste(resized, (offset_x, offset_y), resized)
    return canvas


def process():
    for src_name, sub_dir, out_name, bottom_crop, tl_crop in IMAGES:
        src = PROJECT / src_name
        if not src.exists():
            print(f"SKIP {src_name} (not found)")
            continue

        img = Image.open(src).convert("RGBA")
        w, h = img.size
        print(f"Processing {src_name} ({w}x{h}) -> {sub_dir}/{out_name}.png")

        # 1. 裁剪底部水印
        if bottom_crop > 0:
            crop_h = int(h * bottom_crop)
            img = img.crop((0, 0, w, h - crop_h))
            print(f"  Cropped bottom {crop_h}px")

        # 2. 裁剪左上角
        if tl_crop:
            x1, y1, x2, y2 = tl_crop
            # 用白色填充左上角区域（后续去背景会去掉）
            draw = Image.new("RGBA", img.size, (255, 255, 255, 255))
            draw.paste(img, (0, 0), img)
            from PIL import ImageDraw
            d = ImageDraw.Draw(draw)
            d.rectangle([0, 0, int(w * x2), int(h * y2)], fill=(255, 255, 255, 255))
            img = draw
            print(f"  Covered top-left corner")

        # 3. 去中间斜水印
        img = remove_watermark_text(img)
        print(f"  Watermark removed")

        # 4. 去背景
        img = flood_remove_bg(img, tolerance=35)
        print(f"  Background removed")

        # 5. 统一尺寸
        img = trim_and_center(img)

        # 保存
        out_dir = ASSETS / sub_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{out_name}.png"
        img.save(out_path, "PNG")
        print(f"  Saved -> {out_path}")
        print()


if __name__ == "__main__":
    process()
