"""
从视频中提取大奶龙大笑动作帧：
1. 裁剪掉顶部状态栏和底部UI
2. 均匀提取一个循环的关键帧
3. 泛洪去背景
4. 统一尺寸
"""
import cv2
import numpy as np
from PIL import Image
from collections import deque
from pathlib import Path

VIDEO = r"D:\Downloads\douyin\@睡神olo 666，疑似软件被泄漏了 720P.mp4"
OUT_DIR = Path(r"D:\github\Deskpet\assets\big")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 裁剪区域：去掉顶部状态栏(0-110)和底部UI(1380-1560)
CROP_TOP = 110
CROP_BOTTOM = 1380
# 提取帧数（一个循环大约 5-6 秒，视频18.7秒约3个循环）
NUM_FRAMES = 12
CANVAS = 320


def flood_remove_bg(img: Image.Image, tolerance: int = 40) -> Image.Image:
    arr = np.array(img.convert("RGBA"))
    h, w = arr.shape[:2]
    visited = np.zeros((h, w), dtype=bool)

    seeds = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    seeds += [(w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2)]
    seeds += [(w // 4, 0), (3 * w // 4, 0), (w // 4, h - 1), (3 * w // 4, h - 1)]

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

    # 清理半透明残留和阴影（底部灰色阴影）
    arr[arr[:, :, 3] < 120, 3] = 0
    # 去除底部阴影：alpha 低且颜色偏灰的区域
    gray_mask = (arr[:, :, 3] > 0) & (arr[:, :, 3] < 200) & \
                (np.abs(arr[:, :, 0].astype(int) - arr[:, :, 1].astype(int)) < 15) & \
                (np.abs(arr[:, :, 1].astype(int) - arr[:, :, 2].astype(int)) < 15) & \
                (arr[:, :, 0] < 200)
    arr[gray_mask, 3] = 0

    return Image.fromarray(arr, "RGBA")


def trim_and_center(img: Image.Image, canvas_size: int = CANVAS) -> Image.Image:
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
    scale = canvas_size * 0.9 / max(cw, ch)
    new_w, new_h = int(cw * scale), int(ch * scale)
    resized = cropped.resize((new_w, new_h), Image.LANCZOS)

    canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    offset_x = (canvas_size - new_w) // 2
    offset_y = canvas_size - new_h - int(canvas_size * 0.04)
    canvas.paste(resized, (offset_x, offset_y), resized)
    return canvas


def main():
    cap = cv2.VideoCapture(VIDEO)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    print(f"Total frames: {total}, FPS: {fps}")

    # 提取一个循环的帧：从第 30 帧到第 200 帧（约 0-5.7秒，一个完整循环）
    # 均匀提取 NUM_FRAMES 帧
    start_frame = 30
    end_frame = 210
    frame_indices = [int(start_frame + (end_frame - start_frame) * i / (NUM_FRAMES - 1))
                     for i in range(NUM_FRAMES)]

    for i, idx in enumerate(frame_indices):
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if not ret:
            print(f"Frame {idx} failed")
            continue

        # BGR -> RGB
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        # 裁剪
        cropped = frame_rgb[CROP_TOP:CROP_BOTTOM, :, :]
        img = Image.fromarray(cropped)

        # 去背景
        img = flood_remove_bg(img)
        # 统一尺寸
        img = trim_and_center(img)

        out_path = OUT_DIR / f"laugh_{i:02d}.png"
        img.save(out_path, "PNG")
        print(f"Saved laugh_{i:02d}.png (frame {idx}, {idx/fps:.2f}s)")

    cap.release()
    print(f"Done. {NUM_FRAMES} frames saved to {OUT_DIR}")


if __name__ == "__main__":
    main()
