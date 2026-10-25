# @reelsmith/kit

Everything a component may import from `@reelsmith/kit`, how its props arrive, and a complete component to start
from. The source is `renderer/src/kit/` (`index.ts` lists the exports, `helpers.ts` holds most of them); the built-in
presets in `renderer/src/presets/` are fuller examples (`library(p, "Receipt")` prints a preset's source path).

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
  keep it at 40 px or more on the 1080-wide canvas (the layout check warns under 28 px; render refuses under 20 px). Use
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
| `asset`, `*_asset` | an asset id | `{src, kind, size?, box?, site?, duration?}`; an unknown id arrives as the string |

The asset ref: `src` a project-relative path (give it to `assetSrc` or `Media`), `kind` `"image" | "video" | "audio" |
"evidence"`, `size` `[w, h]` pixels (images and evidence), `box` `[x, y, w, h]` the proving sentence in capture
pixels (evidence; captures are 3× a phone page), `site` the page's site (evidence), `duration` seconds (video, audio).

## useClip()

`const { w, h, dur, fps, theme, width, height, safe, progress } = useClip();`

| field | |
|---|---|
| `w`, `h` | the clip box now, in canvas px (keyframed `w`/`h` included) |
| `dur` | the clip's length in frames |
| `fps` | frames per second (30) |
| `theme` | the theme's colours: `paper`, `ink`, `night`, `snow`, `accent`, `gold`, `good`, `bad`, `muted` (CSS hex) |
| `width`, `height` | the canvas (1080 × 1920) |
| `safe` | the platform's UI-safe area `{x, y, w, h}` in canvas px |
| `progress` | 0..1: the clip's `progress` keyframes if it has them, else how far through the clip it is |

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
| `fontFamily(name)` | a `FONTS` key to its CSS family; anything else passes through (empty: sans) | `fontFamily(props.font)` |
| `fit(text, width, max, family = "sans", weight = 400)` | the largest font size ≤ `max` at which `text` fits `width` on one line | `fit(label, w * 0.9, 64, FONTS.sans, 800)` |
| `fitLines(text, width, max, min = 0, family = "sans", weight = 400)` | `{size, lines}`: one line, or two (`twoLines`) when one line would be under `min` and two fit larger; render `lines.join("\n")` with `whiteSpace: "pre"` | `const { size, lines } = fitLines(label, w * 0.6, 56, 28, FONTS.sans, 800)` |
| `textWidth(text, size, family = "sans", weight = 400, tabular = false)` | width in px of one line; `tabular` measures digits as `fontVariantNumeric: "tabular-nums"` | `textWidth(fmt(value), size, FONTS.sans, 900, true)` |
| `twoLines(text, maxOne = 9)` | at most two balanced lines, split where the text clip may break (Intl.Segmenter "zh" words: never inside a word, a number, a number and its unit, or before closing punctuation), after punctuation when one is near the middle; texts of `maxOne` characters or fewer stay whole | `twoLines("报名百日挑战", 4)` → `["报名", "百日挑战"]` |
| `breakLines(text, width, measure, balance = false)` | `text` in as many lines as it needs at `width`, by the text clip's own rules; `measure(s)` gives a string's width; `balance` evens the lines out | `breakLines(note, w, (s) => textWidth(s, 40, FONTS.sans, 700), true)` |
| `words(text)` | word segments (Intl.Segmenter "zh"), spaces included; joined they give the text | `words("今天的天气很好")` → `["今天", "的", "天气", "很好"]` |
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
| `Media` | an image or video asset filling its parent, `fit` cover/contain around a `focus`, an optional slow `motion` (`push`, `pull`, `pan_left`, `pan_right`, `rise`, `still`), `dim` 0..1 veil; video: `trimIn` (frames), `rate`, `loop`, `volume`, `volumeKeys` (a volume curve, frames from the clip start), `fadeIn`/`fadeOut` (frames) | `<Media media={props.photo_asset} motion="push" dim={0.3} />` |
| `EvidenceCrop` | the evidence clip's own crop in a `w × h` window: the proving sentence scaled to the window's width (at most 2×) with up to `context` capture px of page above and below, in a panel that hugs that content (centred); where it cuts into the page it fades into `background` (white); optional `highlight` `{at, dur (frames), color}` sweep | `<EvidenceCrop ev={props.asset} w={w} h={300} highlight={{ at: 10, dur: 24 }} />` |
| `evidenceLayout(ev, w, h, context?)` | where `EvidenceCrop` puts things, or null: `s` (capture px → window px), `mark` (the sentence), `panel` (the part of the window the content fills), `fade`, all in window px | `const { panel } = evidenceLayout(ev, w, 400, 120)!` |

### Context and types

`useClip()` (above); `ClipContext` (the React context behind it, for test harnesses); types `ClipCtx`, `AssetRef`,
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
 "example": {"pct": 62, "label": "城镇居民占比", "at": "line:4"}}
```

In meta.json, give every Time key the type `["number", "string"]` and every asset key the type `"string"`, and refuse
unknown keys (`"additionalProperties": false`) so a typo is caught at edit time.
