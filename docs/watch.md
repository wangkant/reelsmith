# reelsmith watch

`reelsmith watch` opens an editor window on the project your coding agent is editing: a desktop window of its
own when the `app` extra is installed (`pip install -e ".[app]"`), else a tab in your browser. It is for
watching the work as it happens, the way you would look over someone's shoulder in an editing app: a monitor that
plays the current cut, a multi-track timeline that changes with every edit, and a feed of what the agent just did.
It also has a chat: ask an agent for a change at any time, and watch it make it (see
[Talking to the agent](#talking-to-the-agent)).

The window itself changes the project only through that chat, whose agent works with the same tools and the same
fences as `reelsmith run`. The server listens on 127.0.0.1 only and, apart from the chat, writes nothing but its own
caches under `build/watch/`.

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
with anything shaped like a key masked, and paths relative to the project: the workspace as `<workspace>`, the home
folder as `~`) and the pictures that result names; never the arguments. The window reads older lines the same way.
It shows the last 300 rows, batches the log missed included. While a call runs
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
- `library`: a stamp of the workspace's components; it moves (and with it the `revision`) when one is edited, since
  that changes the picture.

## Talking to the agent

The chat panel sends a message to an agent working on the project you are watching. Each message is one turn: the
agent does what you ask with the reelsmith tools, looks at what it changed (preview), and answers briefly in your
language, saying what it did and what to look at. It renders only when you ask for it or when the change is meant to
be final. If you have a clip selected or the playhead parked, the message carries that as one line of context
(`[selected clip sb (7.60-16.81 s); playhead at 13.40 s]`), so "here" and "this" mean what you are looking at.
While a turn runs you see each step as it happens (what the agent says, each tool call with what it got, and which
failed); **Stop** ends the turn (the API engine between model calls, the Agent SDK at once, Codex and DeepSeek
Harness by ending their process), and the next message goes on in the same conversation.

The next message resumes the same session, so the agent remembers what you said before. The conversation is kept
apart from `reelsmith run`: its state is `build/chat_state.json` (the session, its engine and model, and the spend),
its API conversation `build/chat_messages.json`, its log `build/chat.jsonl`. A headless run and a chat never share a
session, and a chat never starts the fix-up loop a run uses to deliver a film. Choosing another engine or model
starts a new session; delete `build/chat_state.json` to start over.

**Engines.** The chat runs on the engines `reelsmith run` has, where they can run on this machine:

| Engine | Needs |
|---|---|
| `agent-sdk` | the `runner` extra (Claude Agent SDK) and its claude CLI; `ANTHROPIC_API_KEY`, or else the claude CLI's own sign-in (the chat may use it; `reelsmith run` does not) |
| `codex` | the Codex CLI, signed in (what `reelsmith doctor` checks) |
| `dsh` | DeepSeek Harness (or `npx`) and `DEEPSEEK_API_KEY` |
| `api` | the key of the workspace's provider (`runner.provider`) |

The default is `runner.engine` in `workspace.json` when it can run here, else the first that can in that order. The
model, effort and the other runner settings are the workspace's, as for `reelsmith run`.

**Budget.** The chat spends under `runner.budget_usd`, counted across the whole conversation (all turns, all
engines), and each turn under `runner.max_minutes` and `runner.max_turns`. When it is used up the chat says so and
runs nothing more until you raise it. Every turn ends with a line saying what it cost.

**The transcript** is `<project>/.history/chat.jsonl`, one JSON row per line:
`{"id", "ts", "role", "text", "tool", "ok", "turn"}` with `role` `user`, `assistant`, `tool` or `note`. A user row
also has `context` (the selection it carried) and `engine`; a tool row has `tool` (its name), `text` (a one-line
summary of what it got), `ok` (`null` while it runs) and, when it failed, `detail`; a note ends each turn, with `kind`
(`end`, `stopped`, `aborted`, `error` or `budget`), `cost_usd`, `spent_usd` and `budget_usd`. A row whose state
changes (a tool call that finished) is written again with the same `id`; the last copy wins.

## Routes

Everything is JSON in UTF-8 unless said otherwise; times are film seconds. In a workspace, each project's routes sit
under `/p/<name>/`, and `/api/projects` lists them.

| Route | Gives |
|---|---|
| `/` | the window (`/static/...` its files; `/favicon.ico` its icon, also `/static/favicon.svg`) |
| `/api/state` | the whole state: canvas, duration, voice, tracks, markers, chapters, assets, issues, render, spend, activity, history, running, summary, and a `revision` (which `running` does not move) |
| `/api/events` | server-sent events: `change` with `{"revision", "running"}` whenever the state changes; `running` with the running call (or `null`) when one starts, changes stage or ends, and as its progress moves (at most once a second); `chat` with `{"rows", "busy", "turn", "stopping"}` (the new or changed transcript rows) as a turn proceeds, or `{"resync": true}` when the stream fell behind and the page should fetch `/api/chat` |
| `/api/session` | `{"token"}`: the server's random token, which every POST sends back as `X-Reelsmith-Token` |
| `/api/chat` | `{"busy", "turn", "stopping", "engine", "session_engine", "engines": [{"id", "label", "available", "why"}], "spent_usd", "budget_usd", "messages"}`; `messages` are the last 200 rows; `engine` is the default (or the running turn's) |
| `POST /api/chat` | body `{"message", "engine"?, "context"?: {"clip", "start", "end", "playhead"}}`: 202 `{"turn"}`; 409 while a turn runs; 400 for an empty message, one over 8000 characters, or an engine that cannot run here (the reason in `error`) |
| `POST /api/chat/stop` | `{"stopped"}`: whether a turn was running and is being stopped |
| `/api/history/<n>` | the timeline right after edit batch `n` (`0`: before the first recorded batch) |
| `/api/resolved` | the resolved film the renderer plays |
| `/api/still?t=&w=` | a JPEG of the film at `t`, rendered by the engine (cached by the resolved film, the renderer and components, and the files it shows); 503 `{"busy"}` while a render, preview or draft of the project holds its lock |
| `/api/thumb?asset=&t=&h=` | a small JPEG of an image or video asset |
| `/api/wave?asset=` | `{"duration", "peaks"}` of an audio or video asset (`voice` = the narration) |
| `/project/<path>` | a file under `assets/`, `voice/`, `out/` or `build/` (byte ranges work); nothing else |
| `/player/<file>` | the live player; 503 `{"building"}` until it is built |

`.env`, the ledger, `project.json` itself and anything outside those four folders are never served. Requests that
name another host are refused, so a web page cannot read the project through the port. Every route but the page
itself refuses (403) a request another site's page makes (`Sec-Fetch-Site` `cross-site` or `same-site`, or an
`Origin` that is not the window's own), so no page can make the server render or run ffmpeg; an address-bar visit
works. No response carries a CORS header, and every one says `Cross-Origin-Resource-Policy: same-origin`. A POST needs
both the window's own `Origin` and the token from `/api/session`, which only the window's own page can read. A bad
request gets a JSON error, never a dropped connection.
