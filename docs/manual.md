# reelsmith manual

reelsmith is your video editing app. You decide everything — the story, the script, the voice, the pictures, the
cut — and do it with tools: research the topic, write the script, narrate it (`speak`), gather pictures and proof
(`capture`, `draw`, `animate`, `import_asset`), then edit a project the way an editor works in an NLE: tracks,
clips, keyframes, text, shapes, components. reelsmith renders, times everything to the narration, measures where
your words land on screen, masters the loudness and refuses delivery when something is broken.

There is no pipeline and no template. Call any tool at any time. A good loop:

1. `notes` — what you learned last time. `manual` once (this text).
2. Research and write `script.md` in the project folder (your scratchpad: sources, angle, lines).
3. `speak` the lines → `voice/voice.json` gives every line's start and end.
4. Gather assets, then `edit` the project in batches. `describe` shows the editor's window as text.
5. `check` → `preview` key moments and **look at the stills** (Read the PNGs) → fix → repeat.
6. `preview` with `sweep` (the layout of the whole film) → `render` → `review` the frames as a viewer would →
   `note` what you learned.

Every tool takes `project` = the path of the project folder (the one holding `project.json`). Tools never throw:
a failure comes back as text that says what to do.

## The canvas

**`describe` prints your canvas first: its profile, size, fps, safe area and locale.** Lay every box out for that
canvas. Box values are canvas pixels; `"full"` is the whole canvas, `"safe"` the safe area.

The profile is project.json `"profile"`, else workspace.json's, else `landscape`:

| profile | canvas | safe area | delivery |
|---|---|---|---|
| `landscape` (default) | 1920×1080 | x 96–1824, y 54–1026 | any length, sound optional |
| `vertical` / `square` / `portrait` | 1080×1920 / 1080×1080 / 1080×1350 | 5 % in from each edge | any length, sound optional |
| `youtube` | 1920×1080 | as landscape | sound required |
| `douyin` | 1080×1920 | x 40–880, y 220–1460 | 20–90 s, ≤ 80 MB, −10 LUFS |
| `douyin-long`, `tiktok`, `shorts`, `reels` | 1080×1920 | each its platform's | each its platform's limits |

All run at 30 fps and are mastered to −14 LUFS unless the table says otherwise. On the generic canvases the safe
area is a title-safe margin; on the platform ones (douyin, tiktok, shorts, reels) it is where the phone's UI does
not cover the picture (status bar and tabs on top, like/comment buttons down the right, title and music at the
bottom), and there a film needs sound and nothing may stand still for more than 5 s. Backgrounds may bleed to the
edges; **words must stay inside the safe area** — render measures every second and refuses text outside it. The
owner may define other canvases (workspace.json `profiles`, or an inline `"profile": {"base": "douyin", "width":
720, "height": 1280, "fps": 25}`); `new_project(p, canvas="1920x1080@25")` makes one.

Pixel sizes in this manual (28 px text, 40 px evidence) are for a canvas whose short side is 1080 px; the checks
scale them with your canvas.

**Locale**: project.json `"locale"` (else workspace.json's, else `en`) is the film's language as a BCP-47 tag
(`en`, `en-GB`, `zh-CN`, `ja`). It sets how captions are cut, capture's browser language and whether `speak` has a
default voice (only Chinese has one; otherwise the owner sets `providers.tts.voice`).

**Captions** (when the project has a captions track) sit in the profile's captions band, the bottom 200 px of the
safe area — on landscape x 96–1824, y 826–1026; on douyin x 40–880, y 1260–1460 — one line of 36–66 px, white on a
dark plate. Keep other words above the band while captions show, or give the captions track its own `box`.

## Folders

```
<workspace>/workspace.json        profile, locale, theme, providers, budget        rules.json   owner rules
<workspace>/library/components/   your own components (persist across projects)   library/NOTES.md  your notes
<workspace>/library/fonts/        the owner's fonts: a text `font` may name a family there (the file name)
<workspace>/projects/<name>/      project.json  script.md  voice/  assets/  build/ (previews)  out/film.mp4
```

`new_project` creates a project folder. You may also edit `project.json` directly with your file tools; every
tool reads it fresh and validates it. `edit` is safer: atomic, validated and undoable.

## The project

Tracks are listed bottom to top. Clips on one track must not overlap — layer with more tracks. A complete example,
a vertical Chinese explainer (its boxes are laid out for the 1080×1920 douyin canvas):

```json
{
  "version": 2,
  "profile": "douyin",
  "locale": "zh-CN",
  "meta": {"title": "一件T恤要喝多少水", "desc": "一件棉T恤背后的水账 #环保", "topic": "一件棉T恤从种棉到成衣的用水量",
           "shape": "count-up explainer, verdict at the end",
           "sources": [{"title": "棉花用水报告", "url": "https://example.com/report/cotton"}]},
  "voice": "voice/voice.json",
  "assets": {
    "field":    {"path": "assets/field.png", "kind": "image"},
    "mill":     {"path": "assets/mill.mp4", "kind": "video"},
    "ev_water": {"path": "assets/ev_water.png", "kind": "evidence", "box": [40, 820, 1210, 150],
                 "site": "example.com", "url": "https://example.com/report/cotton"},
    "bed":      {"path": "assets/bed.m4a", "kind": "audio"}
  },
  "tracks": [
    {"id": "bg", "kind": "visual", "clips": [
      {"id": "c1", "type": "image", "asset": "field", "start": 0, "end": "line:3", "motion": "push"},
      {"id": "c2", "type": "video", "asset": "mill", "start": "line:3", "end": "line:5", "filter": {"brightness": 0.7}},
      {"id": "c3", "type": "evidence", "asset": "ev_water", "start": "line:5", "end": "end",
       "box": {"x": 40, "y": 360, "w": 840, "h": 420}, "highlight": {"at": 0.8}}
    ]},
    {"id": "fg", "kind": "visual", "clips": [
      {"id": "hook", "type": "text", "text": "一件T恤，**要喝多少水**？", "start": 0, "end": "line:2.end",
       "box": {"x": 60, "y": 300, "w": 800, "h": 360},
       "style": {"font": "display", "size": "fit", "max_size": 140, "color": "snow", "stroke": {"color": "night", "width": 8}},
       "keyframes": {"scale": [{"t": 0, "v": 1}, {"t": 2, "v": 1.05, "ease": "inOut"}]}},
      {"id": "n1", "type": "component", "name": "CountUp", "start": "line:6", "dur": 3.5,
       "box": {"x": 60, "y": 800, "w": 800, "h": 360},
       "props": {"value": 2700, "suffix": "升", "label": "种棉到成衣", "at": "line:6+0.3", "ground": "dark"}}
    ]},
    {"id": "marks", "kind": "visual", "clips": [
      {"id": "arrow", "type": "shape", "shape": "arrow", "start": "clip:n1.end-1", "dur": 1.5,
       "box": {"x": 220, "y": 1160, "w": 460, "h": 140}, "d": "M0 70 L460 70", "stroke": "accent",
       "stroke_width": 10, "draw": true}
    ]},
    {"id": "music", "kind": "audio", "clips": [
      {"id": "m1", "type": "audio", "asset": "bed", "start": 0, "end": "end", "volume": 0.12, "loop": true,
       "fade_out": 1.5}
    ]},
    {"id": "cap", "kind": "captions", "source": "voice", "emphasis": ["T恤"]}
  ]
}
```

The arrow sits on its own track because it starts while `n1` is still on screen: two clips that overlap in time
need two tracks.

The narration (`voice`) plays by itself at full volume. The film lasts until the voice ends + 0.6 s unless you
set `"duration"`. Without a captions track there are no captions.

### Time

A **Time** is seconds or a string anchored on the narration, a clip or the film end:

| Time | means |
|---|---|
| `"line:5"` / `"line:5.end"` | start / end of voice line 5 (1-based) |
| `"clip:c2"` / `"clip:c2.end"` | start / end of clip c2 |
| `"end"` | end of the film |
| `"line:5+0.3"`, `"clip:c2.end-0.5"`, `"end-2"` | any of these plus or minus seconds |

What a **plain number** means depends on where it is:

- `start`, `end` of a clip, `duration`, caption `items`: **seconds from the film's start**.
- Inside a clip — keyframe `t`, `highlight.at`, component props named `at` or `*_at`: **seconds from the clip's
  start**. A clip starting at 10 s with `"at": 0.4` fires at 10.4 s.
- Time strings are the same everywhere: `"at": "line:5+0.3"` fires 0.3 s after line 5 starts, wherever the clip is.

Cut on the narration: start clips at `line:N` and they stay in sync when you re-record the voice. A clip takes
`end` (a Time) or `dur` (seconds). Cycles (`clip:a` timed from `clip:b` timed from `clip:a`) are an error.
`preview` and `describe(at=…)` read Times the same way; there `"clip:c2.end"` shows c2's last frame.

### Clips

Common fields: `id` (unique in the project), `type`, `start`, `end` | `dur`, `box` (`{x,y,w,h}` | `"full"` |
`"safe"`, default full), `opacity`, `rotate` (deg), `scale`, `origin` (`"center"`, `"top-left"`, ...), `radius`,
`blend` (`"multiply"`, `"screen"`, ...), `filter` `{blur, brightness, contrast, saturate, grayscale}`, `shadow`
(true or a CSS shadow), `enter` / `exit` `{"preset": "fade"|"rise"|"drop"|"pop"|"wipe_left"|"wipe_up"|"zoom",
"dur": 0.4}`.

`keyframes`: `{"<prop>": [{"t": Time, "v": number, "ease": "linear"|"in"|"out"|"inOut"|"spring"|"step"}]}` for
`x y w h opacity rotate scale blur brightness zoom pan_x pan_y progress`; the ease shapes the move into that
keyframe. `progress` (0..1) drives shapes and components.

**Ken Burns** (image and video clips; the content moves inside the box, which crops it):
- `zoom` is a factor around the clip's `focus` point: 1 = the picture as fitted, 1.2 = 20 % closer.
- `pan_x` / `pan_y` move the picture in box pixels (+ right / down). A pan must not uncover the box's edge, so the
  renderer zooms in just enough for the widest pan you keyframe; to choose the zoom yourself, keep a pan within
  (zoom − 1) × box width ÷ 2 (height for `pan_y`), e.g. zoom 1.2 in an 840 px box allows ±84 px.
- `focus` `[fx, fy]` (0..1, default centre) picks what `cover` keeps when the picture's shape differs from the
  box, and is where `zoom` closes in.
- `motion` is shorthand: `push` (zoom 1.02 → 1.12), `pull` (1.12 → 1.02), `pan_left`/`pan_right` (zoom 1.14,
  pan ±3.4 % of the box), `rise` (zoom 1.1, pan_y ±2.2 %), `still`. Keyframes on the same property win.

| type | fields |
|---|---|
| `image` | `asset`, `fit` `"cover"`/`"contain"`, `focus` `[fx, fy]`, `motion` |
| `video` | `asset`, `trim_in` s, `rate`, `loop`, `fit`, `focus`, `motion`, `volume` (default 0: muted) |
| `text` | `text` (`**word**` = accent colour), `style` (TextStyle), `reveal` `{"mode", "dur"}` |
| `shape` | `shape` `"rect"|"ellipse"|"line"|"arrow"|"path"`, `fill`, `stroke`, `stroke_width`, `d` (SVG path in box pixels), `draw` (the stroke draws on) |
| `evidence` | `asset` (kind evidence): the capture's box (the proving sentence) scaled to the clip's width (at most 2×), with a little page above and below; the panel hugs that content, the rest of the clip box stays transparent, and cut edges fade out; `highlight` `{"at", "dur", "color"}` sweeps the sentence |
| `component` | `name`, `props` (checked against the component's schema; see `library`) |
| `audio` (audio tracks) | `asset`, `trim_in`, `volume`, `fade_in`, `fade_out`, `loop` (repeat the file to fill the clip) |

**Text.** TextStyle: `font`, `size` px or `"fit"`, `max_size` 160, `min_size` 28 (defaults scale with the canvas),
`weight` 400–900, `color`
(default `snow` with a soft shadow, for pictures and dark grounds: **on paper set `ink`**), `accent`, `align`,
`valign`, `line_height` 1.15, `letter_spacing`, `wrap`, `balance` (exactly two even lines), `stroke` `{color, width}`,
`shadow`, `bg` `{color, radius, pad}` (a plate behind the text).
- `"fit"` is the largest size (between `min_size` and `max_size`) at which the text fits the box's width and
  height, on as many lines as that takes. Lines break between words, never inside a number or before closing
  punctuation; your `\n` breaks are kept. Cap headlines with `max_size`.
- Fonts: `sans` (Noto Sans SC, the default: body, numbers, captions; it covers Latin text too), `serif` (Noto Serif
  SC: quotes, a calmer editorial voice), `display` (Smiley Sans 得意黑, a bold oblique: headlines and verdicts),
  `zcool` (ZCOOL QingKe HuangYou, decorative: some characters such as 水 多 算 read oddly, so only short titles you
  have previewed), and any family the workspace adds in `library/fonts/` (named after the file: `Brand
  Sans.woff2` is `"font": "Brand Sans"`; `check` lists them when a name is unknown). Components can use them too
  (`fontFamily("Brand Sans")` from the kit).
- `reveal` modes: `chars` (a character at a time), `words`, `lines` (the lines as laid out on screen, one after
  another), `none`. `dur` is the whole reveal in seconds (default 0.8).

**Shapes.** `rect` and `ellipse` fill the box. `line` and `arrow` without `d` run corner to corner (top-left to
bottom-right of the box): give `d`, e.g. `"M0 70 L460 70"` for a level arrow across a 460×140 box. Lines and
arrows are drawn by their stroke; with only `fill` they use that colour. With neither, they are drawn in `accent`.
`stroke_width` defaults to 6. `draw: true` draws the stroke on over 0.6 s, or along `progress` keyframes.

**Colours.** Every colour field (text `color`/`accent`/`stroke`/`bg`, shape `fill`/`stroke`, `highlight.color`,
component colour props) takes a theme token or any CSS colour. The default theme `paper`:

| token | hex | for |
|---|---|---|
| `paper` | #F3EBDD | light ground |
| `ink` | #1E1A16 | text on paper (set it: text defaults to `snow`) |
| `night` | #16130F | dark ground |
| `snow` | #F7F1E6 | text on night or on pictures (the default text colour) |
| `accent` | #C8372D | the one number that matters, the stamp |
| `gold` | #D9A441 | highlights (poor as text on paper) |
| `good` / `bad` | #2E8B57 / #C8372D | gains / losses |
| `muted` | #7A6F62 | secondary text |

`"theme": {"name": "night"}` switches to the darker palette; `"theme": {"accent": "#FF5A3C"}` overrides one token
(in project.json or workspace.json).

**Captions track:** `{"id", "kind": "captions", "source": "voice", "box"?, "style"?, "emphasis": [words in
accent], "max_chars"?, "overrides": [{"line": 5, "text": "..."}], "items"?: [{"start", "end", "text"}]}` —
phrase-split between words (never inside a word or a number) and timed from the voice lines unless you give
`items`. `max_chars` (4–60) defaults to 14 for Chinese, Japanese and Korean and 32 for other languages. Phrases
drop the punctuation they were cut at. Fix a bad split with an override that adds a comma where the cut should be.

## Edit ops

`edit(project, ops)` applies a list of ops as one batch: all apply and the result validates, or nothing changes.
Each applied batch can be undone with `undo`.

```json
{"op": "add_track", "track": {"id": "v3", "kind": "visual", "clips": []}, "index": 2}
{"op": "update_track", "id": "cap", "set": {"emphasis": ["T恤", "两千七百升"], "hidden": null}}
{"op": "remove_track", "id": "v3"}
{"op": "add_clip", "track": "fg", "clip": {"id": "s1", "type": "component", "name": "Stamp", "start": "line:8", "dur": 2, "box": {"x": 560, "y": 900, "w": 300, "h": 300}, "props": {"text": "省着穿"}}}
{"op": "update_clip", "id": "hook", "set": {"style": {"color": "gold"}, "enter": null}}
{"op": "remove_clip", "id": "arrow"}
{"op": "move_clip", "id": "c2", "start": "line:3", "end": "line:4.end", "track": "bg"}
{"op": "split_clip", "id": "c2", "at": "line:4", "new_id": "c2b"}
{"op": "set_keyframes", "id": "c1", "prop": "zoom", "frames": [{"t": 0, "v": 1}, {"t": "line:3", "v": 1.2, "ease": "inOut"}]}
{"op": "add_asset", "id": "chart", "asset": {"path": "assets/chart.png", "kind": "image"}}
{"op": "update_asset", "id": "ev_water", "set": {"box": [70, 300, 890, 62]}}
{"op": "remove_asset", "id": "chart"}
{"op": "set", "path": "meta.title", "value": "一件T恤要喝多少水"}
```

`set` replaces the value at a dotted path (not inside `tracks` or `assets`). `update_*` deep-merge; `null` removes a
key. `add_asset` with an id that exists replaces that asset. An asset still used by a clip (directly or through
component props) cannot be removed.

## Tools

| tool | what it does | example |
|---|---|---|
| `manual()` | this manual | `manual()` |
| `notes(project)` | your workspace notes | `notes("/home/me/studio/projects/tshirt")` |
| `note(project, text)` | append a dated lesson at the end of the notes (to file it under a heading, edit `library/NOTES.md` with your file tools) | `note(p, "evidence: match one 8-20 character line, not a paragraph")` |
| `new_project(project, profile?, title?, canvas?, locale?)` | create a project folder; `canvas` `"WxH"` or `"WxH@fps"` for a canvas of your own | `new_project("/home/me/studio/projects/tshirt", profile="vertical", locale="en")` |
| `describe(project, at?)` | the editor's window as text; with `at`, what is on screen then | `describe(p, at="line:4")` |
| `edit(project, ops)` | apply a batch of ops atomically | `edit(p, [{"op": "remove_clip", "id": "arrow"}])` |
| `undo(project, steps=1)` | undo applied batches | `undo(p)` |
| `check(project)` | errors (block render), warnings, advice | `check(p)` |
| `library(project, name?)` | components with their prop names; with a name, schema, example and source | `library(p, "Receipt")` |
| `typecheck(project)` | type-check your own components | `typecheck(p)` |
| `speak(project, lines, gap_s=0.22)` | narrate; one item per line, a string or `{text, pace, emotion}` | `speak(p, ["一件T恤，", {"text": "要喝多少水？", "pace": 0.95, "emotion": "惊讶"}])` |
| `capture(project, url, id, match?, viewport?)` | screenshot of a page as evidence, boxed around `match`; `viewport` `phone` or `desktop` (default: phone on vertical and portrait canvases, desktop on landscape and square) | `capture(p, "https://...", "ev_water", "about 2,700 litres")` |
| `draw(project, id, prompt, style_ref_asset?, size?)` | an original picture | `draw(p, "field", "a cotton field at dawn, photo", size="16:9")` |
| `animate(project, id, image_asset, motion, seconds=4, camera?)` | a short clip from a picture | `animate(p, "field_v", "field", "the cotton bolls sway in the wind", 4, "push")` |
| `import_asset(project, id, source, kind?)` | copy a file or download a URL into assets (`kind` image, video, audio, evidence) | `import_asset(p, "bed", "/home/me/music/bed.m4a", "audio")` |
| `assets(project)` | assets with kinds, sizes, durations, spend | `assets(p)` |
| `preview(project, times?, sweep?)` | stills at chosen moments + contact sheet + layout problems; `sweep` measures the whole film | `preview(p, [0, "line:3", "clip:n1+1", "end-1"])`, `preview(p, sweep=true)` |
| `render(project)` | the film to `out/film.mp4`, mastered and checked | `render(p)` |
| `review(project, n=12)` | evenly spaced frames of the delivered film + contact sheet | `review(p, 12)` |

- `speak`: `pace` is a speed factor relative to normal (1.0; 0.9 a little slower, 1.1 a little faster; 0.5–2) or
  `"slower"`/`"normal"`/`"faster"`. `emotion` is a word or two (≤ 20 characters, e.g. `"surprised"`, `"惊讶"`)
  given to the voice as an instruction; how much it changes depends on the voice model, so listen before relying on
  it. `speak` caches per line — only changed lines are paid for again. The voice is the workspace's
  `providers.tts.voice`; without one only a Chinese locale has a default (a Mandarin voice), and `speak` says so.
- `draw`: `size` is an aspect — `9:16` (1080×1920), `2:3`, `3:4`, `4:5` (1080×1350), `1:1` (1080×1080), `4:3`,
  `3:2`, `16:9` (1920×1080); the default is the one nearest your canvas — or pixels `"WxH"` (sides 256–4096).
- `speak`, `draw` and `animate` may cost money: they estimate first and refuse when the project budget or the
  account floor would be crossed.
- Evidence captures are the strongest proof you have: match a short exact phrase that sits on one line of the page
  (8–20 characters). A box spanning two lines, or a whole wide paragraph, comes out too small to read; `check`
  warns when the sentence will read under 40 px (at a 1080 px short side). Re-box an evidence asset with
  `update_asset`. A capture comes back in the project's language (the browser's locale).
- Music: there is no music generator. `import_asset` an audio file you are allowed to use, put it on an audio
  track at a low `volume` (0.08–0.15) with `"loop": true` if it is shorter than the film.
- `preview` is cheap (one bundle, a few seconds a still): use it after every meaningful edit and look at the PNGs.
  In the contact sheet (tiles in your canvas's shape) the dark bands are outside the safe area (the platform's UI,
  or the title-safe margin), the yellow line is the safe area's edge and each tile shows its time. Earlier previews' stills stay in `build/stills`. `sweep=true` measures a still every second, exactly
  as `render` does before it encodes, and keeps the stills of the flagged moments: run it before `render`.

## Components

A component clip renders a React component inside the clip box. Built-in presets: `Receipt`, `Stamp`, `CountUp`,
`BarCompare`, `TimelineRule`, `DotGrid`, `EvidenceCard`, `Highlighter`, `Arrow` — `library(project)` lists them
with their prop names, `library(project, "Receipt")` shows the schema, an example and the source file.

In props, any key named `at` or ending in `_at` takes a Time (a number = seconds from the clip's start) and
arrives in the component as **frames from the clip's start**; any key named `asset` or ending in `_asset` takes an
asset id and arrives as `{src, kind, size?, box?, site?, duration?}`. This works at any depth.

### Writing your own

Put `Name.tsx` and `Name.meta.json` in `<workspace>/library/components/`. They persist, every project can use them,
and a library component shadows a preset of the same name. Imports allowed: `react`, `remotion`, `@remotion/*`,
`@reelsmith/kit` and files in the same folder — anything else is refused when the film is bundled.

**The kit reference is [docs/kit.md](kit.md)** (`library` prints its path): every `@reelsmith/kit` export with its
signature — `useClip()`, `frameOr`, `numOr`, `themeColor`, `onGround`, `fit`, `textWidth`, `springAt`, `ease`,
`fmt`, `twoLines`, `toFrames`, `FONTS`, `Media`, `EvidenceCrop` and the rest. A minimal component:

```tsx
// library/components/Tally.tsx: a number that pops in at `at`
import { useCurrentFrame } from "remotion";
import { fit, FONTS, frameOr, springAt, themeColor, useClip } from "@reelsmith/kit";

export default function Tally({ props }: { props: any }) {
  const { w, h, fps, theme } = useClip();       // the clip box size, fps, theme colours
  const f = useCurrentFrame();                   // frames from the clip's start
  const at = frameOr(props.at, 0);               // a Time in project.json, frames here
  if (f < at) return null;                       // nothing stale on screen before it lands
  const text = String(props.value ?? "");
  const pop = springAt(f, at, { fps });
  return (
    <div style={{ width: w, height: h, display: "flex", alignItems: "center", justifyContent: "center",
                  fontFamily: FONTS.sans, fontWeight: 900, fontSize: fit(text, w * 0.9, h * 0.8, FONTS.sans, 900),
                  color: themeColor(theme, props.color, "accent"), transform: `scale(${0.6 + 0.4 * pop})` }}>
      {text}
    </div>
  );
}
```

```json
{"name": "Tally", "description": "A number that pops in.",
 "props": {"type": "object", "required": ["value"], "additionalProperties": false,
           "properties": {"value": {"type": "string"}, "at": {"description": "Time it pops (default: clip start)"},
                          "color": {"type": "string", "description": "theme token or CSS colour"}}},
 "example": {"value": "2,700升", "at": "line:4"}}
```

Fuller worked examples: the sample component in the example workspace's `library/components/`, and every preset's
source (`library(p, name)` gives the path). Lay yourself out in
`w × h`; keep text at 28 px or more at a 1080 px short side (on other canvases scale by `Math.min(width, height)
/ 1080`, both from `useClip()`); animate from the frame, never from time or randomness; give SVG ids
(`clipPath`, gradients) `React.useId()` so two instances do not collide. Then `typecheck` and `preview` a moment
where it shows. A component that crashes shows a red box in previews and is reported first, with its source line.

## What blocks delivery

`render` stops — and keeps the previous `out/film.mp4` — at the first stage that fails:

1. **check errors**: the project does not validate (unknown ids, missing files, overlaps on a track, bad Times, an
   unknown font...); the owner's hard rules from `rules.json`, when there are any (for example a title of at most
   24 characters with at most 2 numbers, at least 1 source with an http(s) url, no banned words in
   title/desc/topic); the length outside the profile's limits, when it has any.
2. **layout** (measured on a still every second — `preview` with `sweep` runs the same pass): visible text outside
   the safe area or cut by the canvas edge, text under 20 px, a component that crashes. Text during its
   enter/exit animation and text fainter than 10 % opacity are not counted.
3. **the film**: the profile's size and fps, h264/aac, length and size within the profile's limits, black ≤ 10 %
   of the film. On the platform profiles also sound present (not near silent) and **no stretch longer than 5 s
   without any motion** (move something: keyframes, `motion`, a reveal, a video); on the generic canvases a silent
   film or a held frame is delivered as it is.

The report lists what failed with clip ids and times (`hook @ 1.0s`) — fix those, `preview` them, render again. A
failure of the renderer itself (its local server or browser) is retried once and reported as a transient problem,
not as your project's: run the same call again. `render` reports each stage's time; `build/report.json` is the
latest attempt, `out/report.json` the delivered film's.

**Warnings** (information; take them seriously): text under 28 px (at a 1080 px short side); text of one clip
over text of another
(captions included); text on a background of about its own brightness (contrast measured on the still); text
overflowing its clip box; evidence whose proving sentence will read under 40 px; words that are not whole on
frame 0, which is the cover (mid-reveal, mid-enter, fading in), or no words there at all.
**Advice**, only what the owner's `rules.json` asks for: for example no words on screen in the first 2 s (the
hook), one still picture held longer than 8 s with nothing moving it, a length outside the target. An empty title
is a warning only when the owner has a title rule.
