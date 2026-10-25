# reelsmith

**A video editing harness for AI coding agents.**

reelsmith gives a coding agent (Claude Code, Codex, DeepSeek Harness, Cursor or any MCP client) a real video
editor: a timeline of tracks, clips, keyframes, text and components that it edits with tools and code, looks at
frame by frame, and renders through checks that will not let a broken film out. It is not a text-to-video model.
The agent builds the film clip by clip from footage, pictures, narration and its own React components, the way a
person works in an editing app.

```
agent ── brief, footage, research
  │
  ├─ probe · frames · scenes · silences · transcribe ──▶ knows what is in the footage
  ├─ import_asset · speak · draw · capture · animate ──▶ assets/  voice/
  ├─ edit (tracks, clips, keyframes, transitions, ripple cuts, captions, components) ──▶ project.json
  ├─ describe · preview · check ──▶ the timeline as text, stills, contact sheets, measured layout ──▶ fix, repeat
  └─ render ──▶ layout pass ──▶ Remotion ──▶ loudness mastering ──▶ delivery checks ──▶ film.mp4, .srt, .vtt
```

There is no pipeline and no template. Every tool can be called at any time, `project.json` can be edited by hand,
and the agent decides the story, the cut, the sound and the look. reelsmith takes care of the mechanics: valid and
undoable edits, timing, rendering, layout measurement, loudness and the delivery rules.

## Quick start

```sh
git clone https://github.com/wangkant/reelsmith && cd reelsmith
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\Activate.ps1
pip install -e ".[capture,web]"
cd renderer && npm ci && cd ..
```

Attach it to your coding agent, in the folder you run the agent in:

```sh
reelsmith setup claude-code      # or: codex, dsh, cursor, generic (--print shows what it would write)
```

Then ask: *"Cut my talk in ~/videos/talk.mp4 to its best 90 seconds, remove the pauses, add English captions and a
title card."* or *"Make a 60-second vertical explainer on why tea leaves curl."*

Needs Python 3.10+, Node.js 20+ and ffmpeg on `PATH`; `reelsmith doctor` checks all of it, and what each optional
tool needs. reelsmith reads its manual and renderer from the checkout, so keep the editable install.

## Let your coding agent set it up

Paste this into Claude Code, Codex, Cursor or any coding agent:

```text
Read https://raw.githubusercontent.com/wangkant/reelsmith/main/docs/setup-for-agents.md and set up reelsmith for me.
```

It asks where to install and before installing any system tool, checks the machine with `reelsmith doctor`,
attaches itself with `reelsmith setup <agent>` and renders a test film without a paid call.

## What the agent can do

- **Edit a timeline.** Visual, audio and caption tracks; image, video, text, shape, evidence and component clips;
  keyframes with easing, Ken Burns moves, enter/exit presets, transitions, flips, filters and blend modes. Edits
  are atomic batches, validated and undoable.
- **Edit footage.** Probe a recording, look at stills at any source second, find shot cuts and silences, get a
  word-level transcript; cut with `"src:clip@12.4"` anchors, markers, ripple delete, insert gap and trim; reframe
  landscape footage for a vertical canvas with keyframed focus; speed curves, freeze frames and reverse; volume
  curves and ducking under the voice.
- **Captions and chapters.** Captions from the narration or from a transcript, following it through every cut,
  shown phrase by phrase or word by word, burned in and delivered as `.srt` and `.vtt`; chapters from markers.
- **Time to anything.** Times anchor on narration lines, clips, markers or source seconds (`"line:5+0.3"`,
  `"clip:c2.end-0.5"`, `"mark:intro"`, `"end-2"`): re-record the voice or recut a clip and the edit follows.
- **Look at its own work.** `describe` prints the editor's window as text; `preview` renders any moments in seconds
  with a contact sheet and measured layout problems; a draft render shows a stretch as video; `review` shows frames
  of the delivered film.
- **Make assets.** Narration (text-to-speech, cached per line), pictures (Codex image generation), evidence
  screenshots of web pages with the proving sentence boxed, short clips from a picture (image-to-video), and
  imports of local or downloaded media, animated GIFs included.
- **Write its own components.** Nine built-in React presets, and a documented kit for the agent's own components in
  the workspace library, type-checked and import-guarded.
- **Any canvas, any language.** `landscape` (the default, 1920×1080), `vertical`, `square`, `portrait`, platform
  profiles (`youtube`, `tiktok`, `shorts`, `reels`, `douyin`) and custom sizes and frame rates (NTSC included); a
  `locale` sets caption phrasing, the words components add, capture language and web requests; workspaces can add
  fonts.
- **Delivery checks.** Words outside the safe area, cut, tiny, overlapping or low in contrast (measured on rendered
  frames), loudness, black or frozen stretches, length, size and the workspace's own rules. A failed render keeps
  the previous film and says what to fix, with clip ids and times. Films of any length render.
- **Spend control.** Paid calls go through a ledger with a per-project budget and an account balance floor.

## Coding agents

| agent | how |
|---|---|
| Claude Code | `reelsmith setup claude-code`, or the plugin: `/plugin marketplace add wangkant/reelsmith`, then `/plugin install reelsmith@reelsmith` |
| Codex | `reelsmith setup codex` |
| DeepSeek Harness | the plugin in [integrations/dsh](integrations/dsh) (a Video editor mode with a film, preview and timeline panel), or `reelsmith setup dsh` |
| Cursor | `reelsmith setup cursor` |
| any MCP client | `reelsmith setup generic`, or run the server yourself: `reelsmith mcp` (stdio) or `reelsmith mcp --http` |
| no client | `reelsmith run <project> --brief "..."`: an agent makes the film headless, on reelsmith's own loop over any OpenAI-compatible API, or on Codex, DeepSeek Harness or the Claude Agent SDK (`--engine`) |

Every agent gets the same tools and the reelsmith skill ([skills/reelsmith/SKILL.md](skills/reelsmith/SKILL.md)).
[docs/agents.md](docs/agents.md) covers each one, the HTTP transport and headless runs.

## Workspaces and projects

A workspace is a folder for one creator or channel; its projects share settings, rules, keys, a component library
and the agent's notes:

```
studio/
  workspace.json    profile, locale, theme, providers, budget, runner defaults (all optional)
  rules.json        hard rules (block delivery) and advice (information only)
  .env              provider keys; never shown to the agent
  library/          NOTES.md, the agent's components/, fonts/
  projects/<film>/  project.json, assets/, voice/, build/ (previews), out/ (film, subtitles, chapters)
```

[examples/workspace](examples/workspace) is a starter; [examples](examples) also has one channel's setup to show
what a workspace can pin down. Every agent tool is also a command, for scripts and people (`reelsmith --help`):

```sh
P=~/studio/projects/first
reelsmith new $P --canvas 1920x1080@30 --locale en
reelsmith import $P talk ~/videos/talk.mp4      # bring in a recording (hard-linked when it can be)
reelsmith silences $P talk                     # silent ranges, in source seconds
reelsmith edit $P @ops.json                    # apply a batch of edit ops
reelsmith preview $P 0 mark:intro end-1        # stills + contact sheet + layout problems
reelsmith render $P                            # out/film.mp4, mastered and checked, with its subtitles
```

## Optional services

| for | you need |
|---|---|
| `capture` (web page evidence) | the `capture` extra and Edge, Chrome or `python -m playwright install chromium` |
| `draw` (pictures) | the [Codex CLI](https://github.com/openai/codex), signed in |
| `speak` (narration) | an [OpenRouter](https://openrouter.ai) key (the default voice speaks English and Mandarin), or any OpenAI-compatible speech endpoint (`providers.tts.provider: "openai"`) |
| `animate` (image-to-video) | an OpenRouter key |
| `transcribe` | any OpenAI-compatible transcription endpoint (OpenAI, Groq, a local whisper server), or the `transcribe` extra (faster-whisper, on your machine) |
| `reelsmith run` | a model API key (OpenRouter by default; DeepSeek, OpenAI or a local server), or Codex or DeepSeek Harness installed; the `runner` extra for the Claude Agent SDK engine |

Paid calls estimate first and are refused over `budget.per_project_usd` (default $1) or under the account floor
`budget.min_balance_usd` (default $5); narration is cached per line, so only changed lines are paid for again.

## Documentation

- [docs/manual.md](docs/manual.md): the agent's manual (what the `manual` tool returns).
- [docs/editor-spec.md](docs/editor-spec.md): the full reference: layout, settings and defaults, the project format,
  edit ops, providers, checks, profiles, the renderer's input and the runner.
- [docs/agents.md](docs/agents.md): attaching coding agents and running them headless.
- [docs/kit.md](docs/kit.md): `@reelsmith/kit`, for writing components.

## Development

```sh
pip install -e ".[dev]" && pytest
cd renderer && npm run typecheck && node test/selftest.mjs && cd ..
cd integrations/dsh && npm ci && npm test && cd ../..
python integrations/sync_skills.py --check     # the plugin's copy of the skill
```

## License

MIT, see [LICENSE](LICENSE).

The renderer depends on [Remotion](https://www.remotion.dev), which has its own license: free for individuals and
small teams; larger companies need a Remotion company license (https://www.remotion.dev/license). The bundled
Smiley Sans font is under the SIL Open Font License
([renderer/src/fonts/SmileySans-OFL.txt](renderer/src/fonts/SmileySans-OFL.txt)).
