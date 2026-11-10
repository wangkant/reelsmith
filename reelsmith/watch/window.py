"""The desktop window of `reelsmith watch`: the editor window as an app of its own (pywebview: WebView2 on Windows,
WebKit on macOS, GTK or Qt on Linux), so nobody has to keep a browser tab for it. The `app` extra installs it."""
from __future__ import annotations

import importlib.util

SIZE = (1440, 900)
MIN_SIZE = (1100, 680)
GROUND = "#0e0f11"              # the window's own ground, so it never flashes white while the page loads


def available() -> bool:
    return importlib.util.find_spec("webview") is not None


def _fitted(screens) -> tuple[int, int]:
    """SIZE, or nine tenths of the first screen when that is smaller."""
    if not screens:
        return SIZE
    return min(SIZE[0], int(screens[0].width * 0.9)), min(SIZE[1], int(screens[0].height * 0.9))


def open_window(url: str, title: str, ready=None) -> None:
    """Show `url` in a desktop window and return when it is closed. `ready(window)` runs beside it once it is up."""
    import webview
    width, height = _fitted(webview.screens)
    window = webview.create_window(title, url, width=width, height=height, min_size=MIN_SIZE, background_color=GROUND)
    webview.start(ready, window) if ready else webview.start()
