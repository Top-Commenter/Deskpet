"""
网易云音乐 API 客户端（通过本地 NeteaseCloudMusicApi 服务中转）
本地服务默认端口 3000，接口均为 GET，无需加密
"""
import json
import re
import time
from pathlib import Path
from typing import Optional

import requests

LOCAL_API = "http://localhost:3000"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


class NeteaseAPI:
    def __init__(self, cookie_path: Optional[Path] = None):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.cookie_path = cookie_path
        self.nickname = ""
        self.user_id = ""
        self._logged_in = False
        if cookie_path and cookie_path.exists():
            self._load_cookies()

    def _load_cookies(self):
        try:
            data = json.loads(self.cookie_path.read_text("utf-8"))
            self.nickname = data.get("nickname", "")
            self.user_id = data.get("user_id", "")
            cookie = data.get("cookie", "")
            if cookie:
                clean = self._clean_cookie_string(cookie)
                self.session.headers["Cookie"] = clean
                self._logged_in = True
        except Exception:
            pass

    @staticmethod
    def _clean_cookie_string(cookie: str) -> str:
        """清理 Set-Cookie 格式，只保留 key=value 对"""
        pairs = []
        # 按 ;; 或 ; 分割（API 返回的多个 cookie 用 ;; 分隔）
        for part in re.split(r";{1,2}", cookie):
            part = part.strip()
            if not part or "=" not in part:
                continue
            key, _, value = part.partition("=")
            key = key.strip()
            # 跳过 Set-Cookie 属性
            if key.lower() in ("path", "domain", "expires", "max-age",
                               "secure", "httponly", "samesite", "priority"):
                continue
            pairs.append(f"{key}={value.strip()}")
        return "; ".join(pairs)

    def _save_cookies(self, cookie: str):
        if not self.cookie_path:
            return
        data = {
            "cookie": cookie,
            "nickname": self.nickname,
            "user_id": self.user_id,
            "saved_at": time.time(),
        }
        self.cookie_path.parent.mkdir(parents=True, exist_ok=True)
        self.cookie_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        """GET 请求本地服务，带重试"""
        last_error = None
        for attempt in range(3):
            try:
                resp = self.session.get(f"{LOCAL_API}{path}", params=params, timeout=15)
                resp.raise_for_status()
                return resp.json()
            except (requests.ConnectionError, requests.Timeout) as e:
                last_error = e
                time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"API {path} connection failed: {last_error}")

    def is_service_online(self) -> bool:
        """检查本地 API 服务是否启动"""
        try:
            resp = self.session.get(f"{LOCAL_API}/", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    # ---------- 扫码登录 ----------

    def get_qr_key(self) -> str:
        result = self._get("/login/qr/key")
        return result.get("data", {}).get("unikey", "")

    def get_qr_image(self, key: str) -> Optional[str]:
        """返回 base64 编码的二维码图片"""
        result = self._get("/login/qr/create", {"key": key, "qrimg": "true"})
        qr_img = result.get("data", {}).get("qrimg", "")
        if qr_img.startswith("data:image/png;base64,"):
            qr_img = qr_img[len("data:image/png;base64,"):]
        return qr_img

    def check_qr_status(self, key: str) -> dict:
        """
        code=800 过期, 801 等待扫码, 802 已扫码, 803 登录成功
        """
        result = self._get("/login/qr/check", {"key": key})
        code = result.get("code", 0)
        if code == 803:
            cookie = result.get("cookie", "")
            if cookie:
                clean = self._clean_cookie_string(cookie)
                self.session.headers["Cookie"] = clean
                self._save_cookies(clean)
            # 获取用户信息
            try:
                status = self._get("/login/status")
                profile = status.get("data", {}).get("profile", {})
                self.nickname = profile.get("nickname", "")
                self.user_id = str(profile.get("userId", ""))
                if cookie:
                    self._save_cookies(self._clean_cookie_string(cookie))
            except Exception:
                pass
            self._logged_in = True
        return {"code": code, "message": result.get("message", "")}

    def is_logged_in(self) -> bool:
        if self._logged_in:
            return True
        try:
            result = self._get("/login/status")
            profile = result.get("data", {}).get("profile")
            if profile:
                self.nickname = profile.get("nickname", "")
                self.user_id = str(profile.get("userId", ""))
                self._logged_in = True
                return True
        except Exception:
            pass
        return False

    def logout(self):
        try:
            self._get("/logout")
        except Exception:
            pass
        self._logged_in = False
        self.nickname = ""
        self.user_id = ""
        self.session.headers.pop("Cookie", None)
        if self.cookie_path and self.cookie_path.exists():
            self.cookie_path.unlink()

    # ---------- 搜索 ----------

    def search(self, keyword: str, limit: int = 30) -> list:
        result = self._get("/search", {"keywords": keyword, "limit": limit, "type": 1})
        songs = result.get("result", {}).get("songs", [])
        return [
            {
                "id": str(s.get("id", "")),
                "name": s.get("name", ""),
                "artist": " / ".join(a.get("name", "") for a in s.get("artists", s.get("ar", []))),
                "album": s.get("album", s.get("al", {})).get("name", ""),
                "duration": s.get("duration", s.get("dt", 0)),
            }
            for s in songs
        ]

    # ---------- 播放地址 ----------

    def get_song_url(self, song_id: str, level: str = "standard") -> Optional[str]:
        result = self._get("/song/url/v1", {"id": song_id, "level": level})
        data_list = result.get("data", [])
        if data_list:
            return data_list[0].get("url")
        return None

    # ---------- 歌词 ----------

    def get_lyric(self, song_id: str) -> list:
        result = self._get("/lyric", {"id": song_id})
        lrc = result.get("lrc", {}).get("lyric", "")
        return self._parse_lrc(lrc)

    @staticmethod
    def _parse_lrc(lrc_text: str) -> list:
        lines = []
        for line in lrc_text.split("\n"):
            line = line.strip()
            if not line:
                continue
            matches = re.findall(r"\[(\d{1,2}):(\d{1,2})(?:[.:](\d{1,3}))?\]", line)
            text = re.sub(r"\[\d{1,2}:\d{1,2}(?:[.:]\d{1,3})?\]", "", line).strip()
            if not text:
                continue
            for m in matches:
                minutes = int(m[0])
                seconds = int(m[1])
                millis = int(m[2]) if m[2] else 0
                if len(m[2]) == 2:
                    millis *= 10
                total = minutes * 60 + seconds + millis / 1000.0
                lines.append((total, text))
        lines.sort(key=lambda x: x[0])
        return lines

    # ---------- 用户歌单 ----------

    def get_user_playlists(self, uid: str = "", limit: int = 30) -> list:
        uid = uid or self.user_id
        if not uid:
            return []
        result = self._get("/user/playlist", {"uid": uid, "limit": limit})
        playlists = result.get("playlist", [])
        return [
            {"id": str(p.get("id", "")), "name": p.get("name", ""),
             "count": p.get("trackCount", 0)}
            for p in playlists
        ]

    def get_playlist_songs(self, playlist_id: str) -> list:
        result = self._get("/playlist/track/all", {"id": playlist_id, "limit": 1000})
        tracks = result.get("songs", [])
        return [
            {
                "id": str(t.get("id", "")),
                "name": t.get("name", ""),
                "artist": " / ".join(a.get("name", "") for a in t.get("ar", [])),
                "album": t.get("al", {}).get("name", ""),
                "duration": t.get("dt", 0),
            }
            for t in tracks
        ]
