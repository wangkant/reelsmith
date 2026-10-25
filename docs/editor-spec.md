# reelsmith reference

The platform's contract: where things live, the project format, the edit ops, the Time grammar, the tools and the
providers behind them, the renderer's input, the checks a film must pass and the self-hosted runner. The agent's
own guide is [manual.md](manual.md); the component kit is documented in [kit.md](kit.md). Section numbers are stable
(the source refers to them).

## 1. Principles

- **Environment, not pipeline.** No stages, no required order, no templates. Every tool can be called at any time.
- **The agent edits a project like an NLE project**: tracks, clips, keyframes, text, shapes, media, components.
- **Self-editable.** The agent can write its own components into the workspace library (they persist and shadow
  built-in presets of the same name) and keep its own notes. Built-in presets are optional conveniences.
- **The platform guarantees mechanics, not taste**: timing to the narration, rendering, loudness, layout
  measurement, delivery checks. The owner's hard rules (`rules.json`) block delivery; advice is information only.
- **Every edit is validated and undoable.** A batch of edit ops applies atomically or not at all.
- **Spend is explicit.** Paid calls estimate first, check the budget and the balance floor, and record what they
  really cost.
- **Tools never raise to the client.** A failure comes back as text that says what to do.

## 2. Workspace layout

```
<workspace>/                      the nearest folder at or above the project that holds workspace.json
  workspace.json                  profile, locale, profiles, fonts, theme, providers, budget, runner (all optional)
  rules.json                      the owner's rules {"hard": {...}, "advice": {...}} (optional)
  .env                            keys (OPENROUTER_API_KEY, ANTHROPIC_API_KEY, ...); never printed or shown to the agent
  ledger.jsonl                    paid calls (section 9.6)
  .cache/                         narration line cache (tts/), draw.log, animate work files, the type-check config,
                                  the runner's DSH home (dsh/)
  library/
    NOTES.md                      the agent's notes (tools notes / note)
    components/<Name>.tsx         the agent's own components (section 6)
    components/<Name>.meta.json
    fonts/<Family>.woff2          the workspace's fonts (.woff2, .woff, .ttf or .otf; section 2.1)
  projects/<name>/
    project.json                  the project (section 3)
    script.md                     free-form: research, sources, draft script
    voice/voice.wav               narration audio (from speak, or brought in)
    voice/voice.json              narration timing {file, duration_s, lines: [{i, text, t0, t1}], ...}
    assets/                       images, clips, evidence captures, audio; <id>.transcript.json (transcribe)
    build/                        regenerable: resolved*.json, stills/, inspect/, review/, footage/<name>/ (stills of
                                  sources from frames and scenes), fonts/ (the workspace's fonts, linked for the
                                  renderer), segments.json, report.json (latest render attempt), run_state.json,
                                  agent_messages.json, dsh-patch.yml and logs of the runner
    out/film.mp4                  the delivered film; out/meta.json (meta + duration, profile, render time);
                                  out/report.json (the delivered film's report); out/run_report.json (runner)
    .history/NNNN.json            a snapshot of project.json before each applied edit batch (undo); log.jsonl,
                                  redo.json
```

A project may live outside any workspace: then there is no library and no notes, rules and providers take their
defaults, keys come from the environment, and the ledger and cache sit in the project folder.

`.env` holds `KEY=VALUE` lines (`export`, quotes and `#` comments are understood). A key missing from `.env` is
looked up in the process environment.

### 2.1 workspace.json

```json
{
  "profile": "landscape",
  "locale": "en",
  "profiles": {"channel": {"base": "youtube", "fps": 25}},
  "fonts": {"Brand Sans": "library/fonts/brand-sans.woff2"},
  "theme": {"name": "paper", "accent": "#C8372D"},
  "providers": {
    "tts": {"provider": "openrouter", "model": "qwen/qwen-audio-3.0-tts-plus", "voice": "<voice id>"},
    "image": {"provider": "codex"},
    "video": {"provider": "openrouter", "model": "bytedance/seedance-1-5-pro", "resolution": "720p"},
    "transcribe": {"provider": "openai", "base_url": "https://api.openai.com/v1", "model": "whisper-1"}
  },
  "budget": {"per_project_usd": 1.0, "min_balance_usd": 5.0},
  "runner": {"provider": "openrouter", "model": "deepseek/deepseek-v4.1-flash", "budget_usd": 5.0, "max_minutes": 120}
}
```

| key | meaning |
|---|---|
| `profile` | output profile (section 15): a name or an inline profile (section 15.1); a project's own `profile` wins; default `landscape` |
| `locale` | the films' language, a BCP-47 tag (`en`, `en-GB`, `zh-CN`, `ja`); a project's own `locale` wins; default `en`. It sets how captions are phrased and how long a caption may be (section 3), capture's browser language (9.2), the runner's web language (11) and whether the TTS has a default voice (9.1) |
| `profiles` | custom profiles by name, each `{"base": name, field: value, ...}` (section 15.1); a name may not be a built-in one |
| `fonts` | font families for TextStyle `font` and components: `{family: path | {"src", "weight"?, "style"?} | [...]}`, paths inside the workspace (`weight` like `"400"`, or `"100 900"` for a variable font; `style` `normal`, `italic` or `oblique`). Every `library/fonts/*.woff2`, `.woff`, `.ttf` and `.otf` is a family named after its file stem without being listed (a stem other than letters, digits, spaces, `_` and `-`, or one of the built-in names, is skipped); the map adds families and wins over a stem of the same name |
| `theme` | `name` (`paper` or `night`) and token overrides; a project's `theme` is laid over it |
| `providers` | per-tool provider settings (section 9); each section is merged over the defaults |
| `budget` | `per_project_usd` (default 1.0) and `min_balance_usd` (default 5.0), section 9.6 |
| `runner` | defaults for `reelsmith run`: `engine` (`api` or `agent-sdk`), `provider` or `backend`, `model`, budget, limits and the api engine's settings (section 11) |

A malformed `locale`, `profiles` or `fonts` entry makes every tool report the workspace problem until it is fixed.

### 2.2 rules.json

```json
{"hard": {"max_title": 24, "max_title_numbers": 2, "min_sources": 1, "banned": []},
 "advice": {"hook_seconds": 2, "max_same_visual_s": 8, "target_s": [45, 75]}}
```

Every key is optional and none has a default: without rules.json (or with `{}`) there is no hard rule and no
advice. The example above is a news explainer's set (the example workspace's). Hard rules are errors (they block
`render`): the title's length in characters, how many numbers it may hold, how many sources with an http(s) url
`meta.sources` needs, and words that may not appear in the title, description or topic. Advice never blocks: words
on screen within `hook_seconds`, no still image or evidence held longer than `max_same_visual_s` without movement,
the length against `target_s`: `[min, max]` seconds, or `true` for the profile's target (section 15; a profile
without one gives no advice). An empty title is a warning only where a title rule (`max_title` or
`max_title_numbers`) is set: a film for a generic canvas needs no post title.

## 3. project.json

```
{
  "version": 2,
  "profile": "landscape",              optional: a name or an inline profile (section 15.1); overrides workspace.json
  "locale": "en",                      optional: the film's language (BCP-47); overrides workspace.json
  "theme": {},                         optional: {"name": "night"} and/or token overrides
  "meta": {"title": "", "desc": "", "topic": "", "shape": "", "sources": [{"title": "", "url": "https://..."}]},
  "voice": "voice/voice.json",         optional narration timing file; its audio plays at volume 1 automatically
  "duration": null,                    seconds or a Time; default: end of the voice + 0.6 s, else the last clip end
  "markers": {"<name>": Time},         optional named points of the film ("mark:NAME", section 3.1)
  "assets": {"<id>": Asset},
  "tracks": [Track, ...]               bottom to top
}
```

Unknown keys are refused everywhere. Ids (assets, tracks, clips) and marker names are 1-64 letters, digits, `_` or
`-`; clip ids are unique in the project. Paths are relative to the project folder.

**Asset**: `{"path": "assets/x.png", "kind": "image"|"video"|"audio"|"evidence", "box": [x, y, w, h], "site": "",
"url": "", "note": "", "transcript": "assets/x.transcript.json"}`. `box` (pixels in the image: the proving
sentence), `site` and `url` belong to evidence. `transcript` (video and audio; written by `transcribe`, section 9.8)
names the asset's word timing: `{"version": 1, "asset", "source", "duration_s", "language", "provider", "text",
"words": [{"word", "start", "end"}], "segments": [{"start", "end", "text"}]}`, times in source seconds. A missing
or unreadable transcript is a warning (an error when captions follow it).
Accepted files: image `.png .jpg .jpeg .webp .gif`; evidence `.png .jpg .jpeg .webp`; video `.mp4 .m4v .mov .webm
.mkv`; audio `.wav .mp3 .m4a .aac .ogg .oga .opus .flac`. An image clip takes an image or evidence asset, an audio
clip an audio or video asset.

**Track**: `{"id": "v1", "kind": "visual"|"audio"|"captions", "hidden": false, ...}`

- visual / audio: `"clips": [Clip, ...]`. Clips on one track must not overlap in time: layer with more tracks. The
  one exception is a clip with a `transition` (section 3.2): it may overlap the clip just before it on its track by
  at most the transition's `dur`.
- captions: `{"id": "cap", "kind": "captions", "source": "voice" | "clip:<id>", "box"?, "style"?: TextStyle,
  "emphasis": [words in the accent colour], "max_chars"?: 4-60, "overrides": [{"line": 5, "text": "..."}],
  "items"?: [{"start": Time, "end": Time, "text": "..."}]}`. `max_chars` defaults by the locale: 14 for Chinese,
  Japanese and Korean, 32 otherwise. Without `items`, captions come from the `source`:
  - `"voice"`: the voice lines, phrase-split between the words of the locale (`Intl.Segmenter`; never inside a word
    or a number, and in English not right after an article, preposition or conjunction when another cut fits) and
    timed by characters.
  - `"clip:<id>"`: the transcript of that video or audio clip's asset (section 9.8). Each word is placed where the
    clip plays it (its start, `trim_in` and `rate`; a word whose middle the trim cuts away is dropped), through the
    named clip and every other clip on its track that plays the same asset with sound (the pieces a split or a
    ripple edit made of it). Phrases are cut by the words' timing: a pause of 0.5 s, the end of a sentence, a
    clause end past half of `max_chars`, or `max_chars` itself (words are joined with spaces, except around CJK,
    kana, Thai and similar scripts and before closing punctuation); a phrase stays up until the next one across a
    gap under 1 s, else 0.3 s after its last word, and never past its clip. A looping clip cannot be followed;
    `overrides` apply to voice captions only.

  Without `box` they sit in the profile's captions band (section 15). Without a captions track there are no
  captions.

### 3.1 Time

A Time is a number (seconds from the start of the film) or a string:

- `"line:N"` start of voice line N (1-based); `"line:N.end"` its end
- `"clip:ID"` start of clip ID; `"clip:ID.end"` its end
- `"mark:NAME"` the project marker NAME (`markers`, section 3; a marker is itself a Time)
- `"src:ID@S"` the film time at which source second S of video or audio clip ID plays: start + (S − trim_in) ÷
  rate. A looping clip (a source second plays more than once) and a second before its `trim_in` are errors; a
  second past the clip's end resolves but is a warning (that moment is not in the film). This is how source times
  from `scenes`, `silences` and transcripts become cut points.
- `"end"` end of the film
- any of these `+` or `-` seconds: `"line:5+0.3"`, `"clip:c2.end-0.5"`, `"mark:hit-1"`, `"src:c1@12.5+0.2"`,
  `"end-2"`

Inside a clip (keyframe `t`, `highlight.at`, component props `at` / `*_at`) a plain number is seconds from the
clip's start; a Time string stays absolute. A clip's own `start` / `end`, `duration` and caption `items` are film
Times.

Seconds become frames as `round(s × fps)`, halves up (`timeexpr.to_frame`). Cycles in `clip:`, `mark:` and `src:`
references (`src:ID` depends on ID's start) are an error. `resolve.time_of(project, value)` turns a Time into
seconds outside the renderer. In `preview` and `describe(at=...)`, `"clip:ID.end"` means the clip's last frame.

### 3.2 Clip (visual)

Common fields:
```
id, type, start: Time, end: Time | dur: seconds          one of end and dur
box: {x,y,w,h} | "full" | "safe"          default "full"; canvas pixels
opacity 1, rotate 0 (deg), scale 1, origin "center"|"top-left"|..., radius 0
blend "normal"|"multiply"|"screen"|"overlay"|"darken"|"lighten"|... (CSS mix-blend-mode values)
filter: {blur, brightness, contrast, saturate, grayscale}   (CSS filter units)
shadow: bool | css string
enter: {"preset": "fade"|"rise"|"drop"|"pop"|"wipe_left"|"wipe_up"|"zoom", "dur": 0.4}   exit: the same presets
transition: {"type": "crossfade"|"dip_black"|"dip_white"|"wipe_left"|"wipe_right"|"wipe_up"|"slide_left"|"zoom",
     "dur": 0.5}   in from the previous clip on the SAME track (below)
keyframes: {"<prop>": [{"t": number | Time, "v": number, "ease": "linear"|"in"|"out"|"inOut"|"spring"|"step"}]}
     props: x, y, w, h, opacity, rotate, scale, blur, brightness, zoom, pan_x, pan_y, progress, volume
     zoom/pan_x/pan_y move the CONTENT inside the box (Ken Burns); progress (0..1) drives shapes and components;
     volume (>= 0) is a video clip's sound curve, replacing its volume (an error on other visual clips)
motion: "push"|"pull"|"pan_left"|"pan_right"|"rise"|"still"   (image/video shorthand for zoom/pan keyframes;
     keyframes on the same property win)
```

Types and their fields:

- `image`: `asset`, `fit` `"cover"|"contain"` (default cover), `focus` `[fx, fy]` 0..1, `motion`
- `video`: `asset`, `trim_in` s (source seconds skipped), `rate` 1 (source seconds per film second), `loop` false,
  `fit`, `focus`, `motion`, `volume` 0 (muted); film second t of the clip shows source second trim_in + (t − start)
  × rate
- `text`: `text` (markup `**x**` = accent colour), `style`: TextStyle, `reveal`: `{"mode": "chars"|"words"|"lines"|
  "none", "dur": s}` (`lines` reveals the lines as laid out)
- `shape`: `shape` `"rect"|"ellipse"|"line"|"arrow"|"path"`, `fill`, `stroke`, `stroke_width`, `d` (SVG path in box
  pixels), `draw` (the stroke draws on along `progress`, by default over the first 0.6 s). A line or arrow with
  only `fill` is stroked in that colour.
- `evidence`: `asset` (kind evidence). The capture's `box` is scaled to the clip width (at most 2×) with context
  above and below; the panel hugs its content (the rest of the box is transparent) and cut edges fade.
  `highlight`: `{"at": Time?, "dur": 0.8, "color": "gold"}` sweeps across the proving sentence.
- `component`: `name`, `props` (validated against the component's meta schema)

TextStyle: `font` `"sans"|"serif"|"display"|"zcool"` (Noto Sans SC, Noto Serif SC, Smiley Sans, ZCOOL QingKe
HuangYou) or a family of the workspace's fonts (section 2.1; glyphs it lacks fall back to the sans), `size` px or
`"fit"` (the largest size that fits the box width and height on as many word-aware lines as it takes), `max_size`
160, `min_size` 28 (the default `size`, `max_size` and `min_size` are for a canvas whose short side is 1080 px and
scale with it), `weight` 100-900, `color` (default `snow` with a soft shadow), `accent`,
`align` `"left"|"center"|"right"`, `valign` `"top"|"middle"|"bottom"`, `line_height` 1.15, `letter_spacing` 0,
`wrap` true, `balance` false (exactly two even lines), `stroke` `{color, width}`, `shadow` bool or CSS, `bg`
`{color, radius, pad}`.

Colours (text, shapes, highlights, component colour props) take a theme token (section 15) or any CSS colour.

Audio clip: `{id, type: "audio", asset, start, end | dur, trim_in 0, volume 1, fade_in 0, fade_out 0, loop false,
keyframes?: {"volume": [Keyframe]}, transition?: {"type": "crossfade", "dur"}, duck?: {"under": "<track id>" |
"voice", "to": 0.25, "fade": 0.3}}`.

- `keyframes.volume` (audio and video clips): the volume over time, keyframed like any property (numbers count
  from the clip's start); it replaces `volume`. Volumes above 1 are capped at 1 (mastering sets the loudness).
- `duck`: the clip's gain drops to `to` while the named track (an audio track, or a visual track's video clips
  with sound) or the narration (`"voice"`) has sound, easing over `fade` seconds before each stretch and after it.
  The stretches are approximated from the timeline, not measured from the audio: the voice lines' `t0`-`t1`, or
  the extents of the track's sounding clips (volume or volume keyframes above 0), with gaps up to 2 × `fade`
  bridged so a bed does not pump between phrases. A clip cannot duck under its own track.

**Transitions.** A clip's `transition` happens over its first `dur` seconds, from the clip just before it on the
same track (the one that starts last before it), which it paints over. That clip may overlap it by at most `dur`;
overlap them by exactly `dur` for a full two-sided transition, e.g. `"start": "clip:a.end-0.5"` with `"dur": 0.5`.
Where the previous clip has already ended (less overlap, a gap, or the first clip of a track), the clip
transitions in over whatever is beneath it. `crossfade` fades it in over the previous clip; `dip_black` /
`dip_white` fade the previous clip to the colour over the first half and this one out of it over the second;
`wipe_left` / `wipe_right` / `wipe_up` reveal it behind a moving edge (`wipe_left`: the edge travels leftward);
`slide_left` pushes it in from the right while the previous clip slides out to the left; `zoom` fades it in from
1.2× while the previous clip grows. Wipes, slides and zooms ease in and out; fades and dips are linear. A clip
with sound fades its sound in over `dur`, and a previous clip with sound fades out over the overlap (audio clips
take only `crossfade`, which crossfades their volume the same way). A transition longer than either clip, an
overlap longer than the transition, and an overlap with any clip other than the previous one are errors.

### 3.3 Component props and Times

In component props, any key named `at` or ending in `_at` takes a Time and reaches the component as **frames from
the clip's start**; any key named `asset` or ending in `_asset` takes an asset id and reaches the component as
`{src, kind, size?, box?, site?, duration?}`. This applies at any depth (arrays, nested objects).

## 4. Python API (package `reelsmith`)

Problems everywhere are `Issue(level: "error"|"warning"|"advice", where: str, msg: str)` (`issues.py`); `str()`
gives `"[level] where: msg"`.

- `workspace.py`: `Workspace` (`root`, `config`, `rules`, `keys`, `profiles`, `locale`, `fonts`, `library_dir`,
  `components_dir`, `fonts_dir`, `notes_path`, `ledger_path`, `cache_dir`, `projects_dir`); `find_workspace(project)
  -> Workspace | None`; `project_paths(project)`; `profile_for(project)`; `locale_for(project)`.
- `profiles.py`: `Profile` (with `scale`, the canvas's short side / 1080, and `orientation`), `get_profile(name,
  custom)`, `make_profile(spec)`, `build_profiles(specs)`, `choose(value, fallback, custom)`, `parse_canvas(text)`,
  `PROFILES`, themes `PAPER` and `NIGHT`.
- `locales.py`: `check(tag)`, `is_cjk`, `is_chinese`, `caption_chars(tag)`, `accept_language(tag)`.
- `timeexpr.py`: `parse(value)`, `resolve(value, ctx) -> seconds`, `to_frame(seconds, fps)`.
- `library.py`: `components(project) -> dict[name, Component]` (presets from `renderer/src/presets/*.meta.json`,
  overlaid by `<workspace>/library/components/*.meta.json`); `Component(name, description, schema, source:
  "preset"|"library", path, ...)`; `validate_props(component, props) -> list[str]` (JSON Schema).
- `document.py`: pydantic models for section 3; `load(project) -> Document`; `save(project, doc)`; `profile_of`,
  `locale_of`;
  `validate(project, doc) -> list[Issue]` (unique ids, references to assets, clips, components and voice lines,
  Time resolution, cycles, overlaps per track and transitions, files present); `load_transcript(project, asset)`.
- `ops.py`: `apply(project, ops) -> (ok, issues, summary)`; `undo(project, steps=1) -> (ok, text)` (section 5).
- `resolve.py`: `resolve(project) -> dict` (section 7); `describe(project, at=None) -> str` (section 8);
  `time_of(project, value) -> seconds`.
- `checks.py`: `check_project(project) -> list[Issue]`; `check_layout(inspect, profile, resolved=None) ->
  list[Issue]`; `check_film(path, profile) -> dict` (section 14).
- `render.py`: `preview(project, times, sweep=False) -> dict`, `render(project) -> dict`, `review(project, n=12)
  -> dict`.
- `providers/`: the asset tools and the footage tools (section 9).
- `tools.py`: every agent-facing tool as a plain function returning text (section 10); the MCP server, the CLI and
  the runner call these.
- `mcp_server.py` (stdio), `cli.py`, `runner.py` and its file guard `guard.py` (section 11).
- `agent/`: the runner's api engine (section 11): `tools.toolbox(project, ws, scope, web)` (function tools),
  `client.ChatClient` (an OpenAI-compatible Chat Completions client), `loop.Agent` (the tool-calling loop) and
  `providers` (who serves the model: endpoint, key, request extras, prices).

## 5. Edit ops

`apply(project, ops)`: all or nothing.
```
{"op": "add_track", "track": {...}, "index": int?}           index: position bottom→top; default top
{"op": "update_track", "id", "set": {...}}                    deep merge; null removes a key
{"op": "remove_track", "id"}
{"op": "add_clip", "track": "v2", "clip": {...}}              clip needs id, type, start, end|dur
{"op": "update_clip", "id", "set": {...}}                     deep merge; null removes a key
{"op": "remove_clip", "id"}
{"op": "move_clip", "id", "start": Time?, "end": Time?, "dur": s?, "track": id?}
{"op": "split_clip", "id", "at": Time, "new_id": str}         second half gets new_id; keyframes split by time
{"op": "set_keyframes", "id", "prop", "frames": [...]}         replaces that prop's keyframes ([] removes)
{"op": "add_asset", "id", "asset": {...}}                       an existing id is replaced
{"op": "update_asset", "id", "set": {...}}                      deep merge; null removes; no kind change while used
{"op": "remove_asset", "id"}                                    refused while a clip uses it (the file stays)
{"op": "set", "path": "meta.title", "value": ...}              dotted path into project.json (not tracks/assets);
                                                                null removes
{"op": "ripple_delete", "start": Time, "end": Time, "tracks": [id]?}   remove a film range and close the gap
{"op": "insert_gap", "at": Time, "dur": s, "tracks": [id]?}            open a gap of dur seconds at a point
{"op": "trim_clip", "id", "in"?, "out"?, "ripple": false}              a clip's in/out points
```

**split_clip** on a video or audio clip moves the second half's `trim_in` on by the time cut off × `rate` (a
looping clip continues where its loop was); the first half keeps `fade_in` and loses `fade_out`, the second keeps
`fade_out` and loses `fade_in`, `enter` and `transition`; `src:<id>@S` Times with S in the second half are pointed
at the new clip.

**Ripple edits** move many Times at once. Every Time of the project (clip starts and ends, markers, the duration,
caption items, the anchored Times inside clips) is measured before the edit, moved to where the edit puts it and
written as a number; then each Time that was an anchor (`"line:4"`, `"clip:a.end"`, `"mark:x"`, `"src:c@3"`) is put
back wherever it still lands on the same frame. Anchors survive where they stay true (a clip timed from a clip that
moved with it); the others become numbers (a clip after the cut timed from a voice line, since the voice is not
cut). A Time inside a clip keeps its place in the clip. A clip split by an edit continues under a new id
(`<id>_2`, `<id>_3`, ...).

- `ripple_delete`: the range `start`-`end` (frames) goes from the given tracks (default: every visual and audio
  track and every captions track with `items`). Clips inside it are removed, clips crossing an edge are split
  there (video and audio move their `trim_in` by the time cut × rate), and everything after it on those tracks
  moves earlier by its length. Caption items are clipped to what is left. Clips on tracks it does not touch stay
  where they are (an anchor that would drag them becomes a number). Markers and a set `duration` move with the
  cut. The narration is never cut: a note says so when the range falls inside it. To cut several source ranges of
  one clip (`silences`), cut from the last back: an earlier `src:<clip>@S` still names the first piece.
- `insert_gap`: everything at or after `at` on the given tracks moves later by `dur` (a clip that starts at `at`
  moves, one that ends there stays; a clip across it is split); markers at or after it and a set `duration` move.
- `trim_clip`: for a video or audio clip, `in` and `out` are seconds of its source (its new `trim_in` and the
  source second where it ends); for any other clip, Times of its new start and end. Without `ripple` the picture
  stays where it is on the timeline and only the clip's edges move (extending past a neighbour is refused as an
  overlap); with `ripple` the clip keeps its start, and the clips after it on its track move by the change in its
  length. Other clips anchored on it follow their anchors. An out point past the end of a non-looping source, or
  an in point that would start the clip before 0 s without ripple, is refused.

A batch is refused, and project.json left untouched, when an op fails or when the result has validation errors the
project did not have before: errors that were already there do not block edits that leave them alone. Before each
write the previous project.json is kept as `.history/NNNN.json` (the last 500); `undo` puts one back and keeps the
version it replaces as `.history/redo.json`. The project may also be edited as a file directly; every tool reads it
fresh and validates it.

## 6. Components (presets and the agent's library)

A component is a React function in a `.tsx` file plus a `.meta.json` next to it:
```json
{"name": "Receipt", "description": "one line for agents", "props": { JSON Schema of props }, "example": {...}}
```
```tsx
import { useCurrentFrame } from "remotion";
import { useClip, ease, fit, FONTS } from "@reelsmith/kit";
export default function Receipt({ props }: { props: any }) {
  const { w, h, dur, fps, theme } = useClip();   // the clip box size, its length in frames, the theme
  const f = useCurrentFrame();                    // frames from the clip's start
  ...
}
```

- It renders inside an absolutely positioned div of the clip box's size and lays itself out in `w × h`.
- Imports allowed: `react`, `remotion`, installed `@remotion/*`, `@reelsmith/kit`, relative files in the same
  folder. Anything else (node builtins, other packages, absolute paths) is refused at bundle time.
- Built-in presets: `renderer/src/presets/<Name>.tsx` + `.meta.json`: `Arrow`, `BarCompare`, `CountUp`, `DotGrid`,
  `EvidenceCard`, `Highlighter`, `Receipt`, `Stamp`, `TimelineRule`. Library: `<workspace>/library/components/`.
  The renderer discovers both; a library component shadows a preset of the same name.
- `@reelsmith/kit` is documented in full in [kit.md](kit.md).
- `typecheck` type-checks the library with the renderer's TypeScript; a component that throws fails `render` and
  shows as a red box in `preview`, reported with its source line.

## 7. resolved.json (the renderer's input)

`resolve(project)` writes `build/resolved.json`; `render` and `preview` keep their own copies
(`resolved.film.json`, `resolved.inspect.json`, `resolved.preview.json`).
```
{
  "version": 2, "fps": 30, "width": 1920, "height": 1080, "durationInFrames": N,
  "safe": {x,y,w,h}, "theme": {paper, ink, night, snow, accent, gold, good, bad, muted, name},
  "fonts": [{"family", "src" (project-relative, build/fonts/...), "weight"?, "style"?}],
  "tracks": [
    {"id", "kind": "visual", "hidden", "clips": [RClip...]},
    {"id", "kind": "captions", "box": {..}, "style": {...}, "items": [{"from", "to", "runs": [{"text", "accent": bool}]}]},
    {"id", "kind": "audio", "hidden"}
  ],
  "audio": [{"id", "src", "from", "dur", "trimIn" (frames), "volume", "fadeIn", "fadeOut" (frames), "loop"}],
  "inspect": false
}
RClip = {"id", "type", "track", "from", "dur" (frames), "box": {x,y,w,h},
         "style": {opacity, rotate, scale, origin, radius, blend, filter, shadow},
         "keyframes": {prop: [{"f": frames from clip start, "v", "ease"}]},
         "enter": {"preset", "dur" (frames)} | null, "exit": {...} | null,
         "transition": {"type", "dur" (frames), "from": id of the clip it comes from | null} | null,
         "transitionOut": {"type", "dur" (frames), "at": frames into this clip, "to": id} | null,
         "content": {...}}
content by type:
  image     {"src", "size": [w,h], "fit", "focus"}
  video     {"src", "duration": s, "trimIn": frames, "rate", "loop", "fit", "focus", "volume",
             "volumeKeys"?: [Keyframe], "fadeIn"?, "fadeOut"? (frames: crossfades)}
  text      {"runs": [{"text", "accent"}], "style": TextStyle (defaults filled), "reveal": {...} | null}
  shape     {"shape", "fill", "stroke", "stroke_width", "d", "draw"}
  evidence  {"src", "size", "box", "site", "highlight": {"at" frames, "dur" frames, "color"} | null}
  component {"name", "props" (Times → frames, asset ids → refs)}
```
The narration is the first `audio` entry (`"id": "voice"`). Motion shorthand is already turned into
`zoom`/`pan_x`/`pan_y` keyframes, captions are already phrase-split and timed, and a captions track without a box
gets the profile's captions band. `fonts` lists the workspace's fonts: the renderer serves only the project folder,
so resolve links (or copies) each file into `build/fonts/` and the renderer loads them before the first frame.
`renderer/src/types.ts` is the TypeScript side of this format.

Footage additions: an audio entry may carry `"volumeKeys": [{"f", "v", "ease"}]` (frames from its start; replaces
`volume`) and `"duck": [{"start", "end" (frames from its start), "level", "fade" (frames)}]` (merged ranges; the
gain is `level` inside, eased linearly over `fade` frames before and after; overlapping ramps take the lowest).
Volume keyframes leave `keyframes` (they are sound, not picture) for `content.volumeKeys` / `volumeKeys`. A
transition's sound arrives as fades: the incoming item's `fadeIn` and the outgoing item's `fadeOut` are raised to
the transition and the overlap. Clips paint in time order on a track (`from`), so the incoming clip of a
transition is on top whatever the order in `clips`.

## 8. describe

`describe(project, at=None)` returns text an agent reads like the editor's window: canvas (profile, size, fps,
orientation), safe area (and whether the platform's UI or a title-safe margin lies outside it), locale, theme,
duration, markers (`name seconds (as written)`), voice lines (`[n] t0-t1 text`), tracks bottom to top with their
clips (`id type start-end (as written) box summary`; the summary names transitions, trims, volume keyframes and
ducking) and every caption phrase (a transcript track says which clips it follows), assets (with their transcript's
word count, or `transcript MISSING`), and the current validation issues. With `at`, only what is on screen then,
bottom to top (an audio clip with volume keyframes shows its volume then).

## 9. Providers (asset tools)

Each asset tool writes into the project's `assets/` or `voice/`, registers what it made in project.json through the
edit ops (validated, undoable) and returns text. None raises and none echoes a key: key values and anything shaped
like a key are scrubbed from every message.

| tool | provider | needs |
|---|---|---|
| `speak` | OpenRouter text-to-speech | `OPENROUTER_API_KEY`; ffmpeg |
| `capture` | Playwright driving a Chromium browser | the `capture` extra; Microsoft Edge, Google Chrome or Playwright's Chromium |
| `draw` | Codex CLI image generation | the Codex CLI installed and signed in |
| `animate` | OpenRouter image-to-video | `OPENROUTER_API_KEY`; ffmpeg |
| `import_asset` | local copy or http(s) download | ffmpeg (ffprobe) for video and audio |
| `probe`, `frames`, `scenes`, `silences` | ffprobe and ffmpeg (they only read; section 9.7) | ffmpeg |
| `transcribe` | an OpenAI-compatible `/audio/transcriptions` endpoint, or faster-whisper (section 9.8) | the endpoint's key, or the `transcribe` extra; ffmpeg |

### 9.1 speak

`speak(project, lines: [str | {text, pace?, emotion?}], gap_s=0.22)` → `voice/voice.wav` and `voice/voice.json`
(`{file, duration_s, lufs, true_peak_db, gap_s, lines: [{i, text, t0, t1}]}`); sets the project's `voice` when it is
unset. One TTS call per line, at most 200 lines of 400 characters. Each line is cached by everything that shapes
its audio (provider, model, voice, style, pace, emotion, text), so only changed lines are paid for again; each line
is trimmed of the TTS's padding and brought to the same loudness before the lines are joined with `gap_s` of
silence (at most 1.5 s). `pace` is `"slower"`, `"normal"`, `"faster"` or a factor 0.5-2; `emotion` (at most 20
characters) is passed to the voice as an instruction.

`providers.tts`: `provider` `"openrouter"`, `model` (default `qwen/qwen-audio-3.0-tts-plus`), `voice` (default:
`longanlufeng`, the default model's Mandarin voice, for a Chinese locale only; any other locale must name a voice of
its model that speaks it, and `speak` says so instead of reading the script in a Chinese voice), `instructions` (a
standing style instruction), `speed_scale` 1.0, `usd_per_1k_chars` 0.02 (the estimate when the provider reports no
cost), `line_lufs` -12. The words `speak` adds for pace and emotion are Chinese for a Chinese locale and English
otherwise (a non-Chinese locale is part of the line cache key, so they do not mix).

Any narration works: a `voice.json` with `lines` (`t0`, `t1` in seconds) next to its audio file is all the
project needs.

### 9.2 capture

`capture(project, url, id, match?, viewport?)` → `assets/<id>.png`, an evidence asset with `box` (the sentence
holding `match`, in the PNG's pixels), `site` and `url`. The browser is the installed Microsoft Edge, else the
installed Google Chrome, else the Chromium that `python -m playwright install chromium` downloads. `viewport`
`phone` loads the page at 430 CSS px wide and 3× device scale with a phone's user agent (the PNG is 1290 px wide);
`desktop` at 1440 CSS px and 2× with a desktop one (2880 px); the default follows the canvas: phone for vertical
and portrait canvases, desktop for landscape and square ones. The browser speaks the project's locale
(`navigator.language`, `Accept-Language`; a Chinese locale also takes the Asia/Shanghai time zone). Fixed and
sticky overlays are hidden, a text column wider than the viewport is reflowed, and the match grows to its sentence
(at most 4 lines). The reply says how wide the box must be shown for its text to stand 40 px tall on a canvas with
a 1080 px short side (scaled to the project's canvas). An empty `match` boxes the title. All browser traffic goes
through a local guard proxy, so the page, its redirects, frames and scripts cannot reach local or private
addresses. `providers.capture.proxy` (or `REELSMITH_PROXY`, `HTTPS_PROXY`, `HTTP_PROXY`) chains an upstream proxy.

### 9.3 draw

`draw(project, id, prompt, style_ref_asset?, size?)` → `assets/<id>.png`, an image asset. `size` is an aspect
(`9:16` at 1080×1920, `2:3`, `3:4`, `4:5` at 1080×1350, `1:1` at 1080×1080, `4:3`, `3:2`, `16:9` at 1920×1080;
the default is the one nearest the project's canvas) or `"WxH"` with sides 256-4096;
`style_ref_asset` is an image or evidence asset to match in style. The `codex` provider runs `codex exec` with
image generation only: no user config, no shell, a read-only sandbox without network, no web search, in a
throwaway folder; Codex's own words go to `<cache>/draw.log`, never to the agent. It uses the model from
`$CODEX_HOME/config.toml` when one is set there. The binary is `CODEX_EXE`, else the CLI bundled with the Codex
desktop app on Windows, else `codex` on PATH. A logged-out or out-of-quota answer pauses drawing for 10 minutes.

`providers.image`: `provider` `"codex"`, `max_draws` 30 (tries per project, counted in the ledger), `timeout_s`
360, `effort` `"low"` (`minimal`, `low`, `medium`, `high`).

### 9.4 animate

`animate(project, id, image_asset, motion, seconds=4, camera?)` → `assets/<id>.mp4`, a silent video asset of 2-12 s
whose first frame is the picture and in which `motion` happens; `camera` is `push` (default), `pull`, `pan_left`,
`pan_right`, `rise` or `still`. The estimate is reserved in the ledger before anything is sent, and the accepted
job is recorded the moment it exists: a later call with the same picture and motion polls that job instead of
paying again, and a finished clip whose download failed is collected again from its job.

`providers.video`: `provider` `"openrouter"`, `model` (default `bytedance/seedance-1-5-pro`), `resolution`
`480p`, `720p` (default) or `1080p`, `usd_per_s` (overrides the built-in per-second estimate), `timeout_s` 360.

### 9.5 import_asset and assets

`import_asset(project, id, source, kind?)` copies a local file, or downloads an http(s) image, video or audio file,
into `assets/` and registers it (a relative path is read from the project folder). The bytes are sniffed (and video and audio probed) whatever the name or the server
says; a download goes only to public hosts, every redirect included; the size is capped by
`providers.import.max_mb` (200). `kind` `evidence` takes a page screenshot you already have (PNG, JPEG or WebP); its
box is the whole picture until `update_asset` sets one. With `REELSMITH_ROOT` set, local files must live inside it.

`assets(project)` lists the project's assets with kinds, sizes, durations and spend.

### 9.6 Costs: the ledger, the budget and the balance floor

`speak`, `animate` and `transcribe` (with an endpoint) spend money; `draw` spends tries. Every paid call goes
through `ledger.jsonl` (in the workspace, or in the project folder outside one):

1. Estimate the cost.
2. Under the ledger lock, refuse if the project's spend plus this estimate would exceed `budget.per_project_usd`, or
   if the provider's account balance minus calls still in flight minus this estimate would drop under
   `budget.min_balance_usd` (an unreadable balance refuses too); otherwise write a `reserved` row.
3. Call the provider; record `submitted` for an accepted asynchronous job.
4. Settle with the real cost when the provider reports one, else the estimate.

A call without a final row counts at its estimate, so a call killed half-way still counts against the project and
parallel calls see each other's reservations. `REELSMITH_BUDGET_USD` and `REELSMITH_MIN_BALANCE_USD` override the
two budget values for one process.

### 9.7 Footage tools: probe, frames, scenes, silences

They look at a source (an asset id, or a file inside the project folder; anything else is refused) and change
nothing in project.json. Times are **source seconds**; `"src:<clip>@<seconds>"` (section 3.1) puts one on the
timeline. Text comes first, then the same facts as one `JSON: {...}` line.

- `probe(project, source)`: container, duration, size and bit rate; the first picture stream's codec, width,
  height, rotation (the display matrix, with the size it shows at), fps, pixel format and frame count (`still` for
  a picture); the first sound stream's codec, channels, layout and sample rate, with its integrated loudness
  (LUFS), loudness range and true peak (ffmpeg `ebur128`).
- `frames(project, asset, times?, every?, n?)`: stills of a video at source times: `times` (seconds or `m:ss`, at
  most 24), else one every `every` seconds from 0 (at most 24), else `n` evenly spaced (default 12; at the middle
  of each n-th). A time at the very end shows the last frame. Stills are scaled to at most 960 px on their long
  edge and written to `build/footage/<name>/frames/` (replaced on each call) with `contact.png`, a sheet of all of
  them with each source time burned in.
- `scenes(project, asset, threshold=0.3)`: shot cuts where ffmpeg's scene score (on a 240 px wide copy) passes
  `threshold` (0.01-0.99); cuts closer than 0.1 s together or to an end are one shot. Lists every shot (`#n
  start-end (length)`) and writes the first frame of each (the first 48) and their sheet to
  `build/footage/<name>/scenes/`.
- `silences(project, asset, min_s=0.5, noise_db=-35)`: ranges quieter than `noise_db` dB for at least `min_s`
  seconds (ffmpeg `silencedetect`; a silence running to the end ends there) and the sound ranges between them: the
  cut list for jump cuts.

### 9.8 transcribe

`transcribe(project, asset, language?, prompt?)` → `assets/<id>.transcript.json` (section 3) and the asset's
`transcript` set through the edit ops. The asset must be video or audio with sound. ffmpeg takes its sound out as
16 kHz mono (MP3 at 32 kbit/s for an endpoint, WAV for the local model). `language` is an ISO code (empty: the
provider detects it, or `providers.transcribe.language`); `prompt` (at most 800 characters) lists names and words
to spell right. The result lists what is said by segment with source times.

`providers.transcribe`:

| key | default | meaning |
|---|---|---|
| `provider` | `openai` | `openai`: any OpenAI-compatible endpoint; `local`: faster-whisper in-process (the `transcribe` extra) |
| `base_url` | `https://api.openai.com/v1` | POST `{base_url}/audio/transcriptions` (OpenAI, Groq, a local whisper server) |
| `model` | `whisper-1` | the endpoint's model |
| `key_env` | `OPENAI_API_KEY` | the name of its key in `.env` or the environment; `null` sends none |
| `usd_per_min` | 0.006 | the estimate per minute of sound (endpoints report no cost) |
| `max_mb` | 24 | the largest upload; longer sound goes in pieces |
| `timeout_s` | 600 | per request |
| `language` | null | the default language |
| `local_model`, `device`, `compute_type` | `small`, `auto`, `default` | faster-whisper's model name or path and how it runs |

The endpoint is asked for `response_format=verbose_json` with `timestamp_granularities[]=word` and `segment`;
words come from the answer's `words`, or from each segment's `words` (servers differ). Sound over `max_mb` is cut
into pieces at the middle of a silence in the last half of each piece's allowed length (else at that length), each
piece is sent alone and its times are moved back by the piece's start. A request is retried on 408, 409, 425, 429,
5xx and dropped connections, never on another 4xx; errors are scrubbed of the key. The `openai` provider is paid:
the estimate (minutes × `usd_per_min`) is reserved in the ledger against the project budget (section 9.6; there is
no balance to read) and settled at the estimate of what was sent. The local provider is free and not booked.

## 10. Agent-facing tools (tools.py → MCP, CLI, runner)

| tool | does | CLI |
|---|---|---|
| `manual()` | the agent manual ([manual.md](manual.md)) | `manual` |
| `notes(project)` / `note(project, text)` | read / append to the workspace's `library/NOTES.md` | `notes`, `note` |
| `new_project(project, profile?, title?, canvas?, locale?)` | create a project folder; `profile` a name, `canvas` `"WxH"` or `"WxH@fps"` for an inline profile based on `profile` (or the workspace's), `locale` a BCP-47 tag | `new --profile --canvas --locale` |
| `describe(project, at?)` | the editor's window as text (section 8) | `describe --at` |
| `edit(project, ops)` | apply a batch of ops (section 5) | `edit` (JSON, `@file` or `-`) |
| `undo(project, steps=1)` | undo applied batches | `undo --steps` |
| `check(project)` | validation, hard rules, advice (section 14) | `check` |
| `library(project, name?)` | components with their props; one in full with its schema, example and source path | `library` |
| `typecheck(project)` | type-check the library's components | `typecheck` |
| `preview(project, times?, sweep?)` | stills (up to 24 per call), a contact sheet and layout problems; `sweep` measures a still every second as `render` does | `preview [times...] --sweep` |
| `render(project)` | the film, mastered and checked (section 14) | `render` |
| `review(project, n=12)` | 2-24 evenly spaced frames of the delivered film and a contact sheet | `review -n` |
| `speak`, `capture`, `draw`, `animate`, `import_asset`, `assets` | asset tools (section 9) | `speak`, `capture` (`--viewport`), `draw`, `animate`, `import`, `assets` |
| `probe(project, source)` | streams, codecs, rotation, loudness of a source (section 9.7) | `probe <source>` |
| `frames(project, asset, times?, every?, n?)` | stills of a source at source seconds and a timed contact sheet | `frames <asset> [times...] --every -n` |
| `scenes(project, asset, threshold?)` | shot cuts in source seconds and each shot's first frame | `scenes <asset> --threshold` |
| `silences(project, asset, min_s?, noise_db?)` | silent ranges and the sound between them, in source seconds | `silences <asset> --min-s --noise-db` |
| `transcribe(project, asset, language?, prompt?)` | word-level transcript of a video or audio asset (section 9.8) | `transcribe <asset> --language --prompt` |

Each takes `project` (the path of the folder holding project.json, or of project.json itself) first where it
applies and returns text; structured results are JSON inside the text. A result is flagged as an error (MCP
`is_error`, CLI exit status 1) when the call failed or found blocking problems. No tool raises to the client.
DeepSeek Harness gets them, with contact sheets as images, a Video editor mode and a panel: integrations/dsh.

### 10.1 Transports

```
reelsmith mcp [--http [--host 127.0.0.1] [--port 8765] [--allow-remote] [--token-env REELSMITH_MCP_TOKEN]]
```

`reelsmith-mcp` and `python -m reelsmith.mcp_server` take the same flags. Without `--http` the server speaks stdio.
`--http` serves streamable HTTP at `http://HOST:PORT/mcp` (the `mcp` package's app under uvicorn). The host must be a
loopback address (`127.0.0.0/8`, `::1`, `localhost`), where the SDK's DNS-rebinding protection checks the Host and
Origin headers; any other host needs `--allow-remote` and a bearer token of at least 16 characters in the token
variable, or the command exits with status 2 before binding. While the token variable is set, every request needs
`Authorization: Bearer <token>` and is answered 401 without it, loopback included.

With `REELSMITH_GUARD_PROJECT` set to a project folder, the server checks every call with the runner guard's MCP
rules (section 11) before it runs: one project, paths the session may read, public http(s) URLs. A refused call
returns an error result that starts with `Refused by the run's guard`. The codex and dsh engines set it.

### 10.2 Setup: attaching a coding agent

```
reelsmith setup claude-code|codex|dsh|cursor|generic [--user] [--print] [--uninstall] [--root DIR]
```

Adds the server to the agent's own config and copies the skill (`skills/reelsmith/SKILL.md`, the Agent Skills
format) to `<skills dir>/reelsmith/SKILL.md`. Project-level config in the current folder by default; `--user` takes
the agent's user-level config. `--print` shows every file and command it would write or run, and writes nothing.
`--uninstall` removes what setup adds, and the folders it leaves empty. `--root` sets `REELSMITH_ROOT`.

| target | server (folder) | server (`--user`) | skills dir (folder / `--user`) |
|---|---|---|---|
| `claude-code` | `.mcp.json` | `claude mcp add-json --scope user reelsmith <json>` | `.claude/skills` / `~/.claude/skills` |
| `codex` | `.codex/config.toml` | `$CODEX_HOME/config.toml` | `.agents/skills` / `~/.agents/skills` |
| `dsh` | `.dsh/reelsmith.cordis.yml` (a `--patch` overlay) | `$DSH_HOME/cordis.patch.yml` | `<git root>/.dsh/skills` / `$DSH_HOME/skills` |
| `cursor` | `.cursor/mcp.json` | `~/.cursor/mcp.json` | `.cursor/skills` / `~/.cursor/skills` |
| `generic` | printed | printed | printed (writes nothing) |

- **The server**: `{"command": <the absolute path of the Python running setup>, "args": ["-m",
  "reelsmith.mcp_server"], "env": {"PYTHONSAFEPATH": "1", "REELSMITH_ROOT": <--root>}}`. JSON targets add
  `"type": "stdio"` under `mcpServers.reelsmith`. Codex's `[mcp_servers.reelsmith]` adds `env_vars` (the variables
  the tools read: `OPENROUTER_API_KEY`, the proxies, `CODEX_EXE`, `CODEX_HOME`, the budget overrides,
  `REELSMITH_RENDERER`), `startup_timeout_sec = 60` and `tool_timeout_sec = 3600`. DSH gets one patch row,
  `- insert: [{id: mcp-reelsmith, name: '@deepseek-ai/dsh-mcp-client', config: {serverName: reelsmith, transport:
  stdio, command, args, env, toolCallTimeoutMs: 3600000}}]`.
- **Merging.** JSON: `mcpServers.reelsmith` is set and every other key kept; uninstalling from a file that held
  nothing else removes it. TOML: the `[mcp_servers.reelsmith]` table and its sub-tables are replaced in the text, so
  comments and other tables stay; a definition as dotted keys or an inline table is refused; the result is read back
  before it is written. DSH's home patch: a block between `# >>> reelsmith` and `# <<< reelsmith` is appended to the
  row list. A file that does not parse is refused (exit status 2) and nothing is written; a second run changes
  nothing.
- `claude-code --user` runs `claude mcp remove --scope user reelsmith`, then `add-json`; a command that fails is
  printed for the user to run (exit status 1). `generic` prints an instructions block for the agent's instructions
  file, the `mcpServers` JSON and the skill's path.
- **The plugin.** `integrations/claude-code/` is a Claude Code plugin (`.claude-plugin/plugin.json`, the server as
  `reelsmith-mcp` from `PATH`, the skill), listed by the marketplace `.claude-plugin/marketplace.json` at the
  repository root (`/plugin marketplace add wangkant/reelsmith`, `/plugin install reelsmith@reelsmith`). Its copy of
  the skill is written by `integrations/sync_skills.py`; a test fails when it drifts.

## 11. Runner (self-hosted)

```
reelsmith run <project> --brief "..." [--engine api|agent-sdk|codex|dsh] [--provider openrouter|deepseek|openai|custom]
              [--backend anthropic|deepseek] [--model M] [--effort E] [--budget-usd N] [--max-minutes N] [--max-turns N]
              [--fresh]
```

Makes one film in one project with an agent and no client attached. Four engines:

- **`api`** (the default): reelsmith's own agent loop (`reelsmith/agent/`) over the OpenAI-compatible Chat
  Completions API with tool calling, so OpenRouter, DeepSeek, OpenAI, Qwen or GLM gateways and local servers can
  drive it. It needs no extra package (the `web` extra adds keyless web search).
- **`agent-sdk`**: a Claude Agent SDK session (the `runner` extra), served by Anthropic or by DeepSeek's
  Anthropic-compatible API.
- **`codex`**: the Codex CLI's `codex exec`, on the owner's Codex sign-in.
- **`dsh`**: DeepSeek Harness's one-shot headless mode (`dsh --profile headless`), on `DEEPSEEK_API_KEY`.

Settings come from the flags, then `workspace.json` `runner`, then the defaults:

| key | default | meaning |
|---|---|---|
| `engine` | `api` | `--backend` implies `agent-sdk` and `--provider` implies `api`; a workspace whose `runner` names a `backend` and no `engine` (one from before the api engine) runs on `agent-sdk` |
| `provider` | `openrouter` | api engine: who serves the model (table below) |
| `backend` | `anthropic` | agent-sdk engine: `anthropic` or `deepseek` |
| `model` | the provider's or the backend's | `runner.model` goes with the workspace's engine and provider (or backend): a flag that switches away from them starts from the new one's default model. codex: the `model` of `$CODEX_HOME/config.toml`, else Codex's own; dsh: `deepseek-flash` |
| `budget_usd` | 5.0 | the run's model spend; asset spend has its own budget (section 9.6) |
| `max_minutes` | 120 | wall clock for the process |
| `max_turns` | none | model calls per session (dsh: model steps; codex: not applied) |
| `fixups` | 2 | sessions after the first that fix delivery problems |
| `proxy` | `REELSMITH_PROXY` | an upstream proxy for the model API (and the api engine's web tools) |
| `reasoning` | null | api engine: `low`, `medium` or `high`; OpenRouter gets `reasoning.effort`, the others `reasoning_effort`; null keeps the model's default |
| `context_tokens` | 200000 | api engine: once a request's prompt passes it, the oldest tool outputs and images are replaced by short stubs (the newest turn stays) |
| `max_image_edge` | 1280 | api engine: images are downscaled to this edge and sent as JPEG |
| `images` | null | api engine: `false` sends no images (a text-only model); null follows the provider's table |
| `web` | `{}` | api engine: `fetch` (`false` leaves web_fetch out), `search` (`auto`, `ddgs`, `tavily` or `none`; `auto` takes ddgs when installed, else Tavily with `TAVILY_API_KEY`), `region`, `proxy`, `timeout_s`, `locale` (web_fetch's `Accept-Language`: the tag, its language, then English; default the project's locale) |
| `prices` | none | api, codex and dsh engines: `{"model": [input, output, cached_input]}` in $ per million tokens, for calls whose provider reports no cost |
| `extra_body` | none | api engine: fields merged into every request (an OpenRouter `provider` routing preference, a sampling setting) |
| `base_url`, `key_env` | | the `custom` provider's endpoint and the name of its key |
| `effort` | `medium` | agent-sdk: the Claude Code effort; codex: `model_reasoning_effort` (`minimal`, `low`, `medium`, `high`, `xhigh`); dsh: `off`, `low`, `high` or `max`, default DSH's own (`high`). `--effort` overrides it; the api engine takes `reasoning` |
| `stall_minutes` | 60 | agent-sdk, codex and dsh engines: no message for that long aborts the session; codex and dsh also take it as the reelsmith tool timeout |

**Providers of the api engine.** The key comes from the workspace `.env`, else the environment, and goes to its
provider only.

| provider | endpoint | key | default model | spend |
|---|---|---|---|---|
| `openrouter` | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` | `deepseek/deepseek-v4.1-flash` | the cost each response reports |
| `deepseek` | `https://api.deepseek.com` | `DEEPSEEK_API_KEY` | `deepseek-flash` | estimated at DeepSeek's peak prices (below) |
| `openai` | `https://api.openai.com/v1` | `OPENAI_API_KEY` | none: pass one | `prices` |
| `custom` | `runner.base_url` | `runner.key_env`; none sends no key | none: `runner.model` | `prices` |

OpenRouter requests carry `usage: {include: true}`, so each response reports its cost in dollars, and
`provider: {require_parameters: true}`, so they are routed only to hosts that take tools. Known to take images:
`deepseek/deepseek-v4.1-flash` and `deepseek-flash`; text-only: `deepseek/deepseek-v4-pro` and `deepseek-v4-pro`. A
call that reports no cost is priced from the table (`prices`, and DeepSeek's own); a model with neither is not
counted against the budget, and the runner says so.

**The api session.** The system prompt is the role below plus two lines: a reply without a tool call ends the
session, and today's date. Tools: every reelsmith tool (the functions the MCP server serves, with its schemas),
`read_file`, `write_file`, `edit_file`, `glob`, `grep`, `list_dir`, `web_fetch` and `web_search`; no shell. The
loop calls the model, runs every tool call, and feeds the results back; a tool's images (preview stills, contact
sheets, review frames) follow the tool results as one user message of image parts, because most providers take
no image in a tool message. A text-only model's tools return a note instead. Assistant messages go back as the
provider sent them, reasoning fields included. A session stops when the model answers without a tool call, or at
`max_turns`, the budget left or the time limit; a request is retried on 408, 409, 425, 429, 5xx and dropped
connections.

**The agent-sdk session.** Claude Code's system prompt with the role appended. The host's own Claude Code settings,
memory and instructions are not loaded. Tools: the reelsmith MCP server (`python -m reelsmith.mcp_server`, with
`REELSMITH_ROOT` set to the workspace), Read, Write, Edit, Glob, Grep, WebSearch, WebFetch and TodoWrite. No shell.

| backend | key (workspace `.env`, else the environment) | models |
|---|---|---|
| `anthropic` | `ANTHROPIC_API_KEY` (and optionally `ANTHROPIC_WORKSPACE_ID`) | default `claude-opus-5-5` |
| `deepseek` | `DEEPSEEK_API_KEY` | default `deepseek-flash`; `deepseek-v4-pro` |

Each backend's key goes to that backend only: on `anthropic` an inherited `ANTHROPIC_BASE_URL` or
`ANTHROPIC_AUTH_TOKEN` is blanked, so a shell set up for another endpoint does not receive the Anthropic key.

- **DeepSeek on the agent-sdk engine.** The CLI talks to DeepSeek's Anthropic-compatible API
  (`https://api.deepseek.com/anthropic`): its env carries the DeepSeek key as `ANTHROPIC_AUTH_TOKEN` and
  `ANTHROPIC_API_KEY`, the model as every Claude Code model variable (with the `[1m]` context suffix;
  `deepseek-flash` for the small model and subagents) and an auto-compact window of 786432 tokens. The Anthropic
  key, the workspace header and any OAuth token are blanked. `deepseek-v4-pro` takes no images: reading a preview
  still fails on it (the runner logs a warning). The CLI prices sessions with its Claude table, so the runner
  estimates the spend itself from the streamed usage, stops a session once that estimate reaches the budget left,
  and passes the CLI a cap 1000 times the budget as a backstop only. A finished session costs the larger of the
  streamed estimate and the estimate from the CLI's per-model totals; the CLI's own figure is kept as
  `cli_cost_usd`.
- **DeepSeek's peak prices** (both engines; off-peak hours cost half), per million tokens: `deepseek-flash` $0.30
  input, $0.006 cached input, $1.20 output; `deepseek-v4-pro` $1.32, $0.044, $3.96; cache writes at the input price;
  web search $0.75 per 1000. An unlisted DeepSeek model is priced as the dearest.

**The codex session.** `codex exec --json --skip-git-repo-check --ignore-user-config --ignore-rules -C <project>
-c ... [-m model] -` with the prompt on stdin; a fix-up or resume runs `codex exec resume ... <thread id> -`. The
binary is `CODEX_EXE`, else the Windows desktop app's bundled CLI, else `codex` on `PATH`. Codex keeps its own system
prompt and sign-in (`CODEX_HOME`); the role opens the first message. The `-c` overrides set `sandbox_mode =
"workspace-write"` (rooted at the project, with the workspace library in `sandbox_workspace_write.writable_roots`),
`sandbox_workspace_write.network_access = false`, `approval_policy = "never"`, `shell_environment_policy.inherit =
"core"` (commands inherit no keys), `web_search = "live"`, `project_doc_max_bytes = 0` (no AGENTS.md of the host's),
the host's apps, plugins, browsers, subagents and hooks off, and the reelsmith server as `mcp_servers.reelsmith.*`
(as setup writes it, plus `REELSMITH_GUARD_PROJECT`, with `tool_timeout_sec` = `stall_minutes`). Events
(`thread.started`, `item.*`, `turn.completed`, `turn.failed`, `error`) are logged; the thread id is the session id.
Codex reports its tokens (`input_tokens` with `cached_input_tokens` inside, `output_tokens`) when the turn ends: they
are priced with `prices`, so the budget is checked between sessions, and a model without a price is reported as
`cost_known: false` with its tokens.

**The dsh session.** `dsh --patch <project>/build/dsh-patch.yml --profile headless --json --permission-mode
workspace-write --approval-policy never [--add-dir <library>] [--session-id <id>] -` with the prompt on stdin, in the
project folder. The binary is `DSH_EXE`, else `dsh` on `PATH`, else `npx -y @deepseek-ai/dsh`. The process gets
`DEEPSEEK_API_KEY` (workspace `.env`, else the environment), its own `DSH_HOME` (`<workspace>/.cache/dsh`, so the
host's DSH profiles, patches, saved keys and servers stay out) and `DSH_TELEMETRY_MODE=DISABLED`. The overlay mounts
the reelsmith server (setup's row, plus `REELSMITH_GUARD_PROJECT`, `toolCallTimeoutMs` = `stall_minutes`), sets
`agent-default-model` to `deepseek-official` with the model (and `reasoningEffort` when an effort is set) and turns
the `session-log-deepseek` upload off. On Windows the library is not added (DSH's Windows sandbox refuses every shell
call once extra roots are granted), so the session cannot write library components there. Each `status` step end
carries its usage (`inputTokens`, `cacheReadTokens`, `cacheWriteTokens`, `outputTokens`, disjoint), priced with
`prices`, else DeepSeek's table: the session stops at the budget and at `max_turns`. The `final` event's
`reason.kind` is `completed` for a finished turn.

**Common to all engines.**

- **Role.** Read the manual, then the notes; every choice is yours; look at what you make.
- **Guard** (`guard.py`; anything it does not know is refused): a PreToolUse hook on the agent-sdk engine, checked
  in-process before each tool call on the api engine. Writes go to the project and the workspace library only,
  never into `build/`, `out/` or `.history/` (the tools write those), never `workspace.json`, `rules.json`, `.env*`
  or `ledger.jsonl` under any name, never scripts, executables or package files. Reads stay in the workspace, the
  manual and the renderer source. Keys, credentials, tool configs, `.git`, the ledger and `.cache/` are
  unreadable. Web fetches take public http(s) URLs only (the api engine's `web_fetch` checks every connection,
  redirects included, as `capture` does); reelsmith tool arguments that name files or URLs are held to the same
  rules. On the codex and dsh engines the agent's own sandbox fences its shell and file tools instead (writes to the
  project and the library; reads are not fenced, so a workspace `.env` is readable there), and the reelsmith MCP
  server applies the rules for tool arguments itself (`REELSMITH_GUARD_PROJECT`, section 10.1).
- **Delivery.** The run ends when `out/film.mp4` exists, `out/report.json` says it passed, no later render failed,
  `check` has no errors and no input of the film (project.json, voice, assets, library components) changed after
  it. The render records what the film was made of (`inputs` in its report), so an edit to project.json's `meta`
  alone, or to a library component the film does not use, does not call for another render. Otherwise the runner
  continues the same session with the exact problems, up to `fixups` times, within the budget and the time limit.
- **Resume.** State lives in `build/run_state.json`: an interrupted run resumes its own session when started again
  (`--brief` is then optional), on the engine, provider (or backend) and model it started on; anything else is
  refused with the flags to pass, and `--fresh` starts a new one. On the api engine the conversation is saved to
  `build/agent_messages.json` after every turn (without image data: the agent looks again) and the session's spend
  so far to the state's `inflight`, so a killed process loses neither: the next start counts that spend and goes on
  from the saved conversation. The codex and dsh engines resume the agent's own session (the Codex thread, the DSH
  session in the same project folder); dsh keeps its spend so far in `inflight` too.
- **Logs and report.** Every message, tool call and agent event goes to `build/runner.jsonl`, one line per step to
  stdout (the codex and dsh processes' stderr to `build/runner-cli.log`); `out/run_report.json` says how it ended:
  `delivered`, `problems`, `engine`, `provider`, `backend`, `model`, `cost_usd` and whether it is `cost_estimated`,
  `turns`, the sessions (each with its kind, turns, cost and stop), and refused tool calls (agent-sdk). The codex
  and dsh engines add `cost_known` (false when a session's model had no price) and `usage` (their token counters,
  summed), and each session's `tool_calls`.
- Exit status: 0 delivered, 1 not delivered, 2 a setup problem (no project, no brief, no key, an unknown engine,
  provider or backend, a provider without a model, no Codex or DSH executable).

## 12. Inspect (layout measurement)

When resolved.json has `"inspect": true`, the renderer measures each rendered frame and logs one line:
`@@inspect {"frame": F, "items": [{"clip", "track", "kind": "clip"|"text", "rect": [x,y,w,h], "opacity", "text",
"size", "color"}]}`.

- One `clip` item per visible clip container; one `text` item per visible text node (Range rects, merged per node)
  with its effective opacity (the product up the tree), the first 24 characters, the computed font size in px and
  the colour.
- `scripts/render.mjs inspect <resolved.json> <project dir> <out dir> <frame...>` renders those stills and writes
  `<out dir>/inspect.json` = `{"frames": [{"frame", "png", "items"}]}`.
- `check_layout` turns it into issues (section 14): text outside the safe area or cut by the canvas edge, tiny or
  small text, text overflowing its clip box, text over other text, and contrast sampled from the still.

## 13. render.mjs (node, renderer/scripts)

`node scripts/render.mjs film|stills|inspect <resolved.json> <project dir> <out> [frame...]`, one bundle per call:

- `film`: `<out>` is the mp4 to write (h264 crf 18, yuv420p, BT.709); `stills`: a folder of `still_<frame>.png`;
  `inspect`: stills plus `inspect.json`.
- The public dir is the project dir. Webpack aliases `@reelsmith/kit` → `renderer/src/kit` and `@library` → the
  folder in `REELSMITH_LIBRARY` (reelsmith sets it to the workspace's `library/components`; an empty folder when
  unset). The import guard enforces section 6.
- The last stdout line is JSON: `{"ok": true, ...}` or `{"ok": false, "stage", "error", "browserErrors"}`. Stage
  `component` names a crashed or missing component with its source line; stage `infra` with `"transient": true`
  is a socket, browser or compositor failure that a plain retry may pass (reelsmith retries it once).

`scripts/segment.mjs` gives Python the word boundaries (`Intl.Segmenter` in the project's locale; stdin
`{"texts", "locale"}`) used to phrase-split captions; resolve caches them per locale in `build/segments.json`.

## 14. Checks and delivery

`check(project)` reports three levels: **errors** block `render`, **warnings** and **advice** are information.

Pixel thresholds here (40, 28 and 20 px) are written for a canvas whose short side is 1080 px and scale with the
canvas's short side (a 720×1280 canvas warns under 18.7 px, a 3840×2160 one under 56 px); messages give the scaled
value.

- Errors: the project does not load or validate (schema, unknown ids, missing files, overlaps on a track, bad or
  cyclic Times, props that fail a component's schema, an unknown font, a malformed locale or profile); the hard
  rules (section 2.2); a length outside the profile's limits (when it has any). Footage: an unknown clip or marker
  in a `src:` or `mark:` Time, a `src:` on a looping or non-media clip or before its in point, a transition longer
  than its clip or the clip it comes from, an overlap longer than the transition (or with any clip but the previous
  one), an audio transition other than `crossfade`, volume keyframes on a clip without sound or below 0, a `duck`
  under an unknown track, its own track, a captions track or a missing voice, captions from a clip that is unknown,
  not video or audio, looping, or whose asset has no readable transcript; a marker name that is not an id.
- Warnings: an empty title where rules.json has a title rule; frame 0 (the cover) without whole words on it
  (mid-reveal, mid-enter, fading in, or no words at all); evidence whose proving sentence will read under 40 px; a
  component Time that falls outside its clip; motion and keyframes on the same property. Footage: a `src:` second
  past its clip's end, an asset whose transcript is missing, both `enter` and `transition` on a clip, `overrides` on
  captions from a transcript.
- Advice (only what rules.json `advice` sets): nothing on screen at 0 s or no words within `hook_seconds`; a still
  image or evidence held longer than `max_same_visual_s` without anything moving it; the length outside `target_s`.

`render(project)` stops at the first stage that fails and keeps the previous `out/film.mp4`:

1. **check**: any check error.
2. **layout**: a still every second, measured (section 12): visible text outside the safe area or cut by the canvas
   edge, text under 20 px, a component that crashes. Text during its enter/exit animation or a transition between
   clips, and text fainter than 10 % opacity, are not counted. Warnings: text under 28 px, text overflowing its clip
   box, text of one clip over text of another (captions included), and contrast under 3:1 against the background
   sampled from the still (between 2:1 and 3:1 a clearly different hue passes).
3. **film**: the renderer encodes the film.
4. **master**: loudness is normalised to the profile's target (true peak −1 dBTP). A profile with `require_audio`
   refuses a film without sound; any other delivers a silent film as it is (no audio, or audio that is all silence,
   is not mastered).
5. **film check**: the profile's frame size and fps, h264/aac, length within the profile's limits, size under the
   profile's cap, sound present and not near silent (`require_audio`), at most `max_black_ratio` black (10 %), and
   no stretch longer than `max_still_s` (5 s on the social profiles) without any motion; a limit that is null is
   not checked. A rejected film is kept as `build/film.rejected.mp4` to look at.

Every attempt writes `build/report.json`; a delivered film also `out/report.json` and `out/meta.json`. A renderer
failure that is not the project's (its local server or browser) is retried once and reported as transient.

## 15. Profiles and themes

| profile | canvas | safe area x, y, w, h | captions band | length | target | max size | loudness | sound | stills |
|---|---|---|---|---|---|---|---|---|---|
| `landscape` (default) | 1920×1080, 30 fps | 96, 54, 1728, 972 | 96, 826, 1728, 200 | any | none | none | −14 LUFS | optional | any |
| `vertical` | 1080×1920, 30 fps | 54, 96, 972, 1728 | 54, 1624, 972, 200 | any | none | none | −14 LUFS | optional | any |
| `square` | 1080×1080, 30 fps | 54, 54, 972, 972 | 54, 826, 972, 200 | any | none | none | −14 LUFS | optional | any |
| `portrait` | 1080×1350, 30 fps | 54, 68, 972, 1214 | 54, 1082, 972, 200 | any | none | none | −14 LUFS | optional | any |
| `youtube` | as `landscape` | as `landscape` | as `landscape` | any | none | none | −14 LUFS | required | any |
| `douyin` | 1080×1920, 30 fps | 40, 220, 840, 1240 | 40, 1260, 840, 200 | 20-90 s | 45-75 s | 80 MB | −10 LUFS | required | ≤ 5 s |
| `douyin-long` | as `douyin` | as `douyin` | as `douyin` | 60-300 s | 90-180 s | 250 MB | −10 LUFS | required | ≤ 5 s |
| `tiktok` | 1080×1920, 30 fps | 60, 200, 820, 1260 | 60, 1260, 820, 200 | 15-180 s | 30-75 s | 250 MB | −14 LUFS | required | ≤ 5 s |
| `shorts` | 1080×1920, 30 fps | 60, 180, 820, 1300 | 60, 1280, 820, 200 | 15-180 s | 30-60 s | 250 MB | −14 LUFS | required | ≤ 5 s |
| `reels` | 1080×1920, 30 fps | 66, 250, 884, 1000 | 66, 1050, 884, 200 | 3-180 s | 15-60 s | 4000 MB | −14 LUFS | required | ≤ 5 s |

On the generic canvases (`landscape`, `vertical`, `square`, `portrait`) and `youtube` the safe area is a title-safe
margin, 5 % of the width and of the height in from each edge; on the platform profiles it is where the platform's
own UI (status bar, tabs, the button rail, title and music) does not cover the picture: on Instagram Reels Meta keeps
the top 14 % and the bottom 35 % free, and the action rail takes more than its 6 % at the right. Words must stay
inside the safe area; backgrounds may bleed to the edges. The captions band is the safe area's bottom 200 px at a
1080 px short side (scaled with the canvas). YouTube normalises playback to about −14 LUFS and its own upload caps
(12 h, 256 GB) are beyond anything rendered here, so `youtube` sets no length or size limit. Every profile renders
h264/aac with true peak −1 dBTP and at most 10 % black. Advice `"target_s": true` (section 2.2) checks the length
against the profile's `target`.

| token | `paper` (default) | `night` | for |
|---|---|---|---|
| `paper` | #F3EBDD | #E9EEF3 | light ground |
| `ink` | #1E1A16 | #10151C | text on a light ground |
| `night` | #16130F | #0E1319 | dark ground |
| `snow` | #F7F1E6 | #F2F5F8 | text on a dark ground or a picture (the default text colour) |
| `accent` | #C8372D | #FF5A3C | the one number that matters |
| `gold` | #D9A441 | #FFC24B | highlights |
| `good` / `bad` | #2E8B57 / #C8372D | #3BC48A / #FF5A3C | gains / losses |
| `muted` | #7A6F62 | #8A96A3 | secondary text |

The theme is `paper` (or the one `name`d), then workspace.json `theme`, then project.json `theme`.

### 15.1 Custom profiles

workspace.json `profiles` names custom profiles, and a project's (or the workspace's) `profile` may be one inline:
`{"base": "douyin", "width": 720, "height": 1280, "fps": 25}`. `base` names the profile to start from (built-in,
or another custom one of the workspace; default `landscape`) and every other field overrides it:

| field | value |
|---|---|
| `width`, `height` | even whole numbers 64-4096 (h264 needs even sides) |
| `fps` | a whole number 1-120 (24, 25, 30, 50 and 60 are the usual ones) |
| `safe`, `captions` | `{"x", "y", "w", "h"}` or `[x, y, w, h]` in canvas pixels, inside the canvas |
| `min_s`, `max_s`, `max_mb`, `max_still_s` | numbers > 0, or null for no limit (no check) |
| `target_s` | `[min, max]` seconds, or null |
| `lufs`, `peak_db` | the mastering target (−70 to −1) and true peak (−12 to 0) |
| `max_black_ratio` | 0-1 |
| `require_audio` | false: a silent film is delivered |
| `ui` | true: outside the safe area is the platform's UI (only the wording of the layout message changes) |

A new canvas size without `safe` scales the base's safe area to it, axis by axis; without `captions` they take the
new safe area's bottom band. A custom name may not be a built-in one; an inline profile is named `custom`.
`new_project(canvas="1920x1080@25")` writes such an inline profile. Unknown fields, sizes, boxes outside the canvas
and loops of `base` are refused with the field named (workspace.json profiles when the workspace loads, an inline
profile by `check`).

## 16. Environment variables

| variable | effect |
|---|---|
| `REELSMITH_ROOT` | tools refuse projects outside this folder, and `import_asset` local files outside it (the runner sets it to the workspace) |
| `REELSMITH_RENDERER` | the renderer folder (default: `renderer/` next to the package) |
| `REELSMITH_LIBRARY` | set by reelsmith for render.mjs: the workspace's component folder |
| `REELSMITH_BUDGET_USD`, `REELSMITH_MIN_BALANCE_USD` | override `budget.per_project_usd` and `budget.min_balance_usd` |
| `REELSMITH_PROXY` | an upstream proxy for `capture` and the runner (both also honour `HTTPS_PROXY` / `HTTP_PROXY`) |
| `REELSMITH_GUARD_PROJECT` | the MCP server holds every call to this project and the runner guard's rules for tool arguments (set by the codex and dsh engines; section 10.1) |
| `REELSMITH_MCP_TOKEN` | the bearer token `reelsmith mcp --http` requires of every request when set, and needs for `--allow-remote` (`--token-env` names another variable) |
| `CODEX_EXE`, `CODEX_HOME` | the Codex binary for `draw` and the codex engine, and Codex's home folder (default `~/.codex`; `reelsmith setup codex --user` writes its `config.toml`) |
| `DSH_EXE` | the dsh command for the dsh engine (default: `dsh` on `PATH`, else `npx -y @deepseek-ai/dsh`) |
| `DSH_HOME` | DeepSeek Harness's home, where `reelsmith setup dsh --user` writes (default `~/.dsh`); the dsh engine sets its own, `<workspace>/.cache/dsh` |
| `OPENROUTER_API_KEY` | `speak`, `animate` and the runner on OpenRouter (workspace `.env` first, then the environment) |
| `DEEPSEEK_API_KEY` | the runner on DeepSeek (`--provider deepseek`, `--backend deepseek` on the agent-sdk engine, or the dsh engine) |
| `OPENAI_API_KEY` | the runner on OpenAI (`--provider openai`); `transcribe` with the default endpoint (`providers.transcribe.key_env` names another) |
| the name in `runner.key_env` | the runner on a `custom` provider |
| `TAVILY_API_KEY` | the api engine's `web_search` through Tavily (when ddgs is not installed, or `web.search` is `tavily`) |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_WORKSPACE_ID` | the runner on Anthropic (agent-sdk engine) |
