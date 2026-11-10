# reelsmith manual

reelsmith is a video editor you operate with tools. You decide the cut, the story, the words, the pictures and the
sound, and build the film in a project (tracks, clips, keyframes, text, shapes, components). reelsmith times every
clip to what it follows (the narration, a recording's source seconds, other clips), renders through Remotion,
measures where your words land on screen, masters the loudness and refuses delivery when something is broken.

There is no pipeline and no template. Call any tool at any time. A good loop:

1. `notes` (what you learned last time) and `manual(project)` once the project exists: this text, then the
   playbook of the project's platform. Without a project yet, `manual()`.
2. `new_project` with the profile (the canvas and the platform) and the locale (the language) the film needs, unless
   you were given a project.
3. Bring in the material:
   - **Footage** (a recording of the user's, clips they have): `import_asset`, then look at it (`probe`, `frames`,
     `scenes`, `silences`, `transcribe`) and cut it on the timeline at its source seconds (see Editing footage).
   - **A film from a script**: research and write `script.md` in the project folder (your scratchpad: sources,
     angle, lines), `speak` the lines (`voice/voice.json` gives every line's start and end), gather pictures and
     proof (`capture`, `draw`, `animate`, `import_asset`).
4. `edit` the project in batches. `describe` shows the editor's window as text.
5. `check` → `preview` key moments and **look at the stills** (Read the PNGs) → fix → repeat.
6. `preview` with `sweep` (the layout of the whole film) → `render` → `review`: watch the film a second at a time
   (Read every sheet, with the line heard at each frame) as a viewer would → fix → `note` what you learned.

Every tool takes `project` = the path of the project folder (the one holding `project.json`). Tools never throw:
a failure comes back as text that says what to do. From a shell: `reelsmith <tool> <project> ...` (`--help` on
each); `edit` takes the ops as JSON, `@ops.json` or `-` (stdin).

## The canvas and the platform

**`describe` prints your canvas first: its profile, size, fps, safe area and locale.** Lay every box out for that
canvas. Box values are canvas pixels; `"full"` is the whole canvas, `"safe"` the safe area. The profile is
project.json `"profile"`, else workspace.json's, else `landscape`:

| profile | canvas | safe area | length (target) | max size | loudness |
|---|---|---|---|---|---|
| `landscape` (default) | 1920×1080 | x 96–1824, y 54–1026 | any | none | −14 LUFS |
| `vertical` / `square` / `portrait` | 1080×1920 / 1080×1080 / 1080×1350 | 5 % in from each edge | any | none | −14 |
| `youtube` | 1920×1080 | as landscape | any | none | −14 |
| `shorts` (YouTube Shorts) | 1080×1920 | x 60–880, y 288–1248 | 15–180 s (30–60) | 250 MB | −14 |
| `douyin` (抖音) | 1080×1920 | x 120–880, y 240–1460 | 20–90 s (45–75) | 80 MB | −10 |
| `douyin-long` | 1080×1920 | as douyin | 60–300 s (90–180) | 250 MB | −10 |
| `tiktok` | 1080×1920 | x 120–880, y 240–1460 | 15–180 s (30–75) | 250 MB | −14 |
| `reels` (Instagram) | 1080×1920 | x 66–950, y 270–1248 | 3–180 s (15–60) | 300 MB | −14 |
| `bilibili` (哔哩哔哩) | 1920×1080 | x 96–1824, y 54–1000 | any (180–900) | none | −14 |
| `bilibili-story` (竖屏) | 1080×1920 | x 120–880, y 300–1400 | ≤ 600 s (30–90) | none | −14 |
| `xiaohongshu` (小红书) | 1080×1920 | x 120–960, y 240–1480 | ≤ 300 s (30–90) | 1000 MB | −14 |
| `channels` (视频号) | 1080×1920 | x 120–960, y 200–1500 | ≤ 3600 s (60–180) | 2000 MB | −14 |

All run at 30 fps with a true peak of −1 dBTP. On the generic canvases (`landscape`, `vertical`, `square`,
`portrait`) and `youtube` the safe area is a title-safe margin; on the other platform profiles it is where the
phone's UI (status bar, button rail, title and music) does not cover the picture and a tall phone does not crop it
(Bilibili, Xiaohongshu and Channels publish no template: theirs are conservative). Every platform profile requires
sound; all but `youtube` refuse a stretch over 5 s where nothing moves and treat frame 0 as the cover. The target is
advice, checked only when the owner's `rules.json` sets advice `"target_s": true`: a length the brief gives wins
inside the caps (say in `handover.md` that it is off the target). Backgrounds may bleed to the edges; **words must
stay inside the safe area**: render measures the film and refuses text outside it.

**A platform profile brings a playbook** (`docs/platforms/<name>.md`), which `manual(project)` appends: the frame,
the first seconds, pace, words, sound, what to hand over and what gets a film limited there. Where the playbook and
the general chapters here differ, the playbook wins for that film.

The owner may define other canvases (workspace.json `profiles`, or an inline `"profile": {"base": "douyin", "fps":
25}`); `new_project(p, canvas="1920x1080@25")` makes one (NTSC rates such as 29.97 work: editor-spec §15.1). Pixel
sizes in this manual (28 px text, 40 px evidence) are for a 1080 px short side; the checks scale them with the canvas.

**One project, one canvas, one film.** A project renders one mp4 (h264/aac). For the same edit on another canvas:
`new_project(p2, profile="vertical", from_project=p1)`. It brings the first project's assets and voice (hard-linked
on one drive), tracks, markers, chapters, meta, theme, `duration` and every other top-level key, its locale unless
you give `locale`, and maps every pixel box and x/y/w/h keyframe from the old safe area to the new one (`"full"`
and `"safe"` stay). Text sizes stay as they were, and a wide layout squeezed into a tall one is rarely right as it
lands: `preview` every scene and re-lay what needs it. Other formats (webm, GIF, ProRes, audio only, a transparent
overlay) are not made here.

**Locale**: project.json `"locale"` (else workspace.json's, else `en`) is the film's language as a BCP-47 tag
(`en`, `en-GB`, `zh-CN`, `ja`). It sets how captions are cut, capture's browser language, the words components add
(EvidenceCard's `Source: `) and `speak`'s default voice, which reads English and Chinese; for another language the
owner sets `providers.tts.voice`, and `speak` says so.

**Captions** (when the project has a captions track) sit in the profile's captions band, the bottom 200 px of the
safe area (landscape y 826–1026, douyin y 1260–1460), 36–66 px white on a dark plate (a stroke instead: track
`style` `{"bg": null, "stroke": {"color": "night", "width": 6}}`), one line, or more when a phrase does not fit one
line at 36 px. Keep other words above the band while captions show, or give the captions track its own `box`.

## The project

```
<workspace>/workspace.json        profile, locale, theme, providers, budget, profiles, fonts, watch, runner
<workspace>/rules.json            the owner's hard rules and advice
<workspace>/library/components/   your own components (persist across projects)   library/NOTES.md  your notes
<workspace>/library/fonts/        the owner's fonts: a text `font` may name a family there (the file name)
<workspace>/projects/<name>/      project.json  script.md  voice/  assets/  build/ (previews)  out/film.mp4
```

You may edit `project.json` with your file tools; every tool reads it fresh and validates it. `edit` is safer:
atomic, validated and undoable (a hand edit is not a batch: the next `undo` discards it too).

Tracks are listed bottom to top. Clips on one track must not overlap: layer with more tracks. A complete example,
a narrated explainer on `landscape` that opens on its verdict (boxes for 1920×1080; captions use the band at
y 826–1026, so the other words stay above it):

```json
{
  "version": 2,
  "profile": "landscape",
  "locale": "en",
  "meta": {"title": "One T-shirt drinks 2,700 litres of water", "desc": "The water behind one cotton T-shirt",
           "topic": "water used from the cotton field to a finished T-shirt",
           "shape": "verdict first, then the field, the mill and the proof",
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
      {"id": "c2", "type": "video", "asset": "mill", "start": "line:3", "end": "line:5"},
      {"id": "c3", "type": "evidence", "asset": "ev_water", "start": "line:5", "end": "end",
       "box": {"x": 120, "y": 160, "w": 1000, "h": 600}, "highlight": {"at": 0.8}}
    ]},
    {"id": "fg", "kind": "visual", "clips": [
      {"id": "hook", "type": "text", "text": "One T-shirt: **2,700 litres** of water", "start": 0,
       "end": "line:2.end", "box": {"x": 160, "y": 220, "w": 1600, "h": 400},
       "style": {"font": "display", "size": "fit", "max_size": 140, "color": "snow", "stroke": {"color": "night", "width": 8}},
       "keyframes": {"scale": [{"t": 0, "v": 1}, {"t": 2, "v": 1.05, "ease": "inOut"}]}},
      {"id": "n1", "type": "component", "name": "CountUp", "start": "line:3", "dur": 3.5,
       "box": {"x": 1180, "y": 200, "w": 640, "h": 480},
       "props": {"value": 2700, "suffix": "litres", "label": "from the field to the shirt", "at": "line:3+0.3",
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
need two tracks. Words in any language go in the same fields; the `locale` tells reelsmith how to cut the captions.

The narration (`voice`) plays by itself at full volume. The film lasts until the voice ends + 0.6 s unless you set
`"duration"` (without a voice, until its last clip ends). Without a captions track there are no captions.
`"chapters": [{"at": Time, "title": "..."}]` names the film's chapters. `meta` takes only `title`, `desc`, `topic`,
`shape` and `sources`.

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
- Inside a clip (keyframe `t`, `highlight.at`, component props named `at` or `*_at`): **seconds from the clip's
  start**. A clip starting at 10 s with `"at": 0.4` fires at 10.4 s.
- Time strings are the same everywhere: `"at": "line:5+0.3"` fires 0.3 s after line 5 starts, wherever the clip is.

Cut on the narration: start clips at `line:N` and they stay in sync when you re-record the voice. A clip takes
`end` (a Time) or `dur` (seconds). Cycles (`clip:a` timed from `clip:b` timed from `clip:a`) are an error.
`preview` and `describe(at=…)` read Times the same way; there `"clip:c2.end"` shows c2's last frame.

### Clips

Common fields: `id` (1–64 letters, digits, `_`, `-`; clips and tracks share one set of ids; not ending like an
offset, so `c_1`, not `c-1`), `type`, `start`, `end` | `dur`, `box` (`{x,y,w,h}` | `"full"` | `"safe"`, default
full), `opacity`, `rotate` (deg), `scale`, `flip_x` / `flip_y` (mirror the content: selfie footage, a subject that
should face into the frame), `origin` (`"center"`, `"top-left"`, ...), `radius`, `blend` (`"multiply"`,
`"screen"`, ...), `filter` `{blur, brightness, contrast, saturate, grayscale, sepia, invert, hue_rotate}`
(grayscale/sepia/invert 0..1, hue_rotate degrees), `shadow` (true or a CSS shadow), `enter` / `exit` `{"preset":
"fade"|"rise"|"drop"|"pop"|"wipe_left"|"wipe_up"|"zoom", "dur": 0.4}`, `transition` `{"type": "crossfade"|
"dip_black"|"dip_white"|"wipe_left"|"wipe_right"|"wipe_up"|"slide_left"|"zoom", "dur": 0.5}` (in from the clip
before it on the same track: see Editing footage).

`keyframes`: `{"<prop>": [{"t": Time, "v": number, "ease": "linear"|"in"|"out"|"inOut"|"spring"|"step"}]}` for
`x y w h opacity rotate scale zoom pan_x pan_y progress`, the filter props, `focus_x focus_y` on image and video
clips, `volume` on video and audio clips and `rate` on video clips; the ease shapes the move into that keyframe.
`progress` (0..1) drives shapes and components; `volume` replaces the clip's `volume` (0 silent, 1 full).

**Ken Burns** (image and video clips; the content moves inside the box, which crops it):
- `zoom` is a factor around the clip's `focus` point: 1 = the picture as fitted, 1.2 = 20 % closer.
- `pan_x` / `pan_y` move the picture in box pixels (+ right / down). A pan must not uncover the box's edge, so the
  renderer zooms in just enough for the widest pan you keyframe; to choose the zoom yourself, keep a pan within
  (zoom − 1) × box width ÷ 2 (height for `pan_y`): zoom 1.2 in an 840 px box allows ±84 px.
- `focus` `[fx, fy]` (0..1, default centre) picks what `cover` keeps when the picture's shape differs from the box,
  and is where `zoom` closes in: 0 shows the left edge, 1 the right edge.
- `focus_x` / `focus_y` keyframes move that point: **reframing**. Landscape footage on a vertical canvas shows a
  third of its width; to follow a speaker, find their x as a fraction of the picture width (`frames`, `scenes`) and
  keyframe `focus_x` there, e.g. `[{"t": 0, "v": 0.3}, {"t": 4, "v": 0.3}, {"t": 4.6, "v": 0.7, "ease": "inOut"}]`
  (the exact centring formula: editor-spec §3.4). `pan_x`/`pan_y` never reveal what `cover` cropped.
- `motion` is shorthand: `push` (zoom 1.02 → 1.12), `pull` (1.12 → 1.02), `pan_left`/`pan_right` (zoom 1.14,
  pan ±3.4 % of the box), `rise` (zoom 1.1, pan_y ±2.2 %), `still`. Keyframes on the same property win.

| type | fields |
|---|---|
| `image` | `asset`, `fit` `"cover"`/`"contain"`, `focus` `[fx, fy]`, `motion`; an animated GIF, APNG or WebP plays and loops |
| `video` | `asset`, `trim_in` (source seconds skipped), `rate` (2 = twice as fast), `loop`, `fit`, `focus`, `motion`, `volume` (default 0: muted), `reverse`, `hold` (a source second shown throughout: a freeze frame) |
| `text` | `text` (`**word**` = accent colour), `style` (TextStyle), `reveal` `{"mode", "dur"}` |
| `shape` | `shape` `"rect"|"ellipse"|"line"|"arrow"|"path"`, `fill`, `stroke`, `stroke_width`, `d` (SVG path in box pixels), `draw` (the stroke draws on) |
| `evidence` | `asset` (kind evidence): the capture's box (the proving sentence) scaled to the clip's width (at most 2×), with a little page above and below; the panel hugs that content and cut edges fade out; `highlight` `{"at", "dur", "color"}` sweeps the sentence |
| `component` | `name`, `props` (checked against the component's schema; see `library`) |
| `audio` (audio tracks) | `asset`, `trim_in`, `volume`, `fade_in`, `fade_out`, `loop` (repeat the file to fill the clip), `keyframes` (`volume` only), `transition` (`crossfade` only), `duck` `{"under": "<track id>" or "voice", "to": 0.25, "fade": 0.3}` |

**Text.** TextStyle: `font`, `size` px or `"fit"`, `max_size` 160, `min_size` 28 (defaults scale with the canvas),
`weight` 100–900, `color` (default `snow` with a soft shadow, for pictures and dark grounds: **on paper set
`ink`**), `accent`, `align`, `valign`, `line_height` 1.15, `letter_spacing`, `wrap`, `balance` (exactly two even
lines), `stroke` `{color, width}`, `shadow`, `bg` `{color, radius, pad}` (a plate behind the text). A text clip
without a style is 64 px, weight 700, at the top left of its box: give headlines a style.
- `"fit"` is the largest size (between `min_size` and `max_size`) at which the text fits the box, on as many lines
  as that takes. Lines break between words, never inside a number or before closing punctuation; your `\n` breaks
  are kept. Cap headlines with `max_size`.
- Fonts: `sans` (Noto Sans SC, the default: body, numbers, captions; covers Latin too), `serif` (Noto Serif SC:
  quotes, a calmer voice), `display` (Smiley Sans 得意黑, a bold oblique: headlines and verdicts), `zcool` (ZCOOL
  QingKe HuangYou, decorative: some characters such as 水 多 算 read oddly, so only short titles you have previewed),
  and any family in the workspace's `library/fonts/` (`Brand Sans.woff2` is `"font": "Brand Sans"`).
- `reveal` modes: `chars`, `words`, `lines` (as laid out on screen), `none`; `dur` is the whole reveal (default 0.8).

**Shapes.** `rect` and `ellipse` fill the box. `line` and `arrow` without `d` run corner to corner: give `d`, e.g.
`"M0 70 L460 70"` for a level arrow across a 460×140 box. Lines and arrows are drawn by their stroke (with only
`fill`, in that colour; with neither, in `accent`); `stroke_width` defaults to 6. `draw: true` draws the stroke on
over 0.6 s, or along `progress` keyframes.

**Colours.** Every colour field takes a theme token or any CSS colour. The default theme `paper`:

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

**Captions track:** `{"id", "kind": "captions", "source": "voice", "box"?, "style"?, "emphasis": [words],
"max_chars"?, "overrides": [{"line": 5, "text": "..."}], "items"?: [{"start", "end", "text"}], "mode"?,
"language"?}`: phrase-split between words (never inside a word or a number) and timed from the voice lines unless
you give `items` (then `source` is ignored: a film without a voice gives `items` alone), each shown whole from its
`start` to its `end`. `max_chars` (4–60) defaults to 14 for Chinese, Japanese and Korean and 32 for other languages.
Phrases drop the punctuation they were cut at; fix a bad split with an override that adds a comma where the cut
should be. `emphasis` words are drawn in the captions' accent colour (gold unless the track's `style` sets
`accent`). `"mode"`: `"phrase"` (default) shows each phrase whole, `"words"` lights each word in that colour as it
is said (karaoke; `emphasis` is not shown then), `"build"` adds the words one by one. `"source": "clip:a"` captions
what clip `a` says, from its asset's transcript, with word times; in `words` and `build` modes the words of voice
lines and `items` are spread by characters. `language` (default the locale) labels the subtitle files.

## Edit ops

`edit(project, ops)` applies a list of ops as one batch: all apply and add no validation error, or nothing changes
(errors the project already had do not block a batch). `undo(steps=N)` reverts batches; `redo` is one level: it puts
back what the last undo took (all N as one batch), and any later edit clears it.

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
{"op": "set", "path": "meta.title", "value": "One T-shirt drinks 2,700 litres of water"}
{"op": "ripple_delete", "start": "src:a@12.3", "end": "src:a@13.9"}
{"op": "insert_gap", "at": "clip:a2", "dur": 1.5, "tracks": ["v1"]}
{"op": "trim_clip", "id": "a", "in": 4.2, "out": 31, "ripple": true}
```

- `set` replaces the value at a dotted path (not inside `tracks` or `assets`). `update_*` deep-merge; `null`
  removes a key. Setting `end` drops `dur` and the other way round; `move_clip` with only `start` keeps the length.
- Renaming a clip with `update_clip` retargets every Time and captions `source` naming it; renaming a track
  retargets the ducks under it. `update_asset` cannot change an id, nor the kind of an asset in use.
- `add_asset` with an existing id replaces that asset. An asset still used by a clip (directly or through component
  props) cannot be removed; removing a clip others are timed from leaves them where they were (their anchors on it
  become numbers).
- The last three are ripple edits for footage (next sections). `trim_clip` on a clip that is not media takes Times
  for its new start and end.

## Making a film people watch

These are floors of craft, not a formula for views: what brings views is mostly the subject. Each rule says why;
the platform's playbook may tighten them.

- Open on the point. The first spoken line and the first screen state the verdict, or what it means for the viewer,
  as a statement: a spoken question as the first line loses viewers before the answer comes. A title may ask; the
  voice answers.
- Give the takeaway within about 15 s: most viewers of a short leave within the first seconds, so what they should
  keep comes first and story and proof follow.
- The picture shows what the words say: the story's own subject doing the thing (the phone being flexed, the
  passenger in the vestibule), not a prop beside it (a payslip on a desk), because the viewer judges from the
  picture whether the film is about something.
- Something changes every 2–4 s (a cut, a re-crop, a card's next item): a picture held 8–10 s reads as a slideshow.
  Get more from a short clip by re-cropping it (a closer `zoom` with another `focus`, another pan, `flip_x`, a
  different `rate`) between other shots; played forward then backward it reads as a loop. Words over a still
  picture all the way are slides: `animate` the pictures that fill the frame (say in `motion` who moves and how) and
  tell the story with the scene presets (Components) between shots.
- Footage stays at full brightness. Words hold on a picture by their own stroke, shadow or plate (`bg`), or on a
  card with its own ground; never dim the picture to make a card read, which leaves the whole film murky.
- Type large enough for a phone: 40 px or more for anything to be read, headlines far larger. A card fills the box
  you give it: a small card in a big box is small type.
- The screen adds to the voice (a number, a name, a source, the thing itself). Big text repeating the narration above
  captions that repeat it again says one sentence three times and shows nothing.
- End on something the viewer can use (what to check, do or expect), not a recap of what they just heard.
- A generated face never stands for a named real person: use their real photo or footage with its source, or no
  face. No flags, emblems, uniforms, slogans or lit signs and screens with writing in generated pictures: they come
  out wrong (the models scramble writing) or read as a claim nobody made.
- Without a voice the captions are the narration: the frame-0 headline is line 1, the caption items start after it
  and each is a line that would have been spoken. `review` then lists no lines: read the captions off its sheets.

## Editing footage

A recording of your own, or a clip you downloaded, is a source: look at it, cut it on the timeline, caption it.
The footage tools speak **source seconds**; `"src:a@41.2"` is the moment clip `a` plays second 41.2 of its source,
so you cut straight from what you found. A film of footage needs no `speak`; without a voice it lasts until its last
clip ends (or `duration`).

1. `import_asset` the file (any size: on the project's drive it is hard-linked, the same file as its source, so a
   program rewriting the source in place changes the asset: write a new file and import it over the same id), then
   `probe` it: length, resolution, fps, rotation, colour, sound and loudness. HDR is flagged (not tone-mapped).
2. Look before you cut. `frames(p, "talk", n=12)` (or `times`, or `every`) gives stills at source times and a
   contact sheet with each time burned in: Read it. `scenes` lists the shot cuts with each shot's first frame,
   `silences` the quiet ranges and the sound between them, and `transcribe` writes every word with its time
   (`assets/talk.transcript.json`).
3. Lay it down: `{"id": "a", "type": "video", "asset": "talk", "start": 0, "end": "src:a@95", "volume": 1}` runs
   until source second 95. `trim_in` skips the head, `rate` speeds it up; give video `volume` 1 to hear it.
4. Cut. `ripple_delete` takes a range out and closes the gap: a clip crossing its edges is split (the part after
   continues as `a_2`, `a_3`, ...: read the pieces in the result), and later clips, markers, chapters and caption
   items move up. Jump cuts from `silences`: one `ripple_delete` per silence from `"src:a@<start + 0.1>"` to
   `"src:a@<end - 0.1>"`, all in one batch, in any order (a `src:a@...` that a cut left to a later piece names that
   piece). Name the tracks to cut (`"tracks": ["v1"]`, plus its sound's track and a captions track with `items`):
   left out, every track is cut, a music bed included. `trim_clip` sets a clip's in/out in source seconds (`ripple:
   true` pulls the rest of its track along), `insert_gap` opens room, `split_clip` cuts a clip in two. Anchors that
   stay true after a ripple edit stay; the rest become numbers.
5. Join shots: give the later clip `"transition": {"type": "crossfade", "dur": 0.4}` and start it that long before
   the previous one ends (`"start": "clip:a.end-0.4"`); that is the only overlap a track allows. Without the
   overlap it transitions in over whatever is beneath it. A clip with sound crossfades its sound too.
6. Sound: `volume` keyframes ride a clip's level (`{"t": 3, "v": 0.2}`); a music bed with `"duck": {"under": "v1"}`
   (or `"voice"`) drops to 0.25 while that track's clips with sound play, easing 0.3 s either side.
7. Captions that follow the speech: a captions track with `"source": "clip:a"` once `talk` is transcribed. It
   follows every piece of that recording on `a`'s track, drops the words you cut, and phrases by pauses and sentence
   ends, then within `max_chars`.
8. Name moments you will come back to: `"markers": {"punch": "src:a@41.2"}`, then `"mark:punch"` wherever a Time
   goes; markers and chapters move with ripple edits.
9. Speed ramps (`rate` keyframes), freeze frames (`hold`) and `reverse` go on a piece of their own, after the cuts
   that use `src:` on it; such a piece is silent and takes no `src:`, transcript captions or `trim_clip`
   (editor-spec §3.4).
10. `describe` to see the cut as text, `preview` the joins and the captions, `render(p, draft=true, start=...,
    end=...)` to watch a join or a stretch as video, then `render`.

A complete example: a talk recorded in one take on `landscape`, with a pause cut out (the pieces `a` and `a_2`),
b-roll over it, a title, a music bed that ducks under the talk and captions from the transcript. No narration: the
film lasts until `a_2` ends.

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

## Components

A component clip renders a React component inside the clip box. Built-in presets: `Receipt`, `Stamp`, `CountUp`,
`BarCompare`, `TimelineRule`, `DotGrid`, `EvidenceCard`, `Highlighter`, `Arrow`; `library(project)` lists them with
their prop names, `library(project, "Receipt")` shows the schema, an example and the source file.

Six presets are whole scenes for telling what happened. Each fills a large box (about 800 × 800), lands its parts
at their own `at`, keeps moving gently while it holds, and reads on its own `light` or `dark` `ground`, or over a
picture at full brightness (never dim footage to make a card read):

| preset | the scene | reach for it when |
|---|---|---|
| `Parties` | 2–4 parties as cards, arrows with labels between them, coins or people flowing along a link, a link that can be cut | the story is who pays whom, who took whose customers, who stopped paying |
| `QuoteCard` | a speaker plate (silhouette, name, role) and the quote revealed phrase by phrase, hot words marked | a scene is about what someone said |
| `NewsBrief` | a source and date pill, your one-line retelling as the headline, up to three facts landing one by one | a scene says what a report found |
| `Versus` | two versions side by side; one can be struck out, the other lifted | the beat is a contrast or a correction: the claim and the record |
| `StoryBeats` | 3–5 events on a rail, the newest large, earlier ones folded small | the voice tells what happened next, one step at a time |
| `Seesaw` | chips dropping onto two plates, the beam tipping to the heavier side, a verdict under it | one event has winners and losers |

In props, any key named `at` or ending in `_at` takes a Time and arrives in the component as **frames from the
clip's start**; any key named `asset` or ending in `_asset` takes an asset id and arrives as `{src, kind, size?,
box?, site?, duration?}`, at any depth.

**Writing your own**: put `Name.tsx` and `Name.meta.json` in `<workspace>/library/components/`; they persist, every
project can use them, and one shadows a preset of the same name. The kit and a complete component are in
[docs/kit.md](kit.md) (`library` prints its path); the starter workspace's sample and every preset's source are
worked examples. Imports allowed: `react`, `remotion`, `@remotion/*`, `@reelsmith/kit` and files in the same folder.
Lay yourself out in `useClip()`'s `w × h`; text of 40 px or more at a 1080 px short side (the layout check warns
under 28 px, render refuses under 20 px); the words a component adds follow `useClip().locale`; animate from the
frame, never from time or randomness; give SVG ids `React.useId()`. Then `typecheck` and `preview` a moment where it
shows. A component that crashes shows a red box in previews and is reported first, with its source line.

## Tools

| tool | what it does | example |
|---|---|---|
| `manual(project?)` | this manual; with a project, followed by its platform's playbook | `manual(p)` |
| `notes(project)` | your workspace notes | `notes("/home/me/studio/projects/tshirt")` |
| `note(project, text)` | append a dated lesson at the end of the notes (to file it under a heading, edit `library/NOTES.md`) | `note(p, "evidence: match one 8-20 character line, not a paragraph")` |
| `new_project(project, profile?, title?, canvas?, locale?, from_project?)` | create a project folder; `canvas` `"WxH"` or `"WxH@fps"`; `from_project` puts another project's film on this canvas; the result names the profile's playbook | `new_project("/home/me/studio/projects/tshirt", profile="douyin", locale="zh-CN")` |
| `describe(project, at?)` | the editor's window as text; with `at`, what is on screen then | `describe(p, at="line:4")` |
| `edit(project, ops)` | apply a batch of ops atomically | `edit(p, [{"op": "remove_clip", "id": "arrow"}])` |
| `undo(project, steps=1)` / `redo(project)` | undo applied batches (an asset registration is one too) / put the last undo back | `undo(p)` |
| `check(project)` | errors (block render), warnings, advice | `check(p)` |
| `library(project, name?)` | components with their prop names; with a name, schema, example and source | `library(p, "Receipt")` |
| `typecheck(project)` | type-check your own components | `typecheck(p)` |
| `speak(project, lines, gap_s=0.22)` | narrate; one item per line, a string or `{text, pace, emotion}` | `speak(p, ["A T-shirt drinks 2,700 litres.", {"text": "Most of it in the field.", "pace": 0.9}])` |
| `capture(project, url, id, match?, viewport?)` | screenshot of a page as evidence, boxed around `match`; `viewport` `phone` or `desktop` (default: phone on a tall canvas, desktop on a wide or square one) | `capture(p, "https://...", "ev_water", "about 2,700 litres")` |
| `draw(project, id, prompt, style_ref_asset?, size?)` | an original picture | `draw(p, "field", "a cotton field at dawn, photo", size="16:9")` |
| `animate(project, id, image_asset, motion, seconds=4, camera?)` | a 2–12 s silent clip from a 9:16, 1:1 or 16:9 picture; `camera` default `push` | `animate(p, "field_v", "field", "the cotton bolls sway in the wind", 4, "push")` |
| `import_asset(project, id, source, kind?)` | copy a file or download a URL (at most `providers.import.max_mb`, default 200 MB) into assets | `import_asset(p, "bed", "/home/me/music/bed.m4a", "audio")` |
| `assets(project)` | assets with kinds, sizes, durations, spend | `assets(p)` |
| `probe(project, source)` | a source's streams, codecs, rotation and loudness | `probe(p, "talk")` |
| `frames(project, asset, times?, every?, n=12)` | stills of a source at source seconds (at most 24) + a timed contact sheet | `frames(p, "talk", ["0:12", 41.2])` |
| `scenes(project, asset, threshold=0.3)` | shot cuts (source seconds) + each shot's first frame | `scenes(p, "trip")` |
| `silences(project, asset, min_s=0.5, noise_db=-35)` | quiet ranges and the sound between them (source seconds) | `silences(p, "talk", 0.4)` |
| `transcribe(project, asset, language?, prompt?)` | every word said, with its source time, into `assets/<id>.transcript.json` | `transcribe(p, "talk", "en", "Ada Lovelace, reelsmith")` |
| `preview(project, times?, sweep?)` | stills at up to 24 moments + contact sheet + layout problems; `sweep` measures the whole film | `preview(p, [0, "line:3", "clip:n1+1", "end-1"])`, `preview(p, sweep=true)` |
| `render(project, draft?, start?, end?, scale?)` | the film to `out/film.mp4`, mastered and checked; `draft=true` a quick small look to `build/draft.mp4` | `render(p)`, `render(p, draft=true, start="clip:b-2", end="clip:b+3")` |
| `review(project, n?, every?)` | the delivered film a frame a second (spread out past 150 frames) on phone-size sheets, with the voice line heard at each frame and the still stretches | `review(p)`, `review(p, n=12)` |
| `export_captions(project, track?)` | captions as `.srt` and `.vtt` without rendering | `export_captions(p)` |

- `speak` writes the whole narration from the lines you give it: **always pass every line**, changed or not;
  unchanged lines come from the cache and cost nothing. At most 200 lines of 400 characters, `gap_s` 0–1.5. `pace`
  is a factor (0.5–2) or `"slower"`/`"normal"`/`"faster"`; the default voice has three speeds (under 0.944 slow,
  up to 1.04 normal, above fast), so 0.95 and 1.0 sound the same. `emotion` is a word or two (≤ 20 characters,
  `"calm"`) given to the voice as an instruction: listen before relying on it. Write the lines in the film's
  language (`"一件T恤，要喝2700升水。"` in a `zh-CN` film).
- `draw`: `size` is an aspect (`9:16`, `2:3`, `3:4`, `4:5`, `1:1`, `4:3`, `3:2`, `16:9`; default the one nearest
  your canvas) or pixels `"WxH"` (sides 256–4096).
- `speak`, `animate` and `transcribe` cost money (transcribe is free with the owner's local model) and `draw` spends
  limited tries: they estimate first and refuse when the project budget, the account floor or the tries would be
  crossed. Transcribing the same recording again with the same settings is free.
- Evidence captures are the strongest proof you have: match a short exact phrase that sits on one line of the page
  (8–20 characters); a box over two lines or a wide paragraph comes out too small to read (`check` warns under
  40 px). Re-box an evidence asset with `update_asset`.
- Music: there is no music generator. `import_asset` an audio file you are allowed to use (a bed made with ffmpeg's
  `sine` or `anoisesrc` will do), on an audio track at a low `volume` (0.08–0.15) with `"loop": true` if it is
  shorter than the film. Without a voice, mastering brings the whole mix to the profile's loudness: a lone bed comes
  to the front whatever its `volume` (which sets only its balance against other sound), so pick one meant to be heard.
- `preview` is cheap (a few seconds a still): use it after every meaningful edit and look at the PNGs. In the
  contact sheet the dark bands are outside the safe area, the yellow line is its edge and each tile shows its time;
  earlier stills stay in `build/stills`. `sweep=true` measures the film exactly as `render` does: run it first.
- Drafts: `render(p, draft=true)` renders at half size with a fast encode to `build/draft.mp4`, without mastering,
  the layout pass or the delivery checks (the project must still validate); `start`/`end` (Times) render a stretch
  and `scale` (0.1–1) sets the size.

## What blocks delivery

`render` stops, and keeps the previous `out/film.mp4`, at the first stage that fails:

1. **check errors**: the project does not validate (unknown ids, missing files, overlaps on a track, bad Times, an
   unknown font, a clip id ending like an offset, a video or audio clip whose `trim_in` is at or past its source's
   end...); the owner's hard rules from `rules.json` (for example a title of at most 24 characters, at least 1
   source with an http(s) url, no banned words); the length outside the profile's limits; an evidence panel leaving
   the safe area; more than 10 % of the film with nothing on screen (black); on a profile with a stillness limit,
   a stretch over 5 s where nothing can move (move something: keyframes, `motion`, a reveal, a video).
2. **layout** (a still every second, spread to 600 stills past 10 minutes, plus one in each text and caption between
   them; `preview` with `sweep` runs the same pass, and render reuses it when nothing it reads changed): visible
   text outside the safe area or cut by the canvas edge, text under 20 px, a component that crashes. Text during
   its enter/exit animation and text fainter than 10 % opacity are not counted.
3. **the film**: the profile's size and fps, h264/aac, length and size within the profile's limits, black ≤ 10 %;
   a profile that requires sound refuses a silent film, one with a stillness limit any measured 5 s without motion.

The report lists what failed with clip ids and times (`hook @ 1.0s`): fix those, `preview` them, render again. A
rejected film is kept at `build/film.rejected.mp4` to look at; a film a player holds open stops at stage "deliver"
with the finished file in `build/`. `build/report.json` is the latest attempt, `out/report.json` the delivered film's.

**Warnings** (information; take them seriously): text under 28 px; text over other text (captions included); text
on a background of about its own brightness; text overflowing its clip box or cut by a component's own card;
evidence that will read under 40 px; on platform profiles (or with `rules.json` `hook_seconds`) words not whole on
frame 0, the cover, or no words there; a hole of 0.5 s or more with nothing on screen; a video or audio clip that
runs past its source's end (a frozen last frame or silence); footage with sound in a film where nothing is heard
(video `volume` defaults to 0); a `src:` Time past what its clip plays; an HDR source. **Advice** is only what
the owner's `rules.json` asks for (no words in the first 2 s, a still held over 8 s, a length outside the target).

**Handing over.** A delivered render writes `out/film.mp4`, `out/meta.json` (title, desc, sources, duration,
profile, captions, chapters) for publishing, every captions track (hidden ones too) as `out/captions/<track>.srt`
and `.vtt`, and project `chapters` as `out/chapters.txt` and mp4 chapter marks (YouTube shows them when the first
is at 0:00, there are at least 3 and each lasts 10 s or more). Put `meta.title`, `meta.desc` and `meta.sources` in
project.json; everything else the playbook asks to hand over (declarations such as AI-generated content, the
collection, a pinned comment) goes in `handover.md` beside project.json, since `meta` takes nothing else. A cover is
frame 0 of the film, cut beside it: `ffmpeg -i out/film.mp4 -frames:v 1 [-vf <playbook's crop>] cover.png`.
