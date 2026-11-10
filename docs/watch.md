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
draw ...) shows up within about half a second.

## The window

- **Monitor**: the current cut, played live in the browser by the same renderer the film is made with. Until the
  player is built (the first time takes a little while), and whenever it cannot run, the monitor shows stills the
  engine renders at the playhead instead. The delivered `out/film.mp4` and the last draft can be played too.
- **Timeline**: every track top to bottom as an editor stacks them (captions, then the visual layers topmost first,
  then sound), each clip a block at its real time with its label, transitions, enter and exit moves and keyframes;
  the narration's lines and waveform; markers and chapters. Hidden tracks are shown as hidden.
- **Activity**: what the agent did, newest last: each tool call with its result's first line, whether it worked
  and how long it took; edits link to the history entry they made, so you can step back through how the cut grew.
- **Issues**: what check finds, plus the layout and delivery problems of the last render when it was made from the
  current cut. Clicking one moves the playhead to it.
- **Render and spend**: whether a delivered film exists and still matches the cut, the last render attempt and
  where it stopped, and the paid spend against the project's budget.

The activity feed is read from `<project>/.history/activity.jsonl`, one line per tool call (the last 1000 are kept).
It holds the tool's name, when it ran, how long it took, whether it worked and its result's first line; never the
arguments.

## Routes

Everything is read-only JSON in UTF-8 unless said otherwise; times are film seconds. In a workspace, each project's
routes sit under `/p/<name>/`, and `/api/projects` lists them.

| Route | Gives |
|---|---|
| `/` | the window (`/static/...` its files) |
| `/api/state` | the whole state: canvas, duration, voice, tracks, markers, chapters, assets, issues, render, spend, activity, history, and a `revision` |
| `/api/events` | server-sent events: `change` with `{"revision"}` whenever the state changes |
| `/api/history/<n>` | the timeline right after edit batch `n` (`0`: before the first recorded batch) |
| `/api/resolved` | the resolved film the renderer plays |
| `/api/still?t=&w=` | a JPEG of the film at `t`, rendered by the engine; 503 while a render of the project runs |
| `/api/thumb?asset=&t=&h=` | a small JPEG of an image or video asset |
| `/api/wave?asset=` | `{"duration", "peaks"}` of an audio or video asset (`voice` = the narration) |
| `/project/<path>` | a file under `assets/`, `voice/`, `out/` or `build/` (byte ranges work); nothing else |
| `/player/<file>` | the live player; 503 `{"building"}` until it is built |

`.env`, the ledger, `project.json` itself and anything outside those four folders are never served. Requests that
name another host are refused, so a web page cannot read the project through the port.
