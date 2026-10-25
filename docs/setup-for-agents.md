# Set up reelsmith: a guide for AI coding agents

You are a coding agent and the user asked you to set up reelsmith for them. Follow the steps in order; it takes a few
minutes plus downloads. Every command is given for Windows PowerShell and for macOS/Linux bash.

**What reelsmith is.** A video editing harness for coding agents: a Python package with a CLI and an MCP server, a
Remotion renderer (Node.js) and ffmpeg. The agent edits a timeline of tracks and clips with tools, looks at stills,
and renders through checks that refuse a broken film. It is not a text-to-video model.

**The end state.**

- A checkout at `<install>` with its own `.venv`, an editable install and the renderer's packages.
- `reelsmith doctor --json --workspace "<workspace>"` exits 0.
- A workspace at `<workspace>` copied from the starter, with a `.env` the user fills in if they want paid tools.
- The user's coding agent attached with `reelsmith setup <agent>`, and a 3-second test film rendered for free.

## Rules

1. Ask the user only for: where to install (suggest `~/reelsmith` for `<install>` and `~/studio` for
   `<workspace>`), which coding agent they use if you cannot tell which one you are, and whether you may install
   missing system tools. Ask these in one message at the start; decide everything else yourself, except the
   changes rule 3 lists.
2. Never ask the user to paste an API key into the chat, and never print a key's value (no `cat .env`, no echoing
   a key variable). Keys are optional; the user writes them into `<workspace>/.env` themselves.
3. Do not install system software (Python, Node.js, ffmpeg, Git, Homebrew, browsers), install anything globally
   (`npm install -g`) or change the user's `PATH` or shell startup files without the user's yes. Packages inside
   `<install>/.venv` and `<install>/renderer` are part of the setup the user asked for. Sign-ins (`codex login`)
   are the user's to do.
4. When a command fails, stop and report it: the command, the last 20 lines of its output, what you think is wrong
   and the fix you propose. Do not loop on guesses.
5. Write `<install>` and `<workspace>` as absolute paths in every command. Each of your commands may run in a fresh
   shell, so variables, `cd` and an activated venv may not carry over.
6. Clone, pip and npm need the network. If your sandbox blocks it, ask for permission to run those commands.
7. A `sudo` command that asks for a password is the user's to run: give it to them to paste in their terminal.

## 1. Look at the machine

PowerShell:

```powershell
$PSVersionTable.PSVersion.ToString(); [Environment]::OSVersion.VersionString
Get-Command python, py, node, npm, ffmpeg, ffprobe, git, winget -ErrorAction SilentlyContinue | ForEach-Object { "$($_.Name)  $($_.Source)" }
python --version; node --version; git --version
```

A tool missing from the list is not on `PATH`. `npm` shows up as `npm.ps1`: step 3 runs `npm.cmd` instead.

bash:

```bash
uname -sm; echo "$SHELL"
for t in python3 node npm ffmpeg ffprobe git brew apt-get dnf pacman; do printf '%-8s %s\n' "$t" "$(command -v $t)"; done
python3 --version; node --version; git --version
```

You need Python 3.10+, Node.js 20+, Git, and ffmpeg with ffprobe. On Windows, a `python` that prints nothing or
opens the Microsoft Store is a stub: use `py -3` if it exists. If anything is missing or too old, list it for the
user, ask once (rule 3), then install it:

| tool | Windows (winget) | macOS (Homebrew) | Debian/Ubuntu (apt) |
|---|---|---|---|
| Python | `winget install -e --id Python.Python.3.12` | `brew install python@3.12` | `sudo apt-get install -y python3 python3-venv python3-pip` |
| Node.js | `winget install -e --id OpenJS.NodeJS.LTS` | `brew install node` | `curl -fsSL https://deb.nodesource.com/setup_22.x \| sudo -E bash - && sudo apt-get install -y nodejs` |
| ffmpeg | `winget install -e --id Gyan.FFmpeg` | `brew install ffmpeg` | `sudo apt-get install -y ffmpeg` |
| Git | `winget install -e --id Git.Git` | `brew install git` | `sudo apt-get install -y git` |

- winget asks to accept the package and source agreements: add `--accept-package-agreements
  --accept-source-agreements` once the user has said yes to the install. A new install is not on your shell's
  `PATH` until the agent restarts; until then start each PowerShell command with:

  ```powershell
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
  ```

- macOS without Homebrew: ask the user to install it from https://brew.sh (it needs their password).
- Other Linux distributions: install what you can, then `reelsmith doctor` (step 4) prints the dnf or pacman
  command for the rest. Debian 12 and Ubuntu 24.04 ship Node.js 18, hence NodeSource.

## 2. Get the code

Both shells:

```bash
git clone https://github.com/wangkant/reelsmith "<install>"
```

If `<install>` already holds a reelsmith checkout, update it instead (see Update, below). If it exists, is not
empty and holds something else, ask the user for another folder; never clear it.

## 3. Install

PowerShell (use `py -3` for `python` if step 1 found the stub):

```powershell
python -m venv "<install>\.venv"
& "<install>\.venv\Scripts\python.exe" -m pip install --upgrade pip
& "<install>\.venv\Scripts\python.exe" -m pip install -e "<install>[capture,web]"
npm.cmd ci --prefix "<install>\renderer"
```

bash:

```bash
python3 -m venv "<install>/.venv"
"<install>/.venv/bin/python" -m pip install --upgrade pip
"<install>/.venv/bin/python" -m pip install -e "<install>[capture,web]"
npm ci --prefix "<install>/renderer"
```

- The extras: `capture` (screenshots of web pages as evidence; it drives Edge, Chrome or Playwright's Chromium) and
  `web` (keyless web search for headless runs). Add `transcribe` (faster-whisper, free local speech-to-text, a large
  download) only if the user wants it.
- `npm.cmd` because PowerShell's execution policy often blocks `npm.ps1`; use `npx.cmd` for `npx` likewise.
- `npm ci` ends with audit, funding and "new major version of npm" notices: ignore them. Do not run `npm audit fix`
  (it rewrites the checkout's lock file, and updates then stop applying) or upgrade npm (a global change).
- Debian/Ubuntu: if `python3 -m venv` fails, the fix is `sudo apt-get install -y python3-venv` (rule 7).

From here on, `reelsmith` means the full path of the installed command:

- Windows: `& "<install>\.venv\Scripts\reelsmith.exe"`
- macOS/Linux: `"<install>/.venv/bin/reelsmith"`

## 4. Check with doctor

```bash
reelsmith doctor --json
```

It checks the machine without spending anything or touching the network and prints one JSON object: `ok` (true
when every required check passes) and `checks`, each with `name`, `ok`, `required`, `detail`, `fix` (the exact command
for this OS) and `enables` (what an optional check unlocks). Exit status 0 means ready.

- For each check with `"required": true` and `"ok": false`, run its `fix` (asking first when it installs system
  software), then run doctor again. Repeat until `ok` is true.
- Optional checks (`remotion-browser`, `capture`, `codex`, `faster-whisper`, the `key:` rows, `agents`, `on-path`)
  never block. Note them for your report. If `capture` lacks only a browser, offer its fix (it downloads
  Playwright's Chromium) for users who want web screenshots. `remotion-browser` downloads itself on the first
  preview or render.
- `codex`'s fix is a global npm install (rule 3); after it the user runs `codex login` themselves (it opens a
  browser). `on-path` matters only for the Claude Code and DSH plugins (step 6), not for `reelsmith setup`; its fix
  changes the user's `PATH`, so run it only if the user wants a plugin and says yes.

## 5. Make a workspace

A workspace is the folder for the user's films: settings, rules, keys, a component library and the agent's notes,
with projects in `<workspace>/projects/<name>`. Copy the starter:

PowerShell:

```powershell
New-Item -ItemType Directory -Force "<workspace>" | Out-Null; Copy-Item -Recurse -Force "<install>\examples\workspace\*" "<workspace>"
```

bash:

```bash
mkdir -p "<workspace>" && cp -R "<install>/examples/workspace/." "<workspace>/"
```

The starter is a landscape 1920x1080 canvas in English (`workspace.json`: set `"profile": "vertical"` or
`"locale": "zh-CN"` if the user asked for that), with no hard rules and one sample component.

Keys go in `<workspace>/.env` as `NAME=value` lines. All are optional; editing, previews, rendering, checks, the
footage tools, imports and `capture` need none:

| key | enables |
|---|---|
| `OPENROUTER_API_KEY` | `speak` (narration), `animate` (image-to-video) and the default provider of `reelsmith run` |
| `OPENAI_API_KEY` | `transcribe` through OpenAI (or install the `transcribe` extra and set `providers.transcribe.provider` to `"local"`) |
| `DEEPSEEK_API_KEY` | `reelsmith run <project> --provider deepseek` (also `--engine dsh` and `--backend deepseek`) |
| `ANTHROPIC_API_KEY` | `reelsmith run <project> --engine agent-sdk` |
| `TAVILY_API_KEY` | web search in `reelsmith run` when the `web` extra is not installed |

`reelsmith run` makes films headless, without a coding agent; the last three keys serve it alone. Doctor's `key:`
rows list every key reelsmith reads, with what each enables. `draw` (pictures) uses the Codex CLI's own sign-in, not
a key. Write `<workspace>/.env` with your file tool,
holding comments only, so the user can fill it in:

```text
# Optional keys for reelsmith. Add the value after =, save, and never paste it into a chat.
# OPENROUTER_API_KEY=
# OPENAI_API_KEY=
```

Then check the workspace (it is now a required check):

```bash
reelsmith doctor --json --workspace "<workspace>"
```

## 6. Attach the coding agent

Run setup in the folder the user starts their agent in: `<workspace>` is a good default, never `<install>` (it is a
git checkout). Change to that folder in the same command, for example:

PowerShell (`-ErrorAction Stop` keeps setup from running in the wrong folder if the change fails):

```powershell
Set-Location -LiteralPath "<workspace>" -ErrorAction Stop; & "<install>\.venv\Scripts\reelsmith.exe" setup claude-code
```

bash:

```bash
cd "<workspace>" && "<install>/.venv/bin/reelsmith" setup claude-code
```

| you are | command |
|---|---|
| Claude Code | `reelsmith setup claude-code` |
| Codex (CLI, IDE extension or app) | `reelsmith setup codex` |
| DeepSeek Harness (dsh) | `reelsmith setup dsh` |
| Cursor | `reelsmith setup cursor` |
| any other MCP client | `reelsmith setup generic` (prints what to paste; writes nothing) |

Your own system prompt and tool names usually say which agent you are; if they do not, ask (rule 1). Each target
writes the MCP server into the agent's config in that folder and copies the reelsmith skill next to it;
`--print` shows what it would write, `--user` sets it up for every folder instead.

- **Claude Code:** it asks once to approve the folder's `.mcp.json` server. The plugin is the alternative:
  `/plugin marketplace add wangkant/reelsmith`, then `/plugin install reelsmith@reelsmith`; it starts
  `reelsmith-mcp` from `PATH`, so it needs doctor's `on-path` check to pass in the shell the agent starts from.
- **Codex:** it reads the folder's `.codex/config.toml` only once the folder is trusted: trust it when asked.
- **DeepSeek Harness:** start it with `dsh web --patch .dsh/reelsmith.cordis.yml` in that folder (or use `--user`).
  The reelsmith DSH plugin adds a video editor mode and panel: `<install>/integrations/dsh/README.md`.
- **Cursor:** if the reelsmith server shows as disabled in Cursor's MCP settings, enable it.

Run `reelsmith doctor --json --workspace "<workspace>"` again: its `agents` row now names the agent (doctor looks in
the current folder and in the workspace). The agent loads the server only at start: tell the user to quit it and
start it again in that folder. Until then you use the CLI, as the next step does.

## 7. Smoke test (free)

```bash
reelsmith new "<workspace>/projects/hello"
```

Write `<workspace>/projects/hello/ops.json` with your file tool:

```json
[
  {"op": "add_track", "track": {"id": "v1", "kind": "visual", "clips": []}},
  {"op": "add_clip", "track": "v1", "clip": {"id": "hello", "type": "text", "text": "Hello from **reelsmith**",
    "start": 0, "dur": 3, "box": "safe", "style": {"size": 120, "align": "center", "valign": "middle"},
    "enter": {"preset": "rise", "dur": 0.5}}}
]
```

Then (forward slashes work on Windows too; keep the quotes around the `@` argument in PowerShell):

```bash
reelsmith edit "<workspace>/projects/hello" "@<workspace>/projects/hello/ops.json"
reelsmith preview "<workspace>/projects/hello" 1 2.5
```

`preview` prints PNG paths. The first preview or render bundles the renderer and, if doctor's `remotion-browser`
row was false, downloads Remotion's browser, so it can take a minute or two. Read the 1.00 s still: it shows "Hello
from reelsmith" centred on a dark canvas, "reelsmith" in red. Then render:

```bash
reelsmith render "<workspace>/projects/hello"
```

Its first line starts with `DELIVERED:` and gives the film's path (`<workspace>/projects/hello/out/film.mp4`),
length and format; stage times and notes follow. No step here calls a paid service.

## 8. Report to the user

Keep it short:

- Where things are: `<install>`, `<workspace>`, the test film.
- What works now (the doctor rows that pass), and what needs something: a key in `<workspace>/.env` (name which
  key enables which tool), the Codex CLI for `draw`, a browser for `capture`.
- Which agent you attached, and that they must restart it in that folder (approve or trust the server if asked).
  Claude Code users whose renders time out can raise `MCP_TOOL_TIMEOUT` (milliseconds).
- A first request to try: "Make a 30-second vertical explainer on why the sky is blue" or "Cut my recording at
  ~/videos/talk.mp4 to its best 90 seconds and add captions".

## Update

PowerShell:

```powershell
git -C "<install>" pull --ff-only
& "<install>\.venv\Scripts\python.exe" -m pip install -e "<install>[capture,web]"
git -C "<install>" diff --quiet ORIG_HEAD HEAD -- renderer/package-lock.json; if ($LASTEXITCODE -ne 0) { npm.cmd ci --prefix "<install>\renderer" }
```

bash:

```bash
git -C "<install>" pull --ff-only
"<install>/.venv/bin/python" -m pip install -e "<install>[capture,web]"
git -C "<install>" diff --quiet ORIG_HEAD HEAD -- renderer/package-lock.json || npm ci --prefix "<install>/renderer"
```

The last line reinstalls the renderer's packages only when the pull changed their lock file: `npm ci` empties
`renderer/node_modules`, Remotion's downloaded browser included, which the next preview then downloads again.
Then run `reelsmith setup <agent>` again in the agent's folder (the skill is a copy) and
`reelsmith doctor --json --workspace "<workspace>"`.

## Undo

In the folder you set the agent up in (change to it in the same command, as in step 6), with your agent's target
(add `--user` if you used it there):

```bash
reelsmith setup claude-code --uninstall
```

Then delete `<install>` (the checkout, its `.venv` and the renderer's packages). Delete `<workspace>` only if the
user says so: it holds their projects. System tools you installed stay unless the user asks you to remove them.
