"""
音乐播放器模块
- 使用 QtMultimedia 播放音频
- 歌词同步
- 播放列表管理
- 异常中断自动重试
- 缓冲状态处理
"""
from typing import Optional
from PySide6.QtCore import QObject, QTimer, Signal, QUrl
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

from netease_api import NeteaseAPI


class MusicPlayer(QObject):
    """音乐播放器：管理播放、暂停、切歌、歌词同步"""

    state_changed = Signal(str)          # playing/paused/stopped
    song_changed = Signal(dict)          # 当前歌曲信息
    lyric_changed = Signal(str)          # 当前歌词行
    position_changed = Signal(int)       # 当前位置 ms
    duration_changed = Signal(int)       # 总时长 ms
    volume_changed = Signal(int)         # 音量 0-100
    error_occurred = Signal(str)         # 错误信息
    buffering_changed = Signal(bool)     # 缓冲中状态

    MAX_RETRIES = 3

    def __init__(self, api: NeteaseAPI, parent=None):
        super().__init__(parent)
        self.api = api
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(0.7)

        self.playlist: list = []
        self.current_index = -1
        self.current_song: Optional[dict] = None
        self.lyrics: list = []  # [(time_sec, text), ...]
        self._current_lyric_idx = -1
        self._retry_count = 0
        self._is_buffering = False
        self._expected_duration = 0  # 歌曲期望时长 ms（来自搜索结果）

        # 信号连接
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.playbackStateChanged.connect(self._on_state)
        self.player.errorOccurred.connect(self._on_error)
        self.player.mediaStatusChanged.connect(self._on_media_status)

        # 歌词定时器（每 200ms 检查一次）
        self.lyric_timer = QTimer(self)
        self.lyric_timer.setInterval(200)
        self.lyric_timer.timeout.connect(self._update_lyric)

        # 缓冲恢复定时器（Stalled 后 10 秒没恢复则重试）
        self._stall_timer = QTimer(self)
        self._stall_timer.setSingleShot(True)
        self._stall_timer.timeout.connect(self._on_stall_timeout)

    # ---------- 播放控制 ----------

    def set_playlist(self, songs: list, start_index: int = 0):
        """设置播放列表并开始播放"""
        self.playlist = songs
        if songs:
            self.play_at(start_index)

    def play_at(self, index: int):
        """播放指定索引的歌曲"""
        if not self.playlist or index < 0 or index >= len(self.playlist):
            return
        self.current_index = index
        self.current_song = self.playlist[index]
        self._expected_duration = self.current_song.get("duration", 0)
        self._retry_count = 0
        self.song_changed.emit(self.current_song)
        self._load_and_play(self.current_song["id"])

    def _load_and_play(self, song_id: str):
        """获取播放地址并播放"""
        try:
            url = self.api.get_song_url(song_id)
            if not url:
                self.error_occurred.emit("无法获取播放地址（可能需要 VIP 或登录）")
                return
            self.player.setSource(QUrl(url))
            self.player.play()
            # 歌词异步获取，不阻塞播放
            QTimer.singleShot(100, lambda: self._fetch_lyrics(song_id))
        except Exception as e:
            self.error_occurred.emit(f"播放失败: {e}")

    def _fetch_lyrics(self, song_id: str):
        """异步获取歌词"""
        try:
            self.lyrics = self.api.get_lyric(song_id)
            self._current_lyric_idx = -1
            self.lyric_timer.start()
        except Exception:
            self.lyrics = []

    def _retry_current(self):
        """重试当前歌曲"""
        if self._retry_count >= self.MAX_RETRIES:
            self.error_occurred.emit("当前歌曲播放失败多次，自动跳过")
            self._retry_count = 0
            QTimer.singleShot(500, self.next)
            return
        self._retry_count += 1
        self.error_occurred.emit(f"播放中断，正在重试 ({self._retry_count}/{self.MAX_RETRIES})...")
        if self.current_song:
            QTimer.singleShot(800, lambda: self._load_and_play(self.current_song["id"]))

    def play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PausedState:
            self.player.play()
        elif self.current_song:
            self.player.play()

    def pause(self):
        self.player.pause()

    def toggle(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.pause()
        else:
            self.play()

    def next(self):
        if not self.playlist:
            return
        self._retry_count = 0
        idx = (self.current_index + 1) % len(self.playlist)
        self.play_at(idx)

    def previous(self):
        if not self.playlist:
            return
        self._retry_count = 0
        idx = (self.current_index - 1) % len(self.playlist)
        self.play_at(idx)

    def stop(self):
        self.player.stop()
        self.lyric_timer.stop()
        self._stall_timer.stop()
        self.lyrics = []
        self._current_lyric_idx = -1
        self._retry_count = 0
        self.lyric_changed.emit("")
        self.state_changed.emit("stopped")

    def set_position(self, position_ms: int):
        self.player.setPosition(position_ms)

    def set_volume(self, volume: int):
        """volume: 0-100"""
        self.audio_output.setVolume(max(0, min(100, volume)) / 100.0)
        self.volume_changed.emit(volume)

    def get_volume(self) -> int:
        return int(self.audio_output.volume() * 100)

    # ---------- 内部槽 ----------

    def _on_position(self, position_ms: int):
        self.position_changed.emit(position_ms)

    def _on_duration(self, duration_ms: int):
        self.duration_changed.emit(duration_ms)
        # 检测试听版：如果实际时长远短于期望时长（且期望时长 > 60秒），提示
        if (self._expected_duration > 60000
                and 0 < duration_ms < self._expected_duration * 0.5
                and duration_ms < 45000):
            self.error_occurred.emit(
                "注意：此歌曲可能是试听版（约30秒），登录网易云账号可播放完整版"
            )

    def _on_state(self, state):
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.state_changed.emit("playing")
        elif state == QMediaPlayer.PlaybackState.PausedState:
            self.state_changed.emit("paused")
        elif state == QMediaPlayer.PlaybackState.StoppedState:
            self.state_changed.emit("stopped")

    def _on_error(self, error, error_string):
        msg = f"播放错误: {error_string}"
        self.error_occurred.emit(msg)
        # 播放错误时重试
        if self.current_song:
            QTimer.singleShot(1000, self._retry_current)

    def _on_media_status(self, status):
        ms = QMediaPlayer.MediaStatus

        if status == ms.LoadingMedia:
            self._set_buffering(True)

        elif status == ms.LoadedMedia:
            self._set_buffering(False)
            self._stall_timer.stop()

        elif status == ms.BufferingMedia:
            self._set_buffering(True)
            self._stall_timer.stop()

        elif status == ms.BufferedMedia:
            self._set_buffering(False)
            self._stall_timer.stop()

        elif status == ms.StalledMedia:
            # 缓冲不足，播放暂停等待数据
            self._set_buffering(True)
            self._stall_timer.start(15000)  # 15秒没恢复则重试

        elif status == ms.EndOfMedia:
            self._stall_timer.stop()
            self._set_buffering(False)
            # 检查是否正常播放结束
            position = self.player.position()
            duration = self.player.duration()
            if duration > 0 and position < duration * 0.85:
                # 异常中断（还没播到 85% 就结束了），重试
                self._retry_current()
            else:
                # 正常播放结束，切下一首
                self._retry_count = 0
                self.next()

        elif status == ms.InvalidMedia:
            self.error_occurred.emit("媒体格式无效，尝试重新获取播放地址...")
            self._retry_current()

        elif status == ms.NoMedia:
            self._set_buffering(False)
            self._stall_timer.stop()

    def _on_stall_timeout(self):
        """缓冲超时，重试"""
        self._stall_timer.stop()
        self._set_buffering(False)
        if self.current_song:
            self.error_occurred.emit("缓冲超时，正在重新连接...")
            self._retry_current()

    def _set_buffering(self, buffering: bool):
        if self._is_buffering != buffering:
            self._is_buffering = buffering
            self.buffering_changed.emit(buffering)

    def _update_lyric(self):
        """根据当前播放位置更新歌词"""
        if not self.lyrics:
            return
        current_sec = self.player.position() / 1000.0
        # 找到当前时间对应的歌词行
        idx = -1
        for i, (time_sec, _) in enumerate(self.lyrics):
            if time_sec <= current_sec:
                idx = i
            else:
                break
        if idx != self._current_lyric_idx and idx >= 0:
            self._current_lyric_idx = idx
            self.lyric_changed.emit(self.lyrics[idx][1])

    # ---------- 查询 ----------

    def is_playing(self) -> bool:
        return self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def get_current_song(self) -> Optional[dict]:
        return self.current_song

    def get_position_ms(self) -> int:
        return self.player.position()

    def get_duration_ms(self) -> int:
        return self.player.duration()
