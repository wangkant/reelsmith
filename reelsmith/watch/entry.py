"""`reelsmith app` (and bare `reelsmith`): the application on a workspace, one per workspace."""
from __future__ import annotations

import argparse
import os
import sys
import threading
import webbrowser
from pathlib import Path
from urllib.parse import quote

from ..workspace import WorkspaceError

LANGS = ("en", "zh-CN", "zh-TW", "ja", "ko", "es", "fr", "de")


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="reelsmith app",
                                 description="Open the reelsmith application on the workspace at or above a folder: "
                                             "every film of the workspace, requests to the agent in several films "
                                             "at once, the library and the settings. A desktop window when the `app` "
                                             "extra is installed, else a browser tab. Local only.")
    ap.add_argument("path", nargs="?", default="", help="a workspace or film folder (default: the current folder)")
    ap.add_argument("--browser", action="store_true", help="open it in the browser instead of a desktop window")
    ap.add_argument("--no-open", action="store_true", help="serve and print the address without opening anything")
    ap.add_argument("--port", type=int, default=0, help="the port on 127.0.0.1 (default: a free one)")
    ap.add_argument("--lang", default=None, choices=LANGS, help="the interface language")
    ap.add_argument("--native-frame", action="store_true",
                    help="give the desktop window the system's title bar and frame instead of its own")
    return ap


def _terminal() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def _ask(question: str) -> bool:
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def _say(text: str, err: bool = False) -> None:
    print(f"reelsmith app: {text}", file=sys.stderr if err else sys.stdout, flush=True)


def _forward(other: dict, target: Path, browser: bool) -> None:
    from . import app as A
    if browser:
        webbrowser.open(other["url"])
        _say(f"the application on {target.name} is already running (process {other.get('pid')}); opened "
             f"{other['url']} in the browser")
        return
    came = A.ask_to_raise(other)
    where = "its window was brought forward" if came else "it runs in a browser tab at that address"
    _say(f"the application on {target.name} is already running (process {other.get('pid')}, {other['url']}); "
         f"{where}")


def main(argv: list[str] | None = None) -> int:
    from ..term import places
    from . import app as A
    from . import server as W
    from . import window
    args = parser().parse_args(argv)
    start = Path(args.path).expanduser() if args.path else Path(os.getcwd())
    try:
        place = places.locate(start)
    except WorkspaceError as exc:
        _say(str(exc), err=True)
        return 2
    if place.kind == "none":
        if not _terminal():
            _say(f"{place.path} is not inside a workspace (no workspace.json at or above it); run reelsmith app in "
                 "a terminal there to create one", err=True)
            return 2
        _say(f"{place.path} is not inside a workspace.")
        if not _ask(f"Create a workspace in {place.path}?"):
            _say("no workspace was created")
            return 1
        try:
            places.create_workspace(place.path, places.film_locale(args.lang or "en"))
            place = places.locate(place.path)
        except (OSError, WorkspaceError) as exc:
            _say(f"the workspace could not be created: {exc}", err=True)
            return 2
        _say(f"created a workspace in {place.path}")
    as_window = not args.no_open and not args.browser and window.available()
    whole = place.kind == "workspace" or place.listed
    target = place.workspace.root if whole else place.project
    if whole:
        other = A.running_instance(target)
        if other is not None and A.answers(other):
            _forward(other, target, args.browser)
            return 0
    try:
        srv = W.WatchServer(target, args.port)
    except (ValueError, WorkspaceError, OSError) as exc:
        _say(str(exc), err=True)
        return 2
    if whole:
        other = A.claim_instance(target, srv.url, srv.token)
        if other is not None:              # another start on the same workspace won
            srv.stop_quietly()
            _forward(other, target, args.browser)
            return 0
    page = f"p/{quote(place.project.name)}/" if place.kind == "project" and whole else ""
    url = srv.url + page + (f"?lang={args.lang}" if args.lang else "")
    title = f"reelsmith · {target.name}" if whole else W._title(srv)
    if as_window:
        _say(f"{url}  (a desktop window; closing it stops the application and every request it runs)")
    elif args.no_open:
        _say(f"{url}  (local; Ctrl+C stops it and every request it runs)")
    else:
        _say(f"{url}  (a browser tab; Ctrl+C stops it and every request it runs)")
        if not args.browser:
            _say('for a desktop window instead of a browser tab: pip install "reelsmith[app]"')
    try:
        if as_window:
            srv.desktop = True
            hooks: dict = {}
            srv.raise_window = lambda: hooks["raise"]()
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            geometry = (target / ".cache" / "watch" / "window.json") if whole else None
            config = place.workspace.config if place.workspace is not None else None
            window.open_window(url, title, geometry=geometry, hooks=hooks,
                               frame=window.frame_for(args.native_frame, config))
        else:
            if not args.no_open:
                webbrowser.open(url)
            srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if whole:
            A.forget_instance(target)
        srv.stop_quietly()
    return 0
