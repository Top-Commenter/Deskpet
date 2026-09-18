"""
控制面板（小屋）
- 网易云扫码登录
- 搜索歌曲 / 歌单
- 播放控制（播放/暂停/上一首/下一首）
- 音量调节
- 进度条
- 设置（形态、缩放、置顶、歌词开关）
- 互动统计
"""
import base64
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal, QSize
from PySide6.QtGui import QPixmap, QFont, QIcon, QImage
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QListWidget, QListWidgetItem, QSlider, QProgressBar, QTabWidget,
    QFormLayout, QCheckBox, QComboBox, QGroupBox, QScrollArea, QFrame
)

from netease_api import NeteaseAPI
from music_player import MusicPlayer
from settings import Settings


class ControlPanel(QWidget):
    """控制面板"""

    form_changed = Signal(str)
    scale_changed = Signal(float)
    always_on_top_changed = Signal(bool)
    show_lyrics_changed = Signal(bool)
    quit_requested = Signal()

    def __init__(self, api: NeteaseAPI, player: MusicPlayer, settings: Settings, parent=None):
        super().__init__(parent)
        self.api = api
        self.player = player
        self.settings = settings
        self._qr_key = ""
        self._qr_check_timer = QTimer(self)
        self._qr_check_timer.setInterval(2000)
        self._qr_check_timer.timeout.connect(self._check_qr_status)

        self._setup_ui()
        self._connect_signals()
        self._update_login_status()

    def _setup_ui(self):
        self.setWindowTitle("奶龙的小屋")
        self.setFixedSize(480, 640)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)

        # 外层容器（圆角卡片）
        self.container = QFrame(self)
        self.container.setObjectName("container")
        self.container.setGeometry(10, 10, 460, 620)
        self.container.setStyleSheet("""
            #container {
                background-color: #FFF8F0;
                border: 2px solid #FFB366;
                border-radius: 20px;
            }
        """)

        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        # 标题栏
        title_bar = QHBoxLayout()
        title = QLabel("🐲 奶龙的小屋")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #8B4513; font-family: 'Microsoft YaHei';")
        title_bar.addWidget(title)
        title_bar.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet("QPushButton { background: #FF6B6B; color: white; border-radius: 14px; font-weight: bold; } QPushButton:hover { background: #FF5252; }")
        close_btn.clicked.connect(self.hide)
        title_bar.addWidget(close_btn)
        layout.addLayout(title_bar)

        # 标签页
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #FFD699; border-radius: 8px; background: #FFFEFA; }
            QTabBar::tab {
                background: #FFE8CC; color: #8B4513; padding: 6px 16px;
                border-top-left-radius: 8px; border-top-right-radius: 8px;
                font-family: 'Microsoft YaHei'; font-size: 12px;
            }
            QTabBar::tab:selected { background: #FFB366; color: white; }
        """)
        layout.addWidget(self.tabs)

        self.tabs.addTab(self._create_music_tab(), "🎵 音乐")
        self.tabs.addTab(self._create_settings_tab(), "⚙️ 设置")
        self.tabs.addTab(self._create_about_tab(), "💝 关于")

    def _create_music_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)

        # 登录状态
        self.login_label = QLabel("未登录")
        self.login_label.setStyleSheet("color: #8B4513; font-family: 'Microsoft YaHei'; font-size: 12px;")
        login_row = QHBoxLayout()
        login_row.addWidget(self.login_label)
        login_row.addStretch()
        self.login_btn = QPushButton("扫码登录")
        self.login_btn.setStyleSheet(self._btn_style("#4CAF50"))
        self.login_btn.clicked.connect(self._start_qr_login)
        self.logout_btn = QPushButton("退出登录")
        self.logout_btn.setStyleSheet(self._btn_style("#999"))
        self.logout_btn.clicked.connect(self._logout)
        self.logout_btn.hide()
        login_row.addWidget(self.login_btn)
        login_row.addWidget(self.logout_btn)
        layout.addLayout(login_row)

        # 二维码显示区
        self.qr_label = QLabel("扫码后点上方按钮")
        self.qr_label.setAlignment(Qt.AlignCenter)
        self.qr_label.setFixedHeight(160)
        self.qr_label.setStyleSheet("background: white; border: 1px solid #FFD699; border-radius: 8px; color: #999;")
        self.qr_label.hide()
        layout.addWidget(self.qr_label)

        # 搜索
        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索歌曲...")
        self.search_input.setStyleSheet("QLineEdit { border: 1px solid #FFD699; border-radius: 6px; padding: 6px; font-family: 'Microsoft YaHei'; }")
        self.search_input.returnPressed.connect(self._do_search)
        search_btn = QPushButton("🔍")
        search_btn.setFixedWidth(40)
        search_btn.setStyleSheet(self._btn_style("#FFB366"))
        search_btn.clicked.connect(self._do_search)
        search_row.addWidget(self.search_input)
        search_row.addWidget(search_btn)
        layout.addLayout(search_row)

        # 搜索结果列表
        self.song_list = QListWidget()
        self.song_list.setStyleSheet("""
            QListWidget { border: 1px solid #FFD699; border-radius: 8px; background: white; font-family: 'Microsoft YaHei'; font-size: 12px; }
            QListWidget::item { padding: 6px; border-bottom: 1px solid #FFF0E0; }
            QListWidget::item:selected { background: #FFE0B3; color: #8B4513; }
        """)
        self.song_list.itemDoubleClicked.connect(self._play_selected)
        layout.addWidget(self.song_list, 1)

        # 当前歌曲
        self.current_song_label = QLabel("暂无播放")
        self.current_song_label.setStyleSheet("color: #8B4513; font-weight: bold; font-family: 'Microsoft YaHei'; font-size: 12px;")
        self.current_song_label.setWordWrap(True)
        layout.addWidget(self.current_song_label)

        # 进度条
        self.progress = QSlider(Qt.Horizontal)
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setStyleSheet("QSlider::groove:horizontal { height: 4px; background: #FFE0B3; border-radius: 2px; } QSlider::handle:horizontal { width: 12px; height: 12px; background: #FF8A24; border-radius: 6px; margin: -4px 0; }")
        layout.addWidget(self.progress)

        # 播放控制
        ctrl_row = QHBoxLayout()
        self.prev_btn = QPushButton("⏮")
        self.play_btn = QPushButton("▶")
        self.next_btn = QPushButton("⏭")
        for btn in (self.prev_btn, self.play_btn, self.next_btn):
            btn.setFixedSize(44, 44)
            btn.setStyleSheet("QPushButton { background: #FFB366; color: white; border-radius: 22px; font-size: 18px; } QPushButton:hover { background: #FFA040; }")
        self.prev_btn.clicked.connect(self.player.previous)
        self.play_btn.clicked.connect(self.player.toggle)
        self.next_btn.clicked.connect(self.player.next)
        ctrl_row.addStretch()
        ctrl_row.addWidget(self.prev_btn)
        ctrl_row.addWidget(self.play_btn)
        ctrl_row.addWidget(self.next_btn)
        ctrl_row.addStretch()
        layout.addLayout(ctrl_row)

        # 音量
        vol_row = QHBoxLayout()
        vol_label = QLabel("🔊")
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(self.settings.volume)
        self.volume_slider.setStyleSheet("QSlider::groove:horizontal { height: 4px; background: #FFE0B3; border-radius: 2px; } QSlider::handle:horizontal { width: 10px; height: 10px; background: #FF8A24; border-radius: 5px; margin: -3px 0; }")
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        vol_row.addWidget(vol_label)
        vol_row.addWidget(self.volume_slider)
        layout.addLayout(vol_row)

        return widget

    def _create_settings_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)

        # 形态设置
        form_group = QGroupBox("角色形态")
        form_group.setStyleSheet("QGroupBox { font-family: 'Microsoft YaHei'; color: #8B4513; font-weight: bold; border: 1px solid #FFD699; border-radius: 8px; margin-top: 8px; padding-top: 12px; }")
        form_layout = QFormLayout(form_group)
        self.form_combo = QComboBox()
        self.form_combo.addItem("🐣 小奶龙", "small")
        self.form_combo.addItem("🐲 大奶龙", "big")
        self.form_combo.setCurrentIndex(0 if self.settings.form == "small" else 1)
        self.form_combo.currentIndexChanged.connect(self._on_form_changed)
        form_layout.addRow("当前形态:", self.form_combo)
        layout.addWidget(form_group)

        # 显示设置
        display_group = QGroupBox("显示设置")
        display_group.setStyleSheet("QGroupBox { font-family: 'Microsoft YaHei'; color: #8B4513; font-weight: bold; border: 1px solid #FFD699; border-radius: 8px; margin-top: 8px; padding-top: 12px; }")
        display_layout = QVBoxLayout(display_group)

        scale_row = QHBoxLayout()
        scale_row.addWidget(QLabel("桌宠大小:"))
        self.scale_slider = QSlider(Qt.Horizontal)
        self.scale_slider.setRange(50, 200)
        self.scale_slider.setValue(int(self.settings.pet_scale * 100))
        self.scale_slider.valueChanged.connect(self._on_scale_changed)
        self.scale_value_label = QLabel(f"{int(self.settings.pet_scale * 100)}%")
        scale_row.addWidget(self.scale_slider, 1)
        scale_row.addWidget(self.scale_value_label)
        display_layout.addLayout(scale_row)

        self.always_on_top_check = QCheckBox("窗口置顶")
        self.always_on_top_check.setChecked(self.settings.always_on_top)
        self.always_on_top_check.stateChanged.connect(self._on_always_on_top_changed)
        display_layout.addWidget(self.always_on_top_check)

        self.show_lyrics_check = QCheckBox("显示歌词气泡")
        self.show_lyrics_check.setChecked(self.settings.get("show_lyrics", True))
        self.show_lyrics_check.stateChanged.connect(self._on_show_lyrics_changed)
        display_layout.addWidget(self.show_lyrics_check)

        layout.addWidget(display_group)

        # 统计
        stats_group = QGroupBox("陪伴统计")
        stats_group.setStyleSheet("QGroupBox { font-family: 'Microsoft YaHei'; color: #8B4513; font-weight: bold; border: 1px solid #FFD699; border-radius: 8px; margin-top: 8px; padding-top: 12px; }")
        stats_layout = QFormLayout(stats_group)
        self.affection_label = QLabel(str(self.settings.get_stats("affection", 0)))
        self.interactions_label = QLabel(str(self.settings.get_stats("total_interactions", 0)))
        stats_layout.addRow("好感度:", self.affection_label)
        stats_layout.addRow("互动次数:", self.interactions_label)
        layout.addWidget(stats_group)

        layout.addStretch()
        return widget

    def _create_about_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignCenter)

        info = QLabel(
            "🐲 奶龙桌宠 v1.0\n\n"
            "一只住在你桌面的奶龙\n"
            "可以陪你互动、放歌、显示歌词\n\n"
            "左键点击 = 摸头\n"
            "右键 = 菜单\n"
            "拖动 = 移动位置\n\n"
            "小奶龙 / 大奶龙可随时切换\n"
            "网易云音乐扫码登录后可播放\n\n"
            "素材来源：用户提供，仅供个人使用"
        )
        info.setAlignment(Qt.AlignCenter)
        info.setStyleSheet("color: #8B4513; font-family: 'Microsoft YaHei'; font-size: 13px; line-height: 1.8;")
        layout.addWidget(info)
        return widget

    def _btn_style(self, color: str) -> str:
        return f"""
            QPushButton {{
                background: {color}; color: white; border: none;
                border-radius: 6px; padding: 6px 14px;
                font-family: 'Microsoft YaHei'; font-size: 12px;
            }}
            QPushButton:hover {{ background: {color}; opacity: 0.85; }}
        """

    def _connect_signals(self):
        self.player.song_changed.connect(self._on_song_changed)
        self.player.state_changed.connect(self._on_play_state)
        self.player.position_changed.connect(self._on_position)
        self.player.duration_changed.connect(self._on_duration)
        self.player.lyric_changed.connect(self._on_lyric)
        self.player.error_occurred.connect(self._on_error)
        self.player.buffering_changed.connect(self._on_buffering)
        self.progress.sliderMoved.connect(self._on_seek)

    # ---------- 登录 ----------

    def _update_login_status(self):
        if self.api.is_logged_in():
            self.login_label.setText(f"✅ 已登录: {self.api.nickname}")
            self.login_btn.hide()
            self.logout_btn.show()
            self.qr_label.hide()
            self._qr_check_timer.stop()
        else:
            self.login_label.setText("❌ 未登录（登录后可播放VIP歌曲和歌单）")
            self.login_btn.show()
            self.logout_btn.hide()

    def _start_qr_login(self):
        try:
            self._qr_key = self.api.get_qr_key()
            qr_b64 = self.api.get_qr_image(self._qr_key)
            if qr_b64:
                qr_data = base64.b64decode(qr_b64)
                qr_pix = QPixmap()
                qr_pix.loadFromData(qr_data)
                self.qr_label.setPixmap(qr_pix.scaled(140, 140, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                self.qr_label.show()
                self._qr_check_timer.start()
        except Exception as e:
            self.qr_label.setText(f"获取二维码失败: {e}")
            self.qr_label.show()

    def _check_qr_status(self):
        try:
            result = self.api.check_qr_status(self._qr_key)
            code = result.get("code", 0)
            if code == 803:
                self._update_login_status()
                self._qr_check_timer.stop()
            elif code == 800:
                self.qr_label.setText("二维码已过期，请重新获取")
                self._qr_check_timer.stop()
            elif code == 802:
                self.qr_label.setText("已扫码，请在手机上确认")
        except Exception:
            pass

    def _logout(self):
        self.api.logout()
        self._update_login_status()

    # ---------- 搜索与播放 ----------

    def _do_search(self):
        keyword = self.search_input.text().strip()
        if not keyword:
            return
        self.song_list.clear()
        self.song_list.addItem("搜索中...")
        QTimer.singleShot(50, lambda: self._do_search_actual(keyword))

    def _do_search_actual(self, keyword: str):
        try:
            songs = self.api.search(keyword)
            self.song_list.clear()
            for song in songs:
                text = f"{song['name']} - {song['artist']}"
                item = QListWidgetItem(text)
                item.setData(Qt.UserRole, song)
                self.song_list.addItem(item)
            if not songs:
                self.song_list.addItem("未找到相关歌曲")
        except Exception as e:
            self.song_list.clear()
            self.song_list.addItem(f"搜索失败: {e}")

    def _play_selected(self, item: QListWidgetItem):
        song = item.data(Qt.UserRole)
        if not song:
            return
        # 将当前搜索结果作为播放列表
        playlist = []
        for i in range(self.song_list.count()):
            s = self.song_list.item(i).data(Qt.UserRole)
            if s:
                playlist.append(s)
        if playlist:
            idx = playlist.index(song) if song in playlist else 0
            self.player.set_playlist(playlist, idx)

    def _on_song_changed(self, song: dict):
        self.current_song_label.setText(f"▶ {song['name']} - {song['artist']}")

    def _on_play_state(self, state: str):
        if state == "playing":
            self.play_btn.setText("⏸")
        else:
            self.play_btn.setText("▶")

    def _on_position(self, pos_ms: int):
        duration = self.player.get_duration_ms()
        if duration > 0:
            self.progress.setValue(int(pos_ms / duration * 1000))

    def _on_duration(self, duration_ms: int):
        pass

    def _on_lyric(self, text: str):
        # 歌词由主窗口显示，这里不处理
        pass

    def _on_buffering(self, buffering: bool):
        if buffering and self.player.get_current_song():
            song = self.player.get_current_song()
            self.current_song_label.setText(f"⏳ 缓冲中... {song['name']} - {song['artist']}")
        elif not buffering and self.player.get_current_song():
            song = self.player.get_current_song()
            self.current_song_label.setText(f"▶ {song['name']} - {song['artist']}")

    def _on_error(self, msg: str):
        self.current_song_label.setText(f"⚠️ {msg}")

    def _on_seek(self, value: int):
        duration = self.player.get_duration_ms()
        if duration > 0:
            self.player.set_position(int(value / 1000 * duration))

    def _on_volume_changed(self, value: int):
        self.player.set_volume(value)
        self.settings.volume = value

    # ---------- 设置 ----------

    def _on_form_changed(self, index: int):
        form = self.form_combo.itemData(index)
        self.form_changed.emit(form)

    def _on_scale_changed(self, value: int):
        scale = value / 100.0
        self.scale_value_label.setText(f"{value}%")
        self.scale_changed.emit(scale)

    def _on_always_on_top_changed(self, state: int):
        self.settings.always_on_top = (state == 2)
        self.always_on_top_changed.emit(self.settings.always_on_top)

    def _on_show_lyrics_changed(self, state: int):
        show = (state == 2)
        self.settings.set("show_lyrics", show)
        self.show_lyrics_changed.emit(show)

    def refresh_stats(self):
        self.affection_label.setText(str(self.settings.get_stats("affection", 0)))
        self.interactions_label.setText(str(self.settings.get_stats("total_interactions", 0)))

    # ---------- 拖动 ----------

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and hasattr(self, '_drag_pos'):
            self.move(event.globalPosition().toPoint() - self._drag_pos)
