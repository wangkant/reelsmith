# reelsmith manual

reelsmith is your video editing app. You decide everything — the cut, the story, the words, the pictures, the
sound — and do it with tools, editing a project the way an editor works in an NLE: tracks, clips, keyframes, text,
shapes, components. reelsmith renders it, times everything to what it follows (a recording's source seconds, the
narration, other clips), measures where your words land on screen, masters the loudness and refuses delivery when
something is broken. Any canvas, any language.

There is no pipeline and no template. Call any tool at any time. A good loop:

1. `notes` — what you learned last time. `manual` once (this text).
2. `new_project` with the profile (the canvas) and the locale (the language) the film needs, unless you were given
   a project.
3. Bring in the material:
   - **Footage** (a recording of the user's, clips they have): `import_asset`, then look at it — `probe`, `frames`,
     `scenes`, `silences`, `transcribe` — and cut it on the timeline at its source seconds (see Editing footage).
   - **A film from a script**: research and write `script.md` in the project folder (your scratchpad: sources,
     angle, lines), `speak` the lines (`voice/voice.json` gives every line's start and end), gather pictures and
     proof (`capture`, `draw`, `animate`, `import_asset`).
4. `edit` the project in batches. `describe` shows the editor's window as text.
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
area is a title-safe margin; on the platform ones (douyin, douyin-long, tiktok, shorts, reels) it is where the
phone's UI does not cover the picture (status bar and tabs on top, like/comment buttons down the right, title and
music at the bottom), and there a film needs sound and nothing may stand still for more than 5 s (`youtube` needs
sound only). Backgrounds may bleed to the edges; **words must stay inside the safe area** — render measures the
film and refuses text outside it. The owner may define other canvases (workspace.json `profiles`, or an inline
`"profile": {"base": "landscape", "width": 1280, "height": 720, "fps": 25}`); `new_project(p,
canvas="1920x1080@25")` makes one. NTSC rates work too: `"fps": 29.97` (or 23.976, 59.94,
`"30000/1001"`) renders at exactly 30000/1001, for broadcast or to match camera footage.

Pixel sizes in this manual (28 px text, 40 px evidence) are for a canvas whose short side is 1080 px; the checks
scale them with your canvas.

**One project, one canvas, one film.** A project renders one mp4 (h264/aac) on its own canvas. For the same edit on
another canvas (a 9:16 cut of a 16:9 film): `new_project` with that profile, `import_asset` the same files from the
first project (on one drive they are hard-linked, so nothing is copied), copy the first project's `tracks`,
`markers` and `chapters` into the new project.json and re-lay the boxes for the new canvas (they are canvas pixels),
then `preview` it. Other formats (webm, GIF, ProRes, audio only, a transparent overlay) are not made here.

**Locale**: project.json `"locale"` (else workspace.json's, else `en`) is the film's language as a BCP-47 tag
(`en`, `en-GB`, `zh-CN`, `ja`). It sets how captions are cut, capture's browser language, the words components add
(EvidenceCard's `Source: `) and `speak`'s default voice: the default voice reads English and Chinese; for another
language the owner sets `providers.tts.voice`, or an `openai` TTS endpoint, and `speak` says so.

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
a narrated explainer on the default `landscape` canvas (its boxes are laid out for 1920×1080; captions use the band
at y 826–1026, so the other words stay above it):

```json
{
  "version": 2,
  "profile": "landscape",
  "locale": "en",
  "meta": {"title": "How much water does a T-shirt drink?", "desc": "The water behind one cotton T-shirt",
           "topic": "water used from the cotton field to a finished T-shirt",
           "shape": "count-up explainer, verdict at the end",
           "sources": [{"title": "Cotton water report", "url": "https://example.com/report/cotton"}]},
  "voice": "voice/voice.json",
  "assets": {
    "field":    {"path": "assets/field.png", "kind": "image"},
    "mill":     {"path": "assets/mill.mp4", "kind": "video"},
    "ev_water": {"path": "assets/ev_water.png", "kind": "evidence", "box": [120, 1320, 1600, 80],
                 "site": "example.com", "url": "https://example.com/report/cotton"},
    "bed":      {"path": "assets/bed.m4a", "kind": "audio"}
  },
  "tracks": [
    {"id": "bg", "kind": "visual", "clips": [
      {"id": "c1", "type": "image", "asset": "field", "start": 0, "end": "line:3", "motion": "push"},
      {"id": "c2", "type": "video", "asset": "mill", "start": "line:3", "end": "line:5", "filter": {"brightness": 0.7}},
      {"id": "c3", "type": "evidence", "asset": "ev_water", "start": "line:5", "end": "end",
       "box": {"x": 120, "y": 160, "w": 1000, "h": 600}, "highlight": {"at": 0.8}}
    ]},
    {"id": "fg", "kind": "visual", "clips": [
      {"id": "hook", "type": "text", "text": "How much water does **a T-shirt** drink?", "start": 0,
       "end": "line:2.end", "box": {"x": 160, "y": 220, "w": 1600, "h": 400},
       "style": {"font": "display", "size": "fit", "max_size": 140, "color": "snow", "stroke": {"color": "night", "width": 8}},
       "keyframes": {"scale": [{"t": 0, "v": 1}, {"t": 2, "v": 1.05, "ease": "inOut"}]}},
      {"id": "n1", "type": "component", "name": "CountUp", "start": "line:6", "dur": 3.5,
       "box": {"x": 1180, "y": 200, "w": 640, "h": 480},
       "props": {"value": 2700, "suffix": "litres", "label": "from the field to the shirt", "at": "line:6+0.3",
                 "ground": "dark"}}
    ]},
    {"id": "marks", "kind": "visual", "clips": [
      {"id": "arrow", "type": "shape", "shape": "arrow", "start": "clip:n1.end-1", "dur": 1.5,
       "box": {"x": 1270, "y": 700, "w": 460, "h": 100}, "d": "M0 50 L460 50", "stroke": "accent",
       "stroke_width": 10, "draw": true}
    ]},
    {"id": "music", "kind": "audio", "clips": [
      {"id": "m1", "type": "audio", "asset": "bed", "start": 0, "end": "end", "volume": 0.12, "loop": true,
       "fade_out": 1.5}
    ]},
    {"id": "cap", "kind": "captions", "source": "voice", "emphasis": ["T-shirt"]}
  ]
}
```

The arrow sits on its own track because it starts while `n1` is still on screen: two clips that overlap in time
need two tracks. On another canvas lay the boxes out for its size (a `vertical` film is 1080×1920). Words in any
language go in the same fields; the project's `locale` (`"zh-CN"`, `"ja"`, ...) tells reelsmith how to cut the
captions. A film made from footage: see Editing footage.

The narration (`voice`) plays by itself at full volume. The film lasts until the voice ends + 0.6 s unless you
set `"duration"` (without a voice, until its last clip ends). Without a captions track there are no captions. A
captions track's `"language"` (default: the project's locale) labels its subtitle files; `"chapters": [{"at": Time,
"title": "..."}]` names the film's chapters.

### Time

A **Time** is seconds or a string anchored on the narration, a clip or the film end:

| Time | means |
|---|---|
| `"line:5"` / `"line:5.end"` | start / end of voice line 5 (1-based) |
| `"clip:c2"` / `"clip:c2.end"` | start / end of clip c2 |
| `"mark:punch"` | the project marker `punch` (`"markers": {"punch": 12.4}`; a marker is itself a Time) |
| `"src:a@41.2"` | the moment video or audio clip `a` plays second 41.2 of its source (its `trim_in` and `rate` applied) |
| `"end"` | end of the film |
| `"line:5+0.3"`, `"clip:c2.end-0.5"`, `"src:a@41.2-0.1"`, `"end-2"` | any of these plus or minus seconds |

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
`"safe"`, default full), `opacity`, `rotate` (deg), `scale`, `flip_x` / `flip_y` (mirror the content inside the
box: selfie footage, a subject that should face into the frame), `origin` (`"center"`, `"top-left"`, ...),
`radius`, `blend` (`"multiply"`, `"screen"`, ...), `filter` `{blur, brightness, contrast, saturate, grayscale,
sepia, invert, hue_rotate}` (grayscale/sepia/invert 0..1, hue_rotate degrees: sepia 0.6 for a flashback, a small
hue_rotate with saturate 1.1 to warm a shot), `shadow`
(true or a CSS shadow), `enter` / `exit` `{"preset": "fade"|"rise"|"drop"|"pop"|"wipe_left"|"wipe_up"|"zoom",
"dur": 0.4}`, `transition` `{"type": "crossfade"|"dip_black"|"dip_white"|"wipe_left"|"wipe_right"|"wipe_up"|
"slide_left"|"zoom", "dur": 0.5}` (in from the clip before it on the same track: see Editing footage).

`keyframes`: `{"<prop>": [{"t": Time, "v": number, "ease": "linear"|"in"|"out"|"inOut"|"spring"|"step"}]}` for
`x y w h opacity rotate scale zoom pan_x pan_y progress`, the filter props `blur brightness contrast saturate
grayscale sepia invert hue_rotate` (a fade from colour to black and white is `grayscale` 0 → 1), `focus_x focus_y`
on image and video clips, `volume` on video and audio clips and `rate` on video clips; the ease shapes the move
into that keyframe. `progress` (0..1) drives shapes and components; `volume` replaces the clip's `volume` (0
silent, 1 full); `rate` is a speed curve (below).

**Ken Burns** (image and video clips; the content moves inside the box, which crops it):
- `zoom` is a factor around the clip's `focus` point: 1 = the picture as fitted, 1.2 = 20 % closer.
- `pan_x` / `pan_y` move the picture in box pixels (+ right / down). A pan must not uncover the box's edge, so the
  renderer zooms in just enough for the widest pan you keyframe; to choose the zoom yourself, keep a pan within
  (zoom − 1) × box width ÷ 2 (height for `pan_y`), e.g. zoom 1.2 in an 840 px box allows ±84 px.
- `focus` `[fx, fy]` (0..1, default centre) picks what `cover` keeps when the picture's shape differs from the
  box, and is where `zoom` closes in: the picture's point fx sits at fraction fx of the box, so 0 shows the left
  edge, 1 the right edge, and a subject at fraction fx of the picture stays in view.
- `focus_x` / `focus_y` keyframes move that point: **reframing**. Landscape footage on a vertical canvas shows a
  third of its width; to follow a speaker, find where they are (`frames` or `scenes`: their x as a fraction of the
  picture width) and keyframe `focus_x` there, e.g. `[{"t": 0, "v": 0.3}, {"t": 4, "v": 0.3}, {"t": 4.6, "v": 0.7,
  "ease": "inOut"}]`. To centre a subject at fraction s exactly, fx = (s − v/2) ÷ (1 − v) where v is the shown
  fraction (box aspect ÷ picture aspect: 0.316 for 16:9 footage in a 9:16 box). `pan_x`/`pan_y` cannot do this:
  they move the fitted picture inside its box and never reveal what `cover` cropped.
- `motion` is shorthand: `push` (zoom 1.02 → 1.12), `pull` (1.12 → 1.02), `pan_left`/`pan_right` (zoom 1.14,
  pan ±3.4 % of the box), `rise` (zoom 1.1, pan_y ±2.2 %), `still`. Keyframes on the same property win.

| type | fields |
|---|---|
| `image` | `asset`, `fit` `"cover"`/`"contain"`, `focus` `[fx, fy]`, `motion`; an animated GIF, APNG or WebP plays and loops |
| `video` | `asset`, `trim_in` (source seconds skipped), `rate` (2 = twice as fast), `loop`, `fit`, `focus`, `motion`, `volume` (default 0: muted), `reverse` (plays backwards), `hold` (a source second shown throughout: a freeze frame) |
| `text` | `text` (`**word**` = accent colour), `style` (TextStyle), `reveal` `{"mode", "dur"}` |
| `shape` | `shape` `"rect"|"ellipse"|"line"|"arrow"|"path"`, `fill`, `stroke`, `stroke_width`, `d` (SVG path in box pixels), `draw` (the stroke draws on) |
| `evidence` | `asset` (kind evidence): the capture's box (the proving sentence) scaled to the clip's width (at most 2×), with a little page above and below; the panel hugs that content, the rest of the clip box stays transparent, and cut edges fade out; `highlight` `{"at", "dur", "color"}` sweeps the sentence |
| `component` | `name`, `props` (checked against the component's schema; see `library`) |
| `audio` (audio tracks) | `asset`, `trim_in`, `volume`, `fade_in`, `fade_out`, `loop` (repeat the file to fill the clip), `keyframes` (`volume` only), `transition` (`crossfade` only), `duck` `{"under": "<track id>" or "voice", "to": 0.25, "fade": 0.3}` |

**Text.** TextStyle: `font`, `size` px or `"fit"`, `max_size` 160, `min_size` 28 (defaults scale with the canvas),
`weight` 100–900, `color`
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
`"source": "clip:a"` captions what clip `a` says instead, from its asset's transcript (see Editing footage).
`"mode": "words"` lights each word in the accent colour while it is said (karaoke; `emphasis` is not shown then),
`"build"` shows the words one by one as they are said, `"phrase"` (the default) shows each phrase whole. Word times
come from the transcript; voice lines and given `items` are timed by characters.

## Edit ops

`edit(project, ops)` applies a list of ops as one batch: all apply and the result validates, or nothing changes.
Each applied batch can be undone with `undo`.

```json
{"op": "add_track", "track": {"id": "v3", "kind": "visual", "clips": []}, "index": 2}
{"op": "update_track", "id": "cap", "set": {"emphasis": ["T-shirt", "2,700 litres"], "hidden": null}}
{"op": "remove_track", "id": "v3"}
{"op": "add_clip", "track": "fg", "clip": {"id": "s1", "type": "component", "name": "Stamp", "start": "line:8", "dur": 2, "box": {"x": 1400, "y": 380, "w": 360, "h": 360}, "props": {"text": "KEEP IT"}}}
{"op": "update_clip", "id": "hook", "set": {"style": {"color": "gold"}, "enter": null}}
{"op": "remove_clip", "id": "arrow"}
{"op": "move_clip", "id": "c2", "start": "line:3", "end": "line:4.end", "track": "bg"}
{"op": "split_clip", "id": "c2", "at": "line:4", "new_id": "c2b"}
{"op": "set_keyframes", "id": "c1", "prop": "zoom", "frames": [{"t": 0, "v": 1}, {"t": "line:3", "v": 1.2, "ease": "inOut"}]}
{"op": "add_asset", "id": "chart", "asset": {"path": "assets/chart.png", "kind": "image"}}
{"op": "update_asset", "id": "ev_water", "set": {"box": [120, 1300, 1700, 80]}}
{"op": "remove_asset", "id": "chart"}
{"op": "set", "path": "meta.title", "value": "How much water does a T-shirt drink?"}
{"op": "ripple_delete", "start": "src:a@12.3", "end": "src:a@13.9"}
{"op": "insert_gap", "at": "clip:a2", "dur": 1.5, "tracks": ["v1"]}
{"op": "trim_clip", "id": "a", "in": 4.2, "out": 31, "ripple": true}
```

`set` replaces the value at a dotted path (not inside `tracks` or `assets`). `update_*` deep-merge; `null` removes a
key. `add_asset` with an id that exists replaces that asset. An asset still used by a clip (directly or through
component props) cannot be removed. The last three are ripple edits for footage (next section).

## Editing footage

A recording of your own, or a clip you downloaded, is a source: look at it, cut it on the timeline, caption it.
The footage tools speak **source seconds**; `"src:a@41.2"` is the moment clip `a` plays second 41.2 of its source
(its `trim_in` and `rate` applied), so you cut straight from what you found. Narration is optional: a film of
footage needs no `speak`, and without a voice it lasts until its last clip ends (or `duration`).

1. `import_asset` the file (any size: on the project's drive it is hard-linked, not copied), then `probe` it:
   length, resolution, fps, rotation, colour, sound and its loudness. An HDR recording (a phone's HLG or Dolby
   Vision, PQ) is flagged: the film is SDR and is not tone-mapped, so it looks different next to SDR shots.
2. Look before you cut. `frames(p, "talk", n=12)` (or `times`, or `every`) gives stills at source times and a
   contact sheet with each time burned in: Read it. `scenes` lists the shot cuts with each shot's first frame,
   `silences` the quiet ranges and the sound between them, and `transcribe` writes every word with its time
   (`assets/talk.transcript.json`; it costs money with an API provider, so do it once).
3. Lay it down: `{"id": "a", "type": "video", "asset": "talk", "start": 0, "end": "src:a@95", "volume": 1}` runs
   until source second 95. `trim_in` skips the head, `rate` speeds it up; give video `volume` 1 to hear it.
4. Cut. `ripple_delete` takes a range out and closes the gap: clips crossing its edges are split (the part after
   the cut continues as `a_2`, `a_3`, ... with its `trim_in` moved on; a clip whose head is cut keeps its id), later
   clips, markers and caption items move up. Jump cuts from `silences`: one `ripple_delete` per silence from
   `"src:a@<start + 0.1>"` to `"src:a@<end - 0.1>"` (a breath of air each side), **from the last silence back** in
   one batch, so each `src:a@...` still names the piece that plays it. Name the tracks to cut
   (`"tracks": ["v1"]`, plus the track of its sound if that is separate, and a captions track with `items`): left
   out, every track is cut, a music bed included, and the music skips at each jump; or cut first and lay the bed
   after. A cut that falls inside a transition keeps what is left of it (shortened to fit). `trim_clip` sets a clip's
   in/out in source seconds (`ripple: true` pulls the rest of its track along; without it the picture stays put and
   only the edges move), `insert_gap` opens room, and `split_clip` cuts a clip in two. Anchors that stay true after
   a ripple edit stay; the rest become numbers.
5. Join shots: give the later clip `"transition": {"type": "crossfade", "dur": 0.4}` and start it that long before
   the previous one ends (`"start": "clip:a.end-0.4"`); that is the only overlap a track allows. Without the
   overlap it transitions in over whatever is beneath it. `dip_black`/`dip_white` go through a colour,
   `wipe_left`/`wipe_right`/`wipe_up` sweep an edge, `slide_left` pushes the old shot out, `zoom` zooms through. A
   clip with sound crossfades its sound over the same time.
6. Sound: `volume` keyframes ride a clip's level (`{"t": 3, "v": 0.2}`); a music bed with `"duck": {"under": "v1"}`
   (or `"voice"`) drops to 0.25 while that track's clips with sound play, easing 0.3 s either side.
7. Captions that follow the speech: a captions track with `"source": "clip:a"` once `talk` is transcribed. It
   follows every piece of that recording on `a`'s track (if a cut or `remove_clip` takes `a` away, the next piece
   you can hear), drops the words you cut, and phrases by pauses and sentence ends, then within `max_chars` the way
   voice captions are. `"mode": "words"` lights each word as it is said, `"build"` adds the words one by one.
8. Name moments you will come back to: `"markers": {"punch": "src:a@41.2"}`, then `"mark:punch"` wherever a Time
   goes; markers move with ripple edits. Chapters (`"chapters": [{"at": "mark:intro", "title": "Intro"}, ...]`)
   anchored on markers move with them too.
9. Time effects, on a piece of its own (split first; do these after the cuts that use `src:` on it):
   - speed ramp: `rate` keyframes, e.g. `[{"t": 0, "v": 1}, {"t": 0.4, "v": 0.25, "ease": "inOut"}, {"t": 1.6, "v":
     0.25}, {"t": 2, "v": 1, "ease": "inOut"}]`; the source walks on by the curve, frame-accurately;
   - freeze frame: `split_clip` at the moment, `insert_gap` of the freeze's length there, and a clip with `"hold":
     <source second>` (the second half's `trim_in`) in the gap; full resolution, unlike a `frames` still;
   - `"reverse": true` plays the piece backwards, sound too (a cached proxy in `build/proxies`).

   A held or speed-curved piece is silent (lay its sound as an audio clip if you want it). On a reversed, held or
   speed-curved piece `src:` anchors, captions from its transcript and `trim_clip` are refused: their source seconds
   are not in film order.
10. `describe` to see the cut as text, `preview` the joins and the captions, `render(p, draft=true,
    start=..., end=...)` to watch a join or a stretch as video, then `render`.

A complete example: a talk recorded in one take on the default `landscape` canvas, with a pause cut out (the
pieces `a` and `a_2`), b-roll over it, a title, a music bed that ducks under the talk and captions from the
transcript. No narration: the film lasts until `a_2` ends.

```json
{
  "version": 2,
  "profile": "landscape",
  "locale": "en",
  "meta": {"title": "Three things I learned building a bike"},
  "assets": {
    "talk": {"path": "assets/talk.mp4", "kind": "video", "transcript": "assets/talk.transcript.json"},
    "shop": {"path": "assets/shop.mp4", "kind": "video"},
    "bed":  {"path": "assets/bed.m4a", "kind": "audio"}
  },
  "markers": {"punch": "src:a_2@61.4"},
  "tracks": [
    {"id": "v1", "kind": "visual", "clips": [
      {"id": "a", "type": "video", "asset": "talk", "start": 0, "end": "src:a@38.2", "trim_in": 2.5, "volume": 1},
      {"id": "a_2", "type": "video", "asset": "talk", "start": "clip:a.end", "end": "src:a_2@95", "trim_in": 41,
       "volume": 1}
    ]},
    {"id": "v2", "kind": "visual", "clips": [
      {"id": "b1", "type": "video", "asset": "shop", "start": "src:a@20", "dur": 4, "trim_in": 12,
       "enter": {"preset": "fade", "dur": 0.4}, "exit": {"preset": "fade", "dur": 0.4}}
    ]},
    {"id": "titles", "kind": "visual", "clips": [
      {"id": "title", "type": "text", "text": "Three things I learned **building a bike**", "start": 0.5, "dur": 3.5,
       "box": {"x": 96, "y": 80, "w": 1100, "h": 220},
       "style": {"size": "fit", "max_size": 96, "bg": {"color": "night", "radius": 12, "pad": 24}},
       "enter": {"preset": "rise", "dur": 0.5}},
      {"id": "big", "type": "text", "text": "**Measure twice**", "start": "mark:punch", "dur": 2,
       "box": {"x": 96, "y": 560, "w": 1000, "h": 200}, "style": {"size": "fit", "max_size": 140}}
    ]},
    {"id": "music", "kind": "audio", "clips": [
      {"id": "m1", "type": "audio", "asset": "bed", "start": 0, "end": "end", "volume": 0.3, "loop": true,
       "fade_out": 2, "duck": {"under": "v1", "to": 0.25}}
    ]},
    {"id": "cap", "kind": "captions", "source": "clip:a"}
  ]
}
```

## Tools

| tool | what it does | example |
|---|---|---|
| `manual()` | this manual | `manual()` |
| `notes(project)` | your workspace notes | `notes("/home/me/studio/projects/tshirt")` |
| `note(project, text)` | append a dated lesson at the end of the notes (to file it under a heading, edit `library/NOTES.md` with your file tools) | `note(p, "evidence: match one 8-20 character line, not a paragraph")` |
| `new_project(project, profile?, title?, canvas?, locale?)` | create a project folder; `canvas` `"WxH"` or `"WxH@fps"` (fps may be 29.97) for a canvas of your own | `new_project("/home/me/studio/projects/tshirt", profile="vertical", locale="en")` |
| `describe(project, at?)` | the editor's window as text; with `at`, what is on screen then | `describe(p, at="line:4")` |
| `edit(project, ops)` | apply a batch of ops atomically | `edit(p, [{"op": "remove_clip", "id": "arrow"}])` |
| `undo(project, steps=1)` | undo applied batches | `undo(p)` |
| `check(project)` | errors (block render), warnings, advice | `check(p)` |
| `library(project, name?)` | components with their prop names; with a name, schema, example and source | `library(p, "Receipt")` |
| `typecheck(project)` | type-check your own components | `typecheck(p)` |
| `speak(project, lines, gap_s=0.22)` | narrate; one item per line, a string or `{text, pace, emotion}` | `speak(p, ["How much water", {"text": "does a T-shirt drink?", "pace": 0.95, "emotion": "surprised"}])` |
| `capture(project, url, id, match?, viewport?)` | screenshot of a page as evidence, boxed around `match`; `viewport` `phone` or `desktop` (default: phone on vertical and portrait canvases, desktop on landscape and square) | `capture(p, "https://...", "ev_water", "about 2,700 litres")` |
| `draw(project, id, prompt, style_ref_asset?, size?)` | an original picture | `draw(p, "field", "a cotton field at dawn, photo", size="16:9")` |
| `animate(project, id, image_asset, motion, seconds=4, camera?)` | a short clip from a picture | `animate(p, "field_v", "field", "the cotton bolls sway in the wind", 4, "push")` |
| `import_asset(project, id, source, kind?)` | copy a file or download a URL into assets (`kind` image, video, audio, evidence) | `import_asset(p, "bed", "/home/me/music/bed.m4a", "audio")` |
| `assets(project)` | assets with kinds, sizes, durations, spend | `assets(p)` |
| `probe(project, source)` | a source's streams, codecs, rotation and loudness | `probe(p, "talk")` |
| `frames(project, asset, times?, every?, n?)` | stills of a source at source seconds + a timed contact sheet | `frames(p, "talk", ["0:12", 41.2])` |
| `scenes(project, asset, threshold?)` | shot cuts (source seconds) + each shot's first frame | `scenes(p, "trip")` |
| `silences(project, asset, min_s?, noise_db?)` | quiet ranges and the sound between them (source seconds) | `silences(p, "talk", 0.4)` |
| `transcribe(project, asset, language?, prompt?)` | every word said, with its source time, into `assets/<id>.transcript.json` | `transcribe(p, "talk", "en", "Ada Lovelace, reelsmith")` |
| `preview(project, times?, sweep?)` | stills at chosen moments + contact sheet + layout problems; `sweep` measures the whole film | `preview(p, [0, "line:3", "clip:n1+1", "end-1"])`, `preview(p, sweep=true)` |
| `render(project, draft?, start?, end?, scale?)` | the film to `out/film.mp4`, mastered and checked, with captions files and chapters; `draft=true` a quick small look to `build/draft.mp4` | `render(p)`, `render(p, draft=true, start="clip:b-2", end="clip:b+3")` |
| `review(project, n=12)` | evenly spaced frames of the delivered film + contact sheet | `review(p, 12)` |
| `export_captions(project, track?)` | captions as `out/captions/<track>.srt` and `.vtt`, without rendering | `export_captions(p)` |

- `speak`: `pace` is a speed factor relative to normal (1.0; 0.9 a little slower, 1.1 a little faster; 0.5–2) or
  `"slower"`/`"normal"`/`"faster"`. `emotion` is a word or two (≤ 20 characters, e.g. `"surprised"`, `"calm"`)
  given to the voice as an instruction; how much it changes depends on the voice model, so listen before relying on
  it. Write the lines in the film's language (`"一件T恤，要喝多少水？"` in a `zh-CN` film). `speak` caches per
  line — only changed lines are paid for again. The voice is the workspace's
  `providers.tts.voice`; without one, English and Chinese films get the default model's voice (it speaks both), and
  any other language needs the owner to choose a voice, which `speak` says.
- `draw`: `size` is an aspect — `9:16` (1080×1920), `2:3`, `3:4`, `4:5` (1080×1350), `1:1` (1080×1080), `4:3`,
  `3:2`, `16:9` (1920×1080); the default is the one nearest your canvas — or pixels `"WxH"` (sides 256–4096).
- `speak`, `animate` and `transcribe` cost money (transcribe is free with the owner's local model) and `draw` spends
  limited tries: they estimate first and refuse when the project budget, the account floor or the tries would be
  crossed. Transcribe a recording once; re-speak only the lines that changed.
- Evidence captures are the strongest proof you have: match a short exact phrase that sits on one line of the page
  (8–20 characters). A box spanning two lines, or a whole wide paragraph, comes out too small to read; `check`
  warns when the sentence will read under 40 px (at a 1080 px short side). Re-box an evidence asset with
  `update_asset`. A capture comes back in the project's language (the browser's locale).
- Music: there is no music generator. `import_asset` an audio file you are allowed to use, put it on an audio
  track at a low `volume` (0.08–0.15) with `"loop": true` if it is shorter than the film.
- `preview` is cheap (one bundle, a few seconds a still): use it after every meaningful edit and look at the PNGs.
  In the contact sheet (tiles in your canvas's shape) the dark bands are outside the safe area (the platform's UI,
  or the title-safe margin), the yellow line is the safe area's edge and each tile shows its time. Earlier previews' stills stay in `build/stills`. `sweep=true` measures the film exactly
  as `render` does before it encodes, and keeps the stills of the flagged moments: run it before `render`.
- Drafts: `render(p, draft=true)` renders the film at half size with a fast encode to `build/draft.mp4`, not
  mastered and not checked (`out/` is untouched); `start`/`end` (Times) render just that stretch and `scale`
  (0.1-1) sets the size. Use it to watch joins, pacing and sound on a long film before the real render.
- Subtitles and chapters ship with the film: every captions track, hidden ones too, becomes
  `out/captions/<track>.srt` and `.vtt` (a hidden track with its own `items` and `"language": "es"` is a Spanish
  subtitle file that is never burned in); `export_captions` writes them without rendering. Project `chapters`
  become `out/chapters.txt` (`0:00 Intro` lines for a YouTube description) and chapter marks in the mp4; YouTube
  shows them when the first is at 0:00, there are at least 3 and each lasts 10 s or more.

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
 "example": {"value": "2,700 L", "at": "line:4"}}
```

Fuller worked examples: the sample component in `examples/workspace/library/components/` (the starter workspace),
and every preset's source (`library(p, name)` gives the path). Lay yourself out in `w × h`; keep text at 28 px or
more at a 1080 px short side (on other canvases scale by `Math.min(width, height) / 1080`, both from `useClip()`);
choose the words a component adds itself by `useClip().locale`; animate from the frame, never from time or
randomness; give SVG ids (`clipPath`, gradients) `React.useId()` so two instances do not collide. Then `typecheck`
and `preview` a moment where it shows. A component that crashes shows a red box in previews and is reported first,
with its source line.

## What blocks delivery

`render` stops — and keeps the previous `out/film.mp4` — at the first stage that fails:

1. **check errors**: the project does not validate (unknown ids, missing files, overlaps on a track, bad Times, an
   unknown font...); the owner's hard rules from `rules.json`, when there are any (for example a title of at most
   24 characters with at most 2 numbers, at least 1 source with an http(s) url, no banned words in
   title/desc/topic); the length outside the profile's limits, when it has any.
2. **layout** (measured on a still every second, spread to 600 stills on a film over 10 minutes, plus one in each
   text and caption between them — `preview` with `sweep` runs the same pass): visible text outside the safe area
   or cut by the canvas edge, text under 20 px, a component that crashes. Text during its enter/exit animation and
   text fainter than 10 % opacity are not counted.
3. **the film**: the profile's size and fps, h264/aac, length and size within the profile's limits, black ≤ 10 %
   of the film. A profile that requires sound (`youtube` and the platform ones) refuses a silent or near-silent
   film, and the platform ones (douyin, douyin-long, tiktok, shorts, reels) **any stretch longer than 5 s without
   motion** (move something: keyframes, `motion`, a reveal, a video); on the generic canvases a silent film or a
   held frame is delivered as it is.

The report lists what failed with clip ids and times (`hook @ 1.0s`) — fix those, `preview` them, render again. A
failure of the renderer itself (its local server or browser) is retried once and reported as a transient problem,
not as your project's: run the same call again. `render` reports each stage's time; `build/report.json` is the
latest attempt, `out/report.json` the delivered film's.

**Warnings** (information; take them seriously): text under 28 px (at a 1080 px short side); text of one clip
over text of another
(captions included); text on a background of about its own brightness (contrast measured on the still); text
overflowing its clip box; evidence whose proving sentence will read under 40 px; on platform profiles (or when
`rules.json` sets `hook_seconds`), words that are not whole on frame 0, which is the cover (mid-reveal, mid-enter,
fading in), or no words there at all.
**Advice**, only what the owner's `rules.json` asks for: for example no words on screen in the first 2 s (the
hook), one still picture held longer than 8 s with nothing moving it, a length outside the target. An empty title
is a warning only when the owner has a title rule.
