"""
桌宠主窗口
- 透明无边框窗口
- 拖拽移动
- 呼吸动画
- 状态切换（idle/happy/love/play）
- 歌词气泡
- 互动反馈（点击回弹、抖动）
- 右键菜单
"""
import math
import random
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QPoint, Signal, QUrl
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont, QFontMetrics, QMouseEvent, QCursor
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QMenu, QApplication

from settings import Settings

ASSETS_DIR = Path(__file__).resolve().parent / "assets"

# 每个形态可用的状态图片
FORM_STATES = {
    "small": {
        "idle": "small/idle.png",
        "happy": "small/happy.png",
        "love": "small/love.png",
        "smile": "small/smile.png",
        "shy": "small/shy.png",
        "play": "small/happy.png",   # 复用
    },
    "big": {
        "idle": "big/idle.png",
        "happy": "big/play.png",
        "love": "big/idle.png",      # 复用
        "play": "big/play.png",
        "proud": "big/proud.png",
        "stand": "big/stand.png",
        "think": "big/think.png",
    },
}

# 帧动画（多帧循环）：状态名 -> (帧文件列表, 每帧ms, 是否循环)
FRAME_ANIMS = {
    "laugh": {
        "frames": [f"big/laugh_{i:02d}.png" for i in range(12)],
        "frame_ms": 100,
        "loop": True,
        "sound": "sounds/laugh.wav",
    },
}

# 互动反馈文案
INTERACTION_FEEDBACK = {
    "pet-head": ["好舒服呀~", "再摸摸嘛", "嘿嘿~", "喜欢被摸头"],
    "greet":    ["嗨！", "你好呀~", "今天也加油哦", "见到你真开心"],
    "feed":     ["啊呜~好吃", "谢谢投喂！", "还想要~", "满足！"],
    "flick":    ["嗷！疼！", "干嘛弹我!", "哼！", "再弹就生气了"],
}


class LyricsBubble(QWidget):
    """歌词气泡：在桌宠上方显示歌词"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)
        self.setFixedHeight(60)

    def set_text(self, text: str, auto_hide_ms: int = 0):
        self._text = text
        if text:
            # 根据文字长度调整宽度
            font = QFont("Microsoft YaHei", 10)
            fm = QFontMetrics(font)
            text_width = fm.horizontalAdvance(text)
            self.setFixedWidth(max(120, min(400, text_width + 40)))
            self.update()
            self.show()
            if auto_hide_ms > 0:
                self._hide_timer.start(auto_hide_ms)
            else:
                self._hide_timer.stop()
        else:
            self.hide()

    def paintEvent(self, event):
        if not self._text:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # 气泡背景
        rect = self.rect().adjusted(4, 4, -4, -14)
        painter.setBrush(QColor(255, 255, 255, 235))
        painter.setPen(QColor(255, 170, 80, 200))
        painter.drawRoundedRect(rect, 14, 14)
        # 小三角
        center_x = self.width() // 2
        triangle = [
            QPoint(center_x - 8, rect.bottom()),
            QPoint(center_x + 8, rect.bottom()),
            QPoint(center_x, self.height() - 4),
        ]
        from PySide6.QtGui import QPolygonF
        painter.setBrush(QColor(255, 255, 255, 235))
        painter.drawPolygon(QPolygonF(triangle))
        # 文字
        painter.setPen(QColor(60, 40, 20))
        font = QFont("Microsoft YaHei", 10)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, self._text)


class PetWindow(QWidget):
    """桌宠主窗口"""

    form_switched = Signal(str)          # 形态切换
    interaction_triggered = Signal(str)  # 互动触发
    show_panel_requested = Signal()      # 请求显示控制面板
    quit_requested = Signal()            # 请求退出

    BASE_SIZE = 200

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._form = settings.form
        self._state = "idle"
        self._pixmaps: dict[str, QPixmap] = {}
        self._drag_position: Optional[QPoint] = None
        self._is_dragging = False
        # 动画状态
        self._breath_phase = 0.0
        self._sway_phase = 0.0
        self._bounce_scale = 1.0
        self._shake_offset = QPoint(0, 0)
        self._blink_scale = 1.0       # 眨眼时的垂直压缩
        self._hop_offset = 0          # 蹦跶时的 y 偏移
        # 动作切换过渡（交叉淡入淡出）
        self._prev_pixmap: Optional[QPixmap] = None
        self._transition_t = 1.0      # 0=全旧图, 1=全新图
        self._transition_timer = QTimer(self)
        self._transition_timer.setInterval(16)  # ~60fps
        self._transition_timer.timeout.connect(self._transition_tick)
        self._state_timer = QTimer(self)
        self._state_timer.setSingleShot(True)
        self._state_timer.timeout.connect(self._return_to_idle)

        # 帧动画状态
        self._frame_anim: Optional[dict] = None
        self._frame_anim_frames: list[QPixmap] = []
        self._frame_anim_index = 0
        self._frame_anim_timer = QTimer(self)
        self._frame_anim_timer.timeout.connect(self._frame_anim_tick)
        # 音效
        self._sound_effect = QSoundEffect(self)

        self._setup_window()
        self._load_pixmaps()
        self._setup_animation()

        # 歌词气泡
        self.lyrics_bubble = LyricsBubble()
        self._update_bubble_position()

    def _setup_window(self):
        size = int(self.BASE_SIZE * self.settings.pet_scale)
        self.setFixedSize(size, size)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(QCursor(Qt.PointingHandCursor))

        # 恢复位置
        pos = self.settings.position
        if pos and isinstance(pos, list) and len(pos) == 2:
            self.move(pos[0], pos[1])
        else:
            # 默认右下角
            screen = QApplication.primaryScreen().availableGeometry()
            self.move(screen.width() - size - 40, screen.height() - size - 80)

    def _load_pixmaps(self):
        """加载当前形态的所有状态图片"""
        self._pixmaps.clear()
        states = FORM_STATES.get(self._form, FORM_STATES["small"])
        for state_name, rel_path in states.items():
            path = ASSETS_DIR / rel_path
            if path.exists():
                pm = QPixmap(str(path))
                if not pm.isNull():
                    self._pixmaps[state_name] = pm

    def _setup_animation(self):
        # 主动画定时器（呼吸+摇摆）
        self._breath_timer = QTimer(self)
        self._breath_timer.setInterval(50)
        self._breath_timer.timeout.connect(self._anim_tick)
        self._breath_timer.start()

        # 眨眼定时器（已禁用：无缩放效果下无法模拟眨眼）
        self._blink_timer = QTimer(self)
        self._blink_timer.setSingleShot(True)
        self._blink_timer.timeout.connect(self._do_blink)

        # 自动随机动作定时器（8-18 秒一次）
        self._auto_action_timer = QTimer(self)
        self._auto_action_timer.setSingleShot(True)
        self._auto_action_timer.timeout.connect(self._do_auto_action)
        QTimer.singleShot(random.randint(6000, 12000), self._auto_action_timer.start)

        # 蹦跶定时器（15-30 秒一次）
        self._hop_timer = QTimer(self)
        self._hop_timer.setSingleShot(True)
        self._hop_timer.timeout.connect(self._do_hop)
        QTimer.singleShot(random.randint(12000, 25000), self._hop_timer.start)

    def _anim_tick(self):
        self._breath_phase += 0.04
        if self._breath_phase > 2 * math.pi:
            self._breath_phase -= 2 * math.pi
        self._sway_phase += 0.025
        if self._sway_phase > 2 * math.pi:
            self._sway_phase -= 2 * math.pi
        self.update()

    # ---------- 形态切换 ----------

    def switch_form(self, form: str):
        if form not in FORM_STATES:
            return
        if form == self._form:
            return
        # 停止帧动画
        self._stop_frame_anim()
        # 保存当前图用于过渡
        old_pm = self._pixmaps.get(self._state)
        self._form = form
        self.settings.form = form
        self._load_pixmaps()
        self._state = "idle"
        if old_pm:
            self._prev_pixmap = old_pm
            self._transition_t = 0.0
            self._transition_timer.start()
        self.update()
        self.form_switched.emit(form)

    def get_form(self) -> str:
        return self._form

    # ---------- 状态与互动 ----------

    def set_state(self, state: str, duration_ms: int = 1500):
        """切换到某个状态，持续一段时间后回到 idle（带交叉淡入淡出过渡）"""
        # 停止之前的帧动画
        self._stop_frame_anim()

        # 检查是否是帧动画
        if state in FRAME_ANIMS:
            anim = FRAME_ANIMS[state]
            frames = []
            for rel_path in anim["frames"]:
                path = ASSETS_DIR / rel_path
                if path.exists():
                    pm = QPixmap(str(path))
                    if not pm.isNull():
                        frames.append(pm)
            if frames:
                self._frame_anim = anim
                self._frame_anim_frames = frames
                self._frame_anim_index = 0
                self._frame_anim_timer.setInterval(anim["frame_ms"])
                self._frame_anim_timer.start()
                # 播放音效
                sound_path = ASSETS_DIR / anim["sound"]
                if sound_path.exists():
                    self._sound_effect.setSource(QUrl.fromLocalFile(str(sound_path)))
                    self._sound_effect.setVolume(0.8)
                    self._sound_effect.play()
                self._state = state
                self.update()
                if duration_ms > 0:
                    self._state_timer.start(duration_ms)
                return

        # 单图状态
        if state not in self._pixmaps:
            state = "idle"
        if state == self._state and self._transition_t >= 1.0:
            return
        old_pm = self._pixmaps.get(self._state)
        if old_pm and state != self._state:
            self._prev_pixmap = old_pm
            self._transition_t = 0.0
            self._transition_timer.start()
        self._state = state
        self.update()
        if state != "idle" and duration_ms > 0:
            self._state_timer.start(duration_ms)

    def _frame_anim_tick(self):
        """帧动画推进一帧"""
        if not self._frame_anim_frames:
            return
        self._frame_anim_index += 1
        if self._frame_anim_index >= len(self._frame_anim_frames):
            if self._frame_anim.get("loop", True):
                self._frame_anim_index = 0
            else:
                self._stop_frame_anim()
                return
        self.update()

    def _stop_frame_anim(self):
        """停止帧动画和音效"""
        if self._frame_anim_timer.isActive():
            self._frame_anim_timer.stop()
        self._frame_anim = None
        self._frame_anim_frames = []
        self._frame_anim_index = 0
        if self._sound_effect.isPlaying():
            self._sound_effect.stop()

    def _transition_tick(self):
        """过渡动画帧：250ms 完成交叉淡入淡出"""
        self._transition_t += 0.064  # 16ms * 4 = 每帧前进 6.4%，约16帧=256ms
        if self._transition_t >= 1.0:
            self._transition_t = 1.0
            self._prev_pixmap = None
            self._transition_timer.stop()
        self.update()

    def _return_to_idle(self):
        self.set_state("idle", duration_ms=0)

    def trigger_interaction(self, interaction_id: str):
        """触发互动：切换状态 + 气泡文案 + 动画效果"""
        self.interaction_triggered.emit(interaction_id)

        # 大奶龙摸头 = 大笑帧动画 + 笑声
        if interaction_id == "pet-head" and self._form == "big":
            self.set_state("laugh", duration_ms=4500)
            self._bounce()
            feedbacks = ["哈哈哈哈~", "好舒服！再摸摸~", "嘿嘿嘿~", "喜欢被摸头！"]
            text = random.choice(feedbacks)
            self.show_feedback(text, duration_ms=2000)
            return

        # 状态映射
        state_map = {
            "pet-head": "happy",
            "greet": "love",
            "feed": "happy",
            "flick": "play",
        }
        state = state_map.get(interaction_id, "happy")
        self.set_state(state, duration_ms=1800)

        # 动画效果
        if interaction_id == "flick":
            self._shake()
        else:
            self._bounce()

        # 气泡文案
        feedbacks = INTERACTION_FEEDBACK.get(interaction_id, ["~"])
        text = random.choice(feedbacks)
        self.show_feedback(text, duration_ms=2000)

    def _bounce(self):
        """点击回弹动画（用 QTimer 实现压缩-超调-复位）"""
        self._bounce_scale = 0.85
        self._bounce_frame = 0
        self._bounce_timer = QTimer(self)
        self._bounce_timer.setInterval(25)
        keyframes = [0.85, 0.90, 0.96, 1.02, 1.06, 1.08, 1.06, 1.03, 1.01, 1.0]
        def tick():
            if self._bounce_frame < len(keyframes):
                self._bounce_scale = keyframes[self._bounce_frame]
                self._bounce_frame += 1
                self.update()
            else:
                self._bounce_scale = 1.0
                self._bounce_timer.stop()
                self.update()
        self._bounce_timer.timeout.connect(tick)
        self._bounce_timer.start()

    def _shake(self):
        """抖动动画（弹脑瓜崩）"""
        self._shake_timer = QTimer(self)
        self._shake_count = 0
        self._shake_timer.setInterval(40)
        def tick():
            self._shake_count += 1
            if self._shake_count > 8:
                self._shake_offset = QPoint(0, 0)
                self._shake_timer.stop()
                return
            self._shake_offset = QPoint(
                random.randint(-6, 6), random.randint(-3, 3)
            )
            self.update()
        self._shake_timer.timeout.connect(tick)
        self._shake_timer.start()

    def _do_blink(self):
        """眨眼动画：快速垂直压缩再恢复"""
        if self._state != "idle":
            self._schedule_next_blink()
            return
        frames = [0.65, 0.4, 0.65, 1.0]
        self._blink_frame = 0
        self._blink_anim = QTimer(self)
        self._blink_anim.setInterval(60)
        def tick():
            if self._blink_frame < len(frames):
                self._blink_scale = frames[self._blink_frame]
                self._blink_frame += 1
                self.update()
            else:
                self._blink_scale = 1.0
                self._blink_anim.stop()
                self.update()
                self._schedule_next_blink()
        self._blink_anim.timeout.connect(tick)
        self._blink_anim.start()

    def _schedule_next_blink(self):
        self._blink_timer.start(random.randint(3000, 8000))

    def _do_auto_action(self):
        """自动随机做一个动作（只在 idle 时）"""
        if self._state != "idle":
            self._schedule_next_auto_action()
            return
        available = [s for s in self._pixmaps if s != "idle"]
        if not available:
            self._schedule_next_auto_action()
            return
        action = random.choice(available)
        self.set_state(action, duration_ms=10000)
        # 小蹦跶一下
        self._small_hop()
        self._schedule_next_auto_action()

    def _schedule_next_auto_action(self):
        self._auto_action_timer.start(random.randint(8000, 18000))

    def _do_hop(self):
        """蹦跶动画：跳起再落下"""
        if self._state != "idle":
            self._schedule_next_hop()
            return
        frames = [0, -8, -16, -22, -16, -8, 0]
        self._hop_frame = 0
        self._hop_anim = QTimer(self)
        self._hop_anim.setInterval(55)
        def tick():
            if self._hop_frame < len(frames):
                self._hop_offset = frames[self._hop_frame]
                self._hop_frame += 1
                self.update()
            else:
                self._hop_offset = 0
                self._hop_anim.stop()
                self.update()
                self._schedule_next_hop()
        self._hop_anim.timeout.connect(tick)
        self._hop_anim.start()

    def _small_hop(self):
        """小动作时的轻微蹦跶"""
        frames = [0, -5, -10, -5, 0]
        self._hop_frame = 0
        self._hop_anim = QTimer(self)
        self._hop_anim.setInterval(50)
        def tick():
            if self._hop_frame < len(frames):
                self._hop_offset = frames[self._hop_frame]
                self._hop_frame += 1
                self.update()
            else:
                self._hop_offset = 0
                self._hop_anim.stop()
                self.update()
        self._hop_anim.timeout.connect(tick)
        self._hop_anim.start()

    def _schedule_next_hop(self):
        self._hop_timer.start(random.randint(15000, 30000))

    def show_feedback(self, text: str, duration_ms: int = 2000):
        """在桌宠上方显示反馈气泡"""
        self.lyrics_bubble.set_text(text, auto_hide_ms=duration_ms)
        self._update_bubble_position()

    def show_lyric(self, text: str):
        """显示歌词（持续显示，不自动隐藏）"""
        if not self.settings.get("show_lyrics", True):
            self.lyrics_bubble.hide()
            return
        self.lyrics_bubble.set_text(text, auto_hide_ms=0)
        self._update_bubble_position()

    def hide_lyric(self):
        self.lyrics_bubble.hide()

    def _update_bubble_position(self):
        """把气泡定位到桌宠上方"""
        pet_pos = self.pos()
        bubble_x = pet_pos.x() + (self.width() - self.lyrics_bubble.width()) // 2
        bubble_y = pet_pos.y() - self.lyrics_bubble.height() + 10
        self.lyrics_bubble.move(bubble_x, bubble_y)

    # ---------- 绘制 ----------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.Antialiasing)

        # 帧动画优先使用当前帧
        if self._frame_anim_frames:
            pixmap = self._frame_anim_frames[self._frame_anim_index]
        else:
            pixmap = self._pixmaps.get(self._state, self._pixmaps.get("idle"))
        if not pixmap or pixmap.isNull():
            return

        # 过渡中：先画旧图（渐隐），再画新图（渐显）
        if self._prev_pixmap and self._transition_t < 1.0:
            self._draw_pixmap(painter, self._prev_pixmap, 1.0 - self._transition_t)
            self._draw_pixmap(painter, pixmap, self._transition_t)
        else:
            self._draw_pixmap(painter, pixmap, 1.0)

    def _draw_pixmap(self, painter, pixmap, opacity: float):
        """绘制单张图片，应用摇摆/蹦跶等变换（无任何缩放）"""
        # 左右摇摆（帧动画时不摇摆，避免和动作帧冲突）
        is_static = not self._frame_anim_frames
        sway_angle = math.sin(self._sway_phase) * 3.5 if is_static else 0.0
        sway_x = math.sin(self._sway_phase) * 3.5 if is_static else 0.0

        # 点击回弹用上下位移代替缩放
        bounce_y = int((1.0 - self._bounce_scale) * 12)

        scale_x = 1.0
        scale_y = 1.0

        base_w = int(self.width() * 0.92)
        base_h = int(self.height() * 0.92)
        target_w = int(base_w * scale_x)
        target_h = int(base_h * scale_y)

        scaled = pixmap.scaled(
            target_w, target_h,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )

        x = (self.width() - target_w) // 2 + int(sway_x) + self._shake_offset.x()
        y = self.height() - target_h - int(self.height() * 0.02) + self._hop_offset + bounce_y + self._shake_offset.y()

        center_x = x + target_w // 2
        center_y = y + target_h

        painter.save()
        painter.setOpacity(opacity)
        painter.translate(center_x, center_y)
        painter.rotate(sway_angle)
        painter.translate(-center_x, -center_y)
        painter.drawPixmap(x, y, scaled)
        painter.restore()

    # ---------- 鼠标事件 ----------

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._is_dragging = False
        elif event.button() == Qt.RightButton:
            self._show_context_menu(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_position and event.buttons() & Qt.LeftButton:
            delta = event.globalPosition().toPoint() - self.frameGeometry().topLeft() - self._drag_position
            if delta.manhattanLength() > 4:
                self._is_dragging = True
            if self._is_dragging:
                self.move(event.globalPosition().toPoint() - self._drag_position)
                self._update_bubble_position()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            if not self._is_dragging:
                # 点击 = 摸头互动
                self.trigger_interaction("pet-head")
            else:
                # 保存位置
                self.settings.position = [self.x(), self.y()]
            self._drag_position = None
            self._is_dragging = False

    def _show_context_menu(self, global_pos: QPoint):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #FFF8F0;
                border: 1px solid #FFB366;
                border-radius: 8px;
                padding: 4px;
                font-family: "Microsoft YaHei";
                font-size: 13px;
            }
            QMenu::item {
                padding: 6px 24px;
                border-radius: 4px;
                color: #5A3A1A;
            }
            QMenu::item:selected {
                background-color: #FFE0B3;
            }
            QMenu::separator {
                height: 1px;
                background: #FFD699;
                margin: 4px 8px;
            }
        """)

        # 形态切换
        form_menu = menu.addMenu("🔄 切换形态")
        small_action = form_menu.addAction("🐣 小奶龙")
        big_action = form_menu.addAction("🐲 大奶龙")
        small_action.setCheckable(True)
        big_action.setCheckable(True)
        small_action.setChecked(self._form == "small")
        big_action.setChecked(self._form == "big")
        small_action.triggered.connect(lambda: self.switch_form("small"))
        big_action.triggered.connect(lambda: self.switch_form("big"))

        menu.addSeparator()

        # 互动
        menu.addAction("💗 摸摸头", lambda: self.trigger_interaction("pet-head"))
        menu.addAction("👋 打招呼", lambda: self.trigger_interaction("greet"))
        menu.addAction("🍼 递水", lambda: self.trigger_interaction("feed"))
        menu.addAction("👆 弹脑瓜崩", lambda: self.trigger_interaction("flick"))

        menu.addSeparator()
        menu.addAction("🎵 音乐面板", self.show_panel_requested.emit)
        menu.addAction("⚙️ 设置", self.show_panel_requested.emit)
        menu.addSeparator()
        menu.addAction("🚪 退出", self.quit_requested.emit)

        menu.exec(global_pos)

    # ---------- 缩放 ----------

    def set_scale(self, scale: float):
        self.settings.pet_scale = scale
        size = int(self.BASE_SIZE * scale)
        self.setFixedSize(size, size)
        self.update()

    def closeEvent(self, event):
        self.lyrics_bubble.close()
        super().closeEvent(event)
