"""The terminal session without a terminal: it reads lines from a reader, writes through a view, and works on the
projects of a workspace through an in-process watch server, so a window opened on that server shares its
conversations."""
from __future__ import annotations

import difflib
import os
import queue
import re
import signal
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .. import __version__
from ..watch import chat as C
from ..watch import presence as P
from ..watch import server as W
from ..workspace import WorkspaceError
from . import i18n, places

TICK_S = 0.1
LOST_S = 10.0                           # a turn over this long without its end note shown: stop waiting anyway
_BLOCK_MARK = re.compile(r"^\s*(#{1,6}|[-*+]|\d+[.)]|>)\s+")
_INLINE_MARK = re.compile(r"\*\*|`")
STATUS_S = 0.25
RECENT_ROWS = 4
ACTION_WAIT_S = 3 * 3600
TITLE_CELLS = 36
COMMANDS = ("help", "projects", "open", "new", "status", "stop", "check", "render", "undo", "redo", "accept",
            "window", "engine", "lang", "quit")
# tool names as the engines call them -> the key of their phrase
TOOL_KEYS = {"read_file": "read", "Read": "read", "write_file": "write", "Write": "write", "edit_file": "write_edit",
             "Edit": "write_edit", "MultiEdit": "write_edit", "glob": "find", "Glob": "find", "grep": "find",
             "Grep": "find", "list_dir": "find", "LS": "find", "web_fetch": "web_fetch", "WebFetch": "web_fetch",
             "web_search": "search", "WebSearch": "search", "Bash": "shell", "TodoWrite": "plan", "Task": "task"}


def cells(text: str) -> int:
    from rich.cells import cell_len
    return cell_len(text)


def fit(text: str, width: int) -> str:
    """text cut to `width` terminal cells (an ellipsis marks the cut)."""
    if cells(text) <= width:
        return text
    out, used = "", 0
    for ch in text:
        w = cells(ch)
        if used + w > width - 1:
            break
        out, used = out + ch, used + w
    return out + "…"


def pad(text: str, width: int, right: bool = False) -> str:
    gap = " " * max(0, width - cells(text))
    return gap + text if right else text + gap


class Session:
    def __init__(self, start, view, reader, *, lang: str | None = None, engine: str | None = None,
                 chat_options: dict | None = None, open_window=None, window_ok=None, today=None):
        self.start = Path(start or os.getcwd())
        self.view, self.reader = view, reader
        self.t = i18n.Texts(i18n.choose(lang))
        if hasattr(view, "set_marks"):
            view.set_marks(self.t("mark.ok"), self.t("mark.failed"))
        self.engine_flag = engine
        self.chat_options = chat_options or {}
        self._open_window, self._window_ok = open_window, window_ok
        self.today = today
        self.srv: W.WatchServer | None = None
        self.place: places.Place | None = None
        self.ws = None
        self.current: str | None = None         # the open project's name (None: the project the server serves)
        self.at_home = False
        self.listing: list[dict] = []
        self.engine: str | None = None
        self.events: queue.Queue = queue.Queue()
        self._wrapped: set = set()
        self._own: dict = {}                    # project -> the message this session just sent there
        self._started: dict = {}                # (project, turn) -> when its request was seen
        self._calls: dict = {}                  # (project, row id) -> when the tool call started
        self._printed: set = set()
        self._lock = threading.Lock()
        self._waiting: tuple | None = None      # (project, turn) the prompt waits for; turn None until it is known
        self._ended: set = set()                # (project, turn) whose end note was heard
        self._done = threading.Event()
        self._interrupts = 0
        self._pressed = 0                       # Ctrl+C presses counted while a wait holds the signal
        self._pumping = False
        self._live = False                      # a wait shows the status line
        self._acting: tuple | None = None       # (project,) whose action the prompt waits for
        self._seen_action: dict = {}            # project -> the last action result already shown
        self._stop_pump = threading.Event()
        self._pump: threading.Thread | None = None
        self._last_status: str | None = None
        self._recorded: Path | None = None
        self.window = None                      # the window process this session opened
        self.quit_presses = 0

    # ------------------------------------------------------------------ start and stop
    def run(self) -> int:
        try:
            if not self.begin():
                return 1
            self.loop()
            return 0
        finally:
            self.close()

    def begin(self) -> bool:
        t = self.t
        try:
            self.place = places.locate(self.start)
        except WorkspaceError as exc:
            self.view.error(t("start.bad_workspace", error=str(exc)))
            return False
        if self.place.kind == "none":
            self.view.line(t("start.none", path=str(self.place.path)))
            if not self.ask_yes(t("start.create_ask", path=str(self.place.path))):
                self.view.line(t("start.not_created"))
                return False
            try:
                places.create_workspace(self.place.path, places.film_locale(t.code))
                self.place = places.locate(self.place.path)
            except (OSError, WorkspaceError) as exc:
                self.view.error(t("start.create_failed", error=str(exc)))
                return False
            self.view.line(t("start.created", path=str(self.place.path)))
        self.ws = self.place.workspace
        if self.place.kind == "project" and not self.place.listed:
            target = self.place.project
        else:
            target = self.ws.root
        try:
            self.srv = W.serve(target, chat_options=self.chat_options or None)
        except (ValueError, WorkspaceError, OSError) as exc:
            self.view.error(t("start.serve_failed", error=str(exc)))
            return False
        self._pump = threading.Thread(target=self._pump_loop, name="reelsmith-term-pump", daemon=True)
        self._pump.start()
        self.engine = self._engine_default()
        self.header()
        if self.place.kind == "project":
            name = self.place.project.name if self.place.listed else None
            if not self.open_project(name):
                if not self.home_available:
                    return False
                self.home()
        else:
            self.home()
        return True

    def close(self) -> None:
        """Stop the server (and its running turns) and the window child, whatever Ctrl+C does meanwhile."""
        with self._presses():
            self._settle()
            self._stop_pump.set()
            before = self._pressed
            srv, self.srv = self.srv, None
            if srv is not None:
                if any(s.chat_busy is not None for s in list(srv.sites.values())):
                    self._calm(self.view.line, self.t("quit.stopping"))
                self._calm(self._forget_presence)
                self._finish(lambda: _quietly(srv.stop), before)
            self._finish(self._end_window, before)

    def _settle(self, timeout: float = 1.0) -> None:
        """Let the pump show what was already heard before it stops."""
        until = time.monotonic() + timeout
        while (not self.events.empty() or self._pumping) and time.monotonic() < until:
            try:
                time.sleep(0.02)
            except KeyboardInterrupt:
                self._pressed += 1

    def _finish(self, work, before: int) -> None:
        """work() in a thread of its own, so a press only gets one line saying the session is closing."""
        job = threading.Thread(target=work, name="reelsmith-term-close", daemon=True)
        self._calm(job.start)
        told = False
        while job.is_alive():
            try:
                job.join(TICK_S)
            except KeyboardInterrupt:
                self._pressed += 1
            if self._pressed > before and not told:
                told = True
                self._calm(self.view.line, self.t("quit.closing"))

    def _end_window(self) -> None:
        proc = self.window
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        wait = getattr(proc, "wait", None)
        if wait is not None:
            try:
                wait(5)
            except Exception:  # noqa: BLE001 - a child that ignores terminate is killed
                getattr(proc, "kill", lambda: None)()

    @contextmanager
    def _presses(self):
        """Ctrl+C counted in self._pressed instead of raised, while the block runs (main thread only)."""
        if threading.current_thread() is not threading.main_thread():
            yield
            return
        try:
            previous = signal.signal(signal.SIGINT, self._on_press)
        except (ValueError, OSError, TypeError):
            yield
            return
        try:
            yield
        finally:
            try:
                signal.signal(signal.SIGINT, previous if previous is not None else signal.default_int_handler)
            except (ValueError, OSError, TypeError):
                pass

    def _on_press(self, signum, frame) -> None:
        self._pressed += 1

    def _calm(self, fn, *args):
        """fn(*args), run again after a Ctrl+C that reached it (a thread that cannot hold the signal)."""
        while True:
            try:
                return fn(*args)
            except KeyboardInterrupt:
                self._pressed += 1

    @property
    def home_available(self) -> bool:
        return self.srv is not None and self.srv.workspace is not None

    # ------------------------------------------------------------------ engines and the header
    def engines(self) -> list[dict]:
        return C.engine_rows(self.ws, self.chat_options.get("engines_fn"))

    def why(self, row: dict) -> str:
        """An engine row's reason in the interface language."""
        key = "why." + str(row.get("code") or "")
        return self.say_code(key, row.get("params") or {}) if self.t.has(key) else str(row.get("why") or "")

    def join(self, items) -> str:
        return self.t("list.sep").join(items)

    def _engine_default(self) -> str | None:
        rows = self.engines()
        if self.engine_flag:
            row = next((r for r in rows if r["id"] == self.engine_flag), None)
            if row is None:
                self.view.warn(self.t("engine.unknown", engine=self.engine_flag, ids=self.join(C.ENGINE_ORDER)))
            elif not row["available"]:
                self.view.warn(self.t("engine.cannot", engine=row["id"], why=self.why(row)))
            else:
                return row["id"]
        return C.default_engine(rows, self.ws)

    def header(self) -> None:
        t = self.t
        rows = [(t("head.workspace"), str(self.ws.root) if self.ws else t("head.no_workspace"))]
        engines = self.engines()
        chosen = next((r for r in engines if r["id"] == self.engine), None)
        if chosen:
            rows.append((t("head.engine"), f"{chosen['label']} · {self.why(chosen)}"))
        else:
            rows.append((t("head.engine"), t("head.no_engine")))
        rows.append((t("head.language"), i18n.LANGUAGES.get(t.code, t.code)))
        self.view.header(f"reelsmith {__version__}", rows)
        if chosen is None:
            self.view.warn(t("engine.none_intro"))
            self.engine_reasons(engines)
            self.view.line(t("engine.none_next"), style="dim")
        self.view.line(t("head.hint"), style="dim")

    def engine_reasons(self, rows: list[dict]) -> None:
        for r in rows:
            self.view.line(f"  {pad(r['id'], 10)} {self.why(r)}")

    # ------------------------------------------------------------------ the loop
    def prompt_text(self) -> str:
        return f"{self.current_name()} › " if self.in_project else "reelsmith › "

    @property
    def in_project(self) -> bool:
        return not self.at_home and self.srv is not None

    def current_name(self) -> str:
        if self.current is not None:
            return self.current
        return self.srv.target.name if self.srv else ""

    def loop(self) -> None:
        while True:
            try:
                line = self.reader(self.prompt_text(), self)
            except EOFError:
                return
            except KeyboardInterrupt:
                self.quit_presses += 1
                if self.quit_presses >= 2:
                    return
                self.view.line(self.t("quit.again"), style="dim")
                continue
            self.quit_presses = 0
            if line is None:
                return
            text = line.strip()
            if not text:
                continue
            if text.startswith("/"):
                if self.command(text) == "quit":
                    return
            elif self.at_home:
                if self.home_input(text) == "quit":
                    return
            else:
                self.send(text)

    def ask_yes(self, question: str, default: bool = False) -> bool:
        try:
            answer = self.reader(f"{question} ", self)
        except (EOFError, KeyboardInterrupt):
            return False
        answer = str(answer or "").strip().lower()
        if not answer:
            return default
        return answer in self.t("yes.words").split(",")

    # ------------------------------------------------------------------ the home
    def films(self) -> list[dict]:
        """The server's list of the workspace's films (the window's order), as the home shows them."""
        out = []
        for r in self.srv.projects():
            result = r.get("result") or {}
            try:
                changed = datetime.fromisoformat(r["modified"]).timestamp() if r.get("modified") else 0.0
            except ValueError:
                changed = 0.0
            out.append({"name": r["name"], "title": r.get("title") or "", "duration": r.get("duration"),
                        "state": "accepted" if result.get("accepted") else str(result.get("state") or "none"),
                        "changed": changed})
        return out

    def home(self) -> None:
        t = self.t
        if not self.home_available:
            self.view.line(t("home.unavailable"))
            return
        self._forget_presence()
        self.at_home, self.current = True, None
        self.listing = self.films()
        self.view.line("")
        self.view.title(t("home.title", workspace=self.ws.root.name))
        if not self.listing:
            self.view.line(t("home.empty"))
            return
        heads = [t("col.n"), t("col.name"), t("col.title"), t("col.length"), t("col.film"), t("col.changed")]
        rows = []
        for i, p in enumerate(self.listing, 1):
            rows.append([str(i), p["name"], fit(p["title"], TITLE_CELLS), self.length(p["duration"]),
                         t(f"film.{p['state']}"), self.ago(p["changed"])])
        self.view.table(heads, rows, right=(0, 3), states=[p["state"] for p in self.listing])
        self.view.line(t("home.hint"), style="dim")

    def words(self, key: str) -> set:
        """The bare words a command answers to: English and the interface language's."""
        both = f"{self.t.base.get(key, '')},{self.t(key)}"
        return {w.strip().lower() for w in both.split(",") if w.strip()}

    def home_input(self, text: str) -> str | None:
        """Text typed at the home: never a paid request unless the person confirms a new film."""
        t = self.t
        low = text.lower()
        if low in self.words("words.quit"):
            return "quit"
        if low in self.words("words.help"):
            self.cmd_help("")
            return None
        if text.isdigit():
            found = self.find_project(text)
            if found:
                self.open_project(found)
            else:
                self.view.warn(t("home.no_number", n=text))
            return None
        found = self.find_project(text)
        if found:
            self.open_project(found)
            return None
        if places.valid_name(text):
            self.view.warn(t("home.no_film", name=text))
            return None
        name = places.new_name(self.ws, text, self.today)
        if not self.ask_yes(t("new.confirm", name=name), default=True):
            self.view.line(t("new.not_created"))
            return None
        self.new_film(text, name)
        return None

    def find_project(self, text: str) -> str | None:
        if not self.home_available:
            return None
        if not self.listing:
            self.listing = self.films()
        if text.isdigit():
            n = int(text)
            return self.listing[n - 1]["name"] if 1 <= n <= len(self.listing) else None
        low = text.lower()
        return next((p["name"] for p in self.listing if p["name"].lower() == low), None)

    def new_film(self, text: str, name: str | None = None) -> bool:
        """A film made by the server (its names, its lock), opened, and the text sent as its first request."""
        t = self.t
        if not self.home_available:
            self.view.warn(t("new.no_workspace"))
            return False
        if name is None:
            name = places.new_name(self.ws, text, self.today)
        try:
            self.srv.create_project(name)
        except W.HTTPError as exc:
            self.view.warn(self.refusal(exc))
            return False
        self.listing = []
        self.view.line(t("new.created", name=name), style="ok")
        if not self.open_project(name):
            return False
        if text:
            self.send(text)
        return True

    # ------------------------------------------------------------------ a project
    def site(self, name: str | None = None):
        site = self.srv.site(name)
        if id(site) not in self._wrapped:
            self._wrapped.add(id(site))
            with self._lock:
                self._seen_action.setdefault(name, site.last_action)
            original = site.chat.notify

            def heard(payload, _name=name, _orig=original):
                if _orig is not None:
                    _orig(payload)
                self.events.put((_name, payload))
            site.chat.notify = heard
        return site

    def project_root(self, name: str | None) -> Path:
        return self.srv.target if name is None else self.srv.project_dir(name)

    def open_project(self, name: str | None) -> bool:
        t = self.t
        try:
            root = self.project_root(name)
        except W.HTTPError:
            self.view.warn(t("open.none", name=str(name)))
            return False
        other = P.window_of(root)
        if other and other.get("pid") != os.getpid():
            self.view.warn(t("open.other_window", name=root.name, url=str(other.get("url") or ""),
                             pid=str(other.get("pid"))))
            self.view.line(t("open.other_next"), style="dim")
            return False
        self._forget_presence()
        site = self.site(name)
        self.current, self.at_home = name, False
        try:
            P.record_window(root, self.url_for(name))
            self._recorded = root
        except OSError:
            self._recorded = None
        row = self.srv.project_row(root)
        result = row.get("result") or {}
        state = "accepted" if result.get("accepted") else str(result.get("state") or "none")
        try:
            changed = datetime.fromisoformat(row["modified"]).timestamp() if row.get("modified") else 0.0
        except ValueError:
            changed = 0.0
        self.view.line("")
        self.view.title(f"{root.name}" + (f" · {row['title']}" if row.get("title") else ""))
        self.view.line(f"{t('col.length')} {self.length(row.get('duration'))} · {t('col.film')} "
                       f"{t('film.' + state)} · {t('col.changed')} {self.ago(changed)}")
        self.recent(site)
        busy = site.chat_busy
        if busy is not None:
            self.view.line(t("open.busy", turn=busy))
        self.view.line(t("open.hint"), style="dim")
        return True

    def recent(self, site) -> None:
        rows = [r for r in site.chat.rows if r.get("role") in ("user", "assistant")][-RECENT_ROWS:]
        if not rows:
            return
        self.view.line(self.t("open.recent"))
        width = getattr(self.view, "width", 100)
        for r in rows:
            who = self.t("who.you") if r["role"] == "user" else self.t("who.agent")
            head = "  " + self.t("who.says", who=who)
            self.view.line(head + fit(plain_text(str(r.get("text") or "")), max(20, width - cells(head) - 1)))

    def url_for(self, name: str | None) -> str:
        return self.srv.url + (f"p/{name}/" if name is not None else "")

    def _forget_presence(self) -> None:
        if self._recorded is not None:
            try:
                P.forget_window(self._recorded)
            except OSError:
                pass
            self._recorded = None

    # ------------------------------------------------------------------ a request
    def send(self, text: str) -> None:
        t = self.t
        site = self.site(self.current)
        if self.engine is None:
            self.view.warn(t("code.chat.no_engine"))
            self.engine_reasons(self.engines())
            return
        name = self.current
        with self._presses():
            # waiting before the call: a turn that fails at once may end before send_chat returns
            with self._lock:
                self._waiting = (name, None)
                self._done.clear()
            self._own[name] = text.strip()
            try:
                turn = site.send_chat(text, self.engine, None)
            except W.HTTPError as exc:
                self._own.pop(name, None)
                with self._lock:
                    self._waiting = None
                self.view.warn(self.refusal(exc))
                return
            with self._lock:
                self._waiting = (name, turn)
                if (name, turn) in self._ended:
                    self._done.set()
            self._started.setdefault((name, turn), time.monotonic())
            self._wait_turn(name, site, turn)

    def _note_shown(self, name, site, turn: int) -> bool:
        rows = list(site.chat.rows)
        return any(r.get("role") == "note" and r.get("turn") == turn and (name, r.get("id")) in self._printed
                   for r in rows)

    def _wait_turn(self, name, site, turn: int) -> None:
        handled = self._pressed
        self._interrupts = 0
        self._last_status = None
        self._calm(self.view.begin_wait, self.t("status.thinking"))
        self._live = True
        idle_since = None
        try:
            while not self._done.is_set():
                try:
                    self.wait_once()
                except KeyboardInterrupt:
                    self._pressed += 1
                while handled < self._pressed:
                    handled += 1
                    self._calm(self.interrupt)
                if site.chat_busy != turn and self.events.empty() and not self._pumping:
                    idle_since = idle_since or time.monotonic()
                    # the end note shown, or never coming: the prompt returns either way
                    if self._note_shown(name, site, turn) or time.monotonic() - idle_since >= LOST_S:
                        break
                else:
                    idle_since = None
        finally:
            self._live = False
            self._calm(self.view.end_wait)
            with self._lock:
                self._waiting = None

    def wait_once(self) -> None:
        self._done.wait(TICK_S)

    def interrupt(self) -> None:
        site = self.site(self.current)
        self._interrupts += 1
        if self._interrupts > 1 or (site.chat_busy is not None and site.chat.stopping):
            self.view.line(self.t("turn.still_stopping"))
            return
        code, body = site.act("stop")
        self.view.line(self.t("turn.stopping") if body.get("stopped") else self.t("code." + body.get("code", "")),
                       style="warn")

    def say_code(self, key: str, params: dict) -> str:
        """A coded sentence with its params; a {side} is translated too."""
        p = {k: str(v) for k, v in params.items()}
        side = p.get("side")
        if side and self.t.has("side." + side):
            p["side"] = self.t("side." + side)
        return self.t(key, **p)

    def refusal(self, exc: W.HTTPError) -> str:
        body = exc.body or {}
        code = body.get("code")
        params = dict(body.get("params") or {})
        if code == "chat.engine_unavailable":
            row = next((r for r in self.engines() if r["id"] == params.get("engine")), None)
            if row is not None:
                params["why"] = self.why(row)
        if code and self.t.has("code." + code):
            return self.say_code("code." + code, params)
        return str(body.get("error") or exc)

    # ------------------------------------------------------------------ what the chat says
    def _pump_loop(self) -> None:
        next_status = 0.0
        while not self._stop_pump.is_set():
            try:
                name, payload = self.events.get(timeout=TICK_S)
            except queue.Empty:
                pass
            else:
                self._pumping = True
                try:
                    self.heard(name, payload)
                except Exception as exc:  # noqa: BLE001 - one bad row must not end the session's output
                    self.view.error(f"{type(exc).__name__}: {exc}")
                finally:
                    self._pumping = False
            if time.monotonic() >= next_status:
                next_status = time.monotonic() + STATUS_S
                try:
                    self.tick_status()
                    self.check_actions()
                except Exception:  # noqa: BLE001 - the status line is a courtesy
                    pass

    def heard(self, name, payload: dict) -> None:
        t = self.t
        mine = name == self.current and self.in_project
        for row in payload.get("rows") or []:
            role, turn = row.get("role"), row.get("turn")
            if not mine:
                if role == "note":
                    kind = str(row.get("kind") or "end")
                    what = t("note." + kind) if t.has("note." + kind) else str(row.get("text") or "")
                    self.view.line(t("other.note", name=str(name or self.current_name()), what=what))
                    self._turn_ended(name, turn)
                continue
            key = (name, row.get("id"))
            if role == "user":
                self._started.setdefault((name, turn), time.monotonic())
                if self._own.get(name) == str(row.get("text") or "").strip():
                    self._own.pop(name, None)
                elif key not in self._printed:
                    self._printed.add(key)
                    self.view.user(row.get("text") or "", t("who.says", who=t("who.window")))
            elif role == "assistant":
                if key not in self._printed:
                    self._printed.add(key)
                    self.view.say(str(row.get("text") or ""))
            elif role == "tool":
                self.tool_row(name, row)
            elif role == "note":
                if key not in self._printed:
                    self._printed.add(key)
                    self.summary(name, row)
                self._turn_ended(name, turn)

    def _turn_ended(self, name, turn) -> None:
        """After its summary is shown: the prompt waiting for this turn may return."""
        with self._lock:
            self._ended.add((name, turn))
            if self._waiting == (name, turn):
                self._done.set()

    def tool_row(self, name, row: dict) -> None:
        key = (name, row.get("id"))
        if row.get("ok") is None:
            self._calls.setdefault(key, time.monotonic())
            return
        if key in self._printed:
            return
        self._printed.add(key)
        began = self._calls.pop(key, None)
        elapsed = None if began is None else time.monotonic() - began
        tool = str(row.get("tool") or "")
        detail = str(row.get("detail") or "")
        failed = row.get("ok") is False
        self.view.tool(bool(row.get("ok")), self.tool_phrase(tool), str(row.get("text") or ""),
                       self.seconds(elapsed) if elapsed is not None else "",
                       first_line(detail) if failed else "")
        if failed and tool == "render":
            self.refused_render(name)

    def refused_render(self, name) -> None:
        site = self.srv.sites.get(name) or self.site(name)
        res = site.state().get("result") or {}
        if res.get("state") == "refused":
            self.view.warn(self.t("render.refused", reason=self.result_reason(res)))
        self.view.line(self.t("render.refused_next"), style="dim")

    def result_reason(self, res: dict) -> str:
        code = res.get("reason_code") or ""
        if self.t.has("code." + code):
            return self.say_code("code." + code, res.get("params") or {})
        return str(res.get("reason") or "")

    def tool_phrase(self, tool: str) -> str:
        key = "tool." + TOOL_KEYS.get(tool, tool)
        return self.t(key) if self.t.has(key) else self.t("tool.other", tool=tool)

    def summary(self, name, row: dict) -> None:
        t = self.t
        kind = row.get("kind") or "end"
        began = self._started.pop((name, row.get("turn")), None)
        took = self.seconds(time.monotonic() - began) if began is not None else ""
        cost = self.money(row.get("cost_usd"))
        spent, budget = row.get("spent_usd"), row.get("budget_usd")
        params = row.get("params") or {}
        if kind == "budget":
            self.view.warn(t("turn.budget", budget=self.money(budget), spent=self.money(spent)))
            self.view.line(t("turn.budget_next"), style="dim")
            return
        if kind == "error":
            self.view.error(t("turn.error", error=str(params.get("error") or row.get("text") or "")))
            self.view.line(t("turn.error_next"), style="dim")
            return
        head = {"end": "turn.end", "stopped": "turn.stopped", "aborted": "turn.aborted"}.get(kind, "turn.end")
        parts = [t(head, took=took, reason=str(params.get("reason") or "")), t("turn.cost", cost=cost)]
        if spent is not None and budget is not None:
            parts.append(t("turn.spent", spent=self.money(spent), budget=self.money(budget)))
        self.view.summary(" · ".join(p for p in parts if p), kind)
        if row.get("budget_used_up"):
            self.view.warn(t("turn.budget_now", budget=self.money(budget)))
            self.view.line(t("turn.budget_next"), style="dim")

    def tick_status(self) -> None:
        """The live status line, only while the prompt waits; at the prompt an end shows as one line instead."""
        site = self.srv.sites.get(self.current) if self.srv is not None and self.in_project else None
        if not self._live or site is None or (site.chat_busy is None and not site.action):
            if self._last_status is not None:
                self._last_status = None
                self.view.status(None)
            return
        from ..watch import state as S
        run = S.running_view(P.running(site.root), site.running_by())
        if run is not None:
            text = self.running_text(run)
        elif site.chat_busy is not None and site.chat.stopping:
            text = self.t("status.stopping")
        elif site.action:
            text = self.tool_phrase(site.action["action"])
        else:
            text = self.t("status.thinking")
        if text != self._last_status:
            self._last_status = text
            self.view.status(text, transient=run is None)

    def check_actions(self) -> None:
        """One line for each action that ended while nobody waited for it (left running, or started in the window)."""
        if self.srv is None:
            return
        for name, site in list(self.srv.sites.items()):
            done = site.last_action
            with self._lock:
                if name not in self._seen_action:
                    self._seen_action[name] = done
                    continue
                if done is self._seen_action[name] or self._acting == (name,):
                    continue
                self._seen_action[name] = done
            if done is None:
                continue
            if name == self.current and self.in_project:
                self.action_result(name, done)
            else:
                self.view.line(self.t("other.action", name=str(name or self.current_name()),
                                      what=self.action_text(done)))

    def running_text(self, run: dict) -> str:
        t = self.t
        tool = str(run.get("tool") or "")
        key = "run." + tool
        text = t(key) if t.has(key) else t("run.other", tool=tool)
        stage = run.get("stage")
        if stage:
            skey = "stage." + str(stage).replace(" ", "_")
            text += ": " + (t(skey) if t.has(skey) else str(stage))
        if run.get("percent") is not None:
            text += f" ({run['percent']} %)"
        return text

    # ------------------------------------------------------------------ commands
    def command(self, text: str) -> str | None:
        word, _, arg = text[1:].partition(" ")
        word, arg = word.strip().lower(), arg.strip()
        if word not in COMMANDS:
            near = difflib.get_close_matches(word, COMMANDS, n=1, cutoff=0.4)
            self.view.warn(self.t("cmd.unknown_near", word="/" + word, near="/" + near[0]) if near
                           else self.t("cmd.unknown", word="/" + word))
            return None
        if word == "quit":
            return "quit"
        getattr(self, f"cmd_{word}")(arg)
        return word

    def cmd_help(self, arg: str) -> None:
        t = self.t
        self.view.title(t("help.title"))
        width = max(cells(self.usage(c)) for c in COMMANDS)
        for c in COMMANDS:
            self.view.line(f"  {pad(self.usage(c), width)}  {t('help.' + c)}")
        self.view.line("")
        self.view.title(t("help.keys"))
        for k in ("keys.enter", "keys.tab", "keys.history", "keys.stop", "keys.action", "keys.quit"):
            self.view.line(f"  {t(k)}")
        self.view.line("")
        self.view.line(t("help.text_home") if self.at_home else t("help.text_project"), style="dim")

    def usage(self, command: str) -> str:
        args = {"open": " N|NAME", "new": " [NAME]", "engine": " [ID]", "lang": " [CODE]"}
        return "/" + command + args.get(command, "")

    def cmd_projects(self, arg: str) -> None:
        if not self.home_available:
            self.view.warn(self.t("home.unavailable"))
            return
        self.home()

    def cmd_open(self, arg: str) -> None:
        if not arg:
            self.view.warn(self.t("open.usage"))
            return
        found = self.find_project(arg)
        if not found:
            self.view.warn(self.t("open.none", name=arg) if self.home_available else self.t("home.unavailable"))
            return
        self.open_project(found)

    def cmd_new(self, arg: str) -> None:
        self.new_film("", arg or None)

    def need_project(self) -> bool:
        if self.in_project:
            return True
        self.view.warn(self.t("cmd.need_project"))
        return False

    def cmd_status(self, arg: str) -> None:
        if not self.need_project():
            return
        t = self.t
        site = self.site(self.current)
        st = site.state()
        summ = st.get("summary") or {}
        res = st.get("result") or {}
        spend = st.get("spend") or {}
        state = "accepted" if res.get("accepted") else res.get("state") or "none"
        self.view.title(t("status.title", name=self.current_name()))
        rows = [(t("col.length"), self.length(st.get("duration"))),
                (t("status.beats"), str(len(st.get("beats") or []))),
                (t("status.issues"), t("status.issue_counts", errors=summ.get("errors", 0),
                                       warnings=summ.get("warnings", 0))),
                (t("col.film"), t("film." + state) + ("" if state in ("none", "accepted") else
                                                      f" · {self.result_reason(res)}")),
                (t("status.chat_spend"), self.spend(spend.get("chat_usd"), spend.get("chat_budget_usd"))),
                (t("status.project_spend"), self.spend(spend.get("project_usd"), spend.get("project_budget_usd")))]
        if not st.get("valid"):
            rows.append((t("status.error"), str(st.get("error") or "")))
        width = max(cells(k) for k, _ in rows)
        for k, v in rows:
            self.view.line(f"  {pad(k, width)}  {v}")
        if site.chat_busy is not None:
            self.view.line(t("open.busy", turn=site.chat_busy))

    def spend(self, spent, budget) -> str:
        if spent is None:
            return self.t("status.unknown")
        if budget is None:
            return self.money(spent)
        return self.t("turn.spent", spent=self.money(spent), budget=self.money(budget))

    def cmd_stop(self, arg: str) -> None:
        """Stop the request running on the open film, whether the terminal or the window started it."""
        if not self.need_project():
            return
        site = self.site(self.current)
        code, body = site.act("stop")
        if body.get("stopped"):
            self.view.line(self.t("turn.stopping"), style="warn")
        else:
            self.view.line(self.t("code." + str(body.get("code") or "stop.idle")))

    def cmd_check(self, arg: str) -> None:
        self.act("check")

    def cmd_render(self, arg: str) -> None:
        self.act("render")

    def cmd_undo(self, arg: str) -> None:
        self.act("undo")

    def cmd_redo(self, arg: str) -> None:
        self.act("redo")

    def pause(self) -> None:
        time.sleep(TICK_S)

    def act(self, name: str) -> None:
        """The window's action; Ctrl+C once says it cannot be interrupted, twice returns to the prompt."""
        if not self.need_project():
            return
        t = self.t
        key = self.current
        site = self.site(key)
        with self._presses():
            with self._lock:
                self._seen_action[key] = site.last_action
                self._acting = (key,)
            try:
                site.act(name)
            except W.HTTPError as exc:
                with self._lock:
                    self._acting = None
                self.view.warn(self.refusal(exc))
                return
            handled, presses, left = self._pressed, 0, False
            self._last_status = None
            self._calm(self.view.begin_wait, self.tool_phrase(name))
            self._live = True
            until = time.monotonic() + ACTION_WAIT_S
            try:
                while site.action and time.monotonic() < until and not left:
                    try:
                        self.pause()
                    except KeyboardInterrupt:
                        self._pressed += 1
                    while handled < self._pressed:
                        handled += 1
                        presses += 1
                        if presses == 1:
                            self._calm(self.view.line, t("act.cannot_stop"), "warn")
                        else:
                            left = True
            finally:
                self._live = False
                self._calm(self.view.end_wait)
                with self._lock:
                    self._acting = None
                    done = None if left else site.last_action
                    if not left:
                        self._seen_action[key] = done
        if left:
            self.view.line(t("act.background"))
            return
        self.action_result(key, done or {})

    def action_text(self, done: dict) -> str:
        code = str(done.get("code") or "")
        return self.t("code." + code) if self.t.has("code." + code) else str(done.get("text") or "")

    def action_result(self, name, done: dict) -> None:
        ok = bool(done.get("ok"))
        self.view.tool(ok, self.action_text(done), "", "", "")
        detail = str(done.get("detail") or "").strip()
        if detail:
            self.view.detail(detail)
        if done.get("action") == "render" and not ok:
            self.refused_render(name)

    def cmd_accept(self, arg: str) -> None:
        if not self.need_project():
            return
        try:
            self.site(self.current).accept()
        except W.HTTPError as exc:
            self.view.warn(self.refusal(exc))
            return
        self.view.line(self.t("accept.done"), style="ok")

    def cmd_window(self, arg: str) -> None:
        t = self.t
        name = self.current if self.in_project else None
        url = self.url_for(name) if self.in_project else self.srv.url
        if self.window is not None and self.window.poll() is None:
            self.view.line(t("window.already", url=url))
            return
        ok = self._window_ok() if self._window_ok else _window_available()
        if not ok:
            self.view.line(t("window.browser", url=url))
            return
        title = f"reelsmith · {self.current_name() if self.in_project else (self.ws.root.name if self.ws else '')}"
        try:
            self.window = (self._open_window or _launch_window)(url, title)
        except OSError as exc:
            self.view.warn(t("window.failed", error=str(exc), url=url))
            return
        self.view.line(t("window.opened", url=url), style="ok")

    def cmd_engine(self, arg: str) -> None:
        t = self.t
        rows = self.engines()
        if not arg:
            self.view.title(t("engine.title"))
            for r in rows:
                mark = "*" if r["id"] == self.engine else " "
                state = t("engine.ready") if r["available"] else t("engine.unavailable")
                self.view.line(f" {mark} {pad(r['id'], 10)} {pad(r['label'], 20)} {state} · {self.why(r)}")
            self.view.line(t("engine.hint"), style="dim")
            return
        row = next((r for r in rows if r["id"] == arg.lower()), None)
        if row is None:
            self.view.warn(t("engine.unknown", engine=arg, ids=self.join(C.ENGINE_ORDER)))
        elif not row["available"]:
            self.view.warn(t("engine.cannot", engine=row["id"], why=self.why(row)))
        else:
            self.engine = row["id"]
            self.view.line(t("engine.set", label=row["label"]), style="ok")

    def cmd_lang(self, arg: str) -> None:
        t = self.t
        if not arg:
            self.view.title(t("lang.title"))
            for code in i18n.available():
                mark = "*" if code == t.code else " "
                self.view.line(f" {mark} {pad(code, 6)} {i18n.LANGUAGES[code]}")
            self.view.line(t("lang.hint"), style="dim")
            return
        code = i18n.match(arg)
        if code is None:
            self.view.warn(t("lang.unknown", code=arg, codes=self.join(i18n.available())))
            return
        t.set(code)
        if hasattr(self.view, "set_marks"):
            self.view.set_marks(t("mark.ok"), t("mark.failed"))
        try:
            i18n.save_setting("lang", code)
        except OSError as exc:
            self.view.warn(t("lang.not_saved", error=str(exc)))
        self.view.line(t("lang.set", name=i18n.LANGUAGES[code]), style="ok")

    # ------------------------------------------------------------------ words
    def seconds(self, s: float | None) -> str:
        if s is None:
            return ""
        if s < 10:
            return self.t("unit.s1", n=f"{s:.1f}")
        if s < 60:
            return self.t("unit.s", n=int(round(s)))
        m, sec = divmod(int(round(s)), 60)
        return self.t("unit.min_s", m=m, s=sec)

    def length(self, d) -> str:
        if not isinstance(d, (int, float)):
            return "–"
        m, s = divmod(int(round(d)), 60)
        return f"{m}:{s:02d}"

    def money(self, usd) -> str:
        try:
            return f"${float(usd):.2f}"
        except (TypeError, ValueError):
            return "–"

    def ago(self, ts: float) -> str:
        if not ts:
            return "–"
        s = max(0.0, places.now_ts() - ts)
        if s < 60:
            return self.t("ago.now")
        if s < 3600:
            return self.t("ago.min", n=int(s // 60))
        if s < 86400:
            return self.t("ago.h", n=int(s // 3600))
        if s < 30 * 86400:
            return self.t("ago.d", n=int(s // 86400))
        return datetime.fromtimestamp(ts).date().isoformat()

    # ------------------------------------------------------------------ completion
    def completions(self, text: str) -> list[tuple[str, str]]:
        """(completion of the whole input, its one-line help) for the text typed so far."""
        if not text.startswith("/"):
            return []
        word, space, arg = text[1:].partition(" ")
        if not space:
            return [("/" + c, self.t("help." + c)) for c in COMMANDS if c.startswith(word.lower())]
        word = word.lower()
        if word == "open" and self.home_available:
            names = [p["name"] for p in (self.listing or self.films())]
            return [(f"/open {n}", "") for n in names if n.lower().startswith(arg.lower())]
        if word == "engine":
            return [(f"/engine {e}", C.LABELS[e]) for e in C.ENGINE_ORDER if e.startswith(arg.lower())]
        if word == "lang":
            return [(f"/lang {c}", i18n.LANGUAGES[c]) for c in i18n.available() if c.lower().startswith(arg.lower())]
        return []

    def toolbar(self) -> str:
        where = self.current_name() if self.in_project else self.t("home.short")
        engine = self.engine or self.t("head.no_engine_short")
        return f" {where} · {engine} · {self.t.code} · {self.t('toolbar.help')}"

    def history_path(self) -> Path | None:
        if self.ws is not None:
            return self.ws.cache_dir / "term" / "history"
        if self.srv is not None:
            return self.srv.target / "build" / "term" / "history"
        return None


def plain_text(markdown: str) -> str:
    """One line without Markdown marks (headings, list bullets, emphasis, code ticks)."""
    lines = [_BLOCK_MARK.sub("", ln) for ln in markdown.splitlines()]
    return " ".join(_INLINE_MARK.sub("", " ".join(lines)).split())


def first_line(text: str, limit: int = 160) -> str:
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return fit(line, limit)


def _quietly(fn) -> None:
    try:
        fn()
    except Exception:  # noqa: BLE001 - leaving must not fail
        pass


def _window_available() -> bool:
    from ..watch import window
    return window.available()


def _launch_window(url: str, title: str):
    from .window import launch
    return launch(url, title)
