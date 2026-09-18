"""
奶龙桌宠素材处理脚本
- 裁掉底部水印/标签
- 去除背景（白底图用泛洪填充，深色背景图用深色泛洪）
- 统一画布尺寸，角色居中
- 输出透明 PNG
"""
import sys
from pathlib import Path
from PIL import Image, ImageDraw
from collections import deque

PROJECT = Path(__file__).resolve().parent.parent
SRC = PROJECT / "raw_images"
OUT = PROJECT / "assets"

# 原图 -> (输出子目录, 输出名, 背景类型)
# bg_type: 'white' = 白底泛洪去白, 'dark' = 深色底泛洪去暗
IMAGE_MAP = [
    ("屏幕截图 2026-09-12 214241.png", "small", "idle.png",    "white"),  # 小奶龙 举手
    ("屏幕截图 2026-09-12 214250.png", "small", "happy.png",   "white"),  # 小奶龙 wink吐舌
    ("屏幕截图 2026-09-12 214259.png", "small", "love.png",    "white"),  # 小奶龙 比心
    ("屏幕截图 2026-09-12 214423.png", "big",   "idle.png",    "white"),  # 大奶龙 叉腰
    ("屏幕截图 2026-09-12 214434.png", "big",   "play.png",    "white"),  # 大奶龙 武术
    ("屏幕截图 2026-09-12 214323.png", "big",   "angel.png",   "dark"),   # 大奶龙 天使
]

CANVAS = 320  # 输出画布边长


def crop_bottom_watermark(img: Image.Image) -> Image.Image:
    """裁掉底部约 14% 的水印区域"""
    w, h = img.size
    crop_h = int(h * 0.86)
    return img.crop((0, 0, w, crop_h))


def flood_remove_background(img: Image.Image, bg_type: str) -> Image.Image:
    """
    从四角泛洪，移除背景色。
    white: 移除接近白色的像素（亮度 > 200 且饱和度低）
    dark:  移除接近黑色的像素（亮度 < 60）
    """
    img = img.convert("RGBA")
    w, h = img.size
    pixels = img.load()
    visited = [[False] * h for _ in range(w)]
    to_remove = set()

    def is_bg(x, y):
        r, g, b, a = pixels[x, y]
        if bg_type == "white":
            # 白底：亮度高且颜色接近灰/白（降低阈值以覆盖底部灰色渐变）
            brightness = (r + g + b) / 3
            saturation = max(r, g, b) - min(r, g, b)
            return brightness > 168 and saturation < 55
        else:  # dark
            brightness = (r + g + b) / 3
            return brightness < 75

    # 从四条边的所有像素开始泛洪
    queue = deque()
    for x in range(w):
        for y in (0, h - 1):
            if not visited[x][y] and is_bg(x, y):
                visited[x][y] = True
                queue.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            if not visited[x][y] and is_bg(x, y):
                visited[x][y] = True
                queue.append((x, y))

    while queue:
        x, y = queue.popleft()
        to_remove.add((x, y))
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and not visited[nx][ny] and is_bg(nx, ny):
                visited[nx][ny] = True
                queue.append((nx, ny))

    # 设置透明
    for x, y in to_remove:
        r, g, b, a = pixels[x, y]
        pixels[x, y] = (r, g, b, 0)

    # 边缘半透明过渡：对边界像素做 alpha 羽化
    for x in range(w):
        for y in range(h):
            if pixels[x, y][3] == 0:
                continue
            # 检查邻居是否有透明
            has_transparent_neighbor = False
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and pixels[nx, ny][3] == 0:
                    has_transparent_neighbor = True
                    break
            if has_transparent_neighbor:
                r, g, b, a = pixels[x, y]
                brightness = (r + g + b) / 3
                if bg_type == "white" and brightness > 180:
                    pixels[x, y] = (r, g, b, 80)
                elif bg_type == "dark" and brightness < 90:
                    pixels[x, y] = (r, g, b, 80)

    return img


def trim_and_center(img: Image.Image, canvas_size: int) -> Image.Image:
    """裁剪到内容边界，等比缩放到画布，居中放置"""
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)
    w, h = img.size
    # 等比缩放，留 10% 边距
    target = int(canvas_size * 0.85)
    scale = min(target / w, target / h)
    new_w, new_h = int(w * scale), int(h * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    canvas.paste(img, ((canvas_size - new_w) // 2, (canvas_size - new_h) // 2), img)
    return canvas


def main():
    raw_dir = PROJECT
    # 原始截图在项目根目录
    for src_name, sub_dir, out_name, bg_type in IMAGE_MAP:
        src_path = raw_dir / src_name
        if not src_path.exists():
            print(f"[跳过] 找不到: {src_path}")
            continue
        out_dir = OUT / sub_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / out_name

        img = Image.open(src_path)
        img = crop_bottom_watermark(img)
        img = flood_remove_background(img, bg_type)
        img = trim_and_center(img, CANVAS)
        img.save(out_path, "PNG")
        print(f"[OK] {src_name} -> {out_path}")

    # 生成托盘图标（用小奶龙 idle）
    small_idle = OUT / "small" / "idle.png"
    if small_idle.exists():
        tray = Image.open(small_idle).resize((64, 64), Image.LANCZOS)
        tray.save(OUT / "tray.png", "PNG")
        print(f"[OK] 托盘图标 -> {OUT / 'tray.png'}")

    print("\n全部处理完成！")


if __name__ == "__main__":
    main()
