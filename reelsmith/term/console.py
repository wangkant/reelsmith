"""`reelsmith chat`: the session in this terminal (prompt_toolkit in, rich out, plain lines when it cannot)."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import i18n
from .session import Session
from .views import PlainView, RichView


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="reelsmith chat",
                                 description="Work with reelsmith in this terminal: list the films of a workspace, "
                                             "open one and ask the agent for changes. `reelsmith` alone opens the "
                                             "application instead (reelsmith app).")
    ap.add_argument("path", nargs="?", default="", help="a project or workspace folder (default: the current folder)")
    ap.add_argument("--lang", default=None, help=f"the interface language: {', '.join(i18n.LANGUAGES)}")
    ap.add_argument("--engine", default=None, help="the agent engine: agent-sdk, codex, dsh or api")
    ap.add_argument("--plain", action="store_true", help="plain lines: no colour, no live status, no completion menu")
    return ap


def is_terminal() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


class PlainReader:
    """input() with the prompt; Ctrl+C and Ctrl+D (EOF) reach the session as they are. With a PlainView the prompt
    goes through the view, so output from another thread starts on its own line and the prompt is shown again."""

    def __init__(self, stream=None, out=None):
        self.stream, self.out = stream, out

    def __call__(self, prompt: str, session) -> str:
        view = getattr(session, "view", None)
        shared = view if hasattr(view, "prompting") else None
        out = self.out or sys.stdout
        if shared is not None:
            shared.prompting(prompt)
        else:
            out.write(prompt)
            out.flush()
        stream = self.stream or sys.stdin
        try:
            line = stream.readline()
        except BaseException:
            if shared is not None:
                shared.answered(None)
            raise
        if line == "":
            if shared is not None:
                shared.answered("")
            else:
                out.write("\n")
            raise EOFError
        line = line.rstrip("\r\n")
        # piped input is not echoed: show it so the output reads in order
        echo = None if _tty(stream) else line
        if shared is not None:
            shared.answered(echo)
        elif echo is not None:
            out.write(echo + "\n")
        return line


def _tty(stream) -> bool:
    try:
        return stream.isatty()
    except (AttributeError, ValueError):
        return False


class PromptReader:
    """prompt_toolkit's prompt: history per workspace, completion of commands, project names, engines and languages;
    Ctrl+C clears a line that has text and is passed on at an empty one."""

    def __init__(self, input=None, output=None):
        from prompt_toolkit.output import create_output
        if output is None:
            output = create_output()                       # no console (mintty without winpty) raises here
        self.input, self.output = input, output
        self._prompt = None
        self._history: Path | None = None

    def _session(self, session):
        from prompt_toolkit import PromptSession
        from prompt_toolkit.completion import Completer, Completion
        from prompt_toolkit.history import FileHistory, InMemoryHistory
        from prompt_toolkit.key_binding import KeyBindings

        path = session.history_path()
        if self._prompt is not None and path == self._history:
            return self._prompt

        class Commands(Completer):
            def get_completions(self, document, complete_event):
                text = document.text_before_cursor
                for full, meta in session.completions(text):
                    yield Completion(full, start_position=-len(text), display=full.rsplit(" ", 1)[-1]
                                     if " " in full else full, display_meta=meta)

        keys = KeyBindings()

        @keys.add("c-c")
        def _(event):
            buf = event.app.current_buffer
            if buf.text:
                buf.reset()
            else:
                event.app.exit(exception=KeyboardInterrupt, style="class:aborting")

        history = InMemoryHistory()
        if path is not None:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                history = FileHistory(str(path))
            except OSError:
                pass
        self._history = path
        self._prompt = PromptSession(history=history, completer=Commands(), complete_while_typing=True,
                                     key_bindings=keys, bottom_toolbar=lambda: session.toolbar(),
                                     input=self.input, output=self.output)
        return self._prompt

    def __call__(self, prompt: str, session) -> str:
        from prompt_toolkit.patch_stdout import patch_stdout
        ps = self._session(session)
        with patch_stdout(raw=True):
            return ps.prompt(prompt)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    plain = args.plain or not is_terminal()
    reader = None
    if not plain:
        try:
            reader = PromptReader()
        except Exception:  # noqa: BLE001 - no console prompt_toolkit can drive: plain lines instead
            plain = True
    if plain:
        if not _tty(sys.stdin):
            try:
                sys.stdin.reconfigure(encoding="utf-8", errors="replace")     # a pipe carries UTF-8, not the code page
            except (AttributeError, ValueError):
                pass
        view, reader = PlainView(), PlainReader()
    else:
        from rich.console import Console
        view = RichView(Console(highlight=False, force_terminal=True))
    session = Session(Path(args.path).expanduser() if args.path else Path(os.getcwd()), view, reader,
                      lang=args.lang, engine=args.engine)
    try:
        return session.run()
    except KeyboardInterrupt:
        return 130
