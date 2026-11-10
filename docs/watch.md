# reelsmith watch

`reelsmith watch` opens an editor window on the project your coding agent is editing: a desktop window of its
own when the `app` extra is installed (`pip install -e ".[app]"`), else a tab in your browser. It is for
watching the work as it happens, the way you would look over someone's shoulder in an editing app: a monitor that
plays the current cut, a multi-track timeline that changes with every edit, and a feed of what the agent just did.
It also has a chat: ask an agent for a change at any time, and watch it make it (see
[Talking to the agent](#talking-to-the-agent)).

The window itself changes the project only through that chat, whose agent works with the same tools and the same
fences as `reelsmith run`, and through a few actions that run one tool without typing (render, check, undo, redo).
The server listens on 127.0.0.1 only and, apart from those, writes nothing but its own caches under `build/watch/`
and the acceptance record `out/accepted.json`.

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

The window is made for the person who commissioned the film: they follow what the agent does, look at the film,
ask for changes and accept the result. Nothing in it is dragged; every change goes through the agent or through
one of the window's few actions.

- **Session** (left): one thread that tells the work as it happened: each request with what it applied to (the
  selected beat or element, or the playhead), the agent's steps (an edit with the beats it touched, the frames it
  inspected, a check with what it found, a render with its stages and then the film, a paid call with its cost) and
  its replies. At the bottom the composer: what "this" means, quick actions that need no typing (render the film,
  check the film, undo the last change), send (stop while a request runs), the engine and the spend against the
  budget.
- **Stage** (right): the film at the canvas's shape, played live by the same renderer the film is made with (the
  delivered `out/film.mp4` can be played instead), with play, step, the timecode and a progress bar divided into
  beats that marks where the latest change landed and where a problem is.
- **Beats**: the film told line by line. A narrated film has one beat per voice line, from the line's start to
  the next line's start (anything before the first line belongs to beat 1, the last runs to the end); a film
  without narration has one per group of caption phrases (a group ends at a pause, at a sentence's end, at a cut to
  another shot, or once 8 s long), else one per full-frame shot. Each beat shows a frame,
  its line and caption phrases, its pictures, its titles and cards in plain words ("Step-by-step card", "Large
  figure", "Overlay text", "Sound bed"), and any problem in it. Selecting one moves the playhead there and attaches
  it to the next request.
- **Tracks**: the multi-track timeline as a detail view under the beats: every track top to bottom as an editor
  stacks them (captions, then the visual layers topmost first, then sound), each clip a block at its real time;
  the narration's lines and waveform; markers and chapters. Hidden tracks are shown as hidden.
- **Top bar**: the film's title and canvas, the standing of the result (nothing delivered, delivered and current,
  delivered but older than the cut, or the last render refused, with the reason), the language and theme, and
  **Accept the film** once a delivered film matches the cut.

The activity behind the session is read from `<project>/.history/activity.jsonl`, one line per tool call (the last
1000 are kept). It holds the tool's name, when it ran, how long it took, whether it worked, its result (the first
4000 characters, with anything shaped like a key masked, and paths relative to the project: the workspace as
`<workspace>`, the home folder as `~`), the pictures that result names, and who asked for it (`turn`: the chat turn,
`action`: the window's action); never the arguments. The window shows the last 300 rows, batches the log missed
included. While a call runs it also leaves `<project>/.history/running.json` (`{"tool", "since", "pid", "stage",
"progress"}`), removed when it ends; a file whose process is gone, or older than three hours, counts as nothing
running. While a chat turn or an action runs, `<project>/.history/origin.json` (`{"pid", "since", "turn" | "action"}`)
says so, for the calls of any process to copy onto their rows.

### What `/api/state` adds to the timeline

- `beats`: `[{"n", "start", "end", "line", "line_i", "kind", "phrases", "shots", "elements", "sound", "issues",
  "changed", "frame"}]`, described under [Beats](#beats).
- `result`: `{"state", "reason_code", "params", "reason", "stage", "t", "clip", "beat", "film", "frame",
  "accepted"}`. `state` is `none` (no film delivered), `current` (the delivered film was rendered from the current
  cut), `stale` (it was rendered from an earlier cut) or `refused` (the last render of the current cut stopped;
  the previous film, if any, is kept and is `film`). `reason_code` and `params` say why (see [Codes](#codes)),
  `reason` in English; for a layout refusal, `clip`, `t` and `beat` point at the first error and `frame` at the
  still the render measured there. `film` is `render.delivered`. `accepted` is `{"at"}` once the delivered film was
  accepted (`POST /api/accept`) and the current cut is the one accepted (an edit withdraws it; undoing the edit
  restores it), else `null`.
- `spend`: `{"project_usd", "project_budget_usd", "chat_usd", "chat_budget_usd"}`: the project's paid provider
  calls against `budget.per_project_usd`, and the chat's model spend against `runner.budget_usd` (`null` when
  unknown).
- `can`: `{"render", "check", "undo", "redo", "stop": bool, "why": {action: {"code", "params", "text"}}}`: which of
  the window's actions can run now, and for each one that cannot, why.
- `action`: the window's action at work (`{"action", "since"}`) or `null`; `last_action`: how the last one ended
  (`{"action", "state": "done" | "failed", "ok", "code", "params", "text", "detail", "at"}`, `detail` the tool's own
  result).
- `running`: `{"tool", "since", "seconds", "stage", "progress", "by", "code", "stage_code", "percent", "params",
  "text"}` of the call at work, or `null`. `stage` is render's `check`, `layout`, `film`, `master` or `film check`,
  preview's `stills` or `sweep`, a draft's `film`, else `null`; `progress` is how far that stage is, 0 to 1, or
  `null` when it is not known. `by` is `window` (the window's action), `chat` (its chat's agent) or `agent`; `text`
  says it in English ("The agent is rendering the film: measuring layout (40 %)").
- each `issues` row also has `beat` (its beat's `n`, or `null`) and, for a layout problem, `code`, `params` and
  `message` (the formal English of the code; `text` stays the engine's own words).
- each `activity` row: `{"ts", "tool", "ok", "seconds", "summary", "batch", "files", "text"}`, plus `turn` or
  `action` when the window's chat or action made the call; `files` are project-relative paths (at most 12, in the
  order the result names them) to fetch as `/project/<path>`, `text` the whole result. A row with a `batch` has
  `touched`: `{"clips", "tracks", "beats"}`, what that batch changed (its snapshot against the next one, or against
  `project.json` for the last batch), the beats numbered as in the current cut (a removed clip counts where it was);
  `null` once the batch was undone.
- `latest_batch`: the newest batch in the feed (its beats are marked `changed`); `can_undo`, `can_redo`; `cut`: the
  digest of the cut a render would be made from.
- `summary`: `{"clips", "tracks", "narrated_s", "covered", "errors", "warnings", "batches"}`: clips on the timeline,
  tracks, seconds of spoken narration, the share of the film's length with a visible clip on screen (0 to 1; `null`
  when the film has no length), error and warning issues, and recorded edit batches.
- `library`: a stamp of the workspace's components; it moves (and with it the `revision`) when one is edited, since
  that changes the picture.

### Beats

Each beat: `n` (from 1), `start` and `end` in film seconds, `line` (the narration text, or `null` without
narration), `line_i` (the voice line's number), `kind` (`line`, `phrase` or `shot`: what it was cut by), `phrases`
(`[{"start", "end", "text"}]`, the caption phrases in it), `issues` (indexes into `issues`), `changed` (the latest
batch touched it) and `frame` (`/api/frame?t=<its middle>&h=180`). What is on screen:

- `shots`: `[{"clip", "asset", "start", "end", "name_code", "name", "subject", "thumb", "notes", "note_codes",
  "continues"}]`: the pictures (image and video clips) in order. `name_code` is `shot.footage`, `shot.still` or
  `shot.inset` (a picture in a box), `name` its English; `subject` the first clause of the asset's note, if it has
  one; `thumb` a frame of the asset at the shot's middle; `notes` in English and `note_codes` as codes: `shot.speed`
  (`{"rate"}`, "2x speed"), `shot.reversed`, `shot.held` ("held frame"), `shot.looped`, `shot.transition_in`
  (`{"type"}`, "crossfade in"), `shot.motion` (`{"motion"}`, "slow push-in").
- `elements`: `[{"clip", "kind", "name_code", "name", "summary", "start", "end", "continues"}]`: titles, text, cards
  and marks. `kind` is `title`, `text`, `card`, `evidence`, `figure`, `shape` or `component`; `summary` its words in
  one line (a text's text, a component's readable props, an evidence capture's note or site). The built-in
  components have names of their own (`card.steps` "Step-by-step card", `figure.count` "Large figure",
  `card.receipt`, `card.versus`, `card.quote`, `card.news`, `card.parties`, `card.timeline`, `card.stamp`,
  `card.seesaw`, `figure.bars`, `figure.dots`, `evidence.card`, `shape.arrow`, `shape.highlight`); a workspace
  component is `component.custom` and named by its own name. Text is `text.title` ("Title") or `text.overlay`
  ("Overlay text"); shapes are `shape.plate` ("Backing plate"), `shape.frame`, `shape.circle`, `shape.line`,
  `shape.arrow`, `shape.path`.
- `sound`: `[{"clip", "asset", "start", "end", "name_code", "name", "continues"}]`: `sound.bed` ("Sound bed": looped
  or half the film or longer) or `sound.effect`.

A shot, element or sound that spans several beats is listed in the beat where it starts and again, with
`continues: true`, in each later beat it reaches into. Hidden tracks are left out.

### Codes

Every string the server composes from known parts carries a stable code and its parameters beside the English, so
the window can say it in the person's language; the engine's own free-text messages stay as they are.

| Codes | Where |
|---|---|
| `result.none`, `result.current`, `result.stale`, `render.refused.check`, `render.refused.layout`, `render.refused.film_check`, `render.refused.component`, `render.refused.infra`, `render.refused` (`{"error"}`) | `result.reason_code` |
| `layout.cut_by_edge` (`{"text", "side", "px", "also"}`), `layout.outside_safe` (`{"text", "side", "px", "also"}`), `layout.text_tiny` and `layout.text_small` (`{"text", "px", "min", "also"}`), `layout.overlap` (`{"text", "other", "also"}`), `layout.cut_by_card` (`{"text", "share", "also"}`), `layout.low_contrast` (`{"text", "color", "bg", "ratio", "also"}`), `layout.overflow_box` (`{"text", "side", "px", "also"}`) | layout issues, a layout refusal |
| `running.<tool>` (`running.render`, `running.preview`, `running.check`, `running.edit` ...; `running.tool` for any other) with `stage.check`, `stage.layout`, `stage.film`, `stage.master`, `stage.film_check`, `stage.sweep`, `stage.stills` | `running` |
| `busy.action`, `busy.chat`, `busy.render`, `project.invalid`, `render.current`, `undo.empty`, `redo.empty`, `stop.idle`, `stop.pending`, `stop.unsupported` | `can.why`, 409 answers |
| `action.<render/check/undo/redo>.ok` and `.failed`, `action.unknown` | `last_action`, the `action` event |
| `chat.end`, `chat.stopped`, `chat.aborted`, `chat.error`, `chat.budget` | a chat note's `code` and `params` |
| `chat.empty`, `chat.too_long`, `chat.no_engine`, `chat.unknown_engine`, `chat.engine_unavailable`, `chat.workspace_hidden`, `chat.bad_context`, `busy.chat` | a refused `POST /api/chat` |
| `accept.not_current`, `reveal.no_film`, `frame.failed` | other refusals |

An error answer with a code is `{"error" (English), "code", "params"}`.

### Actions

`POST /api/action` with `{"action": "render" | "check" | "undo" | "redo" | "stop"}` runs that reelsmith tool on the
project (undo: the last batch) without a chat turn, on a worker thread: 202 `{"action", "started": true}`, then an
`action` event when it starts and when it ends. One runs at a time; 409 with the reason's code while another runs,
while a chat turn works, or when `can` says no (nothing to undo, a render of the current cut already delivered). It
is logged in the activity like any tool call, with `action` on its row, and `running` shows it with `by: "window"`.
`stop` stops a chat turn that is working (200 `{"stopped": true, "what": "chat"}`); a render started from the window
cannot be interrupted, and stop says so (`{"stopped": false, "code": "stop.unsupported"}`). A chat message is
refused (409 `busy.action`) while an action runs.

`POST /api/accept` records the delivered film as accepted, in `out/accepted.json` (`{"at", "cut"}`); only when the
result is `current` (else 409 `accept.not_current`). `POST /api/reveal` opens the folder holding `out/film.mp4` in
the system's file manager, and does nothing else.

### Frames

`/api/frame?t=&h=` is a JPEG of the film at `t`, `h` pixels high (or `w=` pixels wide, read as the height of the
canvas's shape). While the delivered film matches the cut it is cut
from `out/film.mp4` (fast). Otherwise it is the frame the engine renders from the current cut: served at once when
it is cached (by the resolved film, the renderer and components, and the files it shows), else queued and answered
202 `{"pending": true}`; an `event: frames` with `{"ready": [{"t", "h", "frame", "url"}], "failed": [...],
"stale": [...], "error"}` follows when they are ready (`stale`: queued for a cut that has changed since and not
rendered; ask again). The queue renders at most 12 frames per renderer run, one run at a time
(`/api/still` included), each frame once however often it is asked for, and waits while a render or preview of the
project holds its lock (checked again as the run starts). `src=film` asks for the
delivered film's frame whatever the cut, `src=cut` for the engine's. The response says which in `X-Frame-Source`.
A frame the engine could not render answers 503 `frame.failed` with the reason until the cut changes.

## Talking to the agent

The chat panel sends a message to an agent working on the project you are watching. Each message is one turn: the
agent does what you ask with the reelsmith tools, looks at what it changed (preview), and answers briefly in your
language, saying what it did and what to look at. It renders only when you ask for it or when the change is meant to
be final. If you have a clip selected or the playhead parked, the message carries that as one line of context
(`[selected clip sb (7.60-16.81 s); playhead at 13.40 s]`, or `[selected beat 3 (5.62-8.22 s)]` for a beat), so
"here" and "this" mean what you are looking at.
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
also has `context` (the selection it carried: `clip`, `beat`, `start`, `end`, `playhead`) and `engine`; a tool row has
`tool` (its name), `text` (a one-line summary of what it got), `ok` (`null` while it runs), `batch` when the call
made an edit batch and, when it failed, `detail`; a note ends each turn, with `kind` (`end`, `stopped`, `aborted`,
`error` or `budget`), `code` (`chat.<kind>`) and `params`, `cost_usd`, `spent_usd` and `budget_usd`. A row whose state
changes (a tool call that finished) is written again with the same `id`; the last copy wins.

## Routes

Everything is JSON in UTF-8 unless said otherwise; times are film seconds. In a workspace, each project's routes sit
under `/p/<name>/`, and `/api/projects` lists them.

| Route | Gives |
|---|---|
| `/` | the window (`/static/...` its files; `/favicon.ico` its icon, also `/static/favicon.svg`) |
| `/api/state` | the whole state: canvas, duration, voice, tracks, beats, markers, chapters, assets, issues, render, result, spend, activity, history, running, can, action, summary, and a `revision` (which `running`, `can` and `action` do not move) |
| `/api/events` | server-sent events: `change` with `{"revision", "running"}` whenever the state changes; `running` with the running call (or `null`) when one starts, changes stage or ends, and as its progress moves (at most once a second); `chat` with `{"rows", "busy", "turn", "stopping"}` (the new or changed transcript rows) as a turn proceeds, or `{"resync": true}` when the stream fell behind and the page should fetch `/api/chat`; `frames` when queued frames are ready; `action` when an action starts and ends |
| `/api/session` | `{"token"}`: the server's random token, which every POST sends back as `X-Reelsmith-Token` |
| `/api/chat` | `{"busy", "turn", "stopping", "engine", "session_engine", "engines": [{"id", "label", "available", "why"}], "spent_usd", "budget_usd", "messages"}`; `messages` are the last 200 rows; `engine` is the default (or the running turn's) |
| `POST /api/chat` | body `{"message", "engine"?, "context"?: {"clip", "start", "end", "playhead"}}`: 202 `{"turn"}`; 409 while a turn runs; 400 for an empty message, one over 8000 characters, or an engine that cannot run here (the reason in `error`) |
| `POST /api/chat/stop` | `{"stopped"}`: whether a turn was running and is being stopped |
| `POST /api/action` | body `{"action"}`: runs render, check, undo or redo (202), or stops a chat turn; see [Actions](#actions) |
| `POST /api/accept` | `{"accepted": {"at"}}`: records the current delivered film as accepted in `out/accepted.json`; 409 unless the result is `current` |
| `POST /api/reveal` | `{"revealed": true, "folder": "out"}`: opens the folder of `out/film.mp4` in the file manager; 404 without a film |
| `/api/history/<n>` | the timeline right after edit batch `n` (`0`: before the first recorded batch) |
| `/api/resolved` | the resolved film the renderer plays |
| `/api/frame?t=&h=&w=&src=` | a JPEG of the film as it stands: from the delivered film while it matches the cut, else rendered by the engine (202 `{"pending": true}` while queued); see [Frames](#frames) |
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
