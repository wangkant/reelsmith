# The terminal session

`reelsmith chat` works with reelsmith in the terminal: an interactive session that lists the films of a workspace,
opens one and sends requests to an agent, which edits, checks and renders the film while the session shows each
step. Running `reelsmith` with no arguments opens the application instead ([app.md](app.md)), which does the same
for every film of the workspace at once in a window.

The film window ([watch.md](watch.md)) is its companion: `/window` opens it on the session itself, so a request
sent from either one appears in both. Requests started in the session keep to the workspace's limit of requests at
once (`"watch": {"parallel": N}`); the limit is counted per process, so the session and an application running
beside it each count their own.

## Start it

```
reelsmith chat [PATH] [--lang CODE] [--engine ID] [--plain]
```

`PATH` (default: the current folder) decides where the session starts:

- inside a project: that project is opened, and its workspace is the home;
- in a workspace folder or below it: the home, a list of the workspace's films;
- neither: the session offers to create a workspace there (`workspace.json`, `rules.json`, `library/NOTES.md`,
  `projects/` and a `.env` holding only comments; optional keys go in that file).

The header names the version, the workspace, the agent engine that will be used and the interface language. When no
engine can run on the computer, it lists each engine with what it requires (a package, a sign-in or a key in the
workspace `.env`).

## The home

The films of the workspace, newest change first: number, name, title, length, the state of the delivered film
(none, current, out of date, refused or accepted) and the time of the last change.

- A number or a name opens that film; a number with no film says so.
- `quit`, `exit`, `q` and `help` (and the same words in the interface language) act as `/quit` and `/help`.
- A single word that could be a film's name but matches none says so and names `/new NAME`.
- Any other text describes a new film. The session shows the name it will get (`<date>-<words of the text>`) and
  asks once; Enter or yes creates the film with the workspace's profile, opens it and sends the text to the agent as
  the first request. Nothing typed at the home reaches the agent without that answer.

New films, from the home or from `/new`, are created by the session's watch server, with the same checks as the
window's: the name's characters and length, the names the operating system reserves, a name already taken (letter
case aside), and one creation at a time. A refusal says which rule the name breaks.

## In a project

The prompt shows the project's name. Text is a request to the agent. While the agent works, each tool call appears
as one line (the tool, its brief, a result mark and the time it took), the agent's replies are shown as formatted
text, and a status line follows a slow call's stage and progress. The request ends with one line: its duration, its
cost and the spend against the budget. A used-up budget, an engine failure and a refused render each say what
happened and what to do next.

The status line is shown only while the prompt waits. A request started in the window, an action started in the
window, and an action left running with a second Ctrl+C are each reported by one line when they end.

## Commands

| command | does |
|---|---|
| `/help` | list the commands and keys |
| `/projects` | return to the list of films |
| `/open N\|NAME` | open a film by its number or name |
| `/new [NAME]` | create a film, with the given name or a dated one |
| `/status` | the film's length, beats, issues, result and spend |
| `/stop` | stop the request running on the open film, whether the terminal or the window started it |
| `/check` | check the project |
| `/render` | render and deliver the film |
| `/undo`, `/redo` | undo the last change, or restore it |
| `/accept` | accept the delivered film when it matches the current cut |
| `/window` | open the editor window on this session (or print its address for a browser) |
| `/engine [ID]` | list the agent engines, or select one for the next requests |
| `/lang [CODE]` | list the interface languages, or select one and save the choice |
| `/quit` | leave the session |

An unknown command names the nearest one. `/check`, `/render`, `/undo` and `/redo` run the same actions as the
window's buttons and never while the agent works.

## Keys

| key | does |
|---|---|
| Enter | send the line |
| Tab | complete a command, a film name, an engine or a language |
| Up, Down | earlier lines (kept per workspace in `.cache/term/history`) |
| Ctrl+C while the agent works | stop the request after its current step; another press says it is still stopping |
| Ctrl+C twice during `/check` or `/render` | return to the prompt; the action continues and its result is shown when it ends |
| Ctrl+C on a line with text | clear the line |
| Ctrl+C twice at an empty prompt, Ctrl+D, `/quit` | leave; a running request is stopped first |

While the session closes, Ctrl+C does not interrupt it: the running request, the watch server and the window are
always stopped.

## Languages

English, Simplified Chinese, Traditional Chinese, Japanese, Korean, Spanish, French and German, as their
dictionaries are installed; the engines' reasons, the server's refusals and the punctuation of lists follow the
language too. The language is the first of: `--lang`, the `REELSMITH_LANG` environment variable, the
choice saved by `/lang`, the system's language, English. The choice is saved in `term.json` in the per-user settings
folder (`%APPDATA%\reelsmith` on Windows, `~/Library/Application Support/reelsmith` on macOS,
`$XDG_CONFIG_HOME/reelsmith` or `~/.config/reelsmith` elsewhere); `REELSMITH_CONFIG_DIR` names another folder.

## Plain mode

When the input or the output is not a terminal, with `--plain`, or when the console cannot be driven (for example
Git Bash's mintty without winpty), the session reads plain lines and writes plain text: no colours, no live status
line and no completion menu, with the same commands and behaviour. A slow call's progress is printed at each new
stage and every quarter. Output that arrives while the prompt waits starts on a line of its own, and the prompt is
printed again after it. Piped input is read as UTF-8.

## The session and the window

The session runs a local watch server (127.0.0.1, a free port) for its workspace and works on every project through
it, and lists the films through it, so the home and the window's list agree. `/window` opens the desktop window on
that server in a process of its own, which Ctrl+C in the terminal does not reach and which is closed when the session
ends; without the `app` extra it prints the address for a browser. Requests sent from the window appear in the
terminal as they happen, and the terminal's requests appear in the window.

One process owns a project at a time:

- While a watch window of another process is open on a project, the session does not open that project and says
  which window to close.
- While the session has a project open, it is recorded as that project's window, so `reelsmith watch` on that
  project in another process reports the session's address instead of opening a second window.
- The server checks again whenever a request is sent, an action (check, render, undo, redo) is started or a film is
  accepted, from the terminal or the window: if a window of another process holds the project at that moment, it is
  refused and the session names that window's address. Stopping a request is never refused.
