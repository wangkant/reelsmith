"""The application's desktop window (pywebview, the `app` extra) and the bridge its page may call."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

SIZE = (1440, 900)
MIN_SIZE = (1100, 680)
# the window's own ground (the page's --bg in each theme), so it never flashes another colour while the page loads
GROUND = {"dark": "#121212", "light": "#f7f7f7"}
ICON = Path(__file__).resolve().parent / "static" / "icon.ico"
APP_ID = "reelsmith.watch"
TITLE_MAX = 200
FRAMES = ("frameless", "native")
# Microsoft Edge WebView2 Runtime, then its Beta, Dev and Canary channels (the keys pywebview looks at)
_WEBVIEW2 = ("{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}", "{2CD8A007-E189-409D-A2C8-9AF4EF3C72AA}",
             "{0D50BFEC-CD6A-4F9A-964C-C7416E3ACB10}", "{65C35B14-6C1D-4122-AC46-7148CC9D6497}")

# Win32 values the frameless window uses
WM_SIZE, WM_WINDOWPOSCHANGING, WM_WINDOWPOSCHANGED = 0x0005, 0x0046, 0x0047
WM_NCCALCSIZE, WM_NCDESTROY, WM_NCLBUTTONDOWN = 0x0083, 0x0082, 0x00A1
SIZED = {0: "normal", 1: "minimised", 2: "maximised"}       # WM_SIZE's SIZE_RESTORED, SIZE_MINIMIZED, SIZE_MAXIMIZED
WM_GRAB = 0x8000 + 0x52          # WM_APP + n: the page asks for a move or a resize to begin
HT = {"client": 1, "caption": 2, "left": 10, "right": 11, "top": 12, "top-left": 13, "top-right": 14,
      "bottom": 15, "bottom-left": 16, "bottom-right": 17}
EDGES = ("top", "top-left", "top-right")        # the page draws these; the other edges are the system's
GWLP_WNDPROC = -4
DWMWA_USE_IMMERSIVE_DARK_MODE, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND = 20, 33, 2
# set on each document before its own scripts run: the page's first paint knows the frame (it may miss the first one)
MARK_SCRIPT = "window.__reelsmithFrame = {kind!r};"


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


def frame_for(native_flag: bool = False, config: dict | None = None, system: str | None = None) -> str:
    """"frameless" (Windows) unless --native-frame or workspace.json "watch": {"frame": "native"} asks for the
    system frame; macOS and Linux keep theirs, which pywebview cannot replace with an equal one."""
    watch = config.get("watch") if isinstance(config, dict) else None
    asked = watch.get("frame") if isinstance(watch, dict) else None
    if native_flag or asked == "native" or (system or os.name) != "nt":
        return "native"
    return "frameless"


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


def system_theme() -> str:
    """"light" or "dark", as the system shows its apps (read on Windows; dark elsewhere)."""
    if os.name != "nt":
        return "dark"
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return "light" if winreg.QueryValueEx(k, "AppsUseLightTheme")[0] else "dark"
    except OSError:
        return "light"


# ------------------------------------------------------------------ Win32 (Windows only; None elsewhere)
def _win32():
    """user32 and dwmapi with the signatures used here; None off Windows."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes
    u, d = ctypes.WinDLL("user32", use_last_error=True), ctypes.WinDLL("dwmapi")
    lres = ctypes.c_ssize_t
    for name, res, args in (
            ("CallWindowProcW", lres, [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                       wintypes.LPARAM]),
            ("DefWindowProcW", lres, [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]),
            ("SetWindowLongPtrW", ctypes.c_void_p, [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]),
            ("PostMessageW", wintypes.BOOL, [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]),
            ("SetWindowPos", wintypes.BOOL, [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                             ctypes.c_int, wintypes.UINT]),
            ("IsZoomed", wintypes.BOOL, [wintypes.HWND]), ("IsIconic", wintypes.BOOL, [wintypes.HWND]),
            ("ShowWindow", wintypes.BOOL, [wintypes.HWND, ctypes.c_int]),
            ("GetAsyncKeyState", ctypes.c_short, [ctypes.c_int]), ("GetSystemMetrics", ctypes.c_int, [ctypes.c_int]),
            ("GetCursorPos", wintypes.BOOL, [ctypes.POINTER(wintypes.POINT)]), ("ReleaseCapture", wintypes.BOOL, []),
            ("GetWindowPlacement", wintypes.BOOL, [wintypes.HWND, ctypes.c_void_p])):
        fn = getattr(u, name)
        fn.restype, fn.argtypes = res, args
    d.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    return u, d


def _hwnd(window) -> int | None:
    try:
        return int(window.native.Handle.ToInt64())
    except Exception:           # not shown yet, or a backend without a Win32 handle
        return None


def _dwm_int(hwnd: int, attr: int, value: int) -> bool:
    w = _win32()
    if w is None or not hwnd:
        return False
    import ctypes
    v = ctypes.c_int(value)
    return w[1].DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v)) == 0


def _frame_theme(window, theme: str) -> None:
    """Dark or light window border (Windows 11) and, with the system frame, title bar; a no-op anywhere else."""
    hwnd = _hwnd(window) if os.name == "nt" and theme in GROUND else None
    if hwnd and _dwm_int(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if theme == "dark" else 0):
        _win32()[0].SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0037)    # no move, size, z-order or focus: redraw the frame


def client_top(proposed_top: int, left_before: int, left_after: int, maximised: bool) -> int:
    """The client area's top once the caption is gone: the window's own top, or, maximised, inset as far as the
    system insets its left side (a maximised window reaches past the screen by its border)."""
    return proposed_top + (left_after - left_before if maximised else 0)


def _button_down(user32) -> bool:
    vk = 0x02 if user32.GetSystemMetrics(23) else 0x01            # SM_SWAPBUTTON: the primary button
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


class Frame:
    """The window's frame. "frameless" on Windows keeps the system's resizable, snappable window and its shadow but
    gives the caption's room to the page (WM_NCCALCSIZE); "native" leaves the system frame alone."""

    def __init__(self, kind: str = "native"):
        self.kind = kind if kind in FRAMES else "native"
        self.hwnd: int | None = None
        self.maximised = False          # what the window's events said; Windows asks the window itself
        self._old = None
        self._proc = None               # the callback must outlive the window
        self._sized = "normal"          # the last WM_SIZE kind
        self._hold = False              # inside a restore's WM_WINDOWPOSCHANGED: WinForms may not resize the window

    # ---------------------------------------------------------------- the window's state
    def state(self) -> str:
        """"maximised", "minimised" or "normal"."""
        w = _win32() if self.hwnd else None
        if w is None:
            return "maximised" if self.maximised else "normal"
        u = w[0]
        if u.IsIconic(self.hwnd):
            return "minimised"
        return "maximised" if u.IsZoomed(self.hwnd) else "normal"

    def restores_maximised(self) -> bool:
        """Maximised now, or minimised from maximised (WPF_RESTORETOMAXIMIZED)."""
        st = self.state()
        if st != "minimised" or not self.hwnd:
            return st == "maximised" or (st == "minimised" and self.maximised)
        import ctypes
        place = (ctypes.c_uint * 11)(44)
        return bool(_win32()[0].GetWindowPlacement(self.hwnd, place) and place[1] & 0x2)

    # ---------------------------------------------------------------- frameless (Windows)
    def install(self, hwnd: int) -> bool:
        """Subclass the window so its client area takes the caption's room; True when it did."""
        self.hwnd = hwnd
        w = _win32()
        if self.kind != "frameless" or w is None or not hwnd:
            return False
        import ctypes
        from ctypes import wintypes
        u = w[0]
        proto = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        self._proc = proto(self._wndproc)
        self._old = u.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, ctypes.cast(self._proc, ctypes.c_void_p))
        if not self._old:
            self._proc = None
            return False
        _dwm_int(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND)
        u.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0037)        # SWP_FRAMECHANGED among them: recalculate the frame
        return True

    def _wndproc(self, hwnd, msg, wparam, lparam):
        import ctypes
        from ctypes import wintypes
        u = _win32()[0]
        try:
            if msg == WM_NCCALCSIZE and wparam:
                rect = ctypes.cast(lparam, ctypes.POINTER(wintypes.RECT)).contents     # rgrc[0] leads the struct
                top, left = rect.top, rect.left
                res = u.CallWindowProcW(self._old, hwnd, msg, wparam, lparam)
                rect.top = client_top(top, left, rect.left, bool(u.IsZoomed(hwnd)))
                return res
            if msg == WM_SIZE and wparam in SIZED:
                self._sized = SIZED[wparam]
            if msg == WM_WINDOWPOSCHANGED and self._sized != "normal" and not u.IsZoomed(hwnd) \
                    and not u.IsIconic(hwnd):
                # WinForms answers a restore by rebuilding the size from a client area that no longer leaves room for
                # a caption: it would grow the window by one caption on every restore
                self._hold = True
                try:
                    return u.CallWindowProcW(self._old, hwnd, msg, wparam, lparam)
                finally:
                    self._hold = False
            if msg == WM_WINDOWPOSCHANGING and self._hold:
                class WINDOWPOS(ctypes.Structure):
                    _fields_ = [("hwnd", wintypes.HWND), ("after", wintypes.HWND), ("x", ctypes.c_int),
                                ("y", ctypes.c_int), ("cx", ctypes.c_int), ("cy", ctypes.c_int),
                                ("flags", wintypes.UINT)]
                ctypes.cast(lparam, ctypes.POINTER(WINDOWPOS)).contents.flags |= 0x0003   # NOSIZE | NOMOVE
            if msg == WM_GRAB:
                return self._grab_now(u, int(wparam))
            if msg == WM_NCDESTROY:
                u.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, self._old)
        except Exception:               # never let a Python error take the window's messages down
            pass
        return u.CallWindowProcW(self._old, hwnd, msg, wparam, lparam)

    def _grab_now(self, u, ht: int) -> int:
        """On the window's thread: the system's own move or resize loop, if the button is still held."""
        import ctypes
        from ctypes import wintypes
        if not _button_down(u) or (ht != HT["caption"] and u.IsZoomed(self.hwnd)):
            return 0
        pt = wintypes.POINT()
        u.GetCursorPos(ctypes.byref(pt))
        u.ReleaseCapture()
        u.DefWindowProcW(self.hwnd, WM_NCLBUTTONDOWN, ht, (pt.y & 0xFFFF) << 16 | (pt.x & 0xFFFF))
        return 1

    def grab(self, what: str) -> bool:
        """The page's top edge, top corners (or, without WebView2's drag regions, its drag region) was pressed."""
        w = _win32()
        if self.kind != "frameless" or w is None or not self.hwnd or not self._old or what not in HT:
            return False
        return bool(w[0].PostMessageW(self.hwnd, WM_GRAB, HT[what], 0))

    def show_restored(self) -> bool:
        """Out of the taskbar as it was before (maximised stays maximised); False where pywebview must do it."""
        w = _win32()
        if w is None or not self.hwnd:
            return False
        if w[0].IsIconic(self.hwnd):
            w[0].ShowWindow(self.hwnd, 9)           # SW_RESTORE
        return True


def _web_regions(window, frame: Frame) -> None:
    """Frameless, WebView2 treats `app-region: drag` as the caption (move, snap, double-click, system menu); either
    way each page learns the frame before it paints. A no-op on other backends."""
    try:
        view = window.native.browser.webview
    except Exception:
        return

    def ready(sender, args):
        try:
            if not args.IsSuccess:
                return
            core = sender.CoreWebView2
            core.AddScriptToExecuteOnDocumentCreatedAsync(MARK_SCRIPT.format(kind=frame.kind))
            if frame.kind == "frameless":
                core.Settings.IsNonClientRegionSupportEnabled = True
        except Exception:               # an older runtime: the page's own drag fallback takes over
            pass
    view.CoreWebView2InitializationCompleted += ready


def _flash(window) -> bool:
    """The taskbar entry flashes until the window is next in front; the focus stays where it is (Windows only)."""
    hwnd = _hwnd(window) if os.name == "nt" else None
    if not hwnd:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class FLASHWINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("hwnd", wintypes.HWND), ("dwFlags", wintypes.DWORD),
                        ("uCount", wintypes.UINT), ("dwTimeout", wintypes.DWORD)]
        info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, 0x2 | 0xC, 0, 0)   # TRAY | TIMERNOFG
        ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
        return True
    except Exception:           # another backend: nothing to flash
        return False


def _dialog_kind(name: str):
    import webview
    kinds = getattr(webview, "FileDialog", None)
    if kinds is not None:
        return getattr(kinds, name)
    return getattr(webview, f"{name}_DIALOG")


def _pick(window, folder: bool) -> list[str]:
    """pywebview's own file or folder dialog; [] when it is cancelled."""
    got = window.create_file_dialog(_dialog_kind("FOLDER" if folder else "OPEN"), allow_multiple=not folder)
    return [str(p) for p in got or []]


def bring_forward(window, frame: Frame | None = None) -> None:
    """A second start of the application: its window shows (restored if minimised) and its taskbar entry flashes."""
    if frame is None or not frame.show_restored():
        try:
            window.restore()
        except Exception:           # not minimised, or a backend without it
            pass
    window.show()
    _flash(window)


# ------------------------------------------------------------------ the window's size and place, per workspace
def load_geometry(path: Path | None, screens) -> dict | None:
    """{width, height, x, y, maximised} as last closed; the place is dropped when it would lie off the first screen."""
    if path is None:
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        g = {k: int(data[k]) for k in ("width", "height", "x", "y")}
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if g["width"] < MIN_SIZE[0] or g["height"] < MIN_SIZE[1]:
        return None
    if screens:
        s = screens[0]
        left, top = getattr(s, "x", 0) or 0, getattr(s, "y", 0) or 0
        if g["x"] + 80 > left + s.width or g["y"] + 40 > top + s.height or g["x"] + g["width"] < left + 80 \
                or g["y"] < top - 20:
            g.pop("x")
            g.pop("y")
        g["width"], g["height"] = min(g["width"], s.width), min(g["height"], s.height)
    g["maximised"] = data.get("maximised") is True
    return g


def save_geometry(path: Path | None, g: dict) -> None:
    if path is None or not all(isinstance(g.get(k), int) for k in ("width", "height", "x", "y")):
        return
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        kept = {k: g[k] for k in ("width", "height", "x", "y")}
        Path(path).write_text(json.dumps({**kept, "maximised": g.get("maximised") is True}), encoding="utf-8")
    except OSError:
        pass


def track_place(window, frame: Frame, place: dict, geometry: Path | None) -> None:
    """Keep the restored size and place (never a maximised or minimised one) and save them with the state on close."""
    def resized(w, h, *a):
        if frame.state() == "normal":
            place.update(width=int(w), height=int(h))

    def moved(x, y, *a):
        if frame.state() == "normal":
            place.update(x=int(x), y=int(y))

    def set_max(on):
        def fn(*a):
            frame.maximised = on
        return fn
    window.events.maximized += set_max(True)
    def restored(*a):           # Windows asks the window itself; elsewhere a restore ends a maximise
        frame.maximised = False
        frame.maximised = frame.state() == "maximised"
    window.events.restored += restored
    window.events.resized += resized
    window.events.moved += moved
    window.events.closing += lambda *a: save_geometry(geometry, {**place, "maximised": frame.restores_maximised()})


# ------------------------------------------------------------------ what the page may ask
def bridge(window, frame: Frame | None = None) -> list:
    """The functions window.pywebview.api offers the page; each returns to a promise there."""
    frame = frame or Frame("native")

    def set_theme(name):        # the page calls this whenever its theme is set
        _frame_theme(window, str(name))

    def pick_files():
        return _pick(window, folder=False)

    def pick_folder():
        got = _pick(window, folder=True)
        return got[0] if got else None

    def attention():
        return _flash(window)

    def set_title(text):        # the taskbar and Alt+Tab show it; no title bar does
        window.set_title(str(text or "reelsmith")[:TITLE_MAX])
        return True

    def window_state():
        return {"frame": frame.kind, "maximised": frame.state() == "maximised"}

    def minimise():
        window.minimize()
        return True

    def toggle_maximise():
        on = frame.state() != "maximised"
        window.maximize() if on else window.restore()
        frame.maximised = on
        return {"frame": frame.kind, "maximised": on}

    def close():
        window.destroy()
        return True

    def start_resize(edge):
        return edge in EDGES and frame.grab(edge)

    def start_drag():
        return frame.grab("caption")
    return [set_theme, pick_files, pick_folder, attention, set_title, window_state, minimise, toggle_maximise, close,
            start_resize, start_drag]


def open_window(url: str, title: str, ready=None, geometry: Path | None = None, hooks: dict | None = None,
                frame: str = "frameless") -> None:
    """Show `url` in a desktop window until it is closed; `hooks` receives "raise", which brings it forward."""
    import webview
    _own_taskbar_entry()
    width, height = _fitted(webview.screens)
    kept = load_geometry(geometry, webview.screens) or {}
    theme = system_theme()
    fr = Frame(frame_for(frame == "native"))
    window = webview.create_window(title, url, width=kept.get("width", width), height=kept.get("height", height),
                                   x=kept.get("x"), y=kept.get("y"), min_size=MIN_SIZE,
                                   maximized=bool(kept.get("maximised")), background_color=GROUND[theme])
    fr.maximised = bool(kept.get("maximised"))
    window.expose(*bridge(window, fr))

    def before_show():          # on the window's thread, before it is first drawn
        fr.install(_hwnd(window))
        _web_regions(window, fr)

    def shown():
        _frame_theme(window, theme)
        if kept.get("maximised") and fr.state() != "maximised":
            window.maximize()           # frameless, the first show comes up restored: maximise it as it was left
    window.events.before_show += before_show
    window.events.shown += shown
    place = {"width": kept.get("width", width), "height": kept.get("height", height), "x": kept.get("x"),
             "y": kept.get("y")}
    track_place(window, fr, place, geometry)
    if hooks is not None:
        hooks["raise"] = lambda: bring_forward(window, fr)
    icon = str(ICON) if ICON.is_file() else None
    webview.start(ready, window, icon=icon) if ready else webview.start(icon=icon)
