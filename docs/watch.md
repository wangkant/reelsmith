# reelsmith watch

`reelsmith watch` opens an editor window on the project your coding agent is editing: a desktop window of its
own when the `app` extra is installed (`pip install -e ".[app]"`), else a tab in your browser. It is for
watching the work as it happens, the way you would look over someone's shoulder in an editing app: a monitor that
plays the current cut, a multi-track timeline that changes with every edit, and a feed of what the agent just did.

Nothing in the window changes the project. The server listens on 127.0.0.1 only, reads the project folder, and writes
nothing but its own caches under `build/watch/`.

## Start it

```
reelsmith watch path/to/project
```

It opens the window and prints its local address (a free port on 127.0.0.1); closing the window stops it.
`--browser` opens a browser tab instead, `--no-open` only serves and prints the address (Ctrl+C stops those),
`--port 8765` picks the port.

Give it a workspace folder instead (the one holding `workspace.json`) and the first page lists its projects; each
opens in the same window at `/p/<name>/`.

```
reelsmith watch path/to/workspace --no-open
```

Leave it running while the agent works: every tool call on the project (edit, undo, check, preview, render, speak,
draw ...) shows up within about half a second, and so does a slow call while it still runs.

There is one window per project. While it is open it records itself in `<project>/build/watch/window.json`
(`{"pid", "url"}`, removed when it closes; a file whose process is gone counts as no window), and
`reelsmith watch` on the same project then says where that window is and exits instead of opening a second one.
`--browser` and `--no-open` serve as asked all the same. On Windows the window has its own taskbar entry and icon.

## Opening by itself

With `REELSMITH_WATCH=1` in the MCP server's environment (`reelsmith setup <agent> --watch` writes it), or
`"watch": true` in the workspace's `workspace.json`, the agent's first tool call on a project opens the window on
it, as a process of its own that outlives the call; the result of that call ends with
`(a window showing this project was opened for the user: reelsmith watch)`. It opens once per project per server,
only where the desktop window can open (never a browser tab by itself), and not when a window on the project is
already open. Starting it never fails or slows the tool. `reelsmith doctor` says whether the desktop window can
open on this machine (`watch window`).

## The window

- **Monitor**: the current cut, played live in the browser by the same renderer the film is made with. Until the
  player is built (the first time takes a little while), and whenever it cannot run, the monitor shows stills the
  engine renders at the playhead instead. The delivered `out/film.mp4` and the last draft can be played too.
- **Timeline**: every track top to bottom as an editor stacks them (captions, then the visual layers topmost first,
  then sound), each clip a block at its real time with its label, transitions, enter and exit moves and keyframes;
  the narration's lines and waveform; markers and chapters. Hidden tracks are shown as hidden.
- **Working**: the call that is running right now, how long it has run and, for render and preview, its stage
  and how far it is.
- **Activity**: what the agent did, newest last: each tool call with its result, whether it worked and how long it
  took, and the pictures it made or looked at (preview stills and contact sheets, review and frames sheets, a drawn
  picture, a captured page, the picture an animated clip starts from); edits link to the history entry they made,
  so you can step back through how the cut grew.
- **Issues**: what check finds, plus the layout and delivery problems of the last render when it was made from the
  current cut. Clicking one moves the playhead to it.
- **Render and spend**: whether a delivered film exists and still matches the cut, the last render attempt and
  where it stopped, and the paid spend against the project's budget.

The activity feed is read from `<project>/.history/activity.jsonl`, one line per tool call (the last 1000 are kept).
It holds the tool's name, when it ran, how long it took, whether it worked, its result (the first 4000 characters,
with anything shaped like a key masked) and the pictures that result names; never the arguments. While a call runs
it also leaves `<project>/.history/running.json` (`{"tool", "since", "pid", "stage", "progress"}`), removed when it
ends; a file whose process is gone, or older than three hours, counts as nothing running.

### What `/api/state` adds to the timeline

- `running`: `{"tool", "since", "seconds", "stage", "progress"}` of the call at work, or `null`. `stage` is
  render's `check`, `layout`, `film`, `master` or `film check`, preview's `stills` or `sweep`, a draft's `film`,
  else `null`; `progress` is how far that stage is, 0 to 1, or `null` when it is not known.
- `summary`: `{"clips", "tracks", "narrated_s", "covered", "errors", "warnings", "batches"}`: clips on the timeline,
  tracks, seconds of spoken narration, the share of the film's length with a visible clip on screen (0 to 1; `null`
  when the film has no length), error and warning issues, and recorded edit batches.
- each `activity` row: `{"ts", "tool", "ok", "seconds", "summary", "batch", "files", "text"}`; `files` are
  project-relative paths (at most 12, in the order the result names them) to fetch as `/project/<path>`, `text`
  the whole result.

## Routes

Everything is read-only JSON in UTF-8 unless said otherwise; times are film seconds. In a workspace, each project's
routes sit under `/p/<name>/`, and `/api/projects` lists them.

| Route | Gives |
|---|---|
| `/` | the window (`/static/...` its files; `/favicon.ico` its icon, also `/static/favicon.svg`) |
| `/api/state` | the whole state: canvas, duration, voice, tracks, markers, chapters, assets, issues, render, spend, activity, history, running, summary, and a `revision` (which `running` does not move) |
| `/api/events` | server-sent events: `change` with `{"revision", "running"}` whenever the state changes; `running` with the running call (or `null`) when one starts, changes stage or ends, and as its progress moves (at most once a second) |
| `/api/history/<n>` | the timeline right after edit batch `n` (`0`: before the first recorded batch) |
| `/api/resolved` | the resolved film the renderer plays |
| `/api/still?t=&w=` | a JPEG of the film at `t`, rendered by the engine; 503 while a render of the project runs |
| `/api/thumb?asset=&t=&h=` | a small JPEG of an image or video asset |
| `/api/wave?asset=` | `{"duration", "peaks"}` of an audio or video asset (`voice` = the narration) |
| `/project/<path>` | a file under `assets/`, `voice/`, `out/` or `build/` (byte ranges work); nothing else |
| `/player/<file>` | the live player; 503 `{"building"}` until it is built |

`.env`, the ledger, `project.json` itself and anything outside those four folders are never served. Requests that
name another host are refused, so a web page cannot read the project through the port.
