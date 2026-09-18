"""
设置持久化模块
保存用户偏好：形态、音量、置顶、位置、互动统计等
"""
import json
import time
from pathlib import Path
from typing import Any


class Settings:
    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.settings_file = config_dir / "settings.json"
        self.stats_file = config_dir / "stats.json"
        self._data = self._load(self.settings_file, self._defaults())
        self._stats = self._load(self.stats_file, self._default_stats())

    @staticmethod
    def _defaults() -> dict:
        return {
            "form": "small",           # small / big
            "volume": 70,
            "always_on_top": True,
            "pet_scale": 1.0,          # 0.6 - 1.5
            "position": None,          # [x, y] 上次窗口位置
            "show_lyrics": True,
            "auto_play": False,
        }

    @staticmethod
    def _default_stats() -> dict:
        return {
            "affection": 0,
            "total_interactions": 0,
            "total_play_time_ms": 0,
            "last_visit": time.strftime("%Y-%m-%d"),
        }

    @staticmethod
    def _load(path: Path, default: dict) -> dict:
        if path.exists():
            try:
                data = json.loads(path.read_text("utf-8"))
                # 合并默认值，防止新增字段缺失
                merged = default.copy()
                merged.update(data)
                return merged
            except Exception:
                pass
        return default.copy()

    def _save(self):
        self.settings_file.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), "utf-8"
        )

    def _save_stats(self):
        self.stats_file.write_text(
            json.dumps(self._stats, ensure_ascii=False, indent=2), "utf-8"
        )

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any):
        self._data[key] = value
        self._save()

    def get_stats(self, key: str, default: Any = None) -> Any:
        return self._stats.get(key, default)

    def set_stats(self, key: str, value: Any):
        self._stats[key] = value
        self._save_stats()

    def add_interaction(self, affection_gain: int = 1):
        self._stats["total_interactions"] = self._stats.get("total_interactions", 0) + 1
        self._stats["affection"] = self._stats.get("affection", 0) + affection_gain
        self._save_stats()

    @property
    def form(self) -> str:
        return self._data.get("form", "small")

    @form.setter
    def form(self, value: str):
        self.set("form", value)

    @property
    def volume(self) -> int:
        return self._data.get("volume", 70)

    @volume.setter
    def volume(self, value: int):
        self.set("volume", max(0, min(100, value)))

    @property
    def always_on_top(self) -> bool:
        return self._data.get("always_on_top", True)

    @always_on_top.setter
    def always_on_top(self, value: bool):
        self.set("always_on_top", value)

    @property
    def pet_scale(self) -> float:
        return self._data.get("pet_scale", 1.0)

    @pet_scale.setter
    def pet_scale(self, value: float):
        self.set("pet_scale", max(0.5, min(2.0, value)))

    @property
    def position(self):
        return self._data.get("position")

    @position.setter
    def position(self, value):
        self.set("position", value)
