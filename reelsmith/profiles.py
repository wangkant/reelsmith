"""Platform profiles (frame, UI-safe area, delivery limits) and visual themes."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class Profile:
    name: str
    width: int
    height: int
    fps: int
    safe: Box                       # every glyph stays inside; backgrounds may bleed
    captions: Box                   # the default captions band: the safe area's bottom 200 px (Captions.tsx)
    min_s: float
    max_s: float
    target_s: tuple[float, float]
    max_mb: float
    lufs: float
    peak_db: float = -1.0
    max_still_s: float = 5.0
    max_black_ratio: float = 0.10
    vcodec: str = "h264"
    acodec: str = "aac"

    def to_json(self) -> dict:
        return asdict(self)

    def outside_safe(self) -> list[tuple[int, int, int, int]]:
        """The four bands around the safe area (x, y, w, h): where the platform's UI may cover the picture."""
        s, W, H = self.safe, self.width, self.height
        bands = [(0, 0, W, s.y), (0, s.y + s.h, W, H - s.y - s.h),
                 (0, s.y, s.x, s.h), (s.x + s.w, s.y, W - s.x - s.w, s.h)]
        return [b for b in bands if b[2] > 0 and b[3] > 0]


# Douyin on a phone covers the top ~200 px, the right rail (x >= 920, y 720-1640) and the bottom bar (y >= 1480).
DOUYIN = Profile("douyin", 1080, 1920, 30, Box(40, 220, 840, 1240), Box(40, 1260, 840, 200),
                 20, 90, (45, 75), 80, -10.0)
# Douyin's longer explainers (a how-to, a checklist worth saving): the same screen, more time.
DOUYIN_LONG = replace(DOUYIN, name="douyin-long", min_s=60, max_s=300, target_s=(90, 180), max_mb=250)
# TikTok and Shorts lay their chrome out much the same; the right rail sits a little lower on Shorts.
TIKTOK = Profile("tiktok", 1080, 1920, 30, Box(60, 200, 820, 1260), Box(60, 1260, 820, 200),
                 15, 180, (30, 75), 250, -14.0)
SHORTS = Profile("shorts", 1080, 1920, 30, Box(60, 180, 820, 1300), Box(60, 1280, 820, 200),
                 15, 180, (30, 60), 250, -14.0)

PROFILES = {p.name: p for p in (DOUYIN, DOUYIN_LONG, TIKTOK, SHORTS)}
DEFAULT_PROFILE = "douyin"


def get_profile(name: str | None) -> Profile:
    """The named profile (default douyin); unknown names raise with the choices."""
    key = name or DEFAULT_PROFILE
    if key not in PROFILES:
        raise ValueError(f"unknown profile {key!r}; one of {', '.join(PROFILES)}")
    return PROFILES[key]


@dataclass(frozen=True)
class Theme:
    name: str
    paper: str          # light ground
    ink: str            # text on paper
    night: str          # dark ground
    snow: str           # text on night
    accent: str         # the one number that matters, the stamp
    gold: str
    good: str
    bad: str
    muted: str
    fonts: dict = field(default_factory=lambda: {"sans": "sans", "display": "display", "serif": "serif"})

    def to_json(self) -> dict:
        return asdict(self)


PAPER = Theme("paper", "#F3EBDD", "#1E1A16", "#16130F", "#F7F1E6", "#C8372D", "#D9A441", "#2E8B57", "#C8372D",
              "#7A6F62")
NIGHT = Theme("night", "#E9EEF3", "#10151C", "#0E1319", "#F2F5F8", "#FF5A3C", "#FFC24B", "#3BC48A", "#FF5A3C",
              "#8A96A3")

THEMES = {t.name: t for t in (PAPER, NIGHT)}
