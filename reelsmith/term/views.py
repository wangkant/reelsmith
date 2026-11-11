"""How the session's output looks: PlainView writes lines without colour or live regions (pipes, tests, --plain);
RichView uses rich for colour, Markdown and a live status line while a request runs."""
from __future__ import annotations

import re
import shutil
import sys
import threading

from .session import cells, pad

_PERCENT = re.compile(r" \((\d+) %\)$")
DETAIL_LINES = 12
REPROMPT_S = 0.15                       # output from another thread settles before the prompt is shown again


def detail_lines(text: str) -> list[str]:
    """At most DETAIL_LINES lines; a last line counts the ones left out."""
    lines = text.splitlines()
    if len(lines) <= DETAIL_LINES:
        return lines
    return lines[:DETAIL_LINES - 1] + [f"… (+{len(lines) - DETAIL_LINES + 1})"]


def column_widths(heads: list[str], rows: list[list[str]]) -> list[int]:
    return [max(cells(str(r[i])) for r in [heads, *rows]) for i in range(len(heads))]


def table_lines(heads: list[str], rows: list[list[str]], right=(), widths: list[int] | None = None) -> list[str]:
    """Columns aligned by terminal cells, so CJK text lines up."""
    widths = widths or column_widths(heads, rows)
    return ["  ".join(pad(str(v), widths[i], i in right) for i, v in enumerate(r)).rstrip() for r in [heads, *rows]]


class PlainView:
    def __init__(self, out=None, ok: str = "[ok]", failed: str = "[failed]"):
        self.out = out
        self.marks = (ok, failed)
        self._lock = threading.Lock()
        self._status: tuple[str, int] | None = None
        self._prompt: str | None = None         # the prompt a reader waits at
        self._broken = False                    # output from another thread moved the cursor off that prompt
        self._timer: threading.Timer | None = None

    def set_marks(self, ok: str, failed: str) -> None:
        self.marks = (ok, failed)

    @property
    def width(self) -> int:
        return shutil.get_terminal_size((100, 24)).columns if self.out is None else 100

    @property
    def stream(self):
        return self.out or sys.stdout

    # ---- the prompt, shared with PlainReader
    def prompting(self, prompt: str) -> None:
        with self._lock:
            self.stream.write(prompt)
            self.stream.flush()
            self._prompt, self._broken = prompt, False

    def answered(self, echo: str | None) -> None:
        """The reader has its line; `echo` is written after the prompt when the input was not typed here."""
        with self._lock:
            self._cancel()
            if echo is not None:
                if self._broken:
                    self.stream.write(self._prompt or "")
                self.stream.write(echo + "\n")
                self.stream.flush()
            self._prompt, self._broken = None, False

    def _cancel(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _reprompt(self) -> None:
        with self._lock:
            self._timer = None
            if self._prompt is not None and self._broken:
                self.stream.write(self._prompt)
                self.stream.flush()
                self._broken = False

    def write(self, text: str) -> None:
        with self._lock:
            if self._prompt is not None and not self._broken:
                self.stream.write("\n")         # start on a line of its own, not after the waiting prompt
                self._broken = True
            self.stream.write(text + "\n")
            self.stream.flush()
            if self._prompt is not None:
                self._cancel()
                self._timer = threading.Timer(REPROMPT_S, self._reprompt)
                self._timer.daemon = True
                self._timer.start()

    def line(self, text: str, style: str | None = None) -> None:
        self.write(text)

    def title(self, text: str) -> None:
        self.write(text)

    def header(self, name: str, rows: list[tuple[str, str]]) -> None:
        self.write(name)
        width = max(cells(k) for k, _ in rows)
        for k, v in rows:
            self.write(f"  {pad(k, width)}  {v}")

    def table(self, heads, rows, right=(), states=None) -> None:
        for ln in table_lines(heads, rows, right):
            self.write(ln)

    def warn(self, text: str) -> None:
        self.write(text)

    def error(self, text: str) -> None:
        self.write(text)

    def user(self, text: str, who: str) -> None:
        """`who` is the speaker with its separator ("From the window: ")."""
        self.write(f"{who}{text}")

    def say(self, text: str) -> None:
        self.write(text.rstrip())

    def tool(self, ok: bool, phrase: str, brief: str, elapsed: str, detail: str) -> None:
        parts = [self.marks[0] if ok else self.marks[1], phrase]
        if brief:
            parts.append("· " + " ".join(brief.split()))
        if elapsed:
            parts.append(f"({elapsed})")
        self.write("  " + " ".join(parts))
        if detail:
            self.write("    " + detail)

    def detail(self, text: str) -> None:
        for ln in detail_lines(text):
            self.write("    " + ln)

    def summary(self, text: str, kind: str) -> None:
        self.write(text)

    def begin_wait(self, text: str) -> None:
        self._status = None

    def end_wait(self) -> None:
        self._status = None

    def status(self, text: str | None, transient: bool = False) -> None:
        """Only a running call's stage, and its progress in quarters: a pipe gets no live line."""
        if text is None or transient:
            return
        m = _PERCENT.search(text)
        base = text[:m.start()] if m else text
        quarter = int(m.group(1)) // 25 if m else -1
        if self._status == (base, quarter):
            return
        if self._status and self._status[0] == base and quarter < 0:
            return
        self._status = (base, quarter)
        self.write("  … " + text)


def _markdown_class():
    """rich's Markdown with every heading left-aligned (h1 is centred by default)."""
    from rich.markdown import Heading, Markdown

    class LeftHeading(Heading):
        def __rich_console__(self, console, options):
            text = self.text.copy()
            text.justify = "left"
            yield text

    class Plainer(Markdown):
        elements = {**Markdown.elements, "heading_open": LeftHeading}
    return Plainer


# readable on dark and light grounds alike: headings bold in the default colour, no fixed backgrounds
MARKDOWN_THEME = {**{f"markdown.h{i}": "bold" for i in range(1, 7)}, "markdown.h1.border": "default",
                  "markdown.code": "bold", "markdown.item.bullet": "bold", "markdown.item.number": "bold",
                  "markdown.block_quote": "italic", "markdown.link": "underline", "markdown.link_url": "underline"}


class RichView:
    STYLES = {"dim": "dim", "ok": "green", "warn": "yellow", "error": "red", None: ""}
    STATE = {"none": "", "current": "green", "stale": "yellow", "refused": "red", "accepted": "bold green"}

    def __init__(self, console=None):
        from rich.console import Console
        from rich.theme import Theme
        self.console = console or Console(highlight=False, soft_wrap=False)
        self.console.push_theme(Theme(MARKDOWN_THEME))
        self._markdown = _markdown_class()
        self._live = None
        self._status_text = ""
        self._lock = threading.RLock()
        self._last = None                       # the kind of the last thing printed

    def set_marks(self, ok: str, failed: str) -> None:
        pass

    @property
    def width(self) -> int:
        return self.console.width

    def _print(self, *items, kind: str | None = None, **kw) -> None:
        with self._lock:
            self.console.print(*items, **kw)
            self._last = kind

    def line(self, text: str, style: str | None = None) -> None:
        from rich.text import Text
        self._print(Text(text, style=self.STYLES.get(style, style or "")))

    def title(self, text: str) -> None:
        from rich.text import Text
        self._print(Text(text, style="bold"))

    def header(self, name: str, rows: list[tuple[str, str]]) -> None:
        from rich.text import Text
        self._print(Text(name, style="bold"))
        width = max(cells(k) for k, _ in rows)
        for k, v in rows:
            self._print(Text(f"  {pad(k, width)}  {v}"))

    def table(self, heads, rows, right=(), states=None) -> None:
        from rich.text import Text
        widths = column_widths(heads, rows)
        self._print(Text(table_lines(heads, [], right, widths)[0], style="bold"))
        for n, r in enumerate(rows):
            t = Text()
            for i, v in enumerate(r):
                style = ""
                if i == 1:
                    style = "bold"
                elif i == 4 and states:
                    style = self.STATE.get(states[n], "")
                elif i == 5:
                    style = "dim"               # when it changed: a secondary hint
                t.append(pad(str(v), widths[i], i in right), style=style)
                if i < len(r) - 1:
                    t.append("  ")
            t.rstrip()
            self._print(t)

    def warn(self, text: str) -> None:
        self.line(text, "warn")

    def error(self, text: str) -> None:
        self.line(text, "error")

    def user(self, text: str, who: str) -> None:
        from rich.text import Text
        t = Text(who)
        t.append(text, style="bold")
        self._print(t)

    def say(self, text: str) -> None:
        with self._lock:
            if self._last == "tool":
                self.console.print()            # a blank line between the tool rows and the reply
            self._print(self._markdown(text.strip()), kind="say")

    def tool(self, ok: bool, phrase: str, brief: str, elapsed: str, detail: str) -> None:
        from rich.text import Text
        t = Text("  ")
        t.append("✓ " if ok else "✗ ", style="green" if ok else "red")
        t.append(phrase)
        if brief:
            t.append(" · " + " ".join(brief.split()), style="dim")
        if elapsed:
            t.append(f"  {elapsed}", style="dim")
        with self._lock:
            self._print(t, kind="tool", overflow="ellipsis", no_wrap=True)
            if detail:
                self._print(Text("    " + detail, style="red"), kind="tool", overflow="ellipsis", no_wrap=True)

    def detail(self, text: str) -> None:
        from rich.text import Text
        for ln in detail_lines(text):
            self._print(Text("    " + ln), kind="tool", overflow="ellipsis", no_wrap=True)

    def summary(self, text: str, kind: str) -> None:
        from rich.rule import Rule
        from rich.text import Text
        line = {"end": "green", "stopped": "yellow", "aborted": "yellow"}.get(kind, "dim")
        self._print(Rule(Text(text), style=line, characters="─", align="left"))

    def _render(self):
        from rich.spinner import Spinner
        return Spinner("dots", text=self._status_text, style="cyan")

    def begin_wait(self, text: str) -> None:
        from rich.live import Live
        with self._lock:
            self._status_text = text
            if self._live is None:
                self._live = Live(self._render(), console=self.console, refresh_per_second=8, transient=True)
                self._live.start()

    def end_wait(self) -> None:
        with self._lock:
            if self._live is not None:
                self._live.stop()
                self._live = None

    def status(self, text: str | None, transient: bool = False) -> None:
        with self._lock:
            if text is not None:
                self._status_text = text
            if self._live is not None:
                self._live.update(self._render())
