"""The terminal session's words: one flat dictionary per language (<code>.json, {name} placeholders). en holds every
key; another language falls back to it key by key. The language: --lang, REELSMITH_LANG, the saved choice, the
system's, else en."""
from __future__ import annotations

import json
import locale
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LANGUAGES = {"en": "English", "zh-CN": "简体中文", "zh-TW": "繁體中文", "ja": "日本語", "ko": "한국어",
             "es": "Español", "fr": "Français", "de": "Deutsch"}
DEFAULT = "en"
LANG_ENV = "REELSMITH_LANG"
CONFIG_ENV = "REELSMITH_CONFIG_DIR"
SETTINGS = "term.json"


def available() -> list[str]:
    """The languages that have a dictionary, in LANGUAGES order."""
    return [code for code in LANGUAGES if (HERE / f"{code}.json").is_file()]


def load(code: str) -> dict[str, str]:
    try:
        data = json.loads((HERE / f"{code}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def match(tag: str | None) -> str | None:
    """A supported code for a tag such as zh_CN.UTF-8, zh-Hant-TW, ja-JP or fr; None when none fits."""
    if not tag:
        return None
    t = str(tag).split(".")[0].split("@")[0].replace("_", "-").strip()
    low = t.lower()
    have = available()
    for code in have:
        if code.lower() == low:
            return code
    if low.startswith("zh") or low.startswith("chinese"):
        trad = any(m in low for m in ("-tw", "-hk", "-mo", "hant", "taiwan", "hong kong", "traditional"))
        code = "zh-TW" if trad else "zh-CN"
        return code if code in have else None
    primary = low.split("-")[0]
    names = {"english": "en", "japanese": "ja", "korean": "ko", "spanish": "es", "french": "fr", "german": "de"}
    primary = names.get(primary.split(" ")[0], primary)
    return primary if primary in have else None


def config_dir() -> Path:
    """The per-user folder for the session's settings; REELSMITH_CONFIG_DIR moves it."""
    own = os.environ.get(CONFIG_ENV, "").strip()
    if own:
        return Path(own).expanduser()
    if os.name == "nt":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "reelsmith"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "reelsmith"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "reelsmith"


def read_settings() -> dict:
    try:
        data = json.loads((config_dir() / SETTINGS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_setting(key: str, value) -> Path:
    path = config_dir() / SETTINGS
    data = read_settings()
    data[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def system_tag() -> str | None:
    if os.name == "nt":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, 85):
                return buf.value
        except (AttributeError, OSError):
            pass
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        if os.environ.get(name):
            return os.environ[name]
    try:
        return locale.getlocale()[0]
    except ValueError:
        return None


def choose(flag: str | None = None) -> str:
    for tag in (flag, os.environ.get(LANG_ENV), read_settings().get("lang"), system_tag()):
        code = match(tag) if isinstance(tag, str) else None
        if code:
            return code
    return DEFAULT


class Texts:
    """t(key, **params): the language's sentence, else English, else the key itself."""

    def __init__(self, code: str = DEFAULT):
        self.set(code)

    def set(self, code: str) -> None:
        self.code = code if code in available() else DEFAULT
        self.base = load(DEFAULT)
        self.own = load(self.code) if self.code != DEFAULT else self.base

    def has(self, key: str) -> bool:
        return key in self.own or key in self.base

    def __call__(self, key: str, /, **params) -> str:       # positional: a param may be named key
        text = self.own.get(key) or self.base.get(key) or key
        if not params:
            return text
        try:
            return text.format(**params)
        except (KeyError, IndexError, ValueError):
            return text
