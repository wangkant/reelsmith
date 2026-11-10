"""The desktop window of `reelsmith watch`: the editor window as an app of its own (pywebview: WebView2 on Windows,
WebKit on macOS, GTK or Qt on Linux), so nobody has to keep a browser tab for it. The `app` extra installs it."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

SIZE = (1440, 900)
MIN_SIZE = (1100, 680)
GROUND = "#0e0f11"              # the window's own ground, so it never flashes white while the page loads
ICON = Path(__file__).resolve().parent / "static" / "icon.ico"
APP_ID = "reelsmith.watch"
# Microsoft Edge WebView2 Runtime, then its Beta, Dev and Canary channels (the keys pywebview looks at)
_WEBVIEW2 = ("{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}", "{2CD8A007-E189-409D-A2C8-9AF4EF3C72AA}",
             "{0D50BFEC-CD6A-4F9A-964C-C7416E3ACB10}", "{65C35B14-6C1D-4122-AC46-7148CC9D6497}")


def has_pywebview() -> bool:
    return importlib.util.find_spec("webview") is not None


def webview2_version() -> str | None:
    """The installed WebView2 runtime's version (Windows); None when there is none."""
    import winreg
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for node in ("WOW6432Node\\", ""):
            for key in _WEBVIEW2:
                try:
                    with winreg.OpenKey(hive, f"SOFTWARE\\{node}Microsoft\\EdgeUpdate\\Clients\\{key}") as k:
                        version = str(winreg.QueryValueEx(k, "pv")[0])
                except OSError:
                    continue
                if version and version != "0.0.0.0":
                    return version
    return None


def available() -> bool:
    """pywebview is installed and, on Windows, has WebView2 to draw with (without it pywebview falls back to the old
    Internet Explorer engine, which cannot show the page)."""
    return has_pywebview() and (os.name != "nt" or webview2_version() is not None)


def _fitted(screens) -> tuple[int, int]:
    """SIZE, or nine tenths of the first screen when that is smaller."""
    if not screens:
        return SIZE
    return min(SIZE[0], int(screens[0].width * 0.9)), min(SIZE[1], int(screens[0].height * 0.9))


def _own_taskbar_entry() -> None:
    """Windows groups a window under its process's executable ("Python") unless the process names itself."""
    if os.name == "nt":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)


def open_window(url: str, title: str, ready=None) -> None:
    """Show `url` in a desktop window and return when it is closed. `ready(window)` runs beside it once it is up."""
    import webview
    _own_taskbar_entry()
    width, height = _fitted(webview.screens)
    window = webview.create_window(title, url, width=width, height=height, min_size=MIN_SIZE, background_color=GROUND)
    icon = str(ICON) if ICON.is_file() else None
    webview.start(ready, window, icon=icon) if ready else webview.start(icon=icon)
