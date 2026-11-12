# The reelsmith application

`reelsmith` alone in a terminal, or `reelsmith app`, opens the application on a workspace: a desktop window of its
own when the `app` extra is installed (`pip install -e ".[app]"`), else a tab in the browser. A sidebar on every page
lists the workspace's films and what each one is doing; requests to the agent run in several films at once; films
are created, renamed, duplicated and moved to the trash there; media is added to a film from the window; and the
Library and Settings pages show the workspace's components, notes and rules, its engines, keys, budgets and spend.
Each film's own page is the film window described in [watch.md](watch.md).

The terminal session stays as `reelsmith chat` ([terminal.md](terminal.md)); `reelsmith watch` keeps opening a
window on one project or workspace as before.

## Start it

```
reelsmith app [PATH] [--browser] [--no-open] [--port N] [--lang CODE] [--native-frame]
```

`PATH` (default: the current folder) decides where it opens:

- in a workspace folder or below it: the list of films;
- inside a film of the workspace: that film's page;
- inside a project outside a workspace's `projects` folder: that project alone, as `reelsmith watch` would;
- neither: in a terminal, it offers to create a workspace there (the same files the terminal session creates);
  without a terminal it says so and exits with status 2.

`--browser` opens a browser tab instead of the desktop window, `--no-open` only serves and prints the address,
`--port` picks the port on 127.0.0.1, `--lang` the interface language (`en`, `zh-CN`, `zh-TW`, `ja`, `ko`, `es`,
`fr`, `de`), `--native-frame` the system's title bar (see [The window's frame](#the-windows-frame)). Without the `app` extra it opens a browser tab and says how to get the window. Closing the window (or
Ctrl+C) stops the application and every request it runs.

There is one application per workspace. While it runs it records itself in
`<workspace>/.cache/watch/instance.json` (`{"pid", "url", "token", "since"}`, created atomically so that of two starts
at once one records itself, and removed when it stops). A record whose process is gone, or whose address does not
answer as a reelsmith application (its pid now belongs to another program), counts as none and is replaced. A second
start finds it, asks it to come forward (`POST /api/app/raise`: the window
is restored and its taskbar entry flashes) and exits with status 0 and one line; with `--browser` it opens the
running application's address in the browser instead.

The desktop window remembers its size, place and whether it was maximised per workspace in
`<workspace>/.cache/watch/window.json` (`{"width", "height", "x", "y", "maximised"}`; the size and place are the
restored ones); a place that would lie off the screen is dropped and the size kept. Its title, shown on the taskbar
and in Alt+Tab, is "reelsmith · <workspace>".

### The window's frame

On Windows the window has no system title bar. The top of the sidebar, a strip along the top of every page and each
page's header move the window; a double-click there maximises or restores it, a right-click opens the system menu,
and dragging to a screen edge snaps it. Minimise, maximise (restore when maximised) and close sit at the top right of
every page. The window keeps the system's resizable frame underneath: its edges and corners resize, Win+arrow keys
and Snap work, a maximised window fills the work area above the taskbar, and Windows 11 draws its shadow and rounded
corners. Moving by the page's regions needs a WebView2 runtime with non-client region support (123 or later); with an
older one the page asks the window to move instead.

Where this misbehaves, the system frame comes back with

```
reelsmith app --native-frame
```

or, for a workspace, in `workspace.json`:

```json
{"watch": {"frame": "native"}}
```

macOS and Linux always keep the system frame. A browser tab shows no window controls.

## Requests in several films at once

Each film has its own chat, and requests in different films run at the same time, up to the workspace's limit:

```json
{"watch": {"parallel": 3}}
```

in `workspace.json` (1 to 8; default 3; the Settings page writes it). A request beyond the limit waits for a free
place, first come first served across the workspace, and says so: its chat status has `"queued": <place>` (1 is
next), the film's state has `"queue": {"position", "code": "queue.waiting", "params", "text"}`, and the sidebar row
is `queued` with its place. Stop ends a waiting request at once, with the usual stopped note and no cost. The limit
is counted per process: a terminal session or another server beside the application counts its own requests.

The renderer still draws one job at a time in a process. A render, preview or review that waits for it while another
film's render holds it reports `stage_code: "stage.renderer_wait"` ("waiting for the renderer") in its `running`
view and in the film's row, instead of looking stuck.

What a request touches that other films' requests share, and how each is kept apart: the chat transcript, the chat
state and the activity log are per project; `running.json` and `origin.json` are per project; the ledger takes a
thread lock and an OS lock per file and counts spend by project; the render lock is per project folder, and the
renderer lock is one per process by design; the tools' call context is a context variable, so each turn's thread
has its own; the state, resolve and media caches are keyed by path and file stamp; nothing changes the current
folder. One limit remains: the API engine's in-process tools set `REELSMITH_ROOT` for the length of each tool call
under one lock, so in-process tool calls of different films take turns (the Agent SDK, Codex and DeepSeek Harness
engines run their tools in their own processes and are not affected).

## What each film shows

`GET /api/app` gives the whole application:

```
{"workspace": {"name", "path"}, "version", "desktop", "films": [Film], "counts": {"working", "queued", "attention"},
 "parallel": {"limit", "running", "queued"}, "engine": {"id", "label", "available", "code", "params"}}
```

`engine` is the default engine row (`id` `null` and `code` `chat.no_engine` when none can run). A `Film` is the
home's project row (`name`, `path`, `url`, `title`, `duration`, `valid`, `empty`, `canvas`, `result`, `poster`,
`revision`, `modified`, `working`, see [watch.md](watch.md#routes)) and:

- `status`: `working` (a request, an action, a render or another caller's tool call is at work), `queued` (its
  request waits for a free place), `attention` (it asks something of the person) or `idle`;
- `queue`: the place in the queue from 1, or `null`;
- `unread`: a request ended there since the film was last seen;
- `attention`: `[{"code", "params"}]`, most pressing first: `attention.failed` (the last request failed, ended early
  or met its budget), `attention.reply` (the last request ended with a question to the person, while unread),
  `attention.refused` (the last render was refused), `attention.issues` (`{"n"}` errors in the project),
  `attention.to_accept` (the delivered film matches the cut and is not yet accepted);
- `last`: `{"role", "text", "at"}` of the chat's last row (`text` plain and at most 160 characters), or `null`;
- `errors`: the number of error issues.

A film is marked unread when a request ends there, and seen by `POST /api/app/seen {"name"}` or when its own page
asks for its state (`/p/<name>/api/state`). Both are kept in `<workspace>/.cache/watch/app.json`, so a restart
remembers.

`GET /api/app/events` is a stream of server-sent events: `films` with `{"films", "counts", "parallel"}` whenever
any of it would read differently (at most four a second; first at once), and `ended` with
`{"name", "turn", "outcome", "title"}` when a request ends in any film (`outcome` `done`, `stopped`, `failed` or
`refused`, the last for a used-up budget).

## Films

| Route | Does |
|---|---|
| `GET /api/films/suggest?text=` | `{"name"}`: a free folder name, `<date>-<slug of the text>` as the terminal session makes them |
| `GET /api/formats` | `{"default", "formats": [{"id", "width", "height", "fps", "platform", "origin"}]}`: the built-in profiles and the workspace's own |
| `POST /api/films` | body `{"name"?, "description"?, "format"?, "locale"?, "engine"?, "start"}`: 201 `{"name", "url", "turn", "queued"}`. Without a name one is suggested from the description; with `start` and a description, the description is the film's first request (`turn` its number). A first request that is refused leaves the film made and adds `"refused": {"error", "code", "params"}` |
| `POST /api/films/<name>/title` | body `{"title"}`: sets `meta.title` as an edit (undoable); `{"name", "title"}` |
| `POST /api/films/<name>/duplicate` | body `{"name"?}`: a copy without `build/`, `out/` and `.history/` (default name `<name>-copy`, then `-copy-2` ...); 201 `{"name", "url"}` |
| `POST /api/films/<name>/trash` | moves the film to `<workspace>/.trash/<name>-<YYYYmmdd-HHMMSS>/` with a `trash.json` record; `{"id", "name"}`; 409 `film.busy` while a request, an action, a render or a tool call runs there |
| `POST /api/films/<name>/reveal` | body `{"what": "folder" \| "out"}`: opens the film's folder or its `out/` folder in the file manager |
| `GET /api/trash` | `[{"id", "name", "title", "trashed_at", "size_bytes"}]`, the most recently trashed first |
| `POST /api/trash/<id>/restore` | puts the film back under its old name, or the next free one (`name-2` ...); `{"name", "url"}` |
| `POST /api/trash/<id>/delete` | deletes it for good; `{"deleted": true, "id"}` |

`POST /api/projects` (the older home's route) keeps working. Names are checked as `POST /api/projects` checks them.

Above the films, the Films page has one line, "Describe a film": the suggested folder name shows beside it as it is
typed, and Enter creates the film and sends the description as its first request while the page stays where it is
(the film appears under In progress). "More options" carries the text to the New film page. When the first request
is refused (no engine, for example), the film's page opens with the description in its message box and the reason
above it; the text passes through the tab's session storage, never the address. `GET /api/app` gives the name rules
the pages check before asking (`"names": {"pattern", "max", "reserved"}`), the same reserved names the suggestion
avoids.

`POST /api/reveal` with `{"what": "workspace" | "env" | "notes"}` opens the workspace folder, the folder of its
`.env` or of `library/NOTES.md` in the file manager (the Library and Settings pages' "Show in folder"); 404
`reveal.missing` when the file is not there.

## Media

Media is added to a film as assets, each file under an id made from its name (`Harbor Photo.png` becomes
`harbor_photo`, then `harbor_photo_2` ...), through `import_asset` (a hard link on the same drive, else a copy):

- `POST /p/<name>/api/import` with `{"paths": [absolute paths]}`: the desktop window's file dialog gives paths (at
  most 50 at once);
- `PUT /p/<name>/api/upload?name=<file name>` with the file as the body (a `Content-Length` is required, at most
  8 GB): a browser tab has no paths, so the file is streamed to `build/watch/uploads/` and imported from there.

Both answer `{"assets": [{"id", "kind", "path"}], "refused": [{"name", "code", "params"}]}`. Images, videos and audio
files are accepted, by extension. On a film's page, Add media in the Assets pane uses the desktop window's file dialog (and
`import`) or, in a browser tab, the browser's file picker (and `upload`); files dropped on the page are uploaded. A
file that is not a picture, a video or a sound is turned away by the page before anything is sent.

## Library

`GET /api/library` gives `{"components", "notes", "rules", "fonts"}`: each component `{"name", "origin": "built-in" |
"workspace", "about", "props": [{"name", "type", "required", "about"}], "example", "problem", "preview"}` (a
workspace component of the same name replaces the built-in one), the workspace's `library/NOTES.md`
(`{"path", "text", "modified"}` or `null`), its rules as `{"hard": [{"key", "value"}], "advice": [...]}` and its
fonts (`[{"name", "path"}]`).

`GET /api/library/preview?name=&theme=light|dark` is a JPEG of the component drawn from its `example` on the
theme's ground, 640 pixels wide. The first request answers 202 `{"pending": true}` while the renderer draws it (one
preview at a time, through the same renderer queue as everything else); later requests get the picture from
`<workspace>/.cache/watch/library/`, until the component's files or the renderer change. It is local and free.

## Settings

`GET /api/settings`:

```
{"engines": [{"id", "label", "available", "code", "params", "why"}], "default_engine", "parallel", "parallel_range",
 "budgets": {"request_usd", "project_usd", "min_balance_usd"}, "keys": [{"name", "present", "where", "used_for"}],
 "env_path", "spend": {"month_usd", "by_tool": [{"tool", "usd", "calls"}]}, "checks": [{"name", "ok", "required",
 "detail", "fix"}], "version", "licence", "workspace_path"}
```

`budgets` are `runner.budget_usd` (a request's chat budget), `budget.per_project_usd` and `budget.min_balance_usd`;
`spend` the ledger's paid calls this calendar month (UTC); `checks` the rows of `reelsmith doctor` (run once, again
on `POST /api/settings/checks`). Keys are listed by name and presence only (`where`: `env_file`, `environment` or
`null`); no value is ever returned.

- `POST /api/settings` with any of `{"default_engine", "parallel", "budgets"}` writes only those keys of
  `workspace.json` (atomically, checked to load first) and answers the settings again. A `"watch": true` there
  becomes `{"open": true, "parallel": N}`, which still opens the window by itself.
- `POST /api/settings/key` with `{"name", "value"}` writes the key into the workspace `.env`: only names reelsmith
  reads, one line of text; the file keeps its other lines and comments (a commented placeholder for the key is
  replaced), and is created with a comment header when missing. `POST /api/settings/key/delete` with `{"name"}`
  removes its line. The value is never returned, logged or echoed.

## Pages and the desktop bridge

`/` is the Films page, `/new`, `/library` and `/settings` are `new.html`, `library.html` and `settings.html`; each
film's page is `/p/<name>/`. Every page sits in the same frame (`static/shell.js`): a sidebar with the pages, every
film of the workspace grouped as in progress, for review and the rest, each with its state, and the engine and the
films at work at its foot. A film's row stops or withdraws its request and has a menu (also on a right click or
Shift+F10) to open, rename (F2), duplicate, show its folders, mark as read and move it to the trash (Delete, with a
confirmation). Ctrl+K opens a palette of films, pages and the page's own commands (on a film's page: render, check,
undo and add media); N starts a new film; Ctrl+B collapses the sidebar to a rail, and its edge sets its width. When a
request ends in another film a notice appears, the film is marked unread and the page title counts the unread
films; in the desktop window the taskbar entry flashes when the window is not in front. In the desktop window the page may call `window.pywebview.api`: `set_theme(name)`,
`pick_files()` (absolute paths, `[]` when cancelled), `pick_folder()` (a path or `null`), `attention()` (the taskbar
entry flashes without taking the focus; Windows only, `false` elsewhere) and `set_title(text)`. A browser tab has
none of these.

## Codes

Refusals are `{"error" (English), "code", "params"}` with a 4xx status, like the film page's.

| Code | English | Where |
|---|---|---|
| `film.unknown` (`{"name"}`) | There is no film named "{name}" in this workspace | any route naming a film |
| `film.busy` (`{"name"}`) | A request, an action or a render is running in this film; it can be moved once it has ended | trash |
| `title.invalid` (`{"max"}`), `title.failed` (`{"error"}`) | A title is one line of at most {max} characters; The title could not be changed: {error} | title |
| `duplicate.failed` (`{"error"}`) | The film could not be duplicated: {error} | duplicate |
| `trash.failed` (`{"error"}`), `trash.unknown` (`{"id"}`) | The film could not be moved: {error}; There is no film "{id}" in the trash | trash, restore, delete |
| `reveal.what`, `reveal.no_film` | Choose the film's folder or its output folder; No film has been delivered | reveal |
| `create.format` (`{"format"}`), `create.locale` (`{"locale"}`), `create.engine` (`{"engine"}`), `create.description` (`{"max"}`), and the `create.*` name codes | There is no format named "{format}"; "{locale}" is not a language tag such as en, zh-CN or ja; There is no engine named "{engine}"; A description can be at most {max} characters long | new film |
| `import.empty`, `import.too_many` (`{"max"}`), `import.not_absolute`, `import.missing`, `import.kind` (`{"ext"}`), `import.failed` (`{"error"}`) | Choose at least one file; At most {max} files can be added at once; The file is not given by its full path; The file does not exist; Files of type {ext} cannot be added; add an image, a video or an audio file; The file could not be added: {error} | media |
| `upload.name`, `upload.size` (`{"max_gb"}`), `upload.incomplete` | The file name is not accepted; add an image, a video or an audio file; The file must state its size and be at most {max_gb} GB; The upload ended before the whole file arrived | upload |
| `library.unknown` (`{"name"}`), `library.unusable` (`{"name", "error"}`), `library.theme`, `library.preview_failed` (`{"name", "error"}`) | There is no component named "{name}"; The component "{name}" cannot be used: {error}; The theme must be light or dark; The preview of "{name}" could not be rendered: {error} | library |
| `settings.unknown` (`{"key"}`), `settings.engine` (`{"engine"}`), `settings.parallel` (`{"min", "max"}`), `settings.budget` (`{"key"}`), `settings.workspace` (`{"error"}`) | "{key}" is not a setting; There is no engine named "{engine}"; Requests at once must be a whole number from {min} to {max}; The amount "{key}" must be a number of at least zero (a request budget above zero); The workspace settings could not be saved: {error} | settings |
| `key.unknown` (`{"name"}`), `key.value` (`{"name"}`) | "{name}" is not a key reelsmith reads; The value of {name} must be one line of text | keys |
| `attention.*` (see above), `queue.waiting` (`{"position"}`), `stage.renderer_wait` | ...; Waiting for a free place: number {position} in the queue; waiting for the renderer | film rows, state, running |

Every POST and PUT needs the page's own `Origin` and the token from `/api/session`, as on the film page; every GET
refuses a request another site's page makes.
