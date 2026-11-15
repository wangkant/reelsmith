# @reelsmith/kit

Everything a component may import from `@reelsmith/kit`, how its props arrive, and a complete component to start
from. The source is `renderer/src/kit/` (`index.ts` lists the exports, `helpers.ts` holds most of them); the built-in
presets in `renderer/src/presets/` are fuller examples (`library(p, "Receipt")` prints a preset's source path). The
stage kit for performance films is the last chapter.

## A component

`<workspace>/library/components/Name.tsx` (default export) plus `Name.meta.json` (`name`, a one-line `description`,
`props` as a JSON Schema, an `example`). Every project can use it; a library component shadows a preset of the same
name. Check it with `typecheck(p)`, then `preview(p, [...])` a moment where it shows.

- **Imports allowed**: `react`, `remotion`, `@remotion/*` packages that are installed (`@remotion/paths`,
  `@remotion/layout-utils`, `@remotion/media`), `@reelsmith/kit`, and files in the same folder. Anything else (node
  builtins, other packages, absolute paths) is refused when the film is bundled.
- **Where it draws**: inside an absolutely positioned div the size of the clip box, `w × h` from `useClip()`. Lay
  yourself out in that box; text outside it is reported. Clip keyframes (`x`, `scale`, `opacity`...) move the box from
  outside; keyframed `w`/`h` reach you as the current `w`/`h`.
- **Time**: animate from `useCurrentFrame()` (frames from the clip's start) only. No `Date`, no `Math.random`: use
  remotion's `random(seed)` for noise. Every frame is rendered on its own, in any order.
- **Text**: draw it as HTML (`div`/`span`), so the layout check can measure it; size it to the box with `fit` and
  aim for 40 px or more at a 1080 px short side, `Math.min(width, height) / 1080` times that on other canvases
  (the layout check warns under 28 px and render refuses under 20 px, scaled the same way). Use
  `whiteSpace: "pre"` for text you have fitted, so the browser does not wrap it again.
- **SVG ids** (`clipPath`, `mask`, gradients) are global to the page: two copies of a component on screen share them
  unless each instance makes its own. Use React's `useId()`:
  `const gid = "g" + useId().replace(/[^A-Za-z0-9_-]/g, "")`, then `id={gid}` and `url(#${gid})`.
- **Errors**: a component that throws fails `render`; `preview` draws a red box in its place and reports the error.

## How props arrive

Props are exactly what the clip's `props` say in project.json (meta.json defaults are not filled in: use the `*Or`
helpers with your default), except two kinds of key, at any depth (arrays and nested objects too):

| key | in project.json | in the component |
|---|---|---|
| `at`, `*_at` | a Time: `"line:8"`, `"line:8+0.4"`, `"clip:x.end-1"`, `"end"` (film times), or a number = **seconds from the clip's start** | a number: **frames from the clip's start** (negative = before it). A Time that cannot be read arrives unchanged (a string), so `frameOr(props.at, 0)` falls back |
| `asset`, `*_asset` | an asset id | `{src, kind, size?, box?, site?, duration?, animated?}`; an unknown id arrives as the string |

The asset ref: `src` a project-relative path (give it to `assetSrc` or `Media`), `kind` `"image" | "video" | "audio" |
"evidence"`, `size` `[w, h]` pixels (images and evidence), `box` `[x, y, w, h]` the proving sentence in capture
pixels (evidence; phone captures are 3× the page, desktop ones 2×), `site` the page's site (evidence), `duration`
seconds (video, audio), `animated` true for a GIF, APNG or WebP that moves (`Media` plays it; an `<Img>` would hold
its first frame).

## useClip()

`const { w, h, dur, fps, theme, width, height, safe, locale, progress, lines } = useClip();`

| field | |
|---|---|
| `w`, `h` | the clip box now, in canvas px (keyframed `w`/`h` included) |
| `dur` | the clip's length in frames |
| `fps` | frames per second (the profile's; 30 unless it says otherwise) |
| `theme` | the theme's colours: `paper`, `ink`, `night`, `snow`, `accent`, `gold`, `good`, `bad`, `muted` (CSS hex) |
| `width`, `height` | the canvas (1920 × 1080 on the default `landscape` profile, 1080 × 1920 on the vertical ones) |
| `safe` | the safe area `{x, y, w, h}` in canvas px (the platform's UI-safe area, or a title-safe margin) |
| `locale` | the film's language, the project's BCP-47 `locale` (`"en"` by default, `"zh-CN"`, `"ja"`...): pick the words a component adds itself by it, as `EvidenceCard` does for its source line (`Source: ` / `来源：`) |
| `progress` | 0..1: the clip's `progress` keyframes if it has them, else how far through the clip it is |
| `lines` | the voice lines heard during the clip, in time order, as `ClipLine[]`; `[]` without a voice (below) |

`lines` lets a component time itself to the narration instead of to typed seconds. Each line that overlaps the clip
arrives as `{i, text, from, to}`: `i` the line's number (as in `line:N`), `text` its words without markup, `from` and
`to` the frames where it starts and ends, counted from the clip's start like `useCurrentFrame()`. A line that began
before the clip has a negative `from`; one that runs on after it has `to` past `dur`. A line that ends exactly where
the clip starts, or starts exactly where it ends, is not included. The numbers come from `voice/voice.json` through
`resolve`, so a re-recorded voice moves every cue with it.

```ts
type ClipLine = { i: number; text: string; from: number; to: number };
```

Theme tokens: `paper` light ground, `ink` text on paper, `night` dark ground, `snow` text on night, `accent` the one
number that matters, `gold` highlights, `good` / `bad` gains and losses, `muted` secondary text. The default theme
`paper` is `#F3EBDD #1E1A16 #16130F #F7F1E6 #C8372D #D9A441 #2E8B57 #C8372D #7A6F62` in that order. Props that take a
colour usually accept a token name or CSS: resolve them with `themeColor`.

## Exports

### Timing

| export | | example |
|---|---|---|
| `ease(f, a, b, from = 0, to = 1)` | frames `a..b` mapped to `from..to` on an ease-out curve, held at both ends (`b <= a`: a step at `a`) | `const t = ease(f, at, at + 20)` |
| `springAt(f, at, {fps, damping?, stiffness?, mass?, durationInFrames?})` | a 0 → 1 spring starting at frame `at` (0 before); damping 200 = no overshoot | `springAt(f, at, { fps, damping: 12 })` |
| `clamp` | `interpolate` options that hold both ends | `interpolate(f, [0, 30], [0, 1], clamp)` |
| `toFrames(seconds, fps)` | seconds to frames (rounded) | `toFrames(numOr(props.dur, 0.8), fps)` |
| `spread(n, a, b)` | `n` frames evenly from `a` to `b` (one item: `[a]`) | `spread(rows.length, 8, dur * 0.6)` |

### Props

| export | | example |
|---|---|---|
| `numOr(value, fallback)` | a finite number, or the fallback | `numOr(props.total, 10)` |
| `frameOr(value, fallback)` | a Time prop (frames from the clip start), or the fallback | `frameOr(props.at, 0)` |
| `isAsset(value)` | true for an asset ref (`{src, ...}`) | `if (!isAsset(props.asset)) return null` |
| `assetSrc(ref \| src)` | URL to give `<Img>` / `<OffthreadVideo>` | `<Img src={assetSrc(props.photo_asset)} />` |

### Text

| export | | example |
|---|---|---|
| `FONTS` | CSS font-families: `sans` Noto Sans SC (weights 100–900: body, numbers), `serif` Noto Serif SC (200–900: quotes), `display` 得意黑 Smiley Sans (one weight, oblique: headlines, verdicts), `zcool` ZCOOL QingKe HuangYou (one weight; loud, some glyphs hard to read) | `fontFamily: FONTS.sans` |
| `fontFamily(name)` | a `FONTS` key to its CSS family; a family of the workspace's fonts (`library/fonts`) to that family with the sans as fallback; anything else passes through (empty: sans) | `fontFamily(props.font)` |
| `fit(text, width, max, family = "sans", weight = 400)` | the largest font size ≤ `max` at which `text` fits `width` on one line | `fit(label, w * 0.9, 64, FONTS.sans, 800)` |
| `fitLines(text, width, max, min = 0, family = "sans", weight = 400)` | `{size, lines}`: one line, or two (`twoLines`) when one line would be under `min` and two fit larger; render `lines.join("\n")` with `whiteSpace: "pre"` | `const { size, lines } = fitLines(label, w * 0.6, 56, 28, FONTS.sans, 800)` |
| `fitBlock(text, w, h, {max, min = 0, maxLines = 2, family = "sans", weight = 400, lineHeight = 1.2})` | `{size, lines}` for a `w` x `h` block (options type `BlockOptions`): one line while it fits at `min` or more; else wrapped (`breakLines`, balanced, Han between characters) into up to `maxLines` lines at the largest size ≥ `min` that fits; smaller only when even that fails. Use it for any text that must not shrink under the readable floor (28 px at a 1080 px short side); render `lines.join("\n")` with `whiteSpace: "pre"` and the same `lineHeight` | `const { size, lines } = fitBlock(label, w, h * 0.3, { max: 56, min: (28 * Math.min(width, height)) / 1080, maxLines: 3, weight: 800 })` |
| `textWidth(text, size, family = "sans", weight = 400, tabular = false)` | width in px of one line; `tabular` measures digits as `fontVariantNumeric: "tabular-nums"` | `textWidth(fmt(value), size, FONTS.sans, 900, true)` |
| `twoLines(text, maxOne = 9)` | at most two balanced lines, split where the text clip may break (Intl.Segmenter words: never inside a word, a number, a number and its unit, or before closing punctuation; in CJK text after punctuation when one is near the middle); texts of `maxOne` characters or fewer stay whole | `twoLines("Signed up for the challenge", 4)` → `["Signed up for", "the challenge"]`; `twoLines("报名百日挑战", 4)` → `["报名", "百日挑战"]` |
| `breakLines(text, width, measure, balance = false, han = false)` | `text` in as many lines as it needs at `width`, by the text clip's own rules; `measure(s)` gives a string's width; `balance` evens the lines out; `han` lets Han text break between characters too (as Chinese is set; numbers and Latin words stay whole), taken when it saves a line or keeps a long word inside `width` | `breakLines(note, w, (s) => textWidth(s, 40, FONTS.sans, 700), true)` |
| `words(text)` | word segments (Intl.Segmenter, with Chinese word boundaries), spaces included; joined they give the text | `words("It's 2,700 litres.")` → `["It's", " ", "2,700", " ", "litres", "."]`; `words("今天的天气很好")` → `["今天", "的", "天气", "很好"]` |
| `fmt(value, decimals = 0, grouping = true)` | `"12,345.6"` style number text | `fmt(2700.5, 1)` → `"2,700.5"` |
| `decimalsOf(value)` | decimal places a number is written with (at most 4) | `decimalsOf(8.55)` → `2` |

A number that counts: lay it out once at the width of its final text (`textWidth(..., true)`) with
`fontVariantNumeric: "tabular-nums"`, so it does not shift while digits are added; see the `CountUp` preset.

### Colour

| export | | example |
|---|---|---|
| `themeColor(theme, value, fallback = "accent")` | a token name (`"gold"`) to its colour, other strings as CSS, empty → the fallback token | `themeColor(theme, props.color, "accent")` |
| `onGround(theme, ground)` | text colours for a `"light"` or `"dark"` ground: `{dark, ink, muted, faint}` | `const ink = onGround(theme, props.ground)` |
| `withAlpha(color, a)` | a colour at opacity `a` | `withAlpha(theme.accent, 0.2)` |
| `TOKEN_NAMES` | the nine token names | `TOKEN_NAMES.includes(v)` |

### Pictures

| export | | example |
|---|---|---|
| `Media` | an image or video asset filling its parent, `fit` cover/contain around a `focus`, an optional slow `motion` (`push`, `pull`, `pan_left`, `pan_right`, `rise`, `still`), `dim` 0..1 veil; an animated image ref plays, looping; video: `trimIn` (frames), `rate`, `loop`, `volume`, `volumeKeys` (a volume curve, frames from the clip start), `fadeIn`/`fadeOut` (frames), `hold` (a source frame shown throughout) or `rateKeys` (a speed curve), both silent | `<Media media={props.photo_asset} motion="push" dim={0.3} />` |
| `EvidenceCrop` | the evidence clip's own crop in a `w × h` window: the proving sentence scaled to the window's width (at most 2×) with up to `context` capture px of page above and below, in a panel that hugs that content (centred); where it cuts into the page it fades into `background` (white); optional `highlight` `{at, dur (frames), color}` sweep | `<EvidenceCrop ev={props.asset} w={w} h={300} highlight={{ at: 10, dur: 24 }} />` |
| `evidenceLayout(ev, w, h, context?)` | where `EvidenceCrop` puts things, or null: `s` (capture px → window px), `mark` (the sentence), `panel` (the part of the window the content fills), `fade`, all in window px | `const { panel } = evidenceLayout(ev, w, 400, 120)!` |

### Context and types

`useClip()` (above); `ClipContext` (the React context behind it, for test harnesses); types `ClipCtx`, `ClipLine`, `AssetRef`,
`FontName` (`keyof typeof FONTS`), `Ground` (`"light" | "dark"`), `SpringOptions`, `Tokens`.

## A complete component

A ring that fills to `pct` at `at` with the percentage counting inside and a label under it. It shows a Time prop,
fitted text, theme colours on either ground, and a per-instance SVG id.

```tsx
// library/components/RingStat.tsx: a ring that fills to `pct` from `at`, the percentage counting up inside it.
import { useId } from "react";
import { useCurrentFrame } from "remotion";
import { ease, fit, fmt, FONTS, frameOr, numOr, onGround, themeColor, useClip } from "@reelsmith/kit";

export default function RingStat({ props }: { props: any }) {
  const { w, h, fps, theme } = useClip();
  const f = useCurrentFrame(); // frames from the clip's start
  const gid = "ring" + useId().replace(/[^A-Za-z0-9_-]/g, ""); // unique per instance: two rings never share an id
  const at = frameOr(props.at, 0); // a Time prop arrives as frames from the clip's start
  if (f < at) return null; // nothing before its moment
  const pct = Math.max(0, Math.min(100, numOr(props.pct, 0)));
  const t = ease(f, at, at + Math.round(1.2 * fps)); // 0 -> 1 over 1.2 s, then held
  const ink = onGround(theme, props.ground);
  const color = themeColor(theme, props.color, "accent");
  const label = String(props.label ?? "");
  const labelSize = label ? fit(label, w * 0.9, Math.min(64, h * 0.12), FONTS.sans, 800) : 0;
  const d = Math.min(w, h - labelSize * 1.6) * 0.92; // the ring, with room left for the label
  const sw = d * 0.12;
  const r = (d - sw) / 2;
  const len = 2 * Math.PI * r;
  const numSize = fit(`${fmt(pct)}%`, r * 1.3, r * 0.7, FONTS.sans, 900); // sized at the final text
  return (
    <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
      <div style={{ position: "relative", width: d, height: d }}>
        <svg width={d} height={d} style={{ position: "absolute", inset: 0 }}>
          <defs>
            <linearGradient id={gid} x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor={color} />
              <stop offset="1" stopColor={theme.gold} />
            </linearGradient>
          </defs>
          <circle cx={d / 2} cy={d / 2} r={r} fill="none" stroke={ink.faint} strokeWidth={sw} />
          <circle cx={d / 2} cy={d / 2} r={r} fill="none" stroke={`url(#${gid})`} strokeWidth={sw} strokeLinecap="round"
            strokeDasharray={len} strokeDashoffset={len * (1 - (pct / 100) * t)} transform={`rotate(-90 ${d / 2} ${d / 2})`} />
        </svg>
        <div style={{
          position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: FONTS.sans,
          fontWeight: 900, fontSize: numSize, color: ink.ink, fontVariantNumeric: "tabular-nums", whiteSpace: "pre",
        }}>{`${fmt(pct * t)}%`}</div>
      </div>
      {label ? (
        <div style={{ fontFamily: FONTS.sans, fontWeight: 800, fontSize: labelSize, color: ink.ink, marginTop: labelSize * 0.4, whiteSpace: "pre" }}>{label}</div>
      ) : null}
    </div>
  );
}
```

```json
{"name": "RingStat", "description": "A ring that fills to a percentage, the number counting up inside it, a label under it.",
 "props": {"type": "object", "additionalProperties": false, "required": ["pct"],
           "properties": {"pct": {"type": "number", "minimum": 0, "maximum": 100},
                          "label": {"type": "string", "maxLength": 14},
                          "at": {"type": ["number", "string"], "description": "Time it starts filling: \"line:4\" or seconds from the clip start"},
                          "color": {"type": "string", "default": "accent", "description": "theme token or CSS"},
                          "ground": {"type": "string", "enum": ["light", "dark"], "default": "light"}}},
 "example": {"pct": 62, "label": "live in cities", "at": "line:4"}}
```

In meta.json, give every Time key the type `["number", "string"]` and every asset key the type `"string"`, and refuse
unknown keys (`"additionalProperties": false`) so a typo is caught at edit time.

## Stage kit

The stage kit (`renderer/src/kit/stage/`, exported from `@reelsmith/kit` by name) is for performance films: films in
which every narration line is acted out in code by drawn objects and torn photo cut-outs, instead of laid over a
still or a video. `examples/performance/` is a complete one; the manual's "Performance films" section gives the track
layout.

### The form

1. One `ground` clip runs the whole film (a `Stage` with a ground); one scene component per narration line (or per
   two short lines) sits on a `scenes` track with `"start": "line:N"`; a head text clip holds the take for at most
   4.5 s; captions come from the captions track, never from a component.
2. No image or video clip fills the frame. A picture appears only as a `Cut` (or a `Loupe` of one) inside a scene.
3. Cues come from the narration: `const { T } = useCues()`, then `T("word")`. Never type a time in a scene.
4. Something lands at least every 1.5 to 2 s, on the word that names it; start the move 2 to 6 frames before `T`.
5. Paper and cut-outs move at 12 poses a second (`step`, `Actor`); ink, mist and swings move on every frame.
6. Words on screen belong to objects (`Label`, `Tag`, `Stamp`, `Card`, `Sign`): 64 px or more, the film's key
   number 140 px or more, one new word per beat.
7. Lay out in the clip's own pixels (`useClip()` `w`, `h`); the hero object spans most of the safe box; keep text
   out of the caption band.
8. One language per scene: drawn objects (`Slab`, `Hand`, `Shelf`...) or cut-outs (`Cut`, `Loupe`, ink on the
   photo). A film may alternate them.

Every primitive is absolutely positioned in the clip's pixels and takes the clip frame from `useCurrentFrame()`
unless given `f`. Sizes left out scale with `useUnit()` (clip width / 1080; `72u` below means `72 * useUnit()`). Colours come from props or
`usePalette()`. Nothing uses `Date` or `Math.random`; randomness is seeded through remotion's `random`, so the same
`seed` draws the same tear, boil and stamp texture on every frame. Filter ids are per instance, so every primitive
also works outside a `Stage`. Each component's props type is exported as `<Name>Props` (`CutProps`,
`TableTopProps`...); `Actor`'s entrance and exit names are the types `Entrance` and `Exit`.

### Time

| export | |
|---|---|
| `useCues()` | `cues(useClip().lines, fps)`: the narration cues of the current clip |
| `cues(lines, fps = 30)` | `{T, at, end, S, lines, fps}` over `ClipLine[]` (type alias `CueLine`; result type `Cues`) |
| `T(word, off = 0, nth = 0)` | the frame the `nth` occurrence of `word` is said, across the clip's lines, plus `off` seconds. Placed by character position: every character of the line, punctuation included, takes an equal share of its time. Throws when the word (or that occurrence) is not in the lines |
| `at(i?)`, `end(i?)` | first and last frame of line `i` (its `line:N` number), or of the clip's first / last line; throw when missing |
| `S(sec)` | seconds to frames |
| `prog(f, a, len)` | 0..1 over `len` frames from `a`, held at both ends |
| `clamp01`, `lerp(a, b, t)` | |
| `out3(t)`, `in2(t)`, `inOut(t)`, `backOut(t, s = 1.9)` | easings on 0..1 (`backOut` overshoots) |
| `spr(f, at, cfg?)` | a bouncy `springAt` from `at` (damping 11, stiffness 170, mass 0.9 unless `cfg` says otherwise) |
| `wob(f, at, amp, hz = 1.6, decay = 2.2, fps = 30)` | a decaying shake after a hit |
| `swing(f, at, amp = 28, hz = 1.3, decay = 2.2, fps = 30)` | a damped pendulum in degrees, for things on a string |
| `step(f, rate = 12, fps = 30)` | the frame held at `rate` poses a second (stop motion) |
| `boil(seed, f, amp = 1, fps = 30)` | `[dx, dy]` hand-made jitter that changes 12 times a second |
| `win(f, a, b, inLen = 6, outLen = 6)` | 0..1 envelope: in from `a`, held, out at `b` |

`wob`, `swing`, `step` and `boil` assume 30 fps: pass `fps` from `useClip()` on other profiles.

### Geometry, palette and units

| export | |
|---|---|
| `Pt` | `[x, y]` |
| `torn(pts, seed, amp = 7, seg = 16)` | a seeded torn-paper outline (SVG path) through a polygon |
| `bbox(pts)`, `rect(x, y, w, h)`, `circle(cx, cy, r, n = 28)` | bounds `{x, y, w, h}`; polygons |
| `smooth(pts)`, `smoothClosed(pts)` | Catmull-Rom paths through points (open, closed) |
| `blob(cx, cy, rx, ry, seed, n = 12, jit = 0.12)` | an organic closed shape with a flat bottom |
| `roughRect(x, y, w, h, rad, seed, jit = 0.012)` | a slightly uneven rounded rectangle |
| `fibre(x0, x1, y, amp, seed, n = 6)` | a wavy line |
| `along(pts, t)` | the point at fraction `t` of a polyline's length |
| `mixColor(a, b, k)`, `seedInt(seed, max = 997)` | |
| `usePalette()` | tokens `ink paper kraft kraftDeep kraftLight red lemon accent wood woodDeep wall wallDeep shadow steel` (type `Palette`); `accent` is the theme's, and a `<Stage palette>` overrides any of them. `PALETTE` holds the defaults, `PaletteContext` carries an override |
| `useUnit()` | clip width / 1080 |
| `shadowCss(lift = 0, color?)` | a CSS drop-shadow for an object `lift` (0..1) off the page |
| `shades(base)` | `{base, hi, deep, rim}` |
| `useFilters(softPx = 9, blurPx = 14)` | `{id, soft, blur, defs}`: per-instance soft-edge and blur filters |

### Stage and grounds

| export | |
|---|---|
| `<Stage cam? ground? grain = 0.06 grainFps = 0 light = 0.5 vignette = 0.45 drift = 0 palette? f?>` | fills the clip: a ground (a node, painted on a depth-0.55 layer, or a CSS colour), the children, warm light from the top left, a vignette and faint grain. `drift` is a slow idle sway in px. A scene over a `ground` clip uses `grain={0} light={0} vignette={0}` and no ground, so it stays transparent |
| `<Layer depth = 1 blur = 0 opacity = 1>` | a plane of the stage: under 1 lags behind the camera, over 1 runs ahead; parallax on x, y and zoom |
| `Key`, `camAt(keys, f)` | camera keys `{at, x, y, z, dip?}` (frame, the point at the frame centre, zoom, a zoom-out mid-move); `camAt` gives `{x, y, z}` (type `Cam`) |
| `useStage()` | `{cam, w, h, f}` of the enclosing stage |
| `<Grain w h amount fps f>` | the grain alone; static unless `fps` > 0 (at most 6), `amount` at most 0.2 |
| `<KraftGround color? fibres = 170 seed pad = 0.25>` | brown paper with fibres and warm light; `pad` draws past the edges so camera moves never show a border |
| `<WallGround color? deep? awning? bay = 620 x0? x1? lamps = true seed pad>` | a wall of shelf bays and posts, an optional striped awning `[c1, c2]`, swaying lamps |
| `<TableTop top? kind = "wood" \| "kraft" \| "cloth" color? x0? x1? seed pad>` | fills the frame below `top` (default 0.62 h) with a table seen from the front, so the lower frame is never bare |

### Actors

| export | |
|---|---|
| `Placed` | `{poly, x, y, s?, r?}`: an outline in source pixels, its centre on the canvas, scale, rotation (deg) |
| `<Cut src poly x y s? r? seed imgW? imgH? lift? opacity? keyline = 9 amp = 7 tint? photo? over? free? z? edge?>` | a torn cut-out of `poly` from a picture (an `*_asset` prop or a URL) with a paper keyline and a shadow by `lift`; `photo` is a CSS filter on the photo; `over` (clipped) and `free` draw on it in source pixels. Throws when the picture size is unknown: an asset ref carries it, a URL needs `imgW`/`imgH` |
| `toCanvas(piece, pt)` | where a source pixel of a placed piece lands on the canvas: pens, circles and loupes follow real detail with it |
| `<Loupe src imgW? imgH? at x y r? zoom = 1.9 piece? p = 1 seed ring?>` | a round chip of the same picture enlarged around source point `at`, at canvas `(x, y)`; with `piece`, a leader line runs from the detail; `p` 0..1 pops it in |
| `<Magnifier x y r? ang = 35 zoom = 1.9 focus? back? children>` | a magnifying glass showing its children (canvas coordinates) enlarged |
| `<Actor at leave? from = "drop" to = "fade" inLen = 8 outLen = 7 ox? oy? stop = true idle = 0 seed f?>` | wraps any child in an entrance (`drop left right up slap grow fade`), an idle boil and an exit (`left right up down shrink fade`); draws nothing before `at` or once it has left; `ox, oy` is the pivot |

### Paper

| export | |
|---|---|
| `<Label x y text size = 72u seed r? s? sub? bg? color? font? lift? opacity? padX? peel? at? f? z?>` | a sticker sized to its text, centred on `(x, y)`; with `at` it slaps on at that frame; `peel` 0..1 peels it off |
| `<Tag x y text unit? ang = 0 s = 1 circle = 0 tear = 0 split = 0 w? h? color? opacity?>` | a manila tag hanging from a pin at `(x, y)`, one big word or number (150 px at the default size) and a unit; `circle`, `tear`, `split` 0..1 loop it in red, crack it and pull it apart; sway it with `swing` |
| `<Stamp x y text at sub? round = false r = -8 size = 78u color? seed fade = 1 f?>` | an ink stamp thumped down at `at`; the seed sets the ink texture |
| `<Tape x y seed w? r = 0 opacity color?>` | a strip of masking tape |
| `<Card x y a b flip = 0 w? h? size = 84u color? back? r? seed>` | a stiff card that flips from word `a` to word `b` as `flip` goes 0 to 1 |

### Ink (`p` is 0..1 drawn)

| export | |
|---|---|
| `<Marker d p color? w? seed opacity jitter = 1.2 dash? blend? f?>` | a felt-pen stroke along an SVG path in canvas px (red, 10u wide by default) |
| `<Highlighter ...>` | a Marker 34u wide in lemon, multiplied at 0.8 opacity |
| `<Stroke d clip? p color? w? opacity = 0.92>` | a wide paint stroke kept inside the `clip` path |
| `<CircleIt x y w h p color? sw? seed f?>` | a hand-drawn loop around a point |
| `<ArrowInk from to p color? w? bend = 0.22 seed f?>` | a drawn arrow between two points |

### Effects

| export | |
|---|---|
| `<Mist x y age dir = 180 color n = 46 life = 34 speed = 1 seed>` | a puff of spray leaving `(x, y)` `age` frames ago, travelling `dir` degrees (180 = left, 270 = up) |
| `<Wisps x y k n = 3 spread? color f?>` | curls of steam or smell rising, `k` 0..1 how far |
| `<Drips x y w age n = 5 len? color? seed>` | drips running down from an edge |
| `<Sparks x y age n = 14 life = 14 reach? color? seed>` | a burst of sparks |

### Things

Drawn objects on one material recipe: a gradient body, a darker side, a rim light, a soft ground shadow and seeded
specks. All sizes have defaults relative to the clip width.

| export | |
|---|---|
| `<Slab x y w h shape = "blob" \| "round" \| "rect" color? depth = 0.34 r = 0 seed sheen = 0 detail?>` | any solid on a surface (a pile, a block, a stack); `(x, y)` is the centre of its top face |
| `<Hand x y ang = 0 pose = "point" len = 520 s? glove sleeve seed>` | a gloved hand on a sleeve; `(x, y)` is the fingertip (`point`), the pinch (`pinch`) or the palm (`open`); `ang` 0 points left, 90 up, 180 right, -90 down (type `HandPose`) |
| `<Wheel x y r? roll = 0 color? tyre? spokes = 6>` | a wheel turned by `roll` |
| `<Sign x y text ang = 0 size? hang? color? textColor? font = "serif" seed>` | a board hanging from a pin at `(x, y)` |
| `<Shelf x y w? h? rows = 3 stock = true color? seed items?>`, `shelfBoards(y, h, rows = 3)` | a shelf unit standing on `(x, y)`; `shelfBoards` gives the board tops to stand `items` on |
| `<Phone x y w? r? color? screen? glass?>` | a phone; `screen` is an HTML node shown on it |
| `<Note x y w? r? value = "100" color? count = 1 seed>` | a banknote of no real currency, `count` in a stack |
| `<Parcel x y w? h? d? color? tape? label? seed>` | a box; `(x, y)` is its front-bottom centre |
| `<Doc x y w? h? r? title? lines = 7 p = 1 stamp? color? seed>` | a document, its lines written in by `p`, an optional stamp |
| `<Car x y w? color? roll = 0 flip = false seed>` | a car standing on `(x, y)` |

### A complete scene

The cut-out scene of `examples/performance/` (`library/components/SaltGlass.tsx`), on the clip
`{"type": "component", "name": "SaltGlass", "start": "line:3", "end": "end", "props": {"photo_asset": "glass"}}`
over the film's `ground` clip. The line is "So every litre of seawater holds about thirty-five grams of salt."

```tsx
import React from "react";
import { useCurrentFrame } from "remotion";
import { Actor, CircleIt, Cut, Label, Loupe, Marker, prog, swing, Tag, Tape, toCanvas, useClip, useCues } from "@reelsmith/kit";
import type { Placed, Pt } from "@reelsmith/kit";

// outline in glass.jpg source pixels (232 x 338; read off an AssetGrid preview): the glass and the salt beside it
const GLASS: Pt[] = [[38, 66], [192, 66], [188, 236], [214, 232], [232, 242], [232, 316], [160, 320], [48, 302], [40, 250]];
const SALT: Pt = [205, 276];
const WATER: Pt[] = [[50, 124], [90, 119], [130, 126], [182, 121]];

export default function SaltGlass({ props }: { props: any }) {
  const f = useCurrentFrame();
  const { w } = useClip();
  const { T } = useCues();
  const piece: Placed = { poly: GLASS, x: w * 0.42, y: 840, s: 2.55, r: -3 };
  const salt = toCanvas(piece, SALT);
  const wave = WATER.map((pt) => toCanvas(piece, pt));
  return (
    <>
      <Actor at={0} from="slap" ox={piece.x} oy={piece.y}>
        <Cut src={props.photo_asset} seed="glass" {...piece} lift={0.15} photo="saturate(1.1) contrast(1.05)" />
        <Tape x={piece.x - 40} y={470} w={220} r={-8} seed="tape" />
      </Actor>
      <Marker d={"M" + wave.map((p) => p.join(" ")).join(" L")} p={prog(f, T("seawater") - 3, 12)} w={12} seed="water" />
      <Label x={300} y={420} text="1 litre" r={-5} seed="litre" at={T("litre") - 2} />
      <CircleIt x={salt[0]} y={salt[1]} w={210} h={150} p={prog(f, T("salt") - 6, 12)} />
      <Loupe src={props.photo_asset} at={SALT} x={880} y={1160} r={120} zoom={3.4} piece={piece} p={prog(f, T("grams") - 4, 10)} seed="lp" />
      {f >= T("thirty") - 4 ? <Tag x={790} y={300} ang={swing(f, T("thirty") - 4, 26)} text="35" unit="grams" /> : null}
    </>
  );
}
```

Its meta.json declares `photo_asset` as `{"type": "string"}`. Re-recording the voice moves every cue with it; a word
that is no longer said makes `T` throw, and `preview` shows the error in the clip's place.

### Size and render cost

- Grain is static by default. Grain or texture that changes on every frame over the whole picture multiplies the
  file size (a 30 s film with a per-frame grain overlay came out at 71 MB); keep `grainFps` at 6 or less.
- Aim for 8 Mb/s or less: a 60 s vertical film should stay well under 80 MB. The example renders 13 s at 1080 x 1920
  to about 6 MB in under a minute.
- Paint the ground once, in the `ground` clip; scenes draw no ground, light, vignette or grain of their own.
- A cut-out is one `<Img>` under a CSS clip-path: cheap. Many large blurred filters (`Mist` with a high `n`, a
  blurred `Layer`) cost the most render time; keep them to the moments that need them.
- Text the kit draws is real DOM or SVG text, measured by the layout pass like any other: keep it inside the safe
  area and readable against what is behind it.

### Tracing a cut-out: AssetGrid

`reelsmith preview` cannot overlay a grid on an asset, so the built-in preset `AssetGrid` does: a component clip
with the full canvas box and `{"asset": "<image id>"}` (optional `cols`, `rows`, 2 to 40, default 10) shows the
picture whole on a dark ground under a labelled grid, every fifth line yellow, with the source image's pixel
coordinates on all four edges (fractions when the size is unknown). Preview it once per picture, read the outline's
points off it (10 to 14 points are enough), write them into the scene as `Pt[]` and remove the clip. It is a
tracing aid, not film content; its labels are not measured as film text.
