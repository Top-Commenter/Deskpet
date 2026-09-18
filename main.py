"""
奶龙桌宠 - 主入口
- 自动启动本地网易云 API 服务
- 系统托盘
- 桌宠窗口
- 控制面板
- 网易云音乐
"""
import subprocess
import sys
import time
from pathlib import Path

import requests
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap, QAction
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu

from settings import Settings
from netease_api import NeteaseAPI
from music_player import MusicPlayer
from pet_window import PetWindow
from control_panel import ControlPanel

PROJECT_DIR = Path(__file__).resolve().parent
ASSETS_DIR = PROJECT_DIR / "assets"
CONFIG_DIR = PROJECT_DIR / "data"
API_PORT = 3000


def _is_api_online() -> bool:
    try:
        resp = requests.get(f"http://localhost:{API_PORT}/", timeout=2)
        return resp.status_code == 200
    except Exception:
        return False


def _start_api_service() -> Optional[subprocess.Popen]:
    """启动本地 NeteaseCloudMusicApi 服务"""
    if _is_api_online():
        return None
    api_script = PROJECT_DIR / "node_modules" / "NeteaseCloudMusicApi" / "app.js"
    if not api_script.exists():
        return None
    proc = subprocess.Popen(
        ["node", str(api_script)],
        cwd=str(PROJECT_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    # 等待服务就绪，最多 15 秒
    for _ in range(30):
        time.sleep(0.5)
        if _is_api_online():
            return proc
    return proc


class DesktopPetApp:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.app.setApplicationName("奶龙桌宠")

        # 启动本地网易云 API 服务
        self._api_proc = _start_api_service()

        # 初始化组件
        self.settings = Settings(CONFIG_DIR)
        self.api = NeteaseAPI(cookie_path=CONFIG_DIR / "netease_cookies.json")
        self.player = MusicPlayer(self.api)
        self.pet = PetWindow(self.settings)
        self.panel = ControlPanel(self.api, self.player, self.settings)

        self._connect_signals()
        self._create_tray()

        # 恢复音量
        self.player.set_volume(self.settings.volume)

    def _connect_signals(self):
        # 桌宠 -> 应用
        self.pet.form_switched.connect(self._on_form_switched)
        self.pet.interaction_triggered.connect(self._on_interaction)
        self.pet.show_panel_requested.connect(self._show_panel)
        self.pet.quit_requested.connect(self._quit)

        # 面板 -> 应用
        self.panel.form_changed.connect(self.pet.switch_form)
        self.panel.scale_changed.connect(self.pet.set_scale)
        self.panel.always_on_top_changed.connect(self._on_always_on_top)
        self.panel.show_lyrics_changed.connect(self._on_show_lyrics)
        self.panel.quit_requested.connect(self._quit)

        # 音乐播放器 -> 桌宠歌词
        self.player.lyric_changed.connect(self.pet.show_lyric)
        self.player.state_changed.connect(self._on_music_state)

    def _create_tray(self):
        tray_icon_path = ASSETS_DIR / "tray.png"
        icon = QIcon(str(tray_icon_path)) if tray_icon_path.exists() else QIcon()
        self.tray = QSystemTrayIcon(icon, self.app)
        self.tray.setToolTip("奶龙桌宠")

        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background-color: #FFF8F0; border: 1px solid #FFB366;
                border-radius: 8px; padding: 4px;
                font-family: 'Microsoft YaHei'; font-size: 13px;
            }
            QMenu::item { padding: 6px 24px; border-radius: 4px; color: #5A3A1A; }
            QMenu::item:selected { background-color: #FFE0B3; }
            QMenu::separator { height: 1px; background: #FFD699; margin: 4px 8px; }
        """)

        show_pet_action = QAction("🐾 显示桌宠", self.app)
        show_pet_action.triggered.connect(self.pet.show)
        menu.addAction(show_pet_action)

        panel_action = QAction("🏠 打开小屋", self.app)
        panel_action.triggered.connect(self._show_panel)
        menu.addAction(panel_action)

        menu.addSeparator()

        # 形态切换
        form_menu = menu.addMenu("🔄 切换形态")
        small_action = QAction("🐣 小奶龙", self.app)
        big_action = QAction("🐲 大奶龙", self.app)
        small_action.triggered.connect(lambda: self.pet.switch_form("small"))
        big_action.triggered.connect(lambda: self.pet.switch_form("big"))
        form_menu.addAction(small_action)
        form_menu.addAction(big_action)

        menu.addSeparator()

        # 音乐控制
        play_action = QAction("▶️ 播放/暂停", self.app)
        play_action.triggered.connect(self.player.toggle)
        menu.addAction(play_action)

        next_action = QAction("⏭️ 下一首", self.app)
        next_action.triggered.connect(self.player.next)
        menu.addAction(next_action)

        menu.addSeparator()

        quit_action = QAction("🚪 退出", self.app)
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            # 左键单击 = 显示/隐藏桌宠
            if self.pet.isVisible():
                self.pet.hide()
                self.pet.hide_lyric()
            else:
                self.pet.show()

    def _show_panel(self):
        self.panel.refresh_stats()
        self.panel.show()
        self.panel.raise_()
        self.panel.activateWindow()

    def _on_form_switched(self, form: str):
        # 同步面板下拉框
        index = 0 if form == "small" else 1
        self.panel.form_combo.setCurrentIndex(index)
        self.pet.show_feedback("变成小奶龙啦~" if form == "small" else "变成大奶龙啦~", 1500)

    def _on_interaction(self, interaction_id: str):
        gains = {"pet-head": 2, "greet": 1, "feed": 3, "flick": -1}
        self.settings.add_interaction(gains.get(interaction_id, 1))
        self.panel.refresh_stats()

    def _on_always_on_top(self, on_top: bool):
        flags = self.pet.windowFlags()
        if on_top:
            flags |= Qt.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowStaysOnTopHint
        self.pet.setWindowFlags(flags)
        self.pet.show()

    def _on_show_lyrics(self, show: bool):
        if not show:
            self.pet.hide_lyric()

    def _on_music_state(self, state: str):
        if state == "stopped":
            self.pet.hide_lyric()

    def _quit(self):
        self.player.stop()
        self.pet.close()
        self.panel.close()
        self.tray.hide()
        # 关闭本地 API 服务
        if self._api_proc:
            try:
                self._api_proc.terminate()
                self._api_proc.wait(timeout=3)
            except Exception:
                try:
                    self._api_proc.kill()
                except Exception:
                    pass
        self.app.quit()

    def run(self):
        self.pet.show()
        # 欢迎气泡
        self.pet.show_feedback("嗨！我是奶龙~", 2500)
        sys.exit(self.app.exec())


def main():
    app = DesktopPetApp()
    app.run()


if __name__ == "__main__":
    main()
