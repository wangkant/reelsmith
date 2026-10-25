# reelsmith

A video editor built for AI agents. The agent writes the script, gathers its own assets and edits a timeline with
tools, the way a person works in an editing app; reelsmith renders the film and checks it before it can be
delivered.

It is for people who let an agent (Claude Code, Codex or any MCP client) make short vertical videos and want it to
have a real editor rather than a fixed template, with a platform that will not let a broken film out. With no
client at all, `reelsmith run` drives any model behind an OpenAI-compatible API (OpenRouter, DeepSeek, OpenAI, a
local server) through the same tools.

```
agent ── research, script.md
  │
  ├─ speak · draw · capture · animate · import_asset ──▶ voice/  assets/
  ├─ edit (tracks, clips, keyframes, text, shapes, components) ──▶ project.json
  ├─ check · preview ──▶ stills, contact sheet, measured layout problems ──▶ fix, repeat
  └─ render ──▶ layout pass ──▶ Remotion ──▶ loudness mastering ──▶ delivery checks ──▶ out/film.mp4
```

There is no pipeline and no shot template: every tool can be called at any time, and the agent decides the story,
the voice, the pictures and the cut. The platform guarantees the mechanics: timing to the narration, rendering,
layout measurement, loudness and the delivery rules.

## Features

- **An NLE-style project** (`project.json`): visual, audio and caption tracks; image, video, text, shape, evidence
  and component clips; keyframes with easing, Ken Burns moves, enter/exit presets, filters and blend modes;
  captions phrase-split and timed from the narration.
- **Times anchored on the narration**: `"line:5+0.3"`, `"clip:c2.end-0.5"`, `"end-2"`. Re-record the voice and the
  cut follows it.
- **Atomic, validated, undoable edits**: a batch of ops applies whole or not at all. `project.json` can also be
  edited by hand; every tool reads it fresh.
- **Asset tools**: narration (text-to-speech, cached per line), original pictures (Codex image generation),
  evidence screenshots of web pages at phone width with the proving sentence boxed, short clips from a picture
  (image-to-video), and imports of local or downloaded media.
- **Footage editing**: probe, stills at source times, shot cuts, silences and word-level transcripts of the
  agent's own recordings; `"src:clip@seconds"` anchors and markers; ripple delete, insert gap and trim;
  transitions between clips; volume curves and ducking; captions that follow a transcript.
- **Components**: nine built-in React presets (receipt, count-up, bar comparison, timeline, dot grid, stamp,
  evidence card, highlighter, arrow). The agent can write its own into the workspace library, with a documented
  kit, a type checker and an import guard.
- **Cheap looks**: `preview` renders any moments in seconds with a contact sheet that shows the platform's UI bands
  and the safe area; `describe` prints the editor's window as text.
- **Delivery checks**: words outside the safe area, cut, tiny, overlapping or low in contrast (measured on rendered
  frames), loudness, black or frozen stretches, size, length and the workspace's own rules.
- **Spend control**: paid calls go through a ledger with a per-project budget and an account balance floor.
- **Three ways in**: an MCP server, a CLI, and a self-hosted runner that works with any OpenAI-compatible model
  API (a Claude Agent SDK session is an optional engine).
- **Output profiles** `douyin` (the default), `douyin-long` (60-300 s explainers), `tiktok` and `shorts`:
  1080×1920 at 30 fps, each with its own safe area, length limits, size cap and loudness target.

The defaults are tuned for Chinese short video: Simplified Chinese fonts, CJK-aware line breaking, a Mandarin
narration voice and Chinese browser locale for captures. English works as well; set `profile` and the TTS `voice`
in `workspace.json` to match your audience.

## Requirements

- Python 3.10 or newer
- Node.js 20 or newer, with npm (the renderer)
- ffmpeg and ffprobe on `PATH`

Optional, per tool:

| for | you need |
|---|---|
| `capture` (evidence screenshots) | the `capture` extra and a Chromium browser: Microsoft Edge or Google Chrome if installed, else `python -m playwright install chromium` |
| `draw` (pictures) | the [Codex CLI](https://github.com/openai/codex), installed and signed in |
| `speak` (narration), `animate` (video clips) | an [OpenRouter](https://openrouter.ai) API key |
| `transcribe` (word timing of recordings) | a key for any OpenAI-compatible transcription endpoint (OpenAI, Groq, a local whisper server), or the `transcribe` extra (faster-whisper) |
| `reelsmith run` (the self-hosted agent) | a key for the model's API: [OpenRouter](https://openrouter.ai) (the default), [DeepSeek](https://platform.deepseek.com), OpenAI, or none for a local server; the `web` extra for keyless web search |
| `reelsmith run --engine agent-sdk` | the `runner` extra and an Anthropic or a DeepSeek API key |

## Install

reelsmith reads its manual (`docs/`) and its renderer (`renderer/`) from the checkout, so install it editable:

```sh
git clone https://github.com/wangkant/reelsmith
cd reelsmith
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\Activate.ps1 (PowerShell)
pip install -e ".[capture,web]"      # or just: pip install -e .
cd renderer && npm ci && cd ..
```

The extras are `capture` (Playwright), `web` (ddgs, the runner's web search without a key), `runner` (the Claude
Agent SDK, only for the `agent-sdk` engine) and `dev` (pytest). Remotion fetches the headless browser it renders
with on first use; `npx remotion browser ensure` (in `renderer/`) does it ahead of time.

## A workspace

A workspace is a folder for one creator or channel. Projects inside it share its settings, rules, keys, component
library and notes:

```
studio/
  workspace.json    output profile, theme, providers, budget, runner defaults
  rules.json        hard rules (block delivery) and advice (information only)
  .env              OPENROUTER_API_KEY=...   (and any other provider's key)
  library/
    NOTES.md        the agent's own notes, read at the start of work
    components/     the agent's own React components (Name.tsx + Name.meta.json)
  projects/
    <film>/         project.json, script.md, voice/, assets/, build/ (previews), out/film.mp4
```

`examples/workspace` is a starter: settings, rules, and a library with notes and one sample component. Copy it,
add a `.env`, and create a project:

```sh
cp -r examples/workspace ~/studio
reelsmith new ~/studio/projects/first-film --title "My first film"
```

Every key is optional; [docs/editor-spec.md](docs/editor-spec.md) lists them all with their defaults.

## Use it from Claude Code

Add the MCP server to the project you run Claude Code in, as `.mcp.json`:

```json
{
  "mcpServers": {
    "reelsmith": {
      "command": "reelsmith-mcp",
      "env": {"REELSMITH_ROOT": "/home/me/studio"}
    }
  }
}
```

Then ask for a film: *"Make a 60-second film about why tea leaves curl, in /home/me/studio/projects/tea. Read the
reelsmith manual first."*

## Use it from Codex

In `~/.codex/config.toml`:

```toml
[mcp_servers.reelsmith]
command = "reelsmith-mcp"
env = { REELSMITH_ROOT = "/home/me/studio" }
tool_timeout_sec = 3600
```

Notes for any MCP client:

- `reelsmith-mcp` is installed into the virtual environment; use its full path when that environment is not on
  `PATH`, or run `python -m reelsmith.mcp_server` (or `reelsmith mcp`) with its Python.
- `REELSMITH_ROOT` is optional. When set, the tools refuse projects outside that folder and imports of local files
  from outside it.
- `render` can run for many minutes in one call. Raise the client's tool timeout: `tool_timeout_sec` in Codex,
  the `MCP_TOOL_TIMEOUT` environment variable (milliseconds) in Claude Code.
- The server's instructions point the agent at the `manual` tool; [docs/manual.md](docs/manual.md) is that text.

## The CLI

Every agent tool is also a command, for scripts and for people (`reelsmith --help`, `reelsmith <command> --help`):

```sh
P=~/studio/projects/first-film
reelsmith describe $P                          # the editor's window as text
reelsmith speak $P @lines.txt                  # narrate: one voice line per line of the file (paid)
reelsmith import $P bed ~/music/bed.m4a audio  # bring in a file
reelsmith edit $P @ops.json                    # apply a batch of edit ops (JSON, @file or - for stdin)
reelsmith undo $P
reelsmith check $P                             # errors, warnings, advice
reelsmith preview $P 0 line:3 end-1            # stills of chosen moments + contact sheet + layout problems
reelsmith preview $P --sweep                   # measure the whole film's layout, as render does
reelsmith render $P                            # out/film.mp4, mastered and checked
reelsmith review $P -n 12                      # frames of the delivered film
```

The other commands: `manual`, `new`, `library`, `typecheck`, `capture`, `draw`, `animate`, `assets`, `notes`,
`note`, `run` and `mcp`. A command exits with 1 when the call failed or found blocking problems.

## The self-hosted runner

`reelsmith run` lets an agent make one film on its own, with no client attached. It talks to any model behind an
OpenAI-compatible Chat Completions API with tool calling: OpenRouter (the default), DeepSeek, OpenAI, a Qwen or GLM
gateway, or a local server. Claude is not required; a Claude Agent SDK session is an optional engine.

```sh
reelsmith run ~/studio/projects/tea --brief "A 60-second film on why tea leaves curl" --budget-usd 2
```

| flag | |
|---|---|
| `--brief` | what the film is about; needed unless an unfinished run resumes |
| `--engine` | `api` (default): reelsmith's own agent loop over an OpenAI-compatible API; `agent-sdk`: a Claude Agent SDK session |
| `--provider` | `openrouter` (default), `deepseek`, `openai` or `custom` (the `api` engine) |
| `--backend` | `anthropic` (default) or `deepseek` (the `agent-sdk` engine) |
| `--model` | default `deepseek/deepseek-v4.1-flash` on OpenRouter, `deepseek-flash` on DeepSeek; `openai` and `custom` need one |
| `--budget-usd` | cap on this run's model spend (asset spend has its own budget) |
| `--max-minutes` | wall-clock cap |
| `--max-turns` | model-call cap per session |
| `--fresh` | ignore an unfinished run and start a new session |

Every flag has a `runner` key in workspace.json. The session gets the reelsmith tools, file tools fenced to the
workspace by a guard, and web fetch and search; there is no shell. It ends when the film passes the render checks;
otherwise the runner hands the session the exact problems and lets it fix them, within the budget and the time
limit. An interrupted run resumes its own session. `out/run_report.json` says how it ended. Exit status: 0
delivered, 1 not delivered, 2 a setup problem.

### Run on DeepSeek through OpenRouter

This is the default. Put `OPENROUTER_API_KEY=...` in the workspace `.env` (or the environment), and optionally pin
the choice in workspace.json:

```json
"runner": {"provider": "openrouter", "model": "deepseek/deepseek-v4.1-flash", "reasoning": "medium", "budget_usd": 2}
```

- **Models.** `deepseek/deepseek-v4.1-flash` takes images, so the agent sees its preview stills and review frames.
  `deepseek/deepseek-v4-pro` is text-only: its tools return a note instead of pictures, and it edits without seeing
  the frames.
- **Spend.** OpenRouter reports each call's cost; the runner adds it up and stops a session at the budget.
- **Web search.** The `web` extra searches without a key (ddgs); a `TAVILY_API_KEY` works too. Without either the
  agent can still fetch pages.

### Other providers

| `--provider` | key (workspace `.env`, else the environment) | endpoint | spend |
|---|---|---|---|
| `openrouter` | `OPENROUTER_API_KEY` | `https://openrouter.ai/api/v1` | reported by OpenRouter |
| `deepseek` | `DEEPSEEK_API_KEY` | `https://api.deepseek.com` | estimated at DeepSeek's peak prices |
| `openai` | `OPENAI_API_KEY` | `https://api.openai.com/v1` | from `runner.prices` |
| `custom` | `runner.key_env`, or none | `runner.base_url` | from `runner.prices` |

A local server, or any other compatible gateway:

```json
"runner": {"provider": "custom", "base_url": "http://localhost:8000/v1", "model": "qwen3-vl-32b",
           "prices": {"qwen3-vl-32b": [0, 0]}}
```

`prices` gives `[input, output, cached input]` in $ per million tokens for providers that report no cost; without
a price the spend is not counted and the runner says so. Set `"images": false` for a text-only model the runner
does not know.

### The Claude Agent SDK engine

`--engine agent-sdk` (or `--backend ...`) runs the session in the Claude Agent SDK instead; it needs the `runner`
extra. It is served by Anthropic (`ANTHROPIC_API_KEY`, default `claude-opus-5-5`) or by DeepSeek's
Anthropic-compatible API (`--backend deepseek`, `DEEPSEEK_API_KEY`, default `deepseek-flash`). Each backend's key
goes to that backend only. The CLI prices every session with its Claude table, so on DeepSeek the runner estimates
the spend from the streamed token usage at DeepSeek's peak prices (off-peak hours cost half), stops a session that
reaches the budget, and keeps the CLI's figure as `cli_cost_usd` for reference only. A workspace whose `runner`
names a `backend` and no `engine` keeps running on this engine.

A run resumes on the engine, provider (or backend) and model it started on; `--fresh` starts it over on another.

## What the checks enforce

`check` (and `render` before it spends anything) blocks on:

- a project that does not validate: unknown ids, missing files, clips overlapping on a track, Times that do not
  resolve, component props that fail their schema;
- the workspace's hard rules (`rules.json`): by default a title of at most 24 characters with at most 2 numbers, at
  least one source with an http(s) url, no banned words;
- a length outside the profile's limits.

`render` then measures a still every second and refuses words outside the safe area or cut by the canvas edge, text
under 20 px and crashing components; encodes the film; masters its loudness; and refuses a film without sound,
with more than 10 % black, with a stretch longer than 5 s where nothing moves, or over the size cap. A refused
render keeps the previous film and reports what to fix with clip ids and times. Warnings (small, overlapping or
low-contrast text, an unreadable evidence crop, a cover frame without whole words) and advice (the hook, long
still shots, the target length) never block.

## Costs

`speak` and `animate` call paid APIs. Each call estimates its cost first, then reserves it in the workspace's
`ledger.jsonl`, and is refused when it would take the project over `budget.per_project_usd` (default $1) or the
provider account under `budget.min_balance_usd` (default $5). A call settles with the real cost when the provider
reports one. Narration is cached per line, so only changed lines are paid for again; an image-to-video job that
was already submitted is collected, never bought twice. `draw` runs on the Codex CLI's own allowance and is capped
at `providers.image.max_draws` tries per project (default 30). `assets` shows the project's spend.

## Documentation

- [docs/manual.md](docs/manual.md): the agent's manual (what the `manual` tool returns): the project format, Times,
  every tool, edit ops, components and what blocks delivery.
- [docs/editor-spec.md](docs/editor-spec.md): the full reference: layout, settings and defaults, formats, providers,
  checks, the renderer's input and the runner.
- [docs/kit.md](docs/kit.md): `@reelsmith/kit`, for writing components.

## Development

```sh
pip install -e ".[dev]"
pytest
cd renderer
npm run typecheck
node test/selftest.mjs                       # renders the test timelines and checks the frames
node test/presets-preview/kit-test.mjs       # @reelsmith/kit helpers
node test/presets-preview/check.mjs          # every preset at its meta example and edge cases
npx tsc --noEmit -p test/presets-preview
python test/presets-preview/check_meta.py    # component meta schemas
```

## License

MIT, see [LICENSE](LICENSE).

The renderer depends on [Remotion](https://www.remotion.dev), which has its own license: free for individuals and
small teams, while larger companies need a Remotion company license (see https://www.remotion.dev/license). The
bundled Smiley Sans font is under the SIL Open Font License
([renderer/src/fonts/SmileySans-OFL.txt](renderer/src/fonts/SmileySans-OFL.txt)).
