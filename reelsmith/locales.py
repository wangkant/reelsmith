"""Locales (BCP-47 tags such as "en", "zh-CN", "ja"): what a project's language changes. Caption phrasing and their
default length, the browser and web language of capture and the runner's web tools, and the default voice."""
from __future__ import annotations

import re

DEFAULT_LOCALE = "en"
_TAG = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8}){0,4}$")
_CHINESE = {"zh", "cmn", "yue", "wuu", "hak", "nan"}
_CJK = _CHINESE | {"ja", "ko"}
CJK_CAPTION_CHARS = 14          # full-width characters: one caption line on a phone
CAPTION_CHARS = 32              # Latin and other scripts: about one subtitle line


def check(tag) -> str:
    """The tag as given when it looks like BCP-47; ValueError otherwise."""
    if not isinstance(tag, str) or not _TAG.match(tag.strip()):
        raise ValueError(f"locale {tag!r} is not a BCP-47 language tag such as \"en\", \"en-GB\", \"zh-CN\" or \"ja\"")
    return tag.strip()


def language(tag: str) -> str:
    return str(tag or DEFAULT_LOCALE).split("-")[0].lower()


def is_cjk(tag: str) -> bool:
    return language(tag) in _CJK


def is_chinese(tag: str) -> bool:
    return language(tag) in _CHINESE


def caption_chars(tag: str) -> int:
    """The default max_chars of a captions track."""
    return CJK_CAPTION_CHARS if is_cjk(tag) else CAPTION_CHARS


def accept_language(tag: str) -> str:
    """An Accept-Language header: the tag, its bare language, then English as the fallback."""
    tag = tag or DEFAULT_LOCALE
    lang = language(tag)
    parts = [tag] + ([f"{lang};q=0.9"] if lang != tag.lower() else [])
    if lang != "en":
        parts.append("en;q=0.8")
    return ",".join(parts)
